# -*- coding: utf-8 -*-
"""
Atomic Component Library for Equipment Modeling
Implements parameterized component storage and retrieval system
as described in section 3.3.1 of the research methodology
"""

import json
import uuid
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom


class AtomicComponent:
    """
    Represents a single atomic geometric component with parameters
    """

    def __init__(self, component_id: str = None):
        """
        Initialize an atomic component
        
        Args:
            component_id: Unique identifier for the component
        """
        self.id = component_id or str(uuid.uuid4())
        self.name = ""
        self.type = "generic"  # plane, cylinder, sphere, box, etc.
        self.category = "basic"  # basic, connector, functional
        self.version = "1.0.0"
        self.created_at = datetime.now().isoformat()
        self.modified_at = self.created_at
        self.description = ""
        self.tags = []
        
        # Geometric parameters
        self.parameters = {}
        
        # Material properties
        self.material = {
            "name": "default",
            "density": 1.0,
            "youngs_modulus": 0.0,
            "poissons_ratio": 0.0
        }
        
        # Performance metrics
        self.performance = {
            "weight": 0.0,
            "volume": 0.0,
            "surface_area": 0.0
        }
        
        # Metadata for version control
        self.metadata = {
            "author": "",
            "source": "segmentation",
            "parent_id": None,
            "revision_notes": ""
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert component to dictionary representation
        
        Returns:
            Dictionary containing all component data
        """
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "category": self.category,
            "version": self.version,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "description": self.description,
            "tags": self.tags,
            "parameters": self.parameters,
            "material": self.material,
            "performance": self.performance,
            "metadata": self.metadata
        }

    def from_dict(self, data: Dict[str, Any]) -> 'AtomicComponent':
        """
        Load component from dictionary representation
        
        Args:
            data: Dictionary containing component data
            
        Returns:
            Self for method chaining
        """
        self.id = data.get("id", self.id)
        self.name = data.get("name", "")
        self.type = data.get("type", "generic")
        self.category = data.get("category", "basic")
        self.version = data.get("version", "1.0.0")
        self.created_at = data.get("created_at", self.created_at)
        self.modified_at = data.get("modified_at", self.modified_at)
        self.description = data.get("description", "")
        self.tags = data.get("tags", [])
        self.parameters = data.get("parameters", {})
        self.material = data.get("material", self.material)
        self.performance = data.get("performance", self.performance)
        self.metadata = data.get("metadata", self.metadata)
        return self

    def to_json(self, indent: int = 2) -> str:
        """
        Convert component to JSON string
        
        Args:
            indent: Indentation level for JSON output
            
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_xml(self) -> str:
        """
        Convert component to XML string
        
        Returns:
            XML string representation
        """
        root = ET.Element("AtomicComponent")
        root.set("id", self.id)
        root.set("version", self.version)
        
        # Basic info
        ET.SubElement(root, "Name").text = self.name
        ET.SubElement(root, "Type").text = self.type
        ET.SubElement(root, "Category").text = self.category
        ET.SubElement(root, "Description").text = self.description
        
        # Timestamps
        timestamps = ET.SubElement(root, "Timestamps")
        ET.SubElement(timestamps, "Created").text = self.created_at
        ET.SubElement(timestamps, "Modified").text = self.modified_at
        
        # Tags
        tags_elem = ET.SubElement(root, "Tags")
        for tag in self.tags:
            ET.SubElement(tags_elem, "Tag").text = tag
        
        # Parameters
        params_elem = ET.SubElement(root, "Parameters")
        for key, value in self.parameters.items():
            param = ET.SubElement(params_elem, "Parameter")
            param.set("name", key)
            param.set("value", str(value))
        
        # Material
        material_elem = ET.SubElement(root, "Material")
        for key, value in self.material.items():
            ET.SubElement(material_elem, key).text = str(value)
        
        # Performance
        perf_elem = ET.SubElement(root, "Performance")
        for key, value in self.performance.items():
            ET.SubElement(perf_elem, key).text = str(value)
        
        # Metadata
        meta_elem = ET.SubElement(root, "Metadata")
        for key, value in self.metadata.items():
            if value is not None:
                ET.SubElement(meta_elem, key).text = str(value)
        
        # Pretty print
        rough_string = ET.tostring(root, encoding='unicode')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")


class ComponentLibrary:
    """
    Manages a library of atomic components with search and version control
    """

    def __init__(self, storage_path: str = "./component_library"):
        """
        Initialize component library
        
        Args:
            storage_path: Directory path for storing component data
        """
        self.storage_path = storage_path
        self.components: Dict[str, AtomicComponent] = {}
        self.index: Dict[str, List[str]] = {
            "by_type": {},
            "by_category": {},
            "by_tag": {}
        }
        
        # Create storage directory if it doesn't exist
        os.makedirs(storage_path, exist_ok=True)
        
        # Load existing components
        self._load_library()

    def add_component(self, component: AtomicComponent) -> bool:
        """
        Add a component to the library
        
        Args:
            component: Component to add
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update modification time
            component.modified_at = datetime.now().isoformat()
            
            # Store in memory
            self.components[component.id] = component
            
            # Update indices
            self._update_indices(component)
            
            # Save to disk
            self._save_component(component)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to add component {component.id}: {e}")
            return False

    def get_component(self, component_id: str) -> Optional[AtomicComponent]:
        """
        Get a component by its ID
        
        Args:
            component_id: Component identifier
            
        Returns:
            Component if found, None otherwise
        """
        return self.components.get(component_id)

    def remove_component(self, component_id: str) -> bool:
        """
        Remove a component from the library
        
        Args:
            component_id: Component identifier
            
        Returns:
            True if successful, False otherwise
        """
        if component_id not in self.components:
            return False
        
        try:
            component = self.components[component_id]
            
            # Remove from indices
            self._remove_from_indices(component)
            
            # Remove from memory
            del self.components[component_id]
            
            # Delete file
            file_path = self._get_component_path(component_id)
            if os.path.exists(file_path):
                os.remove(file_path)
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to remove component {component_id}: {e}")
            return False

    def search(self, query: Dict[str, Any]) -> List[AtomicComponent]:
        """
        Search for components matching query criteria
        
        Args:
            query: Dictionary with search criteria
                   Can include: type, category, tags, name_pattern
            
        Returns:
            List of matching components
        """
        results = []
        
        # Filter by type
        if "type" in query:
            component_ids = self.index["by_type"].get(query["type"], [])
            results = [self.components[cid] for cid in component_ids if cid in self.components]
        
        # Filter by category
        elif "category" in query:
            component_ids = self.index["by_category"].get(query["category"], [])
            results = [self.components[cid] for cid in component_ids if cid in self.components]
        
        # Filter by tag
        elif "tag" in query:
            component_ids = self.index["by_tag"].get(query["tag"], [])
            results = [self.components[cid] for cid in component_ids if cid in self.components]
        
        # All components
        else:
            results = list(self.components.values())
        
        # Apply name pattern filter
        if "name_pattern" in query:
            pattern = query["name_pattern"].lower()
            results = [c for c in results if pattern in c.name.lower()]
        
        return results

    def list_components(self, category: Optional[str] = None,
                       component_type: Optional[str] = None) -> List[AtomicComponent]:
        """
        List components with optional filtering
        
        Args:
            category: Filter by category
            component_type: Filter by type
            
        Returns:
            List of components
        """
        components = list(self.components.values())
        
        if category:
            components = [c for c in components if c.category == category]
        
        if component_type:
            components = [c for c in components if c.type == component_type]
        
        return components

    def get_component_history(self, component_id: str) -> List[Dict[str, Any]]:
        """
        Get version history for a component
        
        Args:
            component_id: Component identifier
            
        Returns:
            List of version records
        """
        history = []
        
        # Search for components with matching parent_id
        for comp in self.components.values():
            if comp.metadata.get("parent_id") == component_id:
                history.append({
                    "id": comp.id,
                    "version": comp.version,
                    "modified_at": comp.modified_at,
                    "notes": comp.metadata.get("revision_notes", "")
                })
        
        # Sort by modification time
        history.sort(key=lambda x: x["modified_at"], reverse=True)
        
        return history

    def create_variant(self, base_component_id: str, 
                      new_parameters: Dict[str, Any],
                      notes: str = "") -> Optional[AtomicComponent]:
        """
        Create a new variant of an existing component
        
        Args:
            base_component_id: ID of the base component
            new_parameters: New parameter values
            notes: Revision notes
            
        Returns:
            New component variant or None if failed
        """
        base = self.get_component(base_component_id)
        if not base:
            return None
        
        try:
            # Create new component with copied data
            variant = AtomicComponent()
            variant.name = base.name
            variant.type = base.type
            variant.category = base.category
            variant.description = base.description
            variant.tags = base.tags.copy()
            variant.parameters = base.parameters.copy()
            variant.material = base.material.copy()
            variant.performance = base.performance.copy()
            
            # Update with new parameters
            variant.parameters.update(new_parameters)
            
            # Set metadata for versioning
            variant.metadata["parent_id"] = base_component_id
            variant.metadata["source"] = "variant"
            variant.metadata["revision_notes"] = notes
            
            # Increment version
            base_version = tuple(map(int, base.version.split('.')))
            variant.version = f"{base_version[0]}.{base_version[1]}.{base_version[2] + 1}"
            
            # Add to library
            self.add_component(variant)
            
            return variant
            
        except Exception as e:
            print(f"[ERROR] Failed to create variant: {e}")
            return None

    def export_library(self, format: str = "json") -> str:
        """
        Export entire library to JSON or XML
        
        Args:
            format: Export format ("json" or "xml")
            
        Returns:
            String containing exported data
        """
        if format == "json":
            library_data = {
                "components": [c.to_dict() for c in self.components.values()],
                "exported_at": datetime.now().isoformat(),
                "count": len(self.components)
            }
            return json.dumps(library_data, indent=2, ensure_ascii=False)
        
        elif format == "xml":
            root = ET.Element("ComponentLibrary")
            root.set("exported_at", datetime.now().isoformat())
            root.set("count", str(len(self.components)))
            
            for component in self.components.values():
                # Parse component XML and append to library
                comp_xml = ET.fromstring(component.to_xml())
                root.append(comp_xml)
            
            rough_string = ET.tostring(root, encoding='unicode')
            reparsed = minidom.parseString(rough_string)
            return reparsed.toprettyxml(indent="  ")
        
        return ""

    def _update_indices(self, component: AtomicComponent):
        """Update search indices for a component"""
        # Index by type
        if component.type not in self.index["by_type"]:
            self.index["by_type"][component.type] = []
        if component.id not in self.index["by_type"][component.type]:
            self.index["by_type"][component.type].append(component.id)
        
        # Index by category
        if component.category not in self.index["by_category"]:
            self.index["by_category"][component.category] = []
        if component.id not in self.index["by_category"][component.category]:
            self.index["by_category"][component.category].append(component.id)
        
        # Index by tags
        for tag in component.tags:
            if tag not in self.index["by_tag"]:
                self.index["by_tag"][tag] = []
            if component.id not in self.index["by_tag"][tag]:
                self.index["by_tag"][tag].append(component.id)

    def _remove_from_indices(self, component: AtomicComponent):
        """Remove component from search indices"""
        # Remove from type index
        if component.type in self.index["by_type"]:
            self.index["by_type"][component.type] = [
                cid for cid in self.index["by_type"][component.type] 
                if cid != component.id
            ]
        
        # Remove from category index
        if component.category in self.index["by_category"]:
            self.index["by_category"][component.category] = [
                cid for cid in self.index["by_category"][component.category]
                if cid != component.id
            ]
        
        # Remove from tag indices
        for tag in component.tags:
            if tag in self.index["by_tag"]:
                self.index["by_tag"][tag] = [
                    cid for cid in self.index["by_tag"][tag]
                    if cid != component.id
                ]

    def _get_component_path(self, component_id: str) -> str:
        """Get file path for a component"""
        return os.path.join(self.storage_path, f"{component_id}.json")

    def _save_component(self, component: AtomicComponent):
        """Save component to disk"""
        file_path = self._get_component_path(component.id)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(component.to_json())

    def _load_library(self):
        """Load all components from disk"""
        if not os.path.exists(self.storage_path):
            return
        
        for filename in os.listdir(self.storage_path):
            if filename.endswith('.json'):
                file_path = os.path.join(self.storage_path, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        component = AtomicComponent().from_dict(data)
                        self.components[component.id] = component
                        self._update_indices(component)
                except Exception as e:
                    print(f"[WARN] Failed to load component from {filename}: {e}")


def create_component_from_primitive(primitive, library: ComponentLibrary) -> Optional[AtomicComponent]:
    """
    Create an atomic component from a geometric primitive
    
    Args:
        primitive: GeometricPrimitive instance
        library: ComponentLibrary to add the component to
        
    Returns:
        Created AtomicComponent or None if failed
    """
    try:
        component = AtomicComponent()
        component.name = f"{primitive.type.capitalize()} Component"
        component.type = primitive.type
        component.category = "basic"
        component.description = f"Atomic {primitive.type} component extracted from segmentation"
        component.tags = [primitive.type, "segmented", "geometric"]
        
        # Copy parameters from primitive
        component.parameters = primitive.get_params()
        
        # Set metadata
        component.metadata["source"] = "segmentation"
        component.metadata["primitive_id"] = primitive.id
        
        # Add to library
        library.add_component(component)
        
        return component
        
    except Exception as e:
        print(f"[ERROR] Failed to create component from primitive: {e}")
        return None
