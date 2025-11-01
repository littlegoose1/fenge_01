import os, json
from dotenv import load_dotenv
load_dotenv()

from src.repo.parts import create_part, create_part_version, create_part_interface
from src.repo.assembly import create_assembly, add_node, instantiate_node_interfaces, add_constraint
from src.db.mysql import get_conn
from src.db.util import bin_to_uuid

def main():
    # 1) 准备两个零部件与版本
    part_a = create_part("demo.partA", "演示部件A", category="demo")
    pva = create_part_version(part_a, 1, params={"width":100, "height":50})
    # 定义两个接口：底面与顶面
    create_part_interface(pva, "MATE_BOTTOM", "plane_mate",
                          pose={"pos":[0,0,0], "quat":[1,0,0,0]}, name="底面")
    create_part_interface(pva, "MATE_TOP", "plane_mate",
                          pose={"pos":[0,0,50], "quat":[1,0,0,0]}, name="顶面")

    part_b = create_part("demo.partB", "演示部件B", category="demo")
    pvb = create_part_version(part_b, 1, params={"width":80, "height":30})
    create_part_interface(pvb, "MATE_BOTTOM", "plane_mate",
                          pose={"pos":[0,0,0], "quat":[1,0,0,0]}, name="底面")
    create_part_interface(pvb, "MATE_TOP", "plane_mate",
                          pose={"pos":[0,0,30], "quat":[1,0,0,0]}, name="顶面")

    # 2) 新建装配
    asm = create_assembly("演示装配1")

    # 3) 放置两个实例节点（A 在原点，B 初始在上方）
    node_a = add_node(asm, pva, "A实例", transform={"pos":[0,0,0],"quat":[1,0,0,0]})
    node_b = add_node(asm, pvb, "B实例", transform={"pos":[0,0,120],"quat":[1,0,0,0]})

    # 4) 实例化接口（根据节点位姿计算 world pose）
    # 需要从 DB 读出 transform_json 传入（此处手动与 add_node 保持一致）
    instantiate_node_interfaces(node_a, pva, {"pos":[0,0,0], "quat":[1,0,0,0]})
    instantiate_node_interfaces(node_b, pvb, {"pos":[0,0,120], "quat":[1,0,0,0]})

    # 5) 选择 A 的顶面与 B 的底面，建立 mate/距离约束（将 B 放到 A 顶面上）
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    try:
        # 取接口实例 ID
        cur.execute("""
          SELECT ani.id AS id, pi.`key` AS ikey, ani.node_id
          FROM assembly_node_interfaces ani
          JOIN part_interfaces pi ON pi.id = ani.part_interface_id
          WHERE ani.node_id IN (%s,%s)
        """, (bytes.fromhex(node_a.replace('-','')), bytes.fromhex(node_b.replace('-',''))))
        nis = cur.fetchall()
    finally:
        cur.close(); conn.close()

    aid_top = next(x["id"] for x in nis if x["node_id"] == bytes.fromhex(node_a.replace('-','')) and x["ikey"]=="MATE_TOP")
    bid_bottom = next(x["id"] for x in nis if x["node_id"] == bytes.fromhex(node_b.replace('-','')) and x["ikey"]=="MATE_BOTTOM")

    # 距离约束：让 B 的底面与 A 的顶面法向距离为 0
    add_constraint(asm, bin_to_uuid(aid_top), bin_to_uuid(bid_bottom),
                   ctype="distance", params={"target":0.0, "along":"normal"})

    print("OK: 装配/节点/接口/约束 已建立。可在 DB 中查看。")

if __name__ == "__main__":
    main()