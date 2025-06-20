# src/model/geometry.py
from typing import Dict, List, Tuple, Optional, Union
from OCC.Core.TopoDS import TopoDS_Face, TopoDS_Shape, TopoDS_Compound
from OCC.Core.BRepPrimAPI import (BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere,
                                  BRepPrimAPI_MakeCone, BRepPrimAPI_MakeBox)
from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Vec, gp_Trsf
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.BRep import BRep_Builder
import numpy as np


def normalize_vector(vector: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """标准化向量"""
    mag = np.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
    if mag < 1e-10:
        return (0, 0, 0)
    return (vector[0] / mag, vector[1] / mag, vector[2] / mag)


def cross_product(v1, v2):
    """计算两个向量的叉积"""
    return (
        v1[1] * v2[2] - v1[2] * v2[1],
        v1[2] * v2[0] - v1[0] * v2[2],
        v1[0] * v2[1] - v1[1] * v2[0]
    )


class GeometricPrimitive:
    """基本几何体的抽象基类"""

    def __init__(self, type_name, faces, fitting_score=1.0):
        self.type = type_name
        self.faces = faces
        self.fitting_score = fitting_score

        # 记录参数的历史变化，用于撤销/重做功能
        self.parameter_history = []
        self.current_history_index = -1

    def get_params(self) -> Dict:
        """返回参数化表示"""
        return {"type": self.type}

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建几何体（抽象方法）"""
        raise NotImplementedError("子类必须实现此方法")

    def save_parameters_to_history(self, params):
        """保存参数到历史记录"""
        # 如果我们在历史记录中间进行了修改，删除当前位置之后的历史
        if self.current_history_index < len(self.parameter_history) - 1:
            self.parameter_history = self.parameter_history[:self.current_history_index + 1]

        # 添加新的参数到历史
        self.parameter_history.append(params)
        self.current_history_index = len(self.parameter_history) - 1

    def can_undo(self):
        """检查是否可以撤销"""
        return self.current_history_index > 0

    def can_redo(self):
        """检查是否可以重做"""
        return self.current_history_index < len(self.parameter_history) - 1

    def undo(self):
        """撤销到上一个参数状态"""
        if not self.can_undo():
            return None

        self.current_history_index -= 1
        return self.rebuild_with_parameters(self.parameter_history[self.current_history_index])

    def redo(self):
        """重做到下一个参数状态"""
        if not self.can_redo():
            return None

        self.current_history_index += 1
        return self.rebuild_with_parameters(self.parameter_history[self.current_history_index])

    def __str__(self) -> str:
        return f"{self.type} (匹配度: {self.fitting_score:.2f})"


class Plane(GeometricPrimitive):
    """平面几何体"""

    def __init__(self, faces, normal, origin, width=0.0, height=0.0, fitting_score=1.0):
        super().__init__("plane", faces, fitting_score)
        self.normal = normal
        self.origin = origin
        self.width = width
        self.height = height

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "normal": self.normal,
            "origin": self.origin,
            "width": self.width,
            "height": self.height
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建平面"""
        # 提取新参数
        new_width = parameters.get("width", self.width)
        new_height = parameters.get("height", self.height)
        new_origin = parameters.get("origin", self.origin)
        new_normal = parameters.get("normal", self.normal)

        # 创建正交坐标系
        z_axis = normalize_vector(new_normal)

        # 寻找垂直于法向量的两个向量
        if abs(z_axis[0]) < 0.5:
            x_temp = (1, 0, 0)
        else:
            x_temp = (0, 1, 0)

        y_axis = normalize_vector(cross_product(z_axis, x_temp))
        x_axis = normalize_vector(cross_product(y_axis, z_axis))

        # 创建盒体
        half_width = new_width / 2
        half_height = new_height / 2
        thickness = min(new_width, new_height) / 100  # 薄板

        # 创建坐标系
        ax = gp_Ax2(
            gp_Pnt(*new_origin),
            gp_Dir(*z_axis),
            gp_Dir(*x_axis)
        )

        # 创建盒体
        box = BRepPrimAPI_MakeBox(
            ax, new_width, new_height, thickness
        ).Shape()

        # 将盒体移动到中心位置
        transform = gp_Trsf()
        transform.SetTranslation(
            gp_Vec(-half_width, -half_height, -thickness / 2)
        )
        box_moved = BRepBuilderAPI_Transform(box, transform).Shape()

        # 更新参数
        self.width = new_width
        self.height = new_height
        self.origin = new_origin
        self.normal = new_normal

        return box_moved

    def __str__(self) -> str:
        return (f"平面 (匹配度: {self.fitting_score:.2f}) - "
                f"法向量: {self.normal}, 原点: {self.origin}")


class Cylinder(GeometricPrimitive):
    """圆柱体几何体"""

    def __init__(self, faces, axis, center, radius, height=0.0, fitting_score=1.0):
        super().__init__("cylinder", faces, fitting_score)
        self.axis = axis
        self.center = center
        self.radius = radius
        self.height = height

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "axis": self.axis,
            "center": self.center,
            "radius": self.radius,
            "height": self.height
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建圆柱体"""
        # 提取新参数
        new_radius = parameters.get("radius", self.radius)
        new_height = parameters.get("height", self.height)
        new_center = parameters.get("center", self.center)
        new_axis = parameters.get("axis", self.axis)

        # 创建轴向系统
        ax = gp_Ax2(
            gp_Pnt(*new_center),
            gp_Dir(*new_axis)
        )

        # 创建新的圆柱体
        cylinder = BRepPrimAPI_MakeCylinder(ax, new_radius, new_height).Shape()

        # 更新参数
        self.radius = new_radius
        self.height = new_height
        self.center = new_center
        self.axis = new_axis

        return cylinder

    def __str__(self) -> str:
        return (f"圆柱体 (匹配度: {self.fitting_score:.2f}) - "
                f"轴向: {self.axis}, 中心: {self.center}, "
                f"半径: {self.radius:.2f}, 高度: {self.height:.2f}")


class Cone(GeometricPrimitive):
    """圆锥体几何体"""

    def __init__(self, faces, axis, apex, semi_angle, radius, height=0.0, fitting_score=1.0):
        super().__init__("cone", faces, fitting_score)
        self.axis = axis
        self.apex = apex
        self.semi_angle = semi_angle
        self.radius = radius
        self.height = height

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "axis": self.axis,
            "apex": self.apex,
            "semi_angle": self.semi_angle,
            "radius": self.radius,
            "height": self.height
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建圆锥体"""
        # 提取新参数
        new_radius = parameters.get("radius", self.radius)
        new_height = parameters.get("height", self.height)
        new_apex = parameters.get("apex", self.apex)
        new_axis = parameters.get("axis", self.axis)
        new_semi_angle = parameters.get("semi_angle", self.semi_angle)

        # 计算底面中心点
        base_center_x = new_apex[0] - new_axis[0] * new_height
        base_center_y = new_apex[1] - new_axis[1] * new_height
        base_center_z = new_apex[2] - new_axis[2] * new_height
        base_center = (base_center_x, base_center_y, base_center_z)

        # 创建轴向系统
        ax = gp_Ax2(
            gp_Pnt(*base_center),
            gp_Dir(*new_axis)
        )

        # 创建新的圆锥体
        cone = BRepPrimAPI_MakeCone(ax, new_radius, 0, new_height).Shape()

        # 更新参数
        self.radius = new_radius
        self.height = new_height
        self.apex = new_apex
        self.axis = new_axis
        self.semi_angle = new_semi_angle

        return cone

    def __str__(self) -> str:
        return (f"圆锥体 (匹配度: {self.fitting_score:.2f}) - "
                f"轴向: {self.axis}, 顶点: {self.apex}, "
                f"半角: {self.semi_angle:.2f}°, 底半径: {self.radius:.2f}")


class Sphere(GeometricPrimitive):
    """球体几何体"""

    def __init__(self, faces, center, radius, fitting_score=1.0):
        super().__init__("sphere", faces, fitting_score)
        self.center = center
        self.radius = radius

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "center": self.center,
            "radius": self.radius
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建球体"""
        # 提取新参数
        new_radius = parameters.get("radius", self.radius)
        new_center = parameters.get("center", self.center)

        # 创建新的球体
        sphere = BRepPrimAPI_MakeSphere(
            gp_Pnt(*new_center),
            new_radius
        ).Shape()

        # 更新参数
        self.radius = new_radius
        self.center = new_center

        return sphere

    def __str__(self) -> str:
        return (f"球体 (匹配度: {self.fitting_score:.2f}) - "
                f"中心: {self.center}, 半径: {self.radius:.2f}")


class Torus(GeometricPrimitive):
    """圆环几何体"""

    def __init__(self, faces, axis, center, major_radius, minor_radius, fitting_score=1.0):
        super().__init__("torus", faces, fitting_score)
        self.axis = axis
        self.center = center
        self.major_radius = major_radius
        self.minor_radius = minor_radius

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "axis": self.axis,
            "center": self.center,
            "major_radius": self.major_radius,
            "minor_radius": self.minor_radius
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建圆环"""
        # 提取新参数
        new_major_radius = parameters.get("major_radius", self.major_radius)
        new_minor_radius = parameters.get("minor_radius", self.minor_radius)
        new_center = parameters.get("center", self.center)
        new_axis = parameters.get("axis", self.axis)

        # 创建轴向系统
        ax = gp_Ax2(
            gp_Pnt(*new_center),
            gp_Dir(*new_axis)
        )

        # 创建新的圆环
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeTorus
        torus = BRepPrimAPI_MakeTorus(ax, new_major_radius, new_minor_radius).Shape()

        # 更新参数
        self.major_radius = new_major_radius
        self.minor_radius = new_minor_radius
        self.center = new_center
        self.axis = new_axis

        return torus

    def __str__(self) -> str:
        return (f"圆环 (匹配度: {self.fitting_score:.2f}) - "
                f"轴向: {self.axis}, 中心: {self.center}, "
                f"主半径: {self.major_radius:.2f}, 次半径: {self.minor_radius:.2f}")


class FreeFormSurface(GeometricPrimitive):
    """自由曲面几何体"""

    def __init__(self, faces, control_points, fitting_score=1.0):
        super().__init__("freeform", faces, fitting_score)
        self.control_points = control_points

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "control_points_count": len(self.control_points)
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建自由曲面 - 简化版，不支持真正的重建"""
        # 自由曲面重建比较复杂，这里返回原面的复合体
        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)

        for face in self.faces:
            builder.Add(compound, face)

        return compound

    def __str__(self) -> str:
        return (f"自由曲面 (匹配度: {self.fitting_score:.2f}) - "
                f"控制点数量: {len(self.control_points)}")