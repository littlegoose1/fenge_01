# src/model/segmentation.py
from typing import Dict, List, Tuple, Set, Optional, Union
from collections import defaultdict
import numpy as np
import time

from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                              GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BezierSurface,
                              GeomAbs_BSplineSurface)
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepTools import breptools

from ..model.geometry import (GeometricPrimitive, Plane, Cylinder,
                              Cone, Sphere, Torus, FreeFormSurface,
                              normalize_vector)


def vector_to_tuple(vec) -> Tuple[float, float, float]:
    """将OCC向量转换为Python元组"""
    return (vec.X(), vec.Y(), vec.Z())


def point_to_tuple(point) -> Tuple[float, float, float]:
    """将OCC点转换为Python元组"""
    return (point.X(), point.Y(), point.Z())


def tuple_magnitude(vector: Tuple[float, float, float]) -> float:
    """计算三维向量的模"""
    return np.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def dot_product(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
    """计算两个向量的点积"""
    return v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]


def vector_angle(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
    """计算两个向量之间的角度(弧度)"""
    v1_norm = normalize_vector(v1)
    v2_norm = normalize_vector(v2)
    dot = dot_product(v1_norm, v2_norm)
    # 处理数值精度问题
    dot = max(min(dot, 1.0), -1.0)
    return np.arccos(dot)


def analyze_face_geometry(face: TopoDS_Face) -> Dict:
    """分析面的几何类型及参数"""
    surface = BRepAdaptor_Surface(face)
    surface_type = surface.GetType()

    # 计算面的边界框以估计大小
    props = GProp_GProps()
    brepgprop.SurfaceProperties(face, props)

    # 使用替代方法获取边界框信息
    try:
        bounding_box = breptools.Bnd_Box()
        breptools.AddOptimizedBoundingBox(face, bounding_box)
        xmin, ymin, zmin, xmax, ymax, zmax = bounding_box.Get()
    except (AttributeError, TypeError):
        # 如果前一种方法失败，使用替代方法
        xmin, ymin, zmin = -1000, -1000, -1000
        xmax, ymax, zmax = 1000, 1000, 1000
        print("警告: 无法获取准确的边界框信息")

    area = props.Mass()

    result = {"area": area}

    if surface_type == GeomAbs_Plane:
        # 获取平面参数
        plane = surface.Plane()
        location = plane.Location()
        normal = plane.Axis().Direction()
        return {
            "type": "plane",
            "location": point_to_tuple(location),
            "normal": vector_to_tuple(normal),
            "area": area,
            "dims": (xmax - xmin, ymax - ymin, zmax - zmin)
        }

    elif surface_type == GeomAbs_Cylinder:
        # 获取圆柱参数
        cylinder = surface.Cylinder()
        radius = cylinder.Radius()
        axis = cylinder.Axis().Direction()
        center = cylinder.Location()
        return {
            "type": "cylinder",
            "radius": radius,
            "axis": vector_to_tuple(axis),
            "center": point_to_tuple(center),
            "area": area,
            "dims": (xmax - xmin, ymax - ymin, zmax - zmin)
        }

    elif surface_type == GeomAbs_Cone:
        # 获取圆锥参数
        cone = surface.Cone()
        semi_angle = cone.SemiAngle()
        axis = cone.Axis().Direction()
        apex = cone.Apex()

        # 计算圆锥底面半径 (近似值)
        height = max(xmax - xmin, ymax - ymin, zmax - zmin)
        radius = height * np.tan(semi_angle)

        return {
            "type": "cone",
            "semi_angle": semi_angle,
            "axis": vector_to_tuple(axis),
            "apex": point_to_tuple(apex),
            "radius": radius,
            "area": area,
            "dims": (xmax - xmin, ymax - ymin, zmax - zmin)
        }

    elif surface_type == GeomAbs_Sphere:
        # 获取球体参数
        sphere = surface.Sphere()
        radius = sphere.Radius()
        center = sphere.Location()
        return {
            "type": "sphere",
            "radius": radius,
            "center": point_to_tuple(center),
            "area": area,
            "dims": (xmax - xmin, ymax - ymin, zmax - zmin)
        }

    elif surface_type == GeomAbs_Torus:
        # 获取圆环参数
        torus = surface.Torus()
        major_radius = torus.MajorRadius()
        minor_radius = torus.MinorRadius()
        axis = torus.Axis().Direction()
        center = torus.Location()
        return {
            "type": "torus",
            "major_radius": major_radius,
            "minor_radius": minor_radius,
            "axis": vector_to_tuple(axis),
            "center": point_to_tuple(center),
            "area": area,
            "dims": (xmax - xmin, ymax - ymin, zmax - zmin)
        }

    elif surface_type in (GeomAbs_BezierSurface, GeomAbs_BSplineSurface):
        return {
            "type": "freeform",
            "subtype": "bezier" if surface_type == GeomAbs_BezierSurface else "bspline",
            "area": area,
            "dims": (xmax - xmin, ymax - ymin, zmax - zmin)
        }

    return {"type": "unknown", "area": area}


def build_face_adjacency_map(shape: TopoDS_Shape) -> Tuple[Dict[int, Set[int]], List[TopoDS_Face]]:
    """
    构建面的邻接关系图
    返回：面索引到相邻面索引集合的映射 和 面列表
    """
    print("构建面邻接关系图...")

    # 使用OpenCASCADE的数据结构存储面-边关系
    face_edge_map = TopTools_IndexedDataMapOfShapeListOfShape()
    topexp.MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, face_edge_map)

    # 存储所有面
    faces = []
    face_explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while face_explorer.More():
        faces.append(face_explorer.Current())
        face_explorer.Next()

    # 构建邻接关系
    adjacency_map = defaultdict(set)

    # 遍历所有边，找到共享边的面对
    edge_explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while edge_explorer.More():
        edge = edge_explorer.Current()

        # 修复：使用替代方法寻找共享边的面
        connected_faces = []
        for i, face in enumerate(faces):
            face_edge_explorer = TopExp_Explorer(face, TopAbs_EDGE)
            while face_edge_explorer.More():
                if edge_explorer.Current().IsSame(face_edge_explorer.Current()):
                    connected_faces.append(i)
                    break
                face_edge_explorer.Next()

        # 建立邻接关系
        for i in range(len(connected_faces)):
            for j in range(i + 1, len(connected_faces)):
                face_i = connected_faces[i]
                face_j = connected_faces[j]
                adjacency_map[face_i].add(face_j)
                adjacency_map[face_j].add(face_i)

        edge_explorer.Next()

    print(f"面邻接关系图构建完成: {len(adjacency_map)}个面")
    return adjacency_map, faces


def face_similarity(geom1: Dict, geom2: Dict, angle_threshold: float = 0.05) -> bool:
    """
    判断两个面的几何特性是否相似
    参数:
        geom1, geom2: 面的几何数据字典
        angle_threshold: 法向量角度差异阈值(弧度)
    返回:
        是否相似
    """
    # 不同类型的面不相似
    if geom1["type"] != geom2["type"]:
        return False

    face_type = geom1["type"]

    if face_type == "plane":
        # 平面: 法向量相似
        angle = vector_angle(geom1["normal"], geom2["normal"])
        return angle < angle_threshold or abs(angle - np.pi) < angle_threshold

    elif face_type == "cylinder":
        # 圆柱: 轴向相似且半径相似
        axis_angle = vector_angle(geom1["axis"], geom2["axis"])
        is_parallel = axis_angle < angle_threshold or abs(axis_angle - np.pi) < angle_threshold
        radius_ratio = abs(geom1["radius"] - geom2["radius"]) / max(geom1["radius"], geom2["radius"])
        return is_parallel and radius_ratio < 0.05  # 半径差异小于5%

    elif face_type == "cone":
        # 圆锥: 轴向相似且锥角相似
        axis_angle = vector_angle(geom1["axis"], geom2["axis"])
        is_parallel = axis_angle < angle_threshold or abs(axis_angle - np.pi) < angle_threshold
        angle_diff = abs(geom1["semi_angle"] - geom2["semi_angle"])
        return is_parallel and angle_diff < 0.05  # 锥角差异小于0.05弧度

    elif face_type == "sphere":
        # 球体: 中心接近且半径相似
        center_dist = np.sqrt(sum((c1 - c2) ** 2 for c1, c2 in zip(geom1["center"], geom2["center"])))
        radius_ratio = abs(geom1["radius"] - geom2["radius"]) / max(geom1["radius"], geom2["radius"])
        return center_dist < 0.01 * geom1["radius"] and radius_ratio < 0.05

    elif face_type == "torus":
        # 圆环: 轴向相似且半径相似
        axis_angle = vector_angle(geom1["axis"], geom2["axis"])
        is_parallel = axis_angle < angle_threshold or abs(axis_angle - np.pi) < angle_threshold
        major_ratio = abs(geom1["major_radius"] - geom2["major_radius"]) / max(geom1["major_radius"],
                                                                               geom2["major_radius"])
        minor_ratio = abs(geom1["minor_radius"] - geom2["minor_radius"]) / max(geom1["minor_radius"],
                                                                               geom2["minor_radius"])
        return is_parallel and major_ratio < 0.05 and minor_ratio < 0.05

    # 自由曲面默认不合并
    return False


def region_growing_segmentation(faces: List[TopoDS_Face], adjacency_map: Dict[int, Set[int]]) -> List[List[int]]:
    """
    基于区域生长的面分割算法
    参数:
        faces: 面列表
        adjacency_map: 面的邻接关系图
    返回:
        分割后的面组(每个组是一个面索引列表)
    """
    print("执行区域生长分割...")
    face_geometries = [analyze_face_geometry(face) for face in faces]

    # 跟踪已处理的面
    processed = set()
    regions = []

    # 按面积从大到小排序，优先从大面开始生长
    face_indices = list(range(len(faces)))
    face_indices.sort(key=lambda i: face_geometries[i]["area"], reverse=True)

    for start_idx in face_indices:
        if start_idx in processed:
            continue

        # 新区域从当前面开始
        region = [start_idx]
        processed.add(start_idx)
        queue = [start_idx]

        # 区域生长
        while queue:
            current = queue.pop(0)
            current_geom = face_geometries[current]

            # 检查所有邻接面
            for neighbor in adjacency_map.get(current, set()):
                if neighbor in processed:
                    continue

                neighbor_geom = face_geometries[neighbor]

                # 如果几何相似，加入当前区域
                if face_similarity(current_geom, neighbor_geom):
                    region.append(neighbor)
                    processed.add(neighbor)
                    queue.append(neighbor)

        regions.append(region)

    print(f"区域生长分割完成: 识别出{len(regions)}个区域")
    return regions


def fit_primitive_to_region(region_indices: List[int], faces: List[TopoDS_Face]) -> Optional[GeometricPrimitive]:
    """
    将基本几何体拟合到区域
    参数:
        region_indices: 区域内的面索引
        faces: 所有面的列表
    返回:
        拟合的几何体对象
    """
    if not region_indices:
        return None

    region_faces = [faces[i] for i in region_indices]

    # 分析区域内第一个面的几何类型
    geom = analyze_face_geometry(region_faces[0])
    face_type = geom["type"]

    # 计算区域总面积
    total_area = sum(analyze_face_geometry(face)["area"] for face in region_faces)

    # 根据面类型创建对应的几何体
    if face_type == "plane":
        normal = geom["normal"]
        origin = geom["location"]
        dims = geom["dims"]
        width = max(dims[0], dims[1], dims[2])
        height = width  # 简化处理，实际应计算正确的高度/宽度
        return Plane(region_faces, normal, origin, width, height)

    elif face_type == "cylinder":
        axis = geom["axis"]
        center = geom["center"]
        radius = geom["radius"]

        # 估算高度
        max_dist = 0
        for face in region_faces:
            face_geom = analyze_face_geometry(face)
            if face_geom["type"] != "cylinder":
                continue

            dims = face_geom["dims"]
            max_dist = max(max_dist, max(dims))

        height = max_dist
        return Cylinder(region_faces, axis, center, radius, height)

    elif face_type == "cone":
        axis = geom["axis"]
        apex = geom["apex"]
        semi_angle = geom["semi_angle"]
        radius = geom["radius"]

        # 估算高度
        max_dist = 0
        for face in region_faces:
            face_geom = analyze_face_geometry(face)
            if face_geom["type"] != "cone":
                continue

            dims = face_geom["dims"]
            max_dist = max(max_dist, max(dims))

        height = max_dist
        return Cone(region_faces, axis, apex, semi_angle, radius, height)

    elif face_type == "sphere":
        center = geom["center"]
        radius = geom["radius"]
        return Sphere(region_faces, center, radius)

    elif face_type == "torus":
        axis = geom["axis"]
        center = geom["center"]
        major_radius = geom["major_radius"]
        minor_radius = geom["minor_radius"]
        return Torus(region_faces, axis, center, major_radius, minor_radius)

    elif face_type == "freeform":
        # 简化处理自由曲面
        control_points = [[geom["dims"]]]  # 简化的控制点表示
        return FreeFormSurface(region_faces, control_points)

    return None


def extract_primitives(shape: TopoDS_Shape) -> List[GeometricPrimitive]:
    """
    从CAD模型中提取基本几何体
    参数:
        shape: OCC形状对象
    返回:
        识别出的基本几何体列表
    """
    print("开始提取基本几何体...")

    # 构建面邻接关系
    adjacency_map, faces = build_face_adjacency_map(shape)

    # 分割模型
    regions = region_growing_segmentation(faces, adjacency_map)

    # 拟合几何体
    primitives = []
    for region in regions:
        primitive = fit_primitive_to_region(region, faces)
        if primitive:
            primitives.append(primitive)

    # 解决重叠问题 (简化处理)
    # 实际应用中需要更复杂的重叠检测和处理算法

    print(f"提取完成: 共识别{len(primitives)}个基本几何体")
    return primitives


def resolve_overlaps(primitives: List[GeometricPrimitive]) -> List[GeometricPrimitive]:
    """
    解决几何体之间的重叠问题(简化版)
    参数:
        primitives: 几何体列表
    返回:
        处理后的几何体列表
    """
    # 这里是一个简化的重叠处理算法
    # 实际应用中需要更复杂的重叠检测和处理

    # 按面积排序(面积大的优先)
    primitives.sort(key=lambda p: sum(analyze_face_geometry(face)["area"] for face in p.faces), reverse=True)

    return primitives


class GeometrySegmentationProcessor:
    """几何分割处理器"""

    def __init__(self):
        self.status_callback = None
        self.progress_callback = None

    def set_status_callback(self, callback):
        """设置状态更新回调"""
        self.status_callback = callback

    def set_progress_callback(self, callback):
        """设置进度更新回调"""
        self.progress_callback = callback

    def update_status(self, message):
        """更新处理状态"""
        if self.status_callback:
            self.status_callback(message)
        else:
            print(message)

    def update_progress(self, value, max_value):
        """更新进度条"""
        if self.progress_callback:
            self.progress_callback(value, max_value)

    def process_shape(self, shape: TopoDS_Shape) -> List[GeometricPrimitive]:
        """处理CAD形状，提取几何体"""
        start_time = time.time()

        self.update_status("开始提取基本几何体...")
        primitives = extract_primitives(shape)

        self.update_status("解决重叠问题...")
        primitives = resolve_overlaps(primitives)

        elapsed_time = time.time() - start_time
        self.update_status(f"处理完成: {len(primitives)}个基本几何体，用时: {elapsed_time:.2f}秒")

        return primitives