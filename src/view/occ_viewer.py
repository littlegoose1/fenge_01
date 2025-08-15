# src/view/occ_viewer.py
from typing import List, Dict, Optional
import sys
import os
import traceback

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox

# 首先加载后端
try:
    from OCC.Display.backend import load_backend, get_qt_modules

    load_backend("pyside6")

    # 确认后端已加载
    QtCore, QtGui, QtWidgets, QtOpenGL = get_qt_modules()
    print("成功加载 PySide6 后端")
except Exception as backend_error:
    print(f"警告: 无法加载 PySide6 后端: {backend_error}")
    try:
        # 加载其他可用后端
        available_backends = ["pyqt6", "pyside2", "pyqt5"]
        for backend in available_backends:
            try:
                load_backend(backend)
                print(f"使用 {backend} 后端替代")
                break
            except:
                continue
    except Exception as fallback_error:
        print(f"错误: 无法加载任何Qt后端: {fallback_error}")

# 加载显示模块
try:
    from OCC.Display.qtDisplay import qtViewer3d
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB, Quantity_NOC_GRAY90
    from OCC.Core.AIS import AIS_Shape, AIS_Trihedron
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCC.Core.Geom import Geom_Axis2Placement  # 添加这一行导入
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face

    # 不直接导入Aspect_GDM_STRETCH, 因为它可能不存在
    DISPLAY_AVAILABLE = True
except Exception as import_error:
    print(f"错误: 无法导入OCC显示模块: {import_error}")
    DISPLAY_AVAILABLE = False

from ..model.geometry import GeometricPrimitive


class OCCViewer(QWidget):
    """OpenCASCADE 3D显示组件 - 适用于OCCT 7.9.0"""

    selection_changed = Signal(int)  # 选择变化信号

    def __init__(self, parent=None):
        super().__init__(parent)

        # 检查显示模块是否可用
        if not DISPLAY_AVAILABLE:
            layout = QVBoxLayout()
            layout.addWidget(QWidget())
            self.setLayout(layout)
            QMessageBox.critical(self, "显示初始化失败",
                                 "无法初始化3D显示组件。\n请检查PythonOCC安装是否正确。")
            self.display = None
            return

        # 初始化3D显示
        try:
            self.canvas = qtViewer3d(self)
            self.display = self.canvas._display

            # 界面布局
            layout = QVBoxLayout()
            layout.addWidget(self.canvas)
            layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(layout)

            # 显示设置 - 使用更简单的方法设置背景
            try:
                # 适用于OCCT 7.9.0的背景颜色设置
                bg_color = Quantity_Color(0.9, 0.9, 0.9, Quantity_TOC_RGB)
                self.display.View.SetBackgroundColor(bg_color)
            except Exception as e:
                print(f"警告: 无法设置背景颜色: {e}")
                traceback.print_exc()

            # 设置显示模式
            self.display.SetModeShaded()

            # 显示坐标轴 - 适用于OCCT 7.9.0
            try:
                origin = gp_Pnt(0, 0, 0)
                xDir = gp_Dir(1, 0, 0)
                ax2 = gp_Ax2(origin, gp_Dir(0, 0, 1), xDir)
                ax2placement = Geom_Axis2Placement(ax2)
                trihedron = AIS_Trihedron(ax2placement)
                self.display.Context.Display(trihedron, True)
                self._trihedron = trihedron
                self._trihedron_visible = True
            except Exception as e:
                print(f"警告: 无法显示坐标轴: {e}")
                traceback.print_exc()
                self._trihedron = None
                self._trihedron_visible = False

            # 初始化形状管理
            self.primitives = []
            self.displayed_shapes = {}  # 索引到AIS_Shape的映射
            self.modified_shapes = {}  # 存储修改后的形状
            self.current_colors = {}
            self.selected_index = -1

            # 设置鼠标操作
            self._setup_mouse_events()

        except Exception as e:
            print(f"错误: 3D显示初始化失败: {e}")
            traceback.print_exc()
            self.display = None
            QMessageBox.critical(self, "显示初始化失败", f"3D显示组件初始化失败:\n{str(e)}")

    def _setup_mouse_events(self):
        """设置鼠标事件处理"""
        self.canvas.setMouseTracking(True)
        self.canvas.mousePressEvent = self.mousePressEvent

    def mousePressEvent(self, event):
        """处理鼠标点击事件，实现形状选择 - 适用于OCCT 7.9.0"""
        if self.display is None:
            return super().mousePressEvent(event)

        if event.button() == Qt.LeftButton:
            # 获取鼠标位置
            x, y = event.position().x(), event.position().y()

            # 在OCCT 7.9.0中正确执行选择
            try:
                # 先移动到鼠标位置
                self.display.MoveTo(int(x), int(y))

                # 执行选择 - 在OCCT 7.9.0中，这个方法接受一个布尔参数表示是否更新视图
                self.display.Context.Select(True)

                # 检查是否有选中的对象
                if self.display.Context.NbSelected() > 0:
                    # 尝试找到选中的几何体索引
                    for i in range(len(self.primitives)):
                        if i in self.displayed_shapes:
                            # 检查该形状是否被选中
                            if self._is_shape_selected(self.displayed_shapes[i]):
                                self.select_primitive(i)
                                break
                    else:
                        # 如果没有找到对应的几何体，清除选择
                        self.clear_selection()
                else:
                    # 没有选中任何对象，清除选择
                    self.clear_selection()
            except Exception as e:
                print(f"选择操作失败: {e}")
                traceback.print_exc()

        # 保留原始事件处理
        return super().mousePressEvent(event)

    def _is_shape_selected(self, ais_shape):
        """检查一个AIS_Shape是否被选中 - 适用于OCCT 7.9.0"""
        try:
            # 在OCCT 7.9.0中，可以直接检查对象是否被选中
            return self.display.Context.IsSelected(ais_shape)
        except Exception as e:
            print(f"警告: 检查形状选择状态失败: {e}")
            return False

    def display_primitives(self, primitives: List[GeometricPrimitive]):
        """显示几何体列表 - 适用于OCCT 7.9.0"""
        if self.display is None:
            return

        self.primitives = primitives
        self.displayed_shapes.clear()
        self.current_colors.clear()

        try:
            self.display.EraseAll()

            # 定义颜色数组
            occ_colors = [
                Quantity_Color(1.0, 0.0, 0.0, Quantity_TOC_RGB),  # 红色
                Quantity_Color(0.0, 1.0, 0.0, Quantity_TOC_RGB),  # 绿色
                Quantity_Color(0.0, 0.0, 1.0, Quantity_TOC_RGB),  # 蓝色
                Quantity_Color(1.0, 1.0, 0.0, Quantity_TOC_RGB),  # 黄色
                Quantity_Color(1.0, 0.0, 1.0, Quantity_TOC_RGB),  # 紫色
                Quantity_Color(0.0, 1.0, 1.0, Quantity_TOC_RGB),  # 青色
                Quantity_Color(0.9, 0.5, 0.0, Quantity_TOC_RGB),  # 橙色
            ]

            # 添加每个几何体
            for i, primitive in enumerate(primitives):
                color = occ_colors[i % len(occ_colors)]
                self.current_colors[i] = color
                transparency = 0.1

                # 如果有修改后的形状，显示修改后的
                if i in self.modified_shapes:
                    shape = AIS_Shape(self.modified_shapes[i])
                    self.display.Context.SetColor(shape, color, False)
                    self.display.Context.SetTransparency(shape, transparency, False)
                    self.display.Context.Display(shape, False)
                    self.displayed_shapes[i] = shape  # 在OCCT 7.9.0中直接存储AIS_Shape对象
                else:
                    # 否则显示原始面
                    first_face = True  # 标记第一个面
                    for face in primitive.faces:
                        shape = AIS_Shape(face)
                        self.display.Context.SetColor(shape, color, False)
                        self.display.Context.SetTransparency(shape, transparency, False)
                        self.display.Context.Display(shape, False)

                        # 只将第一个面作为几何体的代表
                        if first_face and i not in self.displayed_shapes:
                            self.displayed_shapes[i] = shape
                            first_face = False

            # 更新视图
            self.display.View_Iso()
            self.display.FitAll()
            self.display.Repaint()
        except Exception as e:
            print(f"显示几何体失败: {e}")
            traceback.print_exc()

    def update_primitive(self, index, new_shape):
        """更新特定几何体的显示 - 适用于OCCT 7.9.0"""
        if self.display is None:
            return False

        if index < 0 or index >= len(self.primitives):
            return False

        try:
            # 存储新形状
            self.modified_shapes[index] = new_shape

            # 重新显示所有几何体
            self.display_primitives(self.primitives)

            # 重新选择当前选中的几何体
            if self.selected_index == index:
                self.select_primitive(index)

            return True
        except Exception as e:
            print(f"更新几何体失败: {e}")
            traceback.print_exc()
            return False

    def select_primitive(self, index):
        """选择特定几何体 - 适用于OCCT 7.9.0"""
        if self.display is None:
            return

        if index < 0 or index >= len(self.primitives):
            return

        try:
            # 清除之前的高亮
            self.clear_selection()

            # 高亮选中的几何体
            if index in self.displayed_shapes:
                shape = self.displayed_shapes[index]

                # 在OCCT 7.9.0中选择对象
                self.display.Context.AddOrRemoveSelected(shape, False)  # 先清除之前的选择
                self.display.Context.AddOrRemoveSelected(shape, True)  # 添加新的选择

                self.selected_index = index

                # 发出选择变化信号
                self.selection_changed.emit(index)
        except Exception as e:
            print(f"选择几何体失败: {e}")
            traceback.print_exc()

    def clear_selection(self):
        """清除选择 - 适用于OCCT 7.9.0"""
        if self.display is None:
            return -1

        if self.selected_index >= 0:
            try:
                # 在OCCT 7.9.0中清除选择
                self.display.Context.ClearSelected(True)

                old_index = self.selected_index
                self.selected_index = -1

                # 发出选择变化信号
                self.selection_changed.emit(-1)

                return old_index
            except Exception as e:
                print(f"清除选择失败: {e}")
                traceback.print_exc()
        return -1

    # 其余视图控制方法保持不变...
    def fit_all(self):
        """适应视图以显示所有对象"""
        if self.display:
            try:
                self.display.FitAll()
            except Exception as e:
                print(f"视图缩放失败: {e}")

    def view_top(self):
        """顶视图"""
        if self.display:
            try:
                self.display.View_Top()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def view_bottom(self):
        """底视图"""
        if self.display:
            try:
                self.display.View_Bottom()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def view_left(self):
        """左视图"""
        if self.display:
            try:
                self.display.View_Left()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def view_right(self):
        """右视图"""
        if self.display:
            try:
                self.display.View_Right()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def view_front(self):
        """前视图"""
        if self.display:
            try:
                self.display.View_Front()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def view_rear(self):
        """后视图"""
        if self.display:
            try:
                self.display.View_Rear()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def view_iso(self):
        """等轴测视图"""
        if self.display:
            try:
                self.display.View_Iso()
            except Exception as e:
                print(f"切换视图失败: {e}")

    def set_display_mode_wireframe(self):
        """设置线框显示模式"""
        if self.display:
            try:
                self.display.SetModeWireFrame()
            except Exception as e:
                print(f"切换显示模式失败: {e}")

    def set_display_mode_shaded(self):
        """设置着色显示模式"""
        if self.display:
            try:
                self.display.SetModeShaded()
            except Exception as e:
                print(f"切换显示模式失败: {e}")

    def toggle_grid(self, state: bool):
        """切换网格显示"""
        if self.display is None:
            return

        try:
            # OCCT 7.9.0中切换网格显示
            from OCC.Core.Graphic3d import Graphic3d_RenderingParams
            params = self.display.View.RenderingParams()
            params.ShowGrid = state
            self.display.View.SetRenderingParams(params)
            self.display.Repaint()
        except Exception as e:
            print(f"警告: 无法切换网格显示: {e}")
            traceback.print_exc()

    def toggle_axes(self, state: bool):
        """切换坐标轴显示"""
        if self.display is None or self._trihedron is None:
            return

        try:
            # OCCT 7.9.0中切换坐标轴显示
            if state and not self._trihedron_visible:
                self.display.Context.Display(self._trihedron, True)
                self._trihedron_visible = True
            elif not state and self._trihedron_visible:
                self.display.Context.Erase(self._trihedron, True)
                self._trihedron_visible = False

            self.display.Repaint()
        except Exception as e:
            print(f"警告: 无法切换坐标轴显示: {e}")
            traceback.print_exc()

    def show_original_with_preview(self, geometry_id, original_shape, preview_shape):
        """显示原始形状和预览形状"""
        if self.display is None:
            return

        try:
            # 清除之前的显示
            self.display.EraseAll()

            # 显示所有几何体
            for i, primitive in enumerate(self.primitives):
                if i == geometry_id:
                    # 显示当前编辑的几何体的原始形状
                    self.display.DisplayShape(original_shape, color="BLUE", update=False)

                    # 如果有预览形状，以半透明方式显示
                    if preview_shape:
                        # 显示预览形状
                        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
                        preview_color = Quantity_Color(0.0, 0.8, 0.2, Quantity_TOC_RGB)  # 绿色
                        self.display.DisplayShape(preview_shape, color=preview_color,
                                                  transparency=0.7, update=False)
                else:
                    # 显示其他几何体
                    for face in primitive.faces:
                        self.display.DisplayShape(face, update=False)

            # 更新显示
            self.display.FitAll()
            self.display.Repaint()

        except Exception as e:
            print(f"显示预览失败: {str(e)}")