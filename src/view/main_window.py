from typing import List, Dict, Any,Optional
import os

from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
                               QFileDialog, QSplitter,
                               QWidget, QTreeWidget, QTreeWidgetItem, QProgressBar,
                               QStatusBar, QMessageBox, QGroupBox, QFormLayout,
                               QDoubleSpinBox, QPushButton, QToolBar,
                               QCheckBox, QDialog, QTextEdit, QDialogButtonBox)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Display.backend import load_backend

load_backend("pyside6")
from OCC.Display.qtDisplay import qtViewer3d

from ..model.geometry import GeometricPrimitive
from ..ui.solve_dialog import SolveAssemblyDialog
from src.view.unity_launcher import UnityLauncherWidget
from .equipment_panel import EquipmentPanel

# ✅ 优化：验证结果对话框
class ValidationResultDialog(QDialog):
    """显示验证结果的对话框"""

    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        # 添加图标提示
        header = QLabel(f"<h2>{title}</h2>")
        layout.addWidget(header)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)
        text_edit.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                background-color: #f5f5f5;
            }
        """)
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)



class ParameterControlPanel(QWidget):
    parameterChanged = Signal(dict)
    previewToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)

        self.form_layout = QFormLayout()
        self.param_group = QGroupBox("参数")
        self.param_group.setLayout(self.form_layout)
        self.main_layout.addWidget(self.param_group)

        self.parameters = {}
        self.controls = {}

        row = QHBoxLayout()
        self.preview_checkbox = QCheckBox("显示参数预览")
        self.preview_checkbox.setChecked(True)
        self.preview_checkbox.stateChanged.connect(self._on_preview_toggled)
        row.addWidget(self.preview_checkbox)
        self.main_layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.apply_button = QPushButton("应用修改")
        self.apply_button.clicked.connect(self._on_apply)
        btn_row.addWidget(self.apply_button)
        self.main_layout.addLayout(btn_row)

        self.main_layout.addStretch(1)

    def _on_preview_toggled(self, state: int):
        self.previewToggled.emit(state == Qt.CheckState.Checked.value)

    def set_primitive(self, primitive: GeometricPrimitive):
        self._clear_form()
        self.parameters = primitive.get_params()
        for name, value in self.parameters.items():
            if name == "type":
                continue
            if isinstance(value, (list, tuple)) and len(value) == 3:
                self._add_vector_control(name, value)
            elif isinstance(value, (int, float)):
                self._add_numeric_control(name, value)

    def _clear_form(self):
        for row in range(self.form_layout.rowCount() - 1, -1, -1):
            self.form_layout.removeRow(row)
        self.controls.clear()

    def _add_vector_control(self, name, value):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)

        x = QDoubleSpinBox();
        x.setRange(-1e3, 1e3);
        x.setDecimals(4);
        x.setValue(value[0])
        y = QDoubleSpinBox();
        y.setRange(-1e3, 1e3);
        y.setDecimals(4);
        y.setValue(value[1])
        z = QDoubleSpinBox();
        z.setRange(-1e3, 1e3);
        z.setDecimals(4);
        z.setValue(value[2])
        row.addWidget(QLabel("X:"));
        row.addWidget(x)
        row.addWidget(QLabel("Y:"));
        row.addWidget(y)
        row.addWidget(QLabel("Z:"));
        row.addWidget(z)
        self.form_layout.addRow(name.replace("_", " ").title(), w)
        self.controls[name] = (x, y, z)

    def _add_numeric_control(self, name, value):
        s = QDoubleSpinBox()
        if name in ["radius", "height", "width", "major_radius", "minor_radius"]:
            s.setRange(0.001, 1000);
            s.setSingleStep(0.1)
        elif name in ["semi_angle"]:
            s.setRange(0, 89);
            s.setSingleStep(1);
            s.setSuffix("°")
        else:
            s.setRange(-1000, 1000);
            s.setSingleStep(0.1)
        s.setDecimals(4);
        s.setValue(value)
        self.form_layout.addRow(name.replace("_", " ").title(), s)
        self.controls[name] = s

    def _on_apply(self):
        new_params = {"type": self.parameters.get("type", "")}
        for name, ctrl in self.controls.items():
            if isinstance(ctrl, tuple) and len(ctrl) == 3:
                x, y, z = ctrl
                new_params[name] = (x.value(), y.value(), z.value())
            elif isinstance(ctrl, QDoubleSpinBox):
                new_params[name] = ctrl.value()
        self.parameterChanged.emit(new_params)


class GeometryTreeWidget(QTreeWidget):
    primitiveSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["几何体"])
        self.setIconSize(QSize(16, 16))
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.primitives: List[GeometricPrimitive] = []

    def set_primitives(self, primitives: List[GeometricPrimitive]):
        self.primitives = primitives
        self._update_tree()

    def _update_tree(self):
        self.clear()
        for i, primitive in enumerate(self.primitives):
            item = QTreeWidgetItem([f"{primitive.type.title()} #{i + 1}"])
            details = QTreeWidgetItem([f"匹配度: {primitive.fitting_score:.2f}"])
            item.addChild(details)
            params = primitive.get_params()
            for name, value in params.items():
                if name != "type":
                    item.addChild(QTreeWidgetItem([f"{name.replace('_', ' ').title()}: {value}"]))
            self.addTopLevelItem(item)

    def _on_selection_changed(self):
        selected = self.selectedItems()
        if not selected:
            return
        item = selected[0]
        while item.parent():
            item = item.parent()
        idx = self.indexOfTopLevelItem(item)
        if 0 <= idx < len(self.primitives):
            self.primitiveSelected.emit(idx)


class MainWindow(QMainWindow):
    open_file_requested = Signal(str)
    save_file_requested = Signal(str)
    modify_primitive_requested = Signal(int, dict)
    update_preview_requested = Signal(int, bool)
    undo_requested = Signal(int)
    redo_requested = Signal(int)
    solve_assembly_requested = Signal(str, int)
    export_part_to_db_requested = Signal()
    import_assembly_requested = Signal(str)

    # ✅ 3.3.2功能信号
    analyze_topology_requested = Signal(str)
    check_collision_requested = Signal(str)
    validate_assembly_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("单兵装备数字化设计系统")
        self.resize(1400, 900)

        self.preview_enabled = True
        self.statusBar = QStatusBar();
        self.setStatusBar(self.statusBar)
        self.progressBar = QProgressBar();
        self.progressBar.setMaximumWidth(200)
        self.progressBar.setVisible(False);
        self.statusBar.addPermanentWidget(self.progressBar)

        self._create_menus()
        self._create_toolbars()
        self._create_layout()

        self.current_primitive_index = -1
        self.current_assembly_id = ""

        self.setup_unity_launcher()

    def _create_menus(self):
        """✅ 优化后的菜单结构"""

        # ========== 文件菜单 ==========
        file_menu = self.menuBar().addMenu("文件(&F)")

        open_action = QAction("打开STEP文件.. .", self)
        open_action.setShortcut("Ctrl+O")
        open_action.setStatusTip("打开现有的STEP/STP文件")
        open_action.triggered.connect(self._on_open_file)

        save_action = QAction("保存为STEP.. .", self)
        save_action.setShortcut("Ctrl+S")
        save_action.setStatusTip("将当前模型保存为STEP文件")
        save_action.triggered.connect(self._on_save_file)

        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ========== 编辑菜单 ==========
        edit_menu = self.menuBar().addMenu("编辑(&E)")

        undo_action = QAction("撤销", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.setStatusTip("撤销上一步修改")
        undo_action.triggered.connect(self._on_undo)

        redo_action = QAction("重做", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.setStatusTip("重做上一步操作")
        redo_action.triggered.connect(self._on_redo)

        edit_menu.addAction(undo_action)
        edit_menu.addAction(redo_action)

        # ========== 视图菜单 ==========
        view_menu = self.menuBar().addMenu("视图(&V)")

        reset_view_action = QAction("重置视图", self)
        reset_view_action.setShortcut("Ctrl+R")
        reset_view_action.setStatusTip("重置3D视图到默认角度")
        reset_view_action.triggered.connect(self._on_reset_view)
        view_menu.addAction(reset_view_action)

        # ========== 数据库菜单 ==========
        database_menu = self.menuBar().addMenu("数据库(&D)")

        export_part_action = QAction("保存零部件到数据库", self)
        export_part_action.setShortcut("Ctrl+D")
        export_part_action.setStatusTip("将当前零部件保存到MySQL数据库")
        export_part_action.triggered.connect(self._on_export_part_to_db)

        import_assembly_action = QAction("导入装配并入库.. .", self)
        import_assembly_action.setShortcut("Ctrl+Shift+A")
        import_assembly_action.setStatusTip("导入完整STEP装配文件并自动分解入库")
        import_assembly_action.triggered.connect(self._on_import_assembly)

        database_menu.addAction(export_part_action)
        database_menu.addAction(import_assembly_action)

        self._act_export_part = export_part_action
        self._act_import_assembly = import_assembly_action

        # ========== ✅ 优化：装配与验证菜单（合并原装配和验证菜单）==========
        assembly_menu = self.menuBar().addMenu("装配与验证(&A)")

        # 约束求解
        solve_action = QAction("约束求解.. .", self)
        solve_action.setShortcut("Ctrl+Alt+S")
        solve_action.setStatusTip("根据装配约束求解各零件位姿")
        solve_action.triggered.connect(self._on_solve_assembly)
        assembly_menu.addAction(solve_action)

        assembly_menu.addSeparator()

        # 拓扑分析
        topology_action = QAction("分析接触关系（拓扑）", self)
        topology_action.setShortcut("Ctrl+T")
        topology_action.setStatusTip("分析零件之间的接触与邻接关系")
        topology_action.triggered.connect(self._on_analyze_topology)
        assembly_menu.addAction(topology_action)

        # 碰撞检测
        collision_action = QAction("检测碰撞干涉", self)
        collision_action.setShortcut("Ctrl+K")
        collision_action.setStatusTip("检测零件之间的碰撞、穿透和间隙")
        collision_action.triggered.connect(self._on_check_collision)
        assembly_menu.addAction(collision_action)

        assembly_menu.addSeparator()

        # 综合验证
        validate_action = QAction("综合验证装配", self)
        validate_action.setShortcut("Ctrl+Shift+V")
        validate_action.setStatusTip("执行完整的装配可行性验证（包含拓扑、碰撞等）")
        validate_action.triggered.connect(self._on_validate_assembly)
        assembly_menu.addAction(validate_action)

        # ========== 帮助菜单 ==========
        help_menu = self.menuBar().addMenu("帮助(&H)")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _on_import_assembly(self):
        step_path, _ = QFileDialog.getOpenFileName(
            self, "选择装配 STEP 文件", "", "STEP Files (*.step *.stp);;All Files (*.*)"
        )
        if step_path:
            self.import_assembly_requested.emit(step_path)

    def _create_toolbars(self):
        """✅ 优化后的工具栏（删除重复项）"""

        # 主工具栏
        main_tb = QToolBar("主工具栏")
        main_tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(main_tb)

        a_open = QAction("打开", self)
        a_open.setStatusTip("打开STEP文件")
        a_open.triggered.connect(self._on_open_file)

        a_save = QAction("保存", self)
        a_save.setStatusTip("保存为STEP文件")
        a_save.triggered.connect(self._on_save_file)

        main_tb.addAction(a_open)
        main_tb.addAction(a_save)
        main_tb.addSeparator()

        a_undo = QAction("撤销", self)
        a_undo.setStatusTip("撤销修改")
        a_undo.triggered.connect(self._on_undo)

        a_redo = QAction("重做", self)
        a_redo.setStatusTip("重做修改")
        a_redo.triggered.connect(self._on_redo)

        main_tb.addAction(a_undo)
        main_tb.addAction(a_redo)

        # ✅ 装配验证工具栏（优化标签）
        validate_tb = QToolBar("装配验证")
        validate_tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(validate_tb)

        a_topology = QAction("🔗 接触分析", self)
        a_topology.setStatusTip("分析零件之间的拓扑接触关系")
        a_topology.triggered.connect(self._on_analyze_topology)

        a_collision = QAction("⚠️ 碰撞检测", self)
        a_collision.setStatusTip("检测装配干涉")
        a_collision.triggered.connect(self._on_check_collision)

        a_validate = QAction("✓ 综合验证", self)
        a_validate.setStatusTip("完整装配验证")
        a_validate.triggered.connect(self._on_validate_assembly)

        validate_tb.addAction(a_topology)
        validate_tb.addAction(a_collision)
        validate_tb.addAction(a_validate)

    def _create_layout(self):
        central = QWidget();
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal);
        main_layout.addWidget(splitter)

        left_panel = QWidget();
        left_layout = QVBoxLayout(left_panel);
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.geometry_tree = GeometryTreeWidget();
        self.geometry_tree.primitiveSelected.connect(self._on_primitive_selected)
        left_layout.addWidget(QLabel("几何体列表"));
        left_layout.addWidget(self.geometry_tree)

        self.param_panel = ParameterControlPanel()
        self.param_panel.parameterChanged.connect(self._on_parameter_changed)
        self.param_panel.previewToggled.connect(self._on_preview_toggled)
        left_layout.addWidget(QLabel("参数编辑"));
        left_layout.addWidget(self.param_panel)
        splitter.addWidget(left_panel)

        self.view_panel = QWidget();
        vbox = QVBoxLayout(self.view_panel);
        vbox.setContentsMargins(0, 0, 0, 0)
        self.canvas = qtViewer3d(self.view_panel);
        vbox.addWidget(self.canvas)
        splitter.addWidget(self.view_panel)
        splitter.setSizes([300, 1100])

        self.canvas.InitDriver()
        self._init_view()

    def _init_view(self):
        from PySide6.QtWidgets import QApplication
        self.canvas.qApp = QApplication.instance()
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCC.Core.Aspect import Aspect_GFM_VER
        top = Quantity_Color(210 / 255, 222 / 255, 236 / 255, Quantity_TOC_RGB)
        bottom = Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB)
        self.canvas._display.View.SetBgGradientColors(top, bottom, Aspect_GFM_VER)
        self.canvas._display.View_Top();
        self.canvas._display.View_Iso();
        self.canvas._display.FitAll()

    def _on_preview_toggled(self, enabled: bool):
        self.preview_enabled = enabled
        if self.current_primitive_index >= 0:
            self.update_preview_requested.emit(self.current_primitive_index, enabled)

    @Slot(str)
    def set_status(self, message: str):
        self.statusBar.showMessage(message)

    @Slot(int)
    def set_progress(self, percent: int):
        if percent < 0:
            self.progressBar.setVisible(False)
        else:
            self.progressBar.setVisible(True)
            self.progressBar.setValue(percent)

    def show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message)

    def show_info(self, title: str, message: str):
        QMessageBox.information(self, title, message)

    def set_primitives(self, primitives: List[GeometricPrimitive]):
        self.geometry_tree.set_primitives(primitives)
        self.canvas._display.EraseAll()
        for p in primitives:
            for f in p.faces:
                self.canvas._display.DisplayShape(f, update=False)
        self.canvas._display.View_Iso()
        self.canvas._display.FitAll()
        self.canvas._display.Repaint()

    def update_primitive(self, index: int, new_shape: TopoDS_Shape):
        if index < 0:
            return
        self.canvas._display.EraseAll()
        primitives = self.geometry_tree.primitives
        for i, p in enumerate(primitives):
            if i == index:
                self.canvas._display.DisplayShape(new_shape, update=False, color="YELLOW")
            else:
                for f in p.faces:
                    self.canvas._display.DisplayShape(f, update=False)
        self.canvas._display.FitAll()
        self.canvas._display.Repaint()

    def show_original_with_preview(self, geometry_id: int, original_shape: TopoDS_Shape, preview_shape: TopoDS_Shape):
        if self.canvas._display is None:
            return
        try:
            self.canvas._display.EraseAll()
            primitives = self.geometry_tree.primitives
            for i, p in enumerate(primitives):
                if i == geometry_id:
                    self.canvas._display.DisplayShape(original_shape, update=False, color="BLUE")
                    if preview_shape and self.preview_enabled:
                        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
                        c = Quantity_Color(0.0, 0.8, 0.2, Quantity_TOC_RGB)
                        self.canvas._display.DisplayShape(preview_shape, color=c, transparency=0.7, update=False)
                else:
                    for f in p.faces:
                        self.canvas._display.DisplayShape(f, update=False)
            self.canvas._display.FitAll()
            self.canvas._display.Repaint()
        except Exception as e:
            print(f"显示预览失败: {e}")

    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开STEP文件", "", "STEP Files (*.step *.stp);;All Files (*.*)")
        if path:
            self.open_file_requested.emit(path)

    def _on_save_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存STEP文件", "", "STEP Files (*.step *.stp)")
        if path:
            if not path.lower().endswith((". step", ".stp")):
                path += ".step"
            self.save_file_requested.emit(path)

    def _on_primitive_selected(self, index: int):
        self.current_primitive_index = index
        primitives = self.geometry_tree.primitives
        if 0 <= index < len(primitives):
            self.param_panel.set_primitive(primitives[index])
            self.canvas._display.EraseAll()
            for i, p in enumerate(primitives):
                if i == index:
                    for f in p.faces:
                        self.canvas._display.DisplayShape(f, update=False, color="GREEN")
                else:
                    for f in p.faces:
                        self.canvas._display.DisplayShape(f, update=False)
            self.canvas._display.Repaint()

    def _on_parameter_changed(self, parameters: Dict[str, Any]):
        if self.current_primitive_index >= 0:
            params = parameters.copy()
            params["show_preview"] = self.preview_enabled
            self.modify_primitive_requested.emit(self.current_primitive_index, params)

    def _on_undo(self):
        if self.current_primitive_index >= 0:
            self.undo_requested.emit(self.current_primitive_index)

    def _on_redo(self):
        if self.current_primitive_index >= 0:
            self.redo_requested.emit(self.current_primitive_index)

    def _on_reset_view(self):
        self.canvas._display.View_Iso()
        self.canvas._display.FitAll()

    def _on_about(self):
        """✅ 更新关于对话框"""
        about_text = """
<h2>单兵装备数字化设计系统</h2>
<p><b>版本:</b> 2.0</p>
<p><b>开发者:</b> littlegoose1</p>
<br>
<p><b>核心功能:</b></p>
<ul>
  <li>几何体自动分割与参数化</li>
  <li>装配拓扑邻接分析（3. 3. 2）</li>
  <li>碰撞检测与干涉验证（3.3.2）</li>
  <li>协同几何变形（3.3.2）</li>
  <li>约束求解与装配优化</li>
</ul>
<br>
<p><i>基于 PythonOCC、PySide6 和 OpenCASCADE</i></p>
"""
        QMessageBox.about(self, "关于", about_text)

    def _on_solve_assembly(self):
        dlg = SolveAssemblyDialog(self)
        try:
            accepted = QDialog.DialogCode.Accepted
        except AttributeError:
            accepted = QDialog.Accepted
        if dlg.exec() != accepted:
            return
        asm_id, iterations = dlg.values()
        self.current_assembly_id = asm_id or ""
        self.solve_assembly_requested.emit(asm_id or "", iterations)

    def _on_export_part_to_db(self):
        self.export_part_to_db_requested.emit()

    # ✅ 3.3.2功能槽函数

    def _get_assembly_id(self) -> Optional[str]:
        """获取装配ID（从用户输入或缓存）"""
        from PySide6.QtWidgets import QInputDialog, QComboBox

        # 如果有缓存的装配ID，询问是否使用
        if self.current_assembly_id:
            reply = QMessageBox.question(
                self,
                "使用当前装配？",
                f"当前装配ID:\n{self.current_assembly_id}\n\n"
                "使用此装配进行分析？\n\n"
                "• 点击 Yes 使用当前装配\n"
                "• 点击 No 选择其他装配\n"
                "• 点击 Cancel 取消操作",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Cancel:
                return None
            elif reply == QMessageBox.Yes:
                return self.current_assembly_id

        # ✅ 改进的输入对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("选择装配")
        dialog.resize(500, 200)

        layout = QVBoxLayout(dialog)

        # 说明文字
        label = QLabel(
            "<b>请选择要分析的装配：</b><br><br>"
            "• 留空使用<b>最新</b>导入的装配<br>"
            "• 或输入完整的UUID（格式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        # 输入框
        from PySide6.QtWidgets import QLineEdit
        input_field = QLineEdit()
        input_field.setPlaceholderText("留空使用最新装配，或输入UUID...")
        if self.current_assembly_id:
            input_field.setText(self.current_assembly_id)
        layout.addWidget(input_field)

        # ✅ 添加"查看可用装配"按钮
        list_button = QPushButton("📋 查看可用装配列表")
        list_button.clicked.connect(lambda: self._show_assemblies_list(input_field))
        layout.addWidget(list_button)

        # 按钮
        from PySide6.QtWidgets import QDialogButtonBox
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            asm_id = input_field.text().strip()
            self.current_assembly_id = asm_id
            return asm_id  # 可以是空字符串（表示最新）

        return None

    # ✅ 新增：显示可用装配列表
    def _show_assemblies_list(self, input_field):
        """显示数据库中的装配列表供用户选择"""
        try:
            from ..db.mysql import get_conn
            from ..db.util import bin_to_uuid

            sql = """
                  SELECT id, \
                         name, \
                         created_at,
                         (SELECT COUNT(*) FROM assembly_nodes WHERE assembly_id = assemblies.id) as node_count
                  FROM assemblies
                  ORDER BY created_at DESC LIMIT 20 \
                  """

            conn = get_conn()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(sql)
                assemblies = cur.fetchall()

                if not assemblies:
                    QMessageBox.information(self, "无装配",
                                            "数据库中没有装配记录\n\n请先导入装配（数据库 → 导入装配并入库）")
                    return

                # 创建选择对话框
                dialog = QDialog(self)
                dialog.setWindowTitle("可用装配列表")
                dialog.resize(700, 400)

                layout = QVBoxLayout(dialog)

                # 列表
                from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
                table = QTableWidget()
                table.setColumnCount(4)
                table.setHorizontalHeaderLabels(["装配名称", "节点数", "创建时间", "UUID"])
                table.setRowCount(len(assemblies))
                table.setSelectionBehavior(QTableWidget.SelectRows)
                table.setSelectionMode(QTableWidget.SingleSelection)

                for i, asm in enumerate(assemblies):
                    asm_id = bin_to_uuid(asm['id'])
                    table.setItem(i, 0, QTableWidgetItem(asm.get('name', 'Unnamed')))
                    table.setItem(i, 1, QTableWidgetItem(str(asm.get('node_count', 0))))
                    table.setItem(i, 2, QTableWidgetItem(str(asm.get('created_at', ''))))
                    table.setItem(i, 3, QTableWidgetItem(asm_id))

                table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
                table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
                table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
                table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)

                layout.addWidget(table)

                # 双击选择
                def on_double_click(row, col):
                    asm_id = table.item(row, 3).text()
                    input_field.setText(asm_id)
                    dialog.accept()

                table.cellDoubleClicked.connect(on_double_click)

                # 按钮
                button_layout = QHBoxLayout()
                select_btn = QPushButton("选择")
                select_btn.clicked.connect(lambda: (
                    input_field.setText(table.item(table.currentRow(), 3).text()) if table.currentRow() >= 0 else None,
                    dialog.accept()
                ))
                cancel_btn = QPushButton("取消")
                cancel_btn.clicked.connect(dialog.reject)

                button_layout.addStretch()
                button_layout.addWidget(select_btn)
                button_layout.addWidget(cancel_btn)
                layout.addLayout(button_layout)

                dialog.exec()

            finally:
                cur.close()
                conn.close()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取装配列表失败：{e}")

    def _on_analyze_topology(self):
        """✅ 分析接触关系"""
        asm_id = self._get_assembly_id()
        if asm_id is not None:
            self.analyze_topology_requested.emit(asm_id)

    def _on_check_collision(self):
        """✅ 检测碰撞干涉"""
        asm_id = self._get_assembly_id()
        if asm_id is not None:
            self.check_collision_requested.emit(asm_id)

    def _on_validate_assembly(self):
        """✅ 综合验证装配"""
        asm_id = self._get_assembly_id()
        if asm_id is not None:
            self.validate_assembly_requested.emit(asm_id)

    # ✅ 显示验证结果的方法

    def show_topology_result(self, report: str, adjacency: Any):
        """显示拓扑分析结果"""
        dlg = ValidationResultDialog("拓扑接触关系分析", report, self)
        dlg.exec()

    def show_collision_result(self, report: str, collisions: List):
        """显示碰撞检测结果"""
        dlg = ValidationResultDialog("碰撞干涉检测", report, self)
        dlg.exec()

    def show_validation_result(self, report: str, validation: Dict):
        """显示装配验证结果"""
        dlg = ValidationResultDialog("装配综合验证", report, self)
        dlg.exec()

    def setup_unity_launcher(self):
        """设置Unity启动器"""
        self.unity_launcher = UnityLauncherWidget()

        unity_dock = QDockWidget("人体展示", self)
        unity_dock.setWidget(self.unity_launcher)
        unity_dock.setAllowedAreas(Qt.RightDockWidgetArea)  # 只能在右侧

        # ← 完全固定，不允许任何操作
        unity_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)

        self.addDockWidget(Qt.RightDockWidgetArea, unity_dock)
        # ← 添加装备面板
        self.setup_equipment_panel()

    def setup_equipment_panel(self):
        """设置装备展示面板"""
        self.equipment_panel = EquipmentPanel()

        equipment_dock = QDockWidget("装备管理", self)
        equipment_dock.setWidget(self.equipment_panel)
        equipment_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        # 设置特性：可移动，但不可关闭
        features = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        equipment_dock.setFeatures(features)

        # 添加到右侧，与Unity启动器并排（上下排列）
        self.addDockWidget(Qt.RightDockWidgetArea, equipment_dock)

        # 连接信号
        self.equipment_panel.equipment_selected.connect(self.on_equipment_selected)
        self.equipment_panel.equipment_loaded.connect(self.on_equipment_loaded)

    def on_equipment_selected(self, equipment_id: str):
        """装备被选中时的回调"""
        print(f"装备已选中: {equipment_id}")
        self.set_status(f"已选中装备: {equipment_id}")

    def on_equipment_loaded(self, equipment_data: dict):
        """装备加载时的回调"""
        equipment_name = equipment_data.get('equipment_name', 'Unknown')
        part_count = len(equipment_data.get('parts', []))

        print(f"装备已加载: {equipment_name}, 包含 {part_count} 个部件")
        self.set_status(f"已加载装备: {equipment_name}")

        # 可以在这里将数据传递给Unity
        # if hasattr(self, 'unity_launcher'):
        #     self.unity_launcher.load_equipment_data(equipment_data)