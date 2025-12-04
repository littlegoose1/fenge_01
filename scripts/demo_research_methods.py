#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demonstration script for research methods (Section 3.3)
Shows usage of:
1. Atomic-level parameterized modeling
2. Collaborative deformation and assembly
3. Human-machine ergonomics verification
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.segmentation_service import SegmentationService
from src.services.ergonomics_service import ErgonomicsService
from src.model.collaborative_deformation import (
    CollaborativeDeformationEngine,
    GeometricConstraint,
    TopologyRelation
)
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCC.Core.gp import gp_Pnt, gp_Ax2, gp_Dir
import json


def demo_atomic_modeling():
    """
    Demonstrate atomic-level parameterized modeling (3.3.1)
    """
    print("=" * 60)
    print("DEMO 1: Atomic-level Parameterized Modeling")
    print("=" * 60)
    
    # Initialize segmentation service
    service = SegmentationService(library_path="./demo_library")
    
    # Create a simple test shape (box)
    test_shape = BRepPrimAPI_MakeBox(10, 20, 30).Shape()
    
    print("\n[1] Segmenting equipment using default method...")
    result_default = service.segment_equipment(test_shape, method="default", extract_to_library=True)
    print(f"   Found {result_default['statistics']['total_faces']} faces")
    print(f"   Extracted {len(result_default['components'])} components to library")
    
    print("\n[2] Segmenting using Region Growing...")
    result_rg = service.segment_equipment(test_shape, method="region_growing", extract_to_library=False)
    print(f"   Found {result_rg['statistics'].get('regions_found', 0)} regions")
    
    print("\n[3] Segmenting using K-means clustering...")
    result_kmeans = service.segment_equipment(test_shape, method="kmeans", extract_to_library=False)
    print(f"   Found {result_kmeans['statistics'].get('clusters_found', 0)} clusters")
    
    print("\n[4] Boundary detection results:")
    boundaries = result_default['boundaries']
    print(f"   Sharp edges: {boundaries['sharp_edges']}")
    print(f"   Boundary edges: {boundaries['boundary_edges']}")
    print(f"   Curvature changes: {boundaries['curvature_changes']}")
    
    print("\n[5] Component library statistics:")
    stats = service.get_component_statistics()
    print(f"   Total components: {stats['total_components']}")
    print(f"   By type: {stats['by_type']}")
    print(f"   Storage: {stats['storage_path']}")
    
    # Export library
    print("\n[6] Exporting component library to JSON...")
    exported = service.export_library(format="json")
    print(f"   Exported {len(exported)} characters")
    
    print("\n✓ Atomic modeling demo completed")


def demo_collaborative_deformation():
    """
    Demonstrate collaborative deformation and assembly (3.3.2)
    """
    print("\n" + "=" * 60)
    print("DEMO 2: Collaborative Deformation and Assembly")
    print("=" * 60)
    
    # Initialize deformation engine
    engine = CollaborativeDeformationEngine()
    
    print("\n[1] Registering components...")
    engine.register_component(
        "component_1",
        {"type": "box", "size": [10, 10, 10]},
        position=(0, 0, 0)
    )
    engine.register_component(
        "component_2",
        {"type": "cylinder", "radius": 5, "height": 20},
        position=(15, 0, 0)
    )
    engine.register_component(
        "component_3",
        {"type": "box", "size": [8, 8, 8]},
        position=(30, 0, 0)
    )
    print("   Registered 3 components")
    
    print("\n[2] Building adjacency relationships...")
    # Component 1 and 2 are connected
    relation_1_2 = TopologyRelation(
        source_id="component_1",
        target_id="component_2",
        relation_type="connected",
        distance=5.0,
        strength=0.8
    )
    engine.adjacency.add_relation(relation_1_2)
    
    # Component 2 and 3 are adjacent
    relation_2_3 = TopologyRelation(
        source_id="component_2",
        target_id="component_3",
        relation_type="adjacent",
        distance=10.0,
        strength=0.5
    )
    engine.adjacency.add_relation(relation_2_3)
    print("   Built adjacency matrix")
    
    print("\n[3] Adding geometric constraints...")
    # Distance constraint between component 1 and 2
    constraint_distance = GeometricConstraint(
        constraint_id="c1",
        constraint_type="distance",
        components=["component_1", "component_2"],
        parameters={"distance": 20.0},
        priority=10
    )
    engine.add_constraint(constraint_distance)
    
    # Position constraint for component 3
    constraint_position = GeometricConstraint(
        constraint_id="c2",
        constraint_type="position",
        components=["component_3", "component_3"],
        parameters={"position": [40.0, 0.0, 0.0]},
        priority=5
    )
    engine.add_constraint(constraint_position)
    print("   Added 2 geometric constraints")
    
    print("\n[4] Applying transformation with propagation...")
    affected = engine.apply_transformation(
        "component_1",
        translation=(5.0, 0.0, 0.0),
        propagate=True
    )
    print(f"   Affected {len(affected)} components:")
    for comp_id, transform in affected.items():
        print(f"      {comp_id}: pos={transform['position']}")
    
    print("\n[5] Solving constraints...")
    final_transforms = engine.solve_constraints(max_iterations=10)
    print(f"   Solved constraints for {len(final_transforms)} components")
    
    print("\n[6] Detecting interference...")
    has_interference = engine.detect_interference("component_1", "component_2")
    print(f"   Interference between component_1 and component_2: {has_interference}")
    
    print("\n[7] Optimizing assembly...")
    optimization = engine.optimize_assembly(["component_1", "component_2", "component_3"])
    print(f"   Interferences detected: {optimization['interferences_detected']}")
    print(f"   Interferences resolved: {optimization['interferences_resolved']}")
    
    print("\n✓ Collaborative deformation demo completed")


def demo_ergonomics_verification():
    """
    Demonstrate human-machine ergonomics verification (3.3.3)
    """
    print("\n" + "=" * 60)
    print("DEMO 3: Human-Machine Ergonomics Verification")
    print("=" * 60)
    
    # Initialize ergonomics service
    service = ErgonomicsService()
    
    print("\n[1] Creating human model...")
    model_id = service.create_human_model(
        "soldier_1",
        height=1.75,
        weight=70.0
    )
    print(f"   Created model: {model_id}")
    
    print("\n[2] Adding equipment...")
    # Add backpack
    service.add_equipment_to_human(model_id, {
        "equipment_id": "backpack_1",
        "name": "Combat Backpack",
        "weight": 15.0,  # kg
        "position": [0.0, -0.15, 0.0],
        "attachment_point": "chest",
        "dimensions": [0.3, 0.2, 0.4],
        "contact_area": 0.06,  # m²
        "center_of_mass": [0.0, -0.1, 0.0]
    })
    
    # Add vest
    service.add_equipment_to_human(model_id, {
        "equipment_id": "vest_1",
        "name": "Tactical Vest",
        "weight": 8.0,  # kg
        "position": [0.0, 0.0, 0.0],
        "attachment_point": "chest",
        "dimensions": [0.4, 0.15, 0.5],
        "contact_area": 0.12,  # m²
        "center_of_mass": [0.0, 0.05, 0.0]
    })
    
    # Add helmet
    service.add_equipment_to_human(model_id, {
        "equipment_id": "helmet_1",
        "name": "Combat Helmet",
        "weight": 1.5,  # kg
        "position": [0.0, 0.0, 0.0],
        "attachment_point": "head",
        "dimensions": [0.25, 0.25, 0.3],
        "contact_area": 0.04,  # m²
        "center_of_mass": [0.0, 0.0, 0.0]
    })
    
    print("   Added 3 equipment items (backpack, vest, helmet)")
    
    print("\n[3] Available postures:")
    postures = service.get_available_postures()
    print(f"   {', '.join(postures)}")
    
    print("\n[4] Setting posture to STANDING...")
    service.set_posture(model_id, "standing")
    print("   Posture set")
    
    print("\n[5] Analyzing load distribution...")
    load_analysis = service.analyze_load_distribution(model_id)
    print(f"   Total equipment weight: {load_analysis['total_equipment_weight']:.2f} kg")
    print(f"   Center of mass: {load_analysis['center_of_mass']}")
    print("   Load distribution by body part:")
    for body_part, load_data in load_analysis['load_distribution'].items():
        print(f"      {body_part}: {load_data['force_newtons']:.2f} N, "
              f"{load_data['pressure_pascals']:.0f} Pa")
    
    print("\n[6] Checking for interference...")
    interference = service.check_interference(model_id)
    print(f"   Total interferences: {interference['total_interferences']}")
    if interference['total_interferences'] > 0:
        print("   Details:")
        print(interference['visualization'])
    
    print("\n[7] Generating comfort report...")
    comfort = service.generate_comfort_report(model_id, duration_minutes=60)
    print(f"   Comfort score: {comfort['comfort_score']:.1f}/100")
    print(f"   Max pressure: {comfort['max_pressure']:.0f} Pa")
    print(f"   Recommendations:")
    for rec in comfort['recommendations']:
        print(f"      - {rec}")
    
    print("\n[8] Simulating motion sequence...")
    motion_sequence = [
        ("standing", 5.0),
        ("walking", 10.0),
        ("crouching", 3.0),
        ("standing", 2.0)
    ]
    motion_results = service.simulate_motion_sequence(model_id, motion_sequence)
    print(f"   Total simulation duration: {motion_results['total_duration']:.1f} seconds")
    print(f"   Posture sequence: {len(motion_results['posture_sequence'])} postures")
    print(f"   Load snapshots: {len(motion_results['load_snapshots'])}")
    print(f"   Interference events: {len(motion_results['interference_events'])}")
    print(f"   Summary:")
    print(f"      Total interferences: {motion_results['summary']['total_interferences']}")
    print(f"      Max load: {motion_results['summary']['max_load']:.2f} N")
    
    print("\n[9] Exporting analysis report...")
    report = service.export_analysis_report(model_id, include_motion=True)
    report_data = json.loads(report)
    print(f"   Report size: {len(report)} characters")
    print(f"   Report sections: {list(report_data.keys())}")
    
    # Save report to file
    report_file = "./demo_ergonomics_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"   Report saved to: {report_file}")
    
    print("\n✓ Ergonomics verification demo completed")


def main():
    """Run all demonstrations"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║  Research Methods Demonstration (Section 3.3)           ║")
    print("║  Single-Soldier Equipment Digital Design                ║")
    print("║" + " " * 58 + "║")
    print("╚" + "═" * 58 + "╝")
    
    try:
        # Demo 1: Atomic-level parameterized modeling
        demo_atomic_modeling()
        
        # Demo 2: Collaborative deformation and assembly
        demo_collaborative_deformation()
        
        # Demo 3: Human-machine ergonomics verification
        demo_ergonomics_verification()
        
        print("\n")
        print("=" * 60)
        print("ALL DEMONSTRATIONS COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print("\nGenerated files:")
        print("  - ./demo_library/ (component library)")
        print("  - ./demo_ergonomics_report.json (analysis report)")
        print()
        
    except Exception as e:
        print(f"\n[ERROR] Demonstration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
