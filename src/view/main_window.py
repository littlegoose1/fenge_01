from typing import List, Dict, Any
import os

from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
                               QFileDialog, QSplitter,
                               QWidget, QTreeWidget, QTreeWidgetItem, QProgressBar,
                               QStatusBar, QMessageBox, QGroupBox, QFormLayout,
                               QDoubleSpinBox, QPushButton, QToolBar,
                               QCheckBox, QDialog)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QAction

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Display.backend import load_backend
load_backend("pyside6")
from OCC.Display.qtDisplay import qtViewer3d

from ..model.geometry import GeometricPrimitive
from ..ui.solve_dialog import SolveAssemblyDialog


class ParameterControlPanel(QWidget):
    parameterChanged = Signal(dict)
    previewToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)

        # 用实例属性保存布局与分组，后续可安全重建/清空
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
        # 每次切换前彻底清空
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
        """
        最稳妥：只移除表单的行，不手动 deleteLater 控件，避免“已删除对象”或类型不匹配。
        Qt 会处理可见性和父子关系，不会出现 UI 叠加。
        """
        # 从最后一行往上移除更稳妥
        for row in range(self.form_layout.rowCount() - 1, -1, -1):
            self.form_layout.removeRow(row)

        # 清空我们保存的控件引用
        self.controls.clear()

    def _add_vector_control(self, name, value):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)

        x = QDoubleSpinBox(); x.setRange(-1e3, 1e3); x.setDecimals(4); x.setValue(value[0])
        y = QDoubleSpinBox(); y.setRange(-1e3, 1e3); y.setDecimals(4); y.setValue(value[1])
        z = QDoubleSpinBox(); z.setRange(-1e3, 1e3); z.setDecimals(4); z.setValue(value[2])
        row.addWidget(QLabel("X:")); row.addWidget(x)
        row.addWidget(QLabel("Y:")); row.addWidget(y)
        row.addWidget(QLabel("Z:")); row.addWidget(z)
        self.form_layout.addRow(name.replace("_", " ").title(), w)
        self.controls[name] = (x, y, z)

    def _add_numeric_control(self, name, value):
        s = QDoubleSpinBox()
        if name in ["radius", "height", "width", "major_radius", "minor_radius"]:
            s.setRange(0.001, 1000); s.setSingleStep(0.1)
        elif name in ["semi_angle"]:
            s.setRange(0, 89); s.setSingleStep(1); s.setSuffix("°")
        else:
            s.setRange(-1000, 1000); s.setSingleStep(0.1)
        s.setDecimals(4); s.setValue(value)
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

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAD几何体分割与参数化系统")
        self.resize(1200, 800)

        self.preview_enabled = True
        self.statusBar = QStatusBar(); self.setStatusBar(self.statusBar)
        self.progressBar = QProgressBar(); self.progressBar.setMaximumWidth(200)
        self.progressBar.setVisible(False); self.statusBar.addPermanentWidget(self.progressBar)

        self._create_menus()
        self._create_toolbars()
        self._create_layout()

        self.current_primitive_index = -1

    def _create_menus(self):
        file_menu = self.menuBar().addMenu("文件")
        open_action = QAction("打开", self); open_action.setShortcut("Ctrl+O"); open_action.triggered.connect(self._on_open_file)
        save_action = QAction("保存", self); save_action.setShortcut("Ctrl+S"); save_action.triggered.connect(self._on_save_file)
        exit_action = QAction("退出", self); exit_action.setShortcut("Ctrl+Q"); exit_action.triggered.connect(self.close)
        file_menu.addAction(open_action); file_menu.addAction(save_action); file_menu.addSeparator(); file_menu.addAction(exit_action)

        edit_menu = self.menuBar().addMenu("编辑")
        undo_action = QAction("撤销", self); undo_action.setShortcut("Ctrl+Z"); undo_action.triggered.connect(self._on_undo)
        redo_action = QAction("重做", self); redo_action.setShortcut("Ctrl+Y"); redo_action.triggered.connect(self._on_redo)
        edit_menu.addAction(undo_action); edit_menu.addAction(redo_action)

        view_menu = self.menuBar().addMenu("视图")
        reset_view_action = QAction("重置视图", self); reset_view_action.triggered.connect(self._on_reset_view)
        view_menu.addAction(reset_view_action)

        asm_menu = self.menuBar().addMenu("装配")
        solve_action = QAction("求解装配...", self)
        solve_action.setShortcut("Ctrl+Alt+S")
        solve_action.setStatusTip("根据约束求解装配节点位姿")
        solve_action.triggered.connect(self._on_solve_assembly)
        asm_menu.addAction(solve_action)

        data_menu = self.menuBar().addMenu("数据")
        export_part_action = QAction("保存零部件到数据库", self)
        export_part_action.setShortcut("Ctrl+D")
        export_part_action.triggered.connect(self._on_export_part_to_db)
        data_menu.addAction(export_part_action)

        import_assembly_action = QAction("导入装配并入库...", self)
        import_assembly_action.setShortcut("Ctrl+Shift+A")
        import_assembly_action.setStatusTip("读取完整 STEP 装配并写入全部零部件/版本/节点")
        import_assembly_action.triggered.connect(self._on_import_assembly)
        data_menu.addAction(import_assembly_action)

        self._act_export_part = export_part_action
        self._act_import_assembly = import_assembly_action

    def _on_import_assembly(self):
        step_path, _ = QFileDialog.getOpenFileName(
            self, "选择装配 STEP 文件", "", "STEP Files (*.step *.stp);;All Files (*.*)"
        )
        if step_path:
            self.import_assembly_requested.emit(step_path)

    def _create_toolbars(self):
        tb = QToolBar("主工具栏"); self.addToolBar(tb)
        a_open = QAction("打开", self); a_open.triggered.connect(self._on_open_file); tb.addAction(a_open)
        a_save = QAction("保存", self); a_save.triggered.connect(self._on_save_file); tb.addAction(a_save)
        tb.addSeparator()
        a_undo = QAction("撤销", self); a_undo.triggered.connect(self._on_undo); tb.addAction(a_undo)
        a_redo = QAction("重做", self); a_redo.triggered.connect(self._on_redo); tb.addAction(a_redo)
        tb.addSeparator()
        tb.addAction(self._act_export_part)

    def _create_layout(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal); main_layout.addWidget(splitter)

        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_layout.setContentsMargins(0, 0, 0, 0)
        self.geometry_tree = GeometryTreeWidget(); self.geometry_tree.primitiveSelected.connect(self._on_primitive_selected)
        left_layout.addWidget(QLabel("几何体列表")); left_layout.addWidget(self.geometry_tree)

        self.param_panel = ParameterControlPanel()
        self.param_panel.parameterChanged.connect(self._on_parameter_changed)
        self.param_panel.previewToggled.connect(self._on_preview_toggled)
        left_layout.addWidget(QLabel("参数编辑")); left_layout.addWidget(self.param_panel)
        splitter.addWidget(left_panel)

        self.view_panel = QWidget(); vbox = QVBoxLayout(self.view_panel); vbox.setContentsMargins(0, 0, 0, 0)
        self.canvas = qtViewer3d(self.view_panel); vbox.addWidget(self.canvas)
        splitter.addWidget(self.view_panel)
        splitter.setSizes([300, 900])

        self.canvas.InitDriver()
        self._init_view()

    def _init_view(self):
        from PySide6.QtWidgets import QApplication
        self.canvas.qApp = QApplication.instance()
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCC.Core.Aspect import Aspect_GFM_VER
        top = Quantity_Color(210/255, 222/255, 236/255, Quantity_TOC_RGB)
        bottom = Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB)
        self.canvas._display.View.SetBgGradientColors(top, bottom, Aspect_GFM_VER)
        self.canvas._display.View_Top(); self.canvas._display.View_Iso(); self.canvas._display.FitAll()

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
            if not path.lower().endswith((".step", ".stp")):
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
        QMessageBox.about(self, "关于",
                          "CAD几何体分割与参数化系统\n\n版本: 1.0\n开发者: littlegoose1\n\n用于CAD模型的几何体分割与参数化。")

    def _on_solve_assembly(self):
        dlg = SolveAssemblyDialog(self)
        try:
            accepted = QDialog.DialogCode.Accepted
        except AttributeError:
            accepted = QDialog.Accepted
        if dlg.exec() != accepted:
            return
        asm_id, iterations = dlg.values()
        self.solve_assembly_requested.emit(asm_id or "", iterations)

    def _on_export_part_to_db(self):
        self.export_part_to_db_requested.emit()