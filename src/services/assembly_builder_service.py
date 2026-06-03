import json
import os
import uuid
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, unquote

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopoDS import TopoDS_Shape

from src.db.mysql import get_conn
from src.db.util import uuid_to_bin, bin_to_uuid, new_uuid
from src.services.assembly_viewer_service import AssemblyViewerService
from src.services.obj_export_service import ObjExportService
from src.services.glb_export_service import GlbExportService


class AssemblyBuilderService:
    """
    自由拼装服务：
    - 零件库查询
    - 基础装配读取
    - STEP外观加载
    - 新装配保存
    """

    def __init__(self):
        self.viewer_service = AssemblyViewerService()
        self.obj_exporter = ObjExportService()
        self.glb_exporter = GlbExportService()

    @staticmethod
    def _to_cn_category(raw_category: str, part_name: str) -> str:
        c = (raw_category or "").strip().lower()
        name = (part_name or "").strip().lower()

        mapping = {
            "barrel": "枪管",
            "receiver": "机匣",
            "bolt": "枪机",
            "stock": "枪托",
            "trigger": "扳机",
            "sight": "瞄具",
            "magazine": "弹匣",
            "grip": "握把",
            "rail": "导轨",
            "fastener": "紧固件",
            "spring": "弹簧",
            "pin": "销钉",
            "screw": "螺钉",
            "nut": "螺母",
            "washer": "垫片",
            "housing": "壳体",
            "cover": "外壳",
            "plate": "板件",
            "gear": "齿轮",
            "shaft": "轴",
            "bearing": "轴承",
            "connector": "连接件",
            "imported_from_bom": "BOM导入件",
        }

        if c in mapping:
            return mapping[c]

        # 按名称关键词做兜底
        keyword_map = [
            (["barrel", "枪管"], "枪管"),
            (["receiver", "机匣"], "机匣"),
            (["bolt", "枪机"], "枪机"),
            (["stock", "枪托"], "枪托"),
            (["trigger", "扳机"], "扳机"),
            (["sight", "瞄"], "瞄具"),
            (["magazine", "弹匣"], "弹匣"),
            (["grip", "握把"], "握把"),
            (["rail", "导轨"], "导轨"),
            (["spring", "弹簧"], "弹簧"),
            (["pin", "销"], "销钉"),
            (["screw", "螺钉"], "螺钉"),
            (["nut", "螺母"], "螺母"),
            (["washer", "垫片"], "垫片"),
            (["gear", "齿轮"], "齿轮"),
            (["shaft", "轴"], "轴"),
            (["bearing", "轴承"], "轴承"),
            (["connector", "连接"], "连接件"),
        ]
        for kws, label in keyword_map:
            if any(k in name for k in kws):
                return label

        # 原始类目如果是中文则原样显示
        if raw_category and any("\u4e00" <= ch <= "\u9fff" for ch in raw_category):
            return raw_category.strip()

        return "未分类"

    def list_assemblies(self) -> List[Dict[str, Any]]:
        return self.viewer_service.get_all_assemblies()

    def list_part_versions(self) -> List[Dict[str, Any]]:
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            sql = """
                  SELECT pv.id         AS version_id,
                         pv.version_no AS version_no,
                         p.id          AS part_id,
                         p.`key`       AS part_key,
                         p.name        AS part_name,
                         p.category    AS part_category,
                         ga.uri        AS step_uri
                  FROM part_versions pv
                           JOIN parts p ON pv.part_id = p.id
                           LEFT JOIN geom_assets ga ON pv.cad_asset_id = ga.id
                  ORDER BY p.name ASC, pv.version_no DESC
                  """
            cur.execute(sql)
            rows = cur.fetchall() or []
            return [{
                "version_id": bin_to_uuid(r["version_id"]) if r.get("version_id") else "",
                "version_no": r.get("version_no", 0),
                "part_id": bin_to_uuid(r["part_id"]) if r.get("part_id") else "",
                "part_key": r.get("part_key", ""),
                "part_name": r.get("part_name", ""),
                "part_category": r.get("part_category", ""),
                "part_category_cn": self._to_cn_category(r.get("part_category", ""), r.get("part_name", "")),
                "step_uri": r.get("step_uri", ""),
            } for r in rows]
        finally:
            cur.close()
            conn.close()

    def load_base_nodes(self, assembly_id: str) -> List[Dict[str, Any]]:
        rows = self.viewer_service.get_assembly_nodes(assembly_id)
        nodes: List[Dict[str, Any]] = []
        for r in rows:
            nodes.append({
                "local_id": str(uuid.uuid4()),
                "node_name": r.get("node_name", ""),
                "part_name": r.get("part_name", ""),
                "part_version_id": r.get("version_id", ""),
                "step_uri": r.get("step_uri", ""),
                "transform": self._parse_transform(r.get("transform_json")),
            })
        return nodes

    @staticmethod
    def _parse_transform(transform_json: Any) -> Dict[str, Any]:
        default_tf = {"pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0]}
        if not transform_json:
            return default_tf
        try:
            tf = json.loads(transform_json) if isinstance(transform_json, str) else transform_json
            if not isinstance(tf, dict):
                return default_tf
            if isinstance(tf.get("matrix"), list) and len(tf["matrix"]) == 16:
                return {"matrix": [float(v) for v in tf["matrix"]]}
            pos = tf.get("pos", [0.0, 0.0, 0.0])
            quat = tf.get("quat", [1.0, 0.0, 0.0, 0.0])
            if not isinstance(pos, list) or len(pos) != 3:
                pos = [0.0, 0.0, 0.0]
            if not isinstance(quat, list) or len(quat) != 4:
                quat = [1.0, 0.0, 0.0, 0.0]
            return {"pos": [float(pos[0]), float(pos[1]), float(pos[2])], "quat": [float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3])]}
        except Exception:
            return default_tf

    @staticmethod
    def _normalize_step_path(step_path: str) -> str:
        if not step_path:
            return ""
        p = str(step_path).strip()
        if p.lower().startswith("file://"):
            u = urlparse(p)
            path = unquote(u.path or "")
            if len(path) >= 3 and path[0] == "/" and path[2] == ":":
                path = path[1:]
            if not path and u.netloc:
                path = unquote(u.netloc)
            p = path
        return os.path.normpath(p)

    def load_step_shape(self, step_path_or_uri: str) -> Tuple[Optional[TopoDS_Shape], str]:
        try:
            local_path = self._normalize_step_path(step_path_or_uri)
            if not local_path:
                return None, "empty-path"
            if not os.path.exists(local_path):
                return None, f"file-not-found: {local_path}"

            reader = STEPControl_Reader()
            status = reader.ReadFile(local_path)
            if status != IFSelect_RetDone:
                return None, f"read-failed(status={status})"
            roots = reader.TransferRoots()
            if roots == 0:
                return None, "transfer-roots=0"
            shape = reader.OneShape()
            if shape is None:
                return None, "shape-none"
            return shape, ""
        except Exception as e:
            return None, str(e)

    def save_assembly(
        self,
        assembly_name: str,
        assembly_description: str,
        nodes: List[Dict[str, Any]]
    ) -> Tuple[str, int, str, str]:
        if not nodes:
            raise ValueError("当前拼装为空，无法保存")
        if not assembly_name.strip():
            raise ValueError("装配名称不能为空")

        assembly_id = new_uuid()
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO assemblies (id, name, description) VALUES (%s, %s, %s)",
                (uuid_to_bin(assembly_id), assembly_name.strip(), assembly_description or "")
            )

            count = 0
            for i, n in enumerate(nodes, 1):
                part_version_id = n.get("part_version_id", "")
                if not part_version_id:
                    continue
                node_id = new_uuid()
                node_name = n.get("node_name") or f"{n.get('part_name', 'Part')}-{i}"
                transform = n.get("transform", {"pos": [0, 0, 0], "quat": [1, 0, 0, 0]})
                transform_json = json.dumps(transform, ensure_ascii=False)

                cur.execute(
                    """
                    INSERT INTO assembly_nodes (id, assembly_id, part_version_id, name, transform_json)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        uuid_to_bin(node_id),
                        uuid_to_bin(assembly_id),
                        uuid_to_bin(part_version_id),
                        node_name,
                        transform_json,
                    ),
                )
                count += 1

            conn.commit()

            # 导出自由拼装整体 OBJ/GLB（不影响主流程）
            obj_path = ""
            glb_path = ""
            try:
                obj_path = self.obj_exporter.export_assembly_nodes(
                    assembly_name=assembly_name.strip(),
                    assembly_id=assembly_id,
                    nodes=nodes,
                )
                if obj_path:
                    print(f"[OBJ] 自由拼装导出成功: {obj_path}")
                    glb_path, glb_err = self.glb_exporter.obj_to_glb(obj_path)
                    if glb_path:
                        print(f"[GLB] 自由拼装导出成功: {glb_path}")
                    else:
                        print(f"[GLB] 自由拼装导出失败（已忽略）: {glb_err}")
            except Exception as ex:
                print(f"[OBJ/GLB] 自由拼装导出失败（已忽略）: {ex}")

            return assembly_id, count, obj_path, glb_path
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
