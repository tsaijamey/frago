"""本机那一侧敲的每个动作，中继那扇门都得放行。

门对不在清单上的动作回的是和「码不对」逐字节相同的 404，本机再把它说成「这个连接码
在中继上不可用」。于是漏掉一个动作不会报错，只会让人去怀疑一串完全没问题的码——
``send`` 就这样漏过：码和钥匙都对，状态、读对方都通，消息一条也投不出去。
"""

from __future__ import annotations

import ast
import inspect

from frago.server.routes import teaming
from frago.team import sync


def _actions_sync_sends() -> set[str]:
    """``sync.py`` 里朝中继敲出去的全部动作名：``client.call("x")`` 与 ``_call(..., "x")``。"""
    found: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(sync))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "call" and node.args:
            first = node.args[0]
        elif isinstance(func, ast.Name) and func.id == "_call" and len(node.args) >= 3:
            first = node.args[2]
        else:
            continue
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


def test_本机会敲的动作门都放行():
    sent = _actions_sync_sends()
    # 认得出这几个，说明上面的扫描没有失效成一个空集合
    assert {"open", "join", "send", "pull"} <= sent
    assert sent <= teaming.ACTIONS, f"门没放行：{sorted(sent - teaming.ACTIONS)}"
