# Research Methods Implementation (Section 3.3)

This document describes the implementation of the research methods for soldier equipment digital design as outlined in section 3.3 of the research methodology.

## Overview

The implementation provides three major research methods:

1. **Atomic-level Parameterized Modeling Mechanism** (3.3.1)
2. **Real-time Collaborative Deformation and Combined Assembly** (3.3.2)
3. **Human-Machine Ergonomics Verification** (3.3.3)

## 3.3.1 Atomic-level Parameterized Modeling Mechanism

### Purpose
Enable efficient construction and reuse of equipment models through systematic decomposition into reusable geometric components.

### Key Features

#### Equipment Structure Decomposition
- **Region Growing Segmentation**: Divides models based on surface continuity and normal vector similarity
- **Clustering-based Segmentation**: Uses K-means and DBSCAN for point cloud/mesh vertex aggregation
- **Boundary Detection**: Identifies edges, holes, slots, and curvature change points

#### Geometric Fitting
- **RANSAC Algorithm**: Robust shape fitting for spheres, cylinders, planes, cones, and tori
- **Improved Least Squares**: Fine-tunes geometric parameters
- **PCA Alignment**: Automatically aligns geometry with standard primitives

#### Atomic Component Library
- **Parameterized Storage**: Components stored in XML/JSON format
- **Classification System**: Organized by type and category
- **Version Management**: Tracks component evolution and variants
- **Search and Retrieval**: Fast lookup by type, category, or tags

### Usage Example

```python
from src.services.segmentation_service import SegmentationService

# Initialize service
service = SegmentationService(library_path="./component_library")

# Segment equipment
results = service.segment_equipment(shape, method="region_growing", 
                                   extract_to_library=True)

# Search components
components = service.search_components({"type": "cylinder", "category": "basic"})

# Export library
exported = service.export_library(format="json")
```

### Modules
- `src/model/advanced_segmentation.py`: Advanced segmentation algorithms
- `src/model/atomic_library.py`: Component library management
- `src/services/segmentation_service.py`: Integration service

## 3.3.2 Real-time Collaborative Deformation and Combined Assembly

### Purpose
Solve the "single part modification → whole model mismatch" problem through dynamic coordination between local deformation and global assembly.

### Key Features

#### Collaborative Geometry Deformation
- **Topology Analysis**: Identifies relationships between parts (adjacency, connection, dependency)
- **Adjacency Matrix**: Tracks component connectivity and influence strength
- **Matrix-driven Adjustment**: Uses geometric transformations for automatic adaptation
- **Influence Propagation**: Dampens transformations based on connectivity strength

#### Constraint-based Assembly
- **Constraint Expression**: Mathematical encoding of position, distance, angle, tangent, parallel relationships
- **Multi-constraint Solver**: Handles complex constraint sets iteratively
- **Automatic Alignment**: Resolves conflicts and adjusts positions automatically

#### Assembly Optimization
- **Conflict Detection**: Predicts and identifies part collisions
- **Interference Resolution**: Suggests and applies position adjustments
- **Constraint Matrix Optimization**: Efficient solving for large assemblies

### Usage Example

```python
from src.model.collaborative_deformation import (
    CollaborativeDeformationEngine,
    GeometricConstraint,
    TopologyRelation
)

# Initialize engine
engine = CollaborativeDeformationEngine()

# Register components
engine.register_component("part_1", part_data, position=(0, 0, 0))
engine.register_component("part_2", part_data, position=(10, 0, 0))

# Add topology relation
relation = TopologyRelation(
    source_id="part_1",
    target_id="part_2",
    relation_type="connected",
    strength=0.8
)
engine.adjacency.add_relation(relation)

# Add constraint
constraint = GeometricConstraint(
    constraint_id="c1",
    constraint_type="distance",
    components=["part_1", "part_2"],
    parameters={"distance": 15.0}
)
engine.add_constraint(constraint)

# Apply transformation with propagation
affected = engine.apply_transformation(
    "part_1", 
    translation=(5, 0, 0), 
    propagate=True
)

# Solve constraints
final_transforms = engine.solve_constraints(max_iterations=10)

# Detect interference
has_interference = engine.detect_interference("part_1", "part_2")

# Optimize assembly
optimization = engine.optimize_assembly(["part_1", "part_2"])
```

### Modules
- `src/model/collaborative_deformation.py`: Deformation and assembly engine
- `src/solver/assembly_solver.py`: Constraint solving (existing, enhanced)

## 3.3.3 Human-Machine Ergonomics Verification

### Purpose
Rapidly verify equipment ergonomics through 3D human visualization and dynamic load analysis.

### Key Features

#### Equipment-Human Dynamic Fitting
- **3D Human Model**: Parametric skeletal model with joint hierarchy
- **Posture Simulation**: Standing, walking, running, crouching, prone positions
- **Joint Kinematics**: Real-time constraint calculation for motion
- **Equipment Attachment**: Multiple attachment points on body

#### Human Load Analysis
- **Force Calculation**: Computes loads on shoulders, waist, legs, etc.
- **Pressure Distribution**: Calculates contact pressure at attachment points
- **Load Visualization**: Generates data for heat maps and vector displays
- **Fatigue Simulation**: Models long-term wearing effects

#### Real-time Interference Detection
- **Equipment-Body Collision**: Detects interference during motion
- **Equipment-Equipment Collision**: Checks for conflicts between items
- **Visual Feedback**: Highlights problem areas
- **Interactive Adjustment**: Supports real-time position optimization

#### Motion Simulation
- **Posture Sequences**: Simulates multiple postures over time
- **Load History**: Tracks force distribution through motion
- **Interference Events**: Records when and where conflicts occur
- **Comfort Scoring**: Quantifies overall ergonomic quality

### Usage Example

```python
from src.services.ergonomics_service import ErgonomicsService

# Initialize service
service = ErgonomicsService()

# Create human model
model_id = service.create_human_model("soldier_1", height=1.75, weight=70.0)

# Add equipment
service.add_equipment_to_human(model_id, {
    "equipment_id": "backpack_1",
    "name": "Combat Backpack",
    "weight": 15.0,
    "position": [0.0, -0.15, 0.0],
    "attachment_point": "chest",
    "dimensions": [0.3, 0.2, 0.4],
    "contact_area": 0.06
})

# Set posture
service.set_posture(model_id, "standing")

# Analyze load distribution
load_analysis = service.analyze_load_distribution(model_id)

# Check interference
interference = service.check_interference(model_id)

# Generate comfort report
comfort_report = service.generate_comfort_report(model_id, duration_minutes=60)

# Simulate motion
motion_results = service.simulate_motion_sequence(model_id, [
    ("standing", 5.0),
    ("walking", 10.0),
    ("crouching", 3.0)
])

# Export comprehensive report
report = service.export_analysis_report(model_id, include_motion=True)
```

### Modules
- `src/model/ergonomics_verification.py`: Human model, load analysis, interference detection
- `src/services/ergonomics_service.py`: Integration service

## Running the Demonstration

A comprehensive demonstration script is provided that showcases all three research methods:

```bash
cd /home/runner/work/fenge_01/fenge_01
python scripts/demo_research_methods.py
```

This will:
1. Demonstrate atomic-level modeling with segmentation and component library
2. Show collaborative deformation with constraint solving
3. Perform ergonomics analysis with load distribution and motion simulation
4. Generate output files including a detailed ergonomics report

## File Structure

```
src/
├── model/
│   ├── advanced_segmentation.py    # Region growing, clustering, boundary detection
│   ├── atomic_library.py           # Component library management
│   ├── collaborative_deformation.py # Deformation and assembly
│   └── ergonomics_verification.py  # Human model and analysis
├── services/
│   ├── segmentation_service.py     # Segmentation integration
│   └── ergonomics_service.py       # Ergonomics integration
scripts/
└── demo_research_methods.py        # Comprehensive demonstration
docs/
└── RESEARCH_METHODS.md            # This document
```

## Dependencies

New dependency added to `requirements.txt`:
- `scikit-learn>=1.0.0` - For K-means and DBSCAN clustering

## Support

For questions or issues related to these research methods, please refer to:
- Module docstrings for detailed API documentation
- Example scripts in `scripts/` directory
- Main application integration code in `src/services/`
