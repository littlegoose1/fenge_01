import os
import json
import hashlib
from typing import Dict, Any, Optional, List, Tuple

DEBUG = os.getenv("ASSEMBLY_IMPORT_DEBUG") == "1"
TOL = float(os.getenv("ASSEMBLY_DEDUP_TOL", "0.02"))
USE_PCA = os.getenv("ASSEMBLY_CANON_USE_PCA", "1") != "0"
FORCE_FLAT = True
SPLIT_SOLIDS = True
ROUND_DIGITS = int(os.getenv("ASSEMBLY_FINGERPRINT_ROUND", "6"))

def _d(msg: str):
    if DEBUG:
        print(f"[ASM-DEBUG] {msg}", flush=True)

# OCC imports
from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.gp import gp_XYZ, gp_Trsf, gp_Pnt, gp_Mat
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

# BRepBndLib compatibility
def _make_bnd_add():
    try:
        import OCC.Core.BRepBndLib as _BRepBndLib
    except Exception:
        return None
    if hasattr(_BRepBndLib, "brepbndlib") and hasattr(_BRepBndLib.brepbndlib, "Add"):
        mod = _BRepBndLib.brepbndlib
        return lambda s, b, tri=True: mod.Add(s, b, bool(tri))
    if hasattr(_BRepBndLib, "Add"):
        return lambda s, b, tri=True: _BRepBndLib.Add(s, b, bool(tri))
    if hasattr(_BRepBndLib, "brepbndlib_Add"):
        old = _BRepBndLib.brepbndlib_Add
        return lambda s, b, tri=True: old(s, b, tri)
    return None

bnd_add = _make_bnd_add()

# numpy / PCA
try:
    import numpy as np
    NP_AVAILABLE = True
except Exception:
    NP_AVAILABLE = False
    _d("numpy 不可用：禁用 PCA 旋转归一。")

# DB
from ..db.mysql_repo import MySQLRepo
from ..db.uuid_util import uuid4_bytes, uuid_bytes_to_str

# -------- utils --------
def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256(); h.update(data); return h.hexdigest()

def _export_shape_to_step_bytes(shape: TopoDS_Shape, tmp_name: str) -> bytes:
    writer = STEPControl_Writer()
    Interface_Static.SetCVal("write.step.schema", "AP214")
    st = writer.Transfer(shape, STEPControl_AsIs)
    if st != IFSelect_RetDone:
        raise RuntimeError("Transfer STEP 失败")
    tmp_path = os.path.abspath(tmp_name)
    st = writer.Write(tmp_path)
    if st != IFSelect_RetDone:
        raise RuntimeError("写 STEP 失败")
    with open(tmp_path, "rb") as f:
        data = f.read()
    try: os.remove(tmp_path)
    except OSError: pass
    return data

def _bbox(shape: TopoDS_Shape) -> Tuple[float, float, float, float, float, float]:
    if bnd_add is None:
        return (0,0,0,0,0,0)
    box = Bnd_Box(); box.SetGap(0.0)
    try:
        bnd_add(shape, box, True)
    except TypeError:
        bnd_add(shape, box, 1)
    return box.Get()

def _volume_props(shape: TopoDS_Shape) -> Dict[str, Any]:
    res: Dict[str, Any] = {}
    props = GProp_GProps()
    try:
        brepgprop.VolumeProperties(shape, props)
        m = props.Mass()
        if m > 0:
            c = props.CentreOfMass()
            I = props.MatrixOfInertia()
            res["mass"] = m
            res["com"] = (c.X(), c.Y(), c.Z())
            res["inertia_diag"] = (I.Value(1,1), I.Value(2,2), I.Value(3,3))
    except Exception:
        pass
    return res

def _remove_location(shape: TopoDS_Shape) -> TopoDS_Shape:
    loc = shape.Location()
    if loc.IsIdentity():
        return shape
    tr = loc.Transformation()
    tr.Invert()  # 原地求逆
    return BRepBuilderAPI_Transform(shape, tr, True).Shape()

def _triangulate(shape: TopoDS_Shape, deflection=0.3, angle=0.6):
    try:
        BRepMesh_IncrementalMesh(shape, deflection, False, angle)
    except Exception as e:
        _d(f"三角化失败: {e}")

def _get_node(tri, i: int):
    """
    宽容获取节点：优先 tri.Node(i)，Fallback tri.Value(i) 或 tri.Point(i)
    """
    for attr in ("Node", "Value", "Point"):
        if hasattr(tri, attr):
            try:
                return getattr(tri, attr)(i)
            except Exception:
                pass
    return None

def _collect_pts(shape: TopoDS_Shape):
    if not NP_AVAILABLE:
        return None
    _triangulate(shape)
    pts = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = exp.Current()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation(face, loc)
        if tri:
            trsf = loc.Transformation()
            nb = getattr(tri, "NbNodes", lambda: 0)()
            for i in range(1, nb + 1):
                node = _get_node(tri, i)
                if node is None:
                    continue
                # node 是 gp_Pnt；获取 XYZ 并原地应用变换（Transforms 无返回值）
                xyz: gp_XYZ = node.XYZ()
                trsf.Transforms(xyz)  # 原地修改 xyz
                pts.append([xyz.X(), xyz.Y(), xyz.Z()])
        exp.Next()
    return np.array(pts) if pts else None

def _canonical_basic(shape: TopoDS_Shape) -> TopoDS_Shape:
    no_loc = _remove_location(shape)
    xmin,ymin,zmin,xmax,ymax,zmax = _bbox(no_loc)
    cx,cy,cz = (xmin+xmax)/2.0, (ymin+ymax)/2.0, (zmin+zmax)/2.0
    tr = gp_Trsf(); tr.SetTranslation(gp_Pnt(cx,cy,cz), gp_Pnt(0,0,0))
    return BRepBuilderAPI_Transform(no_loc, tr, True).Shape()

def _pca_align(shape: TopoDS_Shape) -> TopoDS_Shape:
    no_loc = _remove_location(shape)
    pts = _collect_pts(no_loc)
    if pts is None or len(pts) < 5:
        return _canonical_basic(shape)
    mean = pts.mean(axis=0)
    pts0 = pts - mean
    cov = np.cov(pts0.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvecs = eigvecs[:, order]
    # 右手系
    if np.linalg.det(eigvecs) < 0:
        eigvecs[:,2] *= -1.0
    # 符号锚定
    proj = pts0 @ eigvecs
    signs = np.sign(proj.sum(axis=0) + 1e-12)
    signs[signs==0] = 1.0
    eigvecs *= signs
    R = eigvecs
    R_T = R.T
    mT = gp_Mat(R_T[0,0], R_T[0,1], R_T[0,2],
                R_T[1,0], R_T[1,1], R_T[1,2],
                R_T[2,0], R_T[2,1], R_T[2,2])
    tr_rot = gp_Trsf(); tr_rot.SetVectorialPart(mT)
    rotated = BRepBuilderAPI_Transform(no_loc, tr_rot, True).Shape()
    xmin,ymin,zmin,xmax,ymax,zmax = _bbox(rotated)
    cx,cy,cz = (xmin+xmax)/2.0, (ymin+ymax)/2.0, (zmin+zmax)/2.0
    tr = gp_Trsf(); tr.SetTranslation(gp_Pnt(cx,cy,cz), gp_Pnt(0,0,0))
    return BRepBuilderAPI_Transform(rotated, tr, True).Shape()

def _shape_signature(shape: TopoDS_Shape) -> Dict[str, Any]:
    sig: Dict[str, Any] = {}
    vol = _volume_props(shape)
    if "mass" in vol:
        sig["mass"] = vol["mass"]
        idg = vol.get("inertia_diag")
        if idg:
            tot = sum(idg)
            if tot > 0:
                sig["inertia_ratio"] = [v/tot for v in idg]
    xmin,ymin,zmin,xmax,ymax,zmax = _bbox(shape)
    dx,dy,dz = max(xmax-xmin,1e-9), max(ymax-ymin,1e-9), max(zmax-zmin,1e-9)
    dims_sorted = sorted([dx,dy,dz])
    sig["bbox_ratio"] = [dims_sorted[0]/dims_sorted[2], dims_sorted[1]/dims_sorted[2]]
    pts = _collect_pts(shape) if NP_AVAILABLE else None
    if pts is not None and len(pts) >= 5:
        sig["tri_points"] = len(pts)
        mean = pts.mean(axis=0)
        cov = np.cov((pts-mean).T)
        eigvals,_ = np.linalg.eigh(cov)
        eigvals = sorted(eigvals, reverse=True)
        tot = sum(eigvals)
        if tot > 0:
            sig["eig_ratio"] = [v/tot for v in eigvals]
    else:
        sig["tri_points"] = 0
    return sig

def _similar(sigA: Dict[str,Any], sigB: Dict[str,Any], tol=TOL) -> bool:
    def cmp_list(a,b, scale=1.0):
        if len(a)!=len(b): return False
        for x,y in zip(a,b):
            if y == 0 and x == 0: continue
            if y == 0: return False
            if abs(x - y) / (abs(y) + 1e-12) > tol*scale:
                return False
        return True
    if "mass" in sigA and "mass" in sigB:
        m1,m2 = sigA["mass"], sigB["mass"]
        if m2 == 0 or abs(m1-m2)/(abs(m2)+1e-12) > tol:
            return False
    for key in ["inertia_ratio","bbox_ratio","eig_ratio"]:
        if key in sigA and key in sigB:
            if not cmp_list(sigA[key], sigB[key]):
                return False
    if sigA.get("tri_points") and sigB.get("tri_points"):
        t1,t2 = sigA["tri_points"], sigB["tri_points"]
        if abs(t1 - t2) / (max(t2,1)+1e-12) > tol*5:
            return False
    return True

class AssemblyImportService:
    def __init__(self, repo: Optional[MySQLRepo] = None,
                 export_dir: Optional[str] = None):
        self.repo = repo or MySQLRepo()
        self.export_dir = export_dir or os.getenv("EXPORT_DIR", "exports")
        os.makedirs(self.export_dir, exist_ok=True)

    def import_step_assembly(self, step_path: str) -> Dict[str, Any]:
        if not os.path.isfile(step_path):
            raise FileNotFoundError(step_path)
        _d(f"导入开始(flat-split-signature): {step_path}")
        reader = STEPControl_Reader()
        st = reader.ReadFile(step_path)
        if st != IFSelect_RetDone:
            raise RuntimeError(f"读取失败 status={st}")
        if not reader.TransferRoot():
            raise RuntimeError("TransferRoot 失败")
        top_shape = reader.OneShape()

        assembly_name = os.path.splitext(os.path.basename(step_path))[0]
        assembly_id = uuid4_bytes()
        self._insert_assembly(assembly_id, assembly_name, f"Flat(split signature) from {step_path}")

        subs: List[TopoDS_Shape] = []
        exp = TopExp_Explorer(top_shape, TopAbs_SOLID)
        while exp.More():
            subs.append(exp.Current()); exp.Next()
        if not subs:
            exp = TopExp_Explorer(top_shape, TopAbs_SHELL)
            while exp.More():
                subs.append(exp.Current()); exp.Next()

        if not subs:
            _d("未找到实体→单件处理")
            return self._import_single(top_shape, assembly_name, assembly_id)

        clusters: List[Dict[str,Any]] = []
        nodes = []

        for idx, sub in enumerate(subs, start=1):
            try:
                canon_shape = _pca_align(sub) if (USE_PCA and NP_AVAILABLE) else _canonical_basic(sub)
            except Exception as e:
                _d(f"实体 {idx} 规范化失败: {e}")
                canon_shape = _canonical_basic(sub)

            sig = _shape_signature(canon_shape)

            matched = None
            for c in clusters:
                if _similar(sig, c["sig"], tol=TOL):
                    matched = c
                    break

            if matched:
                part_id = matched["part_id"]
                part_version_id = matched["part_version_id"]
                part_key = matched["part_key"]
                new_version_created = False
            else:
                step_bytes = _export_shape_to_step_bytes(canon_shape, f".__sig_{idx}.step")
                sha = hashlib.sha256(step_bytes).hexdigest()
                short = sha[:8]
                part_key = f"{assembly_name.lower().replace(' ', '_')}.{short}"
                part_name = assembly_name
                part_id = self.repo.ensure_part(
                    key=part_key,
                    name=part_name,
                    category=None,
                    tags=["import", "split", "signature"],
                    description="Signature clustered import"
                )
                filename = f"{part_name}_{short}.step"
                out_path = os.path.abspath(os.path.join(self.export_dir, filename))
                with open(out_path, "wb") as f:
                    f.write(step_bytes)
                xmin,ymin,zmin,xmax,ymax,zmax = _bbox(canon_shape)
                bbox = {"xmin": xmin, "ymin": ymin, "zmin": zmin,
                        "xmax": xmax, "ymax": ymax, "zmax": zmax}
                geom_id = self.repo.insert_geom_asset(
                    uri=f"file://{out_path.replace(os.sep, '/')}",
                    sha256_hex=sha,
                    format_="step",
                    units=os.getenv("UNITS", "mm"),
                    bbox_json=bbox,
                    meta_json={"import": True, "signature": True, "seg_index": idx}
                )
                mass_props = _volume_props(canon_shape)
                part_version_id = self._insert_part_version(
                    part_id=part_id,
                    version_no=1,
                    geom_asset_id=geom_id,
                    source_path=f"{assembly_name}/seg{idx}",
                    mass_props=mass_props
                )
                new_version_created = True
                clusters.append({
                    "sig": sig,
                    "part_id": part_id,
                    "part_version_id": part_version_id,
                    "part_key": part_key
                })

            node_id = self._insert_assembly_node(
                assembly_id=assembly_id,
                part_version_id=part_version_id,
                parent_id=None,
                name=f"{assembly_name}_seg{idx}",
                pos=[0.0,0.0,0.0],
                quat=[1.0,0.0,0.0,0.0],
                source_path=f"{assembly_name}/seg{idx}"
            )

            if DEBUG:
                _d(f"SEG#{idx} -> part_key={part_key} new={new_version_created} sig={sig}")

            nodes.append({
                "path": [assembly_name, f"seg{idx}"],
                "part_key": part_key,
                "version_no": 1,
                "assembly_node_id": uuid_bytes_to_str(node_id),
                "new_version_created": new_version_created
            })

        if DEBUG:
            _d(f"实体总数={len(subs)} 聚类后 part 数={len(clusters)}")

        return {
            "assembly_id": uuid_bytes_to_str(assembly_id),
            "assembly_name": assembly_name,
            "nodes": nodes,
            "mode": "flat-split-signature",
            "cluster_count": len(clusters)
        }

    def _import_single(self, shape: TopoDS_Shape, assembly_name: str, assembly_id: bytes):
        canon_shape = _pca_align(shape) if (USE_PCA and NP_AVAILABLE) else _canonical_basic(shape)
        step_bytes = _export_shape_to_step_bytes(canon_shape, ".__sig_single__.step")
        sha = hashlib.sha256(step_bytes).hexdigest()
        part_key = f"{assembly_name.lower().replace(' ', '_')}.{sha[:8]}"
        part_id = self.repo.ensure_part(
            key=part_key,
            name=assembly_name,
            category=None,
            tags=["import", "single", "signature"],
            description="Single signature import"
        )
        filename = f"{assembly_name}_{sha[:8]}.step"
        out_path = os.path.abspath(os.path.join(self.export_dir, filename))
        with open(out_path, "wb") as f:
            f.write(step_bytes)
        xmin,ymin,zmin,xmax,ymax,zmax = _bbox(canon_shape)
        bbox = {"xmin": xmin, "ymin": ymin, "zmin": zmin,
                "xmax": xmax, "ymax": ymax, "zmax": zmax}
        geom_id = self.repo.insert_geom_asset(
            uri=f"file://{out_path.replace(os.sep, '/')}",
            sha256_hex=sha,
            format_="step",
            units=os.getenv("UNITS", "mm"),
            bbox_json=bbox,
            meta_json={"import": True, "signature": True}
        )
        mass_props = _volume_props(canon_shape)
        pv_id = self._insert_part_version(
            part_id=part_id,
            version_no=1,
            geom_asset_id=geom_id,
            source_path=assembly_name,
            mass_props=mass_props
        )
        node_id = self._insert_assembly_node(
            assembly_id=assembly_id,
            part_version_id=pv_id,
            parent_id=None,
            name=assembly_name,
            pos=[0.0,0.0,0.0],
            quat=[1.0,0.0,0.0,0.0],
            source_path=assembly_name
        )
        return {
            "assembly_id": uuid_bytes_to_str(assembly_id),
            "assembly_name": assembly_name,
            "nodes": [{
                "path":[assembly_name],
                "part_key": part_key,
                "version_no":1,
                "assembly_node_id": uuid_bytes_to_str(node_id),
                "new_version_created": True
            }],
            "mode": "flat-single-signature",
            "cluster_count": 1
        }

    # ---------- DB helpers ----------
    def _insert_assembly(self, assembly_id: bytes, name: str, description: str):
        with self.repo._conn() as cn:
            cur = cn.cursor()
            cur.execute("INSERT INTO assemblies (id, name, description) VALUES (%s,%s,%s)",
                        (assembly_id, name, description))
            cn.commit()
        self.repo.publish_outbox(
            aggregate="assembly",
            aggregate_id=assembly_id,
            event_type="created",
            payload={"name": name, "description": description}
        )

    def _insert_part_version(self, part_id: bytes, version_no: int,
                             geom_asset_id: bytes, source_path: str,
                             mass_props: Dict[str, Any]) -> bytes:
        pv_id = uuid4_bytes()
        params_json = {"source_path": source_path, "import": True}
        com = mass_props.get("com")
        mass = mass_props.get("mass")
        inertia_diag = mass_props.get("inertia_diag")
        inertia_json = {"diag": inertia_diag} if inertia_diag else {}
        with self.repo._conn() as cn:
            cur = cn.cursor()
            cur.execute("""
                INSERT INTO part_versions
                  (id, part_id, version_no, params_json, cad_asset_id, mass,
                   com_x, com_y, com_z, inertia_json, meta_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                pv_id, part_id, version_no,
                json.dumps(params_json, ensure_ascii=False),
                geom_asset_id,
                mass if mass is not None else None,
                com[0] if com else None,
                com[1] if com else None,
                com[2] if com else None,
                json.dumps(inertia_json, ensure_ascii=False),
                json.dumps({"import": True}, ensure_ascii=False)
            ))
            cn.commit()
        self.repo.publish_outbox(
            aggregate="part_version",
            aggregate_id=pv_id,
            event_type="created",
            payload={
                "part_id": uuid_bytes_to_str(part_id),
                "version_no": version_no,
                "cad_asset_id": uuid_bytes_to_str(geom_asset_id),
                "source_path": source_path,
                "mass": mass,
                "com": com
            }
        )
        return pv_id

    def _insert_assembly_node(self, assembly_id: bytes, part_version_id: bytes,
                              parent_id: Optional[bytes], name: str,
                              pos: List[float], quat: List[float], source_path: str) -> bytes:
        node_id = uuid4_bytes()
        transform_json = {"pos": pos, "quat": quat}
        with self.repo._conn() as cn:
            cur = cn.cursor()
            cur.execute("""
                INSERT INTO assembly_nodes
                  (id, assembly_id, parent_id, part_version_id, name, transform_json, overrides_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                node_id, assembly_id, parent_id, part_version_id,
                name,
                json.dumps(transform_json, ensure_ascii=False),
                json.dumps({}, ensure_ascii=False)
            ))
            cn.commit()
        self.repo.publish_outbox(
            aggregate="assembly_node",
            aggregate_id=node_id,
            event_type="created",
            payload={
                "assembly_id": uuid_bytes_to_str(assembly_id),
                "part_version_id": uuid_bytes_to_str(part_version_id),
                "name": name,
                "transform_json": transform_json,
                "path": source_path
            }
        )
        return node_id