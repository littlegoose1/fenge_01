# src/view/equipment_panel.py
"""装备展示面板 - 显示要搭载在人体上的装备"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QGroupBox, QMessageBox,
                               QTextEdit, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QStyle, QMenu)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QAction
import json
from typing import List, Dict, Any, Optional


class EquipmentPanel(QWidget):
    """装备展示面板"""

    equipment_selected = Signal(str)  # 选中装备时发送装备ID
    equipment_loaded = Signal(dict)  # 加载装备数据时发送完整数据

    # ✅ 装配管理信号
    assembly_selected = Signal(str)  # assembly_id
    node_selected = Signal(str, str)  # assembly_id, node_id
    load_assembly_requested = Signal(str)  # assembly_id
    refresh_assemblies_requested = Signal()

    # ✅ 新增：加载单个零件进行分割的信号
    load_part_for_segmentation = Signal(str, str)  # part_version_id, step_uri

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_equipment = None
        self.equipment_list = []
        self.setup_ui()

    def setup_ui(self):
        """构建UI"""
        layout = QVBoxLayout(self)

        # ===== 标题 =====
        title_label = QLabel("🎒 装备列表")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # ===== 分割器：上部列表 + 下部详情 =====
        splitter = QSplitter(Qt.Vertical)

        # ----- 上部：装备列表 -----
        list_group = QGroupBox("可用装备")
        list_layout = QVBoxLayout()

        # ✅ 树形控件
        self.equipment_list_widget = QTreeWidget()
        self.equipment_list_widget.setHeaderLabels(["名称", "信息"])
        self.equipment_list_widget.setColumnWidth(0, 200)
        self.equipment_list_widget.setAlternatingRowColors(True)
        self.equipment_list_widget.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                background-color: white;
            }
            QTreeWidget::item {
                padding:  4px;
            }
            QTreeWidget::item: hover {
                background-color: #E8F5E9;
            }
            QTreeWidget::item: selected {
                background-color:  #81C784;
                color: white;
            }
        """)

        # ✅ 连接事件
        self.equipment_list_widget.itemClicked.connect(self._on_tree_item_clicked)
        self.equipment_list_widget.itemDoubleClicked.connect(self._on_tree_item_double_clicked)

        # ✅ 右键菜单
        self.equipment_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.equipment_list_widget.customContextMenuRequested.connect(self._show_context_menu)

        list_layout.addWidget(self.equipment_list_widget)

        # 列表控制按钮
        list_btn_layout = QHBoxLayout()

        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setToolTip("刷新装配列表")
        btn_refresh.clicked.connect(self.load_equipment_list)
        list_btn_layout.addWidget(btn_refresh)

        btn_load = QPushButton("📥 加载选中装备")
        btn_load.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color:  white;
                padding: 6px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        btn_load.clicked.connect(self._on_load_equipment)
        list_btn_layout.addWidget(btn_load)

        # ✅ 清空3D视图按钮
        btn_clear = QPushButton("🗑️ 清空3D")
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                padding: 6px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #FB8C00;
            }
        """)
        btn_clear.clicked.connect(self._on_clear_3d_view)
        list_btn_layout.addWidget(btn_clear)

        list_layout.addLayout(list_btn_layout)

        # ✅ 提示标签
        hint_label = QLabel("💡 双击装配加载全部，双击零件进行分割编辑")
        hint_label.setStyleSheet("""
            QLabel {
                color: #666;
                font-size: 9pt;
                padding: 5px;
                background-color: #FFF9C4;
                border-radius: 3px;
            }
        """)
        list_layout.addWidget(hint_label)

        list_group.setLayout(list_layout)
        splitter.addWidget(list_group)

        # ----- 下部：装备详情 -----
        detail_group = QGroupBox("装备详情")
        detail_layout = QVBoxLayout()

        # 基本信息
        self.info_label = QLabel("请选择一个装备查看详情")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("padding: 10px; background-color: #f5f5f5; border-radius: 5px;")
        detail_layout.addWidget(self.info_label)

        # 详细参数
        detail_layout.addWidget(QLabel("参数详情: "))
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        self.detail_text.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
                background-color:  #fafafa;
            }
        """)
        detail_layout.addWidget(self.detail_text)

        detail_group.setLayout(detail_layout)
        splitter.addWidget(detail_group)

        # 添加分割器到主布局
        layout.addWidget(splitter)

        # 底部统计信息
        self.stats_label = QLabel("装备总数: 0")
        self.stats_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(self.stats_label)

    # ✅ ========== 事件处理 ==========

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """树项单击事件"""
        assembly_id = item.data(0, Qt.UserRole)
        node_id = item.data(0, Qt.UserRole + 1)

        if node_id:
            # 点击的是部件节点
            print(f"选中部件: {item.text(0)}")
            self.node_selected.emit(assembly_id, node_id)
            self._update_detail_for_node(item)
        elif assembly_id:
            # 点击的是装配
            print(f"选中装配: {item.text(0)}")
            self.assembly_selected.emit(assembly_id)
            self._update_detail_for_assembly(item)

    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """树项双击事件"""
        assembly_id = item.data(0, Qt.UserRole)
        node_id = item.data(0, Qt.UserRole + 1)
        part_version_id = item.data(0, Qt.UserRole + 2)
        step_uri = item.data(0, Qt.UserRole + 3)

        if node_id and part_version_id:
            # ✅ 双击部件 - 加载零件进行分割
            print(f"加载零件进行分割: {item.text(0)}")
            self.info_label.setText(
                f"<b>🔧 正在加载零件... </b><br>"
                f"零件: {item.text(0)}<br>"
                f"<i>加载后可在左侧看到识别的几何体</i>"
            )
            self.load_part_for_segmentation.emit(part_version_id, step_uri or "")
        elif not node_id and assembly_id:
            # 双击装配 - 加载整个装配到3D
            print(f"加载装配:  {item.text(0)}")
            self.load_assembly_requested.emit(assembly_id)

    def _show_context_menu(self, position):
        """显示右键菜单"""
        item = self.equipment_list_widget.itemAt(position)
        if not item:
            return

        node_id = item.data(0, Qt.UserRole + 1)

        menu = QMenu(self)

        if node_id:
            # 部件节点菜单
            load_action = QAction("🔧 加载并分割编辑", self)
            load_action.triggered.connect(lambda: self._on_tree_item_double_clicked(item, 0))
            menu.addAction(load_action)

            highlight_action = QAction("✨ 在3D中高亮", self)
            highlight_action.triggered.connect(lambda: self._on_tree_item_clicked(item, 0))
            menu.addAction(highlight_action)
        else:
            # 装配节点菜单
            load_asm_action = QAction("📦 加载整个装配", self)
            load_asm_action.triggered.connect(lambda: self._on_tree_item_double_clicked(item, 0))
            menu.addAction(load_asm_action)

        menu.exec_(self.equipment_list_widget.mapToGlobal(position))

    def _on_clear_3d_view(self):
        """清空3D视图"""
        main_window = self.window()
        if hasattr(main_window, 'canvas'):
            try:
                main_window.canvas._display.EraseAll()
                main_window.canvas._display.Repaint()
                main_window.set_status("已清空3D视图")
            except Exception as e:
                print(f"清空视图失败: {e}")

    def load_equipment_list(self):
        """触发刷新装配列表"""
        self.refresh_assemblies_requested.emit()

    def _on_load_equipment(self):
        """加载按钮点击"""
        current_item = self.equipment_list_widget.currentItem()
        if current_item:
            assembly_id = current_item.data(0, Qt.UserRole)
            if assembly_id:
                self.load_assembly_requested.emit(assembly_id)

    # ✅ ========== 数据填充方法 ==========

    def populate_assembly_tree(self, assemblies: List[Dict[str, Any]]):
        """填充装配树"""
        self.equipment_list_widget.clear()

        if not assemblies:
            empty_item = QTreeWidgetItem(self.equipment_list_widget)
            empty_item.setText(0, "暂无装配")
            empty_item.setForeground(0, QColor("#999"))
            return

        for asm in assemblies:
            asm_item = QTreeWidgetItem(self.equipment_list_widget)
            asm_item.setText(0, asm['name'])
            asm_item.setText(1, f"{asm.get('node_count', 0)} 个部件")
            asm_item.setData(0, Qt.UserRole, asm['id'])
            asm_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))

            font = asm_item.font(0)
            font.setBold(True)
            asm_item.setFont(0, font)
            asm_item.setForeground(0, QColor("#1976D2"))

        self.stats_label.setText(f"装备总数: {len(assemblies)}")

    def populate_assembly_nodes(self, assembly_id: str, nodes: List[Dict[str, Any]]):
        """填充装配的部件节点"""
        for i in range(self.equipment_list_widget.topLevelItemCount()):
            asm_item = self.equipment_list_widget.topLevelItem(i)
            if asm_item.data(0, Qt.UserRole) == assembly_id:
                asm_item.takeChildren()

                # 按零件分组
                part_groups = {}
                for node in nodes:
                    part_key = node['part_key']
                    if part_key not in part_groups:
                        part_groups[part_key] = []
                    part_groups[part_key].append(node)

                # 添加节点
                for part_key, part_nodes in sorted(part_groups.items()):
                    if len(part_nodes) == 1:
                        node = part_nodes[0]
                        node_item = QTreeWidgetItem(asm_item)
                        node_item.setText(0, node['node_name'])
                        node_item.setText(1, f"v{node['version_no']}")
                        node_item.setData(0, Qt.UserRole, assembly_id)
                        node_item.setData(0, Qt.UserRole + 1, node['node_id'])
                        # ✅ 存储零件信息用于分割
                        node_item.setData(0, Qt.UserRole + 2, node.get('version_id', ''))
                        node_item.setData(0, Qt.UserRole + 3, node.get('step_uri', ''))
                        node_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                    else:
                        group_item = QTreeWidgetItem(asm_item)
                        group_item.setText(0, part_key)
                        group_item.setText(1, f"{len(part_nodes)} 个")
                        group_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))

                        for node in part_nodes:
                            instance_item = QTreeWidgetItem(group_item)
                            instance_item.setText(0, node['node_name'])
                            instance_item.setText(1, f"v{node['version_no']}")
                            instance_item.setData(0, Qt.UserRole, assembly_id)
                            instance_item.setData(0, Qt.UserRole + 1, node['node_id'])
                            # ✅ 存储零件信息用于分割
                            instance_item.setData(0, Qt.UserRole + 2, node.get('version_id', ''))
                            instance_item.setData(0, Qt.UserRole + 3, node.get('step_uri', ''))
                            instance_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))

                asm_item.setExpanded(True)
                break

    # ✅ ========== 详情显示 ==========

    def _update_detail_for_assembly(self, item: QTreeWidgetItem):
        """更新装配的详情显示"""
        assembly_name = item.text(0)
        node_count = item.text(1)

        self.info_label.setText(
            f"<b>📦 装配名称: </b> {assembly_name}<br>"
            f"<b>部件数量:</b> {node_count}<br>"
            f"<br>"
            f"<i>💡 双击装配名称可加载到3D视图</i>"
        )
        self.detail_text.clear()

    def _update_detail_for_node(self, item: QTreeWidgetItem):
        """更新部件节点的详情显示"""
        node_name = item.text(0)
        version = item.text(1)

        self.info_label.setText(
            f"<b>🔧 部件名称:</b> {node_name}<br>"
            f"<b>版本:</b> {version}<br>"
            f"<br>"
            f"<i>💡 双击可加载并进行几何分割编辑</i><br>"
            f"<i>💡 单击可在3D视图中高亮显示</i>"
        )
        self.detail_text.clear()