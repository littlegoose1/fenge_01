from __future__ import annotations
import os
from typing import Optional, Dict, Any
from mysql.connector import pooling

_POOL: Optional[pooling.MySQLConnectionPool] = None

def _mk_pool() -> pooling.MySQLConnectionPool:
    cfg = {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASS", ""),
        "database": os.getenv("DB_NAME", "equip_lib"),
        "autocommit": False,
        "charset": "utf8mb4",
        "collation": "utf8mb4_0900_ai_ci",
    }
    return pooling.MySQLConnectionPool(pool_name="equip_pool", pool_size=8, **cfg)

def get_conn():
    global _POOL
    if _POOL is None:
        _POOL = _mk_pool()
    return _POOL.get_connection()