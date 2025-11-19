from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List
import csv, json, yaml

class ResultLocator:
    """
    三策略定位顺序：
      a) 同名目录：<tif_dir>/<stem>_pred/ 或 <results_root>/<stem>/
      b) manifest：manifest.csv / results_index.json（tif_path -> result_dir）
      c) config 模板：result_root + patterns（可用 {stem}、{parent}）
    """
    def __init__(self, cfg_path: Path):
        self.cfg_path = Path(cfg_path)
        self.cfg = yaml.safe_load(self.cfg_path.read_text(encoding="utf-8"))
        io = self.cfg.get("io", {})
        self.results_root = Path(io.get("results_root", "./results")).resolve()
        self.manifest_path = io.get("manifest")  # 可为 str 或 None
        self.patterns: List[str] = io.get("patterns", ["{stem}_pred", "{stem}"])

    def locate(self, tif_path: Path) -> Optional[Path]:
        tif_path = Path(tif_path).resolve()
        stem = tif_path.stem
        parent = tif_path.parent

        # a) 同名目录（同级）
        cand = [
            parent / f"{stem}_pred",
            parent / stem,
        ]
        # a+) 同名目录（results_root 下）
        cand += [
            self.results_root / f"{stem}",
            self.results_root / f"{stem}_pred",
        ]
        for c in cand:
            if self._looks_like_result_dir(c):
                return c.resolve()

        # b) manifest
        mdir = self._from_manifest(tif_path)
        if mdir and self._looks_like_result_dir(mdir):
            return mdir.resolve()

        # c) 模板
        for pat in self.patterns:
            sub = pat.replace("{stem}", stem).replace("{parent}", parent.name)
            c = (self.results_root / sub)
            if self._looks_like_result_dir(c):
                return c.resolve()

        return None

    # 结果目录判定：存在 detections.(json|csv)
    def _looks_like_result_dir(self, d: Path) -> bool:
        if not d or not d.exists() or not d.is_dir():
            return False
        for nm in ("detections.json", "detections.csv"):
            if (d / nm).exists():
                return True
        return False

    def _from_manifest(self, tif_path: Path) -> Optional[Path]:
        # 优先 config 指定的 manifest
        if self.manifest_path:
            mp = Path(self.manifest_path)
            if mp.exists():
                p = self._read_manifest(mp, tif_path)
                if p:
                    return p
        # 其次：尝试在当前目录及上级目录查找
        for dir_try in [tif_path.parent, tif_path.parent.parent]:
            for name in ("manifest.csv", "results_index.json"):
                mp = dir_try / name
                if mp.exists():
                    p = self._read_manifest(mp, tif_path)
                    if p:
                        return p
        return None

    def _read_manifest(self, mp: Path, tif_path: Path) -> Optional[Path]:
        sp = str(tif_path.resolve())
        if mp.suffix.lower() == ".csv":
            with mp.open("r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if not row:
                        continue
                    k = (row.get("tif_path") or row.get("slide") or "").strip()
                    v = (row.get("result_dir") or row.get("results") or "").strip()
                    if not k or not v:
                        continue
                    # 绝对/相对兼容
                    if Path(k).resolve() == tif_path.resolve():
                        return Path(v)
        else:
            data = json.loads(mp.read_text(encoding="utf-8"))
            # 既支持 {tif_path: result_dir} 也支持 list[{"tif_path":..., "result_dir":...}]
            if isinstance(data, dict):
                for k, v in data.items():
                    if Path(k).resolve() == tif_path.resolve():
                        return Path(v)
            elif isinstance(data, list):
                for it in data:
                    k = it.get("tif_path") or it.get("slide")
                    v = it.get("result_dir") or it.get("results")
                    if k and v and Path(k).resolve() == tif_path.resolve():
                        return Path(v)
        return None
