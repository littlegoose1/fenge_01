# -*- coding: utf-8 -*-
from typing import List, Dict, Tuple, Callable, Optional, Any, Set
import math
import random
import numpy as np

from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Face
from OCC.Core.TopoDS import topods
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
                              GeomAbs_Sphere, GeomAbs_Torus,
                              GeomAbs_BezierSurface, GeomAbs_BSplineSurface)
from OCC.Core.gp import gp_Pnt

from .geometry import (GeometricPrimitive, Plane, Cylinder, Cone, Sphere,
                       Torus, FreeFormSurface, Box, Prism, Pyramid, Polyhedron)


# ===================================================================================
# 表面分类
# ===================================================================================

class SurfaceClassifier:
    """表面分类器 - 判定单个面的几何基类类型"""

    @staticmethod
    def classify_face(face: TopoDS_Face) -> Tuple[str, float, Any]:
        try:
            surface = BRepAdaptor_Surface(face)
            stype = surface.GetType()

            if stype == GeomAbs_Plane:
                return "plane", 1.0, surface.Plane()
            if stype == GeomAbs_Cylinder:
                return "cylinder", 1.0, surface.Cylinder()
            if stype == GeomAbs_Cone:
                return "cone", 1.0, surface.Cone()
            if stype == GeomAbs_Sphere:
                return "sphere", 1.0, surface.Sphere()
            if stype == GeomAbs_Torus:
                return "torus", 1.0, surface.Torus()
            if stype in (GeomAbs_BezierSurface, GeomAbs_BSplineSurface):
                return "freeform", 0.7, None
            return "freeform", 0.5, None
        except Exception as e:
            print(f"分类面失败: {e}")
            return "unknown", 0.0, None


# ===================================================================================
# 面聚类
# ===================================================================================

class FaceClusterer:
    """基于几何参数和相似性将面聚类为几何体"""

    def __init__(self, tolerance: float = 0.001):
        self.tolerance = tolerance

    def cluster_faces(self,
                      faces: List[TopoDS_Face],
                      classifications: List[Tuple[str, float, Any]]) -> List[Tuple[str, List[TopoDS_Face], Any, float]]:
        clusters = []
        used = set()

        for geo_type in ["plane", "cylinder", "cone", "sphere", "torus", "freeform"]:
            idxs = [i for i, (t, _, _) in enumerate(classifications)
                    if t == geo_type and i not in used]
            if not idxs:
                continue

            if geo_type == "plane":
                for face_list, surf, score in self._cluster_planes(
                        [faces[i] for i in idxs],
                        [classifications[i][2] for i in idxs]):
                    grouped = [faces[idxs[j]] for j in face_list]
                    clusters.append((geo_type, grouped, surf, score))
                    for j in face_list:
                        used.add(idxs[j])

            elif geo_type == "cylinder":
                for face_list, surf, score in self._cluster_cylinders(
                        [faces[i] for i in idxs],
                        [classifications[i][2] for i in idxs]):
                    grouped = [faces[idxs[j]] for j in face_list]
                    clusters.append((geo_type, grouped, surf, score))
                    for j in face_list:
                        used.add(idxs[j])

            elif geo_type == "cone":
                for face_list, surf, score in self._cluster_cones(
                        [faces[i] for i in idxs],
                        [classifications[i][2] for i in idxs]):
                    grouped = [faces[idxs[j]] for j in face_list]
                    clusters.append((geo_type, grouped, surf, score))
                    for j in face_list:
                        used.add(idxs[j])

            elif geo_type == "sphere":
                for face_list, surf, score in self._cluster_spheres(
                        [faces[i] for i in idxs],
                        [classifications[i][2] for i in idxs]):
                    grouped = [faces[idxs[j]] for j in face_list]
                    clusters.append((geo_type, grouped, surf, score))
                    for j in face_list:
                        used.add(idxs[j])

            elif geo_type == "torus":
                for face_list, surf, score in self._cluster_tori(
                        [faces[i] for i in idxs],
                        [classifications[i][2] for i in idxs]):
                    grouped = [faces[idxs[j]] for j in face_list]
                    clusters.append((geo_type, grouped, surf, score))
                    for j in face_list:
                        used.add(idxs[j])

            elif geo_type == "freeform":
                for face_list, score in self._cluster_freeform(
                        [faces[i] for i in idxs]):
                    grouped = [faces[idxs[j]] for j in face_list]
                    clusters.append((geo_type, grouped, None, score))
                    for j in face_list:
                        used.add(idxs[j])

        return clusters

    # --- 以下聚类方法保持与旧逻辑一致，只做轻微安全防护 ---

    def _cluster_planes(self, faces, planes):
        clusters = []
        remaining = list(range(len(faces)))
        tol = self.tolerance
        while remaining:
            i0 = remaining[0]
            pl0 = planes[i0]
            n0 = pl0.Axis().Direction()
            n0v = (n0.X(), n0.Y(), n0.Z())
            p0 = pl0.Location()
            d0 = -(p0.X()*n0.X() + p0.Y()*n0.Y() + p0.Z()*n0.Z())
            group = [i0]
            for ii in remaining[1:]:
                pl = planes[ii]
                n = pl.Axis().Direction()
                nv = (n.X(), n.Y(), n.Z())
                dot = n0v[0]*nv[0] + n0v[1]*nv[1] + n0v[2]*nv[2]
                if abs(abs(dot) - 1.0) < tol:
                    p = pl.Location()
                    d = -(p.X()*n.X() + p.Y()*n.Y() + p.Z()*n.Z())
                    if abs(d - d0) < tol:
                        group.append(ii)
            remaining = [x for x in remaining if x not in group]
            clusters.append((group, pl0, 1.0))
        return clusters

    def _cluster_cylinders(self, faces, cylinders):
        clusters = []
        remaining = list(range(len(faces)))
        tol = self.tolerance
        while remaining:
            i0 = remaining[0]
            cy0 = cylinders[i0]
            ax0 = cy0.Axis().Direction()
            a0 = (ax0.X(), ax0.Y(), ax0.Z())
            r0 = cy0.Radius()
            c0 = cy0.Location()
            c0p = (c0.X(), c0.Y(), c0.Z())
            group = [i0]
            for ii in remaining[1:]:
                cy = cylinders[ii]
                ax = cy.Axis().Direction()
                a = (ax.X(), ax.Y(), ax.Z())
                dot = a0[0]*a[0] + a0[1]*a[1] + a0[2]*a[2]
                if abs(abs(dot) - 1.0) < tol:
                    r = cy.Radius()
                    if abs(r - r0) < tol * max(r, r0):
                        cc = cy.Location()
                        cp = (cc.X(), cc.Y(), cc.Z())
                        # 共线性粗略检测：与轴方向垂直距离
                        diff = (cp[0] - c0p[0], cp[1]-c0p[1], cp[2]-c0p[2])
                        proj = diff[0]*a0[0] + diff[1]*a0[1] + diff[2]*a0[2]
                        projp = (c0p[0] + proj*a0[0], c0p[1] + proj*a0[1], c0p[2] + proj*a0[2])
                        dist = math.sqrt((cp[0]-projp[0])**2 + (cp[1]-projp[1])**2 + (cp[2]-projp[2])**2)
                        if dist < tol:
                            group.append(ii)
            remaining = [x for x in remaining if x not in group]
            clusters.append((group, cy0, 1.0))
        return clusters

    def _cluster_cones(self, faces, cones):
        clusters = []
        remaining = list(range(len(faces)))
        tol = self.tolerance
        while remaining:
            i0 = remaining[0]
            co0 = cones[i0]
            ax0 = co0.Axis().Direction()
            a0 = (ax0.X(), ax0.Y(), ax0.Z())
            apex0 = co0.Apex()
            ap0 = (apex0.X(), apex0.Y(), apex0.Z())
            ang0 = co0.SemiAngle()
            group = [i0]
            for ii in remaining[1:]:
                co = cones[ii]
                ax = co.Axis().Direction()
                a = (ax.X(), ax.Y(), ax.Z())
                dot = a0[0]*a[0] + a0[1]*a[1] + a0[2]*a[2]
                if abs(abs(dot) - 1.0) < tol:
                    ang = co.SemiAngle()
                    if abs(ang - ang0) < tol:
                        ap = co.Apex()
                        app = (ap.X(), ap.Y(), ap.Z())
                        dist = math.sqrt((app[0]-ap0[0])**2 + (app[1]-ap0[1])**2 + (app[2]-ap0[2])**2)
                        if dist < tol:
                            group.append(ii)
            remaining = [x for x in remaining if x not in group]
            clusters.append((group, co0, 1.0))
        return clusters

    def _cluster_spheres(self, faces, spheres):
        clusters = []
        remaining = list(range(len(faces)))
        tol = self.tolerance
        while remaining:
            i0 = remaining[0]
            sp0 = spheres[i0]
            c0 = sp0.Location()
            c0p = (c0.X(), c0.Y(), c0.Z())
            r0 = sp0.Radius()
            group = [i0]
            for ii in remaining[1:]:
                sp = spheres[ii]
                r = sp.Radius()
                if abs(r - r0) < tol * max(r, r0):
                    cc = sp.Location()
                    cp = (cc.X(), cc.Y(), cc.Z())
                    dist = math.sqrt((cp[0]-c0p[0])**2 + (cp[1]-c0p[1])**2 + (cp[2]-c0p[2])**2)
                    if dist < tol:
                        group.append(ii)
            remaining = [x for x in remaining if x not in group]
            clusters.append((group, sp0, 1.0))
        return clusters

    def _cluster_tori(self, faces, tori):
        clusters = []
        remaining = list(range(len(faces)))
        tol = self.tolerance
        while remaining:
            i0 = remaining[0]
            to0 = tori[i0]
            ax0 = to0.Axis().Direction()
            a0 = (ax0.X(), ax0.Y(), ax0.Z())
            c0 = to0.Location()
            c0p = (c0.X(), c0.Y(), c0.Z())
            R0 = to0.MajorRadius()
            r0 = to0.MinorRadius()
            group = [i0]
            for ii in remaining[1:]:
                to = tori[ii]
                ax = to.Axis().Direction()
                a = (ax.X(), ax.Y(), ax.Z())
                dot = a0[0]*a[0] + a0[1]*a[1] + a0[2]*a[2]
                if abs(abs(dot) - 1.0) < tol:
                    R = to.MajorRadius(); r = to.MinorRadius()
                    if (abs(R-R0) < tol*max(R,R0) and abs(r-r0) < tol*max(r,r0)):
                        cc = to.Location()
                        cp = (cc.X(), cc.Y(), cc.Z())
                        dist = math.sqrt((cp[0]-c0p[0])**2 + (cp[1]-c0p[1])**2 + (cp[2]-c0p[2])**2)
                        if dist < tol:
                            group.append(ii)
            remaining = [x for x in remaining if x not in group]
            clusters.append((group, to0, 1.0))
        return clusters

    def _cluster_freeform(self, faces):
        # 简化：每个面一个自由曲面
        return [([i], 0.7) for i in range(len(faces))]


# ===================================================================================
# 几何参数估计（改进）
# ===================================================================================

class GeometricParameterEstimator:
    """根据聚类出的面集合与基础 OCCT Surface 估计几何参数"""

    # -------------------- 公共顶点提取 --------------------

    @staticmethod
    def _collect_face_vertices(face: TopoDS_Face) -> List[Tuple[float, float, float]]:
        from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
        verts = []
        seen = set()
        edge_explorer = TopExp_Explorer(face, TopAbs_EDGE)
        while edge_explorer.More():
            edge = topods.Edge(edge_explorer.Current())
            vexp = TopExp_Explorer(edge, TopAbs_VERTEX)
            while vexp.More():
                v = topods.Vertex(vexp.Current())
                p = BRep_Tool.Pnt(v)
                key = (round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6))
                if key not in seen:
                    seen.add(key)
                    verts.append((p.X(), p.Y(), p.Z()))
                vexp.Next()
            edge_explorer.Next()
        return verts

    @staticmethod
    def _collect_all_vertices(faces: List[TopoDS_Face]) -> List[Tuple[float, float, float]]:
        pts = []
        for f in faces:
            pts.extend(GeometricParameterEstimator._collect_face_vertices(f))
        return pts

    # -------------------- 参数估计主入口 --------------------

    @staticmethod
    def estimate_parameters(geo_type: str, faces: List[TopoDS_Face], surface=None) -> Dict:
        try:
            if geo_type == "plane":
                return GeometricParameterEstimator._estimate_plane(faces, surface)
            if geo_type == "cylinder":
                return GeometricParameterEstimator._estimate_cylinder(faces, surface)
            if geo_type == "cone":
                return GeometricParameterEstimator._estimate_cone(faces, surface)
            if geo_type == "sphere":
                return GeometricParameterEstimator._estimate_sphere(faces, surface)
            if geo_type == "torus":
                return GeometricParameterEstimator._estimate_torus(faces, surface)
            if geo_type == "freeform":
                return GeometricParameterEstimator._estimate_freeform(faces)
            return {}
        except Exception as e:
            print(f"参数估计失败({geo_type}): {e}")
            return {}

    # -------------------- 各具体估计实现 --------------------

    @staticmethod
    def _local_frame_from_normal(normal: Tuple[float, float, float]) -> Tuple[Tuple[float, float, float],
                                                                              Tuple[float, float, float]]:
        # 构造任意与 normal 不平行的参考向量
        n = normal
        ref = (0, 0, 1) if abs(n[2]) < 0.9 else (1, 0, 0)
        # u = ref x n
        u = (ref[1]*n[2] - ref[2]*n[1],
             ref[2]*n[0] - ref[0]*n[2],
             ref[0]*n[1] - ref[1]*n[0])
        u_len = math.sqrt(u[0]**2 + u[1]**2 + u[2]**2) or 1.0
        u = (u[0]/u_len, u[1]/u_len, u[2]/u_len)
        # v = n x u
        v = (n[1]*u[2] - n[2]*u[1],
             n[2]*u[0] - n[0]*u[2],
             n[0]*u[1] - n[1]*u[0])
        return u, v

    @staticmethod
    def _estimate_plane(faces: List[TopoDS_Face], plane):
        axis_dir = plane.Axis().Direction()
        normal = (axis_dir.X(), axis_dir.Y(), axis_dir.Z())
        nlen = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) or 1.0
        normal = (normal[0] / nlen, normal[1] / nlen, normal[2] / nlen)
        loc = plane.Location()
        origin = (loc.X(), loc.Y(), loc.Z())

        # 原来的 width/height 逻辑废弃：我们不再需要它们
        # 可选：仍可计算面投影包围盒用于后续 UI 显示（如果想显示“原始 bounding width/height”）
        # 目前直接返回初始缩放参数
        return {
            "normal": normal,
            "origin": origin,
            "scale_u": 1.0,
            "scale_v": 1.0,
            "shape_type": "generic"
        }

    @staticmethod
    def _estimate_cylinder(faces: List[TopoDS_Face], cyl):
        axis_dir = cyl.Axis().Direction()
        axis = (axis_dir.X(), axis_dir.Y(), axis_dir.Z())
        alen = math.sqrt(axis[0]**2 + axis[1]**2 + axis[2]**2) or 1.0
        axis = (axis[0]/alen, axis[1]/alen, axis[2]/alen)
        loc = cyl.Location()
        base_ref = (loc.X(), loc.Y(), loc.Z())  # 这是OCCT圆柱定义位置（轴线穿过的一点）
        radius = cyl.Radius()

        pts = GeometricParameterEstimator._collect_all_vertices(faces)
        height = 1.0
        center = base_ref
        if pts:
            projs = []
            for p in pts:
                vec = (p[0]-base_ref[0], p[1]-base_ref[1], p[2]-base_ref[2])
                proj = vec[0]*axis[0] + vec[1]*axis[1] + vec[2]*axis[2]
                projs.append(proj)
            if projs:
                hmin = min(projs)
                hmax = max(projs)
                height = max(hmax - hmin, 1e-3)
                center = (
                    base_ref[0] + axis[0]*(hmin + height/2.0),
                    base_ref[1] + axis[1]*(hmin + height/2.0),
                    base_ref[2] + axis[2]*(hmin + height/2.0),
                )

        return {
            "axis": axis,
            "center": center,
            "radius": radius,
            "height": height
        }

    @staticmethod
    def _estimate_cone(faces: List[TopoDS_Face], cone):
        axis_dir = cone.Axis().Direction()
        axis = (axis_dir.X(), axis_dir.Y(), axis_dir.Z())
        alen = math.sqrt(axis[0]**2 + axis[1]**2 + axis[2]**2) or 1.0
        axis = (axis[0]/alen, axis[1]/alen, axis[2]/alen)

        apex = cone.Apex()
        apex_pt = (apex.X(), apex.Y(), apex.Z())
        semi_angle = cone.SemiAngle()

        pts = GeometricParameterEstimator._collect_all_vertices(faces)
        height = 1.0
        base_radius = 1.0
        if pts:
            # 投影>0的点，最大投影为高度
            projs = []
            radial_samples = []
            for p in pts:
                v = (p[0]-apex_pt[0], p[1]-apex_pt[1], p[2]-apex_pt[2])
                proj = v[0]*axis[0] + v[1]*axis[1] + v[2]*axis[2]
                if proj > 0:
                    projs.append(proj)
            if projs:
                height = max(projs)
                # 取靠近最大投影的点估计底半径（距离 apex 沿轴方向 height）
                threshold = 0.9 * height
                for p in pts:
                    v = (p[0]-apex_pt[0], p[1]-apex_pt[1], p[2]-apex_pt[2])
                    proj = v[0]*axis[0] + v[1]*axis[1] + v[2]*axis[2]
                    if proj > threshold:
                        # 径向分量长度
                        # v = parallel + radial
                        parallel = (axis[0]*proj, axis[1]*proj, axis[2]*proj)
                        radial = (v[0]-parallel[0], v[1]-parallel[1], v[2]-parallel[2])
                        rlen = math.sqrt(radial[0]**2 + radial[1]**2 + radial[2]**2)
                        radial_samples.append(rlen)
                if radial_samples:
                    base_radius = sum(radial_samples)/len(radial_samples)
                else:
                    # 回退用 semi_angle
                    base_radius = height * math.tan(semi_angle)
            else:
                # 没有正投影点，用 semi_angle
                base_radius = height * math.tan(semi_angle)
        base_radius = max(base_radius, 1e-3)
        height = max(height, 1e-3)

        base_center = (
            apex_pt[0] + axis[0]*height,
            apex_pt[1] + axis[1]*height,
            apex_pt[2] + axis[2]*height
        )

        return {
            "axis": axis,
            "apex": apex_pt,
            "base_center": base_center,
            "radius": base_radius,
            "height": height,
            "semi_angle": semi_angle
        }

    @staticmethod
    def _estimate_sphere(faces: List[TopoDS_Face], sphere):
        c = sphere.Location()
        return {
            "center": (c.X(), c.Y(), c.Z()),
            "radius": sphere.Radius()
        }

    @staticmethod
    def _estimate_torus(faces: List[TopoDS_Face], torus):
        ax = torus.Axis().Direction()
        axis = (ax.X(), ax.Y(), ax.Z())
        alen = math.sqrt(axis[0]**2 + axis[1]**2 + axis[2]**2) or 1.0
        axis = (axis[0]/alen, axis[1]/alen, axis[2]/alen)
        c = torus.Location()
        return {
            "axis": axis,
            "center": (c.X(), c.Y(), c.Z()),
            "major_radius": torus.MajorRadius(),
            "minor_radius": torus.MinorRadius()
        }

    @staticmethod
    def _estimate_freeform(faces: List[TopoDS_Face]):
        # 简化：随机控制点占位
        cps = []
        for _ in range(16):
            cps.append((
                random.uniform(-10, 10),
                random.uniform(-10, 10),
                random.uniform(-10, 10)
            ))
        return {"control_points": cps}


# ===================================================================================
# 几何分割处理器
# ===================================================================================

class GeometrySegmentationProcessor:
    """协调整个分割流程"""

    def __init__(self):
        self.classifier = SurfaceClassifier()
        self.clusterer = FaceClusterer()
        self.parameter_estimator = GeometricParameterEstimator()
        self.status_callback = None
        self.progress_callback = None

    def set_status_callback(self, cb: Callable[[str], None]):
        self.status_callback = cb

    def set_progress_callback(self, cb: Callable[[int], None]):
        self.progress_callback = cb

    def _report_status(self, msg: str):
        if self.status_callback:
            self.status_callback(msg)
        else:
            print(msg)

    def _report_progress(self, percent: int):
        if self.progress_callback:
            self.progress_callback(percent)

    def process_shape(self, shape: TopoDS_Shape) -> List[GeometricPrimitive]:
        self._report_status("提取面...")
        self._report_progress(10)
        faces = self._extract_faces(shape)
        if not faces:
            self._report_status("未找到有效面")
            return []

        self._report_status("检测多面体结构...")
        self._report_progress(20)
        from .polyhedron_detector import PolyhedronDetector
        detector = PolyhedronDetector()
        polyhedra = detector.detect_polyhedra(shape)

        primitives: List[GeometricPrimitive] = []
        used_faces: Set[TopoDS_Face] = set()

        # 多面体 → Box 或 Polyhedron
        for pdata in polyhedra:
            poly_faces = pdata["faces"]
            vertices = pdata["vertices"]
            center = pdata["center"]
            if len(poly_faces) == 6 and pdata["edges_count"] == 12:
                # 简易 Box 参数估计仍然保留默认（可后续精准化）
                box = Box(
                    faces=poly_faces,
                    center=center,
                    dx=10.0, dy=10.0, dz=10.0,
                    direction=(0, 0, 1),
                    fitting_score=0.9
                )
                primitives.append(box)
                used_faces.update(poly_faces)
            elif 3 < len(poly_faces) < 150:
                poly = Polyhedron(
                    faces=poly_faces,
                    vertices=vertices,
                    center=center,
                    fitting_score=0.8
                )
                primitives.append(poly)
                used_faces.update(poly_faces)

        remaining = [f for f in faces if f not in used_faces]
        if remaining:
            self._report_status(f"分类 {len(remaining)} 个剩余面...")
            self._report_progress(40)
            classifications = [self.classifier.classify_face(f) for f in remaining]

            self._report_status("聚类面...")
            self._report_progress(60)
            clusters = self.clusterer.cluster_faces(remaining, classifications)

            self._report_status("估计参数...")
            self._report_progress(80)
            for i, (gtype, cfaces, surf, score) in enumerate(clusters):
                self._report_status(f"估计 {gtype} ({i+1}/{len(clusters)})")
                params = self.parameter_estimator.estimate_parameters(gtype, cfaces, surf)
                prim = self._create_primitive(gtype, cfaces, params, score)
                if prim:
                    primitives.append(prim)

        self._report_status(f"分割完成，共 {len(primitives)} 个几何体")
        self._report_progress(100)
        return primitives

    # -------------------- 工具函数 --------------------

    def _extract_faces(self, shape: TopoDS_Shape) -> List[TopoDS_Face]:
        result = []
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More():
            face = topods.Face(exp.Current())
            result.append(face)
            exp.Next()
        return result

    def _create_primitive(self, geo_type: str, faces: List[TopoDS_Face],
                          params: Dict, score: float) -> Optional[GeometricPrimitive]:
        try:
            if geo_type == "plane":
                return Plane(
                    faces=faces,
                    normal=params.get("normal", (0, 0, 1)),
                    origin=params.get("origin", (0, 0, 0)),
                    width=params.get("width", 1.0),
                    height=params.get("height", 1.0),
                    shape_type=params.get("shape_type", "rectangle"),
                    fitting_score=score
                )
            if geo_type == "cylinder":
                return Cylinder(
                    faces=faces,
                    axis=params.get("axis", (0, 0, 1)),
                    center=params.get("center", (0, 0, 0)),
                    radius=params.get("radius", 1.0),
                    height=params.get("height", 1.0),
                    fitting_score=score
                )
            if geo_type == "cone":
                return Cone(
                    faces=faces,
                    axis=params.get("axis", (0, 0, 1)),
                    apex=params.get("apex", (0, 0, 0)),
                    base_center=params.get("base_center", (0, 0, 1)),
                    radius=params.get("radius", 1.0),
                    height=params.get("height", 1.0),
                    semi_angle=params.get("semi_angle", 0.25),
                    fitting_score=score
                )
            if geo_type == "sphere":
                return Sphere(
                    faces=faces,
                    center=params.get("center", (0, 0, 0)),
                    radius=params.get("radius", 1.0),
                    fitting_score=score
                )
            if geo_type == "torus":
                return Torus(
                    faces=faces,
                    axis=params.get("axis", (0, 0, 1)),
                    center=params.get("center", (0, 0, 0)),
                    major_radius=params.get("major_radius", 2.0),
                    minor_radius=params.get("minor_radius", 0.5),
                    fitting_score=score
                )
            if geo_type == "box":
                return Box(
                    faces=faces,
                    center=params.get("center", (0, 0, 0)),
                    dx=params.get("dx", 1.0),
                    dy=params.get("dy", 1.0),
                    dz=params.get("dz", 1.0),
                    direction=params.get("direction", (0, 0, 1)),
                    fitting_score=score
                )
            if geo_type == "prism":
                return Prism(
                    faces=faces,
                    base_center=params.get("base_center", (0, 0, 0)),
                    axis=params.get("axis", (0, 0, 1)),
                    height=params.get("height", 1.0),
                    base_points=params.get("base_points", []),
                    fitting_score=score
                )
            if geo_type == "pyramid":
                return Pyramid(
                    faces=faces,
                    base_center=params.get("base_center", (0, 0, 0)),
                    apex=params.get("apex", (0, 0, 1)),
                    base_points=params.get("base_points", []),
                    fitting_score=score
                )
            if geo_type == "polyhedron":
                return Polyhedron(
                    faces=faces,
                    vertices=params.get("vertices", []),
                    center=params.get("center", (0, 0, 0)),
                    fitting_score=score
                )
            if geo_type == "freeform":
                return FreeFormSurface(
                    faces=faces,
                    control_points=params.get("control_points", []),
                    fitting_score=score
                )
            return None
        except Exception as e:
            print(f"创建几何体失败({geo_type}): {e}")
            return None