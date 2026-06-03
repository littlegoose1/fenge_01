"""
模块功能：
联动变形可视化面板（安全解析版）。

主要功能：
1) 展示数据库装配并加载节点；
2) 支持添加 fixed / displacement 约束；
3) 调用 DeformationVisualizationService 执行联动变形；
4) 输出变形结果、冲突信息和告警；
5) 通过 on_render 回调通知主窗口刷新3D显示。

安全改进：
- 去除 eval，改为 JSON 安全解析；
- 约束列表内部保存 Python 对象，不依赖字符串反序列化。
"""

from typing import List, Dict, Any, Callable, Optional
import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QListWidget, QTextEdit, QLineEdit, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Qt

from src.services.deformation_visualization_service import DeformationVisualizationService


class DeformationPanel(QWidget):
    """
    联动变形面板（MVP）
    """

    def __init__(
        self,
        on_render: Optional[Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], None]] = None,
        parent=None
    ):
        """
        Args:
            on_render:
                回调函数：
                on_render(original_nodes, deformed_nodes)
        """
        super().__init__(parent)
        self.service = DeformationVisualizationService()
        self.on_render = on_render

        self._assembly_map: Dict[str, str] = {}   # display_name -> assembly_id
        self._loaded_nodes: List[Dict[str, Any]] = []

        self._build_ui()
        self._load_assemblies()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # 装配选择
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("装配："))
        self.cmb_assembly = QComboBox()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._load_assemblies)
        self.btn_load = QPushButton("加载装配")
        self.btn_load.clicked.connect(self._on_load_assembly)
        row1.addWidget(self.cmb_assembly, 1)
        row1.addWidget(self.btn_refresh)
        row1.addWidget(self.btn_load)
        root.addLayout(row1)

        # 参数
        row2 = QHBoxLayout()
        self.edit_stiffness = QLineEdit("1.0")
        self.edit_decay = QLineEdit("0.7")
        self.edit_depth = QLineEdit("3")
        row2.addWidget(QLabel("stiffness"))
        row2.addWidget(self.edit_stiffness)
        row2.addWidget(QLabel("decay"))
        row2.addWidget(self.edit_decay)
        row2.addWidget(QLabel("max_depth"))
        row2.addWidget(self.edit_depth)
        root.addLayout(row2)

        # 节点列表 + 约束区
        row3 = QHBoxLayout()
        self.list_nodes = QListWidget()
        row3.addWidget(self.list_nodes, 2)

        right = QVBoxLayout()
        self.cmb_constraint = QComboBox()
        self.cmb_constraint.addItems(["fixed", "displacement"])
        self.cmb_constraint.currentTextChanged.connect(self._on_constraint_type_changed)

        self.edit_dx = QLineEdit("0")
        self.edit_dy = QLineEdit("0")
        self.edit_dz = QLineEdit("10")

        self.btn_add_constraint = QPushButton("添加约束到选中节点")
        self.btn_add_constraint.clicked.connect(self._on_add_constraint)

        self.btn_remove_constraint = QPushButton("删除选中约束")
        self.btn_remove_constraint.clicked.connect(self._on_remove_constraint)

        self.btn_clear_constraints = QPushButton("清空约束")
        self.btn_clear_constraints.clicked.connect(self._on_clear_constraints)

        right.addWidget(QLabel("约束类型"))
        right.addWidget(self.cmb_constraint)
        right.addWidget(QLabel("dx"))
        right.addWidget(self.edit_dx)
        right.addWidget(QLabel("dy"))
        right.addWidget(self.edit_dy)
        right.addWidget(QLabel("dz"))
        right.addWidget(self.edit_dz)
        right.addWidget(self.btn_add_constraint)
        right.addWidget(self.btn_remove_constraint)
        right.addWidget(self.btn_clear_constraints)

        self.list_constraints = QListWidget()
        right.addWidget(QLabel("已添加约束"))
        right.addWidget(self.list_constraints, 1)

        row3.addLayout(right, 3)
        root.addLayout(row3, 1)

        # 执行按钮
        row4 = QHBoxLayout()
        self.btn_run = QPushButton("执行联动变形")
        self.btn_run.clicked.connect(self._on_run)
        row4.addWidget(self.btn_run)
        root.addLayout(row4)

        # 输出区
        self.txt_output = QTextEdit()
        self.txt_output.setReadOnly(True)
        root.addWidget(self.txt_output, 1)

        self._on_constraint_type_changed(self.cmb_constraint.currentText())

    def _load_assemblies(self):
        self.cmb_assembly.clear()
        self._assembly_map.clear()

        try:
            assemblies = self.service.list_assemblies()
            for a in assemblies:
                show_name = f"{a['name']} ({a['id'][:8]})"
                self._assembly_map[show_name] = a["id"]
                self.cmb_assembly.addItem(show_name)

            self._append_text(f"[装配] 刷新完成，共 {len(assemblies)} 条")
        except Exception as e:
            self._append_text(f"[Error] 装配列表加载失败: {e}")

    def _on_constraint_type_changed(self, ctype: str):
        """
        根据约束类型控制位移输入框可用性
        """
        is_disp = (ctype == "displacement")
        self.edit_dx.setEnabled(is_disp)
        self.edit_dy.setEnabled(is_disp)
        self.edit_dz.setEnabled(is_disp)

    def _on_load_assembly(self):
        key = self.cmb_assembly.currentText()
        assembly_id = self._assembly_map.get(key)
        if not assembly_id:
            QMessageBox.warning(self, "提示", "请选择装配")
            return

        try:
            nodes, warnings = self.service.load_assembly_nodes_with_shapes(assembly_id)
            self._loaded_nodes = nodes

            self.list_nodes.clear()
            for n in nodes:
                item = QListWidgetItem(f"{n['name']} | {n['id']}")
                item.setData(Qt.UserRole, n["id"])
                self.list_nodes.addItem(item)

            self._append_text(f"[加载] 节点数: {len(nodes)}")
            for w in warnings:
                self._append_text(f"[Warning] {w}")

            # 初次加载渲染原始模型
            if self.on_render:
                self.on_render(self._loaded_nodes, [])

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载装配失败：{e}")

    def _on_add_constraint(self):
        node_item = self.list_nodes.currentItem()
        if not node_item:
            QMessageBox.warning(self, "提示", "请先选择一个节点")
            return

        node_id = node_item.data(Qt.UserRole)
        ctype = self.cmb_constraint.currentText()

        payload: Dict[str, Any]
        if ctype == "fixed":
            payload = {
                "node_id": node_id,
                "constraint_type": "fixed",
                "params": {}
            }
        else:
            try:
                dx = float(self.edit_dx.text().strip())
                dy = float(self.edit_dy.text().strip())
                dz = float(self.edit_dz.text().strip())
            except ValueError:
                QMessageBox.warning(self, "提示", "dx/dy/dz 必须是数字")
                return

            payload = {
                "node_id": node_id,
                "constraint_type": "displacement",
                "params": {"displacement": [dx, dy, dz]}
            }

        # 列表项中保存真实对象（安全，不需要eval）
        show_text = self._constraint_to_text(payload)
        item = QListWidgetItem(show_text)
        item.setData(Qt.UserRole, payload)
        self.list_constraints.addItem(item)

        self._append_text(f"[约束] 添加: {json.dumps(payload, ensure_ascii=False)}")

    def _on_remove_constraint(self):
        row = self.list_constraints.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一条约束")
            return
        self.list_constraints.takeItem(row)
        self._append_text("[约束] 已删除选中约束")

    def _on_clear_constraints(self):
        self.list_constraints.clear()
        self._append_text("[约束] 已清空全部约束")

    def _on_run(self):
        key = self.cmb_assembly.currentText()
        assembly_id = self._assembly_map.get(key)
        if not assembly_id:
            QMessageBox.warning(self, "提示", "请选择装配")
            return

        payloads = []
        for i in range(self.list_constraints.count()):
            item = self.list_constraints.item(i)
            payload = item.data(Qt.UserRole)
            if isinstance(payload, dict):
                payloads.append(payload)

        if not payloads:
            QMessageBox.warning(self, "提示", "请至少添加一个约束")
            return

        try:
            stiffness = float(self.edit_stiffness.text().strip())
            decay = float(self.edit_decay.text().strip())
            depth = int(self.edit_depth.text().strip())
        except ValueError:
            QMessageBox.warning(self, "提示", "stiffness/decay/max_depth 参数格式错误")
            return

        try:
            out = self.service.run_deformation(
                assembly_id=assembly_id,
                constraints_payload=payloads,
                stiffness=stiffness,
                translation_decay=decay,
                max_graph_depth=depth
            )

            for w in out.warnings:
                self._append_text(f"[Warning] {w}")

            self._append_text(f"[结果] 变形节点数: {len(out.results)}")
            for r in out.results:
                self._append_text(
                    f"  - {r.node_id}: {r.original_transform.get('pos')} -> {r.deformed_transform.get('pos')} "
                    f"(energy={r.energy:.4f})"
                )

            self._append_text(f"[结果] 冲突数: {len(out.collisions)}")
            for c in out.collisions:
                self._append_text(
                    f"  - {c.node_a_id} <-> {c.node_b_id}, type={c.collision_type}, depth={c.depth:.4f}"
                )

            if self.on_render:
                deformed_nodes = [
                    {"id": r.node_id, "shape": r.deformed_shape, "transform": r.deformed_transform}
                    for r in out.results
                ]
                self.on_render(out.loaded_nodes, deformed_nodes)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"执行联动变形失败：{e}")

    @staticmethod
    def _constraint_to_text(payload: Dict[str, Any]) -> str:
        """
        把约束对象转成用户可读文本
        """
        node_id = payload.get("node_id", "")
        ctype = payload.get("constraint_type", "")
        params = payload.get("params", {})

        if ctype == "fixed":
            return f"{node_id} | fixed"
        if ctype == "displacement":
            d = params.get("displacement", [0, 0, 0])
            return f"{node_id} | displacement | dx={d[0]}, dy={d[1]}, dz={d[2]}"
        return f"{node_id} | {ctype}"

    def _append_text(self, s: str):
        self.txt_output.append(s)