import os
import time
from typing import List, Dict, Any, Optional, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit, QMessageBox
)

from src.services.assembly_builder_service import AssemblyBuilderService


class AssemblyBuilderPanel(QWidget):
    """
    自由拼装面板：
    - 选基础装配
    - 浏览零件库并预览
    - 添加/删除零件
    - 调整位置
    - 保存为新装配
    """

    def __init__(
        self,
        on_render: Optional[Callable[[List[Dict[str, Any]], Optional[Dict[str, Any]], bool, bool], None]] = None,
        on_saved: Optional[Callable[[], None]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.service = AssemblyBuilderService()
        self.on_render = on_render
        self.on_saved = on_saved

        self._assembly_map: Dict[str, str] = {}
        self._all_parts: List[Dict[str, Any]] = []
        self._working_nodes: List[Dict[str, Any]] = []
        self._shape_cache: Dict[str, Any] = {}
        self._current_preview_part: Optional[Dict[str, Any]] = None
        self._is_dragging = False
        self._build_start_ts: Optional[float] = None

        self._build_ui()
        self._refresh_all()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh_elapsed_label)
        self._timer.start()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # 基础装配
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("基础装配"))
        self.cmb_base = QComboBox()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_all)
        self.btn_load_base = QPushButton("加载基础装配")
        self.btn_load_base.clicked.connect(self._on_load_base)
        row0.addWidget(self.cmb_base, 1)
        row0.addWidget(self.btn_refresh)
        row0.addWidget(self.btn_load_base)
        self.lbl_elapsed = QLabel("拼装计时：0.000 秒")
        self.lbl_elapsed.setStyleSheet("""
            QLabel {
                background-color: #FFF3CD;
                color: #7A4D00;
                border: 1px solid #E0A800;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                font-weight: bold;
            }
        """)
        row0.addWidget(self.lbl_elapsed)
        root.addLayout(row0)

        # 拼装区
        body = QHBoxLayout()

        # 左：零件库
        left = QVBoxLayout()
        left.addWidget(QLabel("零件库（点击可预览外观）"))
        row_filter = QHBoxLayout()
        row_filter.addWidget(QLabel("种类"))
        self.cmb_category = QComboBox()
        self.cmb_category.currentIndexChanged.connect(self._filter_parts)
        row_filter.addWidget(self.cmb_category, 1)
        left.addLayout(row_filter)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("按名称/种类过滤...")
        self.edit_search.textChanged.connect(self._filter_parts)
        left.addWidget(self.edit_search)

        self.list_parts = QListWidget()
        self.list_parts.itemClicked.connect(self._on_part_selected)
        left.addWidget(self.list_parts, 1)

        row_left_btn = QHBoxLayout()
        self.btn_add_part = QPushButton("添加到拼装")
        self.btn_add_part.clicked.connect(self._on_add_part)
        row_left_btn.addWidget(self.btn_add_part)
        left.addLayout(row_left_btn)

        # 右：当前拼装
        right = QVBoxLayout()
        right.addWidget(QLabel("当前拼装零件"))
        self.list_nodes = QListWidget()
        self.list_nodes.itemClicked.connect(self._on_working_node_selected)
        right.addWidget(self.list_nodes, 1)

        row_pos = QHBoxLayout()
        row_pos.addWidget(QLabel("X"))
        self.edit_x = QLineEdit("0")
        row_pos.addWidget(self.edit_x)
        row_pos.addWidget(QLabel("Y"))
        self.edit_y = QLineEdit("0")
        row_pos.addWidget(self.edit_y)
        row_pos.addWidget(QLabel("Z"))
        self.edit_z = QLineEdit("0")
        row_pos.addWidget(self.edit_z)
        self.btn_apply_pos = QPushButton("应用位置")
        self.btn_apply_pos.clicked.connect(self._on_apply_position)
        row_pos.addWidget(self.btn_apply_pos)
        right.addLayout(row_pos)

        row_right_btn = QHBoxLayout()
        self.btn_remove = QPushButton("删除选中零件")
        self.btn_remove.clicked.connect(self._on_remove_selected)
        row_right_btn.addWidget(self.btn_remove)
        right.addLayout(row_right_btn)

        body.addLayout(left, 1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # 保存区
        row_save1 = QHBoxLayout()
        row_save1.addWidget(QLabel("新装配名称"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("请输入新装配名称")
        row_save1.addWidget(self.edit_name, 1)
        root.addLayout(row_save1)

        row_save2 = QHBoxLayout()
        row_save2.addWidget(QLabel("描述"))
        self.edit_desc = QLineEdit()
        self.edit_desc.setPlaceholderText("可选")
        row_save2.addWidget(self.edit_desc, 1)
        self.btn_save = QPushButton("保存到数据库")
        self.btn_save.clicked.connect(self._on_save)
        row_save2.addWidget(self.btn_save)
        root.addLayout(row_save2)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        root.addWidget(self.txt_log)

    def _refresh_all(self):
        self._load_assemblies()
        self._load_parts()
        self._append("已刷新装配与零件库")

    def _load_assemblies(self):
        self.cmb_base.clear()
        self._assembly_map.clear()
        self.cmb_base.addItem("（空装配）")
        try:
            assemblies = self.service.list_assemblies()
            for a in assemblies:
                show = f"{a['name']} ({a['id'][:8]})"
                self._assembly_map[show] = a["id"]
                self.cmb_base.addItem(show)
        except Exception as e:
            self._append(f"[错误] 加载装配列表失败: {e}")

    def _load_parts(self):
        try:
            self._all_parts = self.service.list_part_versions()
            self._refresh_category_filter()
            self._filter_parts()
        except Exception as e:
            self._append(f"[错误] 加载零件库失败: {e}")

    def _refresh_category_filter(self):
        categories = sorted({
            (p.get("part_category_cn", "") or "未分类")
            for p in self._all_parts
        })
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        self.cmb_category.addItem("全部")
        for c in categories:
            self.cmb_category.addItem(c)
        self.cmb_category.blockSignals(False)

    def _filter_parts(self):
        kw = self.edit_search.text().strip().lower()
        selected_category = self.cmb_category.currentText().strip() if hasattr(self, "cmb_category") else "全部"
        self.list_parts.clear()

        for p in self._all_parts:
            name = p.get("part_name", "")
            category = p.get("part_category_cn", "") or "未分类"
            if selected_category and selected_category != "全部" and category != selected_category:
                continue
            merged = f"{name} {category}".lower()
            if kw and kw not in merged:
                continue
            text = f"{name} [{category}]  v{p.get('version_no', 0)}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, p)
            self.list_parts.addItem(item)

    def _on_load_base(self):
        key = self.cmb_base.currentText()
        assembly_id = self._assembly_map.get(key)
        try:
            self._build_start_ts = time.perf_counter()
            self._refresh_elapsed_label()
            if not assembly_id:
                self._working_nodes = []
                self._update_nodes_list()
                self._render_scene()
                self._append("已切换为空装配")
                return

            self._working_nodes = self.service.load_base_nodes(assembly_id)
            self._update_nodes_list()
            self._render_scene()
            self._append(f"已加载基础装配节点: {len(self._working_nodes)}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"加载基础装配失败：{e}")

    def _elapsed_seconds(self) -> float:
        if self._build_start_ts is None:
            return 0.0
        return max(0.0, time.perf_counter() - self._build_start_ts)

    def _refresh_elapsed_label(self):
        self.lbl_elapsed.setText(f"拼装计时：{self._elapsed_seconds():.3f} 秒")

    def _on_part_selected(self, item: QListWidgetItem):
        part = item.data(Qt.UserRole) or {}
        cur_id = (self._current_preview_part or {}).get("version_id")
        new_id = part.get("version_id")
        if cur_id and new_id and cur_id == new_id:
            self._current_preview_part = None
            self.list_parts.clearSelection()
            self._render_scene(preview_part=None)
            self._append("已取消零件预览")
            return

        self._current_preview_part = part
        self._render_scene(preview_part=part)

    def _on_add_part(self):
        item = self.list_parts.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个零件")
            return
        part = item.data(Qt.UserRole) or {}
        node = {
            "local_id": f"new_{len(self._working_nodes) + 1}_{part.get('version_id', '')[:8]}",
            "node_name": f"{part.get('part_name', 'Part')}-{len(self._working_nodes) + 1}",
            "part_name": part.get("part_name", "Part"),
            "part_version_id": part.get("version_id", ""),
            "step_uri": part.get("step_uri", ""),
            "transform": {"pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0]},
        }
        self._working_nodes.append(node)
        self._update_nodes_list()
        self._render_scene(preview_part=self._current_preview_part)
        self._append(f"已添加零件: {node['part_name']}")

    def _on_remove_selected(self):
        row = self.list_nodes.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一个拼装零件")
            return
        removed = self._working_nodes.pop(row)
        self._update_nodes_list()
        self._render_scene(preview_part=self._current_preview_part)
        self._append(f"已删除零件: {removed.get('part_name', '')}")

    def _on_working_node_selected(self, item: QListWidgetItem):
        row = self.list_nodes.row(item)
        if row < 0 or row >= len(self._working_nodes):
            return
        tf = self._working_nodes[row].get("transform", {})
        pos = self._extract_pos(tf)
        self.edit_x.setText(str(pos[0]))
        self.edit_y.setText(str(pos[1]))
        self.edit_z.setText(str(pos[2]))
        self._render_scene(preview_part=self._current_preview_part)

    def _on_apply_position(self):
        row = self.list_nodes.currentRow()
        if row < 0 or row >= len(self._working_nodes):
            QMessageBox.information(self, "提示", "请先选择一个拼装零件")
            return
        try:
            x = float(self.edit_x.text().strip())
            y = float(self.edit_y.text().strip())
            z = float(self.edit_z.text().strip())
        except ValueError:
            QMessageBox.warning(self, "提示", "X/Y/Z 必须是数字")
            return

        self._working_nodes[row]["transform"] = {"pos": [x, y, z], "quat": [1.0, 0.0, 0.0, 0.0]}
        self._update_nodes_list()
        self._render_scene(preview_part=self._current_preview_part)

    def _on_save(self):
        name = self.edit_name.text().strip()
        desc = self.edit_desc.text().strip()
        try:
            elapsed = self._elapsed_seconds()
            assembly_id, count, obj_path, glb_path = self.service.save_assembly(name, desc, self._working_nodes)
            self._append(f"[保存成功] 装配ID: {assembly_id}，节点数: {count}")
            msg = f"新装配已保存\nID: {assembly_id}\n节点数: {count}\n用时: {elapsed:.3f} 秒"
            if obj_path:
                msg += f"\nOBJ: {obj_path}"
                self._append(f"[OBJ] 已导出: {obj_path}")
            if glb_path:
                msg += f"\nGLB: {glb_path}"
                self._append(f"[GLB] 已导出: {glb_path}")
            self._append(f"[计时] 从加载模板到入库耗时: {elapsed:.3f} 秒")
            QMessageBox.information(self, "保存成功", msg)
            if self.on_saved:
                self.on_saved()
            self._load_assemblies()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存到数据库失败：{e}")

    def _update_nodes_list(self):
        self.list_nodes.clear()
        for n in self._working_nodes:
            p = self._extract_pos(n.get("transform", {}))
            text = f"{n.get('node_name', '')}  @ ({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, n)
            self.list_nodes.addItem(item)

    def _extract_pos(self, tf: Dict[str, Any]) -> List[float]:
        if isinstance(tf.get("pos"), list) and len(tf["pos"]) == 3:
            return [float(tf["pos"][0]), float(tf["pos"][1]), float(tf["pos"][2])]
        m = tf.get("matrix")
        if isinstance(m, list) and len(m) == 16:
            mm = [float(v) for v in m]
            if abs(mm[15] - 1.0) < 1e-9:
                return [mm[3], mm[7], mm[11]]
            scale = float(os.getenv("SW_TRANSFORM_TRANSLATION_SCALE", "1000"))
            return [mm[9] * scale, mm[10] * scale, mm[11] * scale]
        return [0.0, 0.0, 0.0]

    def _get_shape_cached(self, step_uri: str):
        if not step_uri:
            return None
        if step_uri in self._shape_cache:
            return self._shape_cache[step_uri]
        shape, err = self.service.load_step_shape(step_uri)
        if shape is None:
            self._append(f"[警告] 外观加载失败: {step_uri} ({err})")
            return None
        self._shape_cache[step_uri] = shape
        return shape

    def _render_scene(
        self,
        preview_part: Optional[Dict[str, Any]] = None,
        fit_view: bool = True,
        clear_scene: bool = True
    ):
        if not self.on_render:
            return

        selected_row = self.list_nodes.currentRow()
        render_nodes: List[Dict[str, Any]] = []
        for i, n in enumerate(self._working_nodes):
            shape = self._get_shape_cached(n.get("step_uri", ""))
            if shape is None:
                continue
            render_nodes.append({
                "id": n.get("local_id", ""),
                "shape": shape,
                "transform": n.get("transform", {"pos": [0, 0, 0], "quat": [1, 0, 0, 0]}),
                "selected": i == selected_row,
            })

        preview_node = None
        if preview_part:
            ps = self._get_shape_cached(preview_part.get("step_uri", ""))
            if ps is not None:
                preview_node = {
                    "id": "preview",
                    "shape": ps,
                    "transform": {"pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0]},
                }

        self.on_render(render_nodes, preview_node, fit_view, clear_scene)

    def _append(self, text: str):
        self.txt_log.append(text)

    # ---------- 对外拖拽接口 ----------
    def has_selected_working_node(self) -> bool:
        row = self.list_nodes.currentRow()
        return 0 <= row < len(self._working_nodes)

    def begin_drag_move(self):
        self._is_dragging = True

    def end_drag_move(self):
        if not self._is_dragging:
            return
        self._is_dragging = False
        row = self.list_nodes.currentRow()
        self._update_nodes_list()
        if 0 <= row < self.list_nodes.count():
            self.list_nodes.setCurrentRow(row)

    def move_selected_node_by(self, dx: float, dy: float, dz: float):
        """
        通过增量移动当前选中零件位置，并刷新渲染。
        """
        row = self.list_nodes.currentRow()
        if row < 0 or row >= len(self._working_nodes):
            return

        tf = self._working_nodes[row].get("transform", {})
        pos = self._extract_pos(tf)
        new_pos = [pos[0] + dx, pos[1] + dy, pos[2] + dz]
        self._working_nodes[row]["transform"] = {"pos": new_pos, "quat": [1.0, 0.0, 0.0, 0.0]}

        if not self._is_dragging:
            self._update_nodes_list()
            self.list_nodes.setCurrentRow(row)
        self.edit_x.setText(f"{new_pos[0]:.3f}")
        self.edit_y.setText(f"{new_pos[1]:.3f}")
        self.edit_z.setText(f"{new_pos[2]:.3f}")
        self._render_scene(preview_part=self._current_preview_part, fit_view=False, clear_scene=False)
