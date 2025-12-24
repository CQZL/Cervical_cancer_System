import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import torch

from .detector import DetectorConfig, RetinaNetDetector
from .encoder import ConvNeXtEncoder, EncoderConfig
from .types import Det, Tile
from .wsi_reader import WSIConfig, WSIReader

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    patch_size: int = 256
    padding_mode: str = "reflect"
    dedup_grid: Optional[int] = 64
    batch_size: int = 64
    prob_format: str = "positive"


class WSIFeaturePipeline:
    def __init__(
        self,
        detector: RetinaNetDetector,
        encoder: ConvNeXtEncoder,
        config: PipelineConfig,
    ) -> None:
        self.detector = detector
        self.encoder = encoder
        self.config = config

    @staticmethod
    def _crop_patch(
        image: np.ndarray,
        center_x: float,
        center_y: float,
        patch_size: int,
        padding_mode: str,
    ) -> np.ndarray:
        half = patch_size // 2
        x1 = int(round(center_x - half))
        y1 = int(round(center_y - half))
        x2 = x1 + patch_size
        y2 = y1 + patch_size
        pad_left = max(0, -x1)
        pad_top = max(0, -y1)
        pad_right = max(0, x2 - image.shape[1])
        pad_bottom = max(0, y2 - image.shape[0])
        x1_clamped = max(0, x1)
        y1_clamped = max(0, y1)
        x2_clamped = min(image.shape[1], x2)
        y2_clamped = min(image.shape[0], y2)
        cropped = image[y1_clamped:y2_clamped, x1_clamped:x2_clamped]
        if any([pad_left, pad_right, pad_top, pad_bottom]):
            pad_width = (
                (pad_top, pad_bottom),
                (pad_left, pad_right),
                (0, 0),
            )
            if padding_mode == "reflect":
                cropped = np.pad(cropped, pad_width, mode="reflect")
            else:
                cropped = np.pad(cropped, pad_width, mode="constant", constant_values=0)
        return cropped

    def _dedup_key(self, coord: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        if self.config.dedup_grid is None:
            return None
        grid = self.config.dedup_grid
        return (coord[0] // grid, coord[1] // grid)

    def _run_detector(self, tiles: Iterable[Tile]) -> List[Tuple[Det, np.ndarray, Tuple[int, int], Tuple[float, float, float, float]]]:
        candidates = []
        for tile in tiles:
            dets = self.detector.detect(tile)
            for det in dets:
                x1, y1, x2, y2 = det.bbox
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                patch = self._crop_patch(tile.image, cx, cy, self.config.patch_size, self.config.padding_mode)
                global_x = int(round(det.tile_x0 + cx))
                global_y = int(round(det.tile_y0 + cy))
                bbox_global = (
                    float(det.tile_x0 + x1),
                    float(det.tile_y0 + y1),
                    float(det.tile_x0 + x2),
                    float(det.tile_y0 + y2),
                )
                candidates.append((det, patch, (global_x, global_y), bbox_global))
        return candidates

    def _apply_dedup(
        self,
        candidates: List[Tuple[Det, np.ndarray, Tuple[int, int], Tuple[float, float, float, float]]],
    ) -> List[Tuple[Det, np.ndarray, Tuple[int, int], Tuple[float, float, float, float]]]:
        if self.config.dedup_grid is None:
            return candidates
        best: Dict[Tuple[int, int], Tuple[Det, np.ndarray, Tuple[int, int], Tuple[float, float, float, float]]] = {}
        for candidate in candidates:
            det, patch, coord, bbox = candidate
            key = self._dedup_key(coord)
            if key not in best or det.score > best[key][0].score:
                best[key] = candidate
        return list(best.values())

    def run_on_slide(self, wsi_path: str, wsi_config: WSIConfig) -> Dict[str, torch.Tensor]:
        start_time = time.time()
        reader = WSIReader(wsi_path, wsi_config)
        slide_id = reader.get_slide_id()
        logger.info("Processing slide %s", slide_id)
        tiles = list(reader.iter_tiles())
        logger.info("Tiles: %d", len(tiles))
        candidates = self._run_detector(tiles)
        logger.info("Detections: %d", len(candidates))
        candidates = self._apply_dedup(candidates)
        logger.info("Instances after dedup: %d", len(candidates))
        if not candidates:
            logger.warning("No detections found for slide %s", slide_id)
        patches = [cand[1] for cand in candidates]
        feats_list: List[torch.Tensor] = []
        probs_list: List[torch.Tensor] = []
        coords: List[Tuple[int, int]] = []
        det_scores: List[float] = []
        bboxes: List[Tuple[float, float, float, float]] = []
        if patches:
            for idx in range(0, len(patches), self.config.batch_size):
                batch = patches[idx : idx + self.config.batch_size]
                feats, probs = self.encoder.encode(batch)
                feats_list.append(feats)
                probs_list.append(probs)
        for det, _, coord, bbox in candidates:
            coords.append(coord)
            det_scores.append(det.score)
            bboxes.append(bbox)
        if feats_list:
            feats = torch.cat(feats_list, dim=0)
            probs = torch.cat(probs_list, dim=0)
        else:
            feats = torch.empty((0, self.encoder.feature_dim), dtype=torch.float32)
            probs = torch.empty((0,), dtype=torch.float32)
        coords_tensor = torch.tensor(coords, dtype=torch.int64) if coords else torch.empty((0, 2), dtype=torch.int64)
        det_scores_tensor = torch.tensor(det_scores, dtype=torch.float32) if det_scores else torch.empty((0,), dtype=torch.float32)
        bboxes_tensor = (
            torch.tensor(bboxes, dtype=torch.float32) if bboxes else torch.empty((0, 4), dtype=torch.float32)
        )
        if self.config.prob_format == "all":
            if probs.numel() > 0:
                probs = torch.stack([1 - probs, probs], dim=1)
            else:
                probs = torch.empty((0, 2), dtype=torch.float32)
        elapsed = time.time() - start_time
        logger.info("Finished %s in %.2fs", slide_id, elapsed)
        reader.close()
        return {
            "feats": feats,
            "probs": probs,
            "coords": coords_tensor,
            "det_scores": det_scores_tensor,
            "bboxes": bboxes_tensor,
        }


def save_outputs(
    outputs: Dict[str, torch.Tensor],
    out_path: Path,
    metadata: Optional[Dict[str, object]] = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(outputs, out_path)
    if metadata is not None:
        meta_path = out_path.with_suffix(".json")
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
