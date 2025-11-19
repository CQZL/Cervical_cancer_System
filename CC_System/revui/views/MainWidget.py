from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
import openslide
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import threading

from InfoWidget import OverlayHost, InfoFormWidget
from AtypicalWidget import AtypicalWidget


# ------------------------- LRU 瓦片缓存 -------------------------
class TileCache:
    def __init__(self, max_size=1200):
        self.cache = {}
        self.access_order = []
        self.max_size = max_size
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                try:
                    self.access_order.remove(key)
                except ValueError:
                    pass
                self.access_order.append(key)
                return self.cache[key]
        return None

    def put(self, key, value):
        with self.lock:
            if key not in self.cache:
                if len(self.access_order) >= self.max_size:
                    oldest = self.access_order.pop(0)
                    self.cache.pop(oldest, None)
                self.cache[key] = value
                self.access_order.append(key)

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.access_order.clear()


# ------------------------- OpenSlide 封装 -------------------------
class WSIViewer:
    def __init__(self, file_path: str):
        self.slide = openslide.OpenSlide(file_path)
        self.cache = TileCache(max_size=1600)

        props = self.slide.properties
        self.mpp_x = None
        try:
            if "openslide.mpp-x" in props:
                self.mpp_x = float(props.get("openslide.mpp-x"))
        except Exception:
            self.mpp_x = None

    def read_tile(self, x_l0: int, y_l0: int, tile_size: int, level: int):
        """从 level-0 坐标读取指定 level 的 tile。"""
        key = (level, x_l0, y_l0, tile_size)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        region = self.slide.read_region((x_l0, y_l0), level, (tile_size, tile_size)).convert("RGB")
        arr = np.array(region)
        self.cache.put(key, arr)
        return arr

    def get_dimensions(self, level: int):
        return self.slide.level_dimensions[level]

    def get_level_count(self) -> int:
        return self.slide.level_count

    def get_downsample(self, level: int):
        return self.slide.level_downsamples[level]

    def get_thumbnail_np(self, max_size: int = 512) -> np.ndarray:
        """返回整体缩略图的 numpy 数组 (H, W, 3)。"""
        thumb = self.slide.get_thumbnail((max_size, max_size)).convert("RGB")
        return np.array(thumb)

    def close(self):
        self.slide.close()
        self.cache.clear()


# ------------------------- 比例尺控件（固定在视口底部） -------------------------
class ScaleBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mpp = None
        self.view_scale = 1.0  # level-0 像素到屏幕像素的缩放
        self.setFixedHeight(36)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_mpp(self, mpp: float | None):
        self.mpp = mpp
        self.update()

    def set_view_scale(self, s: float):
        self.view_scale = s
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

        rect = self.rect().adjusted(12, 8, -12, -8)
        if not self.mpp or self.mpp <= 0:
            bar_len_px = rect.width() * 0.5
            label = f"{int(bar_len_px)} px"
        else:
            px_per_um = self.view_scale / self.mpp  # 1μm 对应多少屏幕像素
            nice_um = [10, 20, 50, 100, 200, 500, 1000, 2000]
            target_px = rect.width() * 0.5
            best_um = nice_um[0]
            best_px = best_um * px_per_um
            best_diff = float("inf")
            for um in nice_um:
                px = um * px_per_um
                diff = abs(px - target_px)
                if diff < best_diff:
                    best_diff = diff
                    best_um = um
                    best_px = px
            bar_len_px = max(40, min(rect.width() - 40, best_px))
            label = f"{best_um} μm"

        x = rect.center().x() - bar_len_px / 2
        y = rect.center().y()
        painter.setPen(QPen(Qt.white, 2))
        painter.drawLine(QPointF(x, y), QPointF(x + bar_len_px, y))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(QRectF(x, y + 4, bar_len_px, 16), Qt.AlignCenter, label)


# ------------------------- 左上角 HUD 覆盖层 -------------------------
class HudOverlay(QWidget):
    """
    固定在视口左上角，显示：
    - 文件名
    - 缩放倍率 + level 信息
    - 鼠标当前位置（level-0 坐标）
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._file = ""
        self._zoom = ""
        self._coord = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_file(self, name: str):
        self._file = name
        self.update()

    def set_zoom(self, text: str):
        self._zoom = text
        self.update()

    def set_coord(self, text: str):
        self._coord = text
        self.update()

    def paintEvent(self, event):
        if not (self._file or self._zoom or self._coord):
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        # 半透明背景
        rect = self.rect().adjusted(4, 4, -4, -4)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 8, 8)

        # 文本
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        y = rect.top() + 6
        line_h = 14
        if self._file:
            painter.drawText(rect.left() + 8, y + line_h, f"文件: {self._file}")
            y += line_h
        if self._zoom:
            painter.drawText(rect.left() + 8, y + line_h, f"倍率: {self._zoom}")
            y += line_h
        if self._coord:
            painter.drawText(rect.left() + 8, y + line_h, f"坐标: {self._coord}")


# ------------------------- 左下角 Overview / Minimap -------------------------
class OverviewWidget(QWidget):
    """
    左下角整体缩略图 + 视野框，支持点击/拖动物件进行快速导航。
    与 MainWidget 通过 level-0 坐标交互。
    """
    requestCenterOn = Signal(float, float)  # level-0 center x, y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 220)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)

        self._pix: QPixmap | None = None
        self._full_w = 1
        self._full_h = 1
        self._ratio_x = 1.0
        self._ratio_y = 1.0
        self._view_rect_l0: QRectF | None = None

        self._dragging = False

    def set_overview(self, pixmap: QPixmap, full_size: tuple[int, int]):
        self._full_w, self._full_h = full_size
        # 缩放到适合本控件大小
        scaled = pixmap.scaled(self.size() - QSize(8, 8), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._pix = scaled
        self._ratio_x = self._pix.width() / self._full_w
        self._ratio_y = self._pix.height() / self._full_h
        self.update()

    def clear(self):
        self._pix = None
        self._view_rect_l0 = None
        self.update()

    def update_view_rect(self, rect_l0: QRectF):
        self._view_rect_l0 = rect_l0
        self.update()

    # 内部辅助：将 widget 中点转换到 level-0 坐标
    def _to_level0(self, pos: QPointF) -> tuple[float, float]:
        if not self._pix:
            return 0.0, 0.0
        w = self.width()
        h = self.height()
        px_w = self._pix.width()
        px_h = self._pix.height()
        # 居中绘制的偏移
        offset_x = (w - px_w) / 2
        offset_y = (h - px_h) / 2
        x = (pos.x() - offset_x) / self._ratio_x
        y = (pos.y() - offset_y) / self._ratio_y
        x = max(0.0, min(float(self._full_w), float(x)))
        y = max(0.0, min(float(self._full_h), float(y)))
        return x, y

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._pix:
            self._dragging = True
            cx, cy = self._to_level0(event.position())
            self.requestCenterOn.emit(cx, cy)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._pix:
            cx, cy = self._to_level0(event.position())
            self.requestCenterOn.emit(cx, cy)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 160))

        if not self._pix:
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "无缩略图")
            return

        w = self.width()
        h = self.height()
        px_w = self._pix.width()
        px_h = self._pix.height()
        offset_x = (w - px_w) / 2
        offset_y = (h - px_h) / 2

        # 画缩略图
        painter.drawPixmap(int(offset_x), int(offset_y), self._pix)

        # 画视野框
        if self._view_rect_l0:
            rv = self._view_rect_l0
            x = rv.x() * self._ratio_x + offset_x
            y = rv.y() * self._ratio_y + offset_y
            rw = rv.width() * self._ratio_x
            rh = rv.height() * self._ratio_y

            painter.setPen(QPen(QColor(255, 255, 0), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(x, y, rw, rh))


# ------------------------- 主界面 -------------------------
class MainWidget(QWidget):
    file_loaded = Signal(str)
    tile_loaded = Signal(int, int, int, object)  # x, y, level, np.ndarray

    def __init__(self):
        super().__init__()
        self.font = QFont("Microsoft YaHei", 11)

        # 复核面板
        self.review_panel = AtypicalWidget("./config.yaml", parent=self)
        self.review_panel.requestOpenInWSI.connect(self.centerOnRect)

        # WSI 状态
        self.wsi_viewer: WSIViewer | None = None
        self.wsi_tile_items = {}    # {(lv,x,y): QGraphicsPixmapItem}
        self.pending_tasks = set()  # {(lv,x,y)}
        self.current_level = 0
        self.TILE_SIZE = 512
        self.MAX_TILES_PER_REQUEST = 256
        self.MAX_TILES_ON_SCENE = 2500

        self._current_file_name = ""
        self._last_coord_text = ""

        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=8)

        # 场景 + 视图
        self.scene = QGraphicsScene(self)
        self.graphics_view = QGraphicsView(self.scene)
        self.graphics_view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.graphics_view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.graphics_view.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.graphics_view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.graphics_view.viewport().installEventFilter(self)
        self.graphics_view.viewport().setMouseTracking(True)

        self._roi_rect_item: QGraphicsRectItem | None = None

        # 覆盖层：比例尺 / HUD / Overview
        self.scale_bar = ScaleBarWidget(self.graphics_view.viewport())
        self.scale_bar.hide()

        self.hud = HudOverlay(self.graphics_view.viewport())
        self.hud.hide()

        self.overview = OverviewWidget(self.graphics_view.viewport())
        self.overview.hide()
        self.overview.requestCenterOn.connect(self._center_from_overview)

        self.tile_loaded.connect(self._on_tile_loaded)

        # 刷新调度
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update)

        self._init_control()

        # 快捷键：Ctrl+E 切换右侧抽屉
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.toggle_right_panel)

        # 快捷键：缩放 / 平移
        QShortcut(QKeySequence(Qt.Key_Plus), self, activated=lambda: self._zoom_step(1.2))
        QShortcut(QKeySequence(Qt.Key_Minus), self, activated=lambda: self._zoom_step(1 / 1.2))

    # ------------------------- UI -------------------------
    def _init_control(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.host = OverlayHost(self, drawer_base_width=420, anim_ms=220)
        main_layout.addWidget(self.host)

        # 中央内容：影像浏览页面
        view_page = QWidget()
        v = QVBoxLayout(view_page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        # 顶部工具条
        top_bar = QHBoxLayout()
        self.logo_label = QLabel()
        pixmap = QPixmap("../../icon/logo1.png")
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.logo_label.setPixmap(scaled_pixmap)
        self.logo_label.setFixedSize(75, 40)
        self.logo_label.setScaledContents(True)
        top_bar.addWidget(self.logo_label)

        self.show_queue_btn = QPushButton("返回上一界面")
        self.show_queue_btn.setFixedHeight(30)
        self.show_queue_btn.setFlat(True)
        self.show_queue_btn.setIcon(QIcon("../../icon/return.png"))
        self.show_queue_btn.setIconSize(QSize(15, 15))
        self.show_queue_btn.setStyleSheet("""
            QPushButton {
                background-color:#BBFFFF;
                padding: 5px;
                border: 2px solid #555555;
                border-radius: 5px;
                font-size: 14px;
                font: bold;
            }
            QPushButton:hover { background-color: #AEEEEE; }
        """)
        top_bar.addWidget(self.show_queue_btn)

        top_bar.addStretch(1)
        top_bar.addWidget(QLabel("|", self))

        # 导入 / 清除
        self.btn_load = QPushButton("导入图片")
        self.btn_load.setFixedHeight(30)
        self.btn_load.setStyleSheet("""
            QPushButton {
                background-color:#1976D2;
                color:white;
                border-radius:5px;
                padding:5px 10px;
            }
            QPushButton:hover { background-color:#1565C0; }
        """)
        self.btn_load.clicked.connect(self.on_icon_button_clicked)
        top_bar.addWidget(self.btn_load)

        self.remove_queue_btn = QPushButton("清除图像")
        self.remove_queue_btn.setFixedHeight(30)
        self.remove_queue_btn.setStyleSheet("""
            QPushButton {
                background-color:#F8BBD0;
                border-radius:5px;
                padding:5px 10px;
                font-size:12px;
            }
            QPushButton:hover { background-color:#F48FB1; }
        """)
        self.remove_queue_btn.clicked.connect(self.remove_image)
        top_bar.addWidget(self.remove_queue_btn)

        top_bar.addWidget(QLabel("|", self))

        # 常用倍率按钮
        for text, scale_factor in [("1x", 1.0), ("2x", 2.0), ("4x", 4.0), ("10x", 10.0)]:
            button = QPushButton(text)
            button.setFixedSize(40, 30)
            button.setStyleSheet("""
                QPushButton {
                    background-color:#FFEFD5;
                    border: 1px solid #555555;
                    padding: 5px;
                    border-radius: 5px;
                    font-size: 11px;
                }
                QPushButton:hover { background-color:#FFDEAD; }
            """)
            button.clicked.connect(lambda _=False, f=scale_factor: self.set_view_scale(f))
            top_bar.addWidget(button)

        self.fit_button = QPushButton("Fit")
        self.fit_button.setFixedWidth(40)
        self.fit_button.setStyleSheet("""
            QPushButton {
                background-color:#E0F7FA;
                border: 1px solid #555555;
                padding: 5px;
                border-radius: 5px;
                font-size: 12px;
                font: bold;
            }
            QPushButton:hover { background-color:#B2EBF2; }
        """)
        self.fit_button.clicked.connect(self.fit_in_view)
        top_bar.addWidget(self.fit_button)

        v.addLayout(top_bar)
        v.addWidget(self.graphics_view, 1)

        self.host.tab.addTab(view_page, "影像浏览")

        # 抽屉内容：Tab1 Info，Tab2 复核
        self.host.drawer.lbl_title.setText("医生标注 & Patch 复核")
        self.drawer_tabs = QTabWidget()
        self.drawer_tabs.setTabPosition(QTabWidget.North)
        self.drawer_tabs.setDocumentMode(True)

        self.info_form = InfoFormWidget()
        self.drawer_tabs.addTab(self.info_form, "医生标注")
        self.drawer_tabs.addTab(self.review_panel, "Patch 复核")

        # 顶部模式按钮
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        lbl = QLabel("模式：")
        mode_row.addWidget(lbl)
        self.btn_mode_info = QPushButton("医生标注")
        self.btn_mode_review = QPushButton("复核列表")
        for b in (self.btn_mode_info, self.btn_mode_review):
            b.setCheckable(True)
            b.setMinimumWidth(80)
            b.setStyleSheet("""
                QPushButton {
                    border-radius: 6px;
                    border: 1px solid #90CAF9;
                    padding: 6px 10px;
                    background:#E3F2FD;
                }
                QPushButton:checked {
                    background:#1976D2;
                    color:white;
                    border-color:#1565C0;
                }
            """)
            mode_row.addWidget(b)
        mode_row.addStretch(1)

        self.btn_mode_info.setChecked(True)
        self.btn_mode_info.clicked.connect(lambda: self._switch_drawer_tab(0))
        self.btn_mode_review.clicked.connect(lambda: self._switch_drawer_tab(1))
        self.drawer_tabs.currentChanged.connect(self._sync_mode_buttons)

        self.host.drawer.scroll_layout.addLayout(mode_row)
        self.host.drawer.scroll_layout.addWidget(self.drawer_tabs)
        self.host.drawer.scroll_layout.addStretch(1)

    def _switch_drawer_tab(self, idx: int):
        self.drawer_tabs.setCurrentIndex(idx)

    def _sync_mode_buttons(self, idx: int):
        self.btn_mode_info.blockSignals(True)
        self.btn_mode_review.blockSignals(True)
        self.btn_mode_info.setChecked(idx == 0)
        self.btn_mode_review.setChecked(idx == 1)
        self.btn_mode_info.blockSignals(False)
        self.btn_mode_review.blockSignals(False)

    # ------------------------- 快捷键控制抽屉 -------------------------
    def toggle_right_panel(self):
        self.host.toggleDrawer()

    # ------------------------- 文件加载/清除 -------------------------
    def on_icon_button_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择WSI图像", "", "TIF/WSI Files (*.tif *.svs *.ndpi);;All Files (*)"
        )
        if file_path:
            self.open_slide(file_path)

    def open_slide(self, file_path: str):
        if self.wsi_viewer:
            self.wsi_viewer.close()
            self.wsi_viewer = None
            self.scene.clear()
            self.wsi_tile_items.clear()
            self.pending_tasks.clear()

        try:
            self.wsi_viewer = WSIViewer(file_path)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"打开 WSI 失败：\n{e}")
            return

        self._current_file_name = Path(file_path).name
        self.hud.set_file(self._current_file_name)

        self.file_loaded.emit(file_path)
        # 初始先用中间层（如果有）
        self.current_level = min(2, self.wsi_viewer.get_level_count() - 1)
        dim = self.wsi_viewer.get_dimensions(self.current_level)
        self.scene.clear()
        self.wsi_tile_items.clear()
        self.pending_tasks.clear()
        self.scene.setSceneRect(0, 0, dim[0], dim[1])

        # 比例尺
        mpp = self.wsi_viewer.mpp_x
        self.scale_bar.set_mpp(mpp)
        self.scale_bar.show()

        # Overview 缩略图（从 level-0 生成）
        try:
            thumb_arr = self.wsi_viewer.get_thumbnail_np(max_size=512)
            h, w, _ = thumb_arr.shape
            qimg = QImage(thumb_arr.data, w, h, w * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            full_w, full_h = self.wsi_viewer.get_dimensions(0)
            self.overview.set_overview(pix, (full_w, full_h))
            self.overview.show()
        except Exception:
            self.overview.clear()
            self.overview.hide()

        # Fit 一下
        self.fit_in_view()

        # 复核面板同步
        try:
            self.review_panel.select_wsi(file_path)
        except Exception as e:
            QMessageBox.information(self, "提示", f"复核面板载入结果失败：{e}")

    def remove_image(self):
        if self.wsi_viewer:
            self.scene.clear()
            self.wsi_tile_items.clear()
            self.pending_tasks.clear()
            self.wsi_viewer.close()
            self.wsi_viewer = None
            self._clear_roi_rect()
        self.scale_bar.hide()
        self.overview.clear()
        self.overview.hide()
        self.hud.set_zoom("")
        self.hud.set_coord("")

    # ------------------------- 视图缩放/平移 -------------------------
    def fit_in_view(self):
        if not self.scene.items():
            return
        self.graphics_view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.request_update(force=True)

    def set_view_scale(self, factor: float):
        if not self.wsi_viewer:
            return
        self.graphics_view.resetTransform()
        self.graphics_view.scale(factor, factor)
        self.request_update(force=True)

    def _zoom_step(self, factor: float):
        """键盘 +/- 缩放，以视口中心为锚点。"""
        if not self.wsi_viewer:
            return
        vp = self.graphics_view.viewport().rect()
        center_pos = QPointF(vp.center())
        self._zoom_at(center_pos, factor)

    def _zoom_at(self, pos: QPointF, factor: float):
        if not self.wsi_viewer:
            return
        before = self.graphics_view.mapToScene(pos.toPoint())
        self.graphics_view.scale(factor, factor)
        after = self.graphics_view.mapToScene(pos.toPoint())
        delta = after - before
        self.graphics_view.translate(delta.x(), delta.y())
        self.request_update()

    def centerOnRect(self, patch_id: str, x: int, y: int, w: int, h: int):
        rect = QRectF(x, y, w, h)
        if rect.isNull():
            return
        self.graphics_view.fitInView(rect, Qt.KeepAspectRatio)
        self.request_update(force=True)

        if self._roi_rect_item is not None:
            try:
                self.scene.removeItem(self._roi_rect_item)
            except Exception:
                pass
            self._roi_rect_item = None

        pen = QPen(Qt.red, 3, Qt.DashLine)
        self._roi_rect_item = self.scene.addRect(rect, pen)
        QTimer.singleShot(1500, self._clear_roi_rect)

    def _clear_roi_rect(self):
        if self._roi_rect_item is not None:
            try:
                self.scene.removeItem(self._roi_rect_item)
            except Exception:
                pass
            self._roi_rect_item = None

    def _center_from_overview(self, cx0: float, cy0: float):
        """由 OverviewWidget 发起，cx0,cy0 为 level-0 坐标。"""
        if not self.wsi_viewer:
            return
        ds = self.wsi_viewer.get_downsample(self.current_level)
        cx = cx0 / ds
        cy = cy0 / ds
        self.graphics_view.centerOn(QPointF(cx, cy))
        self.request_update(force=True)

    # ------------------------- 事件过滤：滚轮缩放 + 双击缩放 + 鼠标坐标 HUD -------------------------
    def eventFilter(self, obj, event):
        if obj is self.graphics_view.viewport():
            # 滚轮缩放
            if isinstance(event, QWheelEvent):
                if not self.wsi_viewer:
                    return True
                angle = event.angleDelta().y()
                if angle == 0:
                    return True
                steps = angle / 120.0
                factor = pow(1.15, steps)
                self._zoom_at(event.position(), factor)
                return True
            # 双击缩放（左键放大，右键缩小）
            if event.type() == QEvent.MouseButtonDblClick:
                if not self.wsi_viewer:
                    return True
                if event.button() == Qt.LeftButton:
                    self._zoom_at(event.position(), 1.8)
                elif event.button() == Qt.RightButton:
                    self._zoom_at(event.position(), 1 / 1.8)
                return True
            # 鼠标移动时更新 HUD 坐标
            if event.type() == QEvent.MouseMove and self.wsi_viewer:
                pos = event.position().toPoint()
                scene_pt = self.graphics_view.mapToScene(pos)
                ds = self.wsi_viewer.get_downsample(self.current_level)
                x0 = int(scene_pt.x() * ds)
                y0 = int(scene_pt.y() * ds)
                self._last_coord_text = f"{x0}, {y0}"
                self.hud.set_coord(self._last_coord_text)
        return super().eventFilter(obj, event)

    # ------------------------- 动态选择 level + 更新 HUD / Overview / ScaleBar -------------------------
    def _update_overlays_geometry(self):
        vp_rect = self.graphics_view.viewport().rect()
        # HUD 左上角固定
        hud_w, hud_h = 260, 70
        self.hud.setGeometry(10, 10, hud_w, hud_h)
        self.hud.show()

        # Overview 左下角，略高于比例尺
        if self.overview.isVisible():
            ow, oh = self.overview.width(), self.overview.height()
            margin = 10
            sb_h = self.scale_bar.height() if self.scale_bar.isVisible() else 0
            x = margin
            y = vp_rect.height() - oh - sb_h - margin
            if y < 0:
                y = 0
            self.overview.setGeometry(x, y, ow, oh)

    def _update_scale_bar_and_hud(self):
        if not self.wsi_viewer:
            return
        t = self.graphics_view.transform()
        view_scale = t.m11()

        # 根据 view_scale 粗略选择更合适的 level
        self._maybe_change_level(view_scale)

        # 此时 current_level 可能已变
        ds = self.wsi_viewer.get_downsample(self.current_level)
        global_scale = view_scale / ds  # level-0 像素到屏幕像素

        # 更新比例尺
        self.scale_bar.set_view_scale(global_scale)
        r = self.graphics_view.viewport().rect()
        self.scale_bar.setGeometry(0, r.height() - self.scale_bar.height(), r.width(), self.scale_bar.height())
        self.scale_bar.show()

        # 更新 HUD 的倍率显示
        zoom_text = f"{global_scale:.2f}x (L{self.current_level})"
        self.hud.set_zoom(zoom_text)

        # 更新 HUD / Overview 几何
        self._update_overlays_geometry()
        self._update_overview_rect()

    def _update_overview_rect(self):
        """根据当前视口更新 Overview 中的视野框（使用 level-0 坐标）。"""
        if not (self.wsi_viewer and self.overview.isVisible()):
            return
        rect_scene = self.graphics_view.mapToScene(self.graphics_view.viewport().rect()).boundingRect()
        ds = self.wsi_viewer.get_downsample(self.current_level)
        rect_l0 = QRectF(
            rect_scene.x() * ds,
            rect_scene.y() * ds,
            rect_scene.width() * ds,
            rect_scene.height() * ds,
        )
        self.overview.update_view_rect(rect_l0)

    def _maybe_change_level(self, view_scale: float):
        """
        根据当前 view_scale 粗略决定是否切换 OpenSlide level。
        简单策略：
        - view_scale 太大 -> 切到更细的 level（索引减一）
        - view_scale 太小 -> 切到更粗的 level（索引加一）
        """
        if not self.wsi_viewer:
            return
        max_level = self.wsi_viewer.get_level_count() - 1
        old_level = self.current_level

        upper = 2.4
        lower = 0.7

        if view_scale > upper and self.current_level > 0:
            self.current_level -= 1
        elif view_scale < lower and self.current_level < max_level:
            self.current_level += 1

        if self.current_level != old_level:
            self._reload_scene_for_level(old_level)

    def _reload_scene_for_level(self, old_level: int):
        """切换 level 时，保持视口中心位置（在 level-0 坐标系下尽量不变）"""
        if not self.wsi_viewer:
            return
        view = self.graphics_view
        old_ds = self.wsi_viewer.get_downsample(old_level)
        new_ds = self.wsi_viewer.get_downsample(self.current_level)

        center_scene_old = view.mapToScene(view.viewport().rect().center())
        cx0 = center_scene_old.x() * old_ds
        cy0 = center_scene_old.y() * old_ds

        dim = self.wsi_viewer.get_dimensions(self.current_level)
        self.scene.setSceneRect(0, 0, dim[0], dim[1])

        self.scene.clear()
        self.wsi_tile_items.clear()
        self.pending_tasks.clear()
        self._clear_roi_rect()

        center_scene_new = QPointF(cx0 / new_ds, cy0 / new_ds)
        view.centerOn(center_scene_new)
        self.request_update(force=True)

    # ------------------------- 刷新调度 -------------------------
    def request_update(self, force=False):
        if force:
            self._update_timer.stop()
            self._do_update()
        else:
            self._update_timer.start(25)

    def _do_update(self):
        self.update_visible_tiles()
        self._update_scale_bar_and_hud()

    # ------------------------- 瓦片调度：视野中心优先 + 限量 -------------------------
    def update_visible_tiles(self):
        if not self.wsi_viewer:
            return

        rect = self.graphics_view.mapToScene(self.graphics_view.viewport().rect()).boundingRect()
        rect = rect.intersected(self.scene.sceneRect())
        if rect.isEmpty():
            return

        tile = self.TILE_SIZE
        x0 = int(rect.left()) // tile * tile
        y0 = int(rect.top()) // tile * tile
        x1 = int(rect.right())
        y1 = int(rect.bottom())

        # 控制场景内图元数量，过多则主动回收一部分
        if len(self.wsi_tile_items) > self.MAX_TILES_ON_SCENE:
            for k, it in list(self.wsi_tile_items.items())[: len(self.wsi_tile_items) // 3]:
                self.scene.removeItem(it)
                self.wsi_tile_items.pop(k, None)

        # 移除不可见 tile（带 margin）
        margin = tile
        to_remove = []
        for (lv, tx, ty), item in self.wsi_tile_items.items():
            if lv != self.current_level:
                to_remove.append((lv, tx, ty))
                continue
            if tx + tile < x0 - margin or tx > x1 + margin or ty + tile < y0 - margin or ty > y1 + margin:
                to_remove.append((lv, tx, ty))
        for key in to_remove:
            item = self.wsi_tile_items.pop(key)
            self.scene.removeItem(item)

        # 中心优先调度 tile
        ds = self.wsi_viewer.get_downsample(self.current_level)
        center = rect.center()

        candidates = []
        for y in range(y0, y1 + tile, tile):
            for x in range(x0, x1 + tile, tile):
                key = (self.current_level, x, y)
                if key in self.wsi_tile_items or key in self.pending_tasks:
                    continue
                cx = x + tile / 2
                cy = y + tile / 2
                dist2 = (cx - center.x()) ** 2 + (cy - center.y()) ** 2
                candidates.append((dist2, x, y))

        candidates.sort(key=lambda t: t[0])

        count = 0
        for _, x, y in candidates:
            if count >= self.MAX_TILES_PER_REQUEST:
                break
            key = (self.current_level, x, y)
            self.pending_tasks.add(key)
            lv = self.current_level
            x_l0 = int(x * ds)
            y_l0 = int(y * ds)
            tsize = tile

            def task(lv=lv, tx=x, ty=y, x0=x_l0, y0=y_l0, t=tsize):
                arr = self.wsi_viewer.read_tile(x0, y0, t, lv)
                self.tile_loaded.emit(tx, ty, lv, arr)

            self.executor.submit(task)
            count += 1

    @Slot(int, int, int, object)
    def _on_tile_loaded(self, x: int, y: int, level: int, arr: object):
        key = (level, x, y)
        self.pending_tasks.discard(key)
        if arr is None or not isinstance(arr, np.ndarray):
            return
        if not self.wsi_viewer or level != self.current_level:
            return
        if key in self.wsi_tile_items:
            return

        h, w, _ = arr.shape
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        item = QGraphicsPixmapItem(pix)
        item.setOffset(x, y)
        self.scene.addItem(item)
        self.wsi_tile_items[key] = item

    # ------------------------- 重载 resizeEvent：保持 overlay 位置 -------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 视图大小变化时，重新布置 HUD / Overview / ScaleBar
        self._update_scale_bar_and_hud()

    # ------------------------- 方向键平移 -------------------------
    def keyPressEvent(self, event: QKeyEvent):
        if not self.wsi_viewer:
            return super().keyPressEvent(event)
        step = 80
        if event.key() == Qt.Key_Left:
            self.graphics_view.translate(step, 0)
            self.request_update()
        elif event.key() == Qt.Key_Right:
            self.graphics_view.translate(-step, 0)
            self.request_update()
        elif event.key() == Qt.Key_Up:
            self.graphics_view.translate(0, step)
            self.request_update()
        elif event.key() == Qt.Key_Down:
            self.graphics_view.translate(0, -step)
            self.request_update()
        else:
            super().keyPressEvent(event)
