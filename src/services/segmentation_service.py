# -*- coding: utf-8 -*-
"""
Segmentation Service
Integrates advanced segmentation algorithms with the main application
"""

from typing import List, Dict, Optional, Any
from OCC.Core.TopoDS import TopoDS_Shape

from src.model.segmentation import GeometrySegmentationProcessor
from src.model.advanced_segmentation import (
    RegionGrowingSegmentation,
    ClusteringSegmentation,
    BoundaryDetector
)
from src.model.geometry import GeometricPrimitive
from src.model.atomic_library import (
    ComponentLibrary,
    create_component_from_primitive
)


class SegmentationService:
    """
    Service for advanced equipment segmentation and component extraction
    """

    def __init__(self, library_path: str = "./component_library"):
        """
        Initialize segmentation service
        
        Args:
            library_path: Path for storing atomic components
        """
        self.processor = GeometrySegmentationProcessor()
        self.region_growing = RegionGrowingSegmentation()
        self.kmeans_clustering = ClusteringSegmentation(method="kmeans", n_clusters=8)
        self.dbscan_clustering = ClusteringSegmentation(method="dbscan", eps=0.5)
        self.boundary_detector = BoundaryDetector()
        self.component_library = ComponentLibrary(storage_path=library_path)

    def segment_equipment(self, shape: TopoDS_Shape,
                         method: str = "default",
                         extract_to_library: bool = True) -> Dict[str, Any]:
        """
        Segment equipment shape using specified method
        
        Args:
            shape: Equipment shape to segment
            method: Segmentation method ("default", "region_growing", "kmeans", "dbscan")
            extract_to_library: Whether to extract components to library
            
        Returns:
            Dictionary with segmentation results
        """
        results = {
            "method": method,
            "primitives": [],
            "components": [],
            "boundaries": {},
            "statistics": {}
        }

        # Extract faces from shape
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE
        from OCC.Core.TopoDS import topods
        
        faces = []
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = topods.Face(explorer.Current())
            faces.append(face)
            explorer.Next()

        results["statistics"]["total_faces"] = len(faces)

        # Perform segmentation based on method
        if method == "default":
            # Use existing segmentation processor
            primitives = self.processor.process_shape(shape)
            results["primitives"] = primitives
            results["statistics"]["primitives_found"] = len(primitives)
            
        elif method == "region_growing":
            # Use region growing segmentation
            face_groups = self.region_growing.segment_faces(faces)
            results["statistics"]["regions_found"] = len(face_groups)
            
            # Create primitives from face groups
            from src.model.fitting import RANSACFitter
            fitter = RANSACFitter()
            
            for i, face_group in enumerate(face_groups):
                # Try to fit geometric primitive to face group
                # This is simplified - in practice would analyze each group
                results["primitives"].append({
                    "type": "region",
                    "face_count": len(face_group),
                    "group_id": i
                })
            
        elif method == "kmeans":
            # Use K-means clustering
            face_groups = self.kmeans_clustering.segment_by_vertices(faces)
            results["statistics"]["clusters_found"] = len(face_groups)
            
            for i, face_group in enumerate(face_groups):
                results["primitives"].append({
                    "type": "cluster",
                    "face_count": len(face_group),
                    "cluster_id": i
                })
            
        elif method == "dbscan":
            # Use DBSCAN clustering
            face_groups = self.dbscan_clustering.segment_by_vertices(faces)
            results["statistics"]["clusters_found"] = len(face_groups)
            
            for i, face_group in enumerate(face_groups):
                results["primitives"].append({
                    "type": "cluster",
                    "face_count": len(face_group),
                    "cluster_id": i
                })

        # Detect boundaries
        boundaries = self.boundary_detector.detect_boundaries(shape)
        results["boundaries"] = {
            "sharp_edges": len(boundaries["sharp_edges"]),
            "boundary_edges": len(boundaries["boundary_edges"]),
            "holes": len(boundaries["holes"]),
            "curvature_changes": len(boundaries["curvature_changes"])
        }

        # Extract components to library if requested
        if extract_to_library and method == "default":
            for primitive in results["primitives"]:
                if isinstance(primitive, GeometricPrimitive):
                    component = create_component_from_primitive(
                        primitive, 
                        self.component_library
                    )
                    if component:
                        results["components"].append(component.id)

        return results

    def search_components(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search for components in the library
        
        Args:
            query: Search query parameters
            
        Returns:
            List of matching components as dictionaries
        """
        components = self.component_library.search(query)
        return [comp.to_dict() for comp in components]

    def export_library(self, format: str = "json") -> str:
        """
        Export component library
        
        Args:
            format: Export format ("json" or "xml")
            
        Returns:
            Exported data as string
        """
        return self.component_library.export_library(format=format)

    def get_component_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the component library
        
        Returns:
            Statistics dictionary
        """
        all_components = self.component_library.list_components()
        
        type_counts = {}
        category_counts = {}
        
        for comp in all_components:
            type_counts[comp.type] = type_counts.get(comp.type, 0) + 1
            category_counts[comp.category] = category_counts.get(comp.category, 0) + 1

        return {
            "total_components": len(all_components),
            "by_type": type_counts,
            "by_category": category_counts,
            "storage_path": self.component_library.storage_path
        }
