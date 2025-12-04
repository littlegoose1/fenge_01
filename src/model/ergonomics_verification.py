# -*- coding: utf-8 -*-
"""
Human-Machine Ergonomics Verification Module
Implements 3D human visualization and rapid ergonomics verification
as described in section 3.3.3 of the research methodology
"""

from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import math
from dataclasses import dataclass, field
from enum import Enum


class BodyPart(Enum):
    """Human body part enumeration"""
    HEAD = "head"
    NECK = "neck"
    CHEST = "chest"
    ABDOMEN = "abdomen"
    PELVIS = "pelvis"
    LEFT_SHOULDER = "left_shoulder"
    RIGHT_SHOULDER = "right_shoulder"
    LEFT_UPPER_ARM = "left_upper_arm"
    RIGHT_UPPER_ARM = "right_upper_arm"
    LEFT_FOREARM = "left_forearm"
    RIGHT_FOREARM = "right_forearm"
    LEFT_HAND = "left_hand"
    RIGHT_HAND = "right_hand"
    LEFT_THIGH = "left_thigh"
    RIGHT_THIGH = "right_thigh"
    LEFT_SHIN = "left_shin"
    RIGHT_SHIN = "right_shin"
    LEFT_FOOT = "left_foot"
    RIGHT_FOOT = "right_foot"


class Posture(Enum):
    """Human posture enumeration"""
    STANDING = "standing"
    WALKING = "walking"
    RUNNING = "running"
    CROUCHING = "crouching"
    PRONE = "prone"  # 匍匐
    SITTING = "sitting"
    KNEELING = "kneeling"


@dataclass
class Joint:
    """Represents a human body joint"""
    name: str
    position: np.ndarray  # (x, y, z)
    rotation: np.ndarray  # Quaternion (w, x, y, z)
    limits: Dict[str, Tuple[float, float]] = field(default_factory=dict)  # angle limits
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)


@dataclass
class Equipment:
    """Represents a piece of equipment worn by human"""
    equipment_id: str
    name: str
    weight: float  # kg
    position: np.ndarray  # relative to attachment point
    attachment_point: str  # body part name
    dimensions: Tuple[float, float, float]  # (width, height, depth) in meters
    contact_area: float = 0.0  # m²
    center_of_mass: Tuple[float, float, float] = (0, 0, 0)


@dataclass
class LoadDistribution:
    """Represents load distribution on body part"""
    body_part: str
    force: float  # Newtons
    pressure: float  # N/m²
    duration: float = 0.0  # seconds
    accumulated_stress: float = 0.0


class HumanModel:
    """
    3D parametric human body model with joint kinematics
    """

    def __init__(self, height: float = 1.75, weight: float = 70.0):
        """
        Initialize human model
        
        Args:
            height: Human height in meters
            weight: Human weight in kg
        """
        self.height = height
        self.weight = weight
        self.joints: Dict[str, Joint] = {}
        self.equipment_items: List[Equipment] = []
        self.current_posture = Posture.STANDING
        
        self._initialize_skeleton()

    def _initialize_skeleton(self):
        """Initialize joint hierarchy and positions"""
        # Proportions based on standard anthropometry
        head_height = self.height * 0.13
        torso_height = self.height * 0.30
        upper_arm_length = self.height * 0.19
        forearm_length = self.height * 0.15
        thigh_length = self.height * 0.25
        shin_length = self.height * 0.25
        
        # Create joints (simplified skeleton)
        self.joints = {
            "pelvis": Joint("pelvis", np.array([0.0, 0.0, torso_height * 0.3]), 
                          np.array([1.0, 0.0, 0.0, 0.0])),
            "chest": Joint("chest", np.array([0.0, 0.0, torso_height]), 
                         np.array([1.0, 0.0, 0.0, 0.0]), parent="pelvis"),
            "neck": Joint("neck", np.array([0.0, 0.0, torso_height + 0.1]), 
                        np.array([1.0, 0.0, 0.0, 0.0]), parent="chest"),
            "head": Joint("head", np.array([0.0, 0.0, torso_height + 0.1 + head_height/2]), 
                        np.array([1.0, 0.0, 0.0, 0.0]), parent="neck"),
            
            # Arms
            "left_shoulder": Joint("left_shoulder", 
                                  np.array([-0.2, 0.0, torso_height]), 
                                  np.array([1.0, 0.0, 0.0, 0.0]), parent="chest"),
            "right_shoulder": Joint("right_shoulder", 
                                   np.array([0.2, 0.0, torso_height]), 
                                   np.array([1.0, 0.0, 0.0, 0.0]), parent="chest"),
            
            # Legs
            "left_hip": Joint("left_hip", 
                            np.array([-0.1, 0.0, torso_height * 0.3]), 
                            np.array([1.0, 0.0, 0.0, 0.0]), parent="pelvis"),
            "right_hip": Joint("right_hip", 
                             np.array([0.1, 0.0, torso_height * 0.3]), 
                             np.array([1.0, 0.0, 0.0, 0.0]), parent="pelvis"),
        }
        
        # Set joint limits (simplified)
        for joint in self.joints.values():
            joint.limits = {
                "pitch": (-90, 90),  # Forward/backward
                "yaw": (-90, 90),    # Left/right
                "roll": (-45, 45)    # Rotation
            }

    def set_posture(self, posture: Posture):
        """
        Set human to a specific posture
        
        Args:
            posture: Target posture
        """
        self.current_posture = posture
        
        # Apply predefined joint angles for each posture
        if posture == Posture.STANDING:
            self._apply_standing_posture()
        elif posture == Posture.CROUCHING:
            self._apply_crouching_posture()
        elif posture == Posture.PRONE:
            self._apply_prone_posture()
        elif posture == Posture.WALKING:
            self._apply_walking_posture()

    def _apply_standing_posture(self):
        """Apply standing posture joint angles"""
        # Reset to neutral standing position
        for joint in self.joints.values():
            joint.rotation = np.array([1.0, 0.0, 0.0, 0.0])

    def _apply_crouching_posture(self):
        """Apply crouching posture joint angles"""
        # Bend knees and hips
        # Simplified: just adjust key joint rotations
        pass

    def _apply_prone_posture(self):
        """Apply prone (lying down) posture"""
        # Rotate entire body to horizontal
        pass

    def _apply_walking_posture(self, phase: float = 0.0):
        """Apply walking posture with phase parameter"""
        # Animate leg swing based on phase
        pass

    def attach_equipment(self, equipment: Equipment):
        """
        Attach equipment to the human model
        
        Args:
            equipment: Equipment instance to attach
        """
        self.equipment_items.append(equipment)

    def detach_equipment(self, equipment_id: str) -> bool:
        """
        Remove equipment from human
        
        Args:
            equipment_id: ID of equipment to remove
            
        Returns:
            True if removed successfully
        """
        initial_count = len(self.equipment_items)
        self.equipment_items = [e for e in self.equipment_items 
                               if e.equipment_id != equipment_id]
        return len(self.equipment_items) < initial_count

    def get_joint_position_world(self, joint_name: str) -> Optional[np.ndarray]:
        """
        Get world position of a joint
        
        Args:
            joint_name: Name of joint
            
        Returns:
            World position or None if not found
        """
        if joint_name not in self.joints:
            return None
        
        joint = self.joints[joint_name]
        
        # If joint has parent, compute world position recursively
        if joint.parent:
            parent_pos = self.get_joint_position_world(joint.parent)
            if parent_pos is not None:
                # Simplified: just add positions (proper implementation would apply rotations)
                return parent_pos + joint.position
        
        return joint.position.copy()

    def compute_total_equipment_weight(self) -> float:
        """
        Compute total weight of all equipped items
        
        Returns:
            Total weight in kg
        """
        return sum(e.weight for e in self.equipment_items)

    def get_center_of_mass(self) -> np.ndarray:
        """
        Compute center of mass including equipment
        
        Returns:
            Center of mass position (x, y, z)
        """
        total_mass = self.weight
        weighted_sum = np.array([0.0, 0.0, self.height * 0.55])  # Approximate body COM
        weighted_sum *= self.weight
        
        for equipment in self.equipment_items:
            # Get attachment point position
            attachment_pos = self.get_joint_position_world(equipment.attachment_point)
            if attachment_pos is not None:
                equipment_pos = attachment_pos + equipment.position
                weighted_sum += equipment_pos * equipment.weight
                total_mass += equipment.weight
        
        if total_mass > 0:
            return weighted_sum / total_mass
        return weighted_sum


class LoadAnalyzer:
    """
    Analyzes force distribution and ergonomic loads on human body
    """

    def __init__(self):
        """Initialize load analyzer"""
        self.load_history: List[Dict[str, LoadDistribution]] = []
        self.gravity = 9.81  # m/s²

    def compute_load_distribution(self, human: HumanModel) -> Dict[str, LoadDistribution]:
        """
        Compute load distribution across body parts
        
        Args:
            human: HumanModel instance
            
        Returns:
            Dictionary mapping body part to LoadDistribution
        """
        distributions = {}
        
        # Analyze each equipped item
        for equipment in human.equipment_items:
            body_part = equipment.attachment_point
            
            # Compute force (weight * gravity)
            force = equipment.weight * self.gravity
            
            # Compute pressure (force / contact area)
            pressure = force / max(equipment.contact_area, 0.001)
            
            if body_part not in distributions:
                distributions[body_part] = LoadDistribution(
                    body_part=body_part,
                    force=0.0,
                    pressure=0.0
                )
            
            # Accumulate loads
            distributions[body_part].force += force
            distributions[body_part].pressure += pressure
        
        # Record in history
        self.load_history.append(distributions)
        
        return distributions

    def compute_peak_loads(self) -> Dict[str, float]:
        """
        Compute peak loads for each body part from history
        
        Returns:
            Dictionary mapping body part to peak force
        """
        peak_loads = {}
        
        for snapshot in self.load_history:
            for body_part, distribution in snapshot.items():
                if body_part not in peak_loads:
                    peak_loads[body_part] = 0.0
                peak_loads[body_part] = max(peak_loads[body_part], distribution.force)
        
        return peak_loads

    def estimate_fatigue(self, load_distribution: Dict[str, LoadDistribution],
                        duration_minutes: float) -> Dict[str, float]:
        """
        Estimate fatigue accumulation for each body part
        
        Args:
            load_distribution: Current load distribution
            duration_minutes: Duration of load application
            
        Returns:
            Dictionary mapping body part to fatigue score (0-100)
        """
        fatigue_scores = {}
        
        # Fatigue model: simplified linear accumulation
        # Real model would use biomechanical fatigue curves
        
        for body_part, load in load_distribution.items():
            # Normalize pressure (assume 10 kPa is moderate load)
            normalized_pressure = load.pressure / 10000.0
            
            # Fatigue increases with pressure and duration
            # Using simplified power law
            fatigue = min(100.0, normalized_pressure * duration_minutes * 2.0)
            
            fatigue_scores[body_part] = fatigue
        
        return fatigue_scores

    def generate_comfort_report(self, human: HumanModel,
                               duration_minutes: float = 60) -> Dict[str, Any]:
        """
        Generate comprehensive comfort and load report
        
        Args:
            human: HumanModel instance
            duration_minutes: Analysis duration
            
        Returns:
            Comprehensive report dictionary
        """
        load_dist = self.compute_load_distribution(human)
        fatigue = self.estimate_fatigue(load_dist, duration_minutes)
        peak_loads = self.compute_peak_loads()
        
        # Compute overall comfort score (0-100, higher is better)
        total_force = sum(ld.force for ld in load_dist.values())
        max_pressure = max([ld.pressure for ld in load_dist.values()] + [0])
        avg_fatigue = sum(fatigue.values()) / max(len(fatigue), 1)
        
        comfort_score = max(0, 100 - avg_fatigue)
        
        report = {
            "comfort_score": comfort_score,
            "total_equipment_weight": human.compute_total_equipment_weight(),
            "total_force": total_force,
            "max_pressure": max_pressure,
            "load_distribution": {k: v.__dict__ for k, v in load_dist.items()},
            "fatigue_scores": fatigue,
            "peak_loads": peak_loads,
            "duration_minutes": duration_minutes,
            "recommendations": []
        }
        
        # Generate recommendations
        if max_pressure > 50000:  # 50 kPa
            report["recommendations"].append(
                "High pressure detected. Consider redistributing equipment weight."
            )
        
        if avg_fatigue > 60:
            report["recommendations"].append(
                "High fatigue predicted. Consider reducing equipment weight or duration."
            )
        
        if total_force > human.weight * self.gravity * 0.3:
            report["recommendations"].append(
                "Equipment weight exceeds 30% of body weight. Consider weight reduction."
            )
        
        return report


class InterferenceDetector:
    """
    Detects interference between equipment and human body or between equipment items
    """

    def __init__(self, tolerance: float = 0.01):
        """
        Initialize interference detector
        
        Args:
            tolerance: Minimum clearance distance in meters
        """
        self.tolerance = tolerance
        self.detected_interferences: List[Dict[str, Any]] = []

    def check_equipment_body_interference(self, 
                                         equipment: Equipment,
                                         human: HumanModel) -> List[Dict[str, Any]]:
        """
        Check if equipment interferes with body parts during motion
        
        Args:
            equipment: Equipment to check
            human: Human model
            
        Returns:
            List of detected interferences
        """
        interferences = []
        
        # Get equipment bounding box position
        attachment_pos = human.get_joint_position_world(equipment.attachment_point)
        if attachment_pos is None:
            return interferences
        
        equipment_pos = attachment_pos + equipment.position
        
        # Check against nearby body parts
        for joint_name, joint in human.joints.items():
            if joint_name == equipment.attachment_point:
                continue  # Skip attachment point
            
            joint_pos = human.get_joint_position_world(joint_name)
            if joint_pos is None:
                continue
            
            # Simple sphere-box collision check
            distance = np.linalg.norm(equipment_pos - joint_pos)
            equipment_radius = max(equipment.dimensions) / 2.0
            
            if distance < equipment_radius + self.tolerance:
                interferences.append({
                    "type": "equipment_body",
                    "equipment_id": equipment.equipment_id,
                    "body_part": joint_name,
                    "distance": distance,
                    "severity": "high" if distance < 0 else "medium"
                })
        
        return interferences

    def check_equipment_equipment_interference(self,
                                              equipment_list: List[Equipment],
                                              human: HumanModel) -> List[Dict[str, Any]]:
        """
        Check for interference between multiple equipment items
        
        Args:
            equipment_list: List of equipment to check
            human: Human model
            
        Returns:
            List of detected interferences
        """
        interferences = []
        
        # Check all pairs
        for i, equip1 in enumerate(equipment_list):
            pos1 = self._get_equipment_world_position(equip1, human)
            if pos1 is None:
                continue
            
            for equip2 in equipment_list[i+1:]:
                pos2 = self._get_equipment_world_position(equip2, human)
                if pos2 is None:
                    continue
                
                # Compute distance between equipment bounding volumes
                distance = np.linalg.norm(pos2 - pos1)
                min_distance = (max(equip1.dimensions) + max(equip2.dimensions)) / 2.0
                
                if distance < min_distance + self.tolerance:
                    interferences.append({
                        "type": "equipment_equipment",
                        "equipment1_id": equip1.equipment_id,
                        "equipment2_id": equip2.equipment_id,
                        "distance": distance,
                        "severity": "high" if distance < min_distance else "medium"
                    })
        
        return interferences

    def _get_equipment_world_position(self, equipment: Equipment,
                                     human: HumanModel) -> Optional[np.ndarray]:
        """Get equipment position in world coordinates"""
        attachment_pos = human.get_joint_position_world(equipment.attachment_point)
        if attachment_pos is None:
            return None
        return attachment_pos + equipment.position

    def visualize_interferences(self, interferences: List[Dict[str, Any]]) -> str:
        """
        Generate text visualization of interferences
        
        Args:
            interferences: List of interference records
            
        Returns:
            Text report
        """
        if not interferences:
            return "No interferences detected."
        
        report = f"Detected {len(interferences)} interference(s):\n\n"
        
        for i, interference in enumerate(interferences, 1):
            report += f"{i}. Type: {interference['type']}\n"
            report += f"   Severity: {interference['severity']}\n"
            report += f"   Distance: {interference['distance']:.3f}m\n"
            
            if interference['type'] == 'equipment_body':
                report += f"   Equipment: {interference['equipment_id']}\n"
                report += f"   Body Part: {interference['body_part']}\n"
            else:
                report += f"   Equipment 1: {interference['equipment1_id']}\n"
                report += f"   Equipment 2: {interference['equipment2_id']}\n"
            
            report += "\n"
        
        return report


class MotionSimulator:
    """
    Simulates human motion with equipment for dynamic analysis
    """

    def __init__(self):
        """Initialize motion simulator"""
        self.time_step = 0.01  # seconds
        self.simulation_time = 0.0

    def simulate_motion_sequence(self, human: HumanModel,
                                postures: List[Tuple[Posture, float]]) -> Dict[str, Any]:
        """
        Simulate a sequence of postures over time
        
        Args:
            human: HumanModel instance
            postures: List of (Posture, duration_seconds) tuples
            
        Returns:
            Simulation results including load history
        """
        analyzer = LoadAnalyzer()
        detector = InterferenceDetector()
        
        results = {
            "total_duration": 0.0,
            "posture_sequence": [],
            "load_snapshots": [],
            "interference_events": []
        }
        
        for posture, duration in postures:
            human.set_posture(posture)
            
            # Analyze loads at this posture
            load_dist = analyzer.compute_load_distribution(human)
            
            # Check interferences
            interferences = []
            for equipment in human.equipment_items:
                interferences.extend(
                    detector.check_equipment_body_interference(equipment, human)
                )
            
            if len(human.equipment_items) > 1:
                interferences.extend(
                    detector.check_equipment_equipment_interference(
                        human.equipment_items, human
                    )
                )
            
            # Record results
            results["posture_sequence"].append({
                "posture": posture.value,
                "duration": duration,
                "time_start": results["total_duration"],
                "time_end": results["total_duration"] + duration
            })
            
            results["load_snapshots"].append({
                "time": results["total_duration"],
                "posture": posture.value,
                "loads": {k: v.__dict__ for k, v in load_dist.items()}
            })
            
            if interferences:
                results["interference_events"].append({
                    "time": results["total_duration"],
                    "posture": posture.value,
                    "interferences": interferences
                })
            
            results["total_duration"] += duration
        
        # Generate summary
        results["summary"] = {
            "total_interferences": sum(
                len(event["interferences"]) 
                for event in results["interference_events"]
            ),
            "max_load": max([
                max([ld["force"] for ld in snapshot["loads"].values()] + [0])
                for snapshot in results["load_snapshots"]
            ] + [0])
        }
        
        return results
