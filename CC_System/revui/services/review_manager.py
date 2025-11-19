from __future__ import annotations
from typing import List, Dict, Callable, Tuple, Set
from datetime import datetime
from revui.models.types import Patch, SlideMeta

class ReviewManager:
    def __init__(self, reviewer: str = "anonymous"):
        self._patches: List[Patch] = []
        self._meta: SlideMeta | None = None
        self._changes: List[Dict] = []
        self._undo_stack: List[Dict] = []
        self._redo_stack: List[Dict] = []
        self._hidden_ids: Set[str] = set()   # ← 软删除集合
        self.reviewer = reviewer

        self.on_changed: List[Callable[[], None]] = []
        self.on_undo_redo: List[Callable[[bool, bool], None]] = []

    def set_data(self, patches: List[Patch], meta: SlideMeta):
        self._patches = patches
        self._meta = meta
        self._changes.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._hidden_ids.clear()
        self._emit()

    def get_state(self) -> Tuple[List[Patch], SlideMeta, List[Dict]]:
        return self._patches, self._meta, self._changes

    def changes(self) -> List[Dict]:
        return list(self._changes)

    # --- 改类 ---
    def move_class(self, patch_id: str, new_label: str):
        p = self._find(patch_id)
        if not p or p.label == new_label:
            return
        rec = {
            "patch_id": patch_id,
            "old_label": p.label,
            "new_label": new_label,
            "reviewer": self.reviewer,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        p.label = new_label
        self._changes.append(rec)
        self._undo_stack.append(rec)
        self._redo_stack.clear()
        self._emit()

    # --- 软删除 / 恢复 ---
    def hide(self, patch_id: str):
        if patch_id in self._hidden_ids: return
        self._hidden_ids.add(patch_id)
        self._emit()

    def restore(self, patch_id: str):
        if patch_id in self._hidden_ids:
            self._hidden_ids.remove(patch_id)
            self._emit()

    def is_hidden(self, patch_id: str) -> bool:
        return patch_id in self._hidden_ids

    # --- 状态查询 ---
    def is_reviewed(self, p: Patch) -> bool:
        return (p.orig_label is not None) and (p.label != p.orig_label)

    # --- 撤销 / 重做 ---
    def undo(self):
        if not self._undo_stack:
            return
        rec = self._undo_stack.pop()
        p = self._find(rec["patch_id"])
        if p:
            p.label = rec["old_label"]
        self._redo_stack.append(rec)
        self._emit()

    def redo(self):
        if not self._redo_stack:
            return
        rec = self._redo_stack.pop()
        p = self._find(rec["patch_id"])
        if p:
            p.label = rec["new_label"]
        self._undo_stack.append(rec)
        self._emit()

    # --- 内部 ---
    def _find(self, patch_id: str) -> Patch | None:
        for p in self._patches:
            if p.patch_id == patch_id:
                return p
        return None

    def _emit(self):
        for cb in self.on_changed:
            cb()
        for cb in self.on_undo_redo:
            cb(bool(self._undo_stack), bool(self._redo_stack))
