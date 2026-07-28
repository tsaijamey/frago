"""上下文解析的业务失败。

单独成模块只为一件事：``resolver`` 要 import 各个 scheme 的解析函数，
scheme 又要 raise 这个异常——放在任一侧都会绕成循环 import。
"""

from __future__ import annotations


class ContextError(Exception):
    """解析不出上下文。``fixes`` 是给 agent 的可直接粘贴执行的下一步。"""

    def __init__(self, message: str, *fixes: str) -> None:
        super().__init__(message)
        self.message = message
        self.fixes: tuple[str, ...] = tuple(f for f in fixes if f)
