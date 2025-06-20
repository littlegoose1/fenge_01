#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# main.py - 程序入口点

import sys
import os
import platform

from PySide6.QtWidgets import QApplication

from src.view.main_window import MainWindow
from src.controller.app_controller import ApplicationController


def setup_environment():
    """设置运行环境"""
    # 添加当前目录到模块搜索路径
    if getattr(sys, 'frozen', False):
        # PyInstaller创建的可执行文件中
        application_path = os.path.dirname(sys.executable)
    else:
        # 正常Python环境
        application_path = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, application_path)

    # 设置Qt环境变量
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    # 针对Windows的高DPI支持
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass

    # 设置OpenCASCADE标准位置
    # 根据操作系统设置搜索路径
    if platform.system() == "Windows":
        occ_path = os.path.join(application_path, "occ")
        if os.path.exists(occ_path):
            os.environ["CSF_OCCTResourcePath"] = os.path.join(occ_path, "resources")
            os.environ["CSF_SHMessage"] = os.path.join(occ_path, "resources", "SHMessage")
            os.environ["CSF_XSMessage"] = os.path.join(occ_path, "resources", "XSMessage")
            os.environ["CSF_StandardDefaults"] = os.path.join(occ_path, "resources", "StdResource")
            os.environ["CSF_PluginDefaults"] = os.path.join(occ_path, "resources", "StdResource")
            os.environ["CSF_LANGUAGE"] = "us"
            os.environ["CSF_XCAFDefaults"] = os.path.join(occ_path, "resources", "StdResource")


def main():
    """主函数"""
    # 设置环境
    setup_environment()

    # 创建Qt应用
    app = QApplication(sys.argv)
    app.setApplicationName("CAD几何体分割与参数化系统")

    # 创建主窗口
    main_window = MainWindow()

    # 创建应用控制器
    controller = ApplicationController(main_window)

    # 显示主窗口
    main_window.show()

    # 进入事件循环
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())