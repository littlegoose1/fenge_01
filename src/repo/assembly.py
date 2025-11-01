from __future__ import annotations
from typing import Optional, Dict, Any
import json
from src.db.mysql import get_conn
from src.db.util import new_uuid, uuid_to_bin, bin_to_uuid
from src.repo.parts import list_part_interfaces
from src.util.pose import compose_pose
from src.db.outbox import emit_event

def create_assembly(name:str, desc:str="") -> str:
    aid = new_uuid()
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO assemblies(id,name,description) VALUES(%s,%s,%s)",
                    (uuid_to_bin(aid), name, desc))
        conn.commit()
        # Outbox
        emit_event("assembly", aid, "created", {"id": aid, "name": name})
        return aid
    finally:
        cur.close(); conn.close()

def add_node(assembly_id:str, part_version_id:str, name:str,
             transform:Dict[str,Any], parent_id:Optional[str]=None,
             overrides:Optional[Dict]=None) -> str:
    nid = new_uuid()
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
          "INSERT INTO assembly_nodes(id,assembly_id,parent_id,part_version_id,name,transform_json,overrides_json) "
          "VALUES(%s,%s,%s,%s,%s,%s,%s)",
          (uuid_to_bin(nid), uuid_to_bin(assembly_id),
           (uuid_to_bin(parent_id) if parent_id else None),
           uuid_to_bin(part_version_id), name, json.dumps(transform), json.dumps(overrides or {}))
        )
        conn.commit()
        # Outbox
        emit_event("node", nid, "created", {
            "id": nid, "assembly_id": assembly_id, "part_version_id": part_version_id,
            "name": name, "transform": transform
        })
        return nid
    finally:
        cur.close(); conn.close()

def instantiate_node_interfaces(node_id:str, part_version_id:str, node_transform:Dict[str,Any]) -> int:
    """
    将 part_version 的接口在装配节点上实例化：
    - 读取 part_interfaces
    - 计算每个接口在装配坐标系下的 world_pose
    - 插入 assembly_node_interfaces
    """
    interfaces = list_part_interfaces(part_version_id)
    if not interfaces:
        return 0

    conn = get_conn(); cur = conn.cursor()
    inserted = 0
    try:
        for pi in interfaces:
            # pose_local 可能是 dict（已在 list_part_interfaces 解码），此处再兜底一次
            pose_local = pi.get("pose_json")
            if isinstance(pose_local, (bytes, bytearray)):
                pose_local = pose_local.decode("utf-8")
            if isinstance(pose_local, str):
                try:
                    pose_local = json.loads(pose_local)
                except Exception:
                    pose_local = {"pos":[0,0,0], "quat":[1,0,0,0]}

            world_pose = compose_pose(node_transform, pose_local)
            niid = new_uuid()

            part_interface_id = pi["id"]
            # MySQL dict 游标返回 BINARY(16) 多为 bytes/memoryview；INSERT 可直接用 bytes
            if isinstance(part_interface_id, memoryview):
                part_interface_id_bytes = part_interface_id.tobytes()
            elif isinstance(part_interface_id, (bytes, bytearray)):
                part_interface_id_bytes = bytes(part_interface_id)
            else:
                # 若是 UUID 字符串
                part_interface_id_bytes = uuid_to_bin(part_interface_id)

            cur.execute(
                "INSERT INTO assembly_node_interfaces(id,node_id,part_interface_id,world_pose_json,overrides_json) "
                "VALUES(%s,%s,%s,%s,%s)",
                (uuid_to_bin(niid), uuid_to_bin(node_id), part_interface_id_bytes,
                 json.dumps(world_pose), json.dumps({}))
            )
            inserted += 1

            # Outbox（使用字符串 UUID）
            pi_uuid = (bin_to_uuid(part_interface_id_bytes)
                       if isinstance(part_interface_id_bytes, (bytes, bytearray)) else part_interface_id)
            emit_event("node_interface", niid, "created", {
                "id": niid, "node_id": node_id, "part_interface_id": pi_uuid,
                "world_pose": world_pose
            })

        conn.commit()
        return inserted
    finally:
        cur.close(); conn.close()

def add_constraint(assembly_id:str, a_node_iface_id:str, b_node_iface_id:str,
                   ctype:str, params:Dict[str,Any], expr:str="", active:bool=True, priority:int=0) -> str:
    cid = new_uuid()
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
          "INSERT INTO assembly_constraints(id,assembly_id,a_node_interface_id,b_node_interface_id,`type`,expr,params_json,active,priority) "
          "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
          (uuid_to_bin(cid), uuid_to_bin(assembly_id),
           uuid_to_bin(a_node_iface_id), uuid_to_bin(b_node_iface_id),
           ctype, expr, json.dumps(params), 1 if active else 0, priority)
        )
        conn.commit()
        # Outbox
        emit_event("constraint", cid, "created", {
            "id": cid, "assembly_id": assembly_id,
            "a_node_interface_id": a_node_iface_id, "b_node_interface_id": b_node_iface_id,
            "type": ctype, "params": params, "active": bool(active), "priority": priority
        })
        return cid
    finally:
        cur.close(); conn.close()