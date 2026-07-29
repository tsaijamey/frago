"""``frago context <scheme>:<key>`` —— 按关键词找出上下文落在哪儿。

agent 每次冷启动都不记得上次把东西放在哪。它知道的只是一个语义关键词
（"cxmt 那个视频"、"session workbench"），而落盘的目录名带日期前缀、带连字符、
带它没记住的限定词。让它先 ``ls`` 一遍再猜哪个是，等于每次都付一轮探索。

本包报告关键词在三个层面上的命中：目录名、文件名、可读文档的正文。**不吐全文**
——把哪些文件值得读交回给调用方，它清楚自己的预算。理由见 :mod:`frago.context.report`。

scheme 前缀（``data:``）留出扩展位：日后 ``run:`` / ``session:`` / ``recipe:``
各自注册一个解析器，命令形态不变。
"""

from frago.context.data_scheme import DATA_ROOT, resolve_data
from frago.context.errors import ContextError
from frago.context.matcher import Candidate, match_names, score_name
from frago.context.report import (
    MACHINE_SUFFIXES,
    READABLE_SUFFIXES,
    ContentHit,
    DirHit,
    FileHit,
    SearchReport,
    render,
    search,
    walk_names,
)
from frago.context.resolver import SCHEMES, resolve_ref, scheme_help, split_ref
from frago.context.whole_home import FRAGO_ROOT, resolve_anywhere

__all__ = [
    "DATA_ROOT",
    "FRAGO_ROOT",
    "MACHINE_SUFFIXES",
    "READABLE_SUFFIXES",
    "SCHEMES",
    "Candidate",
    "ContentHit",
    "ContextError",
    "DirHit",
    "FileHit",
    "SearchReport",
    "match_names",
    "render",
    "resolve_anywhere",
    "resolve_data",
    "resolve_ref",
    "scheme_help",
    "score_name",
    "search",
    "split_ref",
    "walk_names",
]
