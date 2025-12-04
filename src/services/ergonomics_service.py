# -*- coding: utf-8 -*-
"""
Ergonomics Service
Integrates human-machine ergonomics verification with the main application
"""

from typing import List, Dict, Optional, Any, Tuple
import json

from src.model.ergonomics_verification import (
    HumanModel,
    Equipment,
    LoadAnalyzer,
    InterferenceDetector,
    MotionSimulator,
    Posture,
    BodyPart
)
import numpy as np


class ErgonomicsService:
    """
    Service for equipment ergonomics analysis and verification
    """

    def __init__(self):
        """Initialize ergonomics service"""
        self.human_models: Dict[str, HumanModel] = {}
        self.load_analyzer = LoadAnalyzer()
        self.interference_detector = InterferenceDetector()
        self.motion_simulator = MotionSimulator()

    def create_human_model(self, model_id: str,
                          height: float = 1.75,
                          weight: float = 70.0) -> str:
        """
        Create a new human model
        
        Args:
            model_id: Unique identifier for the model
            height: Human height in meters
            weight: Human weight in kg
            
        Returns:
            Model ID
        """
        self.human_models[model_id] = HumanModel(height=height, weight=weight)
        return model_id

    def add_equipment_to_human(self, model_id: str,
                              equipment_data: Dict[str, Any]) -> bool:
        """
        Add equipment to a human model
        
        Args:
            model_id: Human model ID
            equipment_data: Equipment parameters
            
        Returns:
            True if successful
        """
        if model_id not in self.human_models:
            return False

        try:
            equipment = Equipment(
                equipment_id=equipment_data["equipment_id"],
                name=equipment_data["name"],
                weight=equipment_data["weight"],
                position=np.array(equipment_data.get("position", [0, 0, 0])),
                attachment_point=equipment_data["attachment_point"],
                dimensions=tuple(equipment_data.get("dimensions", [0.1, 0.1, 0.1])),
                contact_area=equipment_data.get("contact_area", 0.01),
                center_of_mass=tuple(equipment_data.get("center_of_mass", [0, 0, 0]))
            )
            
            self.human_models[model_id].attach_equipment(equipment)
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to add equipment: {e}")
            return False

    def set_posture(self, model_id: str, posture: str) -> bool:
        """
        Set human model posture
        
        Args:
            model_id: Human model ID
            posture: Posture name ("standing", "crouching", "prone", etc.)
            
        Returns:
            True if successful
        """
        if model_id not in self.human_models:
            return False

        try:
            posture_enum = Posture[posture.upper()]
            self.human_models[model_id].set_posture(posture_enum)
            return True
        except (KeyError, AttributeError):
            return False

    def analyze_load_distribution(self, model_id: str) -> Dict[str, Any]:
        """
        Analyze load distribution for a human model
        
        Args:
            model_id: Human model ID
            
        Returns:
            Load distribution analysis results
        """
        if model_id not in self.human_models:
            return {"error": "Model not found"}

        human = self.human_models[model_id]
        load_dist = self.load_analyzer.compute_load_distribution(human)

        result = {
            "model_id": model_id,
            "total_equipment_weight": human.compute_total_equipment_weight(),
            "center_of_mass": human.get_center_of_mass().tolist(),
            "load_distribution": {}
        }

        for body_part, load in load_dist.items():
            result["load_distribution"][body_part] = {
                "force_newtons": load.force,
                "pressure_pascals": load.pressure,
                "duration_seconds": load.duration
            }

        return result

    def check_interference(self, model_id: str) -> Dict[str, Any]:
        """
        Check for equipment interference
        
        Args:
            model_id: Human model ID
            
        Returns:
            Interference detection results
        """
        if model_id not in self.human_models:
            return {"error": "Model not found"}

        human = self.human_models[model_id]
        all_interferences = []

        # Check equipment-body interferences
        for equipment in human.equipment_items:
            interferences = self.interference_detector.check_equipment_body_interference(
                equipment, human
            )
            all_interferences.extend(interferences)

        # Check equipment-equipment interferences
        if len(human.equipment_items) > 1:
            equip_interferences = self.interference_detector.check_equipment_equipment_interference(
                human.equipment_items, human
            )
            all_interferences.extend(equip_interferences)

        return {
            "model_id": model_id,
            "total_interferences": len(all_interferences),
            "interferences": all_interferences,
            "visualization": self.interference_detector.visualize_interferences(all_interferences)
        }

    def generate_comfort_report(self, model_id: str,
                                duration_minutes: float = 60) -> Dict[str, Any]:
        """
        Generate comprehensive comfort report
        
        Args:
            model_id: Human model ID
            duration_minutes: Analysis duration in minutes
            
        Returns:
            Comprehensive comfort report
        """
        if model_id not in self.human_models:
            return {"error": "Model not found"}

        human = self.human_models[model_id]
        report = self.load_analyzer.generate_comfort_report(human, duration_minutes)
        
        report["model_id"] = model_id
        report["human_height"] = human.height
        report["human_weight"] = human.weight
        report["current_posture"] = human.current_posture.value

        return report

    def simulate_motion_sequence(self, model_id: str,
                                posture_sequence: List[Tuple[str, float]]) -> Dict[str, Any]:
        """
        Simulate a sequence of postures over time
        
        Args:
            model_id: Human model ID
            posture_sequence: List of (posture_name, duration_seconds) tuples
            
        Returns:
            Motion simulation results
        """
        if model_id not in self.human_models:
            return {"error": "Model not found"}

        human = self.human_models[model_id]

        # Convert posture names to enums
        try:
            postures = [
                (Posture[posture.upper()], duration)
                for posture, duration in posture_sequence
            ]
        except KeyError as e:
            return {"error": f"Invalid posture name: {e}"}

        # Run simulation
        results = self.motion_simulator.simulate_motion_sequence(human, postures)
        results["model_id"] = model_id

        return results

    def export_analysis_report(self, model_id: str,
                              include_motion: bool = False) -> str:
        """
        Export comprehensive analysis report as JSON
        
        Args:
            model_id: Human model ID
            include_motion: Whether to include motion simulation
            
        Returns:
            JSON report string
        """
        if model_id not in self.human_models:
            return json.dumps({"error": "Model not found"})

        report = {
            "model_id": model_id,
            "human_parameters": {
                "height": self.human_models[model_id].height,
                "weight": self.human_models[model_id].weight,
                "current_posture": self.human_models[model_id].current_posture.value
            },
            "equipment": [],
            "load_analysis": {},
            "interference_check": {},
            "comfort_report": {}
        }

        # Equipment info
        human = self.human_models[model_id]
        for equip in human.equipment_items:
            report["equipment"].append({
                "id": equip.equipment_id,
                "name": equip.name,
                "weight": equip.weight,
                "attachment_point": equip.attachment_point
            })

        # Load analysis
        report["load_analysis"] = self.analyze_load_distribution(model_id)

        # Interference check
        report["interference_check"] = self.check_interference(model_id)

        # Comfort report
        report["comfort_report"] = self.generate_comfort_report(model_id)

        # Motion simulation (if requested)
        if include_motion:
            # Default motion sequence: standing -> walking -> crouching
            default_sequence = [
                ("standing", 5.0),
                ("walking", 10.0),
                ("crouching", 3.0),
                ("standing", 2.0)
            ]
            report["motion_simulation"] = self.simulate_motion_sequence(
                model_id, default_sequence
            )

        return json.dumps(report, indent=2, ensure_ascii=False)

    def get_available_postures(self) -> List[str]:
        """
        Get list of available postures
        
        Returns:
            List of posture names
        """
        return [p.value for p in Posture]

    def get_available_body_parts(self) -> List[str]:
        """
        Get list of body parts for equipment attachment
        
        Returns:
            List of body part names
        """
        return [bp.value for bp in BodyPart]

    def list_models(self) -> List[Dict[str, Any]]:
        """
        List all human models
        
        Returns:
            List of model information
        """
        models = []
        for model_id, human in self.human_models.items():
            models.append({
                "model_id": model_id,
                "height": human.height,
                "weight": human.weight,
                "current_posture": human.current_posture.value,
                "equipment_count": len(human.equipment_items),
                "total_equipment_weight": human.compute_total_equipment_weight()
            })
        return models

    def delete_model(self, model_id: str) -> bool:
        """
        Delete a human model
        
        Args:
            model_id: Model to delete
            
        Returns:
            True if deleted successfully
        """
        if model_id in self.human_models:
            del self.human_models[model_id]
            return True
        return False
