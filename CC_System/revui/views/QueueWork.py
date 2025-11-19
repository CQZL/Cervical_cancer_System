import sys
import time
import os
import subprocess
from PySide6.QtCore import Qt, QObject, Signal, QThread, QMutex, QMutexLocker
from PySide6.QtGui import QFont, QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QFileDialog, QMainWindow, QLabel, QHBoxLayout, QFrame,
    QTableWidget, QTableWidgetItem, QMenu, QDialog, QFormLayout, QLineEdit, QDialogButtonBox
)
from MainWidget import MainWidget


APP_FONT = QFont("Microsoft YaHei", 13)


class ConfigDialog(QDialog):
    """配置管理对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFont(APP_FONT)

        layout = QFormLayout()

        # 默认输入路径
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setText("./input")
        layout.addRow("默认文件夹路径:", self.input_path_edit)

        # 输出路径
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setText("./output")
        layout.addRow("输出结果路径:", self.output_path_edit)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_config(self):
        return {
            "input_path": self.input_path_edit.text(),
            "output_path": self.output_path_edit.text()
        }


class ProcessingQueueWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.queue_manager = QueueManager()
        self.init_ui()
        self.connect_signals()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(12)

        # ===== 顶栏 =====
        top_layout = QHBoxLayout()
        logo_label = QLabel()
        pixmap = QPixmap('../../icon/logo1.png')
        scaled_pixmap = pixmap.scaled(60, 40, Qt.KeepAspectRatio)
        logo_label.setPixmap(scaled_pixmap)
        logo_label.setFixedSize(60, 40)

        header = QLabel("宫颈细胞病理学 AI 辅助诊断 - 文件处理队列")
        header.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))

        top_layout.addWidget(logo_label)
        top_layout.addWidget(header)
        top_layout.addStretch()

        # ===== 工具栏 =====
        btn_frame = QFrame()
        btn_frame.setStyleSheet("QFrame { background: #F0F4FF; border-radius: 8px; }")
        btn_container = QHBoxLayout(btn_frame)
        btn_container.setContentsMargins(8, 5, 8, 5)
        btn_container.setSpacing(10)

        self.add_btn = self.create_button("➕ 添加文件")
        self.clear_btn = self.create_button("🗑️ 清空队列")
        self.remove_btn = self.create_button("✖️ 移除选中")
        self.show_work_btn = self.create_button("📊 显示工作")

        for btn in [self.add_btn, self.clear_btn, self.remove_btn, self.show_work_btn]:
            btn_container.addWidget(btn)

        # ===== 队列表格 =====
        self.pending_table = self.create_table(["文件名", "状态", "添加时间"])
        self.processing_table = self.create_table(["文件名", "状态", "时间戳"])

        pending_label = QLabel("待处理队列")
        pending_label.setFont(APP_FONT)
        processing_label = QLabel("处理队列")
        processing_label.setFont(APP_FONT)

        # ===== 确认按钮 =====
        self.confirm_btn = QPushButton("确认添加到处理队列")
        self.confirm_btn.setFont(APP_FONT)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                border-radius: 8px;
                padding: 8px 20px;
                font-size: 14px;
                color: white;
            }
            QPushButton:hover { background-color: #45A049; }
        """)

        # ===== 组装布局 =====
        main_layout.addLayout(top_layout)
        main_layout.addWidget(btn_frame)
        main_layout.addWidget(pending_label)
        main_layout.addWidget(self.pending_table)
        main_layout.addWidget(self.confirm_btn)
        main_layout.addWidget(processing_label)
        main_layout.addWidget(self.processing_table)

        self.setLayout(main_layout)

    def create_button(self, text):
        btn = QPushButton(text)
        btn.setFont(APP_FONT)
        btn.setFixedHeight(36)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2;
                color: white;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #2196F3; }
            QPushButton:pressed { background-color: #1565C0; }
        """)
        return btn

    def create_table(self, headers):
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setFont(APP_FONT)
        table.setStyleSheet("""
            QTableWidget { background: #FAFAFA; border: 1px solid #DDD; }
            QHeaderView::section { background: #E3EFFF; padding: 5px; border: 1px solid #CCC; }
            QTableWidget::item:selected { background: #64B5F6; color: white; }
        """)
        # 添加右键菜单
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self.show_context_menu(pos, t))
        return table

    def show_context_menu(self, pos, table):
        menu = QMenu(self)

        open_action = QAction("📂 打开所在目录", self)
        remove_action = QAction("❌ 移除任务", self)
        retry_action = QAction("🔄 重新处理", self)

        selected_row = table.currentRow()
        if selected_row < 0:
            return

        file_path_item = table.item(selected_row, 0)
        if not file_path_item:
            return
        file_path = file_path_item.text()

        open_action.triggered.connect(lambda: self.open_in_explorer(file_path))
        remove_action.triggered.connect(lambda: table.removeRow(selected_row))
        retry_action.triggered.connect(lambda: self.queue_manager.add_task(file_path))

        menu.addAction(open_action)
        menu.addAction(remove_action)
        menu.addAction(retry_action)
        menu.exec(table.viewport().mapToGlobal(pos))

    def open_in_explorer(self, file_path):
        if os.path.exists(file_path):
            if sys.platform == "win32":
                os.startfile(os.path.dirname(file_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", os.path.dirname(file_path)])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(file_path)])

    def connect_signals(self):
        self.add_btn.clicked.connect(self.add_files)
        self.clear_btn.clicked.connect(self.clear_queue)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.confirm_btn.clicked.connect(self.confirm_selection)

        self.queue_manager.task_added.connect(self.add_processing_item)
        self.queue_manager.task_started.connect(self.update_processing_status)
        self.queue_manager.task_finished.connect(self.handle_task_finished)

    # === 文件操作逻辑 ===
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择WSI文件", "", "WSI Files (*.ndpi *.svs *.tif)")
        for file in files:
            row = self.pending_table.rowCount()
            self.pending_table.insertRow(row)
            self.pending_table.setItem(row, 0, QTableWidgetItem(file))
            self.pending_table.setItem(row, 1, QTableWidgetItem("等待中"))
            self.pending_table.setItem(row, 2, QTableWidgetItem(time.strftime("%Y-%m-%d %H:%M:%S")))

    def confirm_selection(self):
        for row in range(self.pending_table.rowCount()):
            file_item = self.pending_table.item(row, 0)
            if file_item:
                file_path = file_item.text()
                self.queue_manager.add_task(file_path)
        self.pending_table.setRowCount(0)

    def remove_selected(self):
        for row in reversed(range(self.pending_table.rowCount())):
            self.pending_table.removeRow(row)

    def add_processing_item(self, file_path):
        row = self.processing_table.rowCount()
        self.processing_table.insertRow(row)
        self.processing_table.setItem(row, 0, QTableWidgetItem(file_path))
        self.processing_table.setItem(row, 1, QTableWidgetItem("等待处理"))
        self.processing_table.setItem(row, 2, QTableWidgetItem(time.strftime("%H:%M:%S")))

    def update_processing_status(self, file_path):
        for row in range(self.processing_table.rowCount()):
            if self.processing_table.item(row, 0).text() == file_path:
                self.processing_table.setItem(row, 1, QTableWidgetItem("处理中"))

    def handle_task_finished(self, file_path):
        for row in range(self.processing_table.rowCount()):
            if self.processing_table.item(row, 0).text() == file_path:
                self.processing_table.setItem(row, 1, QTableWidgetItem("已完成"))

    def clear_queue(self):
        self.processing_table.setRowCount(0)
        self.queue_manager.clear_queue()


class QueueManager(QObject):
    task_added = Signal(str)
    task_started = Signal(str)
    task_finished = Signal(str)

    def __init__(self):
        super().__init__()
        self.queue = []
        self.mutex = QMutex()
        self.worker = None
        self.running = False

    def add_task(self, file_path):
        with QMutexLocker(self.mutex):
            self.queue.append(file_path)
            self.task_added.emit(file_path)
        self.start_processing()

    def start_processing(self):
        if not self.running:
            self.running = True
            self.worker = Worker(self)
            self.worker.task_started.connect(self.task_started.emit)
            self.worker.task_finished.connect(self.task_finished.emit)
            self.worker.finished.connect(self.on_worker_finished)
            self.worker.start()

    def clear_queue(self):
        with QMutexLocker(self.mutex):
            self.queue.clear()

    def on_worker_finished(self):
        self.running = False


class Worker(QThread):
    task_started = Signal(str)
    task_finished = Signal(str)

    def __init__(self, queue_manager):
        super().__init__()
        self.queue_manager = queue_manager

    def run(self):
        while True:
            with QMutexLocker(self.queue_manager.mutex):
                if not self.queue_manager.queue:
                    break
                file_path = self.queue_manager.queue.pop(0)

            self.task_started.emit(file_path)
            time.sleep(2)  # 模拟处理
            self.task_finished.emit(file_path)


class QueueWork(QMainWindow):
    def __init__(self):
        super().__init__()
        self.queue_widget = ProcessingQueueWidget()
        self.setCentralWidget(self.queue_widget)
        self.setWindowTitle("宫颈细胞病理学 AI 辅助诊断 - 队列管理")

        # ===== 菜单栏 =====
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")

        config_action = QAction("配置管理", self)
        config_action.triggered.connect(self.open_config_dialog)
        settings_menu.addAction(config_action)

    def open_config_dialog(self):
        dialog = ConfigDialog(self)
        if dialog.exec():
            config = dialog.get_config()
            print("配置已更新:", config)