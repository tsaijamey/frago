"""``data:<关键词>`` —— 在 ``~/.frago/data`` 下找这个词。

``~/.frago/data/<语义目录>/`` 是产出物的落点：一次调研的笔记、一份 spec、一个
notebook 账本、几份中间数据。目录名带日期前缀、带限定词，agent 下次回来只记得
其中一小段。

带前缀就是"我知道要找的是产出物"，范围锁在这一处，快且干净。搜索与呈现的规则见
:mod:`frago.context.report`——三类命中各自成段，不吐全文。
"""

from __future__ import annotations

from pathlib import Path

from frago.context.report import SearchReport, search

DATA_ROOT = Path.home() / ".frago" / "data"


def resolve_data(keyword: str, *, root: Path | None = None) -> SearchReport:
    """在 ``~/.frago/data`` 下按关键词报告三类命中。"""
    return search(keyword, root or DATA_ROOT, ref=f"data:{keyword}")
