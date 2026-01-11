"""
基于BOM的装配导入服务（完整版 - 修复对象生命周期）
不修改数据库表结构，使用现有字段存储扩展信息
"""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Compound
from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox

from .. services.solidworks_bom_extractor_auto import SolidWorksBOMExtractorAuto, SWBOMItem
from ..db.persistence_service import PersistenceService
from ..db.mysql import get_conn
from ..db.util import uuid_to_bin, bin_to_uuid, new_uuid


class AssemblyImportServiceBOM:
    """基于BOM的装配导入服务"""

    def __init__(self):
        self.persistence = PersistenceService()

    def import_assembly_from_bom(
        self,
        sldasm_path: str,
        assembly_name: Optional[str] = None,
        assembly_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        从装配文件导入并基于BOM入库

        Args:
            sldasm_path: . SLDASM文件路径
            assembly_name: 装配名称（可选，默认使用文件名）
            assembly_description: 装配描述（可选）

        Returns:
            导入结果字典
        """
        print("\n" + "="*70)
        print("📦 基于BOM的装配导入")
        print("="*70 + "\n")

        if not os.path.exists(sldasm_path):
            raise FileNotFoundError(f"文件不存在:  {sldasm_path}")

        # 默认装配名称
        if not assembly_name:
            assembly_name = os.path.splitext(os.path.basename(sldasm_path))[0]

        # 创建提取器实例
        bom_extractor = SolidWorksBOMExtractorAuto()

        try:
            # 1. 启动SolidWorks并打开文件
            print("🚀 启动SolidWorks...")
            if not bom_extractor.start_solidworks(visible=False):
                raise RuntimeError("无法启动SolidWorks")

            print(f"📂 打开装配:  {assembly_name}")
            if not bom_extractor.open_assembly(sldasm_path):
                raise RuntimeError("无法打开装配文件")

            # 2. 提取BOM
            print("\n📋 提取BOM...")
            bom_items = bom_extractor.extract_bom()

            if not bom_items:
                raise RuntimeError("BOM为空，无法导入")

            total_qty = sum(item.quantity for item in bom_items)
            print(f"✓ 提取到 {len(bom_items)} 种零件，共 {total_qty} 个实例")

            # 3. 创建装配记录
            print(f"\n💾 创建装配记录...")
            assembly_id = self._create_assembly_record(
                assembly_name,
                assembly_description,
                sldasm_path,
                bom_items
            )
            print(f"✓ 装配ID: {assembly_id[: 8]}...")

            # 4. 导入零件版本
            print(f"\n📦 导入零件版本...")
            part_versions = self._import_parts_from_bom(bom_items, sldasm_path)
            print(f"✓ 导入了 {len(part_versions)} 个零件版本")

            # 5. 创建装配节点
            print(f"\n🔗 创建装配节点...")
            nodes = self._create_assembly_nodes(
                assembly_id,
                bom_items,
                part_versions
            )
            print(f"✓ 创建了 {len(nodes)} 个装配节点")

            # 6. 生成结果
            result = {
                'assembly_id': assembly_id,
                'assembly_name': assembly_name,
                'total_parts':  len(bom_items),
                'total_quantity': total_qty,
                'part_versions': part_versions,
                'nodes': nodes,
                'source_file': sldasm_path,
                'import_mode':  'bom-based'
            }

            print(f"\n✅ 导入完成！")
            print(f"   装配:  {assembly_name}")
            print(f"   零件种类: {len(part_versions)}")
            print(f"   装配节点: {len(nodes)}")

            return result

        finally:
            # 清理
            try:
                bom_extractor.close_document()
                bom_extractor.quit_solidworks()
            except:
                pass

    def _create_assembly_record(
        self,
        name: str,
        description:  Optional[str],
        source_file: str,
        bom_items: List[SWBOMItem]
    ) -> str:
        """创建装配记录"""
        conn = get_conn()
        cur = conn.cursor()

        try:
            assembly_id = new_uuid()

            # 构建描述
            if description:
                full_description = description
            else:
                full_description = f"从 {os.path.basename(source_file)} 导入"

            full_description += f"\n[BOM导入模式 | 零件种类: {len(bom_items)} | 总数量: {sum(item.quantity for item in bom_items)}]"
            full_description += f"\n源文件: {source_file}"

            sql = """
                INSERT INTO assemblies (
                    id, name, description, created_at
                ) VALUES (%s, %s, %s, %s)
            """

            cur.execute(sql, (
                uuid_to_bin(assembly_id),
                name,
                full_description,
                datetime.now()
            ))

            conn.commit()
            return assembly_id

        finally:
            cur.close()
            conn.close()

    def _import_parts_from_bom(
        self,
        bom_items: List[SWBOMItem],
        assembly_path: str
    ) -> Dict[str, Dict[str, Any]]:
        """从BOM导入零件版本"""
        part_versions = {}

        for idx, item in enumerate(bom_items, 1):
            print(f"   [{idx}/{len(bom_items)}] {item.part_name}...")

            try:
                part_key = item.part_name

                # 检查是否已存在
                existing = self._get_existing_part_version(part_key)

                if existing:
                    print(f"      ✓ 使用现有版本 v{existing['version_no']}")
                    part_versions[item.part_name] = existing
                else:
                    # 创建新版本
                    version_info = self._create_part_version(
                        part_key,
                        item.part_name,
                        item
                    )
                    print(f"      ✓ 创建新版本 v{version_info['version_no']}")
                    part_versions[item.part_name] = version_info

            except Exception as e:
                print(f"      ⚠ 导入失败: {e}")
                import traceback
                traceback.print_exc()

        return part_versions

    def _get_existing_part_version(self, part_key: str) -> Optional[Dict[str, Any]]:
        """获取已存在的零件版本"""
        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        try:
            sql = """
                SELECT pv.id, pv.version_no, pv.part_id, p.`key` as part_key
                FROM part_versions pv
                JOIN parts p ON pv. part_id = p.id
                WHERE p.`key` = %s
                ORDER BY pv.version_no DESC
                LIMIT 1
            """

            cur.execute(sql, (part_key,))
            row = cur.fetchone()

            if row:
                return {
                    'part_key': row['part_key'],
                    'part_id': bin_to_uuid(row['part_id']),
                    'version_id': bin_to_uuid(row['id']),
                    'version_no': row['version_no']
                }

            return None

        finally:
            cur.close()
            conn.close()

    def _create_part_version(
        self,
        part_key: str,
        part_name: str,
        bom_item: SWBOMItem
    ) -> Dict[str, Any]:
        """创建零件版本"""

        # 参数快照
        params_snapshot = {
            'source':  'bom',
            'configuration': bom_item.configuration,
            'material': bom_item.material if bom_item.material else None,
            'bom_item_number': bom_item.item_number
        }

        # 元数据
        meta_json = {
            'from_bom': True,
            'configuration': bom_item.configuration,
            'import_date': datetime.now().isoformat()
        }

        # 创建占位形状
        shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()

        # 质量
        mass = bom_item.mass if bom_item.mass > 0 else None

        # 调用 persistence 服务
        result = self.persistence.persist_part_version(
            part_key=part_key,
            part_name=part_name,
            params_snapshot=params_snapshot,
            shape=shape,
            step_file_stub=f"{part_key}_bom",
            category="imported_from_bom",
            tags=[bom_item.configuration] if bom_item.configuration != "Default" else [],
            description=f"从BOM导入:  {part_name} (配置: {bom_item. configuration})",
            meta_asset={'from_bom': True, 'placeholder': True},
            meta_version=meta_json
        )

        # 使用正确的键名
        version_id = result['part_version_id']
        version_no = result['version_no']
        part_id = result['part_id']

        # 更新质量
        if mass:
            try:
                self._update_part_mass(version_id, mass)
            except Exception as e:
                print(f"      ⚠ 更新质量失败: {e}")

        return {
            'part_key': part_key,
            'part_id': part_id,
            'version_id': version_id,
            'version_no': version_no
        }

    def _update_part_mass(self, version_id: str, mass:  float):
        """更新零件版本的质量"""
        conn = get_conn()
        cur = conn.cursor()

        try:
            sql = """
                UPDATE part_versions
                SET mass = %s
                WHERE id = %s
            """
            cur.execute(sql, (mass, uuid_to_bin(version_id)))
            conn.commit()
        except Exception as e:
            print(f"      ⚠ 更新质量失败: {e}")
        finally:
            cur.close()
            conn.close()

    def _create_assembly_nodes(
        self,
        assembly_id: str,
        bom_items: List[SWBOMItem],
        part_versions: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """创建装配节点"""
        conn = get_conn()
        cur = conn.cursor()

        nodes = []

        try:
            for item in bom_items:
                version_info = part_versions.get(item.part_name)

                if not version_info:
                    print(f"   ⚠ 跳过 {item.part_name}（无版本信息）")
                    continue

                # 为每个实例创建节点
                for instance_idx in range(item.quantity):
                    node_id = new_uuid()
                    node_name = f"{item.part_name}-{instance_idx + 1}"

                    # 默认变换
                    transform = {
                        'pos': [0.0, 0.0, 0.0],
                        'quat': [1.0, 0.0, 0.0, 0.0]
                    }

                    sql = """
                        INSERT INTO assembly_nodes (
                            id, assembly_id, part_version_id,
                            name, transform_json, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                    """

                    cur.execute(sql, (
                        uuid_to_bin(node_id),
                        uuid_to_bin(assembly_id),
                        uuid_to_bin(version_info['version_id']),
                        node_name,
                        json.dumps(transform),
                        datetime. now()
                    ))

                    nodes.append({
                        'node_id':  node_id,
                        'part_name': item.part_name,
                        'instance':  instance_idx + 1,
                        'version_no': version_info['version_no']
                    })

            conn.commit()
            return nodes

        finally:
            cur.close()
            conn.close()

    def print_import_summary(self, result: Dict[str, Any]):
        """打印导入摘要"""
        print("\n" + "="*70)
        print("📊 导入摘要")
        print("="*70)

        print(f"装配名称: {result['assembly_name']}")
        print(f"装配ID: {result['assembly_id'][:8]}...")
        print(f"导入模式: {result['import_mode']}")
        print(f"\n零件统计:")
        print(f"  种类: {result['total_parts']}")
        print(f"  总数:  {result['total_quantity']}")
        print(f"  节点:  {len(result['nodes'])}")

        print("\n零件版本:")
        items = list(result['part_versions'].items())
        for part_name, version_info in items[: 10]:
            print(f"  • {part_name}: v{version_info['version_no']}")

        if len(items) > 10:
            print(f"  ...  还有 {len(items) - 10} 个零件")

        print("="*70 + "\n")