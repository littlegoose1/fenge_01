# src/model/segmentation.py
from typing import List, Dict, Tuple, Callable, Optional, Set, Any
import math
import random
import numpy as np
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE
from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, TopoDS_Compound
# 修改导入语句，正确导入topods函数
from OCC.Core.TopoDS import topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                              GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BezierSurface,
                              GeomAbs_BSplineSurface)
from OCC.Core.gp import gp_Pln, gp_Cylinder, gp_Cone, gp_Sphere, gp_Torus

from .geometry import (GeometricPrimitive, Plane, Cylinder, Cone, Sphere,
                       Torus, FreeFormSurface, Box, Prism, Pyramid, Polyhedron)


class SurfaceClassifier:
    """表面分类器 - 确定面的几何类型"""

    @staticmethod
    def classify_face(face: TopoDS_Face) -> Tuple[str, float, Any]:
        """
        确定面的几何类型

        返回:
            Tuple[str, float, Any]: (几何类型, 适配度, 表面对象)
        """
        try:
            # 获取面的基础几何
            surface = BRepAdaptor_Surface(face)
            surface_type = surface.GetType()

            # 根据类型返回
            if surface_type == GeomAbs_Plane:
                # 平面
                plane = surface.Plane()
                return "plane", 1.0, plane

            elif surface_type == GeomAbs_Cylinder:
                # 圆柱
                cylinder = surface.Cylinder()
                return "cylinder", 1.0, cylinder

            elif surface_type == GeomAbs_Cone:
                # 圆锥
                cone = surface.Cone()
                return "cone", 1.0, cone

            elif surface_type == GeomAbs_Sphere:
                # 球面
                sphere = surface.Sphere()
                return "sphere", 1.0, sphere

            elif surface_type == GeomAbs_Torus:
                # 圆环面
                torus = surface.Torus()
                return "torus", 1.0, torus

            elif surface_type in (GeomAbs_BezierSurface, GeomAbs_BSplineSurface):
                # 自由曲面
                return "freeform", 0.7, None

            else:
                # 其他曲面类型，作为自由曲面处理
                return "freeform", 0.5, None

        except Exception as e:
            print(f"分类面时出错: {str(e)}")
            return "unknown", 0.0, None


class FaceClusterer:
    """面聚类器 - 将属于同一几何体的面分组"""

    def __init__(self, tolerance: float = 0.001):
        self.tolerance = tolerance

    def cluster_faces(self,
                      faces: List[TopoDS_Face],
                      classifications: List[Tuple[str, float, Any]]) -> List[Tuple[str, List[TopoDS_Face], Any, float]]:
        """
        将面聚类为几何体

        参数:
            faces: 面列表
            classifications: 面分类结果列表

        返回:
            List[Tuple[str, List[TopoDS_Face], Any, float]]:
                聚类结果列表，每项为(几何类型, 面列表, 表面对象, 适配度)
        """
        # 初始化结果
        clusters = []
        used_faces = set()

        # 对每种几何类型分别处理
        for geo_type in ["plane", "cylinder", "cone", "sphere", "torus", "freeform"]:
            # 查找所有该类型的面
            candidate_indices = [i for i, (type_name, _, _) in enumerate(classifications)
                                 if type_name == geo_type and i not in used_faces]

            # 如果没有这类面，继续下一种类型
            if not candidate_indices:
                continue

            # 根据几何类型进行聚类
            if geo_type == "plane":
                # 平面按法向量和距离聚类
                plane_clusters = self._cluster_planes(
                    [faces[i] for i in candidate_indices],
                    [classifications[i][2] for i in candidate_indices]
                )

                for face_indices, surface, score in plane_clusters:
                    cluster_faces = [faces[candidate_indices[i]] for i in face_indices]
                    clusters.append((geo_type, cluster_faces, surface, score))
                    # 标记已使用的面
                    for i in face_indices:
                        used_faces.add(candidate_indices[i])

            elif geo_type == "cylinder":
                # 圆柱按轴线和半径聚类
                cylinder_clusters = self._cluster_cylinders(
                    [faces[i] for i in candidate_indices],
                    [classifications[i][2] for i in candidate_indices]
                )

                for face_indices, surface, score in cylinder_clusters:
                    cluster_faces = [faces[candidate_indices[i]] for i in face_indices]
                    clusters.append((geo_type, cluster_faces, surface, score))
                    # 标记已使用的面
                    for i in face_indices:
                        used_faces.add(candidate_indices[i])

            elif geo_type == "cone":
                # 圆锥按轴线、顶点和锥角聚类
                cone_clusters = self._cluster_cones(
                    [faces[i] for i in candidate_indices],
                    [classifications[i][2] for i in candidate_indices]
                )

                for face_indices, surface, score in cone_clusters:
                    cluster_faces = [faces[candidate_indices[i]] for i in face_indices]
                    clusters.append((geo_type, cluster_faces, surface, score))
                    # 标记已使用的面
                    for i in face_indices:
                        used_faces.add(candidate_indices[i])

            elif geo_type == "sphere":
                # 球面按中心和半径聚类
                sphere_clusters = self._cluster_spheres(
                    [faces[i] for i in candidate_indices],
                    [classifications[i][2] for i in candidate_indices]
                )

                for face_indices, surface, score in sphere_clusters:
                    cluster_faces = [faces[candidate_indices[i]] for i in face_indices]
                    clusters.append((geo_type, cluster_faces, surface, score))
                    # 标记已使用的面
                    for i in face_indices:
                        used_faces.add(candidate_indices[i])

            elif geo_type == "torus":
                # 圆环按轴线、中心和半径聚类
                torus_clusters = self._cluster_tori(
                    [faces[i] for i in candidate_indices],
                    [classifications[i][2] for i in candidate_indices]
                )

                for face_indices, surface, score in torus_clusters:
                    cluster_faces = [faces[candidate_indices[i]] for i in face_indices]
                    clusters.append((geo_type, cluster_faces, surface, score))
                    # 标记已使用的面
                    for i in face_indices:
                        used_faces.add(candidate_indices[i])

            elif geo_type == "freeform":
                # 自由曲面按相邻性聚类
                freeform_clusters = self._cluster_freeform(
                    [faces[i] for i in candidate_indices]
                )

                for face_indices, score in freeform_clusters:
                    cluster_faces = [faces[candidate_indices[i]] for i in face_indices]
                    clusters.append((geo_type, cluster_faces, None, score))
                    # 标记已使用的面
                    for i in face_indices:
                        used_faces.add(candidate_indices[i])

        return clusters

    def _cluster_planes(self, faces, planes):
        """聚类平面面"""
        # 平面用法向量和原点到平面的距离表征
        clusters = []
        remaining = list(range(len(faces)))

        while remaining:
            # 取第一个未处理的面
            idx = remaining[0]
            plane = planes[idx]

            # 获取平面法向量和距离
            normal = plane.Axis().Direction()
            normal_vec = (normal.X(), normal.Y(), normal.Z())
            point = plane.Location()
            origin_dist = -(point.X() * normal.X() + point.Y() * normal.Y() + point.Z() * normal.Z())

            # 查找相似平面
            cluster = [idx]
            for i in remaining[1:]:
                other_plane = planes[i]
                other_normal = other_plane.Axis().Direction()
                other_normal_vec = (other_normal.X(), other_normal.Y(), other_normal.Z())

                # 检查法向量是否平行
                dot_product = (normal_vec[0] * other_normal_vec[0] +
                               normal_vec[1] * other_normal_vec[1] +
                               normal_vec[2] * other_normal_vec[2])

                if abs(abs(dot_product) - 1.0) < self.tolerance:
                    # 法向量平行，检查距离
                    other_point = other_plane.Location()
                    other_origin_dist = -(other_point.X() * other_normal.X() +
                                          other_point.Y() * other_normal.Y() +
                                          other_point.Z() * other_normal.Z())

                    if abs(origin_dist - other_origin_dist) < self.tolerance:
                        cluster.append(i)

            # 从剩余列表中移除已聚类的面
            remaining = [i for i in remaining if i not in cluster]
            clusters.append((cluster, plane, 1.0))

        return clusters

    def _cluster_cylinders(self, faces, cylinders):
        """聚类圆柱面"""
        clusters = []
        remaining = list(range(len(faces)))

        while remaining:
            # 取第一个未处理的面
            idx = remaining[0]
            cylinder = cylinders[idx]

            # 获取圆柱轴线和半径
            axis = cylinder.Axis().Direction()
            axis_vec = (axis.X(), axis.Y(), axis.Z())
            center = cylinder.Location()
            center_point = (center.X(), center.Y(), center.Z())
            radius = cylinder.Radius()

            # 查找相似圆柱
            cluster = [idx]
            for i in remaining[1:]:
                other_cylinder = cylinders[i]
                other_axis = other_cylinder.Axis().Direction()
                other_axis_vec = (other_axis.X(), other_axis.Y(), other_axis.Z())

                # 检查轴线是否平行
                dot_product = (axis_vec[0] * other_axis_vec[0] +
                               axis_vec[1] * other_axis_vec[1] +
                               axis_vec[2] * other_axis_vec[2])

                if abs(abs(dot_product) - 1.0) < self.tolerance:
                    # 轴线平行，检查半径
                    other_radius = other_cylinder.Radius()
                    if abs(radius - other_radius) < self.tolerance * max(radius, other_radius):
                        # 半径相似，检查轴线是否共线
                        other_center = other_cylinder.Location()
                        other_center_point = (other_center.X(), other_center.Y(), other_center.Z())

                        # 计算中心点连线与轴线的垂直距离
                        center_diff = (
                            other_center_point[0] - center_point[0],
                            other_center_point[1] - center_point[1],
                            other_center_point[2] - center_point[2]
                        )

                        # 点积获取轴线方向的投影
                        proj = (center_diff[0] * axis_vec[0] +
                                center_diff[1] * axis_vec[1] +
                                center_diff[2] * axis_vec[2])

                        # 投影点
                        proj_point = (
                            center_point[0] + proj * axis_vec[0],
                            center_point[1] + proj * axis_vec[1],
                            center_point[2] + proj * axis_vec[2]
                        )

                        # 计算距离
                        dist = math.sqrt(
                            (other_center_point[0] - proj_point[0]) ** 2 +
                            (other_center_point[1] - proj_point[1]) ** 2 +
                            (other_center_point[2] - proj_point[2]) ** 2
                        )

                        if dist < self.tolerance:
                            cluster.append(i)

            # 从剩余列表中移除已聚类的面
            remaining = [i for i in remaining if i not in cluster]
            clusters.append((cluster, cylinder, 1.0))

        return clusters

    def _cluster_cones(self, faces, cones):
        """聚类圆锥面"""
        clusters = []
        remaining = list(range(len(faces)))

        while remaining:
            # 取第一个未处理的面
            idx = remaining[0]
            cone = cones[idx]

            # 获取圆锥参数
            axis = cone.Axis().Direction()
            axis_vec = (axis.X(), axis.Y(), axis.Z())
            apex = cone.Apex()
            apex_point = (apex.X(), apex.Y(), apex.Z())
            semi_angle = cone.SemiAngle()

            # 查找相似圆锥
            cluster = [idx]
            for i in remaining[1:]:
                other_cone = cones[i]
                other_axis = other_cone.Axis().Direction()
                other_axis_vec = (other_axis.X(), other_axis.Y(), other_axis.Z())

                # 检查轴线是否平行
                dot_product = (axis_vec[0] * other_axis_vec[0] +
                               axis_vec[1] * other_axis_vec[1] +
                               axis_vec[2] * other_axis_vec[2])

                if abs(abs(dot_product) - 1.0) < self.tolerance:
                    # 轴线平行，检查锥角
                    other_semi_angle = other_cone.SemiAngle()
                    if abs(semi_angle - other_semi_angle) < self.tolerance:
                        # 锥角相似，检查顶点
                        other_apex = other_cone.Apex()
                        other_apex_point = (other_apex.X(), other_apex.Y(), other_apex.Z())

                        # 计算顶点距离
                        dist = math.sqrt(
                            (apex_point[0] - other_apex_point[0]) ** 2 +
                            (apex_point[1] - other_apex_point[1]) ** 2 +
                            (apex_point[2] - other_apex_point[2]) ** 2
                        )

                        if dist < self.tolerance:
                            cluster.append(i)

            # 从剩余列表中移除已聚类的面
            remaining = [i for i in remaining if i not in cluster]
            clusters.append((cluster, cone, 1.0))

        return clusters

    def _cluster_spheres(self, faces, spheres):
        """聚类球面"""
        clusters = []
        remaining = list(range(len(faces)))

        while remaining:
            # 取第一个未处理的面
            idx = remaining[0]
            sphere = spheres[idx]

            # 获取球参数
            center = sphere.Location()
            center_point = (center.X(), center.Y(), center.Z())
            radius = sphere.Radius()

            # 查找相似球面
            cluster = [idx]
            for i in remaining[1:]:
                other_sphere = spheres[i]

                # 检查半径
                other_radius = other_sphere.Radius()
                if abs(radius - other_radius) < self.tolerance * max(radius, other_radius):
                    # 半径相似，检查中心
                    other_center = other_sphere.Location()
                    other_center_point = (other_center.X(), other_center.Y(), other_center.Z())

                    # 计算中心距离
                    dist = math.sqrt(
                        (center_point[0] - other_center_point[0]) ** 2 +
                        (center_point[1] - other_center_point[1]) ** 2 +
                        (center_point[2] - other_center_point[2]) ** 2
                    )

                    if dist < self.tolerance:
                        cluster.append(i)

            # 从剩余列表中移除已聚类的面
            remaining = [i for i in remaining if i not in cluster]
            clusters.append((cluster, sphere, 1.0))

        return clusters

    def _cluster_tori(self, faces, tori):
        """聚类圆环面"""
        clusters = []
        remaining = list(range(len(faces)))

        while remaining:
            # 取第一个未处理的面
            idx = remaining[0]
            torus = tori[idx]

            # 获取圆环参数
            axis = torus.Axis().Direction()
            axis_vec = (axis.X(), axis.Y(), axis.Z())
            center = torus.Location()
            center_point = (center.X(), center.Y(), center.Z())
            major_radius = torus.MajorRadius()
            minor_radius = torus.MinorRadius()

            # 查找相似圆环
            cluster = [idx]
            for i in remaining[1:]:
                other_torus = tori[i]
                other_axis = other_torus.Axis().Direction()
                other_axis_vec = (other_axis.X(), other_axis.Y(), other_axis.Z())

                # 检查轴线是否平行
                dot_product = (axis_vec[0] * other_axis_vec[0] +
                               axis_vec[1] * other_axis_vec[1] +
                               axis_vec[2] * other_axis_vec[2])

                if abs(abs(dot_product) - 1.0) < self.tolerance:
                    # 轴线平行，检查半径
                    other_major_radius = other_torus.MajorRadius()
                    other_minor_radius = other_torus.MinorRadius()

                    if (abs(major_radius - other_major_radius) < self.tolerance * max(major_radius,
                                                                                      other_major_radius) and
                            abs(minor_radius - other_minor_radius) < self.tolerance * max(minor_radius,
                                                                                          other_minor_radius)):

                        # 半径相似，检查中心
                        other_center = other_torus.Location()
                        other_center_point = (other_center.X(), other_center.Y(), other_center.Z())

                        # 计算中心距离
                        dist = math.sqrt(
                            (center_point[0] - other_center_point[0]) ** 2 +
                            (center_point[1] - other_center_point[1]) ** 2 +
                            (center_point[2] - other_center_point[2]) ** 2
                        )

                        if dist < self.tolerance:
                            cluster.append(i)

            # 从剩余列表中移除已聚类的面
            remaining = [i for i in remaining if i not in cluster]
            clusters.append((cluster, torus, 1.0))

        return clusters

    def _cluster_freeform(self, faces):
        """聚类自由曲面 - 简单实现，默认每个面独立一个自由曲面"""
        # 实际实现中应该通过拓扑连接性分析将相邻的自由曲面合并
        # 这里简化处理，每个自由曲面独立
        return [([i], 0.7) for i in range(len(faces))]


class GeometricParameterEstimator:
    """几何参数估计 - 为分割的几何体确定参数"""

    @staticmethod
    def estimate_parameters(geo_type: str, faces: List[TopoDS_Face], surface=None) -> Dict:
        """
        估计几何体参数

        参数:
            geo_type: 几何体类型
            faces: 构成几何体的面列表
            surface: 面的基础几何表面对象

        返回:
            Dict: 几何体参数
        """
        try:
            if geo_type == "plane":
                return GeometricParameterEstimator._estimate_plane_params(faces, surface)
            elif geo_type == "cylinder":
                return GeometricParameterEstimator._estimate_cylinder_params(faces, surface)
            elif geo_type == "cone":
                return GeometricParameterEstimator._estimate_cone_params(faces, surface)
            elif geo_type == "sphere":
                return GeometricParameterEstimator._estimate_sphere_params(faces, surface)
            elif geo_type == "torus":
                return GeometricParameterEstimator._estimate_torus_params(faces, surface)
            elif geo_type == "freeform":
                return GeometricParameterEstimator._estimate_freeform_params(faces)
            else:
                return {}

        except Exception as e:
            print(f"参数估计失败: {str(e)}")
            return {}

    @staticmethod
    def _estimate_plane_params(faces, plane):
        """估计平面参数"""
        # 获取平面法向量和原点
        normal = plane.Axis().Direction()
        normal_vec = (normal.X(), normal.Y(), normal.Z())
        point = plane.Location()
        origin = (point.X(), point.Y(), point.Z())

        # 估计面的尺寸和形状类型
        shape_type = "rectangle"  # 默认

        # 尝试检测是否是圆形
        try:
            from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds
            from OCC.Core.TopAbs import TopAbs_WIRE
            from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
            from OCC.Core.GeomAbs import GeomAbs_Circle

            # 获取面的边界
            wires = []
            explorer = TopExp_Explorer(faces[0], TopAbs_WIRE)
            while explorer.More():
                wires.append(topods.Wire(explorer.Current()))
                explorer.Next()

            if wires:
                # 检查是否是圆形边界
                edges = []
                wire_explorer = TopExp_Explorer(wires[0], TopAbs_EDGE)
                while wire_explorer.More():
                    edges.append(topods.Edge(wire_explorer.Current()))
                    wire_explorer.Next()

                if len(edges) == 1:  # 圆通常只有一条边
                    curve = BRepAdaptor_Curve(edges[0])
                    if curve.GetType() == GeomAbs_Circle:
                        shape_type = "circle"
                        # 获取圆半径作为宽度/高度
                        width = height = curve.Circle().Radius() * 2
        except:
            pass  # 如果检测失败，使用默认矩形

        # 估计尺寸
        width = 10.0  # 默认值
        height = 10.0  # 默认值

        return {
            "normal": normal_vec,
            "origin": origin,
            "width": width,
            "height": height,
            "shape_type": shape_type
        }

    @staticmethod
    def _estimate_cylinder_params(faces, cylinder):
        """估计圆柱参数"""
        # 获取轴线和半径
        axis = cylinder.Axis().Direction()
        axis_vec = (axis.X(), axis.Y(), axis.Z())
        center = cylinder.Location()
        center_point = (center.X(), center.Y(), center.Z())
        radius = cylinder.Radius()

        # 估计高度 (默认值，实际应该计算边界)
        height = 10.0

        return {
            "axis": axis_vec,
            "center": center_point,
            "radius": radius,
            "height": height
        }

    @staticmethod
    def _estimate_cone_params(faces, cone):
        """估计圆锥参数"""
        # 获取轴线、顶点和锥角
        axis = cone.Axis().Direction()
        axis_vec = (axis.X(), axis.Y(), axis.Z())
        apex = cone.Apex()
        apex_point = (apex.X(), apex.Y(), apex.Z())
        semi_angle = cone.SemiAngle()

        # 估计底面半径 (默认值，实际应该计算)
        radius = 5.0

        # 估计高度 (默认值，实际应该计算)
        height = 10.0

        return {
            "axis": axis_vec,
            "apex": apex_point,
            "semi_angle": semi_angle,
            "radius": radius,
            "height": height
        }

    @staticmethod
    def _estimate_sphere_params(faces, sphere):
        """估计球体参数"""
        # 获取中心和半径
        center = sphere.Location()
        center_point = (center.X(), center.Y(), center.Z())
        radius = sphere.Radius()

        return {
            "center": center_point,
            "radius": radius
        }

    @staticmethod
    def _estimate_torus_params(faces, torus):
        """估计圆环参数"""
        # 获取轴线、中心和半径
        axis = torus.Axis().Direction()
        axis_vec = (axis.X(), axis.Y(), axis.Z())
        center = torus.Location()
        center_point = (center.X(), center.Y(), center.Z())
        major_radius = torus.MajorRadius()
        minor_radius = torus.MinorRadius()

        return {
            "axis": axis_vec,
            "center": center_point,
            "major_radius": major_radius,
            "minor_radius": minor_radius
        }

    @staticmethod
    def _estimate_freeform_params(faces):
        """估计自由曲面参数"""
        # 自由曲面参数化比较复杂，这里提供一个简化版本
        # 随机生成控制点
        control_points = []
        for _ in range(10):
            control_points.append((
                random.uniform(-10, 10),
                random.uniform(-10, 10),
                random.uniform(-10, 10)
            ))

        return {
            "control_points": control_points
        }

    @staticmethod
    def _estimate_box_params(faces, plane_params_list):
        """估计立方体参数

        通过分析平面参数来确定立方体的尺寸和方向
        """
        # 需要至少3个正交面
        if len(faces) < 3 or len(plane_params_list) < 3:
            return {}

        # 分析法向量，寻找三个互相正交的方向
        normals = [params.get("normal") for params in plane_params_list[:6]]  # 最多6个面

        # 筛选出三个正交方向
        ortho_dirs = []
        for i, n1 in enumerate(normals):
            is_new = True
            for existing in ortho_dirs:
                # 检查是否平行或反平行
                dot = abs(sum(a * b for a, b in zip(n1, existing)))
                if dot > 0.95:  # 几乎平行
                    is_new = False
                    break
            if is_new:
                ortho_dirs.append(n1)
                if len(ortho_dirs) == 3:
                    break

        # 如果没找到三个正交方向，返回空
        if len(ortho_dirs) < 3:
            return {}

        # 使用第一个方向作为主方向
        direction = ortho_dirs[0]

        # 估计中心点 (所有面的中心的平均)
        centers = []
        for params in plane_params_list:
            if "origin" in params:
                centers.append(params["origin"])

        if not centers:
            return {}

        center = (
            sum(c[0] for c in centers) / len(centers),
            sum(c[1] for c in centers) / len(centers),
            sum(c[2] for c in centers) / len(centers)
        )

        # 估计尺寸 (简化处理，实际应计算面之间的距离)
        dx = dy = dz = 10.0  # 默认尺寸

        return {
            "center": center,
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "direction": direction
        }


class GeometrySegmentationProcessor:
    """几何分割处理器 - 整个分割过程的协调者"""

    def __init__(self):
        self.classifier = SurfaceClassifier()
        self.clusterer = FaceClusterer()
        self.parameter_estimator = GeometricParameterEstimator()
        self.status_callback = None
        self.progress_callback = None

    def set_status_callback(self, callback: Callable[[str], None]):
        """设置状态回调"""
        self.status_callback = callback

    def set_progress_callback(self, callback: Callable[[int], None]):
        """设置进度回调"""
        self.progress_callback = callback

    def _report_status(self, message: str):
        """报告状态"""
        if self.status_callback:
            self.status_callback(message)
        else:
            print(message)

    def _report_progress(self, percent: int):
        """报告进度"""
        if self.progress_callback:
            self.progress_callback(percent)

    def use_ransac_fitting(self, faces: List[TopoDS_Face]) -> List[Tuple[str, List[TopoDS_Face], Dict, float]]:
        """
        使用RANSAC算法进行几何体拟合

        参数:
            faces: 面列表

        返回:
            List[Tuple[str, List[TopoDS_Face], Dict, float]]:
                拟合结果列表 (几何类型, 面列表, 参数, 拟合分数)
        """
        from .fitting import RANSACFitter

        # 创建RANSAC拟合器
        fitter = RANSACFitter()

        # 尝试拟合每个面
        results = []
        for face in faces:
            geo_type, params, score = fitter.fit_face(face)
            if geo_type != "unknown" and score > 0.7:
                results.append((geo_type, [face], params, score))

        # 合并相似的拟合结果
        merged_results = []
        used_faces = set()

        for geo_type in ["plane", "cylinder", "sphere", "cone", "torus"]:
            # 查找所有该类型的结果
            type_results = [(i, r) for i, r in enumerate(results)
                            if r[0] == geo_type and i not in used_faces]

            if not type_results:
                continue

            # 基于参数聚类
            while type_results:
                # 取第一个结果
                idx, (_, faces, params, score) = type_results[0]
                used_faces.add(idx)

                # 寻找相似的结果
                similar_indices = []
                for other_idx, (_, other_faces, other_params, _) in type_results[1:]:
                    if self._are_similar_params(geo_type, params, other_params):
                        similar_indices.append(other_idx)
                        faces.extend(other_faces)
                        used_faces.add(other_idx)

                # 合并结果
                merged_results.append((geo_type, faces, params, score))

                # 更新剩余结果
                type_results = [(i, r) for i, r in enumerate(results)
                                if r[0] == geo_type and i not in used_faces]

        return merged_results

    def _are_similar_params(self, geo_type: str, params1: Dict, params2: Dict) -> bool:
        """
        判断两组参数是否相似

        参数:
            geo_type: 几何类型
            params1: 参数1
            params2: 参数2

        返回:
            bool: 是否相似
        """
        tolerance = 0.01

        if geo_type == "plane":
            # 比较法向量和距离
            normal1 = params1.get("normal", (0, 0, 1))
            normal2 = params2.get("normal", (0, 0, 1))

            # 计算法向量点积
            dot_product = sum(n1 * n2 for n1, n2 in zip(normal1, normal2))
            if abs(abs(dot_product) - 1.0) > tolerance:
                return False

            # 比较平面常数
            d1 = params1.get("d", 0)
            d2 = params2.get("d", 0)
            return abs(d1 - d2) <= tolerance

        elif geo_type == "cylinder":
            # 比较轴线、半径
            axis1 = params1.get("axis", (0, 0, 1))
            axis2 = params2.get("axis", (0, 0, 1))

            # 计算轴线点积
            dot_product = sum(a1 * a2 for a1, a2 in zip(axis1, axis2))
            if abs(abs(dot_product) - 1.0) > tolerance:
                return False

            # 比较半径
            radius1 = params1.get("radius", 1.0)
            radius2 = params2.get("radius", 1.0)
            return abs(radius1 - radius2) <= tolerance * max(radius1, radius2)

        elif geo_type == "sphere":
            # 比较中心和半径
            center1 = params1.get("center", (0, 0, 0))
            center2 = params2.get("center", (0, 0, 0))

            # 计算中心距离
            dist = sum((c1 - c2) ** 2 for c1, c2 in zip(center1, center2)) ** 0.5
            if dist > tolerance:
                return False

            # 比较半径
            radius1 = params1.get("radius", 1.0)
            radius2 = params2.get("radius", 1.0)
            return abs(radius1 - radius2) <= tolerance * max(radius1, radius2)

        # 其他几何类型的比较逻辑可以按需添加
        return False

    def process_shape(self, shape: TopoDS_Shape) -> List[GeometricPrimitive]:
        """
        处理几何体，分割为基本几何体

        参数:
            shape: 要处理的几何体

        返回:
            List[GeometricPrimitive]: 分割后的基本几何体列表
        """
        # 1. 提取所有面
        self._report_status("提取面...")
        self._report_progress(10)
        faces = self._extract_faces(shape)

        if not faces:
            self._report_status("未找到有效面")
            return []

        # 2. 检测多面体结构
        self._report_status("检测多面体结构...")
        self._report_progress(20)

        from .polyhedron_detector import PolyhedronDetector
        polyhedron_detector = PolyhedronDetector()
        polyhedra = polyhedron_detector.detect_polyhedra(shape)

        primitives = []
        used_faces = set()

        # 创建多面体几何体
        for poly_data in polyhedra:
            poly_faces = poly_data["faces"]
            vertices = poly_data["vertices"]
            center = poly_data["center"]

            # 根据面数和形状特征确定类型
            if len(poly_faces) == 6 and poly_data["edges_count"] == 12:
                # 可能是长方体/立方体
                params = self._estimate_box_params(poly_faces, [])
                if params:
                    box = Box(
                        faces=poly_faces,
                        center=params.get("center", center),
                        dx=params.get("dx", 10.0),
                        dy=params.get("dy", 10.0),
                        dz=params.get("dz", 10.0),
                        direction=params.get("direction", (0, 0, 1)),
                        fitting_score=0.9
                    )
                    primitives.append(box)
                    used_faces.update(poly_faces)

            elif len(poly_faces) > 3 and len(poly_faces) < 100:  # 限制面数防止过大的多面体
                # 创建通用多面体
                polyhedron = Polyhedron(
                    faces=poly_faces,
                    vertices=vertices,
                    center=center,
                    fitting_score=0.8
                )
                primitives.append(polyhedron)
                used_faces.update(poly_faces)

        # 3. 分类剩余面
        remaining_faces = [f for f in faces if f not in used_faces]

        if remaining_faces:
            self._report_status(f"分类{len(remaining_faces)}个面...")
            self._report_progress(40)
            classifications = [self.classifier.classify_face(face) for face in remaining_faces]

            # 4. 聚类剩余面
            self._report_status("聚类面...")
            self._report_progress(60)
            clusters = self.clusterer.cluster_faces(remaining_faces, classifications)

            # 5. 估计参数
            self._report_status(f"估计{len(clusters)}个几何体的参数...")
            self._report_progress(80)

            for i, (geo_type, cluster_faces, surface, score) in enumerate(clusters):
                self._report_status(f"处理几何体 {i + 1}/{len(clusters)}...")

                # 估计参数
                params = self.parameter_estimator.estimate_parameters(geo_type, cluster_faces, surface)

                # 创建几何体
                primitive = self._create_primitive(geo_type, cluster_faces, params, score)
                if primitive:
                    primitives.append(primitive)

        self._report_status(f"分割完成，得到{len(primitives)}个几何体")
        self._report_progress(100)

        return primitives

    def _extract_faces(self, shape: TopoDS_Shape) -> List[TopoDS_Face]:
        """提取几何体中的所有面"""
        faces = []
        explorer = TopExp_Explorer(shape, TopAbs_FACE)

        while explorer.More():
            # 使用topods.Face代替topods_Face
            face = topods.Face(explorer.Current())
            faces.append(face)
            explorer.Next()

        return faces

    def _create_primitive(self, geo_type: str, faces: List[TopoDS_Face],
                          params: Dict, score: float) -> Optional[GeometricPrimitive]:
        """根据类型和参数创建几何体"""
        try:
            if geo_type == "plane":
                return Plane(
                    faces=faces,
                    normal=params.get("normal", (0, 0, 1)),
                    origin=params.get("origin", (0, 0, 0)),
                    width=params.get("width", 10.0),
                    height=params.get("height", 10.0),
                    shape_type=params.get("shape_type", "rectangle"),  # 添加这一行
                    fitting_score=score
                )

            elif geo_type == "cylinder":
                return Cylinder(
                    faces=faces,
                    axis=params.get("axis", (0, 0, 1)),
                    center=params.get("center", (0, 0, 0)),
                    radius=params.get("radius", 1.0),
                    height=params.get("height", 10.0),
                    fitting_score=score
                )

            elif geo_type == "cone":
                return Cone(
                    faces=faces,
                    axis=params.get("axis", (0, 0, 1)),
                    apex=params.get("apex", (0, 0, 0)),
                    semi_angle=params.get("semi_angle", 0.25),
                    radius=params.get("radius", 5.0),
                    height=params.get("height", 10.0),
                    fitting_score=score
                )

            elif geo_type == "sphere":
                return Sphere(
                    faces=faces,
                    center=params.get("center", (0, 0, 0)),
                    radius=params.get("radius", 1.0),
                    fitting_score=score
                )

            elif geo_type == "torus":
                return Torus(
                    faces=faces,
                    axis=params.get("axis", (0, 0, 1)),
                    center=params.get("center", (0, 0, 0)),
                    major_radius=params.get("major_radius", 2.0),
                    minor_radius=params.get("minor_radius", 0.5),
                    fitting_score=score
                )

            elif geo_type == "box":
                return Box(
                    faces=faces,
                    center=params.get("center", (0, 0, 0)),
                    dx=params.get("dx", 10.0),
                    dy=params.get("dy", 10.0),
                    dz=params.get("dz", 10.0),
                    direction=params.get("direction", (0, 0, 1)),
                    fitting_score=score
                )

            elif geo_type == "prism":
                return Prism(
                    faces=faces,
                    base_center=params.get("base_center", (0, 0, 0)),
                    axis=params.get("axis", (0, 0, 1)),
                    height=params.get("height", 10.0),
                    base_points=params.get("base_points", []),
                    fitting_score=score
                )

            elif geo_type == "pyramid":
                return Pyramid(
                    faces=faces,
                    base_center=params.get("base_center", (0, 0, 0)),
                    apex=params.get("apex", (0, 10, 0)),
                    base_points=params.get("base_points", []),
                    fitting_score=score
                )

            elif geo_type == "polyhedron":
                return Polyhedron(
                    faces=faces,
                    vertices=params.get("vertices", []),
                    center=params.get("center", (0, 0, 0)),
                    fitting_score=score
                )

            elif geo_type == "freeform":
                return FreeFormSurface(
                    faces=faces,
                    control_points=params.get("control_points", []),
                    fitting_score=score
                )

            return None

        except Exception as e:
            print(f"创建几何体失败: {str(e)}")
            return None

    def _estimate_box_params(self, faces, plane_params_list):
        """估计立方体参数"""
        # 简单实现，返回默认参数
        center = (0, 0, 0)

        # 尝试通过面的中心点估计盒子中心
        if faces:
            points = []
            for face in faces:
                props = BRepAdaptor_Surface(face)
                u_mid = (props.FirstUParameter() + props.LastUParameter()) / 2
                v_mid = (props.FirstVParameter() + props.LastVParameter()) / 2
                pnt = props.Value(u_mid, v_mid)
                points.append((pnt.X(), pnt.Y(), pnt.Z()))

            if points:
                # 计算平均中心点
                x_sum = sum(p[0] for p in points)
                y_sum = sum(p[1] for p in points)
                z_sum = sum(p[2] for p in points)
                center = (x_sum / len(points), y_sum / len(points), z_sum / len(points))

        # 默认尺寸
        dx = dy = dz = 10.0

        return {
            "corner": (center[0] - dx / 2, center[1] - dy / 2, center[2] - dz / 2),
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "direction": (0, 0, 1)  # 默认方向
        }