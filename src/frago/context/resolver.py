"""引用解析：``<scheme>:<key>`` 走对应范围的检索，裸关键词走全盘兜底。

scheme 前缀是"我知道要去哪儿找"。只有 ``data:`` 一个 scheme 时这层看着多余，
但它定的是命令的形状：日后加 ``run:`` / ``session:`` / ``recipe:``，注册一行、
命令签名不变，调用方已经学会的写法不用重学。

裸关键词是"我不知道去哪儿找"。它 NEVER 被当成某个 scheme 的简写——那样会在加
第二个 scheme 的那天让所有老写法突然变成歧义。它有自己的含义：翻遍整个
``~/.frago``。代价见 :mod:`frago.context.whole_home`，由命令层在动手前征得同意。
"""

from __future__ import annotations

from collections.abc import Callable

from frago.context.data_scheme import resolve_data
from frago.context.errors import ContextError
from frago.context.report import SearchReport
from frago.context.whole_home import resolve_anywhere

# scheme 名 → (解析函数, 一句话说明)。解析函数签名统一为 ``(key) -> SearchReport``。
SCHEMES: dict[str, tuple[Callable[[str], SearchReport], str]] = {
    "data": (resolve_data, "~/.frago/data 下的工作目录（产出物、调研笔记、spec）"),
}


def scheme_help() -> str:
    return "\n".join(f"  {name}:<关键词>  —— {desc}" for name, (_, desc) in SCHEMES.items())


def split_ref(ref: str) -> tuple[str | None, str]:
    """把引用拆成 ``(scheme, key)``；没有前缀时 scheme 为 None。

    关键词本身可以带冒号，只切第一个。前缀里出现空白（``看看 data:x``）说明那个
    冒号属于正文而不是 scheme，同样按无前缀处理——NEVER 把半句话的一部分错认成
    命名空间。
    """
    scheme, sep, key = ref.partition(":")
    if not sep or not scheme or any(ch.isspace() for ch in scheme):
        stripped = ref.strip()
        if not stripped:
            raise ContextError("引用是空的", "frago context data:<关键词>")
        return None, stripped

    scheme = scheme.strip().lower()
    key = key.strip()
    if not key:
        raise ContextError(
            f"{ref!r} 只给了 scheme，没给关键词。",
            f"frago context {scheme}:<关键词>",
        )
    return scheme, key


def resolve_ref(ref: str, *, allow_whole_home: bool = False) -> SearchReport:
    """解析一个引用。

    裸关键词只有在 ``allow_whole_home`` 为真时才会真的去翻整个 ~/.frago——
    那趟活又慢又脏，调用方 MUST 先明确同意，NEVER 由这里替它决定。
    """
    scheme, key = split_ref(ref)

    if scheme is None:
        if not allow_whole_home:
            raise ContextError(
                f"{ref!r} 没有 scheme 前缀，需要先确认是否全盘搜索。",
                f"frago context data:{key}",
                f"frago context {key} --yes",
            )
        return resolve_anywhere(key)

    entry = SCHEMES.get(scheme)
    if entry is None:
        raise ContextError(
            f"不认识的 scheme {scheme!r}。可用的 scheme：\n{scheme_help()}",
            f"frago context data:{key}",
        )
    resolver, _ = entry
    return resolver(key)
