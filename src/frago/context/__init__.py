"""``frago context <scheme>:<key>`` —— 把一个短关键词解析成一段可读的上下文。

agent 每次冷启动都不记得上次把东西放在哪。它知道的只是一个语义关键词
（"cxmt 那个视频"、"session workbench"），而落盘的目录名带日期前缀、带连字符、
带它没记住的限定词。让它先 ``ls`` 一遍再猜哪个是，等于每次都付一轮探索。

本包把「关键词 → 目录 → 目录里有什么 → 索引型小文件的全文」压成一条命令。
scheme 前缀（``data:``）留出扩展位：日后 ``run:`` / ``session:`` / ``recipe:``
各自注册一个解析器，命令形态不变。
"""

from frago.context.data_scheme import (
    DATA_ROOT,
    ContextResult,
    FileEntry,
    render,
    resolve_data,
)
from frago.context.errors import ContextError
from frago.context.matcher import Candidate, match_names, score_name
from frago.context.resolver import SCHEMES, resolve_ref, split_ref

__all__ = [
    "DATA_ROOT",
    "SCHEMES",
    "Candidate",
    "ContextError",
    "ContextResult",
    "FileEntry",
    "match_names",
    "render",
    "resolve_data",
    "resolve_ref",
    "score_name",
    "split_ref",
]
