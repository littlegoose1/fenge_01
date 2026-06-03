import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.gp import gp_Trsf, gp_Vec, gp_Quaternion
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCC.Core.TopExp import TopExp_Explorer

try:
    from OCC.Core.TopoDS import topods_Face
except Exception:
    topods_Face = None


class ObjExportService:
    def __init__(self, export_dir: Optional[str] = None):
        base_dir = export_dir or os.getenv("OBJ_EXPORT_DIR", "")
        if not base_dir:
            base_dir = os.path.join(os.getenv("EXPORT_DIR", "exports"), "obj")
        self.export_dir = os.path.abspath(base_dir)
        os.makedirs(self.export_dir, exist_ok=True)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        if not name:
            return "model"
        s = re.sub(r"[\\/:*?\"<>|]+", "_", name.strip())
        s = re.sub(r"\s+", "_", s)
        return s or "model"

    @staticmethod
    def normalize_path(path_or_uri: str) -> str:
        if not path_or_uri:
            return ""
        p = str(path_or_uri).strip()
        if p.lower().startswith("file://"):
            u = urlparse(p)
            path = unquote(u.path or "")
            if len(path) >= 3 and path[0] == "/" and path[2] == ":":
                path = path[1:]
            if not path and u.netloc:
                path = unquote(u.netloc)
            p = path
        return os.path.normpath(p)

    def load_step_shape(self, path_or_uri: str):
        local_path = self.normalize_path(path_or_uri)
        if not local_path or not os.path.exists(local_path):
            return None
        reader = STEPControl_Reader()
        if reader.ReadFile(local_path) != IFSelect_RetDone:
            return None
        if reader.TransferRoots() == 0:
            return None
        return reader.OneShape()

    @staticmethod
    def parse_transform(tf: Any) -> Dict[str, Any]:
        default_tf = {"pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0]}
        if not tf:
            return default_tf
        if isinstance(tf, str):
            try:
                tf = json.loads(tf)
            except Exception:
                return default_tf
        if not isinstance(tf, dict):
            return default_tf
        if isinstance(tf.get("matrix"), list) and len(tf["matrix"]) == 16:
            return {"matrix": [float(v) for v in tf["matrix"]]}
        pos = tf.get("pos", [0.0, 0.0, 0.0])
        quat = tf.get("quat", [1.0, 0.0, 0.0, 0.0])
        if not isinstance(pos, list) or len(pos) != 3:
            pos = [0.0, 0.0, 0.0]
        if not isinstance(quat, list) or len(quat) != 4:
            quat = [1.0, 0.0, 0.0, 0.0]
        return {
            "pos": [float(pos[0]), float(pos[1]), float(pos[2])],
            "quat": [float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3])],
        }

    @staticmethod
    def apply_transform(shape, tf: Dict[str, Any]):
        tr = gp_Trsf()
        m = tf.get("matrix") if isinstance(tf, dict) else None
        if isinstance(m, list) and len(m) == 16:
            tr.SetValues(
                float(m[0]), float(m[1]), float(m[2]), float(m[3]),
                float(m[4]), float(m[5]), float(m[6]), float(m[7]),
                float(m[8]), float(m[9]), float(m[10]), float(m[11]),
            )
        else:
            pos = tf.get("pos", [0, 0, 0]) if isinstance(tf, dict) else [0, 0, 0]
            quat = tf.get("quat", [1, 0, 0, 0]) if isinstance(tf, dict) else [1, 0, 0, 0]
            if isinstance(quat, list) and len(quat) == 4 and quat != [1, 0, 0, 0]:
                q = gp_Quaternion(float(quat[1]), float(quat[2]), float(quat[3]), float(quat[0]))
                tr.SetRotation(q)
            if isinstance(pos, list) and len(pos) == 3:
                tr.SetTranslation(gp_Vec(float(pos[0]), float(pos[1]), float(pos[2])))
        return BRepBuilderAPI_Transform(shape, tr, True).Shape()

    @staticmethod
    def _as_face(current):
        if topods_Face is not None:
            return topods_Face(current)
        # pyOCC 7.8/7.9 fallback
        return current

    @staticmethod
    def _mesh_shape(shape, deflection: float = 0.5):
        # 兼容不同 pythonOCC 版本的构造签名
        attempts = [
            (shape, float(deflection), False, 0.5, True),
            (shape, float(deflection), False, 0.5),
            (shape, float(deflection)),
        ]
        for args in attempts:
            try:
                mesher = BRepMesh_IncrementalMesh(*args)
                if hasattr(mesher, "Perform"):
                    mesher.Perform()
                if hasattr(mesher, "IsDone"):
                    if mesher.IsDone():
                        return True
                else:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _get_node(tri, i: int):
        # 兼容 Node/Value/Point API
        for attr in ("Node", "Value", "Point"):
            if hasattr(tri, attr):
                try:
                    return getattr(tri, attr)(i)
                except Exception:
                    pass
        return None

    @staticmethod
    def _get_tri_indices(triangulation, i: int):
        # 兼容 Triangle(i) 与 Triangles().Value(i)
        if hasattr(triangulation, "Triangle"):
            try:
                t = triangulation.Triangle(i)
                return t.Get()
            except Exception:
                pass
        try:
            arr = triangulation.Triangles()
            t = arr.Value(i)
            return t.Get()
        except Exception:
            return None

    def export_shape_to_obj(self, shape, obj_path: str, deflection: float = 0.5) -> Tuple[bool, str]:
        self._mesh_shape(shape, deflection)

        os.makedirs(os.path.dirname(obj_path), exist_ok=True)
        vertex_offset = 1
        tri_count = 0

        try:
            with open(obj_path, "w", encoding="utf-8") as f:
                f.write("# CAD Geometry Editor OBJ export\n")
                exp = TopExp_Explorer(shape, TopAbs_FACE)
                while exp.More():
                    face = self._as_face(exp.Current())
                    loc = face.Location()
                    try:
                        triangulation = BRep_Tool.Triangulation(face, loc)
                    except TypeError:
                        from OCC.Core.TopLoc import TopLoc_Location
                        loc = TopLoc_Location()
                        triangulation = BRep_Tool.Triangulation(face, loc)
                    if triangulation is None:
                        exp.Next()
                        continue

                    n_nodes = int(getattr(triangulation, "NbNodes", lambda: 0)() or 0)
                    n_tris = int(getattr(triangulation, "NbTriangles", lambda: 0)() or 0)
                    if n_nodes <= 0 or n_tris <= 0:
                        exp.Next()
                        continue

                    index_map: Dict[int, int] = {}
                    trsf = loc.Transformation()
                    for i in range(1, n_nodes + 1):
                        node = self._get_node(triangulation, i)
                        if node is None:
                            continue
                        pnt = node.Transformed(trsf)
                        f.write(f"v {pnt.X():.9f} {pnt.Y():.9f} {pnt.Z():.9f}\n")
                        index_map[i] = vertex_offset
                        vertex_offset += 1

                    reversed_face = (face.Orientation() == TopAbs_REVERSED)
                    for i in range(1, n_tris + 1):
                        idx = self._get_tri_indices(triangulation, i)
                        if not idx:
                            continue
                        i1, i2, i3 = idx
                        if i1 not in index_map or i2 not in index_map or i3 not in index_map:
                            continue
                        g1, g2, g3 = index_map[i1], index_map[i2], index_map[i3]
                        if reversed_face:
                            g2, g3 = g3, g2
                        f.write(f"f {g1} {g2} {g3}\n")
                        tri_count += 1

                    exp.Next()

            if tri_count <= 0:
                return False, "no-triangle"
            return True, obj_path
        except Exception as e:
            return False, str(e)

    def export_assembly_nodes(
        self,
        assembly_name: str,
        assembly_id: str,
        nodes: List[Dict[str, Any]],
    ) -> Optional[str]:
        if not nodes:
            return None

        from OCC.Core.TopoDS import TopoDS_Compound
        from OCC.Core.BRep import BRep_Builder

        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)

        added = 0
        for n in nodes:
            step_uri = n.get("step_uri", "")
            shape = self.load_step_shape(step_uri)
            if shape is None:
                continue
            tf = self.parse_transform(n.get("transform") or n.get("transform_json"))
            shape_w = self.apply_transform(shape, tf)
            builder.Add(compound, shape_w)
            added += 1

        if added <= 0:
            return None

        safe_name = self._sanitize_filename(assembly_name)
        out_name = f"{safe_name}_{assembly_id[:8]}.obj" if assembly_id else f"{safe_name}.obj"
        out_path = os.path.join(self.export_dir, out_name)
        ok, _ = self.export_shape_to_obj(compound, out_path)
        return out_path if ok else None
