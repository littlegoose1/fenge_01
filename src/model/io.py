# src/model/io.py
from typing import List, Dict, Any, Optional
import os

from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Compound
from OCC.Core.BRep import BRep_Builder
from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer
from OCC.Core.STEPControl import STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Interface import Interface_Static
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Copy

from .geometry import GeometricPrimitive


class StepFileHandler:
    """STEP文件处理器 - 读取和保存STEP格式的CAD模型"""

    def load_step_model(self, file_path: str) -> TopoDS_Shape:
        """
        加载STEP文件

        参数:
            file_path: STEP文件路径

        返回:
            TopoDS_Shape: 加载的几何体

        异常:
            RuntimeError: 文件加载失败时抛出
        """
        if not os.path.exists(file_path):
            raise RuntimeError(f"文件不存在: {file_path}")

        # 创建STEP读取器
        reader = STEPControl_Reader()

        # 读取文件
        status = reader.ReadFile(file_path)
        if status != IFSelect_RetDone:
            raise RuntimeError(f"无法读取STEP文件: {file_path}")

        # 转换
        reader.TransferRoots()

        # 返回第一个形状
        if reader.NbShapes() <= 0:
            raise RuntimeError("STEP文件不包含有效几何体")

        return reader.Shape(1)

    def export_primitives(self,
                          primitives: List[GeometricPrimitive],
                          modified_shapes: Dict[int, TopoDS_Shape],
                          file_path: str) -> bool:
        """
        导出几何体到STEP文件

        参数:
            primitives: 几何体列表
            modified_shapes: 已修改的几何体形状
            file_path: 输出文件路径

        返回:
            bool: 导出是否成功
        """
        try:
            # 创建复合体
            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)

            # 添加所有几何体
            for i, primitive in enumerate(primitives):
                # 使用修改过的形状（如果存在）
                if i in modified_shapes:
                    shape = modified_shapes[i]
                else:
                    # 否则使用原始面
                    for face in primitive.faces:
                        builder.Add(compound, face)
                    continue

                # 添加到复合体
                builder.Add(compound, shape)

            # 创建STEP写入器
            writer = STEPControl_Writer()

            # 设置STEP格式
            Interface_Static.SetCVal("write.step.schema", "AP214")

            # 转换形状
            status = writer.Transfer(compound, STEPControl_AsIs)
            if status != IFSelect_RetDone:
                return False

            # 写入文件
            status = writer.Write(file_path)
            return status == IFSelect_RetDone

        except Exception as e:
            print(f"导出STEP文件失败: {str(e)}")
            return False