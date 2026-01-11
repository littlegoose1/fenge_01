"""
装配查看服务
从数据库加载装配和部件信息
"""
from typing import List, Dict, Any, Optional
from ..db.mysql import get_conn
from ..db.util import bin_to_uuid, uuid_to_bin


class AssemblyViewerService:
    """装配查看服务"""

    def get_all_assemblies(self) -> List[Dict[str, Any]]:
        """获取所有装配列表"""
        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        try:
            sql = """
                  SELECT id, \
                         name, \
                         description, \
                         created_at, \
                         (SELECT COUNT(*) FROM assembly_nodes WHERE assembly_id = assemblies.id) as node_count
                  FROM assemblies
                  ORDER BY created_at DESC \
                  """

            cur.execute(sql)
            rows = cur.fetchall()

            assemblies = []
            for row in rows:
                assemblies.append({
                    'id': bin_to_uuid(row['id']),
                    'name': row['name'],
                    'description': row['description'],
                    'created_at': row['created_at'],
                    'node_count': row['node_count']
                })

            return assemblies

        finally:
            cur.close()
            conn.close()

    def get_assembly_nodes(self, assembly_id: str) -> List[Dict[str, Any]]:
        """获取装配的所有节点（部件）"""
        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        try:
            sql = """
                  SELECT an.id   as node_id, \
                         an.name as node_name, \
                         an.transform_json, \
                         pv.id   as version_id, \
                         pv.version_no, \
                         pv.cad_asset_id, \
                         p.id    as part_id, \
                         p.`key` as part_key, \
                         p.name  as part_name, \
                         ga.uri  as step_uri
                  FROM assembly_nodes an
                           JOIN part_versions pv ON an.part_version_id = pv.id
                           JOIN parts p ON pv.part_id = p.id
                           LEFT JOIN geom_assets ga ON pv.cad_asset_id = ga.id
                  WHERE an.assembly_id = %s
                  ORDER BY an.name \
                  """

            cur.execute(sql, (uuid_to_bin(assembly_id),))
            rows = cur.fetchall()

            nodes = []
            for row in rows:
                nodes.append({
                    'node_id': bin_to_uuid(row['node_id']),
                    'node_name': row['node_name'],
                    'transform_json': row['transform_json'],
                    'version_id': bin_to_uuid(row['version_id']),
                    'version_no': row['version_no'],
                    'part_id': bin_to_uuid(row['part_id']),
                    'part_key': row['part_key'],
                    'part_name': row['part_name'],
                    'step_uri': row['step_uri']
                })

            return nodes

        finally:
            cur.close()
            conn.close()

    def get_part_geometry(self, version_id: str) -> Optional[str]:
        """获取零件几何文件路径"""
        conn = get_conn()
        cur = conn.cursor(dictionary=True)

        try:
            sql = """
                  SELECT ga.uri
                  FROM part_versions pv
                           JOIN geom_assets ga ON pv.cad_asset_id = ga.id
                  WHERE pv.id = %s \
                  """

            cur.execute(sql, (uuid_to_bin(version_id),))
            row = cur.fetchone()

            if row and row['uri']:
                # 转换 file://URI 为本地路径
                uri = row['uri']
                if uri.startswith('file://'):
                    return uri[7:].replace('/', '\\')  # Windows路径
                return uri

            return None

        finally:
            cur.close()
            conn.close()