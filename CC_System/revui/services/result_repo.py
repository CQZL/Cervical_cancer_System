from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import List, Tuple, Optional

from revui.models.types import Patch, SlideMeta


class ResultRepo:
    def __init__(self, labels: List[str]):
        self.labels = labels

    def _find_file(self, result_dir: Path, base: str, exts=("json","csv")) -> Optional[Path]:
        for ext in exts:
            p = result_dir / f"{base}.{ext}"
            if p.exists():
                return p
        return None

    def load(self, result_dir: Path) -> Tuple[List[Patch], SlideMeta]:
        det_path = self._find_file(result_dir, "detections")
        slide_meta_path = self._find_file(result_dir, "slide_meta")
        tiles_dir = result_dir / "tiles"
        thumbs_dir = result_dir / "tiles"

        if det_path is None:
            raise FileNotFoundError(f"Missing detections.(json|csv) under {result_dir}")
        patches = self._load_detections(det_path, tiles_dir, thumbs_dir)

        meta = SlideMeta(tif_id=patches[0].tif_id if patches else result_dir.name)
        if slide_meta_path and slide_meta_path.exists():
            meta = self._load_slide_meta(slide_meta_path, meta.tif_id)

        return patches, meta

    def _load_detections(self, p: Path, tiles_dir: Path, thumbs_dir: Path) -> List[Patch]:
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            rows = data if isinstance(data, list) else data.get("detections", [])
        else:
            rows = []
            with p.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f); rows.extend(reader)

        patches: List[Patch] = []
        for i, r in enumerate(rows):
            get = lambda k, d=None: r.get(k) if isinstance(r, dict) else None
            tif_id = str(get("tif_id") or get("slide_id") or "")
            tile_id = str(get("tile_id") or i)
            x = int(float(get("x", 0))); y = int(float(get("y", 0)))
            w = int(float(get("w", 0))); h = int(float(get("h", 0)))
            score = float(get("score", 0)); label = str(get("label") or "ASCUS")
            tile_rel = get("tile_path")
            patch_id = f"{tif_id}:{tile_id}:{i}"
            tile_path = Path(tile_rel) if tile_rel else (tiles_dir / f"{tile_id}.png")
            thumb_path = tile_path
            patches.append(Patch(
                patch_id=patch_id, tif_id=tif_id, tile_id=tile_id,
                x=x, y=y, w=w, h=h, score=score, label=label,
                tile_path=tile_path, thumb_path=thumb_path, orig_label=label,
                extra=r
            ))
        return patches

    def _load_slide_meta(self, p: Path, tif_id_fallback: str) -> SlideMeta:
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            tif_id = data.get("tif_id", tif_id_fallback)
            return SlideMeta(
                tif_id=tif_id,
                slide_pred_label=data.get("slide_pred_label"),
                slide_pred_scores=data.get("slide_pred_scores", {}),
                source_priority=data.get("source_priority", []),
            )
        else:
            with p.open("r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                return SlideMeta(tif_id=tif_id_fallback)
            r = rows[0]
            scores = {k.replace("score_", ""): float(v) for k, v in r.items() if k.startswith("score_")}
            return SlideMeta(
                tif_id=r.get("tif_id", tif_id_fallback),
                slide_pred_label=r.get("slide_pred_label"),
                slide_pred_scores=scores,
                source_priority=[],
            )

    def save_reviewed(self, out_dir: Path, patches: List[Patch], meta: SlideMeta, changes: List[dict]):
        out_dir.mkdir(parents=True, exist_ok=True)
        det_csv = out_dir / "detections_reviewed.csv"
        with det_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "tif_id","tile_id","patch_id","x","y","w","h","score","label","tile_path","orig_label"
            ])
            writer.writeheader()
            for p in patches:
                writer.writerow({
                    "tif_id": p.tif_id, "tile_id": p.tile_id, "patch_id": p.patch_id,
                    "x": p.x, "y": p.y, "w": p.w, "h": p.h, "score": p.score,
                    "label": p.label, "tile_path": str(p.tile_path) if p.tile_path else "",
                    "orig_label": p.orig_label or ""
                })
        (out_dir / "slide_meta_reviewed.json").write_text(
            json.dumps({
                "tif_id": meta.tif_id,
                "slide_pred_label": meta.slide_pred_label,
                "slide_pred_scores": meta.slide_pred_scores,
                "source_priority": meta.source_priority,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "changes.log.json").write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
