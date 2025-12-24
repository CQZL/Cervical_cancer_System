# WSI Stage-1 Feature Extraction Pipeline

This module provides an end-to-end pipeline that takes a cervical WSI (or tiles), runs RetinaNet detection on tiles, crops 256×256 cell patches from detection centers, and uses a ConvNeXt encoder to output per-cell embeddings + HSIL+ probabilities. The result is a `.pt` file per slide for Stage-2 MIL training/inference.

## Dependencies
- Python 3.8+
- `torch`, `torchvision`
- `openslide-python` (and system OpenSlide library)
- `numpy`

> If OpenSlide is not installed, WSI reading will fail with a clear error. Install OpenSlide first, then `pip install openslide-python`.

## Quick Start
Single WSI:
```bash
python CC_System/scripts/extract_wsi_features.py \
  --wsi /path/to/slide.svs \
  --out-dir /path/to/output \
  --det-ckpt /path/to/retinanet.pth \
  --enc-ckpt /path/to/convnext.pth \
  --device cuda:0
```

Batch WSI list:
```bash
python CC_System/scripts/extract_wsi_features.py \
  --wsi-list /path/to/wsi_list.txt \
  --out-dir /path/to/output \
  --det-ckpt /path/to/retinanet.pth \
  --enc-ckpt /path/to/convnext.pth
```

## CLI Parameters
- `--det-ckpt`: RetinaNet weight path (replaceable)
- `--enc-ckpt`: ConvNeXt weight path (replaceable)
- `--tile-size`: WSI tile size (default 2048)
- `--stride`: tile stride (default 2048)
- `--level` or `--downsample`: WSI reading level control
- `--patch-size`: cell patch size (default 256)
- `--det-thres`: detection score threshold (default 0.25)
- `--batch-size`: encoder batch size (default 64)
- `--device`: `cuda:0` or `cpu`
- `--dedup-grid`: grid size for de-duplication (default 64)
- `--dedup-none`: disable de-duplication
- `--prob-format`: `positive` (default, HSIL+ only) or `all`
- `--out-dir`: output directory

## Output Format
Each WSI produces `{out_dir}/{slide_id}.pt`:
- `feats`: `FloatTensor[M, D]` ConvNeXt embedding
- `probs`: `FloatTensor[M]` (HSIL+ probability) or `FloatTensor[M, 2]` if `--prob-format all`
- `coords`: `IntTensor[M, 2]` global center coordinates (x, y)
- `det_scores`: `FloatTensor[M]` detection scores
- `bboxes`: `FloatTensor[M, 4]` global detection boxes

Optional `{slide_id}.json` (when `--save-index`): slide metadata (instance count, thresholds, timestamp).

## FAQ
**WSI打不开 / 报 openslide 错误**
- 请确保系统 OpenSlide 已安装，并执行 `pip install openslide-python`。

**显存不足**
- 降低 `--batch-size`，或使用 `--device cpu`。

**输出为空（0 instances）**
- 降低 `--det-thres`，或确认检测权重是否匹配当前模型结构。

**阈值如何调**
- 检测阈值（`--det-thres`）影响候选数量；过高会漏检，过低会增加噪声。
- 可通过调整 `--dedup-grid` 降低重复检测。
