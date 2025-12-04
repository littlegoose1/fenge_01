"""
装配冲突检测器 - 3.3.2节核心模块
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
import numpy as np

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop  # ✅ 修复：模块级别导入
from OCC.Core.gp import gp_Pnt
from OCC.Core. Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib  # ✅ 修复：模块级别导入


@dataclass
class CollisionInfo:
    """碰撞信息"""
    node_a_id: str
    node_b_id: str
    collision_type: str
    volume: float
    depth: float
    center: Tuple[float, float, float]
    severity: float


@dataclass
class GapAnalysisResult:
    """间隙分析结果"""
    node_a_id: str
    node_b_id: str
    min_gap: float
    max_gap: float
    avg_gap: float
    gap_points: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]


class CollisionDetector:
    """装配冲突检测器"""

    def __init__(
        self,
        penetration_threshold: float = -0.01,
        contact_threshold: float = 0.01,
        clearance_threshold: float = 1.0
    ):
        self.penetration_threshold = penetration_threshold
        self.contact_threshold = contact_threshold
        self.clearance_threshold = clearance_threshold

    def detect_collisions(self, nodes: List[Dict[str, Any]]) -> List[CollisionInfo]:
        """检测装配中的所有碰撞"""
        collisions = []
        n = len(nodes)

        for i in range(n):
            for j in range(i + 1, n):
                collision = self._check_collision(nodes[i], nodes[j])
                if collision:
                    collisions.append(collision)

        return collisions

    def _check_collision(self, node_a: Dict, node_b: Dict) -> Optional[CollisionInfo]:
        """检查两个节点间的碰撞"""
        shape_a = node_a['shape']
        shape_b = node_b['shape']

        # 1. 包围盒快速剔除
        if not self._bboxes_overlap(shape_a, shape_b):
            return None

        # 2. 距离计算
        dist_calc = BRepExtrema_DistShapeShape(shape_a, shape_b)
        dist_calc.Perform()

        if not dist_calc.IsDone():
            return None

        min_dist = dist_calc.Value()

        # 3. 判断碰撞类型
        if min_dist < self.penetration_threshold:
            collision_type = 'penetration'
        elif min_dist < self.contact_threshold:
            collision_type = 'contact'
        elif min_dist < self.clearance_threshold:
            collision_type = 'clearance'
        else:
            return None

        # 4. 计算干涉体积
        volume = 0.0
        depth = abs(min_dist)

        if collision_type == 'penetration':
            try:
                common_op = BRepAlgoAPI_Common(shape_a, shape_b)
                if common_op.IsDone():
                    common_shape = common_op.Shape()
                    props = GProp_GProps()
                    brepgprop.VolumeProperties(common_shape, props)  # ✅ 修复
                    volume = props.Mass()
            except Exception as e:
                print(f"[Collision] 干涉体积计算失败: {e}")

        # 5. 计算碰撞中心
        if dist_calc.NbSolution() > 0:
            pt_a = dist_calc. PointOnShape1(1)
            pt_b = dist_calc.PointOnShape2(1)
            center = (
                (pt_a.X() + pt_b.X()) / 2,
                (pt_a.Y() + pt_b. Y()) / 2,
                (pt_a.Z() + pt_b.Z()) / 2
            )
        else:
            center = (0, 0, 0)

        # 6. 计算严重程度
        if collision_type == 'penetration':
            severity = min(1.0, depth / 10.0)
        elif collision_type == 'contact':
            severity = 0.3
        else:
            severity = 0.1

        return CollisionInfo(
            node_a_id=node_a['id'],
            node_b_id=node_b['id'],
            collision_type=collision_type,
            volume=volume,
            depth=depth,
            center=center,
            severity=severity
        )

    def _bboxes_overlap(self, shape_a: TopoDS_Shape, shape_b: TopoDS_Shape) -> bool:
        """包围盒重叠检测"""
        bbox_a = Bnd_Box()
        bbox_b = Bnd_Box()
        brepbndlib.Add(shape_a, bbox_a)  # ✅ 修复
        brepbndlib.Add(shape_b, bbox_b)  # ✅ 修复
        bbox_a.Enlarge(self.contact_threshold)
        return not bbox_a.IsOut(bbox_b)

    def analyze_gaps(
        self,
        nodes: List[Dict[str, Any]],
        sample_count: int = 100
    ) -> List[GapAnalysisResult]:
        """分析装配中的间隙分布"""
        results = []
        n = len(nodes)

        for i in range(n):
            for j in range(i + 1, n):
                gap_result = self._analyze_gap_between(nodes[i], nodes[j], sample_count)
                if gap_result:
                    results. append(gap_result)

        return results

    def _analyze_gap_between(
        self,
        node_a: Dict,
        node_b: Dict,
        sample_count: int
    ) -> Optional[GapAnalysisResult]:
        """分析两个节点间的间隙"""
        shape_a = node_a['shape']
        shape_b = node_b['shape']

        dist_calc = BRepExtrema_DistShapeShape(shape_a, shape_b)
        dist_calc.Perform()

        if not dist_calc.IsDone():
            return None

        min_gap = dist_calc.Value()

        gap_points = []
        for k in range(1, min(dist_calc.NbSolution(), sample_count) + 1):
            pt_a = dist_calc. PointOnShape1(k)
            pt_b = dist_calc.PointOnShape2(k)
            gap_points.append((
                (pt_a.X(), pt_a.Y(), pt_a.Z()),
                (pt_b.X(), pt_b. Y(), pt_b.Z())
            ))

        if gap_points:
            distances = [
                np.linalg.norm(np.array(pa) - np.array(pb))
                for pa, pb in gap_points
            ]
            max_gap = max(distances)
            avg_gap = sum(distances) / len(distances)
        else:
            max_gap = min_gap
            avg_gap = min_gap

        return GapAnalysisResult(
            node_a_id=node_a['id'],
            node_b_id=node_b['id'],
            min_gap=min_gap,
            max_gap=max_gap,
            avg_gap=avg_gap,
            gap_points=gap_points
        )

    def validate_assembly(self, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """验证装配的可行性"""
        collisions = self.detect_collisions(nodes)

        penetrations = [c for c in collisions if c.collision_type == 'penetration']
        contacts = [c for c in collisions if c.collision_type == 'contact']
        clearances = [c for c in collisions if c.collision_type == 'clearance']

        total_severity = sum(c.severity for c in collisions)
        max_severity = max([c.severity for c in collisions], default=0.0)

        is_valid = len(penetrations) == 0

        return {
            'is_valid': is_valid,
            'total_collisions': len(collisions),
            'penetrations': len(penetrations),
            'contacts': len(contacts),
            'clearances': len(clearances),
            'total_severity': total_severity,
            'max_severity': max_severity,
            'collision_details': [
                {
                    'node_a': c.node_a_id[:8],
                    'node_b': c.node_b_id[:8],
                    'type': c.collision_type,
                    'depth': c.depth,
                    'volume': c.volume,
                    'severity': c.severity
                }
                for c in collisions
            ]
        }