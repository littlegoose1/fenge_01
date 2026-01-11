"""
零件3D可视化服务（使用现有的OCC Display）
"""
import os
import json
from typing import Optional, Dict, Any, List
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.AIS import AIS_Shape
from OCC.Core.gp import gp_Trsf, gp_Quaternion, gp_Vec


class PartVisualizer:
    """零件3D可视化器"""

    def __init__(self, display):
        """
        Args:
            display: OCC Display对象（从 canvas._display 获取）
        """
        self.display = display
        self.loaded_shapes: Dict[str, AIS_Shape] = {}  # node_id -> AIS_Shape
        self.colors = [
            (0.8, 0.2, 0.2),  # 红色
            (0.2, 0.8, 0.2),  # 绿色
            (0.2, 0.2, 0.8),  # 蓝色
            (0.8, 0.8, 0.2),  # 黄色
            (0.8, 0.2, 0.8),  # 品红
            (0.2, 0.8, 0.8),  # 青色
            (0.9, 0.5, 0.2),  # 橙色
            (0.5, 0.2, 0.9),  # 紫色
        ]
        self.color_index = 0

    def load_step_file(self, step_path: str) -> Optional[TopoDS_Shape]:
        """加载STEP文件"""
        # 处理 file: // URI
        if step_path.startswith('file://'):
            step_path = step_path[7:].replace('/', os.sep)

        if not os.path.exists(step_path):
            print(f"⚠️ STEP文件不存在: {step_path}")
            return None

        try:
            reader = STEPControl_Reader()
            status = reader.ReadFile(step_path)

            if status != IFSelect_RetDone:
                print(f"⚠️ 无法读取STEP文件:  {step_path}")
                return None

            reader.TransferRoots()
            shape = reader.OneShape()

            return shape

        except Exception as e:
            print(f"⚠️ 加载STEP文件失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def display_node(
            self,
            node_id: str,
            step_path: str,
            transform: Optional[str] = None,  # JSON字符串
            color: Optional[tuple] = None,
            transparency: float = 0.0
    ) -> bool:
        """
        显示节点

        Args:
            node_id: 节点ID
            step_path: STEP文件路径或URI
            transform: 变换JSON字符串 '{"pos": [x,y,z], "quat": [w,x,y,z]}'
            color: RGB颜色 (r, g, b) 范围0-1
            transparency:  透明度 0-1
        """
        # 加载几何
        shape = self.load_step_file(step_path)
        if not shape:
            return False

        try:
            # 解析变换
            if transform:
                if isinstance(transform, str):
                    transform = json.loads(transform)
                shape = self._apply_transform(shape, transform)

            # 创建AIS形状
            ais_shape = AIS_Shape(shape)

            # 设置颜色
            if not color:
                color = self._get_next_color()

            r, g, b = color
            ais_shape.SetColor(Quantity_Color(r, g, b, Quantity_TOC_RGB))

            # 设置透明度
            if transparency > 0:
                ais_shape.SetTransparency(transparency)

            # 显示
            self.display.Context.Display(ais_shape, False)  # False = 不自动刷新

            # 保存引用
            self.loaded_shapes[node_id] = ais_shape

            return True

        except Exception as e:
            print(f"⚠️ 显示节点失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _apply_transform(self, shape: TopoDS_Shape, transform: Dict) -> TopoDS_Shape:
        """应用变换矩阵"""
        try:
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

            # 创建变换
            trsf = gp_Trsf()

            # 解析位置和旋转
            pos = transform.get('pos', [0, 0, 0])
            quat = transform.get('quat', [1, 0, 0, 0])  # [w, x, y, z]

            # 应用旋转（四元数）
            if quat != [1, 0, 0, 0]:
                gp_quat = gp_Quaternion(quat[1], quat[2], quat[3], quat[0])  # x,y,z,w
                trsf.SetRotation(gp_quat)

            # 应用平移
            if pos != [0, 0, 0]:
                trsf.SetTranslation(gp_Vec(pos[0], pos[1], pos[2]))

            # 变换形状
            brep_trsf = BRepBuilderAPI_Transform(shape, trsf, True)  # True = 复制
            return brep_trsf.Shape()

        except Exception as e:
            print(f"⚠️ 应用变换失败: {e}")
            return shape  # 返回原始形状

    def _get_next_color(self) -> tuple:
        """获取下一个颜色"""
        color = self.colors[self.color_index % len(self.colors)]
        self.color_index += 1
        return color

    def highlight_node(self, node_id: str):
        """高亮显示节点"""
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.SetSelected(ais_shape, True)
            self.display.Repaint()

    def unhighlight_all(self):
        """取消所有高亮"""
        self.display.Context.ClearSelected(True)

    def hide_node(self, node_id: str):
        """隐藏节点"""
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.Erase(ais_shape, True)

    def show_node(self, node_id: str):
        """显示节点"""
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.Display(ais_shape, True)

    def remove_node(self, node_id: str):
        """移除节点"""
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.Remove(ais_shape, False)
            del self.loaded_shapes[node_id]

    def clear_all(self):
        """清空所有显示"""
        for node_id in list(self.loaded_shapes.keys()):
            self.remove_node(node_id)

        self.display.EraseAll()
        self.color_index = 0  # 重置颜色索引

    def fit_all(self):
        """适应视图"""
        self.display.FitAll()
        self.display.Repaint()