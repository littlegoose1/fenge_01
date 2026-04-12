"""
零件3D可视化服务（使用现有 OCC Display）
"""
import os
import json
from typing import Optional, Dict, Any

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
            display: OCC Display 对象（从 canvas._display 获取）
        """
        self.display = display
        self.loaded_shapes: Dict[str, AIS_Shape] = {}  # node_id -> AIS_Shape
        self.colors = [
            (0.8, 0.2, 0.2),
            (0.2, 0.8, 0.2),
            (0.2, 0.2, 0.8),
            (0.8, 0.8, 0.2),
            (0.8, 0.2, 0.8),
            (0.2, 0.8, 0.8),
            (0.9, 0.5, 0.2),
            (0.5, 0.2, 0.9),
        ]
        self.color_index = 0

    def load_step_file(self, step_path: str) -> Optional[TopoDS_Shape]:
        """加载 STEP 文件"""
        if step_path.startswith('file://'):
            step_path = step_path[7:].replace('/', os.sep)

        if not os.path.exists(step_path):
            print(f"⚠️ STEP文件不存在: {step_path}")
            return None

        try:
            reader = STEPControl_Reader()
            status = reader.ReadFile(step_path)

            if status != IFSelect_RetDone:
                print(f"⚠️ 无法读取STEP文件: {step_path}")
                return None

            reader.TransferRoots()
            return reader.OneShape()

        except Exception as e:
            print(f"⚠️ 加载STEP文件失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def display_node(
        self,
        node_id: str,
        step_path: str,
        transform: Optional[str] = None,
        color: Optional[tuple] = None,
        transparency: float = 0.0
    ) -> bool:
        """
        显示节点

        Args:
            node_id: 节点ID
            step_path: STEP文件路径或URI
            transform: 变换 JSON 字符串/bytes/dict
            color: RGB 颜色 (r, g, b), 范围 0-1
            transparency: 透明度 0-1
        """
        shape = self.load_step_file(step_path)
        if not shape:
            return False

        try:
            if transform:
                if isinstance(transform, str):
                    transform = json.loads(transform)
                elif isinstance(transform, (bytes, bytearray)):
                    transform = json.loads(transform.decode("utf-8"))

                if isinstance(transform, dict):
                    shape = self._apply_transform(shape, transform)

            ais_shape = AIS_Shape(shape)

            if not color:
                color = self._get_next_color()

            r, g, b = color
            ais_shape.SetColor(Quantity_Color(r, g, b, Quantity_TOC_RGB))

            if transparency > 0:
                ais_shape.SetTransparency(transparency)

            self.display.Context.Display(ais_shape, False)
            self.loaded_shapes[node_id] = ais_shape
            return True

        except Exception as e:
            print(f"⚠️ 显示节点失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _apply_transform(self, shape: TopoDS_Shape, transform: Dict[str, Any]) -> TopoDS_Shape:
        """??????? matrix(4x4)??? pos/quat?"""
        try:
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

            trsf = gp_Trsf()

            matrix = transform.get("matrix")
            if isinstance(matrix, list) and len(matrix) == 16:
                matrix = self._normalize_matrix16(matrix)
                # ???: [r11,r12,r13,tx, r21,r22,r23,ty, r31,r32,r33,tz, 0,0,0,1]
                trsf.SetValues(
                    float(matrix[0]), float(matrix[1]), float(matrix[2]), float(matrix[3]),
                    float(matrix[4]), float(matrix[5]), float(matrix[6]), float(matrix[7]),
                    float(matrix[8]), float(matrix[9]), float(matrix[10]), float(matrix[11])
                )
            else:
                pos = transform.get('pos', [0, 0, 0])
                quat = transform.get('quat', [1, 0, 0, 0])  # [w, x, y, z]

                if quat != [1, 0, 0, 0]:
                    gp_quat = gp_Quaternion(quat[1], quat[2], quat[3], quat[0])  # x,y,z,w
                    trsf.SetRotation(gp_quat)

                if pos != [0, 0, 0]:
                    trsf.SetTranslation(gp_Vec(pos[0], pos[1], pos[2]))

            return BRepBuilderAPI_Transform(shape, trsf, True).Shape()

        except Exception as e:
            print(f"?? ??????: {e}")
            return shape

    @staticmethod
    def _normalize_matrix16(matrix: list) -> list:
        """
        ??? 16 ?????
        1) ?? 4x4 ???????
        2) ?? SolidWorks ArrayData(16): [R(0..8), T(9..11), scale(12), ...]
        """
        m = [float(v) for v in matrix[:16]]

        # ??????
        if abs(m[15] - 1.0) < 1e-9:
            return m

        # ??????SW ?? 16 ????m[15]??0????9/10/11?
        t_scale = float(os.getenv("SW_TRANSFORM_TRANSLATION_SCALE", "1000"))
        return [
            m[0], m[1], m[2], m[9] * t_scale,
            m[3], m[4], m[5], m[10] * t_scale,
            m[6], m[7], m[8], m[11] * t_scale,
            0.0, 0.0, 0.0, 1.0
        ]

    def _get_next_color(self) -> tuple:
        color = self.colors[self.color_index % len(self.colors)]
        self.color_index += 1
        return color

    def highlight_node(self, node_id: str):
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.SetSelected(ais_shape, True)
            self.display.Repaint()

    def unhighlight_all(self):
        self.display.Context.ClearSelected(True)

    def hide_node(self, node_id: str):
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.Erase(ais_shape, True)

    def show_node(self, node_id: str):
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.Display(ais_shape, True)

    def remove_node(self, node_id: str):
        if node_id in self.loaded_shapes:
            ais_shape = self.loaded_shapes[node_id]
            self.display.Context.Remove(ais_shape, False)
            del self.loaded_shapes[node_id]

    def clear_all(self):
        for node_id in list(self.loaded_shapes.keys()):
            self.remove_node(node_id)

        self.display.EraseAll()
        self.color_index = 0

    def fit_all(self):
        self.display.FitAll()
        self.display.Repaint()
