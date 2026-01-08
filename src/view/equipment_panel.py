# src/view/equipment_panel.py
"""装备展示面板 - 显示要搭载在人体上的装备"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QListWidget,
                               QListWidgetItem, QGroupBox, QMessageBox,
                               QTextEdit, QSplitter)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
import json
from typing import List, Dict, Any, Optional


class EquipmentPanel(QWidget):
    """装备展示面板"""

    equipment_selected = Signal(str)  # 选中装备时发送装备ID
    equipment_loaded = Signal(dict)  # 加载装备数据时发送完整数据

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_equipment = None
        self.equipment_list = []
        self.setup_ui()
        self.load_equipment_list()

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

        self.equipment_list_widget = QListWidget()
        self.equipment_list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.equipment_list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        list_layout.addWidget(self.equipment_list_widget)

        # 列表控制按钮
        list_btn_layout = QHBoxLayout()

        btn_refresh = QPushButton("🔄 刷新")
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

        list_layout.addLayout(list_btn_layout)
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

        # 详细参数（JSON格式）
        detail_layout.addWidget(QLabel("参数详情: "))
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        self.detail_text.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
                background-color: #fafafa;
            }
        """)
        detail_layout.addWidget(self.detail_text)

        detail_group.setLayout(detail_layout)
        splitter.addWidget(detail_group)

        splitter.setSizes([300, 200])
        layout.addWidget(splitter)

        # ===== 底部统计信息 =====
        self.stats_label = QLabel("装备总数: 0")
        self.stats_label.setStyleSheet("color: #666; font-size:  10pt; padding: 5px;")
        layout.addWidget(self.stats_label)

    def load_equipment_list(self):
        """从数据库加载装备列表"""
        try:
            from ..db.mysql import get_conn
            from ..db.util import bin_to_uuid

            conn = get_conn()
            cur = conn.cursor(dictionary=True)

            # 查询所有装配（视为装备）
            cur.execute("""
                        SELECT a.id,
                               a.name,
                               a.created_at,
                               COUNT(an.id) as part_count
                        FROM assemblies a
                                 LEFT JOIN assembly_nodes an ON an.assembly_id = a.id
                        GROUP BY a.id, a.name, a.created_at
                        ORDER BY a.created_at DESC
                        """)

            assemblies = cur.fetchall()
            cur.close()
            conn.close()

            # 清空列表
            self.equipment_list_widget.clear()
            self.equipment_list = []

            # 填充列表
            for asm in assemblies:
                equipment_id = bin_to_uuid(asm['id'])
                equipment_name = asm.get('name', 'Unnamed')
                part_count = asm.get('part_count', 0)
                created_at = str(asm.get('created_at', ''))

                # 存储装备数据
                equipment_data = {
                    'id': equipment_id,
                    'name': equipment_name,
                    'part_count': part_count,
                    'created_at': created_at
                }
                self.equipment_list.append(equipment_data)

                # 创建列表项
                item = QListWidgetItem(f"📦 {equipment_name} ({part_count}个部件)")
                item.setData(Qt.UserRole, equipment_id)
                item.setToolTip(f"ID: {equipment_id}\n创建时间: {created_at}")
                self.equipment_list_widget.addItem(item)

            # 更新统计
            self.stats_label.setText(f"装备总数: {len(self.equipment_list)}")

            if not assemblies:
                self.info_label.setText("⚠️ 数据库中暂无装备\n\n请先导入装配（数据库 → 导入装配并入库）")

        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载装备列表：\n{str(e)}")
            import traceback
            traceback.print_exc()

    def _on_selection_changed(self):
        """选中装备时显示详情"""
        selected_items = self.equipment_list_widget.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        equipment_id = item.data(Qt.UserRole)

        # 查找对应的装备数据
        equipment = next((e for e in self.equipment_list if e['id'] == equipment_id), None)
        if not equipment:
            return

        self.current_equipment = equipment

        # 显示基本信息
        info_text = f"""
<b>装备名称:</b> {equipment['name']}<br>
<b>部件数量:</b> {equipment['part_count']}<br>
<b>创建时间:</b> {equipment['created_at']}<br>
<b>装备ID:</b> <code>{equipment['id']}</code>
        """.strip()
        self.info_label.setText(info_text)

        # 加载详细参数
        self._load_equipment_details(equipment_id)

        # 发送信号
        self.equipment_selected.emit(equipment_id)

    def _load_equipment_details(self, equipment_id: str):
        """加载装备详细参数"""
        try:
            from ..db.mysql import get_conn

            conn = get_conn()
            cur = conn.cursor(dictionary=True)

            # 查询装备的所有节点和参数
            cur.execute("""
                        SELECT an.name as node_name,
                               an.transform_json,
                               pv.params_json,
                               p.name  as part_name
                        FROM assembly_nodes an
                                 LEFT JOIN part_versions pv ON pv.id = an.part_version_id
                                 LEFT JOIN parts p ON p.id = pv.part_id
                        WHERE an.assembly_id = UUID_TO_BIN(%s)
                        """, (equipment_id,))

            nodes = cur.fetchall()
            cur.close()
            conn.close()

            # 格式化显示
            details = {
                "equipment_id": equipment_id,
                "parts": []
            }

            for node in nodes:
                part_detail = {
                    "node_name": node.get('node_name', 'Unknown'),
                    "part_name": node.get('part_name', 'Unknown'),
                    "transform": json.loads(node['transform_json']) if node.get('transform_json') else {},
                    "params": json.loads(node['params_json']) if node.get('params_json') else {}
                }
                details["parts"].append(part_detail)

            # 显示JSON
            detail_json = json.dumps(details, ensure_ascii=False, indent=2)
            self.detail_text.setText(detail_json)

        except Exception as e:
            self.detail_text.setText(f"加载详情失败:  {str(e)}")

    def _on_item_double_clicked(self, item):
        """双击加载装备"""
        self._on_load_equipment()

    def _on_load_equipment(self):
        """加载选中的装备"""
        if not self.current_equipment:
            QMessageBox.warning(self, "未选择", "请先选择一个装备")
            return

        try:
            # 获取完整的装备数据
            equipment_data = self._get_full_equipment_data(self.current_equipment['id'])

            if equipment_data:
                # 发送信号
                self.equipment_loaded.emit(equipment_data)

                QMessageBox.information(
                    self,
                    "加载成功",
                    f"装备 '{self.current_equipment['name']}' 已加载\n\n"
                    f"包含 {len(equipment_data.get('parts', []))} 个部件"
                )
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载装备数据：\n{str(e)}")

    def _get_full_equipment_data(self, equipment_id: str) -> Optional[Dict[str, Any]]:
        """获取完整的装备数据（用于传递给Unity）"""
        try:
            from ..db.mysql import get_conn

            conn = get_conn()
            cur = conn.cursor(dictionary=True)

            # 获取装配信息
            cur.execute("""
                        SELECT id, name, created_at
                        FROM assemblies
                        WHERE id = UUID_TO_BIN(%s)
                        """, (equipment_id,))

            assembly = cur.fetchone()
            if not assembly:
                return None

            # 获取所有节点
            cur.execute("""
                        SELECT an.id,
                               an.name as node_name,
                               an.transform_json,
                               pv.params_json,
                               p.key   as part_key,
                               p.name  as part_name
                        FROM assembly_nodes an
                                 LEFT JOIN part_versions pv ON pv.id = an.part_version_id
                                 LEFT JOIN parts p ON p.id = pv.part_id
                        WHERE an.assembly_id = UUID_TO_BIN(%s)
                        """, (equipment_id,))

            nodes = cur.fetchall()
            cur.close()
            conn.close()

            # 组装数据
            from ..db.util import bin_to_uuid

            equipment_data = {
                "equipment_id": equipment_id,
                "equipment_name": assembly['name'],
                "created_at": str(assembly.get('created_at', '')),
                "parts": []
            }

            for node in nodes:
                part_data = {
                    "id": bin_to_uuid(node['id']),
                    "name": node.get('node_name', 'Unknown'),
                    "part_key": node.get('part_key', ''),
                    "part_name": node.get('part_name', ''),
                    "transform": json.loads(node['transform_json']) if node.get('transform_json') else {
                        "pos": [0, 0, 0],
                        "quat": [1, 0, 0, 0]
                    },
                    "params": json.loads(node['params_json']) if node.get('params_json') else {}
                }
                equipment_data["parts"].append(part_data)

            return equipment_data

        except Exception as e:
            print(f"获取装备数据失败: {e}")
            import traceback
            traceback.print_exc()
            return None