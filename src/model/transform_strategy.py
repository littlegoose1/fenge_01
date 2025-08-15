# src/model/transform_strategy.py
from typing import Dict, Any, Tuple
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.gp import gp_Trsf, gp_Vec, gp_Pnt, gp_Dir, gp_Ax1, gp_Ax2, gp_Ax3
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
import math


def normalize_vector(vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """归一化向量"""
    length = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
    if length < 1e-10:
        return (0, 0, 1)  # 默认向上
    return (vec[0] / length, vec[1] / length, vec[2] / length)


def cross_product(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """计算叉积"""
    return (
        v1[1] * v2[2] - v1[2] * v2[1],
        v1[2] * v2[0] - v1[0] * v2[2],
        v1[0] * v2[1] - v1[1] * v2[0]
    )


class TransformStrategy:
    """几何体变换策略类"""

    @staticmethod
    def create_translation(from_point: Tuple[float, float, float],
                           to_point: Tuple[float, float, float]) -> gp_Trsf:
        """创建平移变换"""
        dx = to_point[0] - from_point[0]
        dy = to_point[1] - from_point[1]
        dz = to_point[2] - from_point[2]

        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(dx, dy, dz))
        return transform

    @staticmethod
    def create_rotation(center: Tuple[float, float, float],
                        old_dir: Tuple[float, float, float],
                        new_dir: Tuple[float, float, float]) -> gp_Trsf:
        """创建旋转变换"""
        # 归一化方向
        old_norm = normalize_vector(old_dir)
        new_norm = normalize_vector(new_dir)

        # 创建初始点和方向
        center_pnt = gp_Pnt(*center)
        old_direction = gp_Dir(*old_norm)
        new_direction = gp_Dir(*new_norm)

        # 如果方向几乎相同，返回恒等变换
        if abs(old_direction.Dot(new_direction) - 1.0) < 0.001:
            transform = gp_Trsf()
            return transform

        # 如果方向相反，选择任意垂直轴旋转180度
        if abs(old_direction.Dot(new_direction) + 1.0) < 0.001:
            # 找一个垂直于old_direction的向量
            if abs(old_norm[0]) < 0.5:
                rot_axis = normalize_vector(cross_product((1, 0, 0), old_norm))
            else:
                rot_axis = normalize_vector(cross_product((0, 1, 0), old_norm))

            rotation_ax = gp_Ax1(center_pnt, gp_Dir(*rot_axis))
            transform = gp_Trsf()
            transform.SetRotation(rotation_ax, math.pi)  # 旋转180度
            return transform

        # 一般情况：计算旋转轴和角度
        # 旋转轴是两个方向的叉积
        cross = cross_product(old_norm, new_norm)
        rot_axis = normalize_vector(cross)

        # 计算旋转角度 (acos of dot product)
        angle = math.acos(min(1.0, max(-1.0,
                                       old_direction.Dot(new_direction))))

        # 创建旋转轴和变换
        rotation_ax = gp_Ax1(center_pnt, gp_Dir(*rot_axis))
        transform = gp_Trsf()
        transform.SetRotation(rotation_ax, angle)
        return transform

    @staticmethod
    def create_scaling(center: Tuple[float, float, float],
                       scale_factor: float) -> gp_Trsf:
        """创建缩放变换"""
        transform = gp_Trsf()
        transform.SetScale(gp_Pnt(*center), scale_factor)
        return transform

    @staticmethod
    def apply_transform(shape: TopoDS_Shape, transform: gp_Trsf) -> TopoDS_Shape:
        """应用变换到形状"""
        try:
            result = BRepBuilderAPI_Transform(shape, transform).Shape()
            return result
        except Exception as e:
            print(f"应用变换失败: {str(e)}")
            return shape

    @staticmethod
    def composite_transform(*transforms) -> gp_Trsf:
        """组合多个变换"""
        result = gp_Trsf()

        for transform in transforms:
            result.Multiply(transform)

        return result