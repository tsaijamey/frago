"""不带 scheme 前缀时的兜底：把整个 ``~/.frago`` 翻一遍。

带前缀是精确查找——``data:cxmt`` 只看 ``~/.frago/data``，那里的每个目录都是一件
工作的产出，命中即有意义。不带前缀就没有这个约束，只能全盘找。

全盘找是有代价的，而且代价 MUST 在动手之前讲给调用方听，不能事后才发现：

- **慢**。这棵树有上万个目录、几十 GB，冷缓存下走一遍要好几秒。
- **脏**。其中绝大多数目录是机器用的——浏览器 profile、HTTP 缓存、recipe 的依赖
  树、日志轮转。它们的名字会跟关键词撞上，但没有一个是"上下文"。

所以这条路径不做默认、不做静默降级：命令层先把上面两件事摆出来，等调用方明确
同意再走。同意之后，扫过多少目录、跳过多少，随结果一并报出。
"""

from __future__ import annotations

from pathlib import Path

from frago.context.report import SearchReport, search

FRAGO_ROOT = Path.home() / ".frago"


def resolve_anywhere(keyword: str, *, root: Path | None = None) -> SearchReport:
    """在整个 ``~/.frago`` 下按关键词报告三类命中。"""
    return search(keyword, root or FRAGO_ROOT, ref=keyword)
