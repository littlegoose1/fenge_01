# src/controller/app_controller.py
from typing import List, Dict, Any

from PySide6.QtCore import QObject, Slot, Signal

from ..model.geometry import GeometricPrimitive
from ..model.io import StepFileHandler
from ..model.segmentation import GeometrySegmentationProcessor
from ..view.main_window import MainWindow
from ..services.solver_service import SolveAssemblyWorker  # 新增导入


class ApplicationController(QObject):
    """
    应用程序控制器 - 连接视图和模型
    """

    def __init__(self, main_window: MainWindow):
        super().__init__()

        self.main_window = main_window
        self.io_handler = StepFileHandler()
        self.processor = GeometrySegmentationProcessor()
        self.primitives = []
        self.modified_shapes = {}
        self.preview_shapes = {}  # 存储预览形状

        # 设置回调
        self.processor.set_status_callback(self.main_window.set_status)
        self.processor.set_progress_callback(self.main_window.set_progress)

        # 连接信号
        self.main_window.open_file_requested.connect(self.open_file)
        self.main_window.save_file_requested.connect(self.save_file)
        self.main_window.modify_primitive_requested.connect(self.modify_primitive)
        self.main_window.update_preview_requested.connect(self.update_preview)  # 连接预览信号
        self.main_window.undo_requested.connect(self.undo_modification)
        self.main_window.redo_requested.connect(self.redo_modification)
        self.main_window.solve_assembly_requested.connect(self.solve_assembly)  # 新增

        # 保存后台任务引用，避免被回收
        self._workers: list[SolveAssemblyWorker] = []

    @Slot(str)
    def open_file(self, file_path: str):
        """
        打开STEP文件并处理
        """
        try:
            # 加载STEP文件
            self.main_window.set_status(f"正在加载文件: {file_path}")
            shape = self.io_handler.load_step_model(file_path)

            # 处理几何体分割
            self.primitives = self.processor.process_shape(shape)
            self.modified_shapes = {}
            self.preview_shapes = {}  # 清除预览缓存

            # 更新UI
            self.main_window.set_primitives(self.primitives)

        except Exception as e:
            self.main_window.show_error("文件加载失败", f"无法加载文件: {str(e)}")
            self.main_window.set_status("文件加载失败")

    @Slot(str)
    def save_file(self, file_path: str):
        """
        保存修改后的模型
        """
        try:
            success = self.io_handler.export_primitives(
                self.primitives, self.modified_shapes, file_path)

            if success:
                self.main_window.show_info("保存成功", f"模型已保存到: {file_path}")
                self.main_window.set_status(f"保存成功: {file_path}")
            else:
                self.main_window.show_error("保存失败", "无法保存文件，请检查路径和权限")

        except Exception as e:
            self.main_window.show_error("保存失败", f"保存文件时出错: {str(e)}")
            self.main_window.set_status("保存失败")

    @Slot(int, dict)
    def modify_primitive(self, index: int, parameters: Dict[str, Any]):
        """
        修改几何体参数
        """
        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 添加调试输出
                print(f"修改几何体 {index}，参数：{parameters}")
                # 提取预览标志
                show_preview = parameters.pop("show_preview", True) if isinstance(parameters, dict) else True
                print(f"预览状态: {show_preview}")

                # 检查参数是否有实际变化
                has_changes = primitive.has_significant_changes(primitive.get_params(), parameters)

                if not has_changes:
                    self.main_window.show_info("无变化", "参数没有实质性变化，无需更新")
                    return

                # 尝试重建几何体
                new_shape = primitive.rebuild_with_parameters(parameters)

                # 创建预览形状（如果支持）
                preview_shape = None
                if show_preview and hasattr(primitive, "create_preview_shape"):
                    try:
                        preview_shape = primitive.create_preview_shape(parameters)
                        # 保存预览形状
                        if preview_shape:
                            self.preview_shapes[index] = preview_shape
                    except Exception as e:
                        print(f"创建预览形状失败: {str(e)}")

                # 保存到历史记录
                if hasattr(primitive, "save_parameters_to_history"):
                    primitive.save_parameters_to_history(parameters)

                # 更新修改的形状
                self.modified_shapes[index] = new_shape

                # 更新UI
                if show_preview and preview_shape:
                    # 显示原始形状和预览
                    self.main_window.show_original_with_preview(index, new_shape, preview_shape)
                else:
                    # 只显示原始形状
                    self.main_window.update_primitive(index, new_shape)

                self.main_window.set_status(f"已修改 {primitive.type} #{index + 1}")

            except Exception as e:
                self.main_window.show_error("修改失败", f"参数应用失败: {str(e)}")

    @Slot(int, bool)
    def update_preview(self, index: int, show_preview: bool):
        """
        更新预览显示状态
        """
        print(f"控制器收到预览更新请求：索引 {index}, 预览状态: {show_preview}")

        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 获取当前形状
                current_shape = self.modified_shapes.get(index, primitive.original_shape)

                # 获取或创建预览形状
                preview_shape = None
                if show_preview:
                    print("尝试获取预览形状")
                    # 检查是否已缓存预览形状
                    if index in self.preview_shapes:
                        preview_shape = self.preview_shapes[index]
                    # 否则尝试创建新的预览形状
                    elif hasattr(primitive, "create_preview_shape"):
                        try:
                            preview_shape = primitive.create_preview_shape(primitive.get_params())
                            if preview_shape:
                                self.preview_shapes[index] = preview_shape
                        except Exception as e:
                            print(f"创建预览形状失败: {str(e)}")

                # 更新显示
                if show_preview and preview_shape:
                    self.main_window.show_original_with_preview(index, current_shape, preview_shape)
                else:
                    self.main_window.update_primitive(index, current_shape)

            except Exception as e:
                print(f"更新预览失败: {str(e)}")

    @Slot(int)
    def undo_modification(self, index: int):
        """
        撤销几何体修改
        """
        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 尝试撤销到上一个状态
                new_shape = primitive.undo()

                if new_shape:
                    # 更新修改的形状
                    self.modified_shapes[index] = new_shape

                    # 清除预览形状
                    if index in self.preview_shapes:
                        del self.preview_shapes[index]

                    # 更新UI
                    self.main_window.update_primitive(index, new_shape)
                    self.main_window.set_status(f"已撤销 {primitive.type} #{index + 1} 的修改")

            except Exception as e:
                self.main_window.show_error("撤销失败", f"无法撤销修改: {str(e)}")

    @Slot(int)
    def redo_modification(self, index: int):
        """
        重做几何体修改
        """
        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 尝试重做到下一个状态
                new_shape = primitive.redo()

                if new_shape:
                    # 更新修改的形状
                    self.modified_shapes[index] = new_shape

                    # 清除预览形状
                    if index in self.preview_shapes:
                        del self.preview_shapes[index]

                    # 更新UI
                    self.main_window.update_primitive(index, new_shape)
                    self.main_window.set_status(f"已重做 {primitive.type} #{index + 1} 的修改")

            except Exception as e:
                self.main_window.show_error("重做失败", f"无法重做修改: {str(e)}")

    @Slot(str, int)
    def solve_assembly(self, assembly_id: str, iterations: int):
        """
        启动‘求解装配’后台任务
        """
        asm_id = assembly_id or None
        worker = SolveAssemblyWorker(asm_id, iterations, self)
        self._workers.append(worker)

        def on_finished(success: bool, message: str, used_asm_id: str):
            # 弹窗提示并更新状态栏
            if success:
                self.main_window.show_info("求解完成", message)
                self.main_window.set_status(f"求解完成（装配: {used_asm_id or '最新'}，迭代: {iterations}）")
            else:
                self.main_window.show_error("求解失败", message)
                self.main_window.set_status("求解失败")
            # 回收 worker 引用
            try:
                self._workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(on_finished)
        self.main_window.set_status(f"开始求解装配（装配: {asm_id or '最新'}，迭代: {iterations}）")
        worker.start()