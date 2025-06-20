# src/controller/app_controller.py
from typing import List, Dict, Any

from PySide6.QtCore import QObject, Slot, Signal

from ..model.geometry import GeometricPrimitive
from ..model.io import StepFileHandler
from ..model.segmentation import GeometrySegmentationProcessor
from ..view.main_window import MainWindow


class ApplicationController(QObject):
    """应用程序控制器 - 连接视图和模型"""

    def __init__(self, main_window: MainWindow):
        super().__init__()

        self.main_window = main_window
        self.io_handler = StepFileHandler()
        self.processor = GeometrySegmentationProcessor()
        self.primitives = []
        self.modified_shapes = {}

        # 设置回调
        self.processor.set_status_callback(self.main_window.set_status)
        self.processor.set_progress_callback(self.main_window.set_progress)

        # 连接信号
        self.main_window.open_file_requested.connect(self.open_file)
        self.main_window.save_file_requested.connect(self.save_file)
        self.main_window.modify_primitive_requested.connect(self.modify_primitive)
        self.main_window.undo_requested.connect(self.undo_modification)
        self.main_window.redo_requested.connect(self.redo_modification)

    @Slot(str)
    def open_file(self, file_path: str):
        """打开STEP文件并处理"""
        try:
            # 加载STEP文件
            self.main_window.set_status(f"正在加载文件: {file_path}")
            shape = self.io_handler.load_step_model(file_path)

            # 处理几何体分割
            self.primitives = self.processor.process_shape(shape)
            self.modified_shapes = {}

            # 更新UI
            self.main_window.set_primitives(self.primitives)

        except Exception as e:
            self.main_window.show_error("文件加载失败", f"无法加载文件: {str(e)}")
            self.main_window.set_status("文件加载失败")

    @Slot(str)
    def save_file(self, file_path: str):
        """保存修改后的模型"""
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
        """修改几何体参数"""
        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 尝试重建几何体
                new_shape = primitive.rebuild_with_parameters(parameters)

                # 保存到历史记录
                primitive.save_parameters_to_history(parameters)

                # 更新修改的形状
                self.modified_shapes[index] = new_shape

                # 更新UI
                self.main_window.update_primitive(index, new_shape)
                self.main_window.set_status(f"已修改 {primitive.type} #{index + 1}")

            except Exception as e:
                self.main_window.show_error("修改失败", f"参数应用失败: {str(e)}")

    @Slot(int)
    def undo_modification(self, index: int):
        """撤销几何体修改"""
        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 尝试撤销到上一个状态
                new_shape = primitive.undo()

                if new_shape:
                    # 更新修改的形状
                    self.modified_shapes[index] = new_shape

                    # 更新UI
                    self.main_window.update_primitive(index, new_shape)
                    self.main_window.set_status(f"已撤销 {primitive.type} #{index + 1} 的修改")

            except Exception as e:
                self.main_window.show_error("撤销失败", f"无法撤销修改: {str(e)}")

    @Slot(int)
    def redo_modification(self, index: int):
        """重做几何体修改"""
        if 0 <= index < len(self.primitives):
            primitive = self.primitives[index]

            try:
                # 尝试重做到下一个状态
                new_shape = primitive.redo()

                if new_shape:
                    # 更新修改的形状
                    self.modified_shapes[index] = new_shape

                    # 更新UI
                    self.main_window.update_primitive(index, new_shape)
                    self.main_window.set_status(f"已重做 {primitive.type} #{index + 1} 的修改")

            except Exception as e:
                self.main_window.show_error("重做失败", f"无法重做修改: {str(e)}")