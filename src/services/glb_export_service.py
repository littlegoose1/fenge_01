import os
from typing import Optional, Tuple


class GlbExportService:
    """
    OBJ -> GLB 转换服务。
    设计目标：
    - 低侵入：复用现有 OBJ 导出结果；
    - 异常不阻断主流程：失败仅返回错误信息。
    """

    @staticmethod
    def obj_to_glb(obj_path: str) -> Tuple[str, str]:
        """
        :param obj_path: 已存在的 OBJ 文件路径
        :return: (glb_path, err)，成功时 err 为空；失败时 glb_path 为空
        """
        try:
            if not obj_path:
                return "", "empty-obj-path"
            obj_path = os.path.abspath(obj_path)
            if not os.path.exists(obj_path):
                return "", f"obj-not-found: {obj_path}"

            glb_path = os.path.splitext(obj_path)[0] + ".glb"

            try:
                import trimesh  # type: ignore
            except Exception as ex:
                return "", f"missing-dependency(trimesh): {ex}"

            mesh_or_scene = trimesh.load(obj_path, force="scene")
            if mesh_or_scene is None:
                return "", "trimesh-load-failed"

            glb_bytes: Optional[bytes] = mesh_or_scene.export(file_type="glb")
            if not glb_bytes:
                return "", "glb-export-empty"

            with open(glb_path, "wb") as f:
                f.write(glb_bytes)

            if not os.path.exists(glb_path) or os.path.getsize(glb_path) <= 0:
                return "", "glb-write-failed"

            return glb_path, ""
        except Exception as ex:
            return "", str(ex)

