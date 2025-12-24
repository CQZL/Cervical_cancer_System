#!/usr/bin/env python3
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from revui.wsi_pipeline import (
    ConvNeXtEncoder,
    EncoderConfig,
    PipelineConfig,
    RetinaNetDetector,
    DetectorConfig,
    WSIConfig,
    WSIFeaturePipeline,
)
from revui.wsi_pipeline.pipeline import save_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WSI -> cell instance feature extraction")
    parser.add_argument("--wsi", type=str, help="Path to a single WSI file")
    parser.add_argument("--wsi-list", type=str, help="Text file with list of WSI paths")
    parser.add_argument("--out-dir", type=str, required=True, help="Output directory for .pt files")
    parser.add_argument("--det-ckpt", type=str, required=True, help="RetinaNet checkpoint path")
    parser.add_argument("--enc-ckpt", type=str, required=True, help="ConvNeXt checkpoint path")
    parser.add_argument("--tile-size", type=int, default=2048)
    parser.add_argument("--stride", type=int, default=2048)
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--downsample", type=float, default=None)
    parser.add_argument("--patch-size", type=int, default=256)
    parser.add_argument("--det-thres", type=float, default=0.25)
    parser.add_argument("--det-nms", type=float, default=0.5)
    parser.add_argument("--det-num-classes", type=int, default=2)
    parser.add_argument("--min-area", type=float, default=None)
    parser.add_argument("--max-area", type=float, default=None)
    parser.add_argument("--enc-arch", type=str, default="convnext_tiny")
    parser.add_argument("--enc-num-classes", type=int, default=2)
    parser.add_argument("--enc-positive-index", type=int, default=1)
    parser.add_argument("--mean", type=float, nargs=3, default=None)
    parser.add_argument("--std", type=float, nargs=3, default=None)
    parser.add_argument("--padding-mode", type=str, default="reflect", choices=["reflect", "constant"])
    parser.add_argument("--dedup-grid", type=int, default=64)
    parser.add_argument("--dedup-none", action="store_true")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", type=str, default="cuda:0")
    parser.add_argument("--prob-format", type=str, default="positive", choices=["positive", "all"])
    parser.add_argument("--save-index", action="store_true")
    return parser.parse_args()


def resolve_wsi_list(args: argparse.Namespace) -> List[str]:
    if args.wsi:
        return [args.wsi]
    if args.wsi_list:
        wsi_paths = []
        with open(args.wsi_list, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    wsi_paths.append(line)
        return wsi_paths
    raise ValueError("Either --wsi or --wsi-list must be provided")


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for ckpt in [args.det_ckpt, args.enc_ckpt]:
        if not Path(ckpt).exists():
            raise FileNotFoundError(f"Checkpoint not found: {ckpt}")
    wsi_paths = resolve_wsi_list(args)
    wsi_config = WSIConfig(tile_size=args.tile_size, stride=args.stride, level=args.level, downsample=args.downsample)
    detector_config = DetectorConfig(
        score_threshold=args.det_thres,
        nms_threshold=args.det_nms,
        min_area=args.min_area,
        max_area=args.max_area,
        num_classes=args.det_num_classes,
    )
    encoder_config = EncoderConfig(
        arch=args.enc_arch,
        num_classes=args.enc_num_classes,
        mean=args.mean,
        std=args.std,
        positive_index=args.enc_positive_index,
    )
    pipeline_config = PipelineConfig(
        patch_size=args.patch_size,
        padding_mode=args.padding_mode,
        dedup_grid=None if args.dedup_none else args.dedup_grid,
        batch_size=args.batch_size,
        prob_format=args.prob_format,
    )
    detector = RetinaNetDetector(args.det_ckpt, args.device, detector_config)
    encoder = ConvNeXtEncoder(args.enc_ckpt, args.device, encoder_config)
    pipeline = WSIFeaturePipeline(detector, encoder, pipeline_config)
    out_dir = Path(args.out_dir)
    for wsi_path in wsi_paths:
        outputs = pipeline.run_on_slide(wsi_path, wsi_config)
        slide_id = Path(wsi_path).stem
        out_path = out_dir / f"{slide_id}.pt"
        metadata = None
        if args.save_index:
            metadata = {
                "slide_id": slide_id,
                "wsi_path": wsi_path,
                "num_instances": int(outputs["feats"].shape[0]),
                "det_threshold": args.det_thres,
                "tile_size": args.tile_size,
                "patch_size": args.patch_size,
                "timestamp": int(time.time()),
            }
        save_outputs(outputs, out_path, metadata)


if __name__ == "__main__":
    main()
