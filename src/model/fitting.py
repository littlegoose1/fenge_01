# src/model/fitting.py
from typing import List, Tuple, Dict, Any, Optional
import math
import random
import numpy as np
from OCC.Core.TopoDS import TopoDS_Face
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomLProp import GeomLProp_SLProps
from OCC.Core.GeomAdaptor import GeomAdaptor_Surface
from OCC.Core.gp import gp_Pnt, gp_Vec, gp_Pln, gp_Cylinder, gp_Cone, gp_Sphere


class RANSACFitter:
    """使用RANSAC算法拟合基本几何体"""

    def __init__(self,
                 min_samples: int = 10,
                 max_iterations: int = 100,
                 tolerance: float = 0.01,
                 min_inlier_ratio: float = 0.6):
        """
        初始化RANSAC拟合器

        参数:
            min_samples: 最小样本数
            max_iterations: 最大迭代次数
            tolerance: 点到模型的距离容差
            min_inlier_ratio: 最小内点比例
        """
        self.min_samples = min_samples
        self.max_iterations = max_iterations
        self.tolerance = tolerance
        self.min_inlier_ratio = min_inlier_ratio

    def fit_plane(self, points: List[Tuple[float, float, float]]) -> Tuple[bool, Dict, float]:
        """
        拟合平面

        参数:
            points: 点列表 [(x, y, z), ...]

        返回:
            (成功标志, 参数, 拟合分数)
        """
        if len(points) < self.min_samples:
            return False, {}, 0.0

        best_score = 0
        best_params = {}

        # RANSAC迭代
        for _ in range(self.max_iterations):
            # 随机选择三个点
            sample_indices = random.sample(range(len(points)), 3)
            p1 = points[sample_indices[0]]
            p2 = points[sample_indices[1]]
            p3 = points[sample_indices[2]]

            # 计算平面参数
            v1 = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
            v2 = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])

            # 计算法向量 (v1 × v2)
            normal = (
                v1[1] * v2[2] - v1[2] * v2[1],
                v1[2] * v2[0] - v1[0] * v2[2],
                v1[0] * v2[1] - v1[1] * v2[0]
            )

            # 标准化法向量
            length = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
            if length < 1e-10:
                continue  # 无效的平面，跳过

            normal = (normal[0] / length, normal[1] / length, normal[2] / length)

            # 计算平面方程: ax + by + cz + d = 0
            a, b, c = normal
            d = -(a * p1[0] + b * p1[1] + c * p1[2])

            # 计算内点数量
            inliers = []
            for i, point in enumerate(points):
                # 计算点到平面的距离
                distance = abs(a * point[0] + b * point[1] + c * point[2] + d)
                if distance <= self.tolerance:
                    inliers.append(i)

            # 计算分数
            score = len(inliers) / len(points)

            # 更新最佳模型
            if score > best_score:
                best_score = score
                best_params = {
                    "normal": normal,
                    "origin": p1,
                    "a": a,
                    "b": b,
                    "c": c,
                    "d": d
                }

                # 如果分数足够好，提前结束
                if score > 0.9:
                    break

        # 判断是否成功拟合
        if best_score >= self.min_inlier_ratio:
            return True, best_params, best_score
        else:
            return False, {}, 0.0

    def fit_cylinder(self, points: List[Tuple[float, float, float]]) -> Tuple[bool, Dict, float]:
        """
        拟合圆柱

        参数:
            points: 点列表 [(x, y, z), ...]

        返回:
            (成功标志, 参数, 拟合分数)
        """
        if len(points) < self.min_samples:
            return False, {}, 0.0

        best_score = 0
        best_params = {}

        # RANSAC迭代
        for _ in range(self.max_iterations):
            # 随机选择点
            sample_indices = random.sample(range(len(points)), min(5, len(points)))
            sample_points = [points[i] for i in sample_indices]

            # 尝试拟合圆柱
            try:
                # 这里简化了圆柱拟合算法，实际应用中需要更复杂的算法
                # 例如使用最小二乘法拟合圆柱轴线和半径

                # 假设轴线方向为Z轴
                axis = (0, 0, 1)

                # 计算轴线平面上的点坐标
                projected_points = [(p[0], p[1]) for p in sample_points]

                # 拟合圆
                x_sum = sum(p[0] for p in projected_points)
                y_sum = sum(p[1] for p in projected_points)
                x_mean = x_sum / len(projected_points)
                y_mean = y_sum / len(projected_points)

                # 计算半径
                radius = sum(math.sqrt((p[0] - x_mean) ** 2 + (p[1] - y_mean) ** 2)
                             for p in projected_points) / len(projected_points)

                # 圆柱中心点
                center = (x_mean, y_mean, 0)

                # 计算内点
                inliers = []
                for i, point in enumerate(points):
                    # 计算点到轴线的距离
                    dx = point[0] - center[0]
                    dy = point[1] - center[1]
                    dist_to_axis = math.sqrt(dx ** 2 + dy ** 2)

                    # 点到圆柱面的距离
                    dist_to_surface = abs(dist_to_axis - radius)

                    if dist_to_surface <= self.tolerance:
                        inliers.append(i)

                # 计算分数
                score = len(inliers) / len(points)

                # 更新最佳模型
                if score > best_score:
                    best_score = score
                    best_params = {
                        "axis": axis,
                        "center": center,
                        "radius": radius
                    }

                    # 如果分数足够好，提前结束
                    if score > 0.9:
                        break

            except Exception as e:
                # 拟合失败，继续尝试
                continue

        # 判断是否成功拟合
        if best_score >= self.min_inlier_ratio:
            return True, best_params, best_score
        else:
            return False, {}, 0.0

    def fit_sphere(self, points: List[Tuple[float, float, float]]) -> Tuple[bool, Dict, float]:
        """
        拟合球体

        参数:
            points: 点列表 [(x, y, z), ...]

        返回:
            (成功标志, 参数, 拟合分数)
        """
        if len(points) < self.min_samples:
            return False, {}, 0.0

        best_score = 0
        best_params = {}

        # RANSAC迭代
        for _ in range(self.max_iterations):
            # 随机选择点
            sample_indices = random.sample(range(len(points)), min(4, len(points)))
            sample_points = [points[i] for i in sample_indices]

            # 尝试拟合球体
            try:
                # 计算质心
                x_sum = sum(p[0] for p in sample_points)
                y_sum = sum(p[1] for p in sample_points)
                z_sum = sum(p[2] for p in sample_points)

                center = (
                    x_sum / len(sample_points),
                    y_sum / len(sample_points),
                    z_sum / len(sample_points)
                )

                # 计算平均半径
                radius = sum(math.sqrt(
                    (p[0] - center[0]) ** 2 +
                    (p[1] - center[1]) ** 2 +
                    (p[2] - center[2]) ** 2
                ) for p in sample_points) / len(sample_points)

                # 计算内点
                inliers = []
                for i, point in enumerate(points):
                    # 计算点到球心的距离
                    dist = math.sqrt(
                        (point[0] - center[0]) ** 2 +
                        (point[1] - center[1]) ** 2 +
                        (point[2] - center[2]) ** 2
                    )

                    # 点到球面的距离
                    dist_to_surface = abs(dist - radius)

                    if dist_to_surface <= self.tolerance:
                        inliers.append(i)

                # 计算分数
                score = len(inliers) / len(points)

                # 更新最佳模型
                if score > best_score:
                    best_score = score
                    best_params = {
                        "center": center,
                        "radius": radius
                    }

                    # 如果分数足够好，提前结束
                    if score > 0.9:
                        break

            except Exception as e:
                # 拟合失败，继续尝试
                continue

        # 判断是否成功拟合
        if best_score >= self.min_inlier_ratio:
            return True, best_params, best_score
        else:
            return False, {}, 0.0

    def fit_cone(self, points: List[Tuple[float, float, float]]) -> Tuple[bool, Dict, float]:
        """
        拟合圆锥

        参数:
            points: 点列表 [(x, y, z), ...]

        返回:
            (成功标志, 参数, 拟合分数)
        """
        if len(points) < self.min_samples:
            return False, {}, 0.0

        best_score = 0
        best_params = {}

        # RANSAC迭代
        for _ in range(self.max_iterations):
            # 随机选择点
            sample_indices = random.sample(range(len(points)), min(5, len(points)))
            sample_points = [points[i] for i in sample_indices]

            # 尝试拟合圆锥 (简化版本)
            try:
                # 假设顶点在原点，轴线沿Z轴正方向
                apex = (0, 0, 0)
                axis = (0, 0, 1)

                # 假设一个半角 (约30度)
                semi_angle = 0.5

                # 计算内点
                inliers = []
                for i, point in enumerate(points):
                    # 计算点到顶点的矢量
                    v = (point[0] - apex[0], point[1] - apex[1], point[2] - apex[2])
                    v_len = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)

                    if v_len < 1e-10:
                        continue  # 点太接近顶点

                    # 计算矢量与轴线的夹角
                    dot = v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2]
                    cos_angle = dot / v_len
                    angle = math.acos(cos_angle)

                    # 点到圆锥面的角度差
                    angle_diff = abs(angle - semi_angle)

                    if angle_diff <= self.tolerance:
                        inliers.append(i)

                # 计算分数
                score = len(inliers) / len(points)

                # 更新最佳模型
                if score > best_score:
                    best_score = score
                    best_params = {
                        "apex": apex,
                        "axis": axis,
                        "semi_angle": semi_angle
                    }

                    # 如果分数足够好，提前结束
                    if score > 0.9:
                        break

            except Exception as e:
                # 拟合失败，继续尝试
                continue

        # 判断是否成功拟合
        if best_score >= self.min_inlier_ratio:
            return True, best_params, best_score
        else:
            return False, {}, 0.0

    def fit_torus(self, points: List[Tuple[float, float, float]]) -> Tuple[bool, Dict, float]:
        """
        拟合圆环

        参数:
            points: 点列表 [(x, y, z), ...]

        返回:
            (成功标志, 参数, 拟合分数)
        """
        if len(points) < self.min_samples:
            return False, {}, 0.0

        # 圆环拟合较为复杂，这里提供一个简化版本
        # 假设圆环的轴线垂直于XY平面
        axis = (0, 0, 1)
        center = (0, 0, 0)

        # 估计主半径和次半径
        # 投影到XY平面，计算到原点的距离分布
        radii = []
        for point in points:
            r = math.sqrt(point[0] ** 2 + point[1] ** 2)
            radii.append(r)

        # 排序半径
        radii.sort()

        # 分簇找出两个主要半径
        # (简化处理，实际应使用聚类算法)
        if len(radii) > 10:
            major_radius = sum(radii[-5:]) / 5  # 较大的作为主半径
            minor_radius = major_radius * 0.2  # 估计次半径为主半径的20%
        else:
            # 数据不足，使用默认值
            major_radius = 5.0
            minor_radius = 1.0

        # 计算内点
        inliers = []
        for i, point in enumerate(points):
            # 计算点到环面的距离
            r = math.sqrt(point[0] ** 2 + point[1] ** 2)
            h = point[2]

            # 到环心的距离
            dist_to_center = math.sqrt((r - major_radius) ** 2 + h ** 2)

            # 到环面的距离
            dist_to_surface = abs(dist_to_center - minor_radius)

            if dist_to_surface <= self.tolerance:
                inliers.append(i)

        # 计算分数
        score = len(inliers) / len(points) if points else 0

        # 判断是否成功拟合
        if score >= self.min_inlier_ratio:
            params = {
                "axis": axis,
                "center": center,
                "major_radius": major_radius,
                "minor_radius": minor_radius
            }
            return True, params, score
        else:
            return False, {}, 0.0

    def sample_points_from_face(self, face: TopoDS_Face, num_samples: int = 100) -> List[Tuple[float, float, float]]:
        """
        从面上采样点

        参数:
            face: OCC面对象
            num_samples: 采样点数

        返回:
            List[Tuple[float, float, float]]: 采样点列表
        """
        try:
            # 获取面的表面几何
            face_surface = BRep_Tool.Surface(face)

            # 使用适配器获取参数范围
            surface_adaptor = BRepAdaptor_Surface(face)
            umin = surface_adaptor.FirstUParameter()
            umax = surface_adaptor.LastUParameter()
            vmin = surface_adaptor.FirstVParameter()
            vmax = surface_adaptor.LastVParameter()

            # 采样点
            points = []
            for _ in range(num_samples):
                # 随机选择u,v参数
                u = random.uniform(umin, umax)
                v = random.uniform(vmin, vmax)

                try:
                    # 计算点坐标
                    props = GeomLProp_SLProps(face_surface, u, v, 1, 0.01)
                    if props.IsNormalDefined():
                        pnt = props.Value()
                        points.append((pnt.X(), pnt.Y(), pnt.Z()))
                except:
                    # 如果特定参数点计算失败，跳过
                    continue

            return points

        except Exception as e:
            print(f"采样点失败: {str(e)}")
            return []

    def fit_face(self, face: TopoDS_Face) -> Tuple[str, Dict, float]:
        """
        拟合面到几何体

        参数:
            face: OCC面对象

        返回:
            Tuple[str, Dict, float]: (几何类型, 参数, 拟合分数)
        """
        # 采样点
        points = self.sample_points_from_face(face, 200)
        if len(points) < self.min_samples:
            return "unknown", {}, 0.0

        # 尝试拟合各种几何体
        # 平面
        plane_success, plane_params, plane_score = self.fit_plane(points)

        # 圆柱
        cylinder_success, cylinder_params, cylinder_score = self.fit_cylinder(points)

        # 球体
        sphere_success, sphere_params, sphere_score = self.fit_sphere(points)

        # 圆锥
        cone_success, cone_params, cone_score = self.fit_cone(points)

        # 圆环
        torus_success, torus_params, torus_score = self.fit_torus(points)

        # 选择最佳拟合
        best_type = "unknown"
        best_params = {}
        best_score = 0.0

        if plane_success and plane_score > best_score:
            best_type = "plane"
            best_params = plane_params
            best_score = plane_score

        if cylinder_success and cylinder_score > best_score:
            best_type = "cylinder"
            best_params = cylinder_params
            best_score = cylinder_score

        if sphere_success and sphere_score > best_score:
            best_type = "sphere"
            best_params = sphere_params
            best_score = sphere_score

        if cone_success and cone_score > best_score:
            best_type = "cone"
            best_params = cone_params
            best_score = cone_score

        if torus_success and torus_score > best_score:
            best_type = "torus"
            best_params = torus_params
            best_score = torus_score

        return best_type, best_params, best_score