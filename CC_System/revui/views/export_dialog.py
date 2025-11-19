from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QFileDialog, QWidget
)
from PySide6.QtCore import Qt
from pathlib import Path

class ExportDialog(QDialog):
    def __init__(self, default_dir: str = "./exports", parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出复核结果")
        self.setModal(True)
        self._dir = QLineEdit(str(default_dir))
        self._btnBrowse = QPushButton("浏览…")
        self._chkCSV = QCheckBox("写出 CSV"); self._chkCSV.setChecked(True)
        self._chkJSON = QCheckBox("写出 JSON"); self._chkJSON.setChecked(False)
        self._chkCopyTiles = QCheckBox("拷贝分类后的 tiles 到 tiles_reviewed/"); self._chkCopyTiles.setChecked(True)
        self._chkOnlyChanged = QCheckBox("仅导出改动项（label != orig_label）"); self._chkOnlyChanged.setChecked(False)
        self._chkIncludeHidden = QCheckBox("包含隐藏项"); self._chkIncludeHidden.setChecked(False)

        row = QHBoxLayout(); row.addWidget(QLabel("输出目录")); row.addWidget(self._dir); row.addWidget(self._btnBrowse)
        hl = QHBoxLayout(); hl.addStretch(1)
        btnOk = QPushButton("导出"); btnCancel = QPushButton("取消")
        hl.addWidget(btnOk); hl.addWidget(btnCancel)

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self._chkCSV)
        lay.addWidget(self._chkJSON)
        lay.addWidget(self._chkCopyTiles)
        lay.addWidget(self._chkOnlyChanged)
        lay.addWidget(self._chkIncludeHidden)
        lay.addStretch(1)
        lay.addLayout(hl)

        self._btnBrowse.clicked.connect(self._browse)
        btnOk.clicked.connect(self.accept)
        btnCancel.clicked.connect(self.reject)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self._dir.text() or "./")
        if d:
            self._dir.setText(d)

    def get_result(self):
        """
        返回：
          out_dir(str), write_csv(bool), write_json(bool),
          copy_tiles(bool), only_changed(bool), include_hidden(bool)
        """
        return (
            self._dir.text().strip(),
            self._chkCSV.isChecked(),
            self._chkJSON.isChecked(),
            self._chkCopyTiles.isChecked(),
            self._chkOnlyChanged.isChecked(),
            self._chkIncludeHidden.isChecked(),
        )
