from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Tuple
import json, csv, shutil, time
from revui.models.types import Patch, SlideMeta

class ExportService:
    def __init__(self, labels: List[str]):
        self.labels = labels

    def export_all(
        self,
        out_dir: Path,
        patches: List[Patch],
        changes: List[Dict],
        meta: SlideMeta,
        *,
        copy_tiles: bool = True,
        write_csv: bool = True,
        write_json: bool = False,
        only_changed: bool = False,
        include_hidden: bool = False,
        hidden_predicate = None,          # 可注入：hidden 判断函数(patch_id)->bool
    ):
        """
        导出复核结果：
        - detections_reviewed.(csv/json)
        - slide_meta_reviewed.json
        - changes.log.json
        - 可选：tiles_reviewed/<label>/... 物理拷贝
        - only_changed: 仅导出 label != orig_label 的项
        - include_hidden: 是否包含“隐藏（软删除）”的项
        - hidden_predicate: 回调，如果传入则以其返回 True 的样本视为隐藏
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        def _is_hidden(p: Patch) -> bool:
            if hidden_predicate is None:
                return False
            try:
                return bool(hidden_predicate(p.patch_id))
            except Exception:
                return False

        def _changed(p: Patch) -> bool:
            return (p.orig_label is not None) and (p.label != p.orig_label)

        # 过滤列表
        ex = []
        for p in patches:
            if not include_hidden and _is_hidden(p):
                continue
            if only_changed and (not _changed(p)):
                continue
            ex.append(p)

        # 写 detections_reviewed.csv
        if write_csv:
            csv_path = out_dir / "detections_reviewed.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "tif_id","tile_id","patch_id","x","y","w","h",
                    "score","label","tile_path","orig_label"
                ])
                w.writeheader()
                for p in ex:
                    w.writerow({
                        "tif_id": p.tif_id, "tile_id": p.tile_id, "patch_id": p.patch_id,
                        "x": p.x, "y": p.y, "w": p.w, "h": p.h,
                        "score": p.score, "label": p.label,
                        "tile_path": str(p.tile_path) if p.tile_path else "",
                        "orig_label": p.orig_label or "",
                    })

        # 写 detections_reviewed.json（可选）
        if write_json:
            js = []
            for p in ex:
                js.append({
                    "tif_id": p.tif_id, "tile_id": p.tile_id, "patch_id": p.patch_id,
                    "x": p.x, "y": p.y, "w": p.w, "h": p.h,
                    "score": p.score, "label": p.label,
                    "tile_path": str(p.tile_path) if p.tile_path else "",
                    "orig_label": p.orig_label or "",
                })
            (out_dir / "detections_reviewed.json").write_text(
                json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        # 写 slide_meta_reviewed.json
        (out_dir / "slide_meta_reviewed.json").write_text(
            json.dumps({
                "tif_id": meta.tif_id,
                "slide_pred_label": meta.slide_pred_label,
                "slide_pred_scores": meta.slide_pred_scores,
                "source_priority": meta.source_priority,
                "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 写 changes.log.json
        (out_dir / "changes.log.json").write_text(
            json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 可选：拷贝 tile 到 tiles_reviewed/<label>/
        if copy_tiles:
            base = out_dir / "tiles_reviewed"
            for p in ex:
                if not p.tile_path:
                    continue
                src = Path(p.tile_path)
                if not src.exists():
                    continue
                sub = base / p.label
                sub.mkdir(parents=True, exist_ok=True)
                fname = f"{p.tif_id}_{p.tile_id}_{p.patch_id.replace(':','_')}_{p.score:.2f}{src.suffix or '.png'}"
                dst = sub / fname
                # 同名覆盖
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    # 兜底：copy 而不带元数据
                    try:
                        shutil.copy(src, dst)
                    except Exception:
                        pass
