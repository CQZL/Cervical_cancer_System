from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtGui import QFontDatabase, QFont

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 统一窗口尺寸
        self.setFixedSize(800, 600)  # 与infoWidget保持一致
        self._center_window()  # 添加居中方法
        self.setWindowTitle("系统登录")
        self._init_ui()

        # 预设账号密码（可根据需要修改）
        self.valid_credentials = {
            "1": "1",
            "doctor": "med2023"
        }

    def _init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(100, 50, 100, 50)  # 适当边距

        # 添加顶部伸缩空间
        main_layout.addStretch(1)
        top_layout = QVBoxLayout()

        # 添加title
        title = QLabel("宫颈癌细胞病理学AI辅助诊断系统")
        title.setFont(QFont("PingFang SC", 24, QFont.Bold)) # 微软雅黑
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #0000FF; margin-bottom: 40px;")

        top_layout.addWidget(title)

        main_layout.addLayout(top_layout)

        # 使用网格布局实现响应式
        form_layout = QGridLayout()
        form_layout.setVerticalSpacing(20)
        form_layout.setHorizontalSpacing(15)

        # 用户名标签
        user_label = QLabel("用户名:")
        user_label.setStyleSheet("font-size: 16px; color: #34495e;")

        # 密码标签
        pwd_label = QLabel("密码:")
        pwd_label.setStyleSheet("font-size: 16px; color: #34495e;")

        # 输入框样式（百分比宽度）
        input_style = """
                     QLineEdit {
                         border: 2px solid #bdc3c7;
                         border-radius: 8px;
                         padding: 12px;
                         font-size: 16px;
                         min-width: 200px;
                     }
                     QLineEdit:focus {
                         border-color: #3498db;
                     }
                 """

        self.username_input = QLineEdit()
        self.username_input.setStyleSheet(input_style)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setStyleSheet(input_style)

        # 将组件添加到网格布局
        form_layout.addWidget(user_label, 0, 0)
        form_layout.addWidget(self.username_input, 0, 1)
        form_layout.addWidget(pwd_label, 1, 0)
        form_layout.addWidget(self.password_input, 1, 1)

        # 输入框列设置扩展
        form_layout.setColumnStretch(1, 1)

        # 将表单添加到主布局
        main_layout.addLayout(form_layout)
        main_layout.addStretch(1)  # 底部伸缩空间

        # 按钮容器
        btn_container = QHBoxLayout()
        btn_container.addStretch(1)

        login_btn = QPushButton("登 录")
        login_btn.setFixedSize(200, 50)
        login_btn.setStyleSheet("""
                     QPushButton {
                         background-color: #3498db;
                         color: white;
                         border: none;
                         border-radius: 8px;
                         font-size: 18px;
                     }
                     QPushButton:hover {
                         background-color: #2980b9;
                     }
                 """)
        login_btn.clicked.connect(self._check_credentials)

        btn_container.addWidget(login_btn)

        btn_container.addStretch(1)

        main_layout.addLayout(btn_container)
        main_layout.addStretch(1)

        # 添加logo
        logo_label = QLabel()
        pixmap = QPixmap('../../icon/logo5.png')
        scaled_pixmap = pixmap.scaled(150, 150, Qt.KeepAspectRatio)
        logo_label.setPixmap(scaled_pixmap)
        logo_label.setScaledContents(True)
        logo_label.setFixedSize(280, 40)

        # 创建一个水平布局用于放置 logo 标签到底部居中
        logo_layout = QHBoxLayout()
        logo_layout.addStretch(1)
        logo_layout.addWidget(logo_label, alignment=Qt.AlignCenter)
        logo_layout.addStretch(1)

        main_layout.addLayout(logo_layout)

        self.setLayout(main_layout)

    def _center_window(self):
        """窗口居中显示"""
        frame_geo = self.frameGeometry()
        screen_center = self.screen().availableGeometry().center()
        frame_geo.moveCenter(screen_center)
        self.move(frame_geo.topLeft())

    def _check_credentials(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "输入错误", "用户名和密码不能为空")
            return

        if self.valid_credentials.get(username) == password:
            self.accept()  # 关闭对话框并返回 QDialog.Accepted
        else:
            QMessageBox.critical(self, "登录失败", "用户名或密码错误")
            self.password_input.clear()

