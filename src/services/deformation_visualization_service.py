"""
模块功能：
该服务用于把“数据库装配节点”转换成“协同变形引擎可执行数据”，并返回可视化所需结果。

主要职责：
1) 从数据库读取装配节点与几何路径（通过 AssemblyViewerService）。
2) 加载 STEP 几何并构建联动引擎输入节点（id/name/shape/transform）。
3) 接收前端约束参数，调用 CooperativeDeformationEngine 执行联动变形。
4) 输出变形结果、冲突检测结果，供主窗口可视化显示。

本版本修复：
- 支持 file:// URI（如 file://D:/...、file:///D:/...）自动转换为本地路径；
- 增强 STEP 读取失败诊断（文件不存在/读取失败/无根可转移）。
"""

import os
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, unquote

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopoDS import TopoDS_Shape

from src.services.assembly_viewer_service import AssemblyViewerService
from src.assembly.topology_analyzer import TopologyAnalyzer
from src.assembly.cooperative_deformation import (
    CooperativeDeformationEngine,
    DeformationConstraint
)
from src.assembly.deformation_config import DeformationPropagationConfig
from src.assembly.collision_detector import CollisionDetector


@dataclass
class DeformationRunOutput:
    """
    联动变形执行结果封装
    """
    loaded_nodes: List[Dict[str, Any]]
    results: List[Any]
    collisions: List[Any]
    warnings: List[str]


class DeformationVisualizationService:
    """
    联动变形可视化服务
    """

    def __init__(self):
        self.viewer_service = AssemblyViewerService()
        self.topology_analyzer = TopologyAnalyzer()
        self.collision_detector = CollisionDetector()

    def list_assemblies(self) -> List[Dict[str, Any]]:
        """
        获取装配列表（供UI下拉框）
        """
        return self.viewer_service.get_all_assemblies()

    def load_assembly_nodes_with_shapes(self, assembly_id: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        加载装配节点与几何体。

        Returns:
            (nodes, warnings)
            nodes格式：
            {
              "id": str,
              "name": str,
              "shape": TopoDS_Shape,
              "transform": {"pos":[x,y,z], "quat":[w,x,y,z]}
            }
        """
        rows = self.viewer_service.get_assembly_nodes(assembly_id)
        nodes: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for row in rows:
            node_id = row.get("node_id", "")
            node_name = row.get("node_name", node_id or "Unnamed")
            transform = self._parse_transform(row.get("transform_json"))

            # 优先直接用 step_uri；没有则通过 version_id 反查
            step_path = row.get("step_uri")
            if not step_path and row.get("version_id"):
                step_path = self.viewer_service.get_part_geometry(row["version_id"])

            if not step_path:
                warnings.append(f"[{node_name}] 无几何路径，已跳过")
                continue

            shape, err = self._load_step_shape(step_path)
            if shape is None:
                warnings.append(f"[{node_name}] STEP加载失败: {step_path} ({err})")
                continue

            nodes.append({
                "id": node_id,
                "name": node_name,
                "shape": shape,
                "transform": transform
            })

        return nodes, warnings

    def run_deformation(
        self,
        assembly_id: str,
        constraints_payload: List[Dict[str, Any]],
        stiffness: float = 1.0,
        translation_decay: float = 0.7,
        max_graph_depth: int = 3
    ) -> DeformationRunOutput:
        """
        执行联动变形主流程：
        1) 加载真实装配节点
        2) 构建拓扑邻接
        3) 执行协同变形
        4) 检测冲突
        """
        nodes, warnings = self.load_assembly_nodes_with_shapes(assembly_id)
        if not nodes:
            warnings.append("没有可用节点（几何全部加载失败或装配为空）")
            return DeformationRunOutput([], [], [], warnings)

        constraints = self._build_constraints(constraints_payload)

        config = DeformationPropagationConfig(
            translation_decay=translation_decay,
            max_graph_depth=max_graph_depth,
            collision_safe_mode=True,
            collision_step_scale=0.5
        )
        engine = CooperativeDeformationEngine(
            stiffness=stiffness,
            max_iterations=80,
            tolerance=1e-5,
            config=config
        )

        adjacency = self.topology_analyzer.analyze_assembly(nodes)
        results = engine.propagate_deformation(nodes, constraints, adjacency=adjacency)

        deformed_nodes = [
            {
                "id": r.node_id,
                "shape": r.deformed_shape,
                "transform": r.deformed_transform
            }
            for r in results
        ]
        collisions = self.collision_detector.detect_collisions(deformed_nodes)

        return DeformationRunOutput(
            loaded_nodes=nodes,
            results=results,
            collisions=collisions,
            warnings=warnings
        )

    @staticmethod
    def _parse_transform(transform_json: Optional[str]) -> Dict[str, Any]:
        """
        解析数据库 transform_json，兜底默认值
        """
        default_tf = {"pos": [0, 0, 0], "quat": [1, 0, 0, 0]}
        if not transform_json:
            return default_tf

        try:
            if isinstance(transform_json, str):
                tf = json.loads(transform_json)
            else:
                tf = transform_json

            if not isinstance(tf, dict):
                return default_tf

            # 兼容 matrix 存储：优先恢复位移，保证联动变形加载不挤在一起
            pos = tf.get("pos")
            quat = tf.get("quat")
            matrix = tf.get("matrix")
            if (not isinstance(pos, list) or len(pos) != 3) and isinstance(matrix, list) and len(matrix) == 16:
                pos = DeformationVisualizationService._extract_pos_from_matrix16(matrix)
            if not isinstance(pos, list) or len(pos) != 3:
                pos = [0, 0, 0]

            if not isinstance(quat, list) or len(quat) != 4:
                quat = [1, 0, 0, 0]

            out = {"pos": [float(pos[0]), float(pos[1]), float(pos[2])], "quat": quat}
            if isinstance(matrix, list) and len(matrix) == 16:
                out["matrix"] = matrix
            return out
        except Exception:
            return default_tf

    @staticmethod
    def _extract_pos_from_matrix16(matrix: List[Any]) -> List[float]:
        """
        从 16 元矩阵提取平移，兼容两种布局：
        1) 标准 4x4 行主序: tx,ty,tz 在 3/7/11
        2) SolidWorks ArrayData(16): tx,ty,tz 在 9/10/11（通常单位 m）
        """
        m = [float(v) for v in matrix[:16]]
        # 标准齐次矩阵（m[15]≈1）
        if abs(m[15] - 1.0) < 1e-9:
            return [m[3], m[7], m[11]]

        # SW 原始布局，默认 m->mm
        t_scale = float(os.getenv("SW_TRANSFORM_TRANSLATION_SCALE", "1000"))
        return [m[9] * t_scale, m[10] * t_scale, m[11] * t_scale]

    @staticmethod
    def _normalize_step_path(step_path: str) -> str:
        """
        将数据库中的step路径统一为本地文件路径。

        支持：
        - file://D:/solidworks/step/a.step
        - file:///D:/solidworks/step/a.step
        - D:/solidworks/step/a.step
        - D:\\solidworks\\step\\a.step
        """
        if not step_path:
            return ""

        p = str(step_path).strip()

        if p.lower().startswith("file://"):
            u = urlparse(p)
            path = unquote(u.path or "")

            # Windows URI 常见格式：/D:/...
            if len(path) >= 3 and path[0] == "/" and path[2] == ":":
                path = path[1:]

            # 兜底：少数情况下盘符跑到 netloc
            if not path and u.netloc:
                path = unquote(u.netloc)

            p = path

        return os.path.normpath(p)

    def _load_step_shape(self, step_path: str) -> Tuple[Optional[TopoDS_Shape], str]:
        """
        从STEP文件加载TopoDS_Shape。

        Returns:
            (shape, err_msg)
        """
        try:
            local_path = self._normalize_step_path(step_path)

            if not local_path:
                return None, "empty-path"

            if not os.path.exists(local_path):
                return None, f"file-not-found: {local_path}"

            reader = STEPControl_Reader()
            status = reader.ReadFile(local_path)
            if status != IFSelect_RetDone:
                return None, f"read-failed(status={status})"

            roots = reader.TransferRoots()
            if roots == 0:
                return None, "transfer-roots=0"

            shape = reader.OneShape()
            if shape is None:
                return None, "shape-none"

            return shape, ""
        except Exception as e:
            return None, f"exception: {e}"

    @staticmethod
    def _build_constraints(payloads: List[Dict[str, Any]]) -> List[DeformationConstraint]:
        """
        将UI输入约束转换为引擎约束对象
        """
        constraints: List[DeformationConstraint] = []
        for p in payloads:
            ctype = str(p.get("constraint_type", "")).strip()
            node_id = str(p.get("node_id", "")).strip()
            params = p.get("params", {}) or {}

            if not ctype or not node_id:
                continue

            constraints.append(
                DeformationConstraint(
                    node_id=node_id,
                    constraint_type=ctype,
                    params=params
                )
            )
        return constraints
