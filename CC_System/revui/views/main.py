import sys
from PySide6.QtCore import QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QStackedWidget, QVBoxLayout, QDialog

from LoginDialog import LoginDialog
from MainWidget import MainWidget
from QueueWork import QueueWork


class QueueAndMainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.stacked_widget = QStackedWidget()

        self.main_interface = MainWidget()
        self.queue_interface = QueueWork()

        self.stacked_widget.addWidget(self.queue_interface)
        self.stacked_widget.addWidget(self.main_interface)

        self.main_interface.show_queue_btn.clicked.connect(self.show_queue_interface)
        self.queue_interface.queue_widget.show_work_btn.clicked.connect(self.show_main_interface)

        layout = QVBoxLayout(self)
        layout.addWidget(self.stacked_widget)

        self._window_style()

    def _window_style(self):
        self.setWindowTitle("宫颈癌细胞病理学 AI 辅助诊断系统")
        self.setStyleSheet("""
            QComboBox {
                border: 2px solid white;
            }
            QComboBox:hover {
                border-color: lightgray;
            }
        """)

    def show_queue_interface(self):
        self.stacked_widget.setCurrentIndex(0)

    def show_main_interface(self):
        self.stacked_widget.setCurrentIndex(1)

    def showEvent(self, event: QEvent):
        screen = QGuiApplication.primaryScreen()
        if screen:
            screen_geometry = screen.geometry()
            window_geometry = self.geometry()
            x = (screen_geometry.width() - window_geometry.width()) // 2
            y = (screen_geometry.height() - window_geometry.height()) // 2
            self.move(x, y)
        super().showEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec() == QDialog.Accepted:
        window = QueueAndMainWindow()
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)
