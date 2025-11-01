from typing import Optional, Tuple  # Python 3.9 兼容：使用 Optional/Tuple 而不是 X | Y
from PySide6 import QtCore, QtWidgets


class SolveAssemblyDialog(QtWidgets.QDialog):
    """
    “求解装配”对话框
    - 装配 ID 可留空，表示使用“最新装配”
    - 迭代次数默认 1
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("求解装配")
        self.setModal(True)
        self.resize(380, 140)

        self.asmEdit = QtWidgets.QLineEdit(self)
        self.asmEdit.setPlaceholderText("装配 UUID（可留空=最新装配）")

        self.iterSpin = QtWidgets.QSpinBox(self)
        self.iterSpin.setRange(1, 1000)
        self.iterSpin.setValue(1)

        form = QtWidgets.QFormLayout()
        form.addRow("装配 ID：", self.asmEdit)
        form.addRow("迭代次数：", self.iterSpin)

        btnOk = QtWidgets.QPushButton("开始求解", self)
        btnCancel = QtWidgets.QPushButton("取消", self)

        btnBox = QtWidgets.QHBoxLayout()
        btnBox.addStretch(1)
        btnBox.addWidget(btnOk)
        btnBox.addWidget(btnCancel)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btnBox)

        btnOk.clicked.connect(self.accept)
        btnCancel.clicked.connect(self.reject)

    def values(self) -> Tuple[Optional[str], int]:
        """
        返回用户输入：
        - assembly_id: Optional[str]
        - iterations: int
        """
        asm_id = self.asmEdit.text().strip() or None
        iterations = int(self.iterSpin.value())
        return asm_id, iterations