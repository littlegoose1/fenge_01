import os
import json
from typing import Optional, Tuple, Dict, Any

import mysql.connector
from mysql.connector import pooling

from .uuid_util import uuid4_bytes


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name, default)


class MySQLRepo:
    """
    与你的表结构（parts/part_versions/geom_assets/outbox_events）对齐的轻量仓储。
    - UUID 用 BINARY(16) bytes
    """
    def __init__(self):
        self.pool = pooling.MySQLConnectionPool(
            pool_name="cad_pool",
            pool_size=5,
            host=_env("MYSQL_HOST", "127.0.0.1"),
            port=int(_env("MYSQL_PORT", "3306")),
            user=_env("MYSQL_USER", "root"),
            password=_env("MYSQL_PASSWORD", ""),
            database=_env("MYSQL_DB", "equip_lib"),
            charset="utf8mb4",
            use_pure=True,
        )

    def _conn(self):
        return self.pool.get_connection()

    # parts
    def get_part_id_by_key(self, key: str) -> Optional[bytes]:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute("SELECT id FROM parts WHERE `key`=%s", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def ensure_part(self, *, key: str, name: str,
                    category: Optional[str] = None,
                    tags: Optional[list] = None,
                    description: Optional[str] = None) -> bytes:
        pid = self.get_part_id_by_key(key)
        if pid:
            # 同步基础信息（可按需关闭）
            with self._conn() as cn:
                cur = cn.cursor()
                cur.execute(
                    "UPDATE parts SET name=%s, category=%s, tags=%s, description=%s WHERE id=%s",
                    (name, category, json.dumps(tags or [], ensure_ascii=False), description, pid),
                )
                cn.commit()
            return pid

        new_id = uuid4_bytes()
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(
                "INSERT INTO parts (id, `key`, name, category, tags, description) VALUES (%s,%s,%s,%s,%s,%s)",
                (new_id, key, name, category, json.dumps(tags or [], ensure_ascii=False), description),
            )
            cn.commit()
        return new_id

    # part_versions
    def next_version_no(self, part_id: bytes) -> int:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute("SELECT COALESCE(MAX(version_no), 0) FROM part_versions WHERE part_id=%s", (part_id,))
            row = cur.fetchone()
            return int(row[0]) + 1

    def insert_part_version(
        self,
        *,
        part_id: bytes,
        version_no: int,
        params_json: Dict[str, Any],
        cad_asset_id: Optional[bytes],
        mass: Optional[float] = None,
        com_xyz: Optional[Tuple[float, float, float]] = None,
        inertia_json: Optional[Dict[str, Any]] = None,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        new_id = uuid4_bytes()
        px, py, pz = (com_xyz if com_xyz else (None, None, None))
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(
                """
                INSERT INTO part_versions
                  (id, part_id, version_no, params_json, cad_asset_id, mass, com_x, com_y, com_z, inertia_json, meta_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    new_id, part_id, version_no,
                    json.dumps(params_json or {}, ensure_ascii=False),
                    cad_asset_id,
                    mass, px, py, pz,
                    json.dumps(inertia_json or {}, ensure_ascii=False),
                    json.dumps(meta_json or {}, ensure_ascii=False),
                ),
            )
            cn.commit()
        return new_id

    # geom_assets
    def get_geom_asset_by_sha(self, sha256_hex: str) -> Optional[bytes]:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute("SELECT id FROM geom_assets WHERE sha256=%s", (sha256_hex,))
            row = cur.fetchone()
            return row[0] if row else None

    def insert_geom_asset(
        self,
        *,
        uri: str,
        sha256_hex: str,
        format_: str,
        units: str = "mm",
        bbox_json: Optional[Dict[str, float]] = None,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        exist = self.get_geom_asset_by_sha(sha256_hex)
        if exist:
            return exist
        new_id = uuid4_bytes()
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(
                """
                INSERT INTO geom_assets
                  (id, uri, sha256, format, units, bbox_json, meta_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    new_id, uri, sha256_hex, format_, units,
                    json.dumps(bbox_json or {}, ensure_ascii=False) if bbox_json else None,
                    json.dumps(meta_json or {}, ensure_ascii=False) if meta_json else None,
                ),
            )
            cn.commit()
        return new_id

    # outbox
    def publish_outbox(self, *, aggregate: str, aggregate_id: bytes, event_type: str, payload: Dict[str, Any]) -> int:
        with self._conn() as cn:
            cur = cn.cursor()
            cur.execute(
                """
                INSERT INTO outbox_events (aggregate, aggregate_id, event_type, payload_json)
                VALUES (%s,%s,%s,%s)
                """,
                (aggregate, aggregate_id, event_type, json.dumps(payload, ensure_ascii=False)),
            )
            cn.commit()
            return cur.lastrowid