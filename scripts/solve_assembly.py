import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

from src.solver.assembly_solver import AssemblySolver
from src.db.mysql import get_conn
from src.db.util import bin_to_uuid

def pick_latest_assembly() -> str:
    sql = "SELECT id FROM assemblies ORDER BY created_at DESC LIMIT 1"
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(sql)
        row = cur.fetchone()
        if not row:
            raise RuntimeError("数据库中没有 assemblies 记录，请先创建装配。")
        return bin_to_uuid(row[0])
    finally:
        cur.close(); conn.close()

def main():
    parser = argparse.ArgumentParser(description="最小装配求解器（distance/mate）")
    parser.add_argument("--assembly-id", help="要求解的装配 ID（UUID）", default=None)
    parser.add_argument("--iterations", type=int, default=1, help="迭代次数（默认 1）")
    args = parser.parse_args()

    asm_id = args.assembly_id or pick_latest_assembly()

    solver = AssemblySolver(iterations=args.iterations)
    solver.solve(asm_id)

if __name__ == "__main__":
    main()