"""
从STEP文件提取BOM（优化版：防止内存溢出）
"""
import os
import gc
import hashlib
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

# ✅ 修复导入检测
OCC_AVAILABLE = False
try:
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core. IFSelect import IFSelect_RetDone
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core. XCAFApp import XCAFApp_Application
    from OCC.Core. XCAFDoc import (
        XCAFDoc_DocumentTool,
        XCAFDoc_ShapeTool,
        XCAFDoc_ColorTool,
        XCAFDoc_MaterialTool
    )
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
    from OCC.Core.TDF import TDF_Label, TDF_LabelSequence
    from OCC.Core.TCollection import TCollection_ExtendedString
    from OCC.Core. Quantity import Quantity_Color
    from OCC.Core. TDataStd import TDataStd_Name
    from OCC.Core. TopoDS import TopoDS_Shape
    from OCC.Core. TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core. Bnd import Bnd_Box
    from OCC.Core. BRepBndLib import brepbndlib

    # ✅ 只有全部导入成功才设置为True
    OCC_AVAILABLE = True
    print("✅ pythonocc-core 加载成功")

except ImportError as e:
    print(f"⚠️ pythonocc-core 导入失败: {e}")
    print("BOM提取功能不可用")

    # 创建占位符类型
    if TYPE_CHECKING:
        from OCC.Core.TDF import TDF_Label
        from OCC.Core.TopoDS import TopoDS_Shape
    else:
        TDF_Label = Any
        TopoDS_Shape = Any
except Exception as e:
    print(f"⚠️ 导入OCC时发生错误: {e}")
    import traceback
    traceback.print_exc()

    if TYPE_CHECKING:
        from OCC.Core.TDF import TDF_Label
        from OCC.Core.TopoDS import TopoDS_Shape
    else:
        TDF_Label = Any
        TopoDS_Shape = Any


@dataclass
class STEPBOMItem:
    """STEP文件中的BOM项"""
    item_number: str
    level: int
    name: str
    label_entry: str
    quantity:  int = 1

    shape_hash: str = ""
    volume: float = 0.0
    mass: float = 0.0
    bounding_box: Dict = field(default_factory=dict)

    color: Optional[Tuple[float, float, float]] = None
    material: str = ""

    parent_entry: str = ""
    children: List['STEPBOMItem'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（用于导出）"""
        return {
            'item_number': self. item_number,
            'level': self.level,
            'name': self.name,
            'quantity': self.quantity,
            'volume': round(self.volume, 2),
            'mass': round(self.mass, 4),
            'material': self.material,
            'shape_hash': self.shape_hash,
            'bounding_box': self.bounding_box,
            'color': self.color,
            'parent_entry': self.parent_entry,
            'label_entry': self.label_entry
        }


class STEPBOMExtractor:
    """从STEP文件提取BOM（优化版）"""

    def __init__(self):
        # ✅ 改为警告而不是抛出异常
        if not OCC_AVAILABLE:
            import warnings
            warnings.warn("pythonocc-core 未正确加载，BOM提取功能可能不可用")

        self.bom_items: List[STEPBOMItem] = []
        self. step_file_path: str = ""
        self.extraction_mode: str = ""

        # 内存控制参数
        self.max_items = 10000
        self.processed_count = 0

    def extract_from_step(self, step_path: str, use_xcaf: bool = True) -> List[STEPBOMItem]:
        """从STEP文件提取BOM（带内存保护）"""

        # ✅ 在实际使用时才检查
        if not OCC_AVAILABLE:
            raise ImportError(
                "pythonocc-core 未正确加载！\n\n"
                "请检查：\n"
                "1. 是否已安装 pythonocc-core:  pip install pythonocc-core\n"
                "2. Python版本是否兼容（推荐 Python 3.8-3.11）\n"
                "3. 是否有DLL缺失（Windows需要Visual C++运行库）"
            )

        if not os.path.exists(step_path):
            raise FileNotFoundError(f"文件不存在:  {step_path}")

        self.step_file_path = step_path
        self.bom_items = []
        self.processed_count = 0

        print(f"\n{'='*70}")
        print(f"📖 读取STEP文件: {os.path.basename(step_path)}")
        print(f"{'='*70}")

        # 检查文件大小
        file_size_mb = os.path.getsize(step_path) / (1024 * 1024)
        print(f"📊 文件大小: {file_size_mb:.2f} MB")

        if file_size_mb > 100:
            print("⚠️ 警告：文件较大，可能需要较长时间处理")

        try:
            if use_xcaf:
                self.extraction_mode = "XCAF"
                return self._extract_with_xcaf_safe(step_path)
            else:
                self.extraction_mode = "Basic"
                return self._extract_basic_safe(step_path)
        except MemoryError as e:
            print(f"❌ 内存不足:  {e}")
            raise MemoryError("文件过大，内存不足。请尝试：\n1. 关闭其他程序\n2. 使用基本模式\n3. 分割STEP文件")
        except Exception as e:
            print(f"❌ 提取失败: {e}")
            import traceback
            traceback.print_exc()

            if use_xcaf:
                print("🔄 尝试回退到基本模式...")
                self.extraction_mode = "Basic"
                return self._extract_basic_safe(step_path)
            raise
        finally:
            gc.collect()

    def _extract_with_xcaf_safe(self, step_path: str) -> List[STEPBOMItem]:
        """使用XCAF提取（安全版本）"""
        print("🔍 使用XCAF模式（支持装配结构、颜色、材料）")

        app = XCAFApp_Application. GetApplication()
        doc = TDocStd_Document(TCollection_ExtendedString("MDTV-CAF"))

        try:
            app.NewDocument(TCollection_ExtendedString("MDTV-CAF"), doc)

            reader = STEPCAFControl_Reader()
            reader.SetColorMode(True)
            reader.SetNameMode(True)
            reader. SetLayerMode(True)
            reader.SetMatMode(True)

            print("📖 读取STEP文件...")
            status = reader.ReadFile(step_path)
            if status != IFSelect_RetDone:
                raise RuntimeError(f"STEP文件读取失败:  {status}")

            print("🔄 转换文档...")
            if not reader.Transfer(doc):
                raise RuntimeError("文档转换失败")

            shape_tool = XCAFDoc_DocumentTool. ShapeTool(doc. Main())
            color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main())
            material_tool = XCAFDoc_DocumentTool.MaterialTool(doc. Main())

            free_shapes = TDF_LabelSequence()
            shape_tool.GetFreeShapes(free_shapes)

            print(f"✅ 找到 {free_shapes.Length()} 个顶层组件")

            if free_shapes.Length() == 0:
                print("⚠️ 未找到顶层组件，尝试基本模式")
                return self._extract_basic_safe(step_path)

            item_counter = [1]

            for i in range(1, free_shapes.Length() + 1):
                if self. processed_count >= self.max_items:
                    print(f"⚠️ 已达到最大项数限制 ({self.max_items})，停止处理")
                    break

                label = free_shapes.Value(i)
                self._process_label_recursive_safe(
                    label=label,
                    shape_tool=shape_tool,
                    color_tool=color_tool,
                    material_tool=material_tool,
                    level=0,
                    parent_number="",
                    item_counter=item_counter,
                    parent_entry=""
                )

                if i % 10 == 0:
                    gc.collect()

            print(f"✅ 提取完成，共 {len(self.bom_items)} 个BOM项")
            return self.bom_items

        finally:
            try:
                app.Close(doc)
            except:
                pass
            del doc
            gc.collect()

    # ✅ 使用 Any 类型注解代替具体OCC类型
    def _process_label_recursive_safe(
        self,
        label: Any,  # TDF_Label
        shape_tool: Any,
        color_tool: Any,
        material_tool: Any,
        level: int,
        parent_number: str,
        item_counter: List[int],
        parent_entry: str = "",
        max_depth: int = 20
    ):
        """递归处理Label（安全版本）"""

        if level >= max_depth:
            print(f"⚠️ 达到最大递归深度 {max_depth}，停止")
            return

        if self. processed_count >= self.max_items:
            return

        try:
            if level == 0:
                item_number = str(item_counter[0])
                item_counter[0] += 1
            else:
                item_number = f"{parent_number}.{item_counter[0]}"
                item_counter[0] += 1

            name = self._get_label_name(label)

            try:
                shape = shape_tool.GetShape(label)
            except Exception as e:
                print(f"  ⚠️ 无法获取形状: {e}")
                shape = None

            if shape and not shape.IsNull():
                volume, mass, bbox = self._calculate_properties_safe(shape)
                shape_hash = self._compute_shape_hash(shape, volume, bbox)
            else:
                volume, mass, bbox = 0.0, 0.0, {}
                shape_hash = "null"

            color = self._get_label_color(label, color_tool)
            material = self._get_label_material(label, material_tool)

            entry = label.EntryDumpToString()
            bom_item = STEPBOMItem(
                item_number=item_number,
                level=level,
                name=name,
                label_entry=entry,
                quantity=1,
                shape_hash=shape_hash,
                volume=volume,
                mass=mass,
                bounding_box=bbox,
                color=color,
                material=material,
                parent_entry=parent_entry
            )

            self. bom_items.append(bom_item)
            self.processed_count += 1

            is_assembly = shape_tool.IsAssembly(label)

            if is_assembly:
                components = TDF_LabelSequence()
                shape_tool.GetComponents(label, components)

                print(f"{'  ' * level}📦 {name} (装配, {components.Length()} 个子件)")

                child_counter = [1]
                for j in range(1, components.Length() + 1):
                    if self.processed_count >= self.max_items:
                        break

                    comp_label = components.Value(j)

                    referred_label = TDF_Label()
                    if shape_tool.GetReferredShape(comp_label, referred_label):
                        actual_label = referred_label
                    else:
                        actual_label = comp_label

                    old_counter = item_counter[0]
                    item_counter[0] = child_counter[0]

                    self._process_label_recursive_safe(
                        label=actual_label,
                        shape_tool=shape_tool,
                        color_tool=color_tool,
                        material_tool=material_tool,
                        level=level + 1,
                        parent_number=item_number,
                        item_counter=item_counter,
                        parent_entry=entry,
                        max_depth=max_depth
                    )

                    child_counter[0] = item_counter[0]
                    item_counter[0] = old_counter
            else:
                vol_str = f"{volume:.2f} mm³" if volume > 0 else "N/A"
                print(f"{'  ' * level}🔧 {name} (零件, 体积: {vol_str})")

        except Exception as e:
            print(f"  ⚠️ 处理Label失败: {e}")

    def _calculate_properties_safe(self, shape: Any) -> Tuple[float, float, Dict]:   # TopoDS_Shape
        """安全计算几何属性"""
        if shape is None or shape.IsNull():
            return 0.0, 0.0, {}

        volume = 0.0
        mass = 0.0
        bbox_dict = {}

        try:
            props = GProp_GProps()
            brepgprop. VolumeProperties(shape, props)
            volume = props.Mass()
            mass = volume
        except Exception as e:
            print(f"    ⚠️ 体积计算失败: {e}")

        try:
            bbox = Bnd_Box()
            brepbndlib.Add(shape, bbox)

            if not bbox.IsVoid():
                xmin, ymin, zmin, xmax, ymax, zmax = bbox. Get()
                bbox_dict = {
                    'xmin': round(xmin, 2),
                    'ymin': round(ymin, 2),
                    'zmin': round(zmin, 2),
                    'xmax': round(xmax, 2),
                    'ymax': round(ymax, 2),
                    'zmax': round(zmax, 2),
                    'dx': round(xmax - xmin, 2),
                    'dy': round(ymax - ymin, 2),
                    'dz': round(zmax - zmin, 2)
                }
        except Exception as e:
            print(f"    ⚠️ 包围盒计算失败: {e}")

        return volume, mass, bbox_dict

    def _extract_basic_safe(self, step_path: str) -> List[STEPBOMItem]:
        """基本提取（安全版本）"""
        print("🔍 使用基本模式（仅提取实体列表）")

        reader = STEPControl_Reader()

        try:
            print("📖 读取STEP文件...")
            status = reader.ReadFile(step_path)

            if status != IFSelect_RetDone:
                raise RuntimeError(f"读取失败: {status}")

            print("🔄 转换根形状...")
            reader.TransferRoot()
            shape = reader.OneShape()

            if shape is None or shape.IsNull():
                raise RuntimeError("未能获取形状")

            print("🔍 提取实体...")
            exp = TopExp_Explorer(shape, TopAbs_SOLID)
            idx = 1

            while exp.More():
                if self.processed_count >= self.max_items:
                    print(f"⚠️ 已达到最大项数限制")
                    break

                try:
                    solid = exp.Current()
                    volume, mass, bbox = self._calculate_properties_safe(solid)
                    shape_hash = self._compute_shape_hash(solid, volume, bbox)

                    bom_item = STEPBOMItem(
                        item_number=str(idx),
                        level=0,
                        name=f"Solid_{idx}",
                        label_entry=f"solid_{idx}",
                        quantity=1,
                        shape_hash=shape_hash,
                        volume=volume,
                        mass=mass,
                        bounding_box=bbox
                    )

                    self.bom_items. append(bom_item)
                    self.processed_count += 1
                    print(f"  🔧 Solid_{idx} (体积:  {volume:.2f} mm³)")

                    exp.Next()
                    idx += 1

                    if idx % 50 == 0:
                        gc.collect()

                except Exception as e:
                    print(f"  ⚠️ 处理实体 {idx} 失败: {e}")
                    exp.Next()
                    idx += 1

            if not self.bom_items:
                print("🔍 未找到SOLID，尝试提取SHELL...")
                exp = TopExp_Explorer(shape, TopAbs_SHELL)
                idx = 1

                while exp.More() and self.processed_count < self.max_items:
                    try:
                        shell = exp.Current()
                        bom_item = STEPBOMItem(
                            item_number=str(idx),
                            level=0,
                            name=f"Shell_{idx}",
                            label_entry=f"shell_{idx}",
                            quantity=1
                        )
                        self.bom_items.append(bom_item)
                        self.processed_count += 1
                        print(f"  📄 Shell_{idx}")

                        exp. Next()
                        idx += 1
                    except Exception as e:
                        print(f"  ⚠️ 处理Shell {idx} 失败: {e}")
                        exp.Next()
                        idx += 1

            print(f"✅ 提取到 {len(self.bom_items)} 个项目")
            return self.bom_items

        finally:
            del reader
            gc.collect()

    def _get_label_name(self, label: Any) -> str:  # TDF_Label
        """获取Label的名称"""
        try:
            name_attr = TDataStd_Name()
            if label.FindAttribute(TDataStd_Name.GetID(), name_attr):
                name = name_attr.Get().ToExtString()
                return name if name else "Unnamed"
        except:
            pass
        return "Unnamed"

    def _get_label_color(self, label: Any, color_tool: Any) -> Optional[Tuple[float, float, float]]:
        """获取Label的颜色"""
        try:
            color = Quantity_Color()
            for color_type in [0, 1, 2]:
                if color_tool.GetColor(label, color_type, color):
                    return (color.Red(), color.Green(), color.Blue())
        except:
            pass
        return None

    def _get_label_material(self, label: Any, material_tool: Any) -> str:
        """获取Label的材料"""
        try:
            mat_label = TDF_Label()
            if material_tool. GetMaterial(label, mat_label):
                return self._get_label_name(mat_label)
        except:
            pass
        return ""

    def _compute_shape_hash(self, shape:  Any, volume: float, bbox:  Dict) -> str:  # TopoDS_Shape
        """计算形状哈希"""
        if shape is None or shape.IsNull():
            return "null"

        hash_str = f"{volume:.6f}"
        if bbox:
            hash_str += f"_{bbox. get('dx', 0):.6f}_{bbox.get('dy', 0):.6f}_{bbox.get('dz', 0):.6f}"

        return hashlib.md5(hash_str.encode()).hexdigest()[:8]

    def consolidate_duplicates(self, tolerance: float = 0.01) -> List[STEPBOMItem]:
        """合并重复零件"""
        print(f"\n🔄 合并重复零件...")

        groups = defaultdict(list)
        for item in self.bom_items:
            groups[item.shape_hash].append(item)

        consolidated = []
        item_num = 1

        for shape_hash, items in sorted(groups.items()):
            representative = items[0]

            consolidated_item = STEPBOMItem(
                item_number=str(item_num),
                level=0,
                name=representative.name,
                label_entry=representative.label_entry,
                quantity=len(items),
                shape_hash=shape_hash,
                volume=representative.volume,
                mass=representative.mass * len(items),
                bounding_box=representative.bounding_box. copy(),
                color=representative.color,
                material=representative.material
            )

            consolidated. append(consolidated_item)
            item_num += 1

        print(f"  原始项数: {len(self.bom_items)}")
        print(f"  合并后:  {len(consolidated)} 个独特零件")

        return consolidated

    def export_to_excel(self, output_path: str, hierarchical: bool = True):
        """导出BOM到Excel"""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("需要安装:  pip install pandas openpyxl")

        print(f"\n📊 导出到Excel:  {output_path}")

        data = []
        for item in self.bom_items:
            row = {
                '项目号': item.item_number,
                '层级': item.level,
                '零件名称': item.name,
                '数量': item.quantity,
                '体积(mm³)': f"{item.volume:.2f}" if item.volume > 0 else "",
                '质量(g)': f"{item.mass:.2f}" if item.mass > 0 else "",
                '材料': item.material,
            }

            if item.bounding_box:
                row['长(X)'] = f"{item.bounding_box.get('dx', 0):.2f}"
                row['宽(Y)'] = f"{item.bounding_box.get('dy', 0):.2f}"
                row['高(Z)'] = f"{item.bounding_box.get('dz', 0):.2f}"

            if item. color:
                r, g, b = item.color
                row['颜色RGB'] = f"({r:. 2f}, {g:.2f}, {b:.2f})"

            row['形状哈希'] = item. shape_hash

            data.append(row)

        df = pd.DataFrame(data)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='BOM', index=False)

            file_info = {
                'STEP文件':  os.path.basename(self.step_file_path),
                '文件路径': self.step_file_path,
                '提取模式': self.extraction_mode,
                '生成时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            info_df = pd.DataFrame([file_info])
            info_df.to_excel(writer, sheet_name='文件信息', index=False)

            unique_parts = len(set(item.shape_hash for item in self.bom_items))
            total_quantity = sum(item.quantity for item in self.bom_items)
            total_volume = sum(item.volume * item.quantity for item in self. bom_items)
            max_level = max(item.level for item in self.bom_items) + 1 if self.bom_items else 0

            stats = {
                '总零件种类': unique_parts,
                '总零件数量': total_quantity,
                '总体积(mm³)': f"{total_volume:.2f}",
                'BOM层级数': max_level,
                'BOM项总数': len(self.bom_items),
            }
            stats_df = pd.DataFrame([stats])
            stats_df.to_excel(writer, sheet_name='统计', index=False)

        print(f"✅ BOM已导出到: {output_path}")

    def export_to_json(self, output_path: str):
        """导出为JSON格式"""
        import json

        print(f"\n📊 导出到JSON: {output_path}")

        bom_data = {
            'file_info': {
                'step_file':  os.path.basename(self.step_file_path),
                'file_path': self.step_file_path,
                'extraction_mode': self.extraction_mode,
                'generated_at': datetime.now().isoformat()
            },
            'statistics': {
                'total_items': len(self.bom_items),
                'unique_parts': len(set(item.shape_hash for item in self.bom_items)),
                'total_quantity': sum(item.quantity for item in self.bom_items),
                'max_level': max(item.level for item in self.bom_items) + 1 if self.bom_items else 0
            },
            'bom_items':  [item.to_dict() for item in self.bom_items]
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(bom_data, f, ensure_ascii=False, indent=2)

        print(f"✅ BOM已导出到: {output_path}")

    def print_tree(self, max_items: int = 50):
        """打印BOM树结构"""
        print("\n" + "="*70)
        print("📋 BOM树结构")
        print("="*70)

        for idx, item in enumerate(self.bom_items[:max_items]):
            indent = "  " * item.level
            is_assembly = any(i.parent_entry == item.label_entry for i in self.bom_items)
            icon = "📦" if is_assembly else "🔧"

            vol_str = f"{item.volume: 8.1f}" if item.volume > 0 else "     N/A"

            print(f"{item.item_number:8s} {indent}{icon} {item.name:30s} "
                  f"x{item.quantity:2d}  Vol:{vol_str} mm³")

        if len(self.bom_items) > max_items:
            print(f"... 还有 {len(self.bom_items) - max_items} 项")

        print("="*70)

        unique = len(set(item.shape_hash for item in self.bom_items))
        total_qty = sum(item.quantity for item in self.bom_items)
        print(f"\n📊 统计: {len(self.bom_items)} 个BOM项, "
              f"{unique} 个独特零件, "
              f"总数量 {total_qty}")
        print()