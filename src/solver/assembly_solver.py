from __future__ import annotations
from typing import Dict, Any, List, Tuple
import math
import json
import numpy as np

from src.db.mysql import get_conn
from src.db.util import uuid_to_bin, bin_to_uuid
from src.util.pose import compose_pose
from src.db.outbox import emit_event

# --------- 数学工具 ---------

def _np(v) -> np.ndarray:
    return np.array(v, dtype=float)

def _clamp(x: float, lo=-1.0, hi=1.0) -> float:
    return max(lo, min(hi, x))

def quat_mul(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    w1,x1,y1,z1 = q1; w2,x2,y2,z2 = q2
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2
    ], dtype=float)

def quat_conj(q: np.ndarray) -> np.ndarray:
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=float)

def quat_from_two_vectors(v_from: np.ndarray, v_to: np.ndarray) -> np.ndarray:
    a = v_from / (np.linalg.norm(v_from) + 1e-15)
    b = v_to   / (np.linalg.norm(v_to) + 1e-15)
    dot = _clamp(float(np.dot(a, b)))
    if dot > 0.999999:
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
    if dot < -0.999999:
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        axis = axis / (np.linalg.norm(axis) + 1e-15)
        return np.array([0.0, axis[0], axis[1], axis[2]], dtype=float)  # 180°
    axis = np.cross(a, b)
    s = math.sqrt((1.0 + dot) * 2.0)
    invs = 1.0 / s
    q = np.array([s * 0.5, axis[0]*invs, axis[1]*invs, axis[2]*invs], dtype=float)
    return q / (np.linalg.norm(q) + 1e-15)

def rot(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    qv = np.array([0.0, v[0], v[1], v[2]], dtype=float)
    return (quat_mul(quat_mul(q, qv), quat_conj(q)))[1:]

Z_AXIS = np.array([0.0, 0.0, 1.0], dtype=float)

# --------- JSON/DB 工具 ---------

def _json_load(x):
    if isinstance(x, (bytes, bytearray, memoryview)):
        x = bytes(x).decode("utf-8")
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return {}
    return x if isinstance(x, dict) else {}

def _pose_equal(a: Dict[str,Any], b: Dict[str,Any], eps=1e-9) -> bool:
    try:
        ap = np.array(a["pos"], float); aq = np.array(a["quat"], float)
        bp = np.array(b["pos"], float); bq = np.array(b["quat"], float)
        return np.allclose(ap, bp, atol=eps) and np.allclose(aq, bq, atol=eps)
    except Exception:
        return False

# --------- 数据访问 ---------

def fetch_active_constraints(assembly_id: str) -> List[Dict[str, Any]]:
    sql = """
    SELECT
      ac.id,
      ac.`type`,
      ac.params_json,
      ac.a_node_interface_id, ac.b_node_interface_id,
      ani_a.node_id AS a_node_id, ani_b.node_id AS b_node_id,
      ani_a.world_pose_json AS a_world_pose,
      ani_b.world_pose_json AS b_world_pose
    FROM assembly_constraints ac
    JOIN assembly_node_interfaces ani_a ON ani_a.id = ac.a_node_interface_id
    JOIN assembly_node_interfaces ani_b ON ani_b.id = ac.b_node_interface_id
    WHERE ac.assembly_id = %s AND ac.active = 1
    ORDER BY ac.priority ASC, ac.created_at ASC
    """
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, (uuid_to_bin(assembly_id),))
        rows = cur.fetchall() or []
        for r in rows:
            r["params_json"]  = _json_load(r["params_json"])
            r["a_world_pose"] = _json_load(r.get("a_world_pose"))
            r["b_world_pose"] = _json_load(r.get("b_world_pose"))
            for k in ("id","a_node_interface_id","b_node_interface_id","a_node_id","b_node_id"):
                if isinstance(r.get(k), (bytes, bytearray, memoryview)):
                    r[k] = bin_to_uuid(r[k])
        return rows
    finally:
        cur.close(); conn.close()

def fetch_node_transform(node_id: str) -> Dict[str,Any]:
    sql = "SELECT transform_json FROM assembly_nodes WHERE id=%s"
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(sql, (uuid_to_bin(node_id),))
        row = cur.fetchone()
        return _json_load(row[0]) if row else {"pos":[0,0,0], "quat":[1,0,0,0]}
    finally:
        cur.close(); conn.close()

def update_node_transform(node_id: str, transform: Dict[str,Any]) -> Tuple[bool, Dict[str,Any], Dict[str,Any]]:
    old_tf = fetch_node_transform(node_id)
    if _pose_equal(old_tf, transform):
        return (False, old_tf, transform)
    sql = "UPDATE assembly_nodes SET transform_json=%s WHERE id=%s"
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(sql, (json.dumps(transform), uuid_to_bin(node_id)))
        conn.commit()
        return (cur.rowcount > 0, old_tf, transform)
    finally:
        cur.close(); conn.close()

def refresh_node_interfaces(node_id: str) -> List[Dict[str, Any]]:
    """
    用当前节点位姿刷新该节点的接口实例 world_pose。
    返回列表：[{id, node_id, part_interface_id, world_pose}, ...]（UUID 字符串）
    """
    node_tf = fetch_node_transform(node_id)
    sql = """
    SELECT ani.id AS ni_id, ani.part_interface_id AS pi_id, pi.pose_json AS pose_local
    FROM assembly_node_interfaces ani
    JOIN part_interfaces pi ON pi.id = ani.part_interface_id
    WHERE ani.node_id = %s
    """
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    out: List[Dict[str, Any]] = []
    try:
        cur.execute(sql, (uuid_to_bin(node_id),))
        rows = cur.fetchall() or []
        for r in rows:
            pose_local = _json_load(r["pose_local"])
            world_pose = compose_pose(node_tf, pose_local)

            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE assembly_node_interfaces SET world_pose_json=%s WHERE id=%s",
                (json.dumps(world_pose), r["ni_id"])
            )
            cur2.close()

            ni_uuid = bin_to_uuid(r["ni_id"]) if isinstance(r["ni_id"], (bytes, bytearray, memoryview)) else r["ni_id"]
            pi_uuid = bin_to_uuid(r["pi_id"]) if isinstance(r["pi_id"], (bytes, bytearray, memoryview)) else r["pi_id"]
            out.append({
                "id": ni_uuid,
                "node_id": node_id,
                "part_interface_id": pi_uuid,
                "world_pose": world_pose
            })
        conn.commit()
        return out
    finally:
        cur.close(); conn.close()

def fetch_interface_local_pose(node_interface_id: str) -> Dict[str,Any]:
    sql = """
    SELECT pi.pose_json
    FROM assembly_node_interfaces ani
    JOIN part_interfaces pi ON pi.id = ani.part_interface_id
    WHERE ani.id = %s
    """
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(sql, (uuid_to_bin(node_interface_id),))
        row = cur.fetchone()
        return _json_load(row[0]) if row else {"pos":[0,0,0], "quat":[1,0,0,0]}
    finally:
        cur.close(); conn.close()

# --------- 约束算子 ---------

def solve_distance(a_pose: Dict[str,Any], b_pose: Dict[str,Any], params: Dict[str,Any],
                   b_node_tf: Dict[str,Any]) -> Dict[str,Any]:
    target = float(params.get("target", 0.0))
    along = params.get("along", "normal")
    pa = _np(a_pose["pos"]); qa = _np(a_pose["quat"])
    pb = _np(b_pose["pos"])
    if along == "normal":
        n = rot(qa, Z_AXIS)
    elif along == "vector":
        v = _np(params.get("vector", [0,0,1]))
        n = v / (np.linalg.norm(v) + 1e-15)
    else:
        n = rot(qa, Z_AXIS)
    d = float(np.dot(pb - pa, n))
    delta = (target - d) * n
    pos = _np(b_node_tf["pos"]) + delta
    return {"pos": pos.tolist(), "quat": b_node_tf["quat"]}

def solve_mate(a_pose: Dict[str,Any], b_pose: Dict[str,Any],
               b_node_tf: Dict[str,Any], b_iface_local: Dict[str,Any]) -> Dict[str,Any]:
    pa = _np(a_pose["pos"]); qa = _np(a_pose["quat"])
    pb = _np(b_pose["pos"]); qb = _np(b_pose["quat"])
    nA = rot(qa, Z_AXIS)
    nB = rot(qb, Z_AXIS)
    # 旋转对齐法向
    q_align = quat_from_two_vectors(nB, nA)
    q_node_old = _np(b_node_tf["quat"])
    q_node_rot = quat_mul(q_align, q_node_old)
    node_rot_tf = {"pos": b_node_tf["pos"], "quat": q_node_rot.tolist()}
    # 旋转后的接口世界位置
    b_pose_rot = compose_pose(node_rot_tf, b_iface_local)
    pb_rot = _np(b_pose_rot["pos"])
    # 平移贴合
    delta = pa - pb_rot
    pos_new = _np(b_node_tf["pos"]) + delta
    return {"pos": pos_new.tolist(), "quat": q_node_rot.tolist()}

# --------- 求解主流程 ---------

class AssemblySolver:
    def __init__(self, iterations: int = 1):
        self.iterations = max(1, iterations)

    def solve(self, assembly_id: str) -> None:
        total_constraints = 0
        total_node_updates = 0
        for it in range(self.iterations):
            constraints = fetch_active_constraints(assembly_id)
            if not constraints:
                print(f"[solver] assembly={assembly_id} 无激活约束，跳过")
                break
            print(f"[solver] iteration {it+1}, constraints={len(constraints)}")
            for c in constraints:
                total_constraints += 1
                ctype = c["type"]; params = c["params_json"]
                a_pose = c["a_world_pose"]; b_pose = c["b_world_pose"]
                b_node_id = c["b_node_id"]
                b_node_tf = fetch_node_transform(b_node_id)

                if ctype == "distance":
                    b_new = solve_distance(a_pose, b_pose, params, b_node_tf)
                elif ctype == "mate":
                    b_local = fetch_interface_local_pose(c["b_node_interface_id"])
                    b_new = solve_mate(a_pose, b_pose, b_node_tf, b_local)
                else:
                    continue

                changed, _, new_tf = update_node_transform(b_node_id, b_new)
                if changed:
                    total_node_updates += 1
                    # 节点更新事件
                    emit_event("node", b_node_id, "updated", {"id": b_node_id, "transform": new_tf})
                    # 刷新节点接口并逐条发 updated 事件（让 Neo4j 同步 world_pos/world_quat）
                    refreshed = refresh_node_interfaces(b_node_id)
                    for ni in refreshed:
                        emit_event("node_interface", ni["id"], "updated", ni)
                    print(f"[solver] node {b_node_id} updated; interfaces refreshed={len(refreshed)}")
                else:
                    print(f"[solver] node {b_node_id} unchanged (no-op)")

        print(f"[solver] 完成: assembly={assembly_id}, iterations={self.iterations}, "
              f"constraints={total_constraints}, node_updates={total_node_updates}")