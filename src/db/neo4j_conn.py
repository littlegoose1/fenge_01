from __future__ import annotations
import os
from typing import Optional
from neo4j import GraphDatabase, Driver

_DRIVER: Optional[Driver] = None

def get_driver() -> Driver:
    global _DRIVER
    if _DRIVER is None:
        uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        pwd  = os.getenv("NEO4J_PASS", "")
        _DRIVER = GraphDatabase.driver(uri, auth=(user, pwd), max_connection_pool_size=20)
        _DRIVER.verify_connectivity()
    return _DRIVER