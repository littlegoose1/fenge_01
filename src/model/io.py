# src/model/io.py
from typing import List, Optional, Dict
import os

from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Compound
from OCC.Core.BRep import BRep_Builder

from ..model.geometry import GeometricPrimitive


class StepFileHandler:
    """STEP文件处理类"""

    @staticmethod
    def load_step_model(filename: str) -> Optional[TopoDS_Shape]:
        """加载STEP模型文件"""
        print(f"正在加载STEP文件: {filename}")
        if not os.path.exists(filename):
            raise FileNotFoundError(f"文件不存在: {filename}")

        step_reader = STEPControl_Reader()
        status = step_reader.ReadFile(filename)

        if status == IFSelect_RetDone:
            step_reader.TransferRoot()
            shape = step_reader.Shape()
            return shape
        else:
            raise Exception("无法读取STEP文件")

    @staticmethod
    def export_primitives(primitives: List[GeometricPrimitive], modified_shapes: Dict[int, TopoDS_Shape],
                          output_file: str) -> bool:
        """导出几何体到STEP文件"""
        writer = STEPControl_Writer()

        # 为每个基本几何体创建一个复合体并写入
        for i, primitive in enumerate(primitives):
            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)

            # 如果有修改后的形状，添加修改后的
            if i in modified_shapes:
                builder.Add(compound, modified_shapes[i])
            else:
                # 否则添加原始面
                for face in primitive.faces:
                    builder.Add(compound, face)

            # 传输到STEP写入器
            writer.Transfer(compound, STEPControl_AsIs)

        # 写入文件
        status = writer.Write(output_file)
        return status