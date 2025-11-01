import os
from dotenv import load_dotenv
load_dotenv()

import mysql.connector
from neo4j import GraphDatabase

def check_mysql():
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=os.getenv("DB_NAME", "equip_lib"),
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    conn.close()
    return True

def check_neo4j():
    drv = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASS", "")),
        max_connection_lifetime=300,
    )
    drv.verify_connectivity()
    with drv.session() as s:
        ok = s.run("RETURN 1 AS ok").single()["ok"]
        assert ok == 1
    drv.close()
    return True

if __name__ == "__main__":
    print("MySQL OK:", check_mysql())
    print("Neo4j  OK:", check_neo4j())