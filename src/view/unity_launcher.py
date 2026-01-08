# src/view/unity_launcher. py
"""Unity人体展示程序启动器 - 极简版"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QLineEdit,
                               QFileDialog, QMessageBox, QGroupBox)
from PySide6.QtCore import Qt
import subprocess
import os


class UnityLauncherWidget(QWidget):
    """Unity人体展示程序启动器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.unity_process = None
        self.unity_exe_path = ""
        self.setup_ui()
        self.load_saved_path()

    def setup_ui(self):
        """构建UI"""
        layout = QVBoxLayout(self)

        # ===== 路径配置 =====
        path_group = QGroupBox("Unity程序路径")
        path_layout = QHBoxLayout()

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择 solid.exe 文件")
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit)

        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self.browse_unity_exe)
        path_layout.addWidget(btn_browse)

        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # ===== 启动按钮 =====
        self.btn_launch = QPushButton("🚀 启动人体展示程序")
        self.btn_launch.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 16px;
                padding: 15px;
                border-radius:  5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.btn_launch.clicked.connect(self.launch_unity)
        self.btn_launch.setEnabled(False)
        layout.addWidget(self.btn_launch)

        # ===== 状态显示 =====
        self.status_label = QLabel("● 未启动")
        self.status_label.setStyleSheet("color: gray; font-size: 14px; padding: 10px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        layout.addStretch()

    def browse_unity_exe(self):
        """浏览选择Unity程序"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择Unity人体展示程序",
            "",
            "可执行文件 (solid.exe);;所有文件 (*.*)"
        )

        if file_path:
            self.unity_exe_path = file_path
            self.path_edit.setText(file_path)
            self.save_path()
            self.btn_launch.setEnabled(True)

    def launch_unity(self):
        """启动Unity程序"""
        if not self.unity_exe_path or not os.path.exists(self.unity_exe_path):
            QMessageBox.warning(self, "错误", "请先选择有效的Unity程序路径！")
            return

        try:
            # 直接启动Unity进程
            self.unity_process = subprocess.Popen([self.unity_exe_path])

            # 更新状态
            self.status_label.setText("● 已启动")
            self.status_label.setStyleSheet("color: green; font-size: 14px; padding: 10px;")

            print(f"Unity已启动，PID: {self.unity_process.pid}")

        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"无法启动Unity程序：\n{str(e)}")

    def save_path(self):
        """保存路径到. env"""
        try:
            from dotenv import set_key, find_dotenv
            dotenv_path = find_dotenv(usecwd=True)
            if dotenv_path:
                set_key(dotenv_path, "UNITY_EXE_PATH", self.unity_exe_path)
        except:
            pass

    def load_saved_path(self):
        """加载保存的路径"""
        saved_path = os.getenv("UNITY_EXE_PATH", "")
        if saved_path and os.path.exists(saved_path):
            self.unity_exe_path = saved_path
            self.path_edit.setText(saved_path)
            self.btn_launch.setEnabled(True)