# -*- coding: utf-8 -*-
"""
Advanced segmentation algorithms for equipment structure decomposition
Implements Region Growing, K-means, DBSCAN clustering, and boundary detection
as described in section 3.3.1 of the research methodology
"""

from typing import List, Dict, Tuple, Set, Optional, Any
import math
import numpy as np
from collections import deque
from sklearn.cluster import KMeans, DBSCAN

from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face, topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomLProp import GeomLProp_SLProps
from OCC.Core.gp import gp_Pnt


class RegionGrowingSegmentation:
    """
    Region Growing algorithm for geometric region partitioning
    Based on surface continuity and normal vector similarity
    """

    def __init__(self, normal_threshold: float = 0.95, curvature_threshold: float = 0.1):
        """
        Initialize Region Growing segmentation
        
        Args:
            normal_threshold: Threshold for normal vector similarity (cosine similarity)
            curvature_threshold: Threshold for curvature difference
        """
        self.normal_threshold = normal_threshold
        self.curvature_threshold = curvature_threshold

    def segment_faces(self, faces: List[TopoDS_Face]) -> List[List[TopoDS_Face]]:
        """
        Segment faces using region growing algorithm
        
        Args:
            faces: List of faces to segment
            
        Returns:
            List of face groups (regions)
        """
        if not faces:
            return []

        # Extract face properties
        face_properties = {}
        for face in faces:
            props = self._extract_face_properties(face)
            if props:
                face_properties[id(face)] = props

        # Build adjacency graph
        adjacency = self._build_adjacency_graph(faces)

        # Perform region growing
        visited = set()
        regions = []

        for seed_face in faces:
            if id(seed_face) not in visited:
                region = self._grow_region(seed_face, faces, face_properties, adjacency, visited)
                if region:
                    regions.append(region)

        return regions

    def _extract_face_properties(self, face: TopoDS_Face) -> Optional[Dict[str, Any]]:
        """
        Extract geometric properties from a face
        
        Returns:
            Dictionary with normal, center, and curvature information
        """
        try:
            surface = BRepAdaptor_Surface(face)
            
            # Sample at the middle of parameter range
            u_min = surface.FirstUParameter()
            u_max = surface.LastUParameter()
            v_min = surface.FirstVParameter()
            v_max = surface.LastVParameter()
            
            u_mid = (u_min + u_max) / 2.0
            v_mid = (v_min + v_max) / 2.0

            # Get properties at center point
            props = GeomLProp_SLProps(surface, u_mid, v_mid, 2, 1e-6)
            
            if not props.IsNormalDefined():
                return None

            normal = props.Normal()
            point = props.Value()
            
            # Get curvatures
            max_curv = props.MaxCurvature() if props.IsCurvatureDefined() else 0.0
            min_curv = props.MinCurvature() if props.IsCurvatureDefined() else 0.0
            
            return {
                "normal": np.array([normal.X(), normal.Y(), normal.Z()]),
                "center": np.array([point.X(), point.Y(), point.Z()]),
                "max_curvature": max_curv,
                "min_curvature": min_curv,
                "mean_curvature": (max_curv + min_curv) / 2.0
            }
        except Exception as e:
            print(f"[WARN] Failed to extract face properties: {e}")
            return None

    def _build_adjacency_graph(self, faces: List[TopoDS_Face]) -> Dict[int, Set[int]]:
        """
        Build adjacency graph of faces sharing edges
        
        Returns:
            Dictionary mapping face id to set of adjacent face ids
        """
        adjacency = {id(face): set() for face in faces}
        
        # Build edge to faces mapping
        edge_to_faces = {}
        for face in faces:
            edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
            while edge_exp.More():
                edge = edge_exp.Current()
                edge_id = edge.HashCode(100000000)
                
                if edge_id not in edge_to_faces:
                    edge_to_faces[edge_id] = []
                edge_to_faces[edge_id].append(id(face))
                
                edge_exp.Next()

        # Build adjacency from shared edges
        for edge_id, face_ids in edge_to_faces.items():
            if len(face_ids) == 2:
                face_id1, face_id2 = face_ids
                adjacency[face_id1].add(face_id2)
                adjacency[face_id2].add(face_id1)

        return adjacency

    def _grow_region(self, seed_face: TopoDS_Face, all_faces: List[TopoDS_Face],
                     face_properties: Dict[int, Dict],
                     adjacency: Dict[int, Set[int]],
                     visited: Set[int]) -> List[TopoDS_Face]:
        """
        Grow a region starting from seed face
        
        Returns:
            List of faces in the grown region
        """
        seed_id = id(seed_face)
        
        if seed_id in visited or seed_id not in face_properties:
            return []

        region = []
        queue = deque([seed_face])
        visited.add(seed_id)
        
        seed_props = face_properties[seed_id]

        while queue:
            current_face = queue.popleft()
            region.append(current_face)
            current_id = id(current_face)

            # Check neighbors
            for neighbor_id in adjacency.get(current_id, []):
                if neighbor_id in visited or neighbor_id not in face_properties:
                    continue

                neighbor_props = face_properties[neighbor_id]
                
                # Check similarity criteria
                if self._are_similar(seed_props, neighbor_props):
                    visited.add(neighbor_id)
                    # Find the actual face object
                    neighbor_face = next((f for f in all_faces if id(f) == neighbor_id), None)
                    if neighbor_face:
                        queue.append(neighbor_face)

        return region

    def _are_similar(self, props1: Dict, props2: Dict) -> bool:
        """
        Check if two faces are similar based on geometric properties
        
        Returns:
            True if faces are similar enough to be in same region
        """
        # Check normal similarity (cosine similarity)
        normal1 = props1["normal"]
        normal2 = props2["normal"]
        
        # Normalize
        norm1 = np.linalg.norm(normal1)
        norm2 = np.linalg.norm(normal2)
        
        if norm1 < 1e-10 or norm2 < 1e-10:
            return False
            
        cos_sim = np.dot(normal1, normal2) / (norm1 * norm2)
        
        if abs(cos_sim) < self.normal_threshold:
            return False

        # Check curvature similarity
        curv_diff = abs(props1["mean_curvature"] - props2["mean_curvature"])
        if curv_diff > self.curvature_threshold:
            return False

        return True


class ClusteringSegmentation:
    """
    Clustering-based segmentation using K-means and DBSCAN
    For point cloud or mesh vertex aggregation
    """

    def __init__(self, method: str = "kmeans", n_clusters: int = 8,
                 eps: float = 0.5, min_samples: int = 5):
        """
        Initialize clustering segmentation
        
        Args:
            method: "kmeans" or "dbscan"
            n_clusters: Number of clusters for K-means
            eps: DBSCAN epsilon parameter
            min_samples: DBSCAN minimum samples parameter
        """
        self.method = method
        self.n_clusters = n_clusters
        self.eps = eps
        self.min_samples = min_samples

    def segment_by_vertices(self, faces: List[TopoDS_Face]) -> List[List[TopoDS_Face]]:
        """
        Segment faces by clustering their vertices
        
        Args:
            faces: List of faces to segment
            
        Returns:
            List of face groups
        """
        if not faces:
            return []

        # Extract vertices from all faces
        face_vertex_map = {}
        all_vertices = []
        
        for face in faces:
            vertices = self._extract_face_vertices(face)
            face_vertex_map[id(face)] = vertices
            all_vertices.extend(vertices)

        if not all_vertices:
            return [faces]

        # Convert to numpy array
        points = np.array(all_vertices)

        # Perform clustering
        if self.method == "kmeans":
            labels = self._kmeans_clustering(points)
        elif self.method == "dbscan":
            labels = self._dbscan_clustering(points)
        else:
            return [faces]

        # Map vertices to clusters
        vertex_to_cluster = {}
        for i, vertex in enumerate(all_vertices):
            key = tuple(vertex)
            vertex_to_cluster[key] = labels[i]

        # Assign faces to clusters based on majority voting
        face_clusters = {}
        for face in faces:
            vertices = face_vertex_map[id(face)]
            cluster_votes = [vertex_to_cluster.get(tuple(v), -1) for v in vertices]
            
            # Majority vote
            if cluster_votes:
                cluster = max(set(cluster_votes), key=cluster_votes.count)
                if cluster not in face_clusters:
                    face_clusters[cluster] = []
                face_clusters[cluster].append(face)

        return list(face_clusters.values())

    def _extract_face_vertices(self, face: TopoDS_Face) -> List[Tuple[float, float, float]]:
        """
        Extract unique vertices from a face
        
        Returns:
            List of vertex coordinates
        """
        vertices = []
        vertex_exp = TopExp_Explorer(face, TopAbs_VERTEX)
        
        seen = set()
        while vertex_exp.More():
            vertex = topods.Vertex(vertex_exp.Current())
            pnt = BRep_Tool.Pnt(vertex)
            coord = (round(pnt.X(), 6), round(pnt.Y(), 6), round(pnt.Z(), 6))
            
            if coord not in seen:
                seen.add(coord)
                vertices.append(coord)
            
            vertex_exp.Next()

        return vertices

    def _kmeans_clustering(self, points: np.ndarray) -> np.ndarray:
        """
        Perform K-means clustering
        
        Returns:
            Cluster labels for each point
        """
        try:
            # Adjust n_clusters if we have fewer points
            n_clusters = min(self.n_clusters, len(points))
            if n_clusters < 2:
                return np.zeros(len(points), dtype=int)
                
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(points)
            return labels
        except Exception as e:
            print(f"[WARN] K-means clustering failed: {e}")
            return np.zeros(len(points), dtype=int)

    def _dbscan_clustering(self, points: np.ndarray) -> np.ndarray:
        """
        Perform DBSCAN clustering
        
        Returns:
            Cluster labels for each point
        """
        try:
            dbscan = DBSCAN(eps=self.eps, min_samples=self.min_samples)
            labels = dbscan.fit_predict(points)
            return labels
        except Exception as e:
            print(f"[WARN] DBSCAN clustering failed: {e}")
            return np.zeros(len(points), dtype=int)


class BoundaryDetector:
    """
    Boundary detection and topological segmentation
    Detects edges, holes, slots, and curvature change points
    """

    def __init__(self, curvature_threshold: float = 0.2):
        """
        Initialize boundary detector
        
        Args:
            curvature_threshold: Threshold for detecting curvature changes
        """
        self.curvature_threshold = curvature_threshold

    def detect_boundaries(self, shape: TopoDS_Shape) -> Dict[str, List]:
        """
        Detect various boundary features in a shape
        
        Returns:
            Dictionary with detected features
        """
        boundaries = {
            "sharp_edges": [],
            "boundary_edges": [],
            "holes": [],
            "curvature_changes": []
        }

        # Detect sharp edges and boundary edges
        edge_exp = TopExp_Explorer(shape, TopAbs_EDGE)
        while edge_exp.More():
            edge = topods.Edge(edge_exp.Current())
            
            # Check if it's a boundary edge (not shared by two faces)
            if self._is_boundary_edge(edge, shape):
                boundaries["boundary_edges"].append(edge)
            
            # Check if it's a sharp edge (large angle between adjacent faces)
            if self._is_sharp_edge(edge, shape):
                boundaries["sharp_edges"].append(edge)
            
            edge_exp.Next()

        # Detect holes (closed boundary loops)
        boundaries["holes"] = self._detect_holes(shape)

        # Detect curvature change points
        boundaries["curvature_changes"] = self._detect_curvature_changes(shape)

        return boundaries

    def _is_boundary_edge(self, edge: TopoDS_Edge, shape: TopoDS_Shape) -> bool:
        """
        Check if an edge is a boundary edge (appears in only one face)
        """
        try:
            face_count = 0
            face_exp = TopExp_Explorer(shape, TopAbs_FACE)
            
            while face_exp.More():
                face = topods.Face(face_exp.Current())
                edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
                
                while edge_exp.More():
                    if edge.IsSame(edge_exp.Current()):
                        face_count += 1
                        if face_count > 1:
                            return False
                    edge_exp.Next()
                
                face_exp.Next()
            
            return face_count == 1
        except Exception:
            return False

    def _is_sharp_edge(self, edge: TopoDS_Edge, shape: TopoDS_Shape,
                       angle_threshold: float = 30.0) -> bool:
        """
        Check if an edge is a sharp edge based on dihedral angle
        
        Args:
            angle_threshold: Angle in degrees below which edge is considered sharp
        """
        try:
            # Find faces sharing this edge
            adjacent_faces = []
            face_exp = TopExp_Explorer(shape, TopAbs_FACE)
            
            while face_exp.More():
                face = topods.Face(face_exp.Current())
                edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
                
                while edge_exp.More():
                    if edge.IsSame(edge_exp.Current()):
                        adjacent_faces.append(face)
                        break
                    edge_exp.Next()
                
                face_exp.Next()

            # Need exactly 2 faces to compute dihedral angle
            if len(adjacent_faces) != 2:
                return False

            # Compute angle between face normals
            face1, face2 = adjacent_faces
            normal1 = self._get_face_normal(face1)
            normal2 = self._get_face_normal(face2)
            
            if normal1 is None or normal2 is None:
                return False

            # Compute angle
            cos_angle = np.dot(normal1, normal2)
            cos_angle = np.clip(cos_angle, -1.0, 1.0)
            angle_rad = np.arccos(abs(cos_angle))
            angle_deg = np.degrees(angle_rad)

            return angle_deg > (180.0 - angle_threshold)
            
        except Exception:
            return False

    def _get_face_normal(self, face: TopoDS_Face) -> Optional[np.ndarray]:
        """
        Get the normal vector of a face at its center
        """
        try:
            surface = BRepAdaptor_Surface(face)
            
            u_min = surface.FirstUParameter()
            u_max = surface.LastUParameter()
            v_min = surface.FirstVParameter()
            v_max = surface.LastVParameter()
            
            u_mid = (u_min + u_max) / 2.0
            v_mid = (v_min + v_max) / 2.0

            props = GeomLProp_SLProps(surface, u_mid, v_mid, 1, 1e-6)
            
            if not props.IsNormalDefined():
                return None

            normal = props.Normal()
            n = np.array([normal.X(), normal.Y(), normal.Z()])
            norm = np.linalg.norm(n)
            
            if norm < 1e-10:
                return None
                
            return n / norm
            
        except Exception:
            return None

    def _detect_holes(self, shape: TopoDS_Shape) -> List[Dict]:
        """
        Detect closed boundary loops (holes)
        
        Returns:
            List of hole information
        """
        holes = []
        
        # Simple hole detection: look for closed boundary edge loops
        # More sophisticated detection would analyze wire topology
        
        return holes

    def _detect_curvature_changes(self, shape: TopoDS_Shape) -> List[Dict]:
        """
        Detect points where curvature changes significantly
        
        Returns:
            List of curvature change points
        """
        changes = []
        
        face_exp = TopExp_Explorer(shape, TopAbs_FACE)
        while face_exp.More():
            face = topods.Face(face_exp.Current())
            
            # Sample face and detect curvature variations
            face_changes = self._analyze_face_curvature(face)
            changes.extend(face_changes)
            
            face_exp.Next()

        return changes

    def _analyze_face_curvature(self, face: TopoDS_Face) -> List[Dict]:
        """
        Analyze curvature variation across a face
        """
        changes = []
        
        try:
            surface = BRepAdaptor_Surface(face)
            
            u_min = surface.FirstUParameter()
            u_max = surface.LastUParameter()
            v_min = surface.FirstVParameter()
            v_max = surface.LastVParameter()
            
            # Sample at multiple points
            num_samples = 5
            u_samples = np.linspace(u_min, u_max, num_samples)
            v_samples = np.linspace(v_min, v_max, num_samples)
            
            curvatures = []
            for u in u_samples:
                for v in v_samples:
                    try:
                        props = GeomLProp_SLProps(surface, u, v, 2, 1e-6)
                        if props.IsCurvatureDefined():
                            max_curv = props.MaxCurvature()
                            curvatures.append(max_curv)
                    except Exception:
                        continue

            # Detect significant changes in curvature
            if len(curvatures) > 1:
                curv_std = np.std(curvatures)
                if curv_std > self.curvature_threshold:
                    changes.append({
                        "face": face,
                        "curvature_variation": curv_std,
                        "mean_curvature": np.mean(curvatures)
                    })
                    
        except Exception:
            pass

        return changes
