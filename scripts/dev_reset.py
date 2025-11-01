import os
import sys
import argparse
from dotenv import load_dotenv
from neo4j import GraphDatabase

from src.db.mysql import get_conn

load_dotenv()

def reset_mysql():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SET FOREIGN_KEY_CHECKS=0;")
        tables = [
            "assembly_constraints",
            "assembly_node_interfaces",
            "assembly_nodes",
            "assemblies",
            "part_interfaces",
            "part_versions",
            "parts",
            "outbox_events",
        ]
        for t in tables:
            cur.execute(f"TRUNCATE TABLE {t};")
        cur.execute("SET FOREIGN_KEY_CHECKS=1;")
        conn.commit()
        print("[reset] MySQL tables truncated.")
    finally:
        cur.close(); conn.close()

def reset_neo4j():
    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd  = os.getenv("NEO4J_PASS", "")
    drv = GraphDatabase.driver(uri, auth=(user, pwd))
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n;")
        # 约束可按需重建，这里留给 outbox_worker 在启动时创建
    drv.close()
    print("[reset] Neo4j graph cleared.")

def main():
    ap = argparse.ArgumentParser(description="开发重置：清空 MySQL 业务数据 + 清空 Neo4j 图")
    ap.add_argument("--confirm", action="store_true", help="确认执行清空操作")
    args = ap.parse_args()
    if not args.confirm:
        print("保护机制：请加 --confirm 才会执行清空。示例：python scripts/dev_reset.py --confirm")
        sys.exit(1)
    # 提醒停掉 worker
    print("提示：请先停止正在运行的 outbox_worker（Ctrl+C）。")
    reset_mysql()
    reset_neo4j()
    print("完成。建议顺序：\n1) 启动 outbox_worker\n2) 运行 demo_build_assembly.py\n3) 运行 solve_assembly.py")

if __name__ == "__main__":
    main()