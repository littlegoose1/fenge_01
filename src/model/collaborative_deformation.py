# -*- coding: utf-8 -*-
"""
Collaborative Deformation and Assembly Module
Implements real-time collaborative geometry deformation and constraint-based assembly
as described in section 3.3.2 of the research methodology
"""

from typing import Dict, List, Tuple, Optional, Any, Set
import numpy as np
import math
from dataclasses import dataclass, field


@dataclass
class TopologyRelation:
    """
    Represents topological relationship between two components
    """
    source_id: str
    target_id: str
    relation_type: str  # "adjacent", "connected", "dependent", "nested"
    contact_area: float = 0.0
    shared_edges: int = 0
    distance: float = 0.0
    strength: float = 1.0  # Influence strength (0-1)


@dataclass
class GeometricConstraint:
    """
    Represents a geometric constraint between components
    """
    constraint_id: str
    constraint_type: str  # "position", "angle", "distance", "tangent", "parallel"
    components: List[str]  # Component IDs involved
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    active: bool = True


class AdjacencyMatrix:
    """
    Manages component adjacency and topological relationships
    """

    def __init__(self):
        """Initialize adjacency matrix"""
        self.components: Dict[str, Any] = {}
        self.relations: Dict[str, List[TopologyRelation]] = {}
        self.matrix: np.ndarray = np.array([])
        self.component_indices: Dict[str, int] = {}

    def add_component(self, component_id: str, component_data: Any):
        """
        Add a component to the adjacency system
        
        Args:
            component_id: Unique identifier for the component
            component_data: Component data (primitive or geometry)
        """
        if component_id not in self.components:
            self.components[component_id] = component_data
            self.relations[component_id] = []
            self._rebuild_matrix()

    def add_relation(self, relation: TopologyRelation):
        """
        Add a topological relation between components
        
        Args:
            relation: TopologyRelation instance
        """
        if relation.source_id in self.relations:
            # Check if relation already exists
            existing = [r for r in self.relations[relation.source_id] 
                       if r.target_id == relation.target_id]
            
            if existing:
                # Update existing relation
                idx = self.relations[relation.source_id].index(existing[0])
                self.relations[relation.source_id][idx] = relation
            else:
                # Add new relation
                self.relations[relation.source_id].append(relation)
            
            self._rebuild_matrix()

    def get_neighbors(self, component_id: str, 
                     relation_type: Optional[str] = None) -> List[str]:
        """
        Get neighboring components
        
        Args:
            component_id: Component to query
            relation_type: Optional filter by relation type
            
        Returns:
            List of neighboring component IDs
        """
        if component_id not in self.relations:
            return []
        
        neighbors = []
        for relation in self.relations[component_id]:
            if relation_type is None or relation.relation_type == relation_type:
                neighbors.append(relation.target_id)
        
        return neighbors

    def get_influence_region(self, component_id: str, 
                            max_depth: int = 2) -> Set[str]:
        """
        Get components within influence region using BFS
        
        Args:
            component_id: Starting component
            max_depth: Maximum search depth
            
        Returns:
            Set of component IDs in influence region
        """
        if component_id not in self.components:
            return set()
        
        visited = set()
        queue = [(component_id, 0)]
        
        while queue:
            current_id, depth = queue.pop(0)
            
            if current_id in visited or depth > max_depth:
                continue
            
            visited.add(current_id)
            
            # Add neighbors to queue
            for neighbor_id in self.get_neighbors(current_id):
                if neighbor_id not in visited:
                    queue.append((neighbor_id, depth + 1))
        
        return visited

    def compute_connectivity_strength(self, source_id: str, 
                                     target_id: str) -> float:
        """
        Compute connectivity strength between two components
        
        Returns:
            Strength value (0-1)
        """
        if source_id not in self.relations:
            return 0.0
        
        for relation in self.relations[source_id]:
            if relation.target_id == target_id:
                return relation.strength
        
        return 0.0

    def _rebuild_matrix(self):
        """Rebuild the numerical adjacency matrix"""
        n = len(self.components)
        self.matrix = np.zeros((n, n))
        
        # Build index mapping
        self.component_indices = {cid: i for i, cid in enumerate(self.components.keys())}
        
        # Fill matrix with relation strengths
        for source_id, relations in self.relations.items():
            source_idx = self.component_indices[source_id]
            for relation in relations:
                if relation.target_id in self.component_indices:
                    target_idx = self.component_indices[relation.target_id]
                    self.matrix[source_idx, target_idx] = relation.strength


class CollaborativeDeformationEngine:
    """
    Manages collaborative geometric deformation with constraint propagation
    """

    def __init__(self):
        """Initialize deformation engine"""
        self.adjacency = AdjacencyMatrix()
        self.constraints: Dict[str, GeometricConstraint] = {}
        self.deformation_history: List[Dict[str, Any]] = []

    def register_component(self, component_id: str, component_data: Any,
                          position: Tuple[float, float, float],
                          rotation: Tuple[float, float, float, float] = (1, 0, 0, 0)):
        """
        Register a component for deformation management
        
        Args:
            component_id: Unique component identifier
            component_data: Component geometry data
            position: Initial position (x, y, z)
            rotation: Initial rotation quaternion (w, x, y, z)
        """
        component_info = {
            "data": component_data,
            "position": np.array(position, dtype=float),
            "rotation": np.array(rotation, dtype=float),
            "scale": np.array([1.0, 1.0, 1.0], dtype=float)
        }
        
        self.adjacency.add_component(component_id, component_info)

    def add_constraint(self, constraint: GeometricConstraint):
        """
        Add a geometric constraint
        
        Args:
            constraint: GeometricConstraint instance
        """
        self.constraints[constraint.constraint_id] = constraint

    def apply_transformation(self, component_id: str,
                           translation: Optional[Tuple[float, float, float]] = None,
                           rotation: Optional[Tuple[float, float, float, float]] = None,
                           scale: Optional[Tuple[float, float, float]] = None,
                           propagate: bool = True) -> Dict[str, Any]:
        """
        Apply transformation to a component and propagate to neighbors
        
        Args:
            component_id: Component to transform
            translation: Translation vector (dx, dy, dz)
            rotation: Rotation quaternion (w, x, y, z)
            scale: Scale factors (sx, sy, sz)
            propagate: Whether to propagate to connected components
            
        Returns:
            Dictionary of affected components and their new transforms
        """
        if component_id not in self.adjacency.components:
            return {}
        
        affected = {}
        component = self.adjacency.components[component_id]
        
        # Apply direct transformation
        if translation is not None:
            component["position"] += np.array(translation, dtype=float)
        
        if rotation is not None:
            # Quaternion multiplication
            component["rotation"] = self._quat_multiply(
                component["rotation"], 
                np.array(rotation, dtype=float)
            )
        
        if scale is not None:
            component["scale"] *= np.array(scale, dtype=float)
        
        affected[component_id] = {
            "position": component["position"].tolist(),
            "rotation": component["rotation"].tolist(),
            "scale": component["scale"].tolist()
        }
        
        # Propagate to influence region
        if propagate:
            influence_region = self.adjacency.get_influence_region(component_id, max_depth=2)
            
            for neighbor_id in influence_region:
                if neighbor_id == component_id:
                    continue
                
                # Compute propagated transformation based on connectivity strength
                strength = self.adjacency.compute_connectivity_strength(
                    component_id, neighbor_id
                )
                
                if strength > 0.1:  # Only propagate if significant connection
                    neighbor_transform = self._compute_propagated_transform(
                        component_id, neighbor_id, 
                        translation, rotation, scale, 
                        strength
                    )
                    
                    if neighbor_transform:
                        affected[neighbor_id] = neighbor_transform
        
        # Record in history
        self.deformation_history.append({
            "timestamp": len(self.deformation_history),
            "primary_component": component_id,
            "affected_components": affected
        })
        
        return affected

    def solve_constraints(self, max_iterations: int = 10,
                         tolerance: float = 1e-6) -> Dict[str, Any]:
        """
        Solve all active constraints iteratively
        
        Args:
            max_iterations: Maximum number of iterations
            tolerance: Convergence tolerance
            
        Returns:
            Dictionary of final component transforms
        """
        # Sort constraints by priority
        sorted_constraints = sorted(
            [c for c in self.constraints.values() if c.active],
            key=lambda x: x.priority,
            reverse=True
        )
        
        if not sorted_constraints:
            return {}
        
        converged = False
        iteration = 0
        
        while not converged and iteration < max_iterations:
            max_residual = 0.0
            
            for constraint in sorted_constraints:
                residual = self._apply_constraint(constraint)
                max_residual = max(max_residual, residual)
            
            converged = (max_residual < tolerance)
            iteration += 1
        
        # Collect final transforms
        final_transforms = {}
        for comp_id, comp_data in self.adjacency.components.items():
            final_transforms[comp_id] = {
                "position": comp_data["position"].tolist(),
                "rotation": comp_data["rotation"].tolist(),
                "scale": comp_data["scale"].tolist()
            }
        
        return final_transforms

    def detect_interference(self, component_id1: str, 
                          component_id2: str) -> bool:
        """
        Detect if two components interfere geometrically
        
        Args:
            component_id1: First component ID
            component_id2: Second component ID
            
        Returns:
            True if interference detected
        """
        if (component_id1 not in self.adjacency.components or
            component_id2 not in self.adjacency.components):
            return False
        
        comp1 = self.adjacency.components[component_id1]
        comp2 = self.adjacency.components[component_id2]
        
        # Simple bounding sphere check
        pos1 = comp1["position"]
        pos2 = comp2["position"]
        
        # Estimate bounding radius (simplified)
        radius1 = np.max(comp1["scale"]) * 2.0
        radius2 = np.max(comp2["scale"]) * 2.0
        
        distance = np.linalg.norm(pos2 - pos1)
        
        return distance < (radius1 + radius2)

    def optimize_assembly(self, component_ids: List[str]) -> Dict[str, Any]:
        """
        Optimize assembly configuration to minimize conflicts
        
        Args:
            component_ids: List of component IDs to optimize
            
        Returns:
            Optimized configuration
        """
        # Simple optimization: resolve pairwise interferences
        optimization_report = {
            "interferences_detected": 0,
            "interferences_resolved": 0,
            "adjustments": []
        }
        
        for i, comp_id1 in enumerate(component_ids):
            for comp_id2 in component_ids[i+1:]:
                if self.detect_interference(comp_id1, comp_id2):
                    optimization_report["interferences_detected"] += 1
                    
                    # Attempt to resolve by moving comp_id2
                    if self._resolve_interference(comp_id1, comp_id2):
                        optimization_report["interferences_resolved"] += 1
                        optimization_report["adjustments"].append({
                            "component": comp_id2,
                            "reason": f"interference with {comp_id1}"
                        })
        
        return optimization_report

    def _compute_propagated_transform(self, source_id: str, target_id: str,
                                     translation: Optional[Tuple],
                                     rotation: Optional[Tuple],
                                     scale: Optional[Tuple],
                                     strength: float) -> Optional[Dict[str, Any]]:
        """
        Compute propagated transformation for a connected component
        """
        if target_id not in self.adjacency.components:
            return None
        
        target = self.adjacency.components[target_id]
        
        # Apply dampened transformation
        new_transform = {
            "position": target["position"].copy(),
            "rotation": target["rotation"].copy(),
            "scale": target["scale"].copy()
        }
        
        if translation is not None:
            # Dampen translation by connectivity strength
            dampened_trans = np.array(translation) * strength
            new_transform["position"] = (target["position"] + dampened_trans).tolist()
        
        if rotation is not None:
            # Dampen rotation (simplified - just scale angle)
            dampened_rot = self._dampen_quaternion(
                np.array(rotation), strength
            )
            new_transform["rotation"] = self._quat_multiply(
                target["rotation"], dampened_rot
            ).tolist()
        
        if scale is not None:
            # Dampen scale
            dampened_scale = 1.0 + (np.array(scale) - 1.0) * strength
            new_transform["scale"] = (target["scale"] * dampened_scale).tolist()
        
        # Update component
        target["position"] = np.array(new_transform["position"])
        target["rotation"] = np.array(new_transform["rotation"])
        target["scale"] = np.array(new_transform["scale"])
        
        return new_transform

    def _apply_constraint(self, constraint: GeometricConstraint) -> float:
        """
        Apply a single constraint and return residual
        """
        if len(constraint.components) < 2:
            return 0.0
        
        comp_id1 = constraint.components[0]
        comp_id2 = constraint.components[1]
        
        if (comp_id1 not in self.adjacency.components or
            comp_id2 not in self.adjacency.components):
            return 0.0
        
        comp1 = self.adjacency.components[comp_id1]
        comp2 = self.adjacency.components[comp_id2]
        
        pos1 = comp1["position"]
        pos2 = comp2["position"]
        
        residual = 0.0
        
        if constraint.constraint_type == "distance":
            target_distance = constraint.parameters.get("distance", 0.0)
            current_distance = np.linalg.norm(pos2 - pos1)
            residual = abs(current_distance - target_distance)
            
            if residual > 1e-6:
                # Move comp2 to satisfy distance
                direction = (pos2 - pos1) / (current_distance + 1e-10)
                comp2["position"] = pos1 + direction * target_distance
        
        elif constraint.constraint_type == "position":
            target_pos = np.array(constraint.parameters.get("position", pos2))
            residual = np.linalg.norm(target_pos - pos2)
            
            # Move towards target
            comp2["position"] = target_pos
        
        elif constraint.constraint_type == "parallel":
            # Align orientations (simplified)
            comp2["rotation"] = comp1["rotation"].copy()
            residual = 0.0
        
        return residual

    def _resolve_interference(self, comp_id1: str, comp_id2: str) -> bool:
        """
        Attempt to resolve interference between two components
        """
        try:
            comp1 = self.adjacency.components[comp_id1]
            comp2 = self.adjacency.components[comp_id2]
            
            pos1 = comp1["position"]
            pos2 = comp2["position"]
            
            # Calculate separation vector
            sep_vector = pos2 - pos1
            distance = np.linalg.norm(sep_vector)
            
            if distance < 1e-6:
                # Components at same position, move comp2 arbitrarily
                comp2["position"] += np.array([1.0, 0.0, 0.0])
                return True
            
            # Move comp2 away
            direction = sep_vector / distance
            min_distance = (np.max(comp1["scale"]) + np.max(comp2["scale"])) * 2.5
            comp2["position"] = pos1 + direction * min_distance
            
            return True
        except Exception:
            return False

    @staticmethod
    def _quat_multiply(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
        """
        Multiply two quaternions
        
        Args:
            q1, q2: Quaternions as (w, x, y, z)
            
        Returns:
            Product quaternion
        """
        w1, x1, y1, z1 = q1
        w2, x2, y2, z2 = q2
        
        return np.array([
            w1*w2 - x1*x2 - y1*y2 - z1*z2,
            w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2,
            w1*z2 + x1*y2 - y1*x2 + z1*w2
        ])

    @staticmethod
    def _dampen_quaternion(q: np.ndarray, factor: float) -> np.ndarray:
        """
        Dampen a quaternion rotation by a factor
        
        Args:
            q: Quaternion (w, x, y, z)
            factor: Dampening factor (0-1)
            
        Returns:
            Dampened quaternion
        """
        # Extract angle
        w = q[0]
        angle = 2.0 * math.acos(np.clip(w, -1.0, 1.0))
        
        # Dampen angle
        dampened_angle = angle * factor
        
        # Reconstruct quaternion
        if angle < 1e-10:
            return np.array([1.0, 0.0, 0.0, 0.0])
        
        axis = q[1:] / math.sin(angle / 2.0)
        new_w = math.cos(dampened_angle / 2.0)
        new_xyz = axis * math.sin(dampened_angle / 2.0)
        
        return np.array([new_w, new_xyz[0], new_xyz[1], new_xyz[2]])
