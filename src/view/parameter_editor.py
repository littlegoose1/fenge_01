# src/view/parameter_editor.py
from typing import Dict, List, Any, Optional, Callable
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
                               QPushButton, QGroupBox, QSplitter)

from ..model.geometry import GeometricPrimitive


class ParameterEditor(QWidget):
    """参数编辑组件"""

    parameter_changed = Signal(int, dict)  # (几何体索引, 新参数)
    undo_requested = Signal(int)  # 请求撤销修改
    redo_requested = Signal(int)  # 请求重做修改

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_primitive = None
        self.current_index = -1
        self.parameter_widgets = {}

        self._init_ui()

    def _init_ui(self):
        """初始化界面"""
        main_layout = QVBoxLayout(self)

        # 参数组
        self.params_group = QGroupBox("参数编辑")
        self.params_layout = QFormLayout(self.params_group)

        # 操作按钮
        self.buttons_layout = QHBoxLayout()

        self.apply_button = QPushButton("应用修改")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._on_apply_clicked)

        self.reset_button = QPushButton("重置参数")
        self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(self._on_reset_clicked)

        self.undo_button = QPushButton("撤销")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._on_undo_clicked)

        self.redo_button = QPushButton("重做")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self._on_redo_clicked)

        self.buttons_layout.addWidget(self.apply_button)
        self.buttons_layout.addWidget(self.reset_button)
        self.buttons_layout.addWidget(self.undo_button)
        self.buttons_layout.addWidget(self.redo_button)

        # 添加组件到主布局
        main_layout.addWidget(self.params_group)
        main_layout.addLayout(self.buttons_layout)
        main_layout.addStretch(1)

        self.setLayout(main_layout)

    def set_primitive(self, primitive: Optional[GeometricPrimitive], index: int):
        """设置当前编辑的几何体"""
        # 清除现有参数字段
        self._clear_parameter_fields()

        self.current_primitive = primitive
        self.current_index = index

        if primitive is not None:
            self._create_parameter_fields(primitive)
            self.apply_button.setEnabled(True)
            self.reset_button.setEnabled(True)
            self._update_undo_redo_buttons()
        else:
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.undo_button.setEnabled(False)
            self.redo_button.setEnabled(False)

    def _clear_parameter_fields(self):
        """清除参数字段"""
        # 移除所有现有的参数字段
        while self.params_layout.rowCount() > 0:
            self.params_layout.removeRow(0)

        self.parameter_widgets = {}

    def _create_parameter_fields(self, primitive: GeometricPrimitive):
        """创建参数字段"""
        params = primitive.get_params()

        for param_name, param_value in params.items():
            if param_name == "type":
                continue  # 跳过类型参数

            if isinstance(param_value, tuple) and len(param_value) == 3:
                # 3D向量或点
                vector_widget = QWidget()
                vector_layout = QHBoxLayout(vector_widget)
                vector_layout.setContentsMargins(0, 0, 0, 0)

                self.parameter_widgets[param_name] = []
                for i, coord in enumerate(["X", "Y", "Z"]):
                    label = QLabel(f"{coord}:")
                    spin_box = QDoubleSpinBox()
                    spin_box.setRange(-10000, 10000)
                    spin_box.setDecimals(5)
                    spin_box.setValue(param_value[i])

                    vector_layout.addWidget(label)
                    vector_layout.addWidget(spin_box)
                    self.parameter_widgets[param_name].append(spin_box)

                self.params_layout.addRow(QLabel(f"{param_name}:"), vector_widget)

            elif isinstance(param_value, float):
                # 浮点参数
                spin_box = QDoubleSpinBox()
                spin_box.setRange(-10000, 10000)
                spin_box.setDecimals(5)
                spin_box.setValue(param_value)

                self.parameter_widgets[param_name] = spin_box
                self.params_layout.addRow(QLabel(f"{param_name}:"), spin_box)

            elif isinstance(param_value, int):
                # 整数参数
                spin_box = QSpinBox()
                spin_box.setRange(-10000, 10000)
                spin_box.setValue(param_value)

                self.parameter_widgets[param_name] = spin_box
                self.params_layout.addRow(QLabel(f"{param_name}:"), spin_box)

            else:
                # 其他类型参数 - 使用文本框
                line_edit = QLineEdit(str(param_value))

                self.parameter_widgets[param_name] = line_edit
                self.params_layout.addRow(QLabel(f"{param_name}:"), line_edit)

    def _get_current_parameters(self) -> Dict:
        """获取当前参数值"""
        params = {}

        for param_name, widget in self.parameter_widgets.items():
            if isinstance(widget, list):
                # 3D向量或点
                params[param_name] = tuple(spin_box.value() for spin_box in widget)
            elif isinstance(widget, QDoubleSpinBox):
                # 浮点参数
                params[param_name] = widget.value()
            elif isinstance(widget, QSpinBox):
                # 整数参数
                params[param_name] = widget.value()
            elif isinstance(widget, QLineEdit):
                # 文本参数
                params[param_name] = widget.text()

        return params

    def _on_apply_clicked(self):
        """应用按钮点击处理"""
        if self.current_primitive is None or self.current_index < 0:
            return

        params = self._get_current_parameters()
        self.parameter_changed.emit(self.current_index, params)
        self._update_undo_redo_buttons()

    def _on_reset_clicked(self):
        """重置按钮点击处理"""
        if self.current_primitive is None:
            return

        # 重新创建参数字段
        self._clear_parameter_fields()
        self._create_parameter_fields(self.current_primitive)

    def _on_undo_clicked(self):
        """撤销按钮点击处理"""
        if self.current_index >= 0:
            self.undo_requested.emit(self.current_index)
            self._update_undo_redo_buttons()

    def _on_redo_clicked(self):
        """重做按钮点击处理"""
        if self.current_index >= 0:
            self.redo_requested.emit(self.current_index)
            self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self):
        """更新撤销/重做按钮状态"""
        if self.current_primitive:
            self.undo_button.setEnabled(self.current_primitive.can_undo())
            self.redo_button.setEnabled(self.current_primitive.can_redo())
        else:
            self.undo_button.setEnabled(False)
            self.redo_button.setEnabled(False)