from __future__ import annotations
from pathlib import Path
import yaml

from PySide6.QtCore import Qt, QSize, Signal, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QIcon, QPixmap, QAction, QKeySequence, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget, QListView, QAbstractItemView,
    QPushButton, QLabel, QLineEdit, QSlider, QComboBox, QCheckBox, QMessageBox
)

# ---- 领域/服务（与你项目保持一致）----
from revui.models.types import Patch, SlideMeta
from revui.services.result_locator import ResultLocator
from revui.services.result_repo import ResultRepo
from revui.services.review_manager import ReviewManager
from revui.views.export_dialog import ExportDialog
from revui.services.export_service import ExportService


class ThumbListView(QListView):
    requestContextFor = Signal(str)  # patch_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSpacing(8)

    def contextMenuEvent(self, event):
        idx = self.indexAt(event.pos())
        if not idx.isValid():
            return
        pid = idx.data(Qt.UserRole + 1)
        if not pid:
            return
        self.requestContextFor.emit(pid)


class FilterProxy(QSortFilterProxyModel):
    """文本（patch_id/tile_id）+ score阈值 + 未复核/高/低置信过滤"""
    def __init__(self, manager: ReviewManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.query = ""
        self.min_score = 0.0
        self.only_unreviewed = False
        self.only_high = False
        self.only_low = False

    def set_query(self, q: str):
        self.query = q.strip().lower()
        self.invalidateFilter()

    def set_min_score(self, s: float):
        self.min_score = s
        self.invalidateFilter()

    def set_flags(self, unreviewed: bool, high: bool, low: bool):
        self.only_unreviewed, self.only_high, self.only_low = unreviewed, high, low
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        m = self.sourceModel()
        idx = m.index(source_row, 0, source_parent)
        it: QStandardItem = m.itemFromIndex(idx)  # type: ignore
        if it is None:
            return False
        pid = it.data(Qt.UserRole + 1)
        if not pid:
            return False

        score = it.data(Qt.UserRole + 2) or 0.0
        tile_id = (it.data(Qt.UserRole + 3) or "").lower()
        patch_id = str(pid).lower()

        if self.min_score > 0 and score < self.min_score:
            return False

        if self.only_unreviewed or self.only_high or self.only_low:
            p = self.manager.get_patch_by_id(pid)
            if not p:
                return False
            if self.only_unreviewed and self.manager.is_reviewed(p):
                return False
            if self.only_high and p.score < 0.8:
                return False
            if self.only_low and p.score > 0.3:
                return False

        if self.query and (self.query not in patch_id and self.query not in tile_id):
            return False
        return True


class AtypicalWidget(QWidget):
    """复核面板（供右侧/抽屉使用）：无“QC/上一/下一/选择WSI”，只负责展示/筛选/改类/导出。"""
    requestOpenInWSI = Signal(str, int, int, int, int)  # patch_id, x,y,w,h
    visiblePatchesChanged = Signal()  # 通知主窗口刷新胶片带

    def __init__(self, cfg_path: str | Path, parent=None):
        super().__init__(parent)
        self.cfg_path = Path(cfg_path)
        self.cfg = yaml.safe_load(self.cfg_path.read_text(encoding="utf-8"))
        self.labels = self.cfg.get("labels", ["ASCUS", "LSIL", "HSIL+", "Normal"])
        self.palette = self.cfg.get("palette", {})
        thumb_size = self.cfg.get("thumbnail", {}).get("size", 144)

        # 服务
        self.locator = ResultLocator(self.cfg_path)
        self.repo = ResultRepo(self.labels)
        self.manager = ReviewManager(reviewer="doctor_x")
        self.exporter = ExportService(self.labels)

        # 当前状态
        self._res_dir: Path | None = None
        self._tif_path: Path | None = None

        # UI
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ---- Header（仅保留路径展示/总体判定/导出）----
        header = QHBoxLayout()
        header.setSpacing(6)

        self.editPath = QLineEdit()
        self.editPath.setReadOnly(True)
        self.editPath.setPlaceholderText("当前 WSI 路径...")
        header.addWidget(self.editPath, 2)

        self.slideTag = QLabel("未载入")
        self.slideTag.setObjectName("SlideTag")
        self.slideTag.setMinimumWidth(80)
        self.slideTag.setAlignment(Qt.AlignCenter)
        header.addWidget(self.slideTag, 0)

        header.addStretch(1)

        self.btnExport = QPushButton("导出复核结果")
        self.btnExport.clicked.connect(self._export_dialog)
        header.addWidget(self.btnExport, 0)

        root.addLayout(header)

        # ---- 中间：左侧Tab(各类列表) + 右侧筛选 ----
        splitter = QSplitter(Qt.Horizontal, self)

        # 左：类别 tab + 缩略图列表
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)

        self.models: dict[str, QStandardItemModel] = {}
        self.proxies: dict[str, FilterProxy] = {}
        self.views: dict[str, ThumbListView] = {}

        for lb in self.labels:
            base_model = QStandardItemModel(self)
            proxy = FilterProxy(self.manager, self)
            proxy.setSourceModel(base_model)

            lv = ThumbListView(self)
            lv.setIconSize(QSize(thumb_size, thumb_size))
            lv.setModel(proxy)
            self.models[lb] = base_model
            self.proxies[lb] = proxy
            self.views[lb] = lv
            self.tabs.addTab(lv, f"{lb} (0)")
            lv.requestContextFor.connect(self._ctx_menu_for)
            lv.doubleClicked.connect(self._open_detail_from_index(lb))

        left_layout.addWidget(self.tabs)
        splitter.addWidget(left)

        # 右：筛选/排序
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)

        self.searchBox = QLineEdit()
        self.searchBox.setPlaceholderText("搜索 patch_id / tile_id")
        right_layout.addWidget(self.searchBox)

        self.scoreMin = QSlider(Qt.Horizontal)
        self.scoreMin.setRange(0, 100)
        self.scoreMin.setValue(0)
        right_layout.addWidget(QLabel("最低置信度"))
        right_layout.addWidget(self.scoreMin)

        self.chkUnreviewed = QCheckBox("仅看未复核")
        self.chkHigh = QCheckBox("高置信(≥0.8)")
        self.chkLow = QCheckBox("低置信(≤0.3)")
        right_layout.addWidget(self.chkUnreviewed)
        right_layout.addWidget(self.chkHigh)
        right_layout.addWidget(self.chkLow)

        self.cmbSort = QComboBox()
        self.cmbSort.addItems(["默认", "score↑", "score↓"])
        right_layout.addWidget(QLabel("排序方式"))
        right_layout.addWidget(self.cmbSort)
        right_layout.addStretch(1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, 1)

        # ---- 快捷键：改类 & 撤销/重做 ----
        actUndo = QAction("撤销", self, shortcut=QKeySequence("Ctrl+Z"), triggered=self.manager.undo)
        actRedo = QAction("重做", self, shortcut=QKeySequence("Ctrl+Y"), triggered=self.manager.redo)
        self.addAction(actUndo)
        self.addAction(actRedo)
        for i, lb in enumerate(self.labels):
            key = QKeySequence(str(i + 1 if i < 3 else 0))
            action = QAction(lb, self)
            action.setShortcut(key)
            action.triggered.connect(lambda checked=False, lb=lb: self.relabel_selection(lb))
            self.addAction(action)

        # 过滤刷新 + 胶片带刷新
        self.searchBox.textChanged.connect(self._on_filter_changed_emit)
        self.scoreMin.valueChanged.connect(self._on_filter_changed_emit)
        self.chkUnreviewed.toggled.connect(self._on_filter_changed_emit)
        self.chkHigh.toggled.connect(self._on_filter_changed_emit)
        self.chkLow.toggled.connect(self._on_filter_changed_emit)
        self.cmbSort.currentIndexChanged.connect(self._apply_sort_emit)

        # 默认样式
        self.setStyleSheet("""
        #SlideTag {
            background:#9E9E9E;
            color:white;
            padding:3px 10px;
            border-radius:12px;
        }
        """)

    # ---------- 外部接口 ----------
    def select_wsi(self, preset_path: str | Path):
        """由 MainWidget 调用：根据 WSI 路径自动定位结果目录并加载。"""
        p = str(preset_path)
        self.editPath.setText(p)
        res_dir = self.locator.locate(Path(p))
        if not res_dir:
            QMessageBox.warning(self, "未找到结果", "未能定位到该WSI的结果目录。")
            return
        try:
            patches, meta = self.repo.load(res_dir)
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"读取结果出错：\n{e}")
            return
        self._res_dir = Path(res_dir)
        self._tif_path = Path(p)
        self.manager.set_data(patches, meta)
        self._update_slide_tag(meta)
        self.refresh_views()
        self.visiblePatchesChanged.emit()

    # ---------- 顶部 Tag / 信息 ----------
    def _update_slide_tag(self, meta: SlideMeta):
        if not meta or not meta.slide_pred_label:
            self.slideTag.setText("未判定")
            self.slideTag.setStyleSheet("")
            return
        lb = meta.slide_pred_label
        self.slideTag.setText(lb)
        color = self.palette.get(lb, "#999999")
        self.slideTag.setStyleSheet(
            f"#SlideTag {{ background:{color}; color:white; padding:4px 12px; border-radius:12px; }}"
        )
        scs = ", ".join([f"{k}:{v:.2f}" for k, v in meta.slide_pred_scores.items()])
        self.slideTag.setToolTip(f"模型WSI判定：{lb}\n{scs}")

    # ---------- 列表刷新 ----------
    def refresh_views(self):
        patches, meta, _ = self.manager.get_state()
        per_label = {lb: [] for lb in self.labels}
        for p in patches:
            per_label.get(p.label, per_label[self.labels[0]]).append(p)

        for i, lb in enumerate(self.labels):
            base = self.models[lb]
            base.clear()
            for p in per_label[lb]:
                it = QStandardItem()
                it.setData(p.patch_id, Qt.UserRole + 1)
                it.setData(p.score, Qt.UserRole + 2)
                it.setData(p.tile_id, Qt.UserRole + 3)
                pix = QPixmap(str(p.thumb_path)) if p.thumb_path and Path(p.thumb_path).exists() else QPixmap()
                if not pix.isNull():
                    it.setIcon(QIcon(pix))
                it.setText(f"{p.patch_id}\nscore={p.score:.3f}")
                base.appendRow(it)
            self.tabs.setTabText(i, f"{lb} ({len(per_label[lb])})")

    # ---------- 筛选/排序 ----------
    def _on_filter_changed_emit(self, *_args):
        self._on_filter_changed()
        self.visiblePatchesChanged.emit()

    def _apply_sort_emit(self, *_args):
        self._apply_sort()
        self.visiblePatchesChanged.emit()

    def _on_filter_changed(self, *_args):
        q = self.searchBox.text().strip()
        min_score = self.scoreMin.value() / 100.0
        only_unrev = self.chkUnreviewed.isChecked()
        only_high = self.chkHigh.isChecked()
        only_low = self.chkLow.isChecked()

        for lb, proxy in self.proxies.items():
            proxy.set_query(q)
            proxy.set_min_score(min_score)
            proxy.set_flags(only_unrev, only_high, only_low)

    def _apply_sort(self):
        mode = self.cmbSort.currentText()
        for proxy in self.proxies.values():
            if mode == "默认":
                proxy.sort(-1)
            elif mode == "score↑":
                proxy.sort(0, Qt.AscendingOrder)
            elif mode == "score↓":
                proxy.sort(0, Qt.DescendingOrder)

    # ---------- 右键菜单 & 打开细节 ----------
    def _ctx_menu_for(self, patch_id: str):
        p = self.manager.get_patch_by_id(patch_id)
        if not p:
            return
        # 这里只做简单“跳转至 WSI”的信号，具体由 MainWidget 处理
        self.requestOpenInWSI.emit(p.patch_id, p.x, p.y, p.w, p.h)

    def _open_detail_from_index(self, label: str):
        def handler(idx: QModelIndex):
            proxy = self.proxies[label]
            base = self.models[label]
            src_idx = proxy.mapToSource(idx)
            it = base.itemFromIndex(src_idx)
            if not it:
                return
            pid = it.data(Qt.UserRole + 1)
            p = self.manager.get_patch_by_id(pid)
            if not p:
                return
            self.requestOpenInWSI.emit(p.patch_id, p.x, p.y, p.w, p.h)
        return handler

    # ---------- 改类 ----------
    def relabel_selection(self, target_label: str):
        lv: ThumbListView = self.tabs.currentWidget()  # type: ignore
        proxy: QSortFilterProxyModel = lv.model()      # type: ignore
        base: QStandardItemModel = self.models[self.labels[self.tabs.currentIndex()]]
        ids = []
        if lv.selectionModel():
            for idx in lv.selectionModel().selectedIndexes():
                src_idx = proxy.mapToSource(idx)
                it = base.itemFromIndex(src_idx)
                ids.append(it.data(Qt.UserRole + 1))
        for pid in ids:
            self.manager.move_class(pid, target_label)
        self.refresh_views()
        self.visiblePatchesChanged.emit()

    # ---------- 导出 ----------
    def _export_dialog(self):
        d = ExportDialog(self.cfg.get("io", {}).get("default_export_dir", "./exports"), self)
        if d.exec_() != d.accepted:
            return
        out_dir, write_csv, copy_tiles = d.get_result()
        patches, meta, changes = self.manager.get_state()
        try:
            self.exporter.export_all(
                Path(out_dir),
                patches,
                changes,
                meta,
                copy_tiles=copy_tiles,
                write_csv=write_csv,
                write_json=write_csv,
            )
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出出错：\n{e}")
            return
        QMessageBox.information(self, "导出完成", f"已导出到：\n{out_dir}")

    # ---------- InfoDock 访问器 ----------
    def get_current_meta(self) -> SlideMeta | None:
        try:
            _, meta, _ = self.manager.get_state()
            return meta
        except Exception:
            return None
