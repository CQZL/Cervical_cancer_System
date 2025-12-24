import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import torch
from torchvision import transforms
from torchvision.ops import nms
from torchvision.models.detection import retinanet_resnet50_fpn

from .types import Det, Tile

logger = logging.getLogger(__name__)


@dataclass
class DetectorConfig:
    score_threshold: float = 0.25
    nms_threshold: float = 0.5
    min_area: Optional[float] = None
    max_area: Optional[float] = None
    num_classes: int = 2


class RetinaNetDetector:
    def __init__(self, ckpt_path: str, device: str, config: DetectorConfig) -> None:
        if "cuda" in device and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU for detector")
            device = "cpu"
        self.device = torch.device(device)
        self.config = config
        self.model = retinanet_resnet50_fpn(num_classes=config.num_classes)
        self._load_checkpoint(ckpt_path)
        self.model.to(self.device)
        self.model.eval()
        self.transform = transforms.Compose([transforms.ToTensor()])

    def _load_checkpoint(self, ckpt_path: str) -> None:
        checkpoint = torch.load(ckpt_path, map_location="cpu")
        if isinstance(checkpoint, dict):
            state_dict = checkpoint.get("state_dict") or checkpoint.get("model_state_dict")
            if state_dict is None:
                state_dict = checkpoint
        else:
            state_dict = checkpoint
        cleaned = {k.replace("module.", ""): v for k, v in state_dict.items()}
        missing, unexpected = self.model.load_state_dict(cleaned, strict=False)
        if missing:
            logger.warning("Detector missing keys: %s", missing)
        if unexpected:
            logger.warning("Detector unexpected keys: %s", unexpected)

    @torch.inference_mode()
    def detect(self, tile: Tile) -> List[Det]:
        tensor = self.transform(tile.image).to(self.device)
        outputs = self.model([tensor])[0]
        boxes = outputs["boxes"].detach().cpu().numpy()
        scores = outputs["scores"].detach().cpu().numpy()
        labels = outputs["labels"].detach().cpu().numpy()
        keep = scores >= self.config.score_threshold
        boxes = boxes[keep]
        scores = scores[keep]
        labels = labels[keep]
        if boxes.size == 0:
            return []
        if self.config.nms_threshold is not None:
            keep_idx = nms(
                torch.tensor(boxes, dtype=torch.float32),
                torch.tensor(scores, dtype=torch.float32),
                self.config.nms_threshold,
            )
            boxes = boxes[keep_idx.numpy()]
            scores = scores[keep_idx.numpy()]
            labels = labels[keep_idx.numpy()]
        dets: List[Det] = []
        for bbox, score, cls in zip(boxes, scores, labels):
            x1, y1, x2, y2 = bbox
            area = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))
            if self.config.min_area is not None and area < self.config.min_area:
                continue
            if self.config.max_area is not None and area > self.config.max_area:
                continue
            dets.append(
                Det(
                    bbox=bbox.astype(np.float32),
                    score=float(score),
                    cls=int(cls),
                    tile_x0=tile.x0,
                    tile_y0=tile.y0,
                )
            )
        return dets
