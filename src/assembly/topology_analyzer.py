"""
拓扑邻接分析器 - 3.3.2节核心模块
功能：
1. 构建装配零件的拓扑邻接矩阵
2. 分析接触关系（面-面、边-边、点-点）
3. 识别装配关系链（传递依赖）
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Set, Any, Optional
import numpy as np
from dataclasses import dataclass
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core. Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib  # ✅ 修复：模块级别导入
from OCC.Core. gp import gp_Pnt


@dataclass
class TopologyContact:
    """拓扑接触信息"""
    node_a_id: str
    node_b_id: str
    contact_type: str  # 'face_face', 'edge_edge', 'point_point'
    distance: float
    contact_area: float  # 接触面积/长度
    normal: Tuple[float, float, float]  # 接触法向
    center: Tuple[float, float, float]  # 接触中心


@dataclass
class AdjacencyMatrix:
    """拓扑邻接矩阵"""
    node_ids: List[str]
    matrix: np.ndarray  # n×n矩阵，元素为接触权重
    contacts: List[TopologyContact]

    def get_neighbors(self, node_id: str, threshold: float = 0.01) -> List[str]:
        """获取指定节点的邻居节点"""
        if node_id not in self.node_ids:
            return []
        idx = self.node_ids.index(node_id)
        neighbors = []
        for i, nid in enumerate(self.node_ids):
            if i != idx and self.matrix[idx, i] > threshold:
                neighbors.append(nid)
        return neighbors

    def get_contact_chain(self, start_node: str, end_node: str) -> Optional[List[str]]:
        """查找两个节点之间的接触链（BFS）"""
        if start_node not in self.node_ids or end_node not in self.node_ids:
            return None

        from collections import deque
        queue = deque([(start_node, [start_node])])
        visited = {start_node}

        while queue:
            current, path = queue.popleft()
            if current == end_node:
                return path

            for neighbor in self.get_neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None  # 无连接


class TopologyAnalyzer:
    """拓扑邻接分析器"""

    def __init__(self, contact_threshold: float = 0.1, angle_threshold: float = 5.0):
        """
        参数:
            contact_threshold: 接触距离阈值（mm）
            angle_threshold: 法向角度阈值（度）
        """
        # ✅ 修复：正确缩进属性初始化
        self.contact_threshold = contact_threshold
        self.angle_threshold = np.deg2rad(angle_threshold)

    def analyze_assembly(self, nodes: List[Dict[str, Any]]) -> AdjacencyMatrix:
        """
        分析装配的拓扑邻接关系

        参数:
            nodes: 装配节点列表，每个节点包含:
                - id: 节点ID
                - shape: TopoDS_Shape
                - transform: 位姿变换

        返回:
            AdjacencyMatrix对象
        """
        n = len(nodes)
        node_ids = [node['id'] for node in nodes]
        matrix = np.zeros((n, n), dtype=float)
        contacts = []

        # 两两检测接触
        for i in range(n):
            for j in range(i + 1, n):
                node_a = nodes[i]
                node_b = nodes[j]

                # 先用包围盒快速剔除
                if not self._bboxes_overlap(node_a['shape'], node_b['shape']):
                    continue

                # 详细接触检测
                contact = self._detect_contact(node_a, node_b)
                if contact:
                    contacts. append(contact)
                    weight = self._compute_contact_weight(contact)
                    matrix[i, j] = weight
                    matrix[j, i] = weight

        return AdjacencyMatrix(node_ids=node_ids, matrix=matrix, contacts=contacts)

    def _bboxes_overlap(self, shape_a: TopoDS_Shape, shape_b: TopoDS_Shape) -> bool:
        """包围盒重叠检测"""
        bbox_a = Bnd_Box()
        bbox_b = Bnd_Box()
        brepbndlib.Add(shape_a, bbox_a)  # ✅ 修复：使用模块. 方法
        brepbndlib.Add(shape_b, bbox_b)  # ✅ 修复：使用模块.方法

        # 扩展包围盒以包含接触阈值
        bbox_a. Enlarge(self.contact_threshold)

        return not bbox_a.IsOut(bbox_b)

    def _detect_contact(self, node_a: Dict, node_b: Dict) -> Optional[TopologyContact]:
        """检测两个节点间的接触"""
        shape_a = node_a['shape']
        shape_b = node_b['shape']

        # 使用 BRepExtrema 计算最近距离
        dist_calc = BRepExtrema_DistShapeShape(shape_a, shape_b)
        dist_calc.Perform()

        if not dist_calc. IsDone():
            return None

        min_dist = dist_calc.Value()

        if min_dist > self.contact_threshold:
            return None

        # 获取接触点
        pt_a = dist_calc. PointOnShape1(1)
        pt_b = dist_calc.PointOnShape2(1)
        center = (
            (pt_a.X() + pt_b.X()) / 2,
            (pt_a.Y() + pt_b.Y()) / 2,
            (pt_a.Z() + pt_b.Z()) / 2
        )

        # 计算接触法向（从A指向B）
        dx = pt_b.X() - pt_a.X()
        dy = pt_b.Y() - pt_a.Y()
        dz = pt_b. Z() - pt_a.Z()
        length = np.sqrt(dx*dx + dy*dy + dz*dz) + 1e-10
        normal = (dx/length, dy/length, dz/length)

        # 检测接触类型
        contact_type = self._classify_contact_type(shape_a, shape_b, pt_a, pt_b)

        # 估算接触面积
        contact_area = self._estimate_contact_area(shape_a, shape_b, center, min_dist)

        return TopologyContact(
            node_a_id=node_a['id'],
            node_b_id=node_b['id'],
            contact_type=contact_type,
            distance=min_dist,
            contact_area=contact_area,
            normal=normal,
            center=center
        )

    def _classify_contact_type(self, shape_a: TopoDS_Shape, shape_b: TopoDS_Shape,
                               pt_a: gp_Pnt, pt_b: gp_Pnt) -> str:
        """分类接触类型"""
        dist = pt_a.Distance(pt_b)
        if dist < 1e-6:
            return "face_face"
        elif dist < self.contact_threshold * 0.5:
            return "edge_edge"
        else:
            return "point_point"

    def _estimate_contact_area(self, shape_a: TopoDS_Shape, shape_b: TopoDS_Shape,
                               center: Tuple[float, float, float], dist: float) -> float:
        """估算接触面积"""
        if dist < 1e-6:
            return 100.0
        elif dist < self.contact_threshold * 0.3:
            return 10.0
        else:
            return 1.0

    def _compute_contact_weight(self, contact: TopologyContact) -> float:
        """计算接触权重（用于邻接矩阵）"""
        weight = contact.contact_area / (contact.distance + 0.001)
        return min(weight, 100.0)

    def visualize_adjacency(self, adj_matrix: AdjacencyMatrix, output_path: str = None):
        """可视化邻接矩阵（可选依赖matplotlib）"""
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 8))
            im = ax.imshow(adj_matrix.matrix, cmap='hot', interpolation='nearest')
            ax. set_xticks(range(len(adj_matrix.node_ids)))
            ax.set_yticks(range(len(adj_matrix.node_ids)))
            ax.set_xticklabels([nid[:8] for nid in adj_matrix.node_ids], rotation=45)
            ax. set_yticklabels([nid[:8] for nid in adj_matrix.node_ids])
            plt.colorbar(im, ax=ax, label='Contact Weight')
            plt.title('Assembly Topology Adjacency Matrix')
            plt.tight_layout()

            if output_path:
                plt.savefig(output_path, dpi=150)
            else:
                plt.show()
        except ImportError:
            print("警告: matplotlib未安装，无法可视化邻接矩阵")