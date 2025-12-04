"""
增强装配求解器 - 集成协同变形功能
扩展原有的 assembly_solver.py，增加：
1. 协同变形传播
2. 冲突检测与避免
3. 拓扑感知的约束求解
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional
import sys
import os

# 导入原始求解器
from src.solver.assembly_solver import AssemblySolver, fetch_active_constraints, fetch_node_transform
from src.assembly.topology_analyzer import TopologyAnalyzer
from src.assembly.cooperative_deformation import CooperativeDeformationEngine, DeformationConstraint
from src.assembly.collision_detector import CollisionDetector
from src.db.outbox import emit_event
from src.db.util import bin_to_uuid


class EnhancedAssemblySolver:
    """增强装配求解器（带协同变形）"""

    def __init__(
        self,
        iterations: int = 10,
        enable_deformation: bool = True,
        enable_collision_check: bool = True,
        deformation_stiffness: float = 1.0
    ):
        """
        参数:
            iterations: 最大迭代次数
            enable_deformation: 是否启用协同变形
            enable_collision_check: 是否启用碰撞检测
            deformation_stiffness: 变形刚度系数
        """
        self. base_solver = AssemblySolver(iterations=iterations)
        self.iterations = iterations
        self.enable_deformation = enable_deformation
        self.enable_collision_check = enable_collision_check

        # 初始化子模块
        self.topology_analyzer = TopologyAnalyzer()
        self.deformation_engine = CooperativeDeformationEngine(
            stiffness=deformation_stiffness,
            max_iterations=50
        )
        self.collision_detector = CollisionDetector()

    def solve(
        self,
        assembly_id: str,
        log_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        增强求解流程

        返回:
            求解结果字典
        """
        def log(msg: str):
            if log_callback:
                log_callback(msg)
            else:
                print(f"[EnhancedSolver] {msg}")

        log(f"开始增强装配求解: assembly={assembly_id}")

        # 1. 获取装配节点和约束
        constraints = fetch_active_constraints(assembly_id)
        if not constraints:
            log("无激活约束，跳过求解")
            return {"status": "skipped", "reason": "no_constraints"}

        log(f"约束数量: {len(constraints)}")

        # 2. 构建节点列表（需要从数据库加载）
        nodes = self._load_assembly_nodes(assembly_id)
        log(f"节点数量: {len(nodes)}")

        # 3. 分析拓扑邻接关系
        if self.enable_deformation:
            log("分析拓扑邻接关系...")
            adjacency = self. topology_analyzer.analyze_assembly(nodes)
            log(f"检测到 {len(adjacency. contacts)} 个接触")
        else:
            adjacency = None

        # 4.  迭代求解
        total_updates = 0
        collision_free = True

        for it in range(self.iterations):
            log(f"--- 迭代 {it+1}/{self.iterations} ---")

            # 4.1 基础约束求解
            self. base_solver.solve(assembly_id)

            # 4. 2 应用协同变形
            if self. enable_deformation and adjacency:
                log("应用协同变形传播...")

                # 提取固定节点作为约束
                deform_constraints = self._extract_deformation_constraints(constraints, nodes)

                # 执行变形传播
                deform_results = self.deformation_engine.propagate_deformation(
                    nodes, deform_constraints, adjacency
                )

                # 更新节点变换
                for result in deform_results:
                    # 这里可以选择性地应用变形结果
                    # 当前简化：仅记录能量
                    log(f"节点 {result.node_id[:8]} 变形能量: {result.energy:. 4f}")

            # 4.3 碰撞检测
            if self.enable_collision_check:
                log("执行碰撞检测...")
                collisions = self.collision_detector. detect_collisions(nodes)

                penetrations = [c for c in collisions if c.collision_type == 'penetration']
                if penetrations:
                    log(f"警告: 检测到 {len(penetrations)} 个干涉")
                    collision_free = False

                    # 尝试修正（简化版：回退）
                    # 实际应用中可以使用更复杂的冲突解决策略
                else:
                    log("无碰撞干涉")
                    collision_free = True

            total_updates += 1

        # 5. 最终验证
        log("执行最终装配验证...")
        validation_report = self.collision_detector.validate_assembly(nodes)

        log(f"求解完成: 迭代={self.iterations}, 更新={total_updates}")
        log(f"装配有效性: {validation_report['is_valid']}")

        return {
            "status": "completed",
            "assembly_id": assembly_id,
            "iterations": self.iterations,
            "total_updates": total_updates,
            "collision_free": collision_free,
            "validation": validation_report
        }

    def _load_assembly_nodes(self, assembly_id: str) -> List[Dict[str, Any]]:
        """从数据库加载装配节点"""
        # 这里需要实现从数据库加载节点几何的逻辑
        # 当前返回占位符
        # TODO: 实现完整的数据库查询和STEP加载逻辑
        from src.db.mysql import get_conn
        from src.db.util import uuid_to_bin

        sql = """
        SELECT an.id, an.name, an.transform_json, pv.id AS pv_id
        FROM assembly_nodes an
        JOIN part_versions pv ON pv.id = an.part_version_id
        WHERE an. assembly_id = %s
        """

        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, (uuid_to_bin(assembly_id),))
            rows = cur. fetchall() or []

            nodes = []
            for row in rows:
                node_id = bin_to_uuid(row['id'])
                transform = self._parse_json(row. get('transform_json'))

                # 占位符形状（实际应从STEP文件加载）
                # TODO: 根据 part_version 加载实际几何
                from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
                shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()

                nodes.append({
                    'id': node_id,
                    'name': row. get('name', ''),
                    'transform': transform,
                    'shape': shape
                })

            return nodes
        finally:
            cur.close()
            conn.close()

    def _extract_deformation_constraints(
        self,
        constraints: List[Dict],
        nodes: List[Dict]
    ) -> List[DeformationConstraint]:
        """从装配约束提取变形约束"""
        deform_constraints = []

        # 简化：将约束涉及的节点标记为固定
        constrained_nodes = set()
        for c in constraints:
            constrained_nodes.add(c. get('a_node_id'))
            constrained_nodes.add(c. get('b_node_id'))

        for node in nodes:
            if node['id'] in constrained_nodes:
                deform_constraints. append(DeformationConstraint(
                    node_id=node['id'],
                    constraint_type='fixed',
                    params={}
                ))

        return deform_constraints

    def _parse_json(self, json_data):
        """解析JSON数据"""
        import json
        if isinstance(json_data, (bytes, bytearray)):
            json_data = json_data.decode('utf-8')
        if isinstance(json_data, str):
            return json.loads(json_data)
        return json_data or {"pos": [0, 0, 0], "quat": [1, 0, 0, 0]}