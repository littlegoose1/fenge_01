import os
import json
import time
from typing import Dict, Any, List
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

from src.db.mysql import get_conn
from src.db.util import bin_to_uuid

load_dotenv()

# ---- Neo4j 连接 ----
URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASS = os.getenv("NEO4J_PASS", "")
driver: Driver = GraphDatabase.driver(URI, auth=(USER, PASS))

# ---- MERGE 模板（OPTIONAL MATCH 放在 FOREACH 前；属性使用扁平/JSON 字符串） ----
CYPHERS = {
  "part": """
    MERGE (p:Part {id:$id})
      SET p.key=$key, p.name=$name, p.category=$category, p.tags=$tags
  """,
  "part_version": """
    MERGE (pv:PartVersion {id:$id})
      SET pv.version_no=$version_no, pv.params_json=$params_json, pv.mass=$mass
    WITH pv, $part_id AS partId, $cad_asset_id AS cadId
    OPTIONAL MATCH (p:Part {id:partId})
    FOREACH (_ IN CASE WHEN partId IS NULL OR p IS NULL THEN [] ELSE [1] END |
      MERGE (p)-[:PART_HAS_VERSION]->(pv)
    )
    FOREACH (_ IN CASE WHEN cadId IS NULL THEN [] ELSE [1] END |
      MERGE (ga:GeomAsset {id:cadId})
      MERGE (pv)-[:HAS_GEOM {kind:'cad'}]->(ga)
    )
  """,
  "part_interface": """
    MERGE (pi:PartInterface {id:$id})
      SET pi.key=$key, pi.name=$name, pi.type=$type,
          pi.local_pos=$local_pos, pi.local_quat=$local_quat,
          pi.geom_json=$geom_json
    WITH pi, $part_version_id AS pvId
    OPTIONAL MATCH (pv:PartVersion {id:pvId})
    FOREACH (_ IN CASE WHEN pvId IS NULL OR pv IS NULL THEN [] ELSE [1] END |
      MERGE (pv)-[:VERSION_HAS_INTERFACE]->(pi)
    )
  """,
  "assembly": """
    MERGE (asm:Assembly {id:$id})
      SET asm.name=$name
  """,
  "node": """
    MERGE (node:Node {id:$id})
      SET node.name=COALESCE($name, node.name),
          node.pos=$pos,
          node.quat=$quat
    WITH node, $assembly_id AS asmId, $part_version_id AS pvId
    OPTIONAL MATCH (asm:Assembly {id:asmId})
    OPTIONAL MATCH (pv:PartVersion {id:pvId})
    FOREACH (_ IN CASE WHEN asmId IS NULL OR asm IS NULL THEN [] ELSE [1] END |
      MERGE (asm)-[:ASSEMBLY_HAS_NODE]->(node)
    )
    FOREACH (_ IN CASE WHEN pvId IS NULL OR pv IS NULL THEN [] ELSE [1] END |
      MERGE (node)-[:NODE_USES_VERSION]->(pv)
    )
  """,
  "node_interface": """
    MERGE (ni:NodeInterface {id:$id})
      SET ni.world_pos=$world_pos, ni.world_quat=$world_quat
    WITH ni, $node_id AS nodeId, $part_interface_id AS piId
    OPTIONAL MATCH (node:Node {id:nodeId})
    OPTIONAL MATCH (pi:PartInterface {id:piId})
    FOREACH (_ IN CASE WHEN nodeId IS NULL OR node IS NULL THEN [] ELSE [1] END |
      MERGE (node)-[:NODE_HAS_INTERFACE]->(ni)
    )
    FOREACH (_ IN CASE WHEN piId IS NULL OR pi IS NULL THEN [] ELSE [1] END |
      MERGE (ni)-[:INSTANCE_OF]->(pi)
    )
  """,
  "constraint": """
    MERGE (c:AsmConstraint {id:$id})
      SET c.type=$type, c.params_json=$params_json, c.active=$active, c.priority=$priority
    WITH c, $a_node_interface_id AS aId, $b_node_interface_id AS bId, $type AS ctype
    OPTIONAL MATCH (a:NodeInterface {id:aId})
    OPTIONAL MATCH (b:NodeInterface {id:bId})
    FOREACH (_ IN CASE WHEN aId IS NULL OR bId IS NULL OR a IS NULL OR b IS NULL THEN [] ELSE [1] END |
      MERGE (a)-[:CONSTRAINED_TO {constraint_id:$id, type:ctype}]->(b)
    )
  """
}

def fetch_events(limit=100) -> List[Dict[str, Any]]:
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, aggregate, aggregate_id, event_type, payload_json
            FROM outbox_events
            WHERE processed_at IS NULL
            ORDER BY id ASC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall() or []
        events = []
        for (eid, agg, agg_id, etype, payload) in rows:
            events.append({
                "id": eid,
                "aggregate": agg,
                "aggregate_id": bin_to_uuid(agg_id),
                "event_type": etype,
                "payload": json.loads(payload)
            })
        return events
    finally:
        cur.close(); conn.close()

def mark_processed(eid: int):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("UPDATE outbox_events SET processed_at=NOW() WHERE id=%s", (eid,))
        conn.commit()
    finally:
        cur.close(); conn.close()

def _as_array(x, n=None):
    if x is None:
        return None
    arr = list(x)
    if n is not None and len(arr) != n:
        return [0.0, 0.0, 0.0] if n == 3 else [1.0, 0.0, 0.0, 0.0]
    return [float(v) for v in arr]

def normalize_payload(agg: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    为每个 aggregate 统一补齐 Cypher 会用到的参数，避免 ParameterMissing。
    同时把嵌套 Map 按需要展开/序列化。
    """
    p = dict(payload)

    if agg == "part":
        p.setdefault("name", None)
        p.setdefault("key", None)
        p.setdefault("category", None)
        p.setdefault("tags", [])
    elif agg == "part_version":
        # 展开可选字段
        params = p.pop("params", None)
        p["params_json"] = json.dumps(params, ensure_ascii=False) if params is not None else None
        p.setdefault("mass", None)
        p.setdefault("part_id", None)
        p.setdefault("cad_asset_id", None)
        p.setdefault("version_no", None)
    elif agg == "part_interface":
        pose = p.pop("pose", None)
        if pose:
            p["local_pos"]  = _as_array(pose.get("pos"), 3)
            p["local_quat"] = _as_array(pose.get("quat"), 4)
        p.setdefault("local_pos", None)
        p.setdefault("local_quat", None)
        geom = p.pop("geom", None)
        p["geom_json"] = json.dumps(geom, ensure_ascii=False) if geom is not None else None
        p.setdefault("name", None)
        p.setdefault("key", None)
        p.setdefault("type", None)
        p.setdefault("part_version_id", None)
    elif agg == "assembly":
        p.setdefault("name", None)
    elif agg == "node":
        tf = p.pop("transform", None)
        if tf:
            p["pos"]  = _as_array(tf.get("pos"), 3)
            p["quat"] = _as_array(tf.get("quat"), 4)
        p.setdefault("pos", None)
        p.setdefault("quat", None)
        p.setdefault("name", None)  # 关键：避免 COALESCE($name, ...) 缺参
        p.setdefault("assembly_id", None)
        p.setdefault("part_version_id", None)
    elif agg == "node_interface":
        wp = p.pop("world_pose", None)
        if wp:
            p["world_pos"]  = _as_array(wp.get("pos"), 3)
            p["world_quat"] = _as_array(wp.get("quat"), 4)
        p.setdefault("world_pos", None)
        p.setdefault("world_quat", None)
        p.setdefault("node_id", None)
        p.setdefault("part_interface_id", None)
    elif agg == "constraint":
        params = p.pop("params", None)
        p["params_json"] = json.dumps(params, ensure_ascii=False) if params is not None else None
        p.setdefault("type", None)
        p.setdefault("active", None)
        p.setdefault("priority", None)
        p.setdefault("a_node_interface_id", None)
        p.setdefault("b_node_interface_id", None)

    return p

def process_event(ev: Dict[str, Any]):
    agg = ev["aggregate"]
    raw = ev["payload"]
    cypher = CYPHERS.get(agg)
    if not cypher:
        return
    params = normalize_payload(agg, raw)
    # 每条事件独立 session，避免异常导致连接状态损坏
    with driver.session() as sess:
        sess.run(cypher, **params)

def init_constraints():
    with driver.session() as sess:
        sess.run("CREATE CONSTRAINT part_id IF NOT EXISTS FOR (n:Part) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT pv_id   IF NOT EXISTS FOR (n:PartVersion) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT pi_id   IF NOT EXISTS FOR (n:PartInterface) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT asm_id  IF NOT EXISTS FOR (n:Assembly) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT ni_id   IF NOT EXISTS FOR (n:NodeInterface) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT ac_id   IF NOT EXISTS FOR (n:AsmConstraint) REQUIRE n.id IS UNIQUE;")
        sess.run("CREATE CONSTRAINT ga_id   IF NOT EXISTS FOR (n:GeomAsset) REQUIRE n.id IS UNIQUE;")

def main_loop():
    init_constraints()
    while True:
        events = fetch_events()
        if not events:
            time.sleep(1.0)
            continue
        for ev in events:
            try:
                process_event(ev)
                mark_processed(ev["id"])
            except Exception as e:
                print("process_event error:", ev["id"], ev["aggregate"], e)

if __name__ == "__main__":
    main_loop()