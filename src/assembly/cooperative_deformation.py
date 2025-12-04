"""
协同几何变形引擎 - 3.3.2节核心模块
功能：
1. 基于约束的形变传播算法
2. 矩阵驱动的几何调整
3. 保持拓扑一致性的变形
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Any, Optional
import numpy as np
from dataclasses import dataclass
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.gp import gp_Trsf, gp_Vec, gp_Pnt, gp_Quaternion, gp_Mat
from OCC.Core.TopLoc import TopLoc_Location

from .topology_analyzer import TopologyAnalyzer, AdjacencyMatrix


@dataclass
class DeformationConstraint:
    """变形约束"""
    node_id: str
    constraint_type: str  # 'fixed', 'displacement', 'rotation', 'scaling'
    params: Dict[str, Any]  # 约束参数


@dataclass
class DeformationResult:
    """变形结果"""
    node_id: str
    original_transform: Dict[str, Any]
    deformed_transform: Dict[str, Any]
    deformed_shape: Optional[TopoDS_Shape]
    energy: float  # 变形能量


class CooperativeDeformationEngine:
    """协同几何变形引擎"""

    def __init__(self, stiffness: float = 1.0, max_iterations: int = 50, tolerance: float = 1e-4):
        """
        参数:
            stiffness: 形变刚度系数
            max_iterations: 最大迭代次数
            tolerance: 收敛容差
        """
        self.stiffness = stiffness
        self.max_iterations = max_iterations
        self.tolerance = tolerance
        self.topology_analyzer = TopologyAnalyzer()

    def propagate_deformation(
            self,
            nodes: List[Dict[str, Any]],
            constraints: List[DeformationConstraint],
            adjacency: Optional[AdjacencyMatrix] = None
    ) -> List[DeformationResult]:
        """
        传播形变到相邻零件

        参数:
            nodes: 装配节点列表
            constraints: 变形约束列表
            adjacency: 预计算的邻接矩阵（可选）

        返回:
            变形结果列表
        """
        # 1. 构建拓扑邻接矩阵
        if adjacency is None:
            adjacency = self.topology_analyzer.analyze_assembly(nodes)

        # 2. 构建拉普拉斯矩阵
        L = self._build_laplacian_matrix(adjacency)

        # 3. 设置约束节点
        fixed_indices = []
        fixed_values = []

        for constraint in constraints:
            if constraint.node_id not in adjacency.node_ids:
                continue
            idx = adjacency.node_ids.index(constraint.node_id)
            fixed_indices.append(idx)
            fixed_values.append(self._constraint_to_vector(constraint))

        # 4. 求解变形场（迭代优化）
        deformation_field = self._solve_deformation_field(
            L, adjacency, nodes, fixed_indices, fixed_values
        )

        # 5. 应用变形到各节点
        results = []
        for i, node in enumerate(nodes):
            deformed_transform = self._apply_deformation(
                node['transform'], deformation_field[i]
            )

            # 生成变形后的形状
            deformed_shape = self._transform_shape(node['shape'], deformed_transform)

            # 计算变形能量
            energy = self._compute_deformation_energy(
                node['transform'], deformed_transform, adjacency, i
            )

            results.append(DeformationResult(
                node_id=node['id'],
                original_transform=node['transform'].copy(),
                deformed_transform=deformed_transform,
                deformed_shape=deformed_shape,
                energy=energy
            ))

        return results

    def _build_laplacian_matrix(self, adjacency: AdjacencyMatrix) -> np.ndarray:
        """构建拉普拉斯矩阵（L = D - W）"""
        n = len(adjacency.node_ids)
        W = adjacency.matrix.copy()

        # 度矩阵
        D = np.diag(W.sum(axis=1))

        # 拉普拉斯矩阵
        L = D - W

        # 归一化（避免数值问题）
        L = L / (np.max(np.abs(L)) + 1e-10)

        return L

    def _constraint_to_vector(self, constraint: DeformationConstraint) -> np.ndarray:
        """将约束转换为向量表示"""
        # 12维向量：[dx, dy, dz, qw, qx, qy, qz, sx, sy, sz, 保留1, 保留2]
        vec = np.zeros(12)

        if constraint.constraint_type == 'displacement':
            disp = constraint.params.get('displacement', [0, 0, 0])
            vec[0:3] = disp
        elif constraint.constraint_type == 'rotation':
            quat = constraint.params.get('quaternion', [1, 0, 0, 0])
            vec[3:7] = quat
        elif constraint.constraint_type == 'scaling':
            scale = constraint.params.get('scale', [1, 1, 1])
            vec[7:10] = scale
        elif constraint.constraint_type == 'fixed':
            # 固定节点：保持原始位姿
            pass

        return vec

    def _solve_deformation_field(
            self,
            L: np.ndarray,
            adjacency: AdjacencyMatrix,
            nodes: List[Dict],
            fixed_indices: List[int],
            fixed_values: List[np.ndarray]
    ) -> np.ndarray:
        """
        求解变形场（迭代优化）- 改进的数值稳定版本

        使用梯度下降法最小化能量函数：
        E = Σ_ij w_ij ||d_i - d_j||² + λ Σ_k ||d_k - d_k^target||²
        """
        n = len(nodes)
        d = 12  # 变形向量维度

        # 初始化变形场（全零）
        deformation = np.zeros((n, d))

        # 设置固定节点的初始值
        for idx, val in zip(fixed_indices, fixed_values):
            deformation[idx] = val

        # 迭代优化参数（改进的数值稳定设置）
        lambda_constraint = 10.0  # 约束项权重
        learning_rate = 0.001  # ✅ 降低学习率从0.01到0.001
        min_learning_rate = 1e-6
        max_gradient_norm = 10.0  # ✅ 添加梯度裁剪阈值
        prev_diff = float('inf')

        print(f"[Deformation] 开始迭代优化，max_iter={self.max_iterations}")

        for iteration in range(self.max_iterations):
            deformation_old = deformation.copy()

            # 计算梯度
            gradient = np.zeros_like(deformation)

            # 1. 拉普拉斯平滑项
            for i in range(n):
                neighbors = adjacency.get_neighbors(adjacency.node_ids[i])
                if not neighbors:
                    continue

                for neighbor_id in neighbors:
                    j = adjacency.node_ids.index(neighbor_id)
                    w_ij = adjacency.matrix[i, j]
                    gradient[i] += 2 * w_ij * (deformation[i] - deformation[j])

            # 2. 约束项
            for idx, target in zip(fixed_indices, fixed_values):
                gradient[idx] += 2 * lambda_constraint * (deformation[idx] - target)

            # ✅ 3. 梯度裁剪（防止数值爆炸）
            gradient_norm = np.linalg.norm(gradient)
            if gradient_norm > max_gradient_norm:
                gradient = gradient * (max_gradient_norm / gradient_norm)
                if iteration % 10 == 0:
                    print(f"[Deformation] Iter {iteration}: 梯度裁剪 {gradient_norm:.2e} -> {max_gradient_norm}")

            # ✅ 4. 梯度下降更新
            deformation -= learning_rate * gradient

            # 5. 强制固定节点
            for idx, val in zip(fixed_indices, fixed_values):
                deformation[idx] = val

            # ✅ 6. 检查收敛
            diff = np.linalg.norm(deformation - deformation_old)

            # 自适应学习率
            if diff > prev_diff * 1.2:  # 如果发散
                learning_rate *= 0.5
                learning_rate = max(learning_rate, min_learning_rate)
                if iteration % 10 == 0:
                    print(f"[Deformation] Iter {iteration}: 降低学习率到 {learning_rate:.2e}")

            prev_diff = diff

            if iteration % 10 == 0:
                print(f"[Deformation] Iter {iteration}: diff={diff:.6e}, lr={learning_rate:.2e}")

            if diff < self.tolerance:
                print(f"[Deformation] 收敛于第 {iteration + 1} 次迭代 (diff={diff:.6e})")
                break
        else:
            print(f"[Deformation] 达到最大迭代次数 {self.max_iterations}，最终diff={diff:.6e}")

        return deformation

    def _apply_deformation(
            self,
            original_transform: Dict[str, Any],
            deformation_vector: np.ndarray
    ) -> Dict[str, Any]:
        """将变形向量应用到位姿变换"""
        # 提取变形分量
        disp = deformation_vector[0:3]
        quat_delta = deformation_vector[3:7]
        scale = deformation_vector[7:10]

        # 应用位移
        pos = np.array(original_transform.get('pos', [0, 0, 0]))
        pos_new = pos + disp

        # 应用旋转（四元数乘法）
        quat_orig = np.array(original_transform.get('quat', [1, 0, 0, 0]))
        if np.linalg.norm(quat_delta) > 0.01:
            quat_new = self._quat_multiply(quat_orig, quat_delta / np.linalg.norm(quat_delta))
        else:
            quat_new = quat_orig

        # 归一化四元数
        quat_new = quat_new / (np.linalg.norm(quat_new) + 1e-10)

        return {
            'pos': pos_new.tolist(),
            'quat': quat_new.tolist(),
            'scale': scale.tolist() if np.any(scale != 0) else [1, 1, 1]
        }

    def _quat_multiply(self, q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
        """四元数乘法"""
        w1, x1, y1, z1 = q1
        w2, x2, y2, z2 = q2
        return np.array([
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
        ])

    def _transform_shape(self, shape: TopoDS_Shape, transform: Dict[str, Any]) -> TopoDS_Shape:
        """应用变换到形状"""
        trsf = gp_Trsf()

        # 设置位移
        pos = transform.get('pos', [0, 0, 0])
        trsf.SetTranslation(gp_Vec(pos[0], pos[1], pos[2]))

        # 设置旋转（四元数）
        quat = transform.get('quat', [1, 0, 0, 0])
        gp_quat = gp_Quaternion(quat[1], quat[2], quat[3], quat[0])  # x,y,z,w
        rot_trsf = gp_Trsf()
        rot_trsf.SetRotation(gp_quat)
        trsf = trsf * rot_trsf

        # 应用变换
        builder = BRepBuilderAPI_Transform(shape, trsf, True)
        return builder.Shape()

    def _compute_deformation_energy(
            self,
            original: Dict[str, Any],
            deformed: Dict[str, Any],
            adjacency: AdjacencyMatrix,
            node_index: int
    ) -> float:
        """计算变形能量"""
        # 位移能量
        pos_orig = np.array(original.get('pos', [0, 0, 0]))
        pos_def = np.array(deformed.get('pos', [0, 0, 0]))
        E_disp = np.linalg.norm(pos_def - pos_orig) ** 2

        # 旋转能量（四元数距离）
        quat_orig = np.array(original.get('quat', [1, 0, 0, 0]))
        quat_def = np.array(deformed.get('quat', [1, 0, 0, 0]))
        E_rot = (1 - abs(np.dot(quat_orig, quat_def))) ** 2

        # 总能量
        return self.stiffness * (E_disp + E_rot)