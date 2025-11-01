import os
from dotenv import load_dotenv
load_dotenv()

from src.db.neo4j_conn import get_driver
from src.db.mysql import get_conn
from src.db.util import bin_to_uuid

def main():
    drv = get_driver()

    # 读取装配、节点、接口、约束的最小字段
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, name FROM assemblies")
        asms = cur.fetchall()

        cur.execute("""
          SELECT an.id, an.assembly_id, an.name, an.part_version_id, an.transform_json
          FROM assembly_nodes an
        """); nodes = cur.fetchall()

        cur.execute("""
          SELECT ani.id, ani.node_id, ani.part_interface_id, ani.world_pose_json
          FROM assembly_node_interfaces ani
        """); nis = cur.fetchall()

        cur.execute("""
          SELECT id, assembly_id, a_node_interface_id, b_node_interface_id, `type`, params_json, active, priority
          FROM assembly_constraints
        """); cons = cur.fetchall()
    finally:
        cur.close(); conn.close()

    cypher_setup = """
    CREATE CONSTRAINT asm_id  IF NOT EXISTS FOR (n:Assembly) REQUIRE n.id IS UNIQUE;
    CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE;
    CREATE CONSTRAINT ni_id   IF NOT EXISTS FOR (n:NodeInterface) REQUIRE n.id IS UNIQUE;
    CREATE CONSTRAINT ac_id   IF NOT EXISTS FOR (n:AsmConstraint) REQUIRE n.id IS UNIQUE;
    """
    with drv.session() as s:
        for stmt in cypher_setup.strip().split(";"):
            if stmt.strip():
                s.run(stmt)

        for a in asms:
            s.run("MERGE (asm:Assembly {id:$id}) SET asm.name=$name",
                  id=bin_to_uuid(a["id"]), name=a["name"])

        for n in nodes:
            s.run("""
                MERGE (asm:Assembly {id:$asm_id})
                MERGE (node:Node {id:$id}) SET node.name=$name, node.transform=$tf
                MERGE (asm)-[:ASSEMBLY_HAS_NODE]->(node)
            """, asm_id=bin_to_uuid(n["assembly_id"]), id=bin_to_uuid(n["id"]),
                 name=n["name"], tf=n["transform_json"])

        for ni in nis:
            s.run("""
                MERGE (node:Node {id:$node_id})
                MERGE (ni:NodeInterface {id:$id}) SET ni.world_pose=$pose
                MERGE (node)-[:NODE_HAS_INTERFACE]->(ni)
            """, node_id=bin_to_uuid(ni["node_id"]),
                 id=bin_to_uuid(ni["id"]), pose=ni["world_pose_json"])

        for c in cons:
            s.run("""
                MERGE (c:AsmConstraint {id:$id}) SET c.type=$type, c.params=$params, c.active=$active, c.priority=$priority
                WITH c
                MATCH (a:NodeInterface {id:$a_id}), (b:NodeInterface {id:$b_id})
                MERGE (a)-[:CONSTRAINED_TO {constraint_id:$id, type:$type}]->(b)
            """, id=bin_to_uuid(c["id"]), type=c["type"], params=c["params_json"],
                 active=bool(c["active"]), priority=c["priority"],
                 a_id=bin_to_uuid(c["a_node_interface_id"]), b_id=bin_to_uuid(c["b_node_interface_id"]))

    print("OK: 已投影到 Neo4j，可在浏览器查看。")

if __name__ == "__main__":
    main()