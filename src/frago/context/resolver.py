"""scheme 分发：``<scheme>:<key>`` → 对应的解析器。

只有 ``data:`` 一个 scheme 时这层看着多余，但它定的是命令的形状：日后加
``run:`` / ``session:`` / ``recipe:``，注册一行、命令签名不变，agent 已经学会的
调用形态不用重学。
"""

from __future__ import annotations

from collections.abc import Callable

from frago.context.data_scheme import ContextResult, resolve_data
from frago.context.errors import ContextError

# scheme 名 → (解析函数, 一句话说明)。解析函数签名统一为 ``(key) -> ContextResult``。
SCHEMES: dict[str, tuple[Callable[[str], ContextResult], str]] = {
    "data": (resolve_data, "~/.frago/data 下的工作目录（产出物、调研笔记、spec）"),
}


def _scheme_help() -> str:
    return "\n".join(f"  {name}:<关键词>  —— {desc}" for name, (_, desc) in SCHEMES.items())


def split_ref(ref: str) -> tuple[str, str]:
    """把 ``data:cxmt-ipo`` 拆成 ``("data", "cxmt-ipo")``。

    关键词本身可以带冒号（只切第一个）。缺 scheme 前缀时报错并把原输入当关键词
    拼进修复建议——agent 十有八九只是漏了前缀。
    """
    scheme, sep, key = ref.partition(":")
    if not sep:
        raise ContextError(
            f"{ref!r} 缺少 scheme 前缀。可用的 scheme：\n{_scheme_help()}",
            f"frago context data:{ref}",
        )
    scheme = scheme.strip().lower()
    key = key.strip()
    if not scheme:
        raise ContextError(f"{ref!r} 的 scheme 是空的。可用的 scheme：\n{_scheme_help()}")
    if not key:
        raise ContextError(
            f"{ref!r} 只给了 scheme，没给关键词。",
            f"frago context {scheme}:<关键词>",
        )
    return scheme, key


def resolve_ref(ref: str) -> ContextResult:
    """解析一个引用。scheme 不认识时列出全部可用 scheme。"""
    scheme, key = split_ref(ref)
    entry = SCHEMES.get(scheme)
    if entry is None:
        raise ContextError(
            f"不认识的 scheme {scheme!r}。可用的 scheme：\n{_scheme_help()}",
            f"frago context data:{key}",
        )
    resolver, _ = entry
    return resolver(key)
