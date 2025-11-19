from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

@dataclass
class Patch:
    patch_id: str
    tif_id: str
    tile_id: str
    x: int
    y: int
    w: int
    h: int
    score: float
    label: str
    tile_path: Optional[Path] = None
    thumb_path: Optional[Path] = None
    orig_label: Optional[str] = None          # ← 新增：原始类别，用于“未复核”判断
    extra: Dict = field(default_factory=dict)

@dataclass
class SlideMeta:
    tif_id: str
    slide_pred_label: Optional[str] = None
    slide_pred_scores: Dict[str, float] = field(default_factory=dict)
    source_priority: list[str] = field(default_factory=list)

@dataclass
class ChangeRecord:
    patch_id: str
    old_label: str
    new_label: str
    reviewer: str
    timestamp: str
