# src/view/occ_viewer.py
from typing import List, Dict, Optional
import sys
import os

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
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCC.Core.AIS import AIS_Shape, AIS_Trihedron
    from OCC.Core.gp import gp_Pnt, gp_Dir, gp_Ax2

    # 不直接导入Aspect_GDM_STRETCH, 因为它可能不存在
    DISPLAY_AVAILABLE = True
except Exception as import_error:
    print(f"错误: 无法导入OCC显示模块: {import_error}")
    DISPLAY_AVAILABLE = False

from ..model.geometry import GeometricPrimitive


class OCCViewer(QWidget):
    """OpenCASCADE 3D显示组件 - 修订版"""

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
                # 尝试设置纯色背景 - 更兼容各种版本
                from OCC.Core.Quantity import Quantity_NOC_GRAY90
                self.display.View.SetBackgroundColor(Quantity_NOC_GRAY90)
            except Exception as e:
                print(f"警告: 无法设置背景颜色: {e}")
                try:
                    # 尝试使用RGB值
                    bg_color = Quantity_Color(0.9, 0.9, 0.9, Quantity_TOC_RGB)
                    self.display.View.SetBackgroundColor(bg_color)
                except Exception as e2:
                    print(f"警告: 无法设置背景颜色(备选方法): {e2}")

            # 设置显示模式
            self.display.SetModeShaded()

            # 显示坐标轴
            try:
                # 使用AIS_Trihedron显示坐标轴
                origin = gp_Pnt(0, 0, 0)
                xDir = gp_Dir(1, 0, 0)
                ax2 = gp_Ax2(origin, gp_Dir(0, 0, 1), xDir)
                trihedron = AIS_Trihedron(ax2)
                self.display.Context.Display(trihedron, True)
                self._trihedron = trihedron  # 保存引用以便稍后擦除
                self._trihedron_visible = True
            except Exception as e:
                print(f"警告: 无法显示坐标轴: {e}")
                self._trihedron = None
                self._trihedron_visible = False

            # 初始化形状管理
            self.primitives = []
            self.displayed_shapes = {}
            self.modified_shapes = {}
            self.current_colors = {}
            self.selected_index = -1

            # 设置鼠标操作
            self._setup_mouse_events()

        except Exception as e:
            print(f"错误: 3D显示初始化失败: {e}")
            import traceback
            traceback.print_exc()
            self.display = None
            QMessageBox.critical(self, "显示初始化失败", f"3D显示组件初始化失败:\n{str(e)}")

    def _setup_mouse_events(self):
        """设置鼠标事件处理"""
        self.canvas.setMouseTracking(True)
        self.canvas.mousePressEvent = self.mousePressEvent

    def mousePressEvent(self, event):
        """处理鼠标点击事件，实现形状选择"""
        if self.display is None:
            return super().mousePressEvent(event)

        if event.button() == Qt.LeftButton:
            # 获取鼠标位置
            x, y = event.position().x(), event.position().y()

            # 尝试选择对象
            try:
                self.display.Select(x - 5, y - 5, x + 5, y + 5)
                selected = []
                try:
                    selected = self.display.selected_shapes
                except AttributeError:
                    # 尝试替代方法获取选择
                    try:
                        selected = [self.display.GetSelectedShape()]
                    except:
                        pass

                if selected and any(selected):
                    # 找到对应的原始几何体
                    for i, shape_id in self.displayed_shapes.items():
                        if shape_id in selected:
                            self.select_primitive(i)
                            break
                else:
                    # 清除选择
                    self.clear_selection()
            except Exception as e:
                print(f"选择操作失败: {e}")

        # 保留原始事件处理
        return super().mousePressEvent(event)

    def display_primitives(self, primitives: List[GeometricPrimitive]):
        """显示几何体列表"""
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
                    self.displayed_shapes[i] = shape.GetHandle()
                else:
                    # 否则显示原始面
                    for face in primitive.faces:
                        shape = AIS_Shape(face)
                        self.display.Context.SetColor(shape, color, False)
                        self.display.Context.SetTransparency(shape, transparency, False)
                        self.display.Context.Display(shape, False)
                        if i not in self.displayed_shapes:
                            self.displayed_shapes[i] = shape.GetHandle()

            # 更新视图
            self.display.View_Iso()
            self.display.FitAll()
            self.display.Repaint()
        except Exception as e:
            print(f"显示几何体失败: {e}")

    def update_primitive(self, index, new_shape):
        """更新特定几何体的显示"""
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
            return False

    def select_primitive(self, index):
        """选择特定几何体"""
        if self.display is None:
            return

        if index < 0 or index >= len(self.primitives):
            return

        try:
            # 清除之前的高亮
            self.clear_selection()

            # 高亮选中的几何体
            if index in self.displayed_shapes:
                shape_handle = self.displayed_shapes[index]
                try:
                    self.display.Context.SetSelected(shape_handle, True)
                except Exception as e:
                    print(f"警告: 无法选择形状: {e}")

                self.selected_index = index

                # 发出选择变化信号
                self.selection_changed.emit(index)
        except Exception as e:
            print(f"选择几何体失败: {e}")

    def clear_selection(self):
        """清除选择"""
        if self.display is None:
            return -1

        if self.selected_index >= 0:
            try:
                # 取消选中状态
                if self.selected_index in self.displayed_shapes:
                    shape_handle = self.displayed_shapes[self.selected_index]
                    try:
                        self.display.Context.Unhilight(shape_handle, False)
                    except Exception as e:
                        print(f"警告: 无法取消高亮: {e}")

                old_index = self.selected_index
                self.selected_index = -1

                # 发出选择变化信号
                self.selection_changed.emit(-1)

                return old_index
            except Exception as e:
                print(f"清除选择失败: {e}")
        return -1

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
            # 尝试多种方法切换网格
            try:
                # 方法1: 使用Graphic3d模块
                from OCC.Core.Graphic3d import Graphic3d_RenderingParams
                params = self.display.View.RenderingParams()
                params.ShowGrid = state
                self.display.View.SetRenderingParams(params)
            except:
                # 方法2: 直接设置网格显示
                try:
                    if state:
                        self.display.View.SetGridOn()
                    else:
                        self.display.View.SetGridOff()
                except:
                    # 方法3: 使用SetGridEcho
                    self.display.View.SetGridEcho(state)

            self.display.Repaint()
        except Exception as e:
            print(f"警告: 无法切换网格显示: {e}")

    def toggle_axes(self, state: bool):
        """切换坐标轴显示"""
        if self.display is None or self._trihedron is None:
            return

        try:
            if state and not self._trihedron_visible:
                self.display.Context.Display(self._trihedron, True)
                self._trihedron_visible = True
            elif not state and self._trihedron_visible:
                self.display.Context.Erase(self._trihedron, True)
                self._trihedron_visible = False

            self.display.Repaint()
        except Exception as e:
            print(f"警告: 无法切换坐标轴显示: {e}")