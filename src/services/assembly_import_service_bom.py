"""
基于BOM的装配导入服务（完整版 - 导出真实STEP文件）
不修改数据库表结构，使用现有字段存储扩展信息
"""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Compound
from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone

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
        """从装配文件导入并基于BOM入库（使用宏批量导出STEP）"""

        print("\n" + "=" * 70)
        print("📦 基于BOM的装配导入（使用SolidWorks宏批量导出）")
        print("=" * 70 + "\n")

        if not os.path.exists(sldasm_path):
            raise FileNotFoundError(f"文件不存在:  {sldasm_path}")

        if not assembly_name:
            assembly_name = os.path.splitext(os.path.basename(sldasm_path))[0]

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

            # ✅ 3. 使用宏批量导出所有零件
            export_dir = os.getenv("EXPORT_DIR", "D:\\solidworks\\step")
            os.makedirs(export_dir, exist_ok=True)

            print(f"\n📤 使用SolidWorks宏批量导出零件到:  {export_dir}")

            # ✅ 修复：正确构建宏文件路径
            current_dir = os.path.dirname(os.path.abspath(__file__))  # src/services/
            project_root = os.path.dirname(os.path.dirname(current_dir))  # 项目根目录
            macro_path = os.path.join(project_root, "scripts", "ExportAllComponentsToSTEP.swp")

            # 调试输出
            print(f"   当前文件:  {__file__}")
            print(f"   当前目录: {current_dir}")
            print(f"   项目根目录: {project_root}")
            print(f"   宏文件路径:  {macro_path}")
            print(f"   宏文件存在: {os.path.exists(macro_path)}")

            exported_files = {}

            if os.path.exists(macro_path):
                # 运行宏
                print(f"   🔧 准备运行宏...")
                success = bom_extractor.run_macro(
                    macro_path,
                    "Macro1",  # ✅ 修改：使用 SolidWorks 默认的模块名
                    "main"  # 过程名
                )
                if success:
                    print(f"   ✓ 宏执行成功")

                    # 等待文件生成
                    import time
                    print(f"   ⏳ 等待文件生成 (3秒)...")
                    time.sleep(3)

                    # 扫描导出的文件
                    print(f"   🔍 扫描导出的STEP文件...")
                    for item in bom_items:
                        part_key = self._normalize_part_key(item.part_name)
                        step_file = os.path.join(export_dir, f"{part_key}_bom_v1.step")
                        if os.path.exists(step_file):
                            file_size = os.path.getsize(step_file)
                            print(f"      ✓ 找到: {part_key}_bom_v1.step ({file_size: ,} bytes)")
                            exported_files[part_key] = step_file
                        else:
                            print(f"      ✗ 未找到: {part_key}_bom_v1.step")

                    print(f"\n   ✅ 共找到 {len(exported_files)}/{len(bom_items)} ��STEP文件")
                else:
                    print(f"   ⚠ 宏执行失败，将使用占位立方体")
            else:
                print(f"   ❌ 未找到宏文件: {macro_path}")
                print(f"   请确保文件存在于项目的 scripts 目录下")
                print(f"   将使用占位立方体继续导入")

            # 4. 创建装配记录
            print(f"\n💾 创建装配记录...")
            assembly_id = self._create_assembly_record(
                assembly_name,
                assembly_description,
                sldasm_path,
                bom_items
            )
            print(f"✓ 装配ID: {assembly_id[: 8]}...")

            # 5. 导入零件版本（传递导出的文件字典）
            print(f"\n📦 导入零件版本...")
            part_versions = self._import_part_versions(bom_items, exported_files)
            print(f"✓ 共处理 {len(part_versions)} 种零件版本")

            # 6. 创建装配节点
            print(f"\n🔗 创建装配节点...")
            node_count = self._create_assembly_nodes(
                assembly_id,
                bom_items,
                part_versions
            )
            print(f"✓ 创建 {node_count} 个装配节点")

            # 7. 返回结果
            result = {
                'success': True,
                'assembly_id': assembly_id,
                'assembly_name': assembly_name,
                'part_count': len(bom_items),
                'node_count': node_count,
                'total_instances': total_qty,
                'exported_step_count': len(exported_files)
            }

            print(f"\n{'=' * 70}")
            print(f"✅ 导入完成")
            print(f"   装配:  {assembly_name}")
            print(f"   零件种类: {len(bom_items)}")
            print(f"   总实例数: {total_qty}")
            print(f"   导出STEP:  {len(exported_files)} 个")
            print(f"{'=' * 70}\n")

            return result

        except Exception as e:
            print(f"\n❌ 导入失败: {e}")
            import traceback
            traceback.print_exc()
            raise

        finally:
            print("\n🔒 关闭SolidWorks...")
            try:
                if hasattr(bom_extractor, 'quit_solidworks'):
                    bom_extractor.quit_solidworks()
                    print("✓ SolidWorks已关闭")
            except Exception as e:
                print(f"⚠️ 关闭SolidWorks时出错: {e}")

    def _create_assembly_record(
            self,
            assembly_name: str,
            assembly_description: Optional[str],
            sldasm_path: str,
            bom_items: List[SWBOMItem]
    ) -> str:
        """创建装配记录"""

        assembly_id = new_uuid()

        # ✅ 将元数据信息整合到描述中
        total_qty = sum(item.quantity for item in bom_items)

        if not assembly_description:
            assembly_description = (
                f"从SolidWorks BOM导入\n"
                f"源文件: {os.path.basename(sldasm_path)}\n"
                f"零件种类: {len(bom_items)}\n"
                f"总实例数: {total_qty}\n"
                f"导入时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

        conn = get_conn()
        cur = conn.cursor()

        try:
            # ✅ 只插入表中存在的列
            sql = """
                  INSERT INTO assemblies (id, name, description)
                  VALUES (%s, %s, %s) \
                  """

            cur.execute(sql, (
                uuid_to_bin(assembly_id),
                assembly_name,
                assembly_description
            ))

            conn.commit()
            return assembly_id

        finally:
            cur.close()
            conn.close()

    def _import_part_versions(
            self,
            bom_items: List[SWBOMItem],
            exported_files: Dict[str, str]  # ✅ 新增参数：导出的STEP文件字典
    ) -> Dict[str, Dict[str, Any]]:
        """导入零件版本"""

        part_versions = {}

        for item in bom_items:
            part_key = self._normalize_part_key(item.part_name)

            print(f"\n  📦 处理零件: {item.part_name}")
            print(f"     键: {part_key}")
            print(f"     数量: {item.quantity}")

            # 检查是否已存在
            existing = self._get_existing_part_version(part_key)

            if existing:
                print(f"     ✓ 复用现有版本:  v{existing['version_no']}")
                part_versions[part_key] = existing
            else:
                print(f"     ⊕ 创建新版本...")
                # ✅ 获取对应的STEP文件路径
                step_file_path = exported_files.get(part_key)
                new_version = self._create_part_version(
                    part_key,
                    item.part_name,
                    item,
                    step_file_path  # ✅ 传递STEP文件路径
                )
                print(f"     ✓ 已创建:  v{new_version['version_no']}")
                part_versions[part_key] = new_version

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
            bom_item: SWBOMItem,
            step_file_path: Optional[str] = None  # ✅ 新增参数：STEP文件路径
    ) -> Dict[str, Any]:
        """创建零件版本"""

        params_snapshot = {
            'source': 'bom',
            'configuration': bom_item.configuration,
            'material': bom_item.material if bom_item.material else None,
            'bom_item_number': bom_item.item_number
        }

        meta_json = {
            'from_bom': True,
            'configuration': bom_item.configuration,
            'import_date': datetime.now().isoformat()
        }

        # ✅ 根据是否有STEP文件决定使用真实几何还是占位符
        if step_file_path and os.path.exists(step_file_path):
            print(f"      ✅ 加载真实STEP:  {os.path.basename(step_file_path)}")

            # 加载STEP文件
            from OCC.Core.STEPControl import STEPControl_Reader
            from OCC.Core.IFSelect import IFSelect_RetDone

            try:
                reader = STEPControl_Reader()
                status = reader.ReadFile(step_file_path)

                if status == IFSelect_RetDone:
                    reader.TransferRoots()
                    if reader.NbShapes() > 0:
                        shape = reader.Shape(1)
                        meta_json['placeholder'] = False
                        meta_json['step_source'] = step_file_path
                        print(f"      ✅ STEP加载成功，{reader.NbShapes()} 个形状")
                    else:
                        print(f"      ⚠ STEP无有效几何，使用占位符")
                        shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
                        meta_json['placeholder'] = True
                else:
                    print(f"      ⚠ STEP读取失败，使用占位符")
                    shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
                    meta_json['placeholder'] = True
            except Exception as e:
                print(f"      ⚠ 加载STEP���常: {e}，使用占位符")
                shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
                meta_json['placeholder'] = True
        else:
            print(f"      ⚠ 无STEP文件，使用占位立方体")
            shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
            meta_json['placeholder'] = True

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
            description=f"从BOM导入:  {part_name} (配置: {bom_item.configuration})",
            meta_asset={'from_bom': True, 'placeholder': meta_json.get('placeholder', True)},
            meta_version=meta_json
        )

        version_id = result['part_version_id']
        version_no = result['version_no']
        part_id = result['part_id']

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

    def _update_part_mass(self, version_id: str, mass: float):
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

        finally:
            cur.close()
            conn.close()

    def _create_assembly_nodes(
        self,
        assembly_id: str,
        bom_items:  List[SWBOMItem],
        part_versions: Dict[str, Dict[str, Any]]
    ) -> int:
        """创建装配节点"""

        conn = get_conn()
        cur = conn.cursor()
        node_count = 0

        try:
            for item in bom_items:
                part_key = self._normalize_part_key(item.part_name)
                part_info = part_versions.get(part_key)

                if not part_info:
                    print(f"  ⚠ 跳过零件（未找到版本）: {item.part_name}")
                    continue

                # 为每个实例创建节点
                for instance_idx in range(item.quantity):
                    node_id = new_uuid()
                    node_name = f"{item.part_name}-{instance_idx + 1}"

                    # 默认变换（单位矩阵）
                    transform_json = json.dumps([
                        1, 0, 0, 0,
                        0, 1, 0, 0,
                        0, 0, 1, 0,
                        0, 0, 0, 1
                    ])

                    sql = """
                        INSERT INTO assembly_nodes
                        (id, assembly_id, part_version_id, name, transform_json)
                        VALUES (%s, %s, %s, %s, %s)
                    """

                    cur.execute(sql, (
                        uuid_to_bin(node_id),
                        uuid_to_bin(assembly_id),
                        uuid_to_bin(part_info['version_id']),
                        node_name,
                        transform_json
                    ))

                    node_count += 1

            conn.commit()
            return node_count

        finally:
            cur.close()
            conn.close()

    def _normalize_part_key(self, part_name: str) -> str:
        """规范化零件键名"""
        normalized = part_name.strip()
        normalized = normalized.replace(' ', '_')
        normalized = normalized.replace('/', '_')
        normalized = normalized.replace('\\', '_')
        return normalized