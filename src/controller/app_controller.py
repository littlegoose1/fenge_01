from typing import List, Dict, Any, Optional
import os

from PySide6.QtCore import QObject, Slot, QTimer
from PySide6.QtWidgets import QMessageBox, QInputDialog

from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder

from .. model.geometry import GeometricPrimitive
from ..model.io import StepFileHandler
from ..model.segmentation import GeometrySegmentationProcessor
from ..view.main_window import MainWindow

from .. services.solver_service import SolveAssemblyWorker
from ..services.assembly_import_service import AssemblyImportService
from ..db.persistence_service import PersistenceService

# ✅ 导入3. 3. 2模块
from ..assembly. topology_analyzer import TopologyAnalyzer, AdjacencyMatrix
from ..assembly.collision_detector import CollisionDetector
from ..assembly.cooperative_deformation import CooperativeDeformationEngine, DeformationConstraint

# ✅ 导入官方API版本的SolidWorks BOM提取器
from ..services.solidworks_bom_extractor_auto import SolidWorksBOMExtractorAuto

from .. services.assembly_import_service_bom import AssemblyImportServiceBOM

# ✅ 导入装配查看和可视化服务
from ..services.assembly_viewer_service import AssemblyViewerService
from ..services.part_visualizer import PartVisualizer


class ApplicationController(QObject):
    """
    应用程序控制器
    - 舍弃 XCAF，仅使用 flat-split 拆分并入库（含规范几何去重）
    - 打开/保存、参数修改与预览、撤销/重做
    - 导出当前零部件到数据库
    - 装配求解（后台线程）
    - ✅ 拓扑邻接分析、碰撞检测、协同变形（3.3.2）
    - ✅ 从SolidWorks提取BOM（官方API方法）
    - ✅ 装配查看和可视化
    """

    def __init__(self, main_window: MainWindow):
        super().__init__()

        # 强制 flat-split 模式，保证稳定导入
        os.environ["ASSEMBLY_IMPORT_FORCE_FLAT"] = "1"
        os.environ["ASSEMBLY_IMPORT_SPLIT_SOLIDS"] = "1"

        self.main_window = main_window

        # 模型/处理器
        self.io_handler = StepFileHandler()
        self.processor = GeometrySegmentationProcessor()

        # 当前数据
        self.primitives: List[GeometricPrimitive] = []
        self.modified_shapes: Dict[int, Any] = {}
        self.preview_shapes: Dict[int, Any] = {}
        self.current_file_path: str = ""

        # 服务
        self.persistence = PersistenceService()
        self.assembly_importer = AssemblyImportService()
        self.assembly_importer_bom = AssemblyImportServiceBOM()

        # 后台 workers
        self._workers: list[SolveAssemblyWorker] = []

        # ✅ 3.3.2模块
        self.topology_analyzer = TopologyAnalyzer(contact_threshold=0.1, angle_threshold=5.0)
        self.collision_detector = CollisionDetector(
            penetration_threshold=-0.01,
            contact_threshold=0.1,
            clearance_threshold=1.0
        )
        self.deformation_engine = CooperativeDeformationEngine(
            stiffness=1.0,
            max_iterations=50,
            tolerance=1e-4
        )

        # ✅ 缓存装配分析结果
        self.current_adjacency:  Optional[AdjacencyMatrix] = None
        self.current_assembly_nodes: List[Dict[str, Any]] = []

        # ✅ 装配查看和可视化服务
        self.assembly_viewer = AssemblyViewerService()
        self.part_visualizer = PartVisualizer(main_window. canvas._display)

        # ✅ 装配查看状态
        self.current_assembly_id: Optional[str] = None
        self.current_displayed_nodes: List[Dict[str, Any]] = []

        # 处理器回调接入 UI
        self.processor. set_status_callback(self. main_window.set_status)
        self.processor.set_progress_callback(self.main_window.set_progress)

        # ========== 现有信号连接 ==========
        self.main_window.open_file_requested.connect(self.open_file)
        self.main_window.save_file_requested.connect(self.save_file)
        self.main_window.modify_primitive_requested.connect(self.modify_primitive)
        self.main_window.update_preview_requested.connect(self.update_preview)
        self.main_window. undo_requested.connect(self. undo_modification)
        self.main_window.redo_requested.connect(self.redo_modification)
        self.main_window.solve_assembly_requested.connect(self.solve_assembly)
        self.main_window.export_part_to_db_requested.connect(self.export_part_to_db)
        self.main_window.import_assembly_requested.connect(self.import_and_store_assembly)

        # ✅ 连接3.3.2功能信号
        self.main_window.analyze_topology_requested.connect(self.analyze_topology)
        self.main_window.check_collision_requested.connect(self.check_collision)
        self.main_window.validate_assembly_requested.connect(self.validate_assembly)

        # ✅ 连接SolidWorks BOM提取信号
        self.main_window.extract_bom_auto_requested.connect(self.extract_bom_auto)

        # ✅ 连接装配查看和可视化信号
        self.main_window.refresh_assemblies_requested.connect(self. refresh_assemblies)
        self.main_window.load_assembly_requested.connect(self.load_assembly)
        self.main_window.assembly_selected. connect(self.on_assembly_selected)
        self.main_window.node_selected.connect(self.on_node_selected)

        # ✅ 连接加载零件进行分割的信号
        self.main_window.load_part_for_segmentation_requested.connect(self.load_part_for_segmentation)

        # ✅ 启动后延迟加载装配列表
        QTimer.singleShot(500, self.refresh_assemblies)

    # ---------------- 文件打开/保存 ----------------
    @Slot(str)
    def open_file(self, file_path: str):
        try:
            self.current_file_path = file_path
            self.main_window.set_status(f"正在加载文件: {file_path}")

            shape = self.io_handler.load_step_model(file_path)
            self.primitives = self.processor. process_shape(shape)

            self.modified_shapes. clear()
            self.preview_shapes.clear()

            self.main_window.set_primitives(self.primitives)
            self.main_window.set_status("加载完成")
        except Exception as e:
            self.main_window.show_error("文件加载失败", f"无法加载文件: {e}")
            self.main_window.set_status("文件加载失败")

    @Slot(str)
    def save_file(self, file_path: str):
        try:
            ok = self.io_handler.export_primitives(
                self.primitives, self.modified_shapes, file_path
            )
            if ok:
                self.main_window.show_info("保存成功", f"模型已保存到: {file_path}")
                self.main_window.set_status(f"保存成功: {file_path}")
            else:
                self.main_window.show_error("保存失败", "无法保存文件，请检查路径和��限")
                self.main_window.set_status("保存失败")
        except Exception as e:
            self.main_window.show_error("保存失败", f"保存文件时出错: {e}")
            self.main_window.set_status("保存失败")

    # ---------------- 几何参数修改/预览/历史 ----------------
    @Slot(int, dict)
    def modify_primitive(self, index: int, parameters: Dict[str, Any]):
        if not (0 <= index < len(self.primitives)):
            return
        primitive = self.primitives[index]
        try:
            show_preview = bool(parameters.pop("show_preview", True))

            if hasattr(primitive, "has_significant_changes"):
                if not primitive.has_significant_changes(primitive. get_params(), parameters):
                    self.main_window.show_info("无变化", "参数没有实质性变化，无需更新")
                    return

            if not hasattr(primitive, "rebuild_with_parameters"):
                self.main_window.show_error("不支持", "该几何体不支持参数化重建")
                return

            new_shape = primitive.rebuild_with_parameters(parameters)

            preview_shape = None
            if show_preview and hasattr(primitive, "create_preview_shape"):
                try:
                    preview_shape = primitive.create_preview_shape(parameters)
                    if preview_shape:
                        self.preview_shapes[index] = preview_shape
                except Exception as e:
                    print(f"[preview] 创建预览形状失败: {e}")

            if hasattr(primitive, "save_parameters_to_history"):
                primitive.save_parameters_to_history(parameters)

            self.modified_shapes[index] = new_shape

            if show_preview and preview_shape:
                self. main_window.show_original_with_preview(index, new_shape, preview_shape)
            else:
                self.main_window.update_primitive(index, new_shape)

            self.main_window.set_status(f"已修改 {primitive.type} #{index + 1}")
        except Exception as e:
            self.main_window.show_error("修改失败", f"参数应用失败: {e}")

    @Slot(int, bool)
    def update_preview(self, index: int, show_preview: bool):
        if not (0 <= index < len(self.primitives)):
            return
        primitive = self.primitives[index]
        try:
            current_shape = self.modified_shapes.get(index, getattr(primitive, "original_shape", None))
            preview_shape = None
            if show_preview:
                if index in self.preview_shapes:
                    preview_shape = self. preview_shapes[index]
                elif hasattr(primitive, "create_preview_shape"):
                    try:
                        preview_shape = primitive.create_preview_shape(primitive.get_params())
                        if preview_shape:
                            self.preview_shapes[index] = preview_shape
                    except Exception as e:
                        print(f"[preview] 创建预览形状失败:  {e}")

            if show_preview and preview_shape:
                self.main_window.show_original_with_preview(index, current_shape, preview_shape)
            else:
                self.main_window.update_primitive(index, current_shape)
        except Exception as e:
            print(f"[preview] 更新预览失败: {e}")

    @Slot(int)
    def undo_modification(self, index:  int):
        if not (0 <= index < len(self.primitives)):
            return
        primitive = self.primitives[index]
        try:
            if hasattr(primitive, "undo"):
                new_shape = primitive.undo()
            else:
                new_shape = None
            if new_shape:
                self. modified_shapes[index] = new_shape
                if index in self.preview_shapes:
                    del self.preview_shapes[index]
                self.main_window.update_primitive(index, new_shape)
                self.main_window.set_status(f"已撤销 {primitive.type} #{index + 1} 的修改")
        except Exception as e:
            self.main_window.show_error("撤销失败", f"无法撤销修改: {e}")

    @Slot(int)
    def redo_modification(self, index: int):
        if not (0 <= index < len(self.primitives)):
            return
        primitive = self.primitives[index]
        try:
            if hasattr(primitive, "redo"):
                new_shape = primitive. redo()
            else:
                new_shape = None
            if new_shape:
                self. modified_shapes[index] = new_shape
                if index in self.preview_shapes:
                    del self.preview_shapes[index]
                self.main_window.update_primitive(index, new_shape)
                self.main_window.set_status(f"已重做 {primitive.type} #{index + 1} 的修改")
        except Exception as e:
            self.main_window.show_error("重做失败", f"无法重做修改: {e}")

    # ---------------- 导出当前零部件到数据库 ----------------
    def _compose_part_shape(self):
        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)

        for i, primitive in enumerate(self.primitives):
            shape = self.modified_shapes.get(i)
            if shape is None:
                shape = getattr(primitive, "original_shape", None)
                if shape is None:
                    for face in getattr(primitive, "faces", []):
                        builder.Add(compound, face)
                    continue
            builder.Add(compound, shape)
        return compound

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

    @Slot()
    def export_part_to_db(self):
        if not self.primitives:
            self.main_window.show_error("无数据", "请先打开并解析一个零部件。")
            return

        try:
            part_shape = self._compose_part_shape()
            base = os.path.splitext(os.path.basename(self.current_file_path or "unnamed"))[0]
            part_key = base
            part_name = self._to_cn_part_name(base)

            params_snapshot:  Dict[str, Any] = {
                "primitives": [
                    {
                        "index": i,
                        "type": prim.type,
                        "params": prim.get_params(),
                        "modified": (i in self.modified_shapes),
                    }
                    for i, prim in enumerate(self.primitives)
                ]
            }

            stub = f"{base}_part"

            result = self.persistence.persist_part_version(
                part_key=part_key,
                part_name=part_name,
                params_snapshot=params_snapshot,
                shape=part_shape,
                step_file_stub=stub,
                category=None,
                tags=list({prim.type for prim in self.primitives}),
                description=f"Generated from {self.current_file_path}",
                meta_asset={"source": "gui", "file":  self.current_file_path or ""},
                meta_version={"ui": "pyside6"},
            )

            msg = f"已保存零部件版本 v{result['version_no']}\nSTEP: {result['step_path']}"
            if result.get("obj_path"):
                msg += f"\nOBJ: {result['obj_path']}"
            msg += f"\n零部件名称: {part_name}"
            self.main_window.show_info("导出成功", msg)
            self.main_window.set_status(f"已入库零部件 v{result['version_no']}")
        except Exception as e:
            self.main_window.show_error("导出失败", f"保存零部件到数据库失败：{e}")

    # ---------------- 导入并入库 ----------------
    @Slot(str)
    def import_and_store_assembly(self, step_path: str):
        """导入装配并入库（智能选择导入方式）"""
        try:
            self.main_window.begin_import_progress()
            self.main_window.set_progress(5)
            file_ext = os.path.splitext(step_path)[1].lower()

            # 检查文件类型
            if file_ext not in ['.sldasm', '. step', '.stp']:
                self.main_window.show_error(
                    "不支持的文件",
                    f"请选择 . SLDASM 或 . STEP 文件\n当前文件: {file_ext}"
                )
                return

            self.main_window.set_status(f"开始导入:  {os.path.basename(step_path)}")
            self.main_window.set_progress(12)

            # ✅ 根据文件类型选择导入方式
            if file_ext == '.sldasm':
                # SolidWorks装配 - 使用BOM导入
                result = self._import_solidworks_assembly_bom(
                    step_path,
                    progress_callback=self.main_window.set_progress
                )
            else:
                # STEP文件 - 使用原有的几何分析方法
                self.main_window.set_status("正在解析STEP装配并入库...")
                self.main_window.set_progress(45)
                result = self.assembly_importer.import_step_assembly(step_path)
                self.main_window.set_progress(85)

            asm_id = result["assembly_id"]
            node_count = int(result.get("node_count", len(result.get("nodes", []))))
            mode = result.get("mode", result.get("import_mode", "unknown"))
            obj_path = result.get("obj_path", "")
            glb_path = result.get("glb_path", "")
            self.main_window.set_progress(95)

            msg = (
                f"✅ 导入成功！\n\n"
                f"模式: {mode}\n"
                f"装配ID: {asm_id[:8]}...\n"
                f"零件种类: {result.get('total_parts', 'N/A')}\n"
                f"装配节点: {node_count}"
            )
            if obj_path:
                msg += f"\nOBJ: {obj_path}"
            if glb_path:
                msg += f"\nGLB: {glb_path}"

            self.main_window.show_info("导入完成", msg)

            self.main_window.set_status(f"导入完成（{mode}，节点: {node_count}）")
            self.main_window.set_progress(100)

            # ✅ 导入成功后自动刷新装配列表
            QTimer.singleShot(100, self.refresh_assemblies)

        except Exception as e:
            self.main_window.show_error("导入失败", str(e))
            self.main_window.set_status("导入失败")
            import traceback
            traceback.print_exc()
        finally:
            QTimer.singleShot(500, self.main_window.end_import_progress)

    def _import_solidworks_assembly_bom(
        self,
        step_path: str,
        progress_callback=None
    ) -> Dict[str, Any]:
        """导入SolidWorks装配（基于BOM）"""
        # 获取装配名称
        assembly_name = os.path.splitext(os. path.basename(step_path))[0]

        # 询问用户是否添加描述（可选）
        description, ok = QInputDialog.getText(
            self. main_window,
            "装配描述",
            f"为装配 '{assembly_name}' 添加描述（可选）:",
            text=f"从 {assembly_name}. SLDASM 导入"
        )

        if not ok:
            description = None

        # 导入
        result = self.assembly_importer_bom.import_assembly_from_bom(
            step_path,
            assembly_name=assembly_name,
            assembly_description=description,
            progress_callback=progress_callback
        )



        return result

    # ---------------- 装配求解（后台线程） ----------------
    @Slot(str, int)
    def solve_assembly(self, assembly_id: str, iterations: int):
        asm_id = assembly_id or None
        worker = SolveAssemblyWorker(asm_id, iterations, self)
        self._workers. append(worker)

        def on_finished(success: bool, message: str, used_asm_id: str):
            if success:
                self.main_window.show_info("求解完成", message)
                self.main_window.set_status(
                    f"求解完成（装配:  {used_asm_id or '最新'}，迭代: {iterations}）"
                )
            else:
                self.main_window.show_error("求解失败", message)
                self.main_window.set_status("求解失败")
            try:
                self._workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(on_finished)
        self.main_window.set_status(
            f"开始求解装配（装配:  {asm_id or '最新'}，迭代: {iterations}）"
        )
        worker.start()

    # ✅ ---------------- 3.3.2 新增功能 ----------------

    def _load_assembly_nodes_for_analysis(self, assembly_id: str) -> List[Dict[str, Any]]:
        """从数据库加载装配节点用于分析"""
        from ..db.mysql import get_conn
        from ..db.util import uuid_to_bin, bin_to_uuid
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        import json

        if not assembly_id or assembly_id. strip() == "":
            print("[DEBUG] 未指定装配ID，查找最新装配...")
            assembly_id = self._get_latest_assembly_id()
            if not assembly_id:
                raise ValueError("数据库中没有装配记录，请先导入装配")
            print(f"[DEBUG] 使用最新装配ID: {assembly_id}")

        try:
            import uuid
            uuid. UUID(assembly_id)
        except ValueError:
            raise ValueError(
                f"无效的装配ID格式:  {assembly_id}\n请输入有效的UUID（例如: 12345678-1234-1234-1234-123456789abc）")

        sql = """
              SELECT an.id, an.name, an.transform_json
              FROM assembly_nodes an
              WHERE an. assembly_id = %s
              """

        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, (uuid_to_bin(assembly_id),))
            rows = cur. fetchall() or []

            if not rows:
                raise ValueError(f"装配ID {assembly_id} 没有找到任何节点，请检查是否已导入")

            nodes = []
            for row in rows:
                node_id = bin_to_uuid(row['id'])
                transform_data = row.get('transform_json')

                if isinstance(transform_data, (bytes, bytearray)):
                    transform_data = transform_data.decode('utf-8')
                if isinstance(transform_data, str):
                    transform = json.loads(transform_data)
                else:
                    transform = transform_data or {"pos": [0, 0, 0], "quat": [1, 0, 0, 0]}

                shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()

                nodes.append({
                    'id': node_id,
                    'name': row. get('name', ''),
                    'transform': transform,
                    'shape': shape
                })

            print(f"[DEBUG] 成功加载 {len(nodes)} 个装配节点")
            return nodes
        finally:
            cur.close()
            conn.close()

    def _get_latest_assembly_id(self) -> Optional[str]:
        """获取最新的装配ID"""
        from ..db.mysql import get_conn
        from ..db.util import bin_to_uuid

        sql = "SELECT id FROM assemblies ORDER BY created_at DESC LIMIT 1"
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur. execute(sql)
            row = cur.fetchone()
            if row:
                return bin_to_uuid(row[0])
            return None
        finally:
            cur.close()
            conn.close()

    @Slot(str)
    def analyze_topology(self, assembly_id: str):
        """拓扑邻接分析"""
        try:
            self.main_window.set_status("正在分析装配拓扑关系...")

            nodes = self._load_assembly_nodes_for_analysis(assembly_id)
            if not nodes:
                self.main_window.show_error("分析失败", "未找到装配节点")
                return

            self.current_adjacency = self. topology_analyzer.analyze_assembly(nodes)
            self.current_assembly_nodes = nodes

            report = f"""拓扑邻接分析完成

节点数量: {len(self.current_adjacency.node_ids)}
检测到的接触:  {len(self.current_adjacency.contacts)}

接触详情:
"""
            for contact in self.current_adjacency. contacts[: 10]:
                report += f"\n• {contact. node_a_id[: 8]} ↔ {contact.node_b_id[:8]}"
                report += f"\n  类型: {contact.contact_type}, 距离: {contact.distance:.4f}mm"

            if len(self.current_adjacency.contacts) > 10:
                report += f"\n\n... 还有 {len(self.current_adjacency.contacts) - 10} 个接触"

            self.main_window.show_topology_result(report, self.current_adjacency)
            self.main_window.set_status("拓扑分析完成")

        except Exception as e:
            self.main_window.show_error("拓扑分析失败", f"分析失败: {e}")
            import traceback
            traceback.print_exc()

    @Slot(str)
    def check_collision(self, assembly_id: str):
        """碰撞检测"""
        try:
            self.main_window.set_status("正在执行碰撞检测...")

            if not self.current_assembly_nodes:
                nodes = self._load_assembly_nodes_for_analysis(assembly_id)
            else:
                nodes = self. current_assembly_nodes

            if not nodes:
                self.main_window.show_error("检测失败", "未找到装配节点")
                return

            collisions = self.collision_detector. detect_collisions(nodes)

            report = f"""碰撞检测完成

总碰撞数: {len(collisions)}

"""
            penetrations = [c for c in collisions if c. collision_type == 'penetration']
            contacts = [c for c in collisions if c.collision_type == 'contact']

            if penetrations:
                report += f"⚠️ 干涉穿透: {len(penetrations)} 个\n"
                for p in penetrations[: 5]:
                    report += f"  • {p.node_a_id[:8]} ↔ {p.node_b_id[:8]}:  深度={p.depth:.4f}mm\n"

            if contacts:
                report += f"\n✓ 紧密接触: {len(contacts)} 个\n"

            if not collisions:
                report += "✓ 无碰撞，装配正常"

            self.main_window.show_collision_result(report, collisions)
            self.main_window.set_status("碰撞检测完成")

        except Exception as e:
            self.main_window.show_error("碰撞检测失败", f"检测失败: {e}")
            import traceback
            traceback.print_exc()

    @Slot(str)
    def validate_assembly(self, assembly_id: str):
        """装配验证（综合分析）"""
        try:
            self.main_window.set_status("正在验证装配...")

            if not self.current_assembly_nodes:
                nodes = self._load_assembly_nodes_for_analysis(assembly_id)
            else:
                nodes = self.current_assembly_nodes

            if not nodes:
                self.main_window.show_error("验证失败", "未找到装配节点")
                return

            validation = self.collision_detector.validate_assembly(nodes)

            is_valid = validation['is_valid']
            status_icon = "✓" if is_valid else "✗"

            report = f"""装配验证报告

{status_icon} 装配有效性: {'有效' if is_valid else '无效'}

统计信息:
• 总碰撞数: {validation['total_collisions']}
• 干涉穿透:  {validation['penetrations']}
• 紧密接触: {validation['contacts']}
• 间隙区域: {validation['clearances']}
• 最大严重度: {validation['max_severity']:.2f}

"""

            if validation['collision_details']:
                report += "碰撞详情:\n"
                for detail in validation['collision_details'][:10]:
                    report += f"• {detail['node_a']} ↔ {detail['node_b']}: "
                    report += f"{detail['type']} (严重度={detail['severity']:.2f})\n"

            self.main_window.show_validation_result(report, validation)
            self.main_window.set_status("装配验证完成")

        except Exception as e:
            self.main_window.show_error("装配验证失败", f"验证失败:  {e}")
            import traceback
            traceback.print_exc()

    # ✅ ---------------- SolidWorks BOM提取功能 ----------------

    @Slot(str, str, str)
    def extract_bom_auto(self, sldasm_path: str, output_path: str, format: str = "excel"):
        """从SolidWorks提取BOM（自动模式）"""
        try:
            self.main_window.set_status("启动SolidWorks...")

            extractor = SolidWorksBOMExtractorAuto()

            # 启动SolidWorks（后台）
            if not extractor.start_solidworks(visible=False):
                raise RuntimeError("无法启动SolidWorks")

            self.main_window.set_status("打开装配文件...")

            # 打开文件
            if not extractor. open_assembly(sldasm_path):
                raise RuntimeError("无法打开装配文件")

            self.main_window.set_status("提取BOM...")

            # 提取BOM
            bom_items = extractor.extract_bom()

            if not bom_items:
                self.main_window.show_warning("提取结果", "未找到BOM项")
                return

            extractor.print_summary()

            # 导出
            self.main_window.set_status("导出BOM...")

            # 标准化输出路径
            output_path = self._normalize_output_path(output_path, format)

            if format. lower() == "excel":
                extractor.export_to_excel(output_path)
            elif format. lower() == "json":
                extractor.export_to_json(output_path)
            elif format.lower() == "csv":
                extractor.export_to_csv(output_path)
            else:
                extractor.export_to_excel(output_path)

            # 显示结果
            total_parts = len(bom_items)
            total_quantity = sum(item.quantity for item in bom_items)

            self.main_window.show_info(
                "BOM提取成功",
                f"✅ 提取完成！\n\n"
                f"📊 统计:\n"
                f"  • 独特零件: {total_parts}\n"
                f"  • 总数量: {total_quantity}\n\n"
                f"📁 文件:  {os.path.basename(output_path)}"
            )

            self.main_window.set_status(f"BOM已导出:  {os.path.basename(output_path)}")

        except Exception as e:
            self.main_window.show_error("BOM提取失败", str(e))
            self.main_window.set_status("BOM提取失败")
            import traceback
            traceback. print_exc()

        finally:
            try:
                extractor.close_document()
                extractor.quit_solidworks()
            except:
                pass

    def _normalize_output_path(self, output_path: str, format: str) -> str:
        """标准化输出路径，避免重复扩展名"""
        ext_map = {
            'excel': '.xlsx',
            'json': '.json',
            'csv': '.csv'
        }

        correct_ext = ext_map.get(format.lower(), '.xlsx')

        # 移除重复扩展名
        for ext in ['.xlsx', '.json', '.csv']:
            double_ext = ext + ext
            if output_path.endswith(double_ext):
                output_path = output_path[:-len(ext)]
                break

        # 确保有正确的扩展名
        if not output_path.endswith(correct_ext):
            base_name = os.path.splitext(output_path)[0]
            output_path = base_name + correct_ext

        return output_path

    # ✅ ---------------- 装配查看和可视化功能 ----------------

    @Slot()
    def refresh_assemblies(self):
        """刷新装配列表"""
        try:
            self.main_window.set_status("正在加载装配列表...")

            # 从数据库获取所有装配
            assemblies = self.assembly_viewer. get_all_assemblies()

            # 更新UI
            self.main_window.populate_assembly_tree(assemblies)

            self.main_window.set_status(f"✅ 已加载 {len(assemblies)} 个装配")

        except Exception as e:
            self.main_window.show_error("加载装配列表失败", str(e))
            self.main_window.set_status("❌ 加载装配列表失败")
            import traceback
            traceback.print_exc()

    @Slot(str)
    def on_assembly_selected(self, assembly_id: str):
        """装配选中事件（单击装配）"""
        try:
            # 展开装配，显示部件列表
            nodes = self. assembly_viewer.get_assembly_nodes(assembly_id)
            self.main_window.populate_assembly_nodes(assembly_id, nodes)

            self.main_window.set_status(
                f"📦 装配包含 {len(nodes)} 个部件，双击装配名称可加载到3D视图"
            )

        except Exception as e:
            self.main_window.show_error("加载装配节点失败", str(e))
            import traceback
            traceback.print_exc()

    @Slot(str)
    def load_assembly(self, assembly_id: str):
        """加载装配到3D视图（双击装配）"""
        try:
            self.main_window.set_status("正在加载装配到3D视图...")

            # 获取装配的所有节点
            nodes = self.assembly_viewer.get_assembly_nodes(assembly_id)

            if not nodes:
                self.main_window.show_warning("空装配", "该装配没有部件")
                return

            # 清空当前3D视图
            self.part_visualizer.clear_all()

            # 逐个显示部件
            loaded_count = 0
            failed_count = 0

            for idx, node in enumerate(nodes, 1):
                # 更新进度
                self.main_window.set_status(
                    f"正在加载部件 {idx}/{len(nodes)}: {node['node_name']}..."
                )

                if node. get('step_uri'):
                    success = self.part_visualizer. display_node(
                        node['node_id'],
                        node['step_uri'],
                        transform=node.get('transform_json')
                    )

                    if success:
                        loaded_count += 1
                    else:
                        failed_count += 1
                else:
                    failed_count += 1

            # 刷新显示并适应视图
            self.part_visualizer.fit_all()

            # 保存当前状态
            self.current_assembly_id = assembly_id
            self. current_displayed_nodes = nodes

            # 显示结果
            status_msg = f"✅ 已加载装配:  {loaded_count}/{len(nodes)} 个部件"
            if failed_count > 0:
                status_msg += f"（{failed_count} 个失败）"

            self.main_window.set_status(status_msg)

            if loaded_count == 0:
                self.main_window.show_warning(
                    "加载失败",
                    f"无法加载任何部件\n可能原因：\n"
                    f"• STEP文件路径不正确\n"
                    f"• STEP文件已被删除或移动"
                )

        except Exception as e:
            self.main_window.show_error("加载装配失败", str(e))
            self.main_window.set_status("❌ 加载装配失败")
            import traceback
            traceback.print_exc()

    @Slot(str, str)
    def on_node_selected(self, assembly_id: str, node_id: str):
        """部件选中事件（单击部件）"""
        try:
            # 取消之前的高亮
            self.part_visualizer.unhighlight_all()

            # 高亮选中的部件
            self. part_visualizer.highlight_node(node_id)

            # 查找节点信息并显示
            for node in self.current_displayed_nodes:
                if node['node_id'] == node_id:
                    self.main_window.set_status(
                        f"✨ 选中: {node['node_name']} | "
                        f"零件:  {node['part_name']} v{node['version_no']}"
                    )
                    break

        except Exception as e:
            print(f"⚠️ 高亮部件失败: {e}")
            import traceback
            traceback.print_exc()

    def _resolve_step_path(self, step_uri: str) -> Optional[str]:
        """解析STEP文件路径（支持多种URI格式）"""
        if not step_uri:
            return None

        # ✅ 处理各种 URI 格式
        if step_uri.startswith('file:///'):
            # file:///D:/path/to/file. step
            step_path = step_uri[8:]
        elif step_uri.startswith('file://'):
            # ✅ 您的格式:  file://D:/solidworks/step/Barrel_bom_v1.step
            step_path = step_uri[7:]
        elif step_uri.startswith('file:'):
            # file:/path/to/file.step
            step_path = step_uri[5:]
        else:
            step_path = step_uri

        # ✅ Windows路径处理：将正斜杠转换为反斜杠
        step_path = step_path.replace('/', os.sep)

        print(f"[DEBUG] 解析URI: {step_uri}")
        print(f"[DEBUG] 转换后路径: {step_path}")
        print(f"[DEBUG] 文件存在: {os.path.exists(step_path)}")

        # 如果路径不存在，尝试在EXPORT_DIR中查找
        if not os.path.exists(step_path):
            filename = os.path.basename(step_path)
            export_dir = os.getenv("EXPORT_DIR", "exports")
            alternative_path = os.path.join(export_dir, filename)

            print(f"[DEBUG] 原路径不存在，尝试:  {alternative_path}")

            if os.path.exists(alternative_path):
                print(f"[DEBUG] ✅ 找到替代路径")
                return alternative_path

            return None

        return step_path

    def _export_part_from_database(self, part_version_id: str) -> Optional[str]:
        """从数据库导出零件STEP文件"""
        try:
            from ..db.mysql import get_conn
            from ..db.util import uuid_to_bin

            # 查询零件的几何数据
            sql = """
                  SELECT p.`key` as part_key, \
                         p.name  as part_name, \
                         pv.version_no, \
                         ga.uri  as step_uri, \
                         ga.data as step_data
                  FROM part_versions pv
                           JOIN parts p ON pv.part_id = p.id
                           LEFT JOIN geom_assets ga ON pv.cad_asset_id = ga.id
                  WHERE pv.id = %s \
                  """

            conn = get_conn()
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(sql, (uuid_to_bin(part_version_id),))
                row = cur.fetchone()

                if not row:
                    print(f"⚠️ 未找到零件版本:  {part_version_id}")
                    return None

                part_name = row['part_name']
                version_no = row['version_no']

                print(f"[DEBUG] 零件: {part_name}, 版本: {version_no}")

                # ✅ 策略1: 优先使用数据库中存储的URI
                if row.get('step_uri'):
                    print(f"[DEBUG] 数据库URI: {row['step_uri']}")
                    original_path = self._resolve_step_path(row['step_uri'])
                    if original_path and os.path.exists(original_path):
                        print(f"✅ 使用数据库路径: {original_path}")
                        return original_path
                    else:
                        print(f"⚠️ 数据库路径不存在:  {original_path}")

                # ✅ 策略2: 如果有BLOB数据，导出到文件
                if row.get('step_data'):
                    export_dir = os.getenv("EXPORT_DIR", "exports")
                    os.makedirs(export_dir, exist_ok=True)

                    # ✅ 使用与数据库一致的命名格式
                    filename = f"{part_name}_bom_v{version_no}.step"
                    output_path = os.path.join(export_dir, filename)

                    # 写入文件
                    with open(output_path, 'wb') as f:
                        f.write(row['step_data'])

                    print(f"✅ 从数据库BLOB导出:  {output_path}")
                    return output_path

                print(f"⚠️ 零件没有可用的STEP文件")
                return None

            finally:
                cur.close()
                conn.close()

        except Exception as e:
            print(f"⚠️ 从数据库导出零件失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    @Slot(str, str)
    def load_part_for_segmentation(self, part_version_id: str, step_uri: str):
        """加载零件进行几何分割"""
        try:
            print(f"\n{'=' * 60}")
            print(f"[加载零件] 开始")
            print(f"  零件版本ID: {part_version_id}")
            print(f"  STEP URI: {step_uri}")
            print(f"{'=' * 60}\n")

            self.main_window.set_status("正在加载零件...")

            # 1. 解析STEP文件路径
            step_path = self._resolve_step_path(step_uri)

            if not step_path or not os.path.exists(step_path):
                # 文件不存在 - 尝试从数据库重新导出
                print(f"⚠️ STEP文件不存在，尝试从数据库导出...")
                self.main_window.set_status("STEP文件不存在，正在从数据库重新导出...")
                step_path = self._export_part_from_database(part_version_id)

                if not step_path:
                    error_msg = (
                        f"❌ STEP文件未找到且无法从数据库导出\n\n"
                        f"原URI: {step_uri}\n"
                        f"解析后路径: {self._resolve_step_path(step_uri) or '无'}\n\n"
                        f"可能原因:\n"
                        f"• 文件已被移动或删除\n"
                        f"• 数据库中没有几何数据\n"
                        f"• 路径格式不正确\n\n"
                        f"建议:\n"
                        f"• 检查文件是否存在:  D:\\solidworks\\step\\\n"
                        f"• 检查 . env 中的 EXPORT_DIR 配置\n"
                        f"• 重新导入装配"
                    )
                    self.main_window.show_error("无法加载零件", error_msg)
                    return

            print(f"✅ 找到STEP文件: {step_path}")
            self.main_window.set_status(f"加载零件:  {os.path.basename(step_path)}")

            # 2. 加载STEP文件
            print(f"[加载STEP] {step_path}")
            shape = self.io_handler.load_step_model(step_path)
            print(f"✅ STEP文件加载成功")

            # 3. 几何分割
            print(f"[几何分割] 开始处理...")
            self.main_window.set_status("正在分割几何体...")
            self.primitives = self.processor.process_shape(shape)
            print(f"✅ 识别出 {len(self.primitives)} 个几何体")

            # 4. 清空修改历史
            self.modified_shapes.clear()
            self.preview_shapes.clear()
            self.current_file_path = step_path

            # 5. 显示结果
            self.main_window.set_primitives(self.primitives)

            # 6. 更新状态
            success_msg = (
                f"✅ 已加载并分割零件:  {os.path.basename(step_path)}\n"
                f"识别出 {len(self.primitives)} 个几何体"
            )
            self.main_window.set_status(success_msg)
            print(f"\n{success_msg}\n")

            # 7. 显示提示
            self.main_window.show_info(
                "零件已加载",
                f"✅ 零件已成功加载并分割\n\n"
                f"📁 文件:  {os.path.basename(step_path)}\n"
                f"🔧 识别的几何体: {len(self.primitives)} 个\n\n"
                f"💡 您现在可以:\n"
                f"  • 在左侧几何体列表中选择几何体\n"
                f"  • 在右侧参数面板中调整参数\n"
                f"  • 点击'应用修改'保存更改\n"
                f"  • 使用'文件 → 保存为STEP'导出修改后的零件"
            )

            print(f"{'=' * 60}")
            print(f"[加载零件] 完成")
            print(f"{'=' * 60}\n")

        except Exception as e:
            error_msg = f"加载零件失败:\n{str(e)}"
            self.main_window.show_error("加载失败", error_msg)
            self.main_window.set_status("❌ 加载零件失败")
            print(f"\n❌ 错误: {error_msg}\n")
            import traceback
            traceback.print_exc()

