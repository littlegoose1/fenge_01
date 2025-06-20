# src/view/main_window.py
from typing import List, Optional
import os

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QSplitter, QTreeWidget, QTreeWidgetItem,
                              QListWidget, QStatusBar, QToolBar, QMessageBox,
                              QFileDialog, QLabel, QProgressBar, QMenu)
from PySide6.QtGui import QIcon, QAction

from ..view.occ_viewer import OCCViewer
from ..view.parameter_editor import ParameterEditor
from ..model.geometry import GeometricPrimitive


class MainWindow(QMainWindow):
    """应用程序主窗口"""

    open_file_requested = Signal(str)
    save_file_requested = Signal(str)
    modify_primitive_requested = Signal(int, dict)
    undo_requested = Signal(int)
    redo_requested = Signal(int)

    def __init__(self):
        super().__init__()

        self.primitives = []

        self._init_ui()
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_statusbar()

        self.setWindowTitle("CAD几何体分割与参数化系统")
        self.setMinimumSize(1200, 800)

        # 设置窗口图标
        # self.setWindowIcon(QIcon("resources/app_icon.png"))

    def _init_ui(self):
        """初始化用户界面"""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # 主布局
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建分割器
        self.main_splitter = QSplitter(Qt.Horizontal)

        # 创建左侧面板
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)

        # 几何体列表
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["几何体"])
        self.tree_widget.itemClicked.connect(self._on_primitive_selected)

        left_layout.addWidget(QLabel("几何体列表:"))
        left_layout.addWidget(self.tree_widget)

        # 创建中央3D视图
        self.occ_viewer = OCCViewer()
        self.occ_viewer.selection_changed.connect(self._on_viewer_selection_changed)

        # 创建右侧参数面板
        self.parameter_editor = ParameterEditor()
        self.parameter_editor.parameter_changed.connect(self.modify_primitive_requested)
        self.parameter_editor.undo_requested.connect(self.undo_requested)
        self.parameter_editor.redo_requested.connect(self.redo_requested)

        # 添加到分割器
        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.occ_viewer)
        self.main_splitter.addWidget(self.parameter_editor)

        # 设置分割器初始大小
        self.main_splitter.setSizes([200, 600, 300])

        # 添加到主布局
        main_layout.addWidget(self.main_splitter)

    def _create_actions(self):
        """创建动作"""
        # 文件操作
        self.open_action = QAction("打开STEP文件", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self._on_open_file)

        self.save_action = QAction("保存修改", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self._on_save_file)
        self.save_action.setEnabled(False)

        self.exit_action = QAction("退出", self)
        self.exit_action.setShortcut("Alt+F4")
        self.exit_action.triggered.connect(self.close)

        # 视图操作
        self.view_top_action = QAction("顶视图", self)
        self.view_top_action.triggered.connect(self.occ_viewer.view_top)

        self.view_bottom_action = QAction("底视图", self)
        self.view_bottom_action.triggered.connect(self.occ_viewer.view_bottom)

        self.view_left_action = QAction("左视图", self)
        self.view_left_action.triggered.connect(self.occ_viewer.view_left)

        self.view_right_action = QAction("右视图", self)
        self.view_right_action.triggered.connect(self.occ_viewer.view_right)

        self.view_front_action = QAction("前视图", self)
        self.view_front_action.triggered.connect(self.occ_viewer.view_front)

        self.view_rear_action = QAction("后视图", self)
        self.view_rear_action.triggered.connect(self.occ_viewer.view_rear)

        self.view_iso_action = QAction("等轴测视图", self)
        self.view_iso_action.triggered.connect(self.occ_viewer.view_iso)

        self.fit_all_action = QAction("显示全部", self)
        self.fit_all_action.setShortcut("F")
        self.fit_all_action.triggered.connect(self.occ_viewer.fit_all)

        self.wireframe_action = QAction("线框显示", self)
        self.wireframe_action.triggered.connect(self.occ_viewer.set_display_mode_wireframe)

        self.shaded_action = QAction("着色显示", self)
        self.shaded_action.triggered.connect(self.occ_viewer.set_display_mode_shaded)

        self.toggle_grid_action = QAction("显示网格", self)
        self.toggle_grid_action.setCheckable(True)
        self.toggle_grid_action.toggled.connect(self.occ_viewer.toggle_grid)

        self.toggle_axes_action = QAction("显示坐标轴", self)
        self.toggle_axes_action.setCheckable(True)
        self.toggle_axes_action.setChecked(True)
        self.toggle_axes_action.toggled.connect(self.occ_viewer.toggle_axes)

    def _create_menus(self):
        """创建菜单"""
        # 文件菜单
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        # 视图菜单
        view_menu = self.menuBar().addMenu("视图")
        view_menu.addAction(self.view_top_action)
        view_menu.addAction(self.view_bottom_action)
        view_menu.addAction(self.view_left_action)
        view_menu.addAction(self.view_right_action)
        view_menu.addAction(self.view_front_action)
        view_menu.addAction(self.view_rear_action)
        view_menu.addAction(self.view_iso_action)
        view_menu.addSeparator()
        view_menu.addAction(self.fit_all_action)
        view_menu.addSeparator()
        view_menu.addAction(self.wireframe_action)
        view_menu.addAction(self.shaded_action)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_grid_action)
        view_menu.addAction(self.toggle_axes_action)

        # 帮助菜单
        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _create_toolbars(self):
        """创建工具栏"""
        # 文件工具栏
        file_toolbar = self.addToolBar("文件")
        file_toolbar.addAction(self.open_action)
        file_toolbar.addAction(self.save_action)

        # 视图工具栏
        view_toolbar = self.addToolBar("视图")
        view_toolbar.addAction(self.view_iso_action)
        view_toolbar.addAction(self.fit_all_action)
        view_toolbar.addAction(self.wireframe_action)
        view_toolbar.addAction(self.shaded_action)

    def _create_statusbar(self):
        """创建状态栏"""
        self.statusbar = self.statusBar()

        # 状态信息标签
        self.status_label = QLabel("就绪")
        self.statusbar.addWidget(self.status_label, 1)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.statusbar.addPermanentWidget(self.progress_bar)

    def _update_tree_widget(self, primitives: List[GeometricPrimitive]):
        """更新树形控件显示几何体"""
        self.tree_widget.clear()

        for i, primitive in enumerate(primitives):
            item = QTreeWidgetItem([f"{i + 1}. {primitive.type}"])

            # 添加参数作为子项
            params = primitive.get_params()
            for param_name, param_value in params.items():
                if param_name == "type":
                    continue

                if isinstance(param_value, tuple) and len(param_value) == 3:
                    # 向量类型格式化
                    value_str = f"({param_value[0]:.2f}, {param_value[1]:.2f}, {param_value[2]:.2f})"
                elif isinstance(param_value, float):
                    # 浮点数格式化
                    value_str = f"{param_value:.4f}"
                else:
                    value_str = str(param_value)

                param_item = QTreeWidgetItem([f"{param_name}: {value_str}"])
                item.addChild(param_item)

            self.tree_widget.addTopLevelItem(item)
            item.setExpanded(True)

    def set_primitives(self, primitives: List[GeometricPrimitive]):
        """设置几何体列表并更新UI"""
        self.primitives = primitives
        self._update_tree_widget(primitives)
        self.occ_viewer.display_primitives(primitives)
        self.save_action.setEnabled(len(primitives) > 0)

        # 更新状态栏
        self.status_label.setText(f"已加载 {len(primitives)} 个几何体")

    def update_primitive(self, index: int, new_shape):
        """更新几何体显示"""
        if 0 <= index < len(self.primitives):
            self.occ_viewer.update_primitive(index, new_shape)

    def set_status(self, message: str):
        """设置状态栏消息"""
        self.status_label.setText(message)

    def set_progress(self, value: int, maximum: int):
        """设置进度条"""
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(maximum > 0)

    @Slot(QTreeWidgetItem, int)
    def _on_primitive_selected(self, item, column):
        """处理树形控件中几何体选择"""
        # 仅处理顶级项
        if item.parent() is None:
            index = self.tree_widget.indexOfTopLevelItem(item)
            if 0 <= index < len(self.primitives):
                self.occ_viewer.select_primitive(index)
                self.parameter_editor.set_primitive(self.primitives[index], index)

    @Slot(int)
    def _on_viewer_selection_changed(self, index):
        """处理3D视图中几何体选择"""
        if 0 <= index < len(self.primitives):
            # 更新树形控件选择
            self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(index))
            self.parameter_editor.set_primitive(self.primitives[index], index)
        else:
            self.tree_widget.clearSelection()
            self.parameter_editor.set_primitive(None, -1)

    def _on_open_file(self):
        """打开文件对话框"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开STEP文件",
            "",
            "STEP文件 (*.step *.stp);;所有文件 (*.*)"
        )

        if file_path:
            self.open_file_requested.emit(file_path)

    def _on_save_file(self):
        """保存文件对话框"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存STEP文件",
            "",
            "STEP文件 (*.step);;所有文件 (*.*)"
        )

        if file_path:
            self.save_file_requested.emit(file_path)

    def _show_about_dialog(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 CAD几何体分割与参数化系统",
            "CAD几何体分割与参数化系统 v1.0\n\n"
            "一个用于CAD模型几何分割和参数化修改的工具。\n\n"
            "© 2025 littlegoose1"
        )

    def show_error(self, title, message):
        """显示错误对话框"""
        QMessageBox.critical(self, title, message)

    def show_info(self, title, message):
        """显示信息对话框"""
        QMessageBox.information(self, title, message)