# src/model/geometry.py
# 在文件顶部重新组织导入语句
from typing import Dict, List, Tuple, Optional, Any
import math
import uuid

# OpenCASCADE 核心导入
from OCC.Core.TopoDS import TopoDS_Face, TopoDS_Shape, TopoDS_Compound, topods, TopoDS_Wire, TopoDS_Edge, TopoDS_Vertex
from OCC.Core.BRep import BRep_Builder, BRep_Tool
from OCC.Core.gp import (gp_Pnt, gp_Dir, gp_Vec, gp_Ax1, gp_Ax2, gp_Ax3,
                         gp_Trsf, gp_Pln, gp_Circ, gp_Cylinder, gp_Cone,
                         gp_Sphere, gp_Torus)
from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_Transform, BRepBuilderAPI_MakeFace,
                                     BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
                                     BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeVertex)
from OCC.Core.BRepPrimAPI import (BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone,
                                  BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeBox,
                                  BRepPrimAPI_MakeTorus, BRepPrimAPI_MakePrism)
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE, TopAbs_VERTEX
from OCC.Core.GeomAbs import GeomAbs_Circle, GeomAbs_C2  # 添加GeomAbs_C2
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCC.Core.TColgp import TColgp_Array2OfPnt  # 添加TColgp_Array2OfPnt
from OCC.Core.Geom import Geom_BezierSurface  # 添加Geom_BezierSurface
from OCC.Core.GeomAPI import GeomAPI_PointsToBSplineSurface  # 添加GeomAPI_PointsToBSplineSurfaces


class GeometricPrimitive:
    """几何基本体的基类"""

    def __init__(self, type_name, faces, fitting_score=1.0):
        self.type = type_name
        self.faces = faces
        self.fitting_score = fitting_score
        self.parameter_history = []
        self.current_history_index = 0
        self.id = str(uuid.uuid4())
        self.original_shape = None  # 保存原始形状

        # 创建原始形状的复合体以保留确切的几何形状
        self._create_original_shape()

    def _create_original_shape(self):
        """创建并保存原始形状复合体"""
        try:
            # 创建复合体
            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)

            # 添加所有面
            for face in self.faces:
                builder.Add(compound, face)

            self.original_shape = compound
        except Exception as e:
            print(f"保存原始形状失败: {str(e)}")

    def has_significant_changes(self, old_params, new_params, tolerance=0.001):
        """检测参数是否有实质性变化"""
        for key, new_value in new_params.items():
            if key not in old_params:
                continue

            old_value = old_params[key]

            # 跳过非参数化属性
            if key in ['type', 'fitting_score', 'faces', 'id']:
                continue

            # 数值比较
            if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
                if abs(new_value - old_value) > tolerance:
                    return True

            # 元组比较 (向量、点等)
            elif isinstance(new_value, tuple) and isinstance(old_value, tuple):
                if len(new_value) == len(old_value):
                    if all(isinstance(x, (int, float)) for x in new_value + old_value):
                        if any(abs(new_value[i] - old_value[i]) > tolerance for i in range(len(new_value))):
                            return True
                else:
                    return True

            # 字符串比较
            elif isinstance(new_value, str) and isinstance(old_value, str):
                if new_value != old_value:
                    return True

            # 其他类型直接比较
            elif new_value != old_value:
                return True

        return False

    def get_params(self) -> Dict:
        """获取参数"""
        return {
            "type": self.type,
            "fitting_score": self.fitting_score,
            "id": self.id
        }

    def create_preview_shape(self, parameters):
        """
        创建参数预览形状 - 根据新参数创建理想化的形状用于预览
        与rebuild_with_parameters不同，此方法真正重建形状而不是返回原始形状
        """
        # 默认实现，子类应重写
        return None

    def rebuild_with_parameters(self, parameters):
        """
        基于参数重建几何体
        子类需要重写此方法
        """
        # 当重建失败或不支持时，返回原始形状
        return self.original_shape

    def undo(self):
        """撤销参数修改"""
        if self.current_history_index > 0:
            self.current_history_index -= 1
            return self.rebuild_with_parameters(self.parameter_history[self.current_history_index])
        return None

    def redo(self):
        """重做参数修改"""
        if self.current_history_index < len(self.parameter_history) - 1:
            self.current_history_index += 1
            return self.rebuild_with_parameters(self.parameter_history[self.current_history_index])
        return None

    @staticmethod
    def normalize_vector(vec):
        """归一化向量"""
        length = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
        if length < 1e-10:
            return (0, 0, 1)  # 默认向上
        return (vec[0] / length, vec[1] / length, vec[2] / length)

    @staticmethod
    def cross_product(v1, v2):
        """计算叉积"""
        return (
            v1[1] * v2[2] - v1[2] * v2[1],
            v1[2] * v2[0] - v1[0] * v2[2],
            v1[0] * v2[1] - v1[1] * v2[0]
        )

    def can_undo(self):
        """检查是否可以撤销"""
        return self.current_history_index > 0

    def can_redo(self):
        """检查是否可以重做"""
        return self.current_history_index < len(self.parameter_history) - 1

class Plane(GeometricPrimitive):
    """平面几何体"""

    def __init__(self, faces, normal, origin, width, height, shape_type="rectangle", fitting_score=1.0):
        super().__init__("plane", faces, fitting_score)
        self.normal = normal
        self.origin = origin
        self.width = width
        self.height = height
        self.shape_type = shape_type  # 形状类型："rectangle" 或 "circle"

        # 尝试检测形状类型（如果未指定）
        if self.shape_type == "rectangle" and len(faces) > 0:
            self._detect_shape_type()

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Plane类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建平面预览形状"""
        try:
            # 提取新参数
            new_normal = parameters.get("normal", self.normal)
            new_origin = parameters.get("origin", self.origin)
            new_width = parameters.get("width", self.width)
            new_height = parameters.get("height", self.height)
            new_shape_type = parameters.get("shape_type", self.shape_type)

            # 归一化法向量
            norm_normal = self.normalize_vector(new_normal)

            # 创建点和方向
            pnt = gp_Pnt(*new_origin)
            direction = gp_Dir(*norm_normal)

            # 根据形状类型创建不同的预览形状
            if new_shape_type == "circle":
                # 创建圆形面
                # 创建坐标系，Z轴为法向量
                from OCC.Core.gp import gp_Circ, gp_Ax2

                # 创建带方向的坐标系，Z轴为法向量
                ax2 = gp_Ax2(pnt, direction)

                # 创建圆
                radius = new_width / 2
                circle = gp_Circ(ax2, radius)

                # 创建边、线框和面
                edge = BRepBuilderAPI_MakeEdge(circle).Edge()
                wire = BRepBuilderAPI_MakeWire(edge).Wire()
                face = BRepBuilderAPI_MakeFace(wire).Face()
                return face
            else:
                # 创建矩形面
                plane = gp_Pln(pnt, direction)
                face = BRepBuilderAPI_MakeFace(plane, -new_width / 2, new_width / 2,
                                               -new_height / 2, new_height / 2).Face()
                return face

        except Exception as e:
            print(f"创建平面预览形状失败: {str(e)}")
            return None

    def _detect_shape_type(self):
        """自动检测平面形状类型"""
        try:
            from OCC.Core.TopExp import TopExp_Explorer
            from OCC.Core.TopAbs import TopAbs_WIRE, TopAbs_EDGE
            from OCC.Core.TopoDS import topods
            from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
            from OCC.Core.GeomAbs import GeomAbs_Circle

            # 获取第一个面的边界
            explorer = TopExp_Explorer(self.faces[0], TopAbs_WIRE)
            if not explorer.More():
                return

            wire = topods.Wire(explorer.Current())

            # 获取线框的边
            edges = []
            edge_explorer = TopExp_Explorer(wire, TopAbs_EDGE)
            while edge_explorer.More():
                edges.append(topods.Edge(edge_explorer.Current()))
                edge_explorer.Next()

            # 检查是否是圆（通常只有一条边）
            if len(edges) == 1:
                curve = BRepAdaptor_Curve(edges[0])
                if curve.GetType() == GeomAbs_Circle:
                    self.shape_type = "circle"
                    # 更新尺寸为圆直径
                    self.width = self.height = curve.Circle().Radius() * 2
        except Exception as e:
            print(f"检测形状类型失败: {str(e)}")

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "normal": self.normal,
            "origin": self.origin,
            "width": self.width,
            "height": self.height,
            "shape_type": self.shape_type
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建平面"""
        # 提取新参数
        new_normal = parameters.get("normal", self.normal)
        new_origin = parameters.get("origin", self.origin)
        new_width = parameters.get("width", self.width)
        new_height = parameters.get("height", self.height)
        new_shape_type = parameters.get("shape_type", self.shape_type)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("平面参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.normal = new_normal
        self.origin = new_origin
        self.width = new_width
        self.height = new_height
        self.shape_type = new_shape_type

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Cylinder(GeometricPrimitive):
    """圆柱几何体"""

    def __init__(self, faces, axis, center, radius, height, fitting_score=1.0):
        super().__init__("cylinder", faces, fitting_score)
        self.axis = axis
        self.center = center
        self.radius = radius
        self.height = height

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Cylinder类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建圆柱体预览形状"""
        try:
            # 提取新参数
            new_axis = parameters.get("axis", self.axis)
            new_center = parameters.get("center", self.center)
            new_radius = parameters.get("radius", self.radius)
            new_height = parameters.get("height", self.height)

            # 归一化轴向量
            norm_axis = self.normalize_vector(new_axis)

            # 创建点和方向
            center_point = gp_Pnt(*new_center)
            axis_dir = gp_Dir(*norm_axis)

            # 创建坐标系
            ax2 = gp_Ax2(center_point, axis_dir)

            # 创建圆柱体
            cylinder = BRepPrimAPI_MakeCylinder(ax2, new_radius, new_height).Shape()
            return cylinder

        except Exception as e:
            print(f"创建圆柱体预览形状失败: {str(e)}")
            return None

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
        new_axis = parameters.get("axis", self.axis)
        new_center = parameters.get("center", self.center)
        new_radius = parameters.get("radius", self.radius)
        new_height = parameters.get("height", self.height)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("圆柱体参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.axis = new_axis
        self.center = new_center
        self.radius = new_radius
        self.height = new_height

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Cone(GeometricPrimitive):
    """圆锥几何体"""

    def __init__(self, faces, axis, apex, base_center, radius, height, semi_angle=None, fitting_score=1.0):
        super().__init__("cone", faces, fitting_score)
        self.axis = axis
        self.apex = apex
        self.base_center = base_center
        self.radius = radius
        self.height = height

        # 如果未提供半角，则根据半径和高度计算
        if semi_angle is None:
            self.semi_angle = math.atan(radius / height)
        else:
            self.semi_angle = semi_angle

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Cone类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建圆锥体预览形状"""
        try:
            # 提取新参数
            new_axis = parameters.get("axis", self.axis)
            new_apex = parameters.get("apex", self.apex)
            new_radius = parameters.get("radius", self.radius)
            new_height = parameters.get("height", self.height)
            new_semi_angle = parameters.get("semi_angle", self.semi_angle)

            # 归一化轴向量
            norm_axis = self.normalize_vector(new_axis)

            # 计算底面中心（从顶点沿轴向移动高度距离）
            base_x = new_apex[0] - norm_axis[0] * new_height
            base_y = new_apex[1] - norm_axis[1] * new_height
            base_z = new_apex[2] - norm_axis[2] * new_height
            base_center = gp_Pnt(base_x, base_y, base_z)

            # 创建坐标系，原点在底面中心，Z轴指向顶点
            axis_dir = gp_Dir(-norm_axis[0], -norm_axis[1], -norm_axis[2])  # 方向取反
            ax2 = gp_Ax2(base_center, axis_dir)

            # 创建圆锥体
            cone = BRepPrimAPI_MakeCone(ax2, new_radius, 0, new_height).Shape()
            return cone

        except Exception as e:
            print(f"创建圆锥体预览形状失败: {str(e)}")
            return None

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "axis": self.axis,
            "apex": self.apex,
            "base_center": self.base_center,
            "radius": self.radius,
            "height": self.height,
            "semi_angle": self.semi_angle
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建圆锥体"""
        # 提取新参数
        new_axis = parameters.get("axis", self.axis)
        new_apex = parameters.get("apex", self.apex)
        new_base_center = parameters.get("base_center", self.base_center)
        new_radius = parameters.get("radius", self.radius)
        new_height = parameters.get("height", self.height)
        new_semi_angle = parameters.get("semi_angle", self.semi_angle)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("圆锥体参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.axis = new_axis
        self.apex = new_apex
        self.base_center = new_base_center
        self.radius = new_radius
        self.height = new_height
        self.semi_angle = new_semi_angle

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



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

    # 为Sphere类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建球体预览形状"""
        try:
            # 提取新参数
            new_center = parameters.get("center", self.center)
            new_radius = parameters.get("radius", self.radius)

            # 创建点
            center_point = gp_Pnt(*new_center)

            # 创建球体
            sphere = BRepPrimAPI_MakeSphere(center_point, new_radius).Shape()
            return sphere

        except Exception as e:
            print(f"创建球体预览形状失败: {str(e)}")
            return None

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
        new_center = parameters.get("center", self.center)
        new_radius = parameters.get("radius", self.radius)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("球体参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.center = new_center
        self.radius = new_radius

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Torus(GeometricPrimitive):
    """圆环几何体"""

    def __init__(self, faces, axis, center, major_radius, minor_radius, fitting_score=1.0):
        super().__init__("torus", faces, fitting_score)
        self.axis = axis
        self.center = center
        self.major_radius = major_radius  # 主半径
        self.minor_radius = minor_radius  # 次半径

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Torus类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建圆环体预览形状"""
        try:
            # 提取新参数
            new_axis = parameters.get("axis", self.axis)
            new_center = parameters.get("center", self.center)
            new_major_radius = parameters.get("major_radius", self.major_radius)
            new_minor_radius = parameters.get("minor_radius", self.minor_radius)

            # 归一化轴向量
            norm_axis = self.normalize_vector(new_axis)

            # 创建点和方向
            center_point = gp_Pnt(*new_center)
            axis_dir = gp_Dir(*norm_axis)

            # 创建坐标系
            ax2 = gp_Ax2(center_point, axis_dir)

            # 创建圆环
            torus = BRepPrimAPI_MakeTorus(ax2, new_major_radius, new_minor_radius).Shape()
            return torus

        except Exception as e:
            print(f"创建圆环体预览形状失败: {str(e)}")
            return None

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
        new_axis = parameters.get("axis", self.axis)
        new_center = parameters.get("center", self.center)
        new_major_radius = parameters.get("major_radius", self.major_radius)
        new_minor_radius = parameters.get("minor_radius", self.minor_radius)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("圆环参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.axis = new_axis
        self.center = new_center
        self.major_radius = new_major_radius
        self.minor_radius = new_minor_radius

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Box(GeometricPrimitive):
    """立方体几何体"""

    def __init__(self, faces, center=None, corner=None, dx=10.0, dy=10.0, dz=10.0, direction=(0, 0, 1),
                 fitting_score=1.0):
        super().__init__("box", faces, fitting_score)

        # 处理 center 和 corner 参数
        if corner is None and center is not None:
            self.corner = (center[0] - dx / 2, center[1] - dy / 2, center[2] - dz / 2)
        else:
            self.corner = corner or (0, 0, 0)

        self.dx = dx  # x方向尺寸
        self.dy = dy  # y方向尺寸
        self.dz = dz  # z方向尺寸
        self.direction = direction  # 方向向量

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Box类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建立方体预览形状"""
        try:
            # 提取新参数
            new_corner = parameters.get("corner", self.corner)
            new_dx = parameters.get("dx", self.dx)
            new_dy = parameters.get("dy", self.dy)
            new_dz = parameters.get("dz", self.dz)
            new_direction = parameters.get("direction", self.direction)

            # 创建点
            corner_point = gp_Pnt(*new_corner)

            # 创建立方体
            box = BRepPrimAPI_MakeBox(corner_point, new_dx, new_dy, new_dz).Shape()

            # 如果方向不是默认的(0,0,1)，需要进行旋转
            if new_direction != (0, 0, 1):
                # 计算从(0,0,1)到新方向的旋转
                default_dir = (0, 0, 1)
                rotation_axis = self.cross_product(default_dir, new_direction)

                # 如果叉积接近零，说明方向平行或反平行
                if (abs(rotation_axis[0]) < 1e-6 and
                        abs(rotation_axis[1]) < 1e-6 and
                        abs(rotation_axis[2]) < 1e-6):
                    # 如果方向相反，绕任意轴旋转180度
                    if new_direction[2] < 0:
                        rotation_axis = (1, 0, 0)
                        angle = math.pi
                    else:
                        # 方向相同，不需要旋转
                        return box
                else:
                    # 计算旋转角度
                    dot_product = (default_dir[0] * new_direction[0] +
                                   default_dir[1] * new_direction[1] +
                                   default_dir[2] * new_direction[2])
                    angle = math.acos(dot_product)

                # 创建旋转变换
                center_point = gp_Pnt(
                    new_corner[0] + new_dx / 2,
                    new_corner[1] + new_dy / 2,
                    new_corner[2] + new_dz / 2
                )
                rotation_axis = self.normalize_vector(rotation_axis)
                rotation_dir = gp_Dir(*rotation_axis)
                rotation_ax1 = gp_Ax1(center_point, rotation_dir)

                trsf = gp_Trsf()
                trsf.SetRotation(rotation_ax1, angle)

                # 应用变换
                box = BRepBuilderAPI_Transform(box, trsf).Shape()

            return box

        except Exception as e:
            print(f"创建立方体预览形状失败: {str(e)}")
            return None

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "corner": self.corner,
            "dx": self.dx,
            "dy": self.dy,
            "dz": self.dz,
            "direction": self.direction
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建立方体"""
        # 提取新参数
        new_corner = parameters.get("corner", self.corner)
        new_dx = parameters.get("dx", self.dx)
        new_dy = parameters.get("dy", self.dy)
        new_dz = parameters.get("dz", self.dz)
        new_direction = parameters.get("direction", self.direction)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("立方体参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.corner = new_corner
        self.dx = new_dx
        self.dy = new_dy
        self.dz = new_dz
        self.direction = new_direction

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class FreeFormSurface(GeometricPrimitive):
    """自由曲面几何体"""

    def __init__(self, faces, control_points=None, fitting_score=1.0):
        super().__init__("freeform", faces, fitting_score)
        self.control_points = control_points or []

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为FreeFormSurface类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建自由曲面预览形状"""
        try:
            # 对于自由曲面，可能需要特定的库进行操作
            # 由于复杂性，这里提供一个简化的实现，仅用于预览
            from OCC.Core.gp import gp_Pnt2d
            from OCC.Core.Geom import Geom_BezierSurface
            from OCC.Core.TColgp import TColgp_Array2OfPnt

            # 提取新参数
            new_control_points = parameters.get("control_points", self.control_points)

            # 如果没有控制点或太少，创建默认的控制点网格
            if not new_control_points or len(new_control_points) < 4:
                # 创建4x4网格的控制点
                rows, cols = 4, 4
                ctrl_points = TColgp_Array2OfPnt(1, rows, 1, cols)

                # 设置控制点形成一个简单的曲面
                for i in range(1, rows + 1):
                    for j in range(1, cols + 1):
                        x = (i - 1) * 10.0 / (rows - 1) - 5.0
                        y = (j - 1) * 10.0 / (cols - 1) - 5.0
                        # 创建一个简单的波浪形状
                        z = math.sin(x) * math.cos(y) * 2.0
                        ctrl_points.SetValue(i, j, gp_Pnt(x, y, z))
            else:
                # 使用提供的控制点
                # 假设控制点是一个2D网格形式的列表
                rows = int(math.sqrt(len(new_control_points)))
                cols = rows  # 假设是方形网格

                ctrl_points = TColgp_Array2OfPnt(1, rows, 1, cols)
                idx = 0
                for i in range(1, rows + 1):
                    for j in range(1, cols + 1):
                        if idx < len(new_control_points):
                            pt = new_control_points[idx]
                            ctrl_points.SetValue(i, j, gp_Pnt(*pt))
                            idx += 1

            # 创建Bezier曲面
            bezier_surface = Geom_BezierSurface(ctrl_points)

            # 创建面
            from OCC.Core.GeomAPI import GeomAPI_PointsToBSplineSurface
            from OCC.Core.TColgp import TColgp_Array2OfPnt
            from OCC.Core.GeomAbs import GeomAbs_C2
            from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf

            # 采样bezier曲面上的点
            sample_points = TColgp_Array2OfPnt(1, 10, 1, 10)
            for i in range(1, 11):
                u = (i - 1) / 9.0
                for j in range(1, 11):
                    v = (j - 1) / 9.0
                    pnt = bezier_surface.Value(u, v)
                    sample_points.SetValue(i, j, pnt)

            # 从采样点创建BSpline曲面
            bspline_builder = GeomAPI_PointsToBSplineSurface(sample_points, 3, 3, GeomAbs_C2, 0.001)
            bspline_surface = bspline_builder.Surface()

            # 创建面
            face = BRepBuilderAPI_MakeFace(bspline_surface, 0.0, 1.0, 0.0, 1.0, 0.001).Face()
            return face

        except Exception as e:
            print(f"创建自由曲面预览形状失败: {str(e)}")
            return None

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "control_points": self.control_points
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建自由曲面"""
        # 提取新参数
        new_control_points = parameters.get("control_points", self.control_points)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("自由曲面参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.control_points = new_control_points

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Prism(GeometricPrimitive):
    """棱柱几何体"""

    def __init__(self, faces, base_center, axis, height, base_points=None, fitting_score=1.0):
        super().__init__("prism", faces, fitting_score)
        self.base_center = base_center
        self.axis = axis
        self.height = height
        self.base_points = base_points or []

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Prism类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建棱柱预览形状"""
        try:
            # 提取新参数
            new_base_center = parameters.get("base_center", self.base_center)
            new_axis = parameters.get("axis", self.axis)
            new_height = parameters.get("height", self.height)
            new_base_points = parameters.get("base_points", self.base_points)

            # 如果没有基础点，创建一个默认的正多边形
            if not new_base_points:
                # 创建一个正六边形
                sides = 6
                radius = 5.0  # 默认半径
                points = []

                for i in range(sides):
                    angle = 2 * math.pi * i / sides
                    x = new_base_center[0] + radius * math.cos(angle)
                    y = new_base_center[1] + radius * math.sin(angle)
                    z = new_base_center[2]
                    points.append((x, y, z))

                new_base_points = points

            # 创建底面轮廓
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon

            # 创建多边形
            polygon_builder = BRepBuilderAPI_MakePolygon()
            for point in new_base_points:
                polygon_builder.Add(gp_Pnt(*point))
            polygon_builder.Close()  # 闭合多边形

            # 获取创建的线框
            base_wire = polygon_builder.Wire()

            # 创建底面
            base_face = BRepBuilderAPI_MakeFace(base_wire).Face()

            # 沿着轴向拉伸创建棱柱
            from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism

            # 归一化轴向量
            norm_axis = self.normalize_vector(new_axis)

            # 创建方向向量
            direction = gp_Vec(norm_axis[0] * new_height,
                               norm_axis[1] * new_height,
                               norm_axis[2] * new_height)

            # 创建棱柱
            prism = BRepPrimAPI_MakePrism(base_face, direction).Shape()
            return prism

        except Exception as e:
            print(f"创建棱柱预览形状失败: {str(e)}")
            return None

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "base_center": self.base_center,
            "axis": self.axis,
            "height": self.height,
            "base_points": self.base_points
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建棱柱"""
        # 提取新参数
        new_base_center = parameters.get("base_center", self.base_center)
        new_axis = parameters.get("axis", self.axis)
        new_height = parameters.get("height", self.height)
        new_base_points = parameters.get("base_points", self.base_points)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("棱柱参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.base_center = new_base_center
        self.axis = new_axis
        self.height = new_height
        self.base_points = new_base_points

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Pyramid(GeometricPrimitive):
    """棱锥几何体"""

    def __init__(self, faces, base_center, apex, base_points=None, fitting_score=1.0):
        super().__init__("pyramid", faces, fitting_score)
        self.base_center = base_center
        self.apex = apex
        self.base_points = base_points or []

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Pyramid类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建棱锥预览形状"""
        try:
            # 添加本地导入
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, \
                BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeEdge
            from OCC.Core.BRep import BRep_Builder
            from OCC.Core.TopoDS import TopoDS_Compound

            # 提取新参数
            new_base_center = parameters.get("base_center", self.base_center)
            new_apex = parameters.get("apex", self.apex)  # 确保 self.apex 有值

            # 添加检查确保 new_apex 有值
            if new_apex is None:
                print("顶点坐标为空，使用默认值")
                new_apex = (0, 0, 10)  # 设置默认顶点坐标

            new_base_points = parameters.get("base_points", self.base_points)

            # 如果没有基础点，创建一个默认的正多边形
            if not new_base_points:
                # 创建一个正方形底面
                sides = 4
                radius = 5.0  # 默认半径
                points = []

                for i in range(sides):
                    angle = 2 * math.pi * i / sides
                    x = new_base_center[0] + radius * math.cos(angle)
                    y = new_base_center[1] + radius * math.sin(angle)
                    z = new_base_center[2]
                    points.append((x, y, z))

                new_base_points = points

            # 创建底面轮廓
            # 创建多边形
            polygon_builder = BRepBuilderAPI_MakePolygon()
            for point in new_base_points:
                polygon_builder.Add(gp_Pnt(*point))
            polygon_builder.Close()  # 闭合多边形

            # 获取创建的线框
            base_wire = polygon_builder.Wire()

            # 创建底面
            base_face = BRepBuilderAPI_MakeFace(base_wire).Face()

            # 创建顶点
            apex_point = gp_Pnt(*new_apex)

            # 创建复合体
            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)

            # 添加底面
            builder.Add(compound, base_face)

            # 创建从顶点到底面各点的三角形面
            for i in range(len(new_base_points)):
                p1 = gp_Pnt(*new_base_points[i])
                p2 = gp_Pnt(*new_base_points[(i + 1) % len(new_base_points)])

                # 创建三角形的三条边
                edge1 = BRepBuilderAPI_MakeEdge(apex_point, p1).Edge()
                edge2 = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
                edge3 = BRepBuilderAPI_MakeEdge(p2, apex_point).Edge()

                # 创建三角形线框
                wire = BRepBuilderAPI_MakeWire(edge1, edge2, edge3).Wire()

                # 创建三角形面
                triangle = BRepBuilderAPI_MakeFace(wire).Face()

                # 添加到复合体
                builder.Add(compound, triangle)

            return compound

        except Exception as e:
            print(f"创建棱锥预览形状失败: {str(e)}")
            return None

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "base_center": self.base_center,
            "apex": self.apex,
            "base_points": self.base_points
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建棱锥"""
        # 提取新参数
        new_base_center = parameters.get("base_center", self.base_center)
        new_apex = parameters.get("apex", self.apex)
        new_base_points = parameters.get("base_points", self.base_points)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("棱锥参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.base_center = new_base_center
        self.apex = new_apex
        self.base_points = new_base_points

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape



class Polyhedron(GeometricPrimitive):
    """多面体几何体"""

    def __init__(self, faces, vertices, center, fitting_score=1.0):
        super().__init__("polyhedron", faces, fitting_score)
        self.vertices = vertices
        self.center = center

        # 初始化参数历史
        initial_params = self.get_params()
        self.parameter_history.append(initial_params)
        self.current_history_index = 0

    # 为Polyhedron类添加create_preview_shape方法
    def create_preview_shape(self, parameters):
        """创建多面体预览形状"""
        try:
            # 提取新参数
            new_vertices = parameters.get("vertices", self.vertices)
            new_center = parameters.get("center", self.center)

            # 对于多面体，我们需要有足够的信息来重建它
            # 由于没有足够的信息来创建面，我们使用一个简化的方法
            # 创建一个围绕中心的凸包

            # 如果没有顶点或太少，创建一个默认的正二十面体
            if not new_vertices or len(new_vertices) < 4:
                # 创建一个默认的球形
                center_point = gp_Pnt(*new_center)
                radius = 5.0  # 默认半径
                sphere = BRepPrimAPI_MakeSphere(center_point, radius).Shape()
                return sphere

            # 创建复合体
            from OCC.Core.TopoDS import TopoDS_Compound
            from OCC.Core.BRep import BRep_Builder

            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)

            # 创建简化的多面体 - 使用凸包算法
            try:
                from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
                from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_Sewing
                from OCC.Core.TopoDS import topods

                # 创建点
                vertices = []
                for vertex in new_vertices:
                    pnt = gp_Pnt(*vertex)
                    vert = BRepBuilderAPI_MakeVertex(pnt).Vertex()
                    vertices.append(vert)

                # 创建凸包
                from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
                from OCC.Core.TopTools import TopTools_ListOfShape

                # 使用德劳内三角化或其他方法创建凸包
                # 简化起见，这里我们创建一个连接所有点的多边形
                for i in range(len(vertices) - 2):
                    for j in range(i + 1, len(vertices) - 1):
                        for k in range(j + 1, len(vertices)):
                            # 创建三角形
                            v1 = topods.Vertex(vertices[i])
                            v2 = topods.Vertex(vertices[j])
                            v3 = topods.Vertex(vertices[k])

                            p1 = BRep_Tool.Pnt(v1)
                            p2 = BRep_Tool.Pnt(v2)
                            p3 = BRep_Tool.Pnt(v3)

                            # 创建三角形的三条边
                            edge1 = BRepBuilderAPI_MakeEdge(p1, p2).Edge()
                            edge2 = BRepBuilderAPI_MakeEdge(p2, p3).Edge()
                            edge3 = BRepBuilderAPI_MakeEdge(p3, p1).Edge()

                            # 创建三角形线框
                            wire = BRepBuilderAPI_MakeWire(edge1, edge2, edge3).Wire()

                            # 创建三角形面
                            try:
                                triangle = BRepBuilderAPI_MakeFace(wire).Face()

                                # 添加到复合体
                                builder.Add(compound, triangle)
                            except:
                                # 如果创建面失败，跳过
                                pass

                return compound
            except Exception as inner_e:
                print(f"创建多面体凸包失败，使用替代方法: {str(inner_e)}")

                # 如果凸包创建失败，创建一个简单的球体作为替代
                center_point = gp_Pnt(*new_center)
                radius = 5.0  # 默认半径
                sphere = BRepPrimAPI_MakeSphere(center_point, radius).Shape()
                return sphere

        except Exception as e:
            print(f"创建多面体预览形状失败: {str(e)}")
            # 返回一个简单的球体作为替代
            try:
                center_point = gp_Pnt(*new_center if new_center else self.center)
                radius = 5.0
                sphere = BRepPrimAPI_MakeSphere(center_point, radius).Shape()
                return sphere
            except:
                return None

    def get_params(self) -> Dict:
        params = super().get_params()
        params.update({
            "vertices": self.vertices,
            "center": self.center
        })
        return params

    def rebuild_with_parameters(self, parameters):
        """基于新参数重建多面体"""
        # 提取新参数
        new_vertices = parameters.get("vertices", self.vertices)
        new_center = parameters.get("center", self.center)

        # 获取当前参数
        old_params = self.get_params()

        # 检查是否有实质性变化
        if not self.has_significant_changes(old_params, parameters):
            print("多面体参数无实质性变化，保持原样")
            return self.original_shape

        # 更新参数
        self.vertices = new_vertices
        self.center = new_center

        # 添加到历史
        new_params = self.get_params()
        self.parameter_history.append(new_params)
        self.current_history_index = len(self.parameter_history) - 1

        # 返回原始形状以保留边界
        return self.original_shape
