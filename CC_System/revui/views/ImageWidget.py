# -*- coding: utf-8 -*-
# @Time : 2025/1/11 19:35
# @Author : Li Desheng
# @File : ImageWidget.py
# @Project : Interfaces
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class ImageWidget(QWidget):
    def __init__(self, img_path, img_name):
        super().__init__()

        # 设置固定尺寸
        self.setFixedSize(90, 110)  # 图片90x90，文字20高，总高度110

        layout = QVBoxLayout()
        layout.setSpacing(0)  # 移除间距
        layout.setContentsMargins(0, 0, 0, 0)  # 移除边距

        # 创建并配置图片标签
        label_image = QLabel(self)
        pixmap = QPixmap(img_path).scaled(90, 90, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        label_image.setPixmap(pixmap)
        label_image.setStyleSheet("border: none; padding: 0px; margin: 0px;")

        # 创建并配置文字标签
        label_text = QLabel(img_name, self)
        label_text.setAlignment(Qt.AlignCenter)
        label_text.setFixedHeight(20)  # 固定高度
        label_text.setStyleSheet(
            "border: none; "
            "padding: 0px; "
            "margin: 0px; "
            "background-color: white; "
            "color: black; "
            "font-size: 12px; "
            "font-family: Arial;"
        )

        # 添加到布局
        layout.addWidget(label_image)
        layout.addWidget(label_text)

        self.setLayout(layout)
