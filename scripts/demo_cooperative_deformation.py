"""
演示协同变形与装配功能
展示3. 3.2节的核心算法
"""
import sys
import os
from dotenv import load_dotenv

load_dotenv()

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from src.assembly.topology_analyzer import TopologyAnalyzer
from src.assembly.cooperative_deformation import CooperativeDeformationEngine, DeformationConstraint
from src.assembly.collision_detector import CollisionDetector


def create_simple_assembly():
    """创建简单的测试装配"""
    # 底座：100x100x20的盒子
    base_shape = BRepPrimAPI_MakeBox(100, 100, 20).Shape()
    base_node = {
        'id': 'node_base',
        'name': '底座',
        'shape': base_shape,
        'transform': {'pos': [0, 0, 0], 'quat': [1, 0, 0, 0]}
    }

    # 立柱：圆柱 R=10, H=50
    pillar_shape = BRepPrimAPI_MakeCylinder(10, 50).Shape()
    pillar_node = {
        'id': 'node_pillar',
        'name': '立柱',
        'shape': pillar_shape,
        'transform': {'pos': [50, 50, 20], 'quat': [1, 0, 0, 0]}
    }

    # 顶板：80x80x10的盒子
    top_shape = BRepPrimAPI_MakeBox(80, 80, 10).Shape()
    top_node = {
        'id': 'node_top',
        'name': '顶板',
        'shape': top_shape,
        'transform': {'pos': [10, 10, 70], 'quat': [1, 0, 0, 0]}
    }

    return [base_node, pillar_node, top_node]


def demo_topology_analysis():
    """演示拓扑邻接分析"""
    print("=" * 60)
    print("演示1: 拓扑邻接分析")
    print("=" * 60)

    nodes = create_simple_assembly()
    analyzer = TopologyAnalyzer(contact_threshold=0.5)

    adjacency = analyzer.analyze_assembly(nodes)

    print(f"\n节点数量: {len(adjacency.node_ids)}")
    print(f"检测到的接触: {len(adjacency.contacts)}")

    print("\n邻接矩阵:")
    print(adjacency.matrix)

    print("\n接触详情:")
    for contact in adjacency.contacts:
        print(f"  {contact.node_a_id} <-> {contact.node_b_id}")
        print(f"    类型: {contact.contact_type}, 距离: {contact.distance:.4f}mm")
        print(f"    接触面积: {contact.contact_area:.2f}, 中心: {contact.center}")

    # 查找接触链
    chain = adjacency.get_contact_chain('node_base', 'node_top')
    if chain:
        print(f"\n从底座到顶板的接触链: {' -> '.join(chain)}")


def demo_cooperative_deformation():
    """演示协同几何变形"""
    print("\n" + "=" * 60)
    print("演示2: 协同几何变形")
    print("=" * 60)

    nodes = create_simple_assembly()
    engine = CooperativeDeformationEngine(stiffness=1.0, max_iterations=50)

    # 定义变形约束：将顶板向上移动10mm
    constraints = [
        DeformationConstraint(
            node_id='node_top',
            constraint_type='displacement',
            params={'displacement': [0, 0, 10]}
        ),
        DeformationConstraint(
            node_id='node_base',
            constraint_type='fixed',
            params={}
        )
    ]

    print("\n应用变形约束...")
    print(f"  约束1: 顶板向上移动10mm")
    print(f"  约束2: 底座固定")

    results = engine.propagate_deformation(nodes, constraints)

    print("\n变形结果:")
    for result in results:
        print(f"\n节点: {result.node_id}")
        print(f"  原始位置: {result.original_transform['pos']}")
        print(f"  变形后位置: {result.deformed_transform['pos']}")
        print(f"  变形能量: {result.energy:.6f}")


def demo_collision_detection():
    """演示碰撞检测"""
    print("\n" + "=" * 60)
    print("演示3: 碰撞检测与装配验证")
    print("=" * 60)

    # 创建有干涉的装配
    nodes = create_simple_assembly()

    # 人为制造干涉：将顶板下移
    nodes[2]['transform']['pos'] = [10, 10, 40]  # 原本70，现在40，与立柱干涉

    detector = CollisionDetector(
        penetration_threshold=-0.01,
        contact_threshold=0.1
    )

    print("\n执行碰撞检测...")
    collisions = detector.detect_collisions(nodes)

    print(f"\n检测到 {len(collisions)} 个碰撞:")
    for collision in collisions:
        print(f"\n  {collision.node_a_id} <-> {collision.node_b_id}")
        print(f"    类型: {collision.collision_type}")
        print(f"    干涉深度: {collision.depth:.4f}mm")
        print(f"    干涉体积: {collision.volume:.4f}mm³")
        print(f"    严重程度: {collision.severity:.2f}")

    # 装配验证
    print("\n" + "-" * 60)
    validation = detector.validate_assembly(nodes)

    print("装配验证报告:")
    print(f"  装配有效性: {'✓ 有效' if validation['is_valid'] else '✗ 无效'}")
    print(f"  总碰撞数: {validation['total_collisions']}")
    print(f"  干涉数: {validation['penetrations']}")
    print(f"  接触数: {validation['contacts']}")
    print(f"  最大严重度: {validation['max_severity']:.2f}")


def main():
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║  单兵装备数字化设计系统 - 3.3.2 协同变形与装配演示  ║")
    print("╚" + "═" * 58 + "╝")

    try:
        demo_topology_analysis()
        demo_cooperative_deformation()
        demo_collision_detection()

        print("\n" + "=" * 60)
        print("演示完成！所有功能正常运行。")
        print("=" * 60)

    except Exception as e:
        import traceback
        print(f"\n错误: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()