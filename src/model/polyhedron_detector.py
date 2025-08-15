# src/model/polyhedron_detector.py
from typing import List, Dict, Tuple, Set, Optional
import math
import numpy as np
from collections import defaultdict

from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, TopoDS_Edge, TopoDS_Vertex
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Plane
from OCC.Core.gp import gp_Pnt
from OCC.Core.TopoDS import topods, TopoDS_Iterator


class PolyhedronDetector:
    """多面体检测器 - 检测和分析多面体结构"""

    def __init__(self, tolerance: float = 0.001):
        self.tolerance = tolerance

    def detect_polyhedra(self, shape: TopoDS_Shape) -> List[Dict]:
        """
        检测形状中的多面体

        参数:
            shape: 要分析的形状

        返回:
            List[Dict]: 检测到的多面体列表，每个字典包含多面体参数
        """
        # 提取所有平面面
        plane_faces = self._extract_plane_faces(shape)
        if not plane_faces:
            return []

        # 构建面-边连接关系
        face_edge_map = self._build_face_edge_map(plane_faces)

        # 构建连接图
        connectivity_graph = self._build_connectivity_graph(face_edge_map)

        # 提取连通分量作为多面体候选
        polyhedron_candidates = self._extract_connected_components(connectivity_graph)

        # 分析每个候选多面体
        polyhedra = []
        for candidate_faces in polyhedron_candidates:
            # 提取候选多面体的所有边和顶点
            edges, vertices = self._extract_edges_and_vertices(candidate_faces, face_edge_map)

            # 如果是有效的多面体
            if self._is_valid_polyhedron(len(candidate_faces), len(edges), len(vertices)):
                polyhedron = {
                    "faces": candidate_faces,
                    "edges_count": len(edges),
                    "vertices": [self._get_vertex_coords(v) for v in vertices],
                    "center": self._estimate_center(vertices)
                }
                polyhedra.append(polyhedron)

        return polyhedra

    def _extract_plane_faces(self, shape: TopoDS_Shape) -> List[TopoDS_Face]:
        """提取所有平面面"""
        plane_faces = []

        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = topods.Face(explorer.Current())

            # 检查是否是平面
            surface = BRepAdaptor_Surface(face)
            if surface.GetType() == GeomAbs_Plane:
                plane_faces.append(face)

            explorer.Next()

        return plane_faces

    def _build_face_edge_map(self, faces: List[TopoDS_Face]) -> Dict[TopoDS_Face, List[TopoDS_Edge]]:
        """构建面-边映射关系"""
        face_edge_map = {}

        for face in faces:
            edges = []
            explorer = TopExp_Explorer(face, TopAbs_EDGE)
            while explorer.More():
                edge = topods.Edge(explorer.Current())
                edges.append(edge)
                explorer.Next()

            face_edge_map[face] = edges

        return face_edge_map

    def _build_connectivity_graph(self, face_edge_map: Dict[TopoDS_Face, List[TopoDS_Edge]]) -> Dict[
        TopoDS_Face, List[TopoDS_Face]]:
        """构建面之间的连接图"""
        # 创建边到面的映射
        edge_to_faces = defaultdict(list)
        for face, edges in face_edge_map.items():
            for edge in edges:
                edge_to_faces[edge].append(face)

        # 创建面到面的连接图
        connectivity_graph = defaultdict(list)
        for edge, faces in edge_to_faces.items():
            if len(faces) == 2:  # 如果一条边连接两个面
                face1, face2 = faces
                connectivity_graph[face1].append(face2)
                connectivity_graph[face2].append(face1)

        return connectivity_graph

    def _extract_connected_components(self, graph: Dict[TopoDS_Face, List[TopoDS_Face]]) -> List[List[TopoDS_Face]]:
        """提取连接图中的连通分量"""
        visited = set()
        components = []

        def dfs(node, component):
            visited.add(node)
            component.append(node)
            for neighbor in graph[node]:
                if neighbor not in visited:
                    dfs(neighbor, component)

        for node in graph:
            if node not in visited:
                component = []
                dfs(node, component)
                components.append(component)

        return components

    def _extract_edges_and_vertices(self,
                                    faces: List[TopoDS_Face],
                                    face_edge_map: Dict[TopoDS_Face, List[TopoDS_Edge]]) -> Tuple[
        Set[TopoDS_Edge], Set[TopoDS_Vertex]]:
        """提取多面体的边和顶点"""
        edges = set()
        vertices = set()

        # 收集所有边
        for face in faces:
            for edge in face_edge_map[face]:
                edges.add(edge)

                # 提取边的顶点
                v1, v2 = self._get_edge_vertices(edge)
                vertices.add(v1)
                vertices.add(v2)

        return edges, vertices

    def _get_edge_vertices(self, edge: TopoDS_Edge) -> Tuple[TopoDS_Vertex, TopoDS_Vertex]:
        """获取边的两个顶点"""
        vertices = []
        explorer = TopExp_Explorer(edge, TopAbs_VERTEX)
        while explorer.More():
            vertex = topods.Vertex(explorer.Current())
            vertices.append(vertex)
            explorer.Next()

        if len(vertices) != 2:
            # 异常情况
            raise ValueError(f"边包含 {len(vertices)} 个顶点，应为2个")

        return vertices[0], vertices[1]

    def _get_vertex_coords(self, vertex: TopoDS_Vertex) -> Tuple[float, float, float]:
        """获取顶点的坐标"""
        point = BRep_Tool.Pnt(vertex)
        return (point.X(), point.Y(), point.Z())

    def _estimate_center(self, vertices: Set[TopoDS_Vertex]) -> Tuple[float, float, float]:
        """估计多面体的中心"""
        if not vertices:
            return (0, 0, 0)

        coords = [self._get_vertex_coords(v) for v in vertices]
        x_sum = sum(c[0] for c in coords)
        y_sum = sum(c[1] for c in coords)
        z_sum = sum(c[2] for c in coords)

        n = len(coords)
        return (x_sum / n, y_sum / n, z_sum / n)

    def _is_valid_polyhedron(self, faces_count: int, edges_count: int, vertices_count: int) -> bool:
        """检查是否是有效的多面体 (欧拉公式: V - E + F = 2)"""
        # 容许一定的误差
        euler_characteristic = vertices_count - edges_count + faces_count
        return abs(euler_characteristic - 2) <= 1  # 允许一定误差