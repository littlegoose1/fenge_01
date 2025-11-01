from __future__ import annotations
import json
from typing import Dict, Any
from src.db.mysql import get_conn
from src.db.util import uuid_to_bin

def emit_event(aggregate: str, aggregate_id: str, event_type: str, payload: Dict[str, Any]) -> int:
    """
    写一条 outbox 事件，供 Neo4j worker 消费。
    aggregate: 'part' | 'part_version' | 'part_interface' | 'assembly' | 'node' | 'node_interface' | 'constraint'
    event_type: 'created' | 'updated' | 'deleted'
    payload: 幂等 MERGE 所需的字段（JSON 可序列化）
    返回自增事件ID（可不使用）
    """
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO outbox_events(aggregate, aggregate_id, event_type, payload_json) VALUES(%s,%s,%s,%s)",
            (aggregate, uuid_to_bin(aggregate_id), event_type, json.dumps(payload or {}))
        )
        eid = cur.lastrowid
        conn.commit()
        return eid
    finally:
        cur.close(); conn.close()