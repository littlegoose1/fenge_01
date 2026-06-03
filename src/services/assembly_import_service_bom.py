"""
基于BOM的装配导入服务（完整版 - 导出真实STEP文件）
不修改数据库表结构，使用现有字段存储扩展信息
"""
import os
import json
from typing import List, Dict, Any, Optional, Callable
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
from ..services.assembly_viewer_service import AssemblyViewerService
from ..services.obj_export_service import ObjExportService
from ..services.glb_export_service import GlbExportService


class AssemblyImportServiceBOM:
    """基于BOM的装配导入服务"""

    def __init__(self):
        self.persistence = PersistenceService()
        self.viewer_service = AssemblyViewerService()
        self.obj_exporter = ObjExportService()
        self.glb_exporter = GlbExportService()

    def import_assembly_from_bom(
            self,
            sldasm_path: str,
            assembly_name: Optional[str] = None,
            assembly_description: Optional[str] = None,
            progress_callback: Optional[Callable[[int], None]] = None
    ) -> Dict[str, Any]:
        """从装配文件导入并基于BOM入库（使用SolidWorks宏批量导出STEP）"""
        def _report_progress(p: int):
            if progress_callback:
                try:
                    progress_callback(max(0, min(100, int(p))))
                except Exception:
                    pass

        print("\n" + "=" * 70)
        print("📦 基于BOM的装配导入（使用SolidWorks宏批量导出）")
        print("=" * 70 + "\n")
        _report_progress(15)

        if not os.path.exists(sldasm_path):
            raise FileNotFoundError(f"文件不存在:  {sldasm_path}")

        if not assembly_name:
            assembly_name = os.path.splitext(os.path.basename(sldasm_path))[0]

        bom_extractor = SolidWorksBOMExtractorAuto()

        try:
            # ========== 1. 启动SolidWorks并打开文件 ==========
            print("🚀 启动SolidWorks...")
            if not bom_extractor.start_solidworks(visible=False):
                raise RuntimeError("无法启动SolidWorks")
            _report_progress(22)

            print(f"📂 打开装配:  {assembly_name}")
            if not bom_extractor.open_assembly(sldasm_path):
                raise RuntimeError("无法打开装配文件")
            _report_progress(30)

            # ========== 2. 提取BOM ==========
            print("\n📋 提取BOM...")
            bom_items = bom_extractor.extract_bom()
            instance_rows = bom_extractor.extract_instances(top_level_only=False)
            print(f"✓ 实例位姿数: {len(instance_rows)}")
            _report_progress(40)

            if not bom_items:
                raise RuntimeError("BOM为空，无法导入")

            total_qty = sum(item.quantity for item in bom_items)
            print(f"✓ 提取到 {len(bom_items)} 种零件，共 {total_qty} 个实例")

            # ========== 3. 使用宏批量导出所有零件 ==========
            export_dir = os.getenv("EXPORT_DIR", "D:\\solidworks\\step")
            os.makedirs(export_dir, exist_ok=True)

            print(f"\n📤 使用SolidWorks宏批量导出零件到:  {export_dir}")
            _report_progress(45)

            # 构建宏文件路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            macro_path = os.path.join(project_root, "scripts", "ExportAllComponentsToSTEP.swp")

            print(f"   宏文件路径: {macro_path}")
            print(f"   宏文件存在: {os.path.exists(macro_path)}")

            exported_files = {}

            if os.path.exists(macro_path):
                # 运行宏
                print(f"   🔧 运行宏...")
                success = bom_extractor.run_macro(
                    macro_path,
                    "ExportAllComponentsToSTEP1",
                    "main"
                )

                if success:
                    print(f"   ✓ 宏调用成功")

                    # ✅ 优化：监控STEP文件生成（而不是等待标记文件）
                    import time
                    max_wait = 120  # 最多等待120秒
                    check_interval = 2  # 每2秒检查一次
                    elapsed = 0
                    expected_count = len(bom_items)

                    print(f"   ⏳ 等待STEP文件生成 (需要 {expected_count} 个文件)...")

                    last_count = 0
                    stable_count = 0  # 文件数量稳定的次数

                    while elapsed < max_wait:
                        # 扫描当前已生成的STEP文件
                        current_files = {}
                        for item in bom_items:
                            part_key = self._normalize_part_key(item.part_name)
                            step_file = os.path.join(export_dir, f"{part_key}_bom_v1.step")
                            if os.path.exists(step_file):
                                # 检查文件大小（确保写入完成）
                                file_size = os.path.getsize(step_file)
                                if file_size > 1000:  # 至少1KB，避免空文件
                                    current_files[part_key] = step_file

                        current_count = len(current_files)
                        if expected_count > 0:
                            ratio = float(current_count) / float(expected_count)
                            _report_progress(45 + int(ratio * 15))

                        # 检查是否所有文件都已生成
                        if current_count == expected_count:
                            print(f"   ✅ 所有STEP文件生成完成！(耗时 {elapsed:.1f} 秒)")
                            exported_files = current_files
                            break

                        # 检查文件数量是否稳定（连续3次检查数量不变）
                        if current_count == last_count and current_count > 0:
                            stable_count += 1
                            if stable_count >= 3:  # 6秒内数量不变，认为完成
                                print(f"   ⚠️ 文件生成似乎已完成，但只有 {current_count}/{expected_count} 个文件")
                                exported_files = current_files
                                break
                        else:
                            stable_count = 0

                        last_count = current_count

                        # 显示进度
                        if int(elapsed) % 10 == 0:
                            if elapsed == 0:
                                print(f"      等待中...  {current_count}/{expected_count} 文件")
                            else:
                                print(f"      进度: {current_count}/{expected_count} 文件，已等待 {elapsed:.0f} 秒")

                        time.sleep(check_interval)
                        elapsed += check_interval
                    else:
                        # 超时，使用已找到的文件
                        print(f"   ⚠️ 等待超时，已找到 {current_count}/{expected_count} 个文件")
                        exported_files = current_files

                    # 额外等待1秒，确保文件系统同步
                    time.sleep(1)

                    # 显示详细信息
                    if exported_files:
                        print(f"\n   📋 STEP文件详情:")
                        for i, (key, path) in enumerate(sorted(exported_files.items()), 1):
                            if i <= 5:  # 只显示前5个
                                file_size = os.path.getsize(path)
                                print(f"      [{i}] {key}_bom_v1.step ({file_size:,} bytes)")

                        if len(exported_files) > 5:
                            print(f"      ...  还有 {len(exported_files) - 5} 个文件")

                        print(f"\n   ✅ 共找到 {len(exported_files)}/{expected_count} 个STEP文件")
                    else:
                        print(f"\n   ❌ 未找到任何STEP文件")

                    if len(exported_files) < expected_count:
                        missing = []
                        for item in bom_items:
                            part_key = self._normalize_part_key(item.part_name)
                            if part_key not in exported_files:
                                missing.append(part_key)
                        if missing:
                            print(f"   ⚠️ 缺失的零件:  {', '.join(missing[: 3])}" +
                                  (f" ...  还有 {len(missing) - 3} 个" if len(missing) > 3 else ""))

                else:
                    print(f"   ⚠ 宏执行失败，将使用占位立方体")
            else:
                print(f"   ❌ 未找到宏文件:  {macro_path}")
                print(f"   将使用占位立方体继续导入")

            # ========== 4. 创建装配记录 ==========
            print(f"\n💾 创建装配记录...")
            _report_progress(65)
            assembly_id = self._create_assembly_record(
                assembly_name,
                assembly_description,
                sldasm_path,
                bom_items
            )
            print(f"✓ 装配ID: {assembly_id[: 8]}...")

            # ========== 5. 导入零件版本 ==========
            print(f"\n📦 导入零件版本...")
            part_versions = self._import_part_versions(bom_items, exported_files)
            print(f"✓ 共处理 {len(part_versions)} 种零件版本")
            _report_progress(78)

            # ========== 6. 创建装配节点 ==========
            print(f"\n🔗 创建装配节点...")
            # 在 import_assembly_from_bom() 中（替换你原来的创建节点调用）
            node_count = self._create_assembly_nodes(
                assembly_id=assembly_id,
                bom_items=bom_items,
                part_versions=part_versions,
                instance_rows=instance_rows
            )
            print(f"✓ 创建 {node_count} 个装配节点")
            _report_progress(88)

            obj_path = ""
            glb_path = ""
            try:
                nodes_for_obj = self.viewer_service.get_assembly_nodes(assembly_id)
                obj_path = self.obj_exporter.export_assembly_nodes(
                    assembly_name=assembly_name,
                    assembly_id=assembly_id,
                    nodes=nodes_for_obj,
                ) or ""
                if obj_path:
                    print(f"✅ 装配 OBJ 已导出: {obj_path}")
                    glb_path, glb_err = self.glb_exporter.obj_to_glb(obj_path)
                    if glb_path:
                        print(f"✅ 装配 GLB 已导出: {glb_path}")
                    else:
                        print(f"⚠️ 装配 GLB 导出失败（已忽略）: {glb_err}")
            except Exception as ex:
                print(f"⚠️ 装配 OBJ/GLB 导出失败（已忽略）: {ex}")
            _report_progress(95)

            # ========== 7. 返回结果 ==========
            result = {
                'success': True,
                'assembly_id': assembly_id,
                'assembly_name': assembly_name,
                'part_count': len(bom_items),
                'node_count': node_count,
                'total_instances': total_qty,
                'exported_step_count': len(exported_files),
                'obj_path': obj_path,
                'glb_path': glb_path,
            }

            print(f"\n{'=' * 70}")
            print(f"✅ 导入完成")
            print(f"   装配:  {assembly_name}")
            print(f"   零件种类: {len(bom_items)}")
            print(f"   总实例数: {total_qty}")
            print(f"   导出STEP:  {len(exported_files)} 个")
            print(f"{'=' * 70}\n")
            _report_progress(100)

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
        part_name = self._to_cn_part_name(part_name)

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

    @staticmethod
    def _to_cn_part_name(raw_name: str) -> str:
        name = (raw_name or "").strip()
        if not name:
            return "未命名零部件"
        if any("\u4e00" <= ch <= "\u9fff" for ch in name):
            return name
        lower = name.lower()
        mapping = [
            (["barrel"], "枪管"),
            (["receiver"], "机匣"),
            (["bolt"], "枪机"),
            (["stock"], "枪托"),
            (["trigger"], "扳机"),
            (["sight"], "瞄具"),
            (["magazine"], "弹匣"),
            (["grip"], "握把"),
            (["rail"], "导轨"),
            (["spring"], "弹簧"),
            (["pin"], "销钉"),
            (["screw"], "螺钉"),
            (["nut"], "螺母"),
            (["washer"], "垫片"),
            (["gear"], "齿轮"),
            (["shaft"], "轴"),
            (["bearing"], "轴承"),
            (["connector"], "连接件"),
            (["housing", "cover"], "壳体"),
        ]
        for keys, cn in mapping:
            if any(k in lower for k in keys):
                return cn
        return f"零部件_{name}"

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
            bom_items: List[SWBOMItem],
            part_versions: Dict[str, Dict[str, Any]],
            instance_rows: List[Dict[str, Any]]
    ) -> int:
        """?????????? part+configuration ???????"""

        conn = get_conn()
        cur = conn.cursor()
        node_count = 0

        # (part_key, configuration) -> ????
        # ???? (part_key, None) ??????
        bucket: Dict[tuple, List[Dict[str, Any]]] = {}
        for r in instance_rows:
            part_key = self._normalize_part_key(r.get("part_name", ""))
            cfg = (r.get("configuration") or "Default").strip()
            bucket.setdefault((part_key, cfg), []).append(r)
            bucket.setdefault((part_key, None), []).append(r)

        # ????? key ????
        ptr: Dict[tuple, int] = {k: 0 for k in bucket.keys()}

        def identity16() -> List[float]:
            return [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            ]

        try:
            for item in bom_items:
                part_key = self._normalize_part_key(item.part_name)
                part_info = part_versions.get(part_key)

                if not part_info:
                    print(f"  ? ???????????: {item.part_name}")
                    continue

                for i in range(item.quantity):
                    node_id = new_uuid()
                    node_name = f"{item.part_name}-{i + 1}"
                    m16 = identity16()

                    key_exact = (part_key, (item.configuration or "Default").strip())
                    key_fallback = (part_key, None)

                    rows_exact = bucket.get(key_exact, [])
                    if rows_exact:
                        use_key = key_exact
                        rows = rows_exact
                    else:
                        use_key = key_fallback
                        rows = bucket.get(key_fallback, [])

                    p = ptr.get(use_key, 0)
                    if p < len(rows):
                        rec = rows[p]
                        ptr[use_key] = p + 1
                        node_name = rec.get("instance_name", node_name)
                        mm = rec.get("transform_matrix")
                        if isinstance(mm, list) and len(mm) == 16:
                            m16 = [float(v) for v in mm]

                    transform_json = json.dumps({"matrix": m16}, ensure_ascii=False)

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
