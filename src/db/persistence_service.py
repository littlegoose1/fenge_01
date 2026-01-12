import os
import json
import hashlib
from typing import Optional, Dict, Any

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core. Bnd import Bnd_Box

# -------- 兼容层：BRepBndLib Add --------
try:
    from OCC.Core.BRepBndLib import Add as _bnd_add      # 新版
except ImportError:
    try:
        from OCC.Core.BRepBndLib import brepbndlib_Add as _bnd_add  # 旧版（OCCT 7.9 常见）
    except ImportError:
        _bnd_add = None  # 极端情况：无法计算包围盒

from . mysql_repo import MySQLRepo
from .uuid_util import uuid_bytes_to_str


def _ensure_dir(d: str):
    os.makedirs(d, exist_ok=True)


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f. read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_bbox(shape: TopoDS_Shape) -> Dict[str, float]:
    if _bnd_add is None:
        return {}
    box = Bnd_Box()
    box.SetGap(0.0)
    # 兼容不同签名：有的旧版本不接受第三个参数
    try:
        _bnd_add(shape, box, True)
    except TypeError:
        try:
            _bnd_add(shape, box, 1)
        except TypeError:
            _bnd_add(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "xmin": float(xmin), "ymin": float(ymin), "zmin": float(zmin),
        "xmax": float(xmax), "ymax": float(ymax), "zmax": float(zmax)
    }


class PersistenceService:
    def __init__(self, repo: Optional[MySQLRepo] = None,
                 export_dir: Optional[str] = None,
                 units: Optional[str] = None):
        self.repo = repo or MySQLRepo()
        self.export_dir = export_dir or os.getenv("EXPORT_DIR", "exports")
        self.units = units or os.getenv("UNITS", "mm")
        _ensure_dir(self.export_dir)

    def _export_shape_to_step(self, shape: TopoDS_Shape, out_path: str) -> bool:
        """导出形状为STEP文件"""
        try:
            writer = STEPControl_Writer()
            Interface_Static.SetCVal("write. step. schema", "AP214")
            status = writer.Transfer(shape, STEPControl_AsIs)
            if status != IFSelect_RetDone:
                return False
            status = writer.Write(out_path)
            return status == IFSelect_RetDone
        except Exception as e:
            print(f"导出STEP失败: {e}")
            return False

    def persist_part_version(
        self,
        *,
        part_key: str,
        part_name: str,
        params_snapshot: Dict[str, Any],
        shape: TopoDS_Shape,
        step_file_stub: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list] = None,
        description: Optional[str] = None,
        meta_asset: Optional[Dict[str, Any]] = None,
        meta_version: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        part_id = self.repo.ensure_part(
            key=part_key, name=part_name,
            category=category, tags=tags, description=description
        )
        version_no = self.repo.next_version_no(part_id)

        safe_stub = step_file_stub or part_key.replace("/", "_")
        filename = f"{safe_stub}_v{version_no}.step"
        out_path = os.path. abspath(os.path.join(self.export_dir, filename))
        ok = self._export_shape_to_step(shape, out_path)
        if not ok:
            raise RuntimeError(f"导出 STEP 失败: {out_path}")

        bbox = _compute_bbox(shape)
        sha256_hex = _sha256_of_file(out_path)
        uri = f"file://{out_path.replace(os. sep, '/')}"
        cad_asset_id = self. repo.insert_geom_asset(
            uri=uri,
            sha256_hex=sha256_hex,
            format_="step",
            units=self. units,
            bbox_json=bbox,
            meta_json=meta_asset or {}
        )

        part_version_id = self.repo.insert_part_version(
            part_id=part_id,
            version_no=version_no,
            params_json=params_snapshot or {},
            cad_asset_id=cad_asset_id,
            mass=None,
            com_xyz=None,
            inertia_json=None,
            meta_json=meta_version or {},
        )

        self.repo.publish_outbox(
            aggregate="part_version",
            aggregate_id=part_version_id,
            event_type="created",
            payload={
                "part_id": uuid_bytes_to_str(part_id),
                "part_version_id": uuid_bytes_to_str(part_version_id),
                "version_no": version_no,
                "cad_asset_id": uuid_bytes_to_str(cad_asset_id),
                "uri": uri,
                "format": "step",
                "units": self.units,
                "params_json": params_snapshot,
                "bbox_json": bbox,
            },
        )

        return {
            "part_id": uuid_bytes_to_str(part_id),
            "part_version_id": uuid_bytes_to_str(part_version_id),
            "cad_asset_id": uuid_bytes_to_str(cad_asset_id),
            "version_no":  version_no,
            "step_path": out_path,
            "uri": uri,
            "sha256": sha256_hex,
            "bbox": bbox,
        }