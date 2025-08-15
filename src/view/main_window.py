from typing import List, Dict, Any, Optional
import os

from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
                               QFileDialog, QSplitter, QTabWidget,
                               QWidget, QTreeWidget, QTreeWidgetItem, QProgressBar,
                               QStatusBar, QMessageBox, QGroupBox, QFormLayout,
                               QDoubleSpinBox, QPushButton, QSlider, QToolBar,
                               QCheckBox)  # 添加QCheckBox导入
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QIcon, QAction

from OCC.Core.TopoDS import TopoDS_Shape
# 修改后端加载
from OCC.Display.backend import load_backend

load_backend("pyside6")  # 使用正确的后端名称 "pyside6" 而不是 "qt-pyside6"
from OCC.Display.qtDisplay import qtViewer3d

from ..model.geometry import GeometricPrimitive


class ParameterControlPanel(QWidget):
    """参数控制面板 - 显示和编辑几何体参数"""

    parameterChanged = Signal(dict)
    previewToggled = Signal(bool)  # 添加新信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()
        self.parameters = {}
        self.controls = {}

        # 创建参数编辑表单
        self.param_group = QGroupBox("参数")
        self.param_group.setLayout(self.form_layout)
        self.main_layout.addWidget(self.param_group)

        # 创建预览选项
        self.preview_layout = QHBoxLayout()
        self.preview_checkbox = QCheckBox("显示参数预览")
        self.preview_checkbox.setChecked(True)
        self.preview_checkbox.stateChanged.connect(self._on_preview_toggled)
        self.preview_layout.addWidget(self.preview_checkbox)
        self.main_layout.addLayout(self.preview_layout)

        # 创建应用按钮
        self.button_layout = QHBoxLayout()
        self.apply_button = QPushButton("应用修改")
        self.apply_button.clicked.connect(self._on_apply)
        self.button_layout.addWidget(self.apply_button)
        self.main_layout.addLayout(self.button_layout)

        # 添加弹性空间
        self.main_layout.addStretch(1)

    def _on_preview_toggled(self, state):
        """处理预览开关状态变化"""
        # 添加调试输出
        print(f"预览复选框状态变化: {state}")

        # 使用明确的值比较
        is_checked = (state == Qt.CheckState.Checked.value)  # 或使用 state == 2
        print(f"预览是否启用: {is_checked}")

        # 发出信号
        self.previewToggled.emit(is_checked)

    def set_primitive(self, primitive: GeometricPrimitive):
        """设置当前几何体并更新界面"""
        # 清除现有控件
        self._clear_form()

        # 获取参数
        self.parameters = primitive.get_params()

        # 创建对应的编辑控件
        for name, value in self.parameters.items():
            # 跳过类型
            if name == "type":
                continue

            # 处理不同类型的参数
            if isinstance(value, (list, tuple)) and len(value) == 3:
                # 3D向量 (x,y,z)
                self._add_vector_control(name, value)
            elif isinstance(value, (int, float)):
                # 数值
                self._add_numeric_control(name, value)
            # 其他类型可以按需添加

    def _clear_form(self):
        """清除表单中的所有控件"""
        # 移除所有行
        while self.form_layout.rowCount() > 0:
            # 获取行中的控件
            label_item = self.form_layout.itemAt(0, QFormLayout.LabelRole)
            field_item = self.form_layout.itemAt(0, QFormLayout.FieldRole)

            # 如果控件存在，删除它
            if label_item:
                label = label_item.widget()
                if label:
                    self.form_layout.removeWidget(label)
                    label.deleteLater()

            if field_item:
                field = field_item.widget()
                if field:
                    self.form_layout.removeWidget(field)
                    field.deleteLater()

            # 移除行
            self.form_layout.removeRow(0)

        # 清除控件字典
        self.controls.clear()

    def _add_vector_control(self, name, value):
        """添加向量(x,y,z)控件"""
        # 创建向量编辑的组合控件
        vector_widget = QWidget()
        vector_layout = QHBoxLayout(vector_widget)
        vector_layout.setContentsMargins(0, 0, 0, 0)

        # 创建x,y,z的编辑框
        x_spin = QDoubleSpinBox()
        x_spin.setRange(-1000, 1000)
        x_spin.setValue(value[0])
        x_spin.setDecimals(4)

        y_spin = QDoubleSpinBox()
        y_spin.setRange(-1000, 1000)
        y_spin.setValue(value[1])
        y_spin.setDecimals(4)

        z_spin = QDoubleSpinBox()
        z_spin.setRange(-1000, 1000)
        z_spin.setValue(value[2])
        z_spin.setDecimals(4)

        # 添加到布局
        vector_layout.addWidget(QLabel("X:"))
        vector_layout.addWidget(x_spin)
        vector_layout.addWidget(QLabel("Y:"))
        vector_layout.addWidget(y_spin)
        vector_layout.addWidget(QLabel("Z:"))
        vector_layout.addWidget(z_spin)

        # 添加到表单
        display_name = name.replace("_", " ").title()
        self.form_layout.addRow(display_name, vector_widget)

        # 保存控件引用
        self.controls[name] = (x_spin, y_spin, z_spin)

    def _add_numeric_control(self, name, value):
        """添加数值编辑控件"""
        spin_box = QDoubleSpinBox()

        # 设置范围和精度
        if name in ["radius", "height", "width", "major_radius", "minor_radius"]:
            # 尺寸类参数
            spin_box.setRange(0.001, 1000)
            spin_box.setSingleStep(0.1)
        elif name in ["semi_angle"]:
            # 角度类参数
            spin_box.setRange(0, 89)
            spin_box.setSingleStep(1)
            spin_box.setSuffix("°")
        else:
            # 其他数值
            spin_box.setRange(-1000, 1000)
            spin_box.setSingleStep(0.1)

        spin_box.setValue(value)
        spin_box.setDecimals(4)

        # 添加到表单
        display_name = name.replace("_", " ").title()
        self.form_layout.addRow(display_name, spin_box)

        # 保存控件引用
        self.controls[name] = spin_box

    def _on_apply(self):
        """应用按钮点击事件"""
        # 收集修改后的参数
        new_params = {"type": self.parameters.get("type", "")}

        for name, control in self.controls.items():
            if isinstance(control, tuple) and len(control) == 3:
                # 向量控件
                x_spin, y_spin, z_spin = control
                new_params[name] = (x_spin.value(), y_spin.value(), z_spin.value())
            elif isinstance(control, QDoubleSpinBox):
                # 数值控件
                new_params[name] = control.value()

        # 发送修改信号
        self.parameterChanged.emit(new_params)


class GeometryTreeWidget(QTreeWidget):
    """几何体树形视图"""

    primitiveSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 设置列标题
        self.setHeaderLabels(["几何体"])
        self.setIconSize(QSize(16, 16))

        # 连接选择信号
        self.itemSelectionChanged.connect(self._on_selection_changed)

        # 当前几何体列表
        self.primitives = []

    def set_primitives(self, primitives: List[GeometricPrimitive]):
        """设置几何体列表"""
        self.primitives = primitives
        self._update_tree()

    def _update_tree(self):
        """更新树形视图"""
        self.clear()

        # 添加每个几何体
        for i, primitive in enumerate(self.primitives):
            item = QTreeWidgetItem([f"{primitive.type.title()} #{i + 1}"])

            # 添加图标 (实际应用中应根据几何体类型选择不同图标)
            # item.setIcon(0, QIcon("path/to/icon.png"))

            # 添加详情
            details = QTreeWidgetItem([f"匹配度: {primitive.fitting_score:.2f}"])
            item.addChild(details)

            # 添加参数
            params = primitive.get_params()
            for name, value in params.items():
                if name != "type":
                    display_name = name.replace("_", " ").title()
                    param_item = QTreeWidgetItem([f"{display_name}: {value}"])
                    item.addChild(param_item)

            # 添加到树
            self.addTopLevelItem(item)

    def _on_selection_changed(self):
        """处理选择变化"""
        selected_items = self.selectedItems()
        if selected_items:
            # 获取顶层项
            item = selected_items[0]
            while item.parent():
                item = item.parent()

            # 获取索引
            index = self.indexOfTopLevelItem(item)
            if 0 <= index < len(self.primitives):
                self.primitiveSelected.emit(index)


class MainWindow(QMainWindow):
    """主窗口"""

    # 定义信号
    open_file_requested = Signal(str)
    save_file_requested = Signal(str)
    modify_primitive_requested = Signal(int, dict)
    update_preview_requested = Signal(int, bool)  # 添加预览更新信号
    undo_requested = Signal(int)
    redo_requested = Signal(int)

    def __init__(self):
        super().__init__()

        # 设置窗口属性
        self.setWindowTitle("CAD几何体分割与参数化系统")
        self.resize(1200, 800)

        # 添加预览状态变量
        self.preview_enabled = True

        # 创建状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)

        # 创建进度条
        self.progressBar = QProgressBar()
        self.progressBar.setMaximumWidth(200)
        self.progressBar.setVisible(False)
        self.statusBar.addPermanentWidget(self.progressBar)

        # 创建菜单
        self._create_menus()

        # 创建工具栏
        self._create_toolbars()

        # 创建主布局
        self._create_layout()

        # 当前选中的几何体索引
        self.current_primitive_index = -1

    def _create_menus(self):
        """创建菜单"""
        # 文件菜单
        file_menu = self.menuBar().addMenu("文件")

        open_action = QAction("打开", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_file)
        file_menu.addAction(open_action)

        save_action = QAction("保存", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._on_save_file)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 编辑菜单
        edit_menu = self.menuBar().addMenu("编辑")

        undo_action = QAction("撤销", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._on_undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction("重做", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self._on_redo)
        edit_menu.addAction(redo_action)

        # 视图菜单
        view_menu = self.menuBar().addMenu("视图")

        reset_view_action = QAction("重置视图", self)
        reset_view_action.triggered.connect(self._on_reset_view)
        view_menu.addAction(reset_view_action)

        # 帮助菜单
        help_menu = self.menuBar().addMenu("帮助")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _create_toolbars(self):
        """创建工具栏"""
        # 主工具栏
        main_toolbar = QToolBar("主工具栏")
        self.addToolBar(main_toolbar)

        # 添加工具按钮
        open_action = QAction("打开", self)
        open_action.triggered.connect(self._on_open_file)
        main_toolbar.addAction(open_action)

        save_action = QAction("保存", self)
        save_action.triggered.connect(self._on_save_file)
        main_toolbar.addAction(save_action)

        main_toolbar.addSeparator()

        undo_action = QAction("撤销", self)
        undo_action.triggered.connect(self._on_undo)
        main_toolbar.addAction(undo_action)

        redo_action = QAction("重做", self)
        redo_action.triggered.connect(self._on_redo)
        main_toolbar.addAction(redo_action)

    def _create_layout(self):
        """创建主布局"""
        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧面板
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 几何体树
        self.geometry_tree = GeometryTreeWidget()
        self.geometry_tree.primitiveSelected.connect(self._on_primitive_selected)
        left_layout.addWidget(QLabel("几何体列表"))
        left_layout.addWidget(self.geometry_tree)

        # 参数面板
        self.param_panel = ParameterControlPanel()
        self.param_panel.parameterChanged.connect(self._on_parameter_changed)
        self.param_panel.previewToggled.connect(self._on_preview_toggled)  # 连接新信号
        left_layout.addWidget(QLabel("参数编辑"))
        left_layout.addWidget(self.param_panel)

        # 添加左侧面板到分割器
        splitter.addWidget(left_panel)

        # 右侧 3D 视图
        self.view_panel = QWidget()
        view_layout = QVBoxLayout(self.view_panel)
        view_layout.setContentsMargins(0, 0, 0, 0)

        # 创建 OCC 3D 视图
        self.canvas = qtViewer3d(self.view_panel)
        view_layout.addWidget(self.canvas)

        # 添加视图面板到分割器
        splitter.addWidget(self.view_panel)

        # 设置分割比例
        splitter.setSizes([300, 900])  # 左侧面板 300px，右侧视图 900px

        # 初始化视图
        self.canvas.InitDriver()
        self._init_view()

    def _init_view(self):
        """初始化3D视图"""
        # 修复: 应该设置为QApplication实例而不是MainWindow实例
        from PySide6.QtWidgets import QApplication
        self.canvas.qApp = QApplication.instance()

        # 修复渐变颜色设置
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCC.Core.Aspect import Aspect_GFM_VER  # 垂直渐变

        # 创建颜色对象
        top_color = Quantity_Color(210 / 255, 222 / 255, 236 / 255, Quantity_TOC_RGB)  # 上方颜色
        bottom_color = Quantity_Color(255 / 255, 255 / 255, 255 / 255, Quantity_TOC_RGB)  # 下方颜色

        # 设置渐变背景
        self.canvas._display.View.SetBgGradientColors(top_color, bottom_color, Aspect_GFM_VER)

        # 设置视图方向
        self.canvas._display.View_Top()
        self.canvas._display.View_Iso()
        self.canvas._display.FitAll()

    def _on_preview_toggled(self, enabled):
        """处理预览开关状态变化"""
        print(f"MainWindow 收到预览状态切换: {enabled}")
        self.preview_enabled = enabled

        # 如果当前有选中的几何体，刷新显示
        if self.current_primitive_index >= 0:
            print(f"更新预览显示，当前索引: {self.current_primitive_index}, 预览状态: {enabled}")
            self.update_preview_requested.emit(self.current_primitive_index, enabled)

    @Slot(str)
    def set_status(self, message: str):
        """设置状态栏信息"""
        self.statusBar.showMessage(message)

    @Slot(int)
    def set_progress(self, percent: int):
        """设置进度条"""
        if percent < 0:
            self.progressBar.setVisible(False)
        else:
            self.progressBar.setVisible(True)
            self.progressBar.setValue(percent)

    def show_error(self, title: str, message: str):
        """显示错误对话框"""
        QMessageBox.critical(self, title, message)

    def show_info(self, title: str, message: str):
        """显示信息对话框"""
        QMessageBox.information(self, title, message)

    def set_primitives(self, primitives: List[GeometricPrimitive]):
        """设置几何体列表并更新UI"""
        # 更新树
        self.geometry_tree.set_primitives(primitives)

        # 清除视图
        self.canvas._display.EraseAll()

        # 显示几何体
        for primitive in primitives:
            for face in primitive.faces:
                self.canvas._display.DisplayShape(face, update=False)

        # 更新视图
        self.canvas._display.View_Iso()
        self.canvas._display.FitAll()
        self.canvas._display.Repaint()

    def update_primitive(self, index: int, new_shape: TopoDS_Shape):
        """更新几何体显示"""
        # 如果索引有效
        if index >= 0:
            # 清除特定几何体
            # 这里简化处理，重新显示所有几何体
            self.canvas._display.EraseAll()

            # 获取所有几何体
            primitives = self.geometry_tree.primitives

            # 显示几何体
            for i, primitive in enumerate(primitives):
                if i == index:
                    # 显示修改后的形状
                    self.canvas._display.DisplayShape(new_shape, update=False, color="YELLOW")
                else:
                    # 显示原始面
                    for face in primitive.faces:
                        self.canvas._display.DisplayShape(face, update=False)

            # 更新视图
            self.canvas._display.FitAll()
            self.canvas._display.Repaint()

    def show_original_with_preview(self, geometry_id, original_shape, preview_shape):
        """显示原始形状和预览形状"""
        if self.canvas._display is None:
            return

        try:
            # 清除之前的显示
            self.canvas._display.EraseAll()

            # 获取所有几何体
            primitives = self.geometry_tree.primitives

            # 显示几何体
            for i, primitive in enumerate(primitives):
                if i == geometry_id:
                    # 显示当前编辑的几何体的原始形状
                    self.canvas._display.DisplayShape(original_shape, update=False, color="BLUE")

                    # 如果有预览形状并且预览已启用，以半透明方式显示
                    if preview_shape and self.preview_enabled:
                        # 显示预览形状
                        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
                        preview_color = Quantity_Color(0.0, 0.8, 0.2, Quantity_TOC_RGB)  # 绿色
                        self.canvas._display.DisplayShape(preview_shape, color=preview_color,
                                                          transparency=0.7, update=False)
                else:
                    # 显示其他几何体
                    for face in primitive.faces:
                        self.canvas._display.DisplayShape(face, update=False)

            # 更新显示
            self.canvas._display.FitAll()
            self.canvas._display.Repaint()

        except Exception as e:
            print(f"显示预览失败: {str(e)}")

    def _on_open_file(self):
        """打开文件事件处理"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开STEP文件", "", "STEP Files (*.step *.stp);;All Files (*.*)")

        if file_path:
            self.open_file_requested.emit(file_path)

    def _on_save_file(self):
        """保存文件事件处理"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存STEP文件", "", "STEP Files (*.step *.stp)")

        if file_path:
            # 确保文件有正确的扩展名
            if not file_path.lower().endswith(('.step', '.stp')):
                file_path += '.step'

            self.save_file_requested.emit(file_path)

    def _on_primitive_selected(self, index: int):
        """几何体选择事件处理"""
        self.current_primitive_index = index

        # 更新参数面板
        primitives = self.geometry_tree.primitives
        if 0 <= index < len(primitives):
            self.param_panel.set_primitive(primitives[index])

            # 高亮显示选中的几何体
            self.canvas._display.EraseAll()

            # 显示几何体
            for i, primitive in enumerate(primitives):
                if i == index:
                    # 高亮显示选中的几何体
                    for face in primitive.faces:
                        self.canvas._display.DisplayShape(face, update=False, color="GREEN")
                else:
                    # 正常显示其他几何体
                    for face in primitive.faces:
                        self.canvas._display.DisplayShape(face, update=False)

            # 更新视图
            self.canvas._display.Repaint()

    def _on_parameter_changed(self, parameters: Dict[str, Any]):
        """参数变更事件处理"""
        if self.current_primitive_index >= 0:
            # 将预览状态与参数一起传递
            params_with_preview = parameters.copy()
            params_with_preview["show_preview"] = self.preview_enabled
            self.modify_primitive_requested.emit(self.current_primitive_index, params_with_preview)

    def _on_undo(self):
        """撤销事件处理"""
        if self.current_primitive_index >= 0:
            self.undo_requested.emit(self.current_primitive_index)

    def _on_redo(self):
        """重做事件处理"""
        if self.current_primitive_index >= 0:
            self.redo_requested.emit(self.current_primitive_index)

    def _on_reset_view(self):
        """重置视图事件处理"""
        self.canvas._display.View_Iso()
        self.canvas._display.FitAll()

    def _on_about(self):
        """关于对话框"""
        QMessageBox.about(
            self,
            "关于",
            "CAD几何体分割与参数化系统\n\n"
            "版本: 1.0\n"
            "开发者: littlegoose1\n\n"
            "本系统用于CAD模型的几何体分割与参数化，支持多种基本几何体的识别和修改。"
        )