from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
import json
from mysql.connector import errors as mysql_errors
from src.db.mysql import get_conn
from src.db.util import new_uuid, uuid_to_bin, bin_to_uuid
from src.db.outbox import emit_event

# ---------- 基础查询 ----------

def get_part_id_by_key(key: str) -> Optional[str]:
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM parts WHERE `key`=%s", (key,))
        row = cur.fetchone()
        return bin_to_uuid(row[0]) if row else None
    finally:
        cur.close(); conn.close()

def get_part_version_id(part_id: str, version_no: int) -> Optional[str]:
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM part_versions WHERE part_id=%s AND version_no=%s",
            (uuid_to_bin(part_id), version_no)
        )
        row = cur.fetchone()
        return bin_to_uuid(row[0]) if row else None
    finally:
        cur.close(); conn.close()

def get_part_interface_id(part_version_id: str, key: str) -> Optional[str]:
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM part_interfaces WHERE part_version_id=%s AND `key`=%s",
            (uuid_to_bin(part_version_id), key)
        )
        row = cur.fetchone()
        return bin_to_uuid(row[0]) if row else None
    finally:
        cur.close(); conn.close()

# ---------- 幂等创建（存在则返回已有ID） ----------

def get_or_create_part(key:str, name:str, category:str="",
                       tags:Optional[List[str]]=None, desc:str="") -> str:
    existing = get_part_id_by_key(key)
    if existing:
        return existing

    pid = new_uuid()
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO parts(id,`key`,name,category,tags,description) VALUES(%s,%s,%s,%s,%s,%s)",
            (uuid_to_bin(pid), key, name, category, json.dumps(tags or []), desc)
        )
        conn.commit()
        # Outbox
        emit_event("part", pid, "created", {
            "id": pid, "key": key, "name": name, "category": category, "tags": tags or []
        })
        return pid
    except mysql_errors.IntegrityError:
        conn.rollback()
        found = get_part_id_by_key(key)
        if found:
            return found
        raise
    finally:
        cur.close(); conn.close()

def get_or_create_part_version(part_id:str, version_no:int, params:Dict[str,Any],
                               cad_asset_id:Optional[str]=None,
                               mass:Optional[float]=None, com:Optional[Tuple[float,float,float]]=None,
                               inertia:Optional[Dict]=None, meta:Optional[Dict]=None) -> str:
    existing = get_part_version_id(part_id, version_no)
    if existing:
        return existing

    pvid = new_uuid()
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO part_versions(id,part_id,version_no,params_json,cad_asset_id,mass,com_x,com_y,com_z,inertia_json,meta_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (uuid_to_bin(pvid), uuid_to_bin(part_id), version_no, json.dumps(params or {}),
             (uuid_to_bin(cad_asset_id) if cad_asset_id else None),
             mass, *(com or (None,None,None)), json.dumps(inertia or {}), json.dumps(meta or {}))
        )
        conn.commit()
        # Outbox
        emit_event("part_version", pvid, "created", {
            "id": pvid, "part_id": part_id, "version_no": version_no,
            "params": params or {}, "cad_asset_id": cad_asset_id, "mass": mass
        })
        return pvid
    except mysql_errors.IntegrityError:
        conn.rollback()
        found = get_part_version_id(part_id, version_no)
        if found:
            return found
        raise
    finally:
        cur.close(); conn.close()

def get_or_create_part_interface(part_version_id:str, key:str, type:str,
                                 pose:Dict[str,Any], name:str="",
                                 geom:Optional[Dict]=None, strength:Optional[Dict]=None) -> str:
    existing = get_part_interface_id(part_version_id, key)
    if existing:
        return existing

    iid = new_uuid()
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO part_interfaces(id,part_version_id,`key`,name,`type`,pose_json,geom_json,strength_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (uuid_to_bin(iid), uuid_to_bin(part_version_id), key, name, type,
             json.dumps(pose), json.dumps(geom or {}), json.dumps(strength or {}))
        )
        conn.commit()
        # Outbox
        emit_event("part_interface", iid, "created", {
            "id": iid, "part_version_id": part_version_id,
            "key": key, "name": name, "type": type, "pose": pose, "geom": geom or {}
        })
        return iid
    except mysql_errors.IntegrityError:
        conn.rollback()
        found = get_part_interface_id(part_version_id, key)
        if found:
            return found
        raise
    finally:
        cur.close(); conn.close()

# ---------- 列表查询（将 JSON 列解码为 dict） ----------

def list_part_interfaces(part_version_id:str) -> List[Dict[str,Any]]:
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, `key`, `type`, pose_json, geom_json FROM part_interfaces WHERE part_version_id=%s",
            (uuid_to_bin(part_version_id),)
        )
        rows = cur.fetchall() or []
        for r in rows:
            pj = r.get("pose_json")
            if isinstance(pj, (bytes, bytearray)):
                pj = pj.decode("utf-8")
            if isinstance(pj, str):
                try:
                    r["pose_json"] = json.loads(pj)
                except Exception:
                    r["pose_json"] = {"pos":[0,0,0], "quat":[1,0,0,0]}
            gj = r.get("geom_json")
            if isinstance(gj, (bytes, bytearray)):
                gj = gj.decode("utf-8")
            if isinstance(gj, str):
                try:
                    r["geom_json"] = json.loads(gj)
                except Exception:
                    r["geom_json"] = {}
        return rows
    finally:
        cur.close(); conn.close()

# ---------- 兼容旧接口（包装到幂等版本） ----------

def create_part(key:str, name:str, category:str="",
                tags:Optional[List[str]]=None, desc:str="") -> str:
    """
    兼容旧代码：等价于 get_or_create_part
    """
    return get_or_create_part(key=key, name=name, category=category, tags=tags, desc=desc)

def create_part_version(part_id:str, version_no:int, params:Dict[str,Any],
                        cad_asset_id:Optional[str]=None,
                        mass:Optional[float]=None, com:Optional[Tuple[float,float,float]]=None,
                        inertia:Optional[Dict]=None, meta:Optional[Dict]=None) -> str:
    """
    兼容旧代码：等价于 get_or_create_part_version
    """
    return get_or_create_part_version(
        part_id=part_id, version_no=version_no, params=params,
        cad_asset_id=cad_asset_id, mass=mass, com=com, inertia=inertia, meta=meta
    )

def create_part_interface(part_version_id:str, key:str, type:str,
                          pose:Dict[str,Any], name:str="",
                          geom:Optional[Dict]=None, strength:Optional[Dict]=None) -> str:
    """
    兼容旧代码：等价于 get_or_create_part_interface
    """
    return get_or_create_part_interface(
        part_version_id=part_version_id, key=key, type=type,
        pose=pose, name=name, geom=geom, strength=strength
    )