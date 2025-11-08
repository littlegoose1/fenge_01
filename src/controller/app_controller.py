from typing import List, Dict, Any, Optional
import os

from PySide6.QtCore import QObject, Slot

from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.BRep import BRep_Builder

from ..model.geometry import GeometricPrimitive
from ..model.io import StepFileHandler
from ..model.segmentation import GeometrySegmentationProcessor
from ..view.main_window import MainWindow

from ..services.solver_service import SolveAssemblyWorker
from ..services.assembly_import_service import AssemblyImportService
from ..db.persistence_service import PersistenceService


class ApplicationController(QObject):
    """
    应用程序控制器
    - 舍弃 XCAF，仅使用 flat-split 拆分并入库（含规范几何去重）
    - 打开/保存、参数修改与预览、撤销/重做
    - 导出当前零部件到数据库
    - 装配求解（后台线程）
    """

    def __init__(self, main_window: MainWindow):
        super().__init__()

        # 强制 flat-split 模式，保证稳定导入
        os.environ["ASSEMBLY_IMPORT_FORCE_FLAT"] = "1"
        os.environ["ASSEMBLY_IMPORT_SPLIT_SOLIDS"] = "1"
        # 可选调试
        # os.environ["ASSEMBLY_IMPORT_DEBUG"] = "1"

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

        # 后台 workers
        self._workers: list[SolveAssemblyWorker] = []

        # 处理器回调接入 UI
        self.processor.set_status_callback(self.main_window.set_status)
        self.processor.set_progress_callback(self.main_window.set_progress)

        # 信号连接
        self.main_window.open_file_requested.connect(self.open_file)
        self.main_window.save_file_requested.connect(self.save_file)
        self.main_window.modify_primitive_requested.connect(self.modify_primitive)
        self.main_window.update_preview_requested.connect(self.update_preview)
        self.main_window.undo_requested.connect(self.undo_modification)
        self.main_window.redo_requested.connect(self.redo_modification)
        self.main_window.solve_assembly_requested.connect(self.solve_assembly)
        self.main_window.export_part_to_db_requested.connect(self.export_part_to_db)
        self.main_window.import_assembly_requested.connect(self.import_and_store_assembly)

    # ---------------- 文件打开/保存 ----------------
    @Slot(str)
    def open_file(self, file_path: str):
        try:
            self.current_file_path = file_path
            self.main_window.set_status(f"正在加载文件: {file_path}")

            shape = self.io_handler.load_step_model(file_path)
            self.primitives = self.processor.process_shape(shape)

            self.modified_shapes.clear()
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
                self.main_window.show_error("保存失败", "无法保存文件，请检查路径和权限")
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
                if not primitive.has_significant_changes(primitive.get_params(), parameters):
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
                self.main_window.show_original_with_preview(index, new_shape, preview_shape)
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
                    preview_shape = self.preview_shapes[index]
                elif hasattr(primitive, "create_preview_shape"):
                    try:
                        preview_shape = primitive.create_preview_shape(primitive.get_params())
                        if preview_shape:
                            self.preview_shapes[index] = preview_shape
                    except Exception as e:
                        print(f"[preview] 创建预览形状失败: {e}")

            if show_preview and preview_shape:
                self.main_window.show_original_with_preview(index, current_shape, preview_shape)
            else:
                self.main_window.update_primitive(index, current_shape)
        except Exception as e:
            print(f"[preview] 更新预览失败: {e}")

    @Slot(int)
    def undo_modification(self, index: int):
        if not (0 <= index < len(self.primitives)):
            return
        primitive = self.primitives[index]
        try:
            if hasattr(primitive, "undo"):
                new_shape = primitive.undo()
            else:
                new_shape = None
            if new_shape:
                self.modified_shapes[index] = new_shape
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
                new_shape = primitive.redo()
            else:
                new_shape = None
            if new_shape:
                self.modified_shapes[index] = new_shape
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

    @Slot()
    def export_part_to_db(self):
        if not self.primitives:
            self.main_window.show_error("无数据", "请先打开并解析一个零部件。")
            return

        try:
            part_shape = self._compose_part_shape()
            base = os.path.splitext(os.path.basename(self.current_file_path or "unnamed"))[0]
            part_key = base
            part_name = base

            params_snapshot: Dict[str, Any] = {
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
                meta_asset={"source": "gui", "file": self.current_file_path or ""},
                meta_version={"ui": "pyside6"},
            )

            self.main_window.show_info(
                "导出成功",
                f"已保存零部件版本 v{result['version_no']}\n路径: {result['step_path']}"
            )
            self.main_window.set_status(f"已入库零部件 v{result['version_no']}")
        except Exception as e:
            self.main_window.show_error("导出失败", f"保存零部件到数据库失败：{e}")

    # ---------------- 导入（flat-split canonical）并入库 ----------------
    @Slot(str)
    def import_and_store_assembly(self, step_path: str):
        try:
            self.main_window.set_status(f"开始导入：{step_path}")
            result = self.assembly_importer.import_step_assembly(step_path)
            asm_id = result["assembly_id"]
            node_count = len(result["nodes"])
            mode = result.get("mode", "flat-split-canonical")

            self.main_window.show_info(
                "导入完成",
                f"模式: {mode}\n装配ID: {asm_id}\n零部件数: {node_count}"
            )
            self.main_window.set_status(f"导入完成（{mode}，节点: {node_count}）")

            for n in result["nodes"][:10]:
                print("[IMPORT_NODE]", n)
        except Exception as e:
            self.main_window.show_error("导入失败", str(e))
            self.main_window.set_status("导入失败")

    # ---------------- 装配求解（后台线程） ----------------
    @Slot(str, int)
    def solve_assembly(self, assembly_id: str, iterations: int):
        asm_id = assembly_id or None
        worker = SolveAssemblyWorker(asm_id, iterations, self)
        self._workers.append(worker)

        def on_finished(success: bool, message: str, used_asm_id: str):
            if success:
                self.main_window.show_info("求解完成", message)
                self.main_window.set_status(
                    f"求解完成（装配: {used_asm_id or '最新'}，迭代: {iterations}）"
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
            f"开始求解装配（装配: {asm_id or '最新'}，迭代: {iterations}）"
        )
        worker.start()