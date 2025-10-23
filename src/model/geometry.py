# -*- coding: utf-8 -*-
"""
geometry.py 兼容版 (无直接依赖 BRepBndLib 类对象)

改进要点：
1. 统一使用 _safe_add_bbox 封装执行包围盒计算，多级回退 (Add → brepbndlib_Add → 手动遍历顶点)
2. 保留此前“真实重建 + anchor_center 锚点保持”机制
3. 适配 OCCT / pythonocc-core 7.9.0 环境下可能缺失 BRepBndLib 符号的情况
4. 若仅修改尺寸不改位移类参数，保持几何锚点不漂移
"""

from typing import Dict, List, Tuple, Optional, Any
import math
import uuid

# ---------- OpenCASCADE 基础导入 ----------
from OCC.Core.gp import gp_GTrsf  # 确保已在文件顶部导入
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_GTransform  # 确保已导入
from OCC.Core.gp import gp_Ax2, gp_Ax3, gp_Pnt, gp_Dir
from OCC.Core.Geom import Geom_CylindricalSurface
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCC.Core.TopoDS import (
    TopoDS_Face, TopoDS_Shape, TopoDS_Compound, topods
)
from OCC.Core.BRep import BRep_Builder, BRep_Tool
from OCC.Core.gp import (
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax2, gp_Trsf, gp_Pln, gp_Circ
)
from OCC.Core.BRepBuilderAPI import (
    BRepBuilderAPI_Transform, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
)
from OCC.Core.BRepPrimAPI import (
    BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeTorus
)
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_VERTEX

from OCC.Core.gp import gp_GTrsf  # 新增
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_GTransform  # 新增
# ===================================================================================
# 兼容性：包围盒添加封装
# ===================================================================================

def _safe_add_bbox(shape: TopoDS_Shape, box: Bnd_Box, use_triangulation: bool = True):
    """
    兼容不同 pythonocc 版本的包围盒添加：
    优先级：Add → brepbndlib_Add → 手动顶点遍历
    """
    # 1) 尝试 Add
    try:
        from OCC.Core.BRepBndLib import Add  # 常见函数式 API
        try:
            Add(shape, box, use_triangulation)
            return
        except TypeError:
            # 有些版本 Add(shape, box, use_triangulation, use_shape_tolerance)
            try:
                Add(shape, box, use_triangulation, False)
                return
            except Exception:
                pass
    except Exception:
        pass

    # 2) 尝试 brepbndlib_Add
    try:
        from OCC.Core.BRepBndLib import brepbndlib_Add
        brepbndlib_Add(shape, box)
        return
    except Exception:
        pass

    # 3) 手动遍历所有顶点回退
    xmin = ymin = zmin = 1e100
    xmax = ymax = zmax = -1e100
    has_vertex = False
    exp = TopExp_Explorer(shape, TopAbs_VERTEX)
    while exp.More():
        v = topods.Vertex(exp.Current())
        p = BRep_Tool.Pnt(v)
        x, y, z = p.X(), p.Y(), p.Z()
        xmin = min(xmin, x); ymin = min(ymin, y); zmin = min(zmin, z)
        xmax = max(xmax, x); ymax = max(ymax, y); zmax = max(zmax, z)
        has_vertex = True
        exp.Next()

    if has_vertex:
        box.Update(xmin, ymin, zmin, xmax, ymax, zmax)


# ===================================================================================
# 基类
# ===================================================================================

class GeometricPrimitive:
    """几何基本体基类（支持重建 + 锚点中心）"""

    def __init__(self, type_name: str, faces: List[TopoDS_Face], fitting_score: float = 1.0):
        self.type = type_name
        self.faces = faces
        self.fitting_score = fitting_score
        self.id = str(uuid.uuid4())

        self.original_shape: Optional[TopoDS_Shape] = None
        self.anchor_center: Optional[Tuple[float, float, float]] = None

        self.parameter_history: List[Dict[str, Any]] = []
        self.current_history_index: int = 0

        self._create_original_shape()
        self._ensure_anchor_center()

    # ------------------------------------------------------------------
    # 原始形状与包围盒
    # ------------------------------------------------------------------
    def _create_original_shape(self):
        try:
            compound = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(compound)
            for f in self.faces:
                builder.Add(compound, f)
            self.original_shape = compound
        except Exception as e:
            print(f"[WARN] 创建原始复合体失败: {e}")

    def _compute_faces_bbox(self) -> Optional[Bnd_Box]:
        try:
            box = Bnd_Box()
            for f in self.faces:
                _safe_add_bbox(f, box, True)
            return box
        except Exception as e:
            print(f"[WARN] faces bbox 计算失败: {e}")
            return None

    @staticmethod
    def _compute_shape_bbox(shape: TopoDS_Shape) -> Optional[Bnd_Box]:
        try:
            box = Bnd_Box()
            _safe_add_bbox(shape, box, True)
            return box
        except Exception as e:
            print(f"[WARN] shape bbox 计算失败: {e}")
            return None

    @staticmethod
    def _bbox_center(bbox: Bnd_Box) -> Tuple[float, float, float]:
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        return (0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax))

    def _ensure_anchor_center(self):
        if self.anchor_center is None:
            bb = self._compute_faces_bbox()
            if bb:
                self.anchor_center = self._bbox_center(bb)

    # ------------------------------------------------------------------
    # 向量工具
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_vector(vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
        length = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
        if length < 1e-12:
            return (0.0, 0.0, 1.0)
        return (vec[0]/length, vec[1]/length, vec[2]/length)

    @staticmethod
    def cross_product(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> Tuple[float, float, float]:
        return (
            v1[1]*v2[2] - v1[2]*v2[1],
            v1[2]*v2[0] - v1[0]*v2[2],
            v1[0]*v2[1] - v1[1]*v2[0]
        )

    def _recenter_to_anchor(self, shape: TopoDS_Shape) -> TopoDS_Shape:
        if not self.anchor_center:
            return shape
        bbox = self._compute_shape_bbox(shape)
        if not bbox:
            return shape
        c = self._bbox_center(bbox)
        dx = self.anchor_center[0] - c[0]
        dy = self.anchor_center[1] - c[1]
        dz = self.anchor_center[2] - c[2]
        if abs(dx)+abs(dy)+abs(dz) < 1e-9:
            return shape
        trsf = gp_Trsf()
        trsf.SetTranslation(gp_Vec(dx, dy, dz))
        return BRepBuilderAPI_Transform(shape, trsf).Shape()

    # ------------------------------------------------------------------
    # 参数比较
    # ------------------------------------------------------------------
    def has_significant_changes(self, old_params: Dict, new_params: Dict, tolerance=1e-6) -> bool:
        for k, nv in new_params.items():
            if k not in old_params:
                return True
            ov = old_params[k]
            if isinstance(nv, (int, float)) and isinstance(ov, (int, float)):
                if abs(nv - ov) > tolerance:
                    return True
            elif isinstance(nv, tuple) and isinstance(ov, tuple) and len(nv) == len(ov):
                if any(abs(a-b) > tolerance for a, b in zip(nv, ov)):
                    return True
            else:
                if nv != ov:
                    return True
        return False

    # ------------------------------------------------------------------
    # 参数接口
    # ------------------------------------------------------------------
    def get_params(self) -> Dict:
        return {
            "type": self.type,
            "fitting_score": self.fitting_score,
            "id": self.id
        }

    def _apply_params(self, parameters: Dict):
        pass

    def _build_shape(self, parameters: Dict, keep_anchor: bool) -> Optional[TopoDS_Shape]:
        return None

    # ------------------------------------------------------------------
    # 预览与重建
    # ------------------------------------------------------------------
    def create_preview_shape(self, parameters: Dict):
        try:
            return self._build_shape(parameters, keep_anchor=True)
        except Exception as e:
            print(f"[WARN] 预览失败({self.type}): {e}")
            return None

    def rebuild_with_parameters(self, parameters: Dict):
        old = self.get_params()
        if not self.has_significant_changes(old, parameters):
            return self.original_shape

        new_shape = self._build_shape(parameters, keep_anchor=True)
        if new_shape is None:
            print(f"[WARN] {self.type} 重建失败，使用 original_shape")
            return self.original_shape

        self._apply_params(parameters)

        snap = self.get_params().copy()
        for k, v in parameters.items():
            snap[k] = v
        self.parameter_history.append(snap)
        self.current_history_index = len(self.parameter_history) - 1
        return new_shape

    # ------------------------------------------------------------------
    # 历史
    # ------------------------------------------------------------------
    def undo(self):
        if self.current_history_index > 0:
            self.current_history_index -= 1
            params = self.parameter_history[self.current_history_index]
            self._apply_params(params)
            return self._build_shape(params, keep_anchor=True)
        return None

    def redo(self):
        if self.current_history_index < len(self.parameter_history) - 1:
            self.current_history_index += 1
            params = self.parameter_history[self.current_history_index]
            self._apply_params(params)
            return self._build_shape(params, keep_anchor=True)
        return None

    def can_undo(self):
        return self.current_history_index > 0

    def can_redo(self):
        return self.current_history_index < len(self.parameter_history) - 1


# ===================================================================================
# Plane
# ===================================================================================

class Plane(GeometricPrimitive):
    """
    平面（中心锚点缩放版）
    - 去掉 width/height，使用 scale_u / scale_v
    - normal / origin 变化：刚性变换（旋转+平移）
    - scale_u / scale_v 变化：关于形状中心（包围盒中心）沿 U/V 各向异性缩放，不再发生位置偏移
    - 每次重建都基于 original_shape 组合变换，避免累计误差
    """

    def __init__(self, faces, normal, origin,
                 width=None, height=None,  # 兼容旧签名
                 shape_type="generic",
                 fitting_score=1.0):
        super().__init__("plane", faces, fitting_score)

        self.normal = self.normalize_vector(normal)
        self.origin = origin
        self.shape_type = shape_type

        self.scale_u = 1.0
        self.scale_v = 1.0

        # 固定基准（用于从 original_shape 重建，避免累计误差）
        self._base_normal = self.normal
        self._base_origin = self.origin

        # 当前参考（用于 UI 显示/比较）
        self._current_normal = self.normal
        self._current_origin = self.origin
        self._current_scale_u = self.scale_u
        self._current_scale_v = self.scale_v

        snap = self.get_params()
        self.parameter_history.append(snap)

    # ---------------- 工具：根据 normal 构造局部 U/V ----------------
    def _construct_local_axes(self, normal: Tuple[float, float, float]):
        n = self.normalize_vector(normal)
        ref = (0, 0, 1) if abs(n[2]) < 0.9 else (1, 0, 0)
        u = (ref[1]*n[2] - ref[2]*n[1],
             ref[2]*n[0] - ref[0]*n[2],
             ref[0]*n[1] - ref[1]*n[0])
        ul = math.sqrt(u[0]**2 + u[1]**2 + u[2]**2) or 1.0
        u = (u[0]/ul, u[1]/ul, u[2]/ul)
        v = (n[1]*u[2] - n[2]*u[1],
             n[2]*u[0] - n[0]*u[2],
             n[0]*u[1] - n[1]*u[0])
        return u, v

    # ---------------- 参数接口 ----------------
    def get_params(self):
        p = super().get_params()
        p.update({
            "normal": self.normal,
            "origin": self.origin,
            "scale_u": self.scale_u,
            "scale_v": self.scale_v,
            "shape_type": self.shape_type
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.normal = self.normalize_vector(parameters.get("normal", self.normal))
        self.origin = parameters.get("origin", self.origin)
        self.scale_u = parameters.get("scale_u", self.scale_u)
        self.scale_v = parameters.get("scale_v", self.scale_v)
        self.shape_type = parameters.get("shape_type", self.shape_type)

    # ---------------- 刚性变换（旋转+平移） ----------------
    def _rigid_trsf(self, new_origin, new_normal):
        old_origin = self._base_origin
        old_normal = self._base_normal

        oN = self.normalize_vector(old_normal)
        nN = self.normalize_vector(new_normal)

        cross = self.cross_product(oN, nN)
        clen = math.sqrt(sum(c*c for c in cross))
        dot = max(-1.0, min(1.0, oN[0]*nN[0] + oN[1]*nN[1] + oN[2]*nN[2]))

        trsf = gp_Trsf()

        # 旋转
        if clen < 1e-12:
            if dot < 0:  # 反向
                ref = (1, 0, 0) if abs(oN[0]) < 0.9 else (0, 1, 0)
                rot_axis = self.cross_product(oN, ref)
                rl = math.sqrt(sum(a*a for a in rot_axis)) or 1.0
                rot_axis = (rot_axis[0]/rl, rot_axis[1]/rl, rot_axis[2]/rl)
                ax2 = gp_Ax2(gp_Pnt(*old_origin), gp_Dir(*rot_axis))
                trsf.SetRotation(ax2.Axis(), math.pi)
            # dot≈1 时 trsf 为恒等
        else:
            angle = math.acos(dot)
            rot_axis = (cross[0]/clen, cross[1]/clen, cross[2]/clen)
            ax2 = gp_Ax2(gp_Pnt(*old_origin), gp_Dir(*rot_axis))
            trsf.SetRotation(ax2.Axis(), angle)

        # 旋转后的旧原点位置
        rot_origin = gp_Pnt(*old_origin)
        rot_origin.Transform(trsf)  # 恒等也安全

        # 平移：旧原点移到新 origin
        tx = new_origin[0] - rot_origin.X()
        ty = new_origin[1] - rot_origin.Y()
        tz = new_origin[2] - rot_origin.Z()
        if abs(tx)+abs(ty)+abs(tz) > 1e-12:
            move = gp_Trsf()
            move.SetTranslation(gp_Vec(tx, ty, tz))
            trsf = move * trsf
        return trsf

    # ---------------- 各向异性缩放（关于中心点） ----------------
    def _anisotropic_scale_trsf_about_anchor(self, basis_normal, anchor_xyz, su, sv):
        """
        构造关于 anchor 的各向异性缩放仿射矩阵：
        P' = A P + (anchor - A*anchor)
        其中 A = su * U⊗U + sv * V⊗V + 1 * N⊗N
        基 (U,V,N) 来自 basis_normal
        """
        g = gp_GTrsf()

        # 单位缩放直接返回单位仿射（保持中心不动）
        if abs(su - 1.0) < 1e-12 and abs(sv - 1.0) < 1e-12:
            return g

        U, V = self._construct_local_axes(basis_normal)
        N = self.normalize_vector(basis_normal)

        def outer(a, b):
            return [
                a[0]*b[0], a[0]*b[1], a[0]*b[2],
                a[1]*b[0], a[1]*b[1], a[1]*b[2],
                a[2]*b[0], a[2]*b[1], a[2]*b[2],
            ]

        ou = outer(U, U)
        ov = outer(V, V)
        on = outer(N, N)

        A = [0.0]*9
        for i in range(9):
            A[i] = su*ou[i] + sv*ov[i] + on[i]

        # 线性部分
        for r in range(3):
            for c in range(3):
                g.SetValue(r+1, c+1, A[r*3 + c])

        # 平移补偿：anchor 固定
        Cx, Cy, Cz = anchor_xyz
        ACx = A[0]*Cx + A[1]*Cy + A[2]*Cz
        ACy = A[3]*Cx + A[4]*Cy + A[5]*Cz
        ACz = A[6]*Cx + A[7]*Cy + A[8]*Cz
        tx = Cx - ACx
        ty = Cy - ACy
        tz = Cz - ACz
        g.SetValue(1, 4, tx)
        g.SetValue(2, 4, ty)
        g.SetValue(3, 4, tz)

        return g

    # ---------------- 构建形状（刚性+关于中心缩放） ----------------
    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        new_normal = self.normalize_vector(parameters.get("normal", self.normal))
        new_origin = parameters.get("origin", self.origin)
        su = parameters.get("scale_u", self.scale_u)
        sv = parameters.get("scale_v", self.scale_v)

        # 1) 刚性变换：对齐到 new_normal/new_origin
        rigid = self._rigid_trsf(new_origin, new_normal)
        tmp_shape = BRepBuilderAPI_Transform(self.original_shape, rigid).Shape()

        # 2) 计算缩放锚点：使用刚性后的形状包围盒中心
        bbox = self._compute_shape_bbox(tmp_shape)
        if bbox:
            anchor = self._bbox_center(bbox)
        else:
            # 回退：若无法得到 bbox，就用 new_origin（不会报错，但可能不是视觉中心）
            anchor = new_origin

        # 3) 各向异性缩放（关于中心点 anchor）
        #    若 su,sv 都为 1，直接返回刚性结果，避免数值扰动
        if abs(su - 1.0) < 1e-12 and abs(sv - 1.0) < 1e-12:
            return tmp_shape

        gtrsf = self._anisotropic_scale_trsf_about_anchor(new_normal, anchor, su, sv)
        scaled_shape = BRepBuilderAPI_GTransform(tmp_shape, gtrsf, True).Shape()
        return scaled_shape

    def rebuild_with_parameters(self, parameters: Dict):
        old = self.get_params()
        if not self.has_significant_changes(old, parameters):
            return self.original_shape

        new_shape = self._build_shape(parameters, keep_anchor=True)
        self._apply_params(parameters)

        self._current_normal = self.normal
        self._current_origin = self.origin
        self._current_scale_u = self.scale_u
        self._current_scale_v = self.scale_v

        snap = self.get_params().copy()
        self.parameter_history.append(snap)
        self.current_history_index = len(self.parameter_history) - 1
        return new_shape

    def create_preview_shape(self, parameters: Dict):
        try:
            return self._build_shape(parameters, keep_anchor=True)
        except Exception as e:
            print(f"[WARN] 平面预览失败: {e}")
            return None

# ===================================================================================
# Cylinder
# ===================================================================================

class Cylinder(GeometricPrimitive):
    """
    圆柱：根据原始 faces 是否包含端盖决定重建方式
    - 无端盖: 重建为“侧面”面片（开放圆柱），不再自动补上下盖
    - 有端盖: 继续使用实体圆柱重建（与之前相同）
    锚点策略与之前一致：center 为高度中点；如未显式修改 center，仅改尺寸时保持锚点位置
    """

    def __init__(self, faces, axis, center, radius, height, fitting_score=1.0):
        super().__init__("cylinder", faces, fitting_score)
        self.axis = self.normalize_vector(axis)
        self.center = center        # 高度中点
        self.radius = radius
        self.height = height

        # 检测原始是否有端盖（是否包含平面面）
        self._has_caps = self._detect_has_caps(faces)

        init = self.get_params()
        self.parameter_history.append(init)

    def _detect_has_caps(self, faces: List[TopoDS_Face]) -> bool:
        """粗略检测：如果一组 faces 中存在平面面，则认为原始包含端盖。"""
        try:
            from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
            from OCC.Core.GeomAbs import GeomAbs_Plane
            for f in faces:
                surf = BRepAdaptor_Surface(f)
                if surf.GetType() == GeomAbs_Plane:
                    return True
            return False
        except Exception:
            # 兜底：无法检测时，默认按“无端盖”保守处理
            return False

    def get_params(self):
        p = super().get_params()
        p.update({
            "axis": self.axis,
            "center": self.center,
            "radius": self.radius,
            "height": self.height
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.axis = self.normalize_vector(parameters.get("axis", self.axis))
        self.center = parameters.get("center", self.center)
        self.radius = parameters.get("radius", self.radius)
        self.height = parameters.get("height", self.height)

    def _build_lateral_face(self, axis: Tuple[float, float, float],
                            center: Tuple[float, float, float],
                            radius: float, height: float) -> TopoDS_Shape:
        """
        构建“仅侧面”的圆柱面（开放，无端盖）
        使用参数面：U 为角度（0..2*pi），V 沿轴向（-h/2..h/2）
        """
        ax3 = gp_Ax3(gp_Pnt(*center), gp_Dir(*axis))
        cyl_surf = Geom_CylindricalSurface(ax3, radius)

        umin, umax = 0.0, 2.0 * math.pi
        vmin, vmax = -height / 2.0, height / 2.0

        # 兼容不同绑定的重载：先尝试 5 参，再回退 6 参（含容差）
        try:
            face = BRepBuilderAPI_MakeFace(cyl_surf, umin, umax, vmin, vmax).Face()
        except TypeError:
            face = BRepBuilderAPI_MakeFace(cyl_surf, umin, umax, vmin, vmax, 1.0e-7).Face()
        return face

    def _build_solid(self, axis: Tuple[float, float, float],
                     center: Tuple[float, float, float],
                     radius: float, height: float) -> TopoDS_Shape:
        """
        构建实体圆柱（带端盖）
        以 center 为高度中点，base_center = center - axis * (h/2)
        """
        base_center = (
            center[0] - axis[0] * height / 2.0,
            center[1] - axis[1] * height / 2.0,
            center[2] - axis[2] * height / 2.0
        )
        ax2 = gp_Ax2(gp_Pnt(*base_center), gp_Dir(*axis))
        return BRepPrimAPI_MakeCylinder(ax2, radius, height).Shape()

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        axis = self.normalize_vector(parameters.get("axis", self.axis))
        center = parameters.get("center", self.center)
        radius = parameters.get("radius", self.radius)
        height = parameters.get("height", self.height)

        if self._has_caps:
            shape = self._build_solid(axis, center, radius, height)
        else:
            shape = self._build_lateral_face(axis, center, radius, height)

        # 和之前一致：若未显式修改 center，仅改尺寸时保持 anchor 位置
        if keep_anchor and "center" not in parameters:
            shape = self._recenter_to_anchor(shape)
        return shape


# ===================================================================================
# Cone
# ===================================================================================

class Cone(GeometricPrimitive):
    def __init__(self, faces, axis, apex, base_center, radius, height, semi_angle=None, fitting_score=1.0):
        super().__init__("cone", faces, fitting_score)
        self.axis = self.normalize_vector(axis)
        self.apex = apex
        self.height = height
        self.radius = radius
        self.base_center = base_center if base_center else (
            apex[0] - self.axis[0]*height,
            apex[1] - self.axis[1]*height,
            apex[2] - self.axis[2]*height
        )
        self.semi_angle = semi_angle if semi_angle is not None else math.atan(radius/height)
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({
            "axis": self.axis,
            "apex": self.apex,
            "base_center": self.base_center,
            "radius": self.radius,
            "height": self.height,
            "semi_angle": self.semi_angle
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.axis = self.normalize_vector(parameters.get("axis", self.axis))
        self.apex = parameters.get("apex", self.apex)
        self.base_center = parameters.get("base_center", self.base_center)
        self.radius = parameters.get("radius", self.radius)
        self.height = parameters.get("height", self.height)
        self.semi_angle = parameters.get("semi_angle", self.semi_angle)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        axis = self.normalize_vector(parameters.get("axis", self.axis))
        apex = parameters.get("apex", self.apex)
        height = parameters.get("height", self.height)
        radius = parameters.get("radius", self.radius)

        base_center = (
            apex[0] - axis[0]*height,
            apex[1] - axis[1]*height,
            apex[2] - axis[2]*height
        )
        ax2 = gp_Ax2(gp_Pnt(*base_center), gp_Dir(*axis))
        shape = BRepPrimAPI_MakeCone(ax2, radius, 0.0, height).Shape()
        if keep_anchor and ("apex" not in parameters and "base_center" not in parameters):
            shape = self._recenter_to_anchor(shape)
        return shape


# ===================================================================================
# Sphere
# ===================================================================================

class Sphere(GeometricPrimitive):
    def __init__(self, faces, center, radius, fitting_score=1.0):
        super().__init__("sphere", faces, fitting_score)
        self.center = center
        self.radius = radius
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({"center": self.center, "radius": self.radius})
        return p

    def _apply_params(self, parameters: Dict):
        self.center = parameters.get("center", self.center)
        self.radius = parameters.get("radius", self.radius)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        center = parameters.get("center", self.center)
        radius = parameters.get("radius", self.radius)
        shape = BRepPrimAPI_MakeSphere(gp_Pnt(*center), radius).Shape()
        if keep_anchor and "center" not in parameters:
            shape = self._recenter_to_anchor(shape)
        return shape


# ===================================================================================
# Torus
# ===================================================================================

class Torus(GeometricPrimitive):
    def __init__(self, faces, axis, center, major_radius, minor_radius, fitting_score=1.0):
        super().__init__("torus", faces, fitting_score)
        self.axis = self.normalize_vector(axis)
        self.center = center
        self.major_radius = major_radius
        self.minor_radius = minor_radius
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({
            "axis": self.axis,
            "center": self.center,
            "major_radius": self.major_radius,
            "minor_radius": self.minor_radius
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.axis = self.normalize_vector(parameters.get("axis", self.axis))
        self.center = parameters.get("center", self.center)
        self.major_radius = parameters.get("major_radius", self.major_radius)
        self.minor_radius = parameters.get("minor_radius", self.minor_radius)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        axis = self.normalize_vector(parameters.get("axis", self.axis))
        center = parameters.get("center", self.center)
        r1 = parameters.get("major_radius", self.major_radius)
        r2 = parameters.get("minor_radius", self.minor_radius)
        ax2 = gp_Ax2(gp_Pnt(*center), gp_Dir(*axis))
        shape = BRepPrimAPI_MakeTorus(ax2, r1, r2).Shape()
        if keep_anchor and "center" not in parameters:
            shape = self._recenter_to_anchor(shape)
        return shape


# ===================================================================================
# Box
# ===================================================================================

class Box(GeometricPrimitive):
    def __init__(self, faces, center=None, corner=None, dx=10.0, dy=10.0, dz=10.0, direction=(0, 0, 1),
                 fitting_score=1.0):
        super().__init__("box", faces, fitting_score)
        if corner is None and center is not None:
            corner = (center[0]-dx/2, center[1]-dy/2, center[2]-dz/2)
        self.corner = corner if corner else (0, 0, 0)
        self.dx = dx
        self.dy = dy
        self.dz = dz
        self.direction = self.normalize_vector(direction)
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({
            "corner": self.corner,
            "dx": self.dx,
            "dy": self.dy,
            "dz": self.dz,
            "direction": self.direction
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.corner = parameters.get("corner", self.corner)
        self.dx = parameters.get("dx", self.dx)
        self.dy = parameters.get("dy", self.dy)
        self.dz = parameters.get("dz", self.dz)
        self.direction = self.normalize_vector(parameters.get("direction", self.direction))

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        dx = parameters.get("dx", self.dx)
        dy = parameters.get("dy", self.dy)
        dz = parameters.get("dz", self.dz)
        direction = self.normalize_vector(parameters.get("direction", self.direction))

        if "corner" in parameters:
            corner = parameters["corner"]
        else:
            if keep_anchor and self.anchor_center:
                corner = (
                    self.anchor_center[0] - dx/2.0,
                    self.anchor_center[1] - dy/2.0,
                    self.anchor_center[2] - dz/2.0
                )
            else:
                corner = self.corner

        shape = BRepPrimAPI_MakeBox(gp_Pnt(*corner), dx, dy, dz).Shape()

        # 方向旋转
        default = (0, 0, 1)
        if (abs(direction[0]-default[0]) > 1e-9 or
            abs(direction[1]-default[1]) > 1e-9 or
            abs(direction[2]-default[2]) > 1e-9):

            cross = self.cross_product(default, direction)
            clen = math.sqrt(cross[0]**2 + cross[1]**2 + cross[2]**2)

            if clen < 1e-9:
                # 平行或反向
                dot = sum(a*b for a, b in zip(default, direction))
                if dot < 0:
                    rot_axis = (1, 0, 0)
                    angle = math.pi
                else:
                    angle = 0.0
                    rot_axis = (0, 0, 1)
            else:
                rot_axis = (cross[0]/clen, cross[1]/clen, cross[2]/clen)
                dot = sum(a*b for a, b in zip(default, direction))
                dot = max(-1.0, min(1.0, dot))
                angle = math.acos(dot)

            if abs(angle) > 1e-9:
                center_point = (
                    corner[0] + dx/2.0,
                    corner[1] + dy/2.0,
                    corner[2] + dz/2.0
                )
                ax2 = gp_Ax2(gp_Pnt(*center_point), gp_Dir(*rot_axis))
                trsf = gp_Trsf()
                trsf.SetRotation(ax2.Axis(), angle)
                shape = BRepBuilderAPI_Transform(shape, trsf).Shape()

        return shape


# ===================================================================================
# 其余几何：暂不做真实重建（可按需扩展）
# ===================================================================================

class FreeFormSurface(GeometricPrimitive):
    def __init__(self, faces, control_points=None, fitting_score=1.0):
        super().__init__("freeform", faces, fitting_score)
        self.control_points = control_points or []
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({"control_points": self.control_points})
        return p

    def _apply_params(self, parameters: Dict):
        self.control_points = parameters.get("control_points", self.control_points)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        return self.original_shape


class Prism(GeometricPrimitive):
    def __init__(self, faces, base_center, axis, height, base_points=None, fitting_score=1.0):
        super().__init__("prism", faces, fitting_score)
        self.base_center = base_center
        self.axis = self.normalize_vector(axis)
        self.height = height
        self.base_points = base_points or []
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({
            "base_center": self.base_center,
            "axis": self.axis,
            "height": self.height,
            "base_points": self.base_points
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.base_center = parameters.get("base_center", self.base_center)
        self.axis = self.normalize_vector(parameters.get("axis", self.axis))
        self.height = parameters.get("height", self.height)
        self.base_points = parameters.get("base_points", self.base_points)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        return self.original_shape


class Pyramid(GeometricPrimitive):
    def __init__(self, faces, base_center, apex, base_points=None, fitting_score=1.0):
        super().__init__("pyramid", faces, fitting_score)
        self.base_center = base_center
        self.apex = apex
        self.base_points = base_points or []
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({
            "base_center": self.base_center,
            "apex": self.apex,
            "base_points": self.base_points
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.base_center = parameters.get("base_center", self.base_center)
        self.apex = parameters.get("apex", self.apex)
        self.base_points = parameters.get("base_points", self.base_points)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        return self.original_shape


class Polyhedron(GeometricPrimitive):
    def __init__(self, faces, vertices, center, fitting_score=1.0):
        super().__init__("polyhedron", faces, fitting_score)
        self.vertices = vertices
        self.center = center
        init = self.get_params()
        self.parameter_history.append(init)

    def get_params(self):
        p = super().get_params()
        p.update({
            "vertices": self.vertices,
            "center": self.center
        })
        return p

    def _apply_params(self, parameters: Dict):
        self.vertices = parameters.get("vertices", self.vertices)
        self.center = parameters.get("center", self.center)

    def _build_shape(self, parameters: Dict, keep_anchor: bool):
        return self.original_shape