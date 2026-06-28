"""入站消息路由：conv_key 派生 + 确定性归属分类。

去账本后从 taskboard/ 救出的活核（spec 20260627-pa-deboard Phase 9）：
- ``conv_key`` —— 路由地基，入站派生 + PA 按 conv_key 分组。
- ``thread_classifier`` —— 每条入站消息的确定性归属分类（纯函数，包着 conv_key）。

与已退役的 taskboard 账本无关，只是历史上曾住在那个目录里。
"""

from __future__ import annotations

from frago.server.services.routing.conv_key import (
    CONV_KEY_DERIVERS,
    ConvKey,
    derive_conv_key,
)
from frago.server.services.routing.thread_classifier import classify

__all__ = [
    "CONV_KEY_DERIVERS",
    "ConvKey",
    "derive_conv_key",
    "classify",
]
