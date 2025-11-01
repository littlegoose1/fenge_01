#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例：进程内求解 API，供联调。把这里换成你的真实求解逻辑即可。
函数签名建议保持：
    solve_assembly(assembly_id: Optional[str], iterations: int, log: Optional[callable]) -> Any
- assembly_id 可为 None/"" 表示“最新装配”
- iterations 为最大迭代步数
- log 回调可选：传入字符串以记录到GUI（Worker会收集并在完成时显示）
"""
import time
from typing import Optional, Any


def solve_assembly(
    assembly_id: Optional[str],
    iterations: int = 10,
    log=None,
) -> Any:
    asm = assembly_id or "最新装配"
    if log:
        log(f"开始求解: assembly={asm}, max_iterations={iterations}")

    # 这里用睡眠模拟迭代过程；把它替换为你的实际迭代求解
    for i in range(1, iterations + 1):
        time.sleep(0.05)
        if log:
            log(f"iter {i}: residual={(1.0 / i):.6f}")

    if log:
        log("收敛或达到最大迭代步数")

    # 返回任意对象（dict/字符串/自定义类都可以）
    return {"assembly_id": asm, "status": "ok", "iterations": iterations}