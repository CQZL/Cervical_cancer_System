# InfoWidget.py —— 抽屉覆盖 + 遮罩 + 自适应宽度 + 可折叠组医生标注表单
from __future__ import annotations

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


# ---------- 可折叠组 ----------
class CollapsibleGroupBox(QGroupBox):
    toggled_by_user = Signal(bool)

    def __init__(self, title: str, parent=None, start_expanded=True):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(start_expanded)

        self._content = QWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 26, 8, 8)
        outer.addWidget(self._content)

        self.content_layout = QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        self.toggled.connect(self._on_toggled)

    def setContentLayout(self, layout: QLayout):
        # 清空旧 layout
        while True:
            item = self.content_layout.takeAt(0)
            if not item:
                break
            w = item.widget()
            if w:
                w.setParent(None)
        self.content_layout.addLayout(layout)

    def _on_toggled(self, checked: bool):
        self._content.setVisible(checked)
        self.toggled_by_user.emit(checked)


# ---------- 右侧抽屉：自适应宽度 + 几何动画 ----------
class RightDrawer(QWidget):
    def __init__(self, parent=None, base_width=380, anim_ms=220,
                 min_width=360, max_ratio=0.7, padding=32):
        super().__init__(parent)
        self.setObjectName("RightDrawer")
        self._opened = False
        self._animating = False

        self._min_width = min_width
        self._max_ratio = max_ratio
        self._extra_padding = padding
        self._fallback_width = base_width
        self._anim_ms = anim_ms

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            #RightDrawer {
                background: #F5FAFF;
                border-left: 1px solid #cfd8dc;
            }
        """)

        # 内容框架
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(12, 8, 12, 12)
        self.vbox.setSpacing(8)

        title_bar = QHBoxLayout()
        self.lbl_title = QLabel("右侧面板")
        f = self.lbl_title.font()
        f.setPointSize(14)
        f.setBold(True)
        self.lbl_title.setFont(f)
        self.lbl_title.setWordWrap(True)
        title_bar.addWidget(self.lbl_title)
        title_bar.addStretch(1)

        self.btn_close = QToolButton()
        self.btn_close.setText("收回 ▷")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setAutoRaise(True)
        title_bar.addWidget(self.btn_close)
        self.vbox.addLayout(title_bar)

        # 滚动区：对外暴露 scroll_layout
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.scroll_content = QWidget()
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)
        self.vbox.addWidget(self.scroll_area, 1)

        # 几何动画
        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.setDuration(anim_ms)
        self.anim.finished.connect(self._on_anim_finished)

    @property
    def is_open(self):
        return self._opened

    def _compute_required_width(self) -> int:
        self.scroll_content.adjustSize()
        need = self.scroll_content.sizeHint().width() + self._extra_padding
        if need <= 0:
            need = self._fallback_width
        parent = self.parentWidget()
        if parent:
            cap = int(parent.width() * self._max_ratio)
            need = min(need, cap)
        return max(self._min_width, need)

    def _target_rect(self, opening: bool) -> tuple[QRect, QRect]:
        p = self.parentWidget()
        if not p:
            return QRect(), QRect()
        h = p.height()
        w = self._compute_required_width()
        if opening:
            rect_from = QRect(p.width(), 0, w, h)
            rect_to   = QRect(p.width() - w, 0, w, h)
        else:
            rect_from = QRect(p.width() - w, 0, w, h)
            rect_to   = QRect(p.width(), 0, w, h)
        return rect_from, rect_to

    def open(self):
        if self._opened or self._animating:
            return
        self._opened = True
        self._animating = True
        self.show()
        self.raise_()
        rect_from, rect_to = self._target_rect(True)
        self.anim.stop()
        self.anim.setStartValue(rect_from)
        self.anim.setEndValue(rect_to)
        self.anim.start()

    def close_drawer(self):
        if not self._opened or self._animating:
            return
        self._opened = False
        self._animating = True
        rect_from, rect_to = self._target_rect(False)
        self.anim.stop()
        self.anim.setStartValue(rect_from)
        self.anim.setEndValue(rect_to)
        self.anim.start()

    def _on_anim_finished(self):
        self._animating = False
        if not self._opened:
            self.hide()
        p = self.parentWidget()
        if p and hasattr(p, "_syncLayers"):
            QTimer.singleShot(0, p._syncLayers)

    def relayout(self):
        p = self.parentWidget()
        if not p:
            return
        w = self._compute_required_width()
        if self._opened:
            self.setGeometry(QRect(p.width() - w, 0, w, p.height()))
            self.show()
            self.raise_()
        else:
            self.setGeometry(QRect(p.width(), 0, w, p.height()))


# ---------- 覆盖容器：中间主区域 + 遮罩 + 抽屉 ----------
class OverlayHost(QWidget):
    def __init__(self, parent=None, drawer_base_width=380, anim_ms=220):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # 中央 Tab：给 MainWidget 放“影像浏览”等
        self.tab = QTabWidget(self)
        self.tab.setDocumentMode(True)
        self.tab.setTabsClosable(False)
        self.tab.setMovable(False)
        self.tab.setStyleSheet("""
            QTabWidget::pane { border-top: 2px solid #1976d2; background-color: #f5faff; }
            QTabBar::tab {
                background-color: #bbdefb; color: #37474f;
                border: 1px solid #64b5f6; border-bottom: none;
                padding: 6px 14px; font-size: 13px; min-width: 110px;
            }
            QTabBar::tab:selected { background-color: #1976d2; color: white; font-weight: bold; }
            QTabBar::tab:!selected:hover { background-color: #90caf9; color: #1e88e5; }
        """)

        # 遮罩
        self.mask = QWidget(self)
        self.mask.setObjectName("OverlayMask")
        self.mask.setAttribute(Qt.WA_StyledBackground, True)
        self.mask.setStyleSheet("#OverlayMask { background: rgba(0, 0, 0, 80); }")
        self.mask.hide()
        self.mask.installEventFilter(self)

        # 抽屉
        self.drawer = RightDrawer(self, base_width=drawer_base_width, anim_ms=anim_ms)

        # 展开按钮
        self.edgeBtn = QToolButton(self)
        self.edgeBtn.setText("◁ 信息")
        self.edgeBtn.setCursor(Qt.PointingHandCursor)
        self.edgeBtn.setAutoRaise(True)
        self.edgeBtn.setFixedSize(64, 96)
        self.edgeBtn.setStyleSheet("""
            QToolButton {
                background: #e3f2fd;
                border: 1px solid #90caf9;
                border-right: none;
                font-weight: bold;
                color: #1565c0;
                border-top-left-radius: 8px;
                border-bottom-left-radius: 8px;
            }
            QToolButton:hover { background: #bbdefb; }
        """)

        # 布局
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tab)

        # 交互
        self._anim_ms = anim_ms
        self.edgeBtn.clicked.connect(self.openDrawer)
        self.drawer.btn_close.clicked.connect(self.closeDrawer)

        self.drawer._opened = False
        self._syncLayers()

    # 公共接口，方便外部调用
    def openDrawer(self):
        if not self.drawer.is_open and not self.drawer._animating:
            self.mask.show()
            self.mask.raise_()
            self.drawer.open()
            self._syncLayers()
            QTimer.singleShot(self._anim_ms + 60, self._syncLayers)

    def closeDrawer(self):
        if self.drawer.is_open and not self.drawer._animating:
            self.drawer.close_drawer()
            QTimer.singleShot(self._anim_ms + 60, self._syncLayers)

    def toggleDrawer(self):
        if self.drawer.is_open:
            self.closeDrawer()
        else:
            self.openDrawer()

    # 遮罩点击关闭
    def eventFilter(self, obj, ev):
        if obj is self.mask and ev.type() == QEvent.MouseButtonPress:
            self.closeDrawer()
            return True
        return super().eventFilter(obj, ev)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.tab.setGeometry(0, 0, self.width(), self.height())
        self.mask.setGeometry(0, 0, self.width(), self.height())
        self.drawer.relayout()

        x = self.width() - self.edgeBtn.width() + 2
        y = (self.height() - self.edgeBtn.height()) // 2
        self.edgeBtn.move(x, y)
        self._syncLayers()

    def _syncLayers(self):
        if self.drawer.is_open:
            self.mask.show()
            self.mask.stackUnder(self.drawer)
            self.drawer.raise_()
            self.edgeBtn.hide()
        else:
            self.mask.hide()
            self.edgeBtn.show()
            self.edgeBtn.raise_()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key_Escape and self.drawer.is_open:
            self.closeDrawer()
            e.accept()
            return
        super().keyPressEvent(e)


# ---------- 医生标注表单（可折叠组） ----------
class InfoFormWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_options_1 = {}
        self.selected_options_2 = {}
        self.selected_options_3 = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        def new_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            return lbl

        # 样本信息
        sample_group = CollapsibleGroupBox("样本信息", start_expanded=True)
        _lay_sample = QVBoxLayout()
        row1 = QHBoxLayout()
        row1.addWidget(new_label("样本满意度:"))
        self.box1 = QComboBox()
        self.box1.addItems(["满意", "不满意"])
        row1.addWidget(self.box1)
        _lay_sample.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(new_label("总细胞数"))
        self.box2 = QComboBox()
        self.box2.addItems([">5000个细胞", "其他"])
        row2.addWidget(self.box2)
        _lay_sample.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(new_label("颈管细胞:"))
        self.option1_1 = QRadioButton("有")
        self.option1_2 = QRadioButton("无")
        self.option1_1.setChecked(True)
        row3.addWidget(self.option1_1)
        row3.addWidget(self.option1_2)
        row3.addStretch(1)
        _lay_sample.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(new_label("化生细胞:"))
        self.option2_1 = QRadioButton("有")
        self.option2_2 = QRadioButton("无")
        self.option2_1.setChecked(True)
        row4.addWidget(self.option2_1)
        row4.addWidget(self.option2_2)
        row4.addStretch(1)
        _lay_sample.addLayout(row4)

        row5 = QHBoxLayout()
        row5.addWidget(new_label("炎症程度:"))
        self.box5 = QComboBox()
        self.box5.addItems(["无", "轻度", "中度", "重度", "其他"])
        row5.addWidget(self.box5)
        _lay_sample.addLayout(row5)

        sample_group.setContentLayout(_lay_sample)
        layout.addWidget(sample_group)

        # 感染情况
        infection_group = CollapsibleGroupBox("感染情况", start_expanded=True)
        _lay_inf = QVBoxLayout()
        for option in ["放线菌", "菌群转变", "滴虫感染", "霉菌感染", "HPV感染", "疱疹病毒感染"]:
            cb = QCheckBox(option)
            cb.toggled.connect(lambda checked, text=option: self.on_checkbox_toggled_1(text, checked))
            _lay_inf.addWidget(cb)
        infection_group.setContentLayout(_lay_inf)
        layout.addWidget(infection_group)

        # 鳞状上皮细胞
        squamous_group = CollapsibleGroupBox("鳞状细胞", start_expanded=True)
        _lay_sq = QGridLayout()
        opts1 = [
            "意义不明确(ASC-US)", "不除外高级别鳞状上皮内病变(ASC-H)",
            "低级别鳞状上皮内病变(LSIL)", "高级别鳞状上皮内病变(HSIL)", "鳞状细胞癌"
        ]
        for i, opt in enumerate(opts1):
            cb = QCheckBox(opt)
            cb.toggled.connect(lambda checked, text=opt: self.on_checkbox_toggled_2(text, checked))
            _lay_sq.addWidget(cb, i // 2, i % 2)
        _lay_sq.setColumnStretch(0, 1)
        _lay_sq.setColumnStretch(1, 1)
        squamous_group.setContentLayout(_lay_sq)
        layout.addWidget(squamous_group)

        # 腺上皮细胞
        gland_group = CollapsibleGroupBox("腺细胞", start_expanded=False)
        _lay_gl = QGridLayout()
        opts2 = [
            "子宫颈管腺细胞", "子宫内膜腺细胞", "腺细胞",
            "子宫颈管腺细胞，倾向于肿瘤性", "腺细胞，倾向于肿瘤性",
            "子宫颈管腺癌", "子宫内膜腺癌", "子宫外腺癌", "未指明类型腺癌"
        ]
        for i, opt in enumerate(opts2):
            cb = QCheckBox(opt)
            cb.toggled.connect(lambda checked, text=opt: self.on_checkbox_toggled_3(text, checked))
            _lay_gl.addWidget(cb, i // 3, i % 3)
        _lay_gl.setColumnStretch(0, 1)
        _lay_gl.setColumnStretch(1, 1)
        _lay_gl.setColumnStretch(2, 1)
        gland_group.setContentLayout(_lay_gl)
        layout.addWidget(gland_group)

        # 截图
        capture_group = CollapsibleGroupBox("截图", start_expanded=False)
        _lay_cap = QHBoxLayout()
        _lay_cap.addWidget(QLabel("选取截图"))
        btn_capture = QPushButton("📷 点击截取")
        btn_capture.setFixedSize(150, 80)
        btn_capture.setStyleSheet("border:2px dashed gray; background:#FAFAFA;")
        _lay_cap.addWidget(btn_capture)
        _lay_cap.addStretch(1)
        capture_group.setContentLayout(_lay_cap)
        layout.addWidget(capture_group)

        # 诊断与建议
        result_group = CollapsibleGroupBox("诊断与建议", start_expanded=True)
        _lay_res = QVBoxLayout()
        self.box_line_5 = QComboBox()
        self.box_line_5.addItems(["未见上皮内病变或恶性细胞 (NILM)", "ASC-US", "LSIL", "HSIL", "鳞癌", "其他"])
        _lay_res.addWidget(QLabel("诊断结果"))
        _lay_res.addWidget(self.box_line_5)
        self.box_line_6 = QComboBox()
        self.box_line_6.addItems(["请选择", "建议 HPV 检测", "建议 6 个月复查", "建议阴道镜活检", "其他"])
        _lay_res.addWidget(QLabel("附注建议"))
        _lay_res.addWidget(self.box_line_6)
        result_group.setContentLayout(_lay_res)
        layout.addWidget(result_group)

        layout.addStretch(1)

        self.setStyleSheet("""
            QGroupBox {
                font-size: 14px; font-weight: bold; color: #0D47A1;
                border: 2px solid #64B5F6; border-radius: 8px;
                margin-top: 14px; background-color: #F5FAFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top center;
                padding: 4px 12px;
            }
        """)

    # 选项记录（后续可以导出 JSON）
    def on_checkbox_toggled_1(self, text, checked):
        if checked:
            self.selected_options_1[text] = True
        else:
            self.selected_options_1.pop(text, None)

    def on_checkbox_toggled_2(self, text, checked):
        if checked:
            self.selected_options_2[text] = True
        else:
            self.selected_options_2.pop(text, None)

    def on_checkbox_toggled_3(self, text, checked):
        if checked:
            self.selected_options_3[text] = True
        else:
            self.selected_options_3.pop(text, None)


# ---------- 独立可跑的 InfoWidget（可选） ----------
class InfoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.host = OverlayHost(self)
        layout.addWidget(self.host)

        page = QWidget()
        v = QVBoxLayout(page)
        self.form = InfoFormWidget(page)
        v.addWidget(self.form)
        self.host.tab.addTab(page, "医生标注")

        self.host.drawer.lbl_title.setText("医生标注")
        self.host.drawer.scroll_layout.addWidget(self.form)
        self.host.drawer.scroll_layout.addStretch(1)
