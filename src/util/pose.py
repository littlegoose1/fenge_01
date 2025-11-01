from __future__ import annotations
from typing import Dict, Sequence, Any
import numpy as np
import json

def quat_mul(q1: Sequence[float], q2: Sequence[float]):
    w1,x1,y1,z1 = q1; w2,x2,y2,z2 = q2
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2
    ], dtype=float)

def quat_conj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=float)

def rot(q, v):
    # 旋转向量 v by 四元数 q
    qv = np.array([0.0, v[0], v[1], v[2]], dtype=float)
    return (quat_mul(quat_mul(q, qv), quat_conj(q)))[1:]

def _to_pose_dict(p: Any) -> Dict[str, Any]:
    if isinstance(p, dict):
        return p
    if isinstance(p, (bytes, bytearray)):
        try:
            p = p.decode("utf-8")
        except Exception:
            return {"pos":[0,0,0], "quat":[1,0,0,0]}
    if isinstance(p, str):
        try:
            return json.loads(p)
        except Exception:
            return {"pos":[0,0,0], "quat":[1,0,0,0]}
    # 兜底
    return {"pos":[0,0,0], "quat":[1,0,0,0]}

def compose_pose(node_tf: Dict, iface_local: Dict) -> Dict:
    # 容错处理：允许传入字符串/bytes JSON
    node_tf = _to_pose_dict(node_tf)
    iface_local = _to_pose_dict(iface_local)

    pn = np.array(node_tf["pos"], dtype=float)
    qn = np.array(node_tf["quat"], dtype=float)
    pl = np.array(iface_local["pos"], dtype=float)
    ql = np.array(iface_local["quat"], dtype=float)
    pw = pn + rot(qn, pl)
    qw = quat_mul(qn, ql)
    return {"pos": pw.tolist(), "quat": qw.tolist()}