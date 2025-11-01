import os
import traceback
import importlib
import time
from typing import Optional, Callable, Any

from PySide6 import QtCore


def _resolve_api(api_spec: str) -> Callable[..., Any]:
    """
    解析 "package.module:function" 形式的字符串，返回可调用对象
    例如: "my_pkg.my_mod:solve_assembly"
    """
    if ":" not in api_spec:
        raise ValueError(f"SOLVER_API 需要是 'module.submodule:function' 形式，当前: {api_spec}")
    module_name, func_name = api_spec.split(":", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, func_name, None)
    if not callable(func):
        raise AttributeError(f"在模块 {module_name} 中未找到可调用对象: {func_name}")
    return func


class SolveAssemblyWorker(QtCore.QThread):
    """
    后台求解线程：进程内调用 Python 函数（不依赖命令行/子进程）
    - 通过环境变量 SOLVER_API 或构造参数 api_target 指定求解函数
    - 规格: api_target/SOLVER_API = "package.module:function"
    - 调用约定: function(assembly_id: Optional[str], iterations: int, log: Optional[callable]) -> Any
      - 可忽略 log 参数；结果可为任意对象，将被格式化到消息中
    """
    finished = QtCore.Signal(bool, str, str)  # success, message, assembly_id(可能为空)

    def __init__(
        self,
        assembly_id: Optional[str],
        iterations: int = 1,
        parent=None,
        api_target: Optional[str] = None,
    ):
        super().__init__(parent)
        self.assembly_id = assembly_id
        self.iterations = max(1, int(iterations))
        # 优先级: 构造参数 > 环境变量 > 内置示例
        self.api_spec = api_target or os.getenv(
            "SOLVER_API", "src.services.solver_api_example:solve_assembly"
        )

        self._logs: list[str] = []

    def _log(self, msg: str):
        """供求解函数回调记录日志"""
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._logs.append(line)
        # 如需实时显示到 UI，这里可以发一个 signal 让主线程添加到日志窗口

    def run(self):
        try:
            func = _resolve_api(self.api_spec)
        except Exception as e:
            tb = traceback.format_exc()
            self.finished.emit(
                False,
                f"无法加载求解 API（{self.api_spec}）：{e}\n{tb}",
                self.assembly_id or "",
            )
            return

        try:
            # 优先尝试带 log 回调
            try:
                result = func(
                    assembly_id=self.assembly_id,
                    iterations=self.iterations,
                    log=self._log,
                )
            except TypeError:
                # 兼容不接收 log 参数的函数
                result = func(
                    assembly_id=self.assembly_id, iterations=self.iterations
                )

            # 组织消息
            logs_text = "\n".join(self._logs).strip()
            result_text = repr(result)
            msg = (
                f"求解完成（API: {self.api_spec}）。\n"
                f"装配: {self.assembly_id or '最新'}，最大迭代: {self.iterations}\n\n"
                f"日志:\n{logs_text}\n\n"
                f"结果:\n{result_text}"
            )
            self.finished.emit(True, msg, self.assembly_id or "")
        except Exception as e:
            tb = traceback.format_exc()
            logs_text = "\n".join(self._logs).strip()
            msg = (
                f"求解异常（API: {self.api_spec}）。\n"
                f"装配: {self.assembly_id or '最新'}，最大迭代: {self.iterations}\n\n"
                f"已产生的日志:\n{logs_text}\n\n"
                f"异常信息:\n{e}\n{tb}"
            )
            self.finished.emit(False, msg, self.assembly_id or "")