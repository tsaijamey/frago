"""Thread attribution classifier — pure conv_key derivation (spec 20260627 Phase 3).

去账本后，分类退化为**纯函数**：一条入站消息确定性映射到一个常驻会话 key
(``conv_key``)，不再依赖 board tag 索引、不再有 thread 对象要建。

  L0 (free) — conversation-unit exact match：从 channel + reply_context 派生稳定
              key（feishu chat_id / email 发件人 / slack channel_id），见 conv_key.py
  L1 (free) — channel-native reply reference（feishu parent_message_id /
              email In-Reply-To / webhook conversation_id），同样派生稳定 key

L2（同发件人时间窗启发式）随账本一起删除——它依赖 board 的 last_active 索引，
且属于"模糊归并"，常驻会话模型下不需要。两层都不命中时返回 None，由调用方路由到
fallback 常驻会话（scheduled / internal 等无会话单元的消息天然走这里）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from frago.server.services.taskboard.conv_key import derive_conv_key

logger = logging.getLogger(__name__)


@dataclass
class ClassifyResult:
    conv_key: str | None            # 稳定会话 key（None → 路由到 fallback 会话）
    parent_ref: str | None          # channel-native parent message id (for L1)
    layer: str                      # "L0" | "L1" | "none"

    # Backward-compat alias: 老调用方读 ``thread_id``，语义即 conv_key。
    @property
    def thread_id(self) -> str | None:
        return self.conv_key

    @property
    def is_new(self) -> bool:  # 纯函数无"建/不建"概念，保留以兼容旧读取点
        return False


def _extract_conv_key(channel: str, reply_context: dict | None) -> str | None:
    """派生会话单元 key（含 channel 前缀），无则 None。委托 conv_key.derive_conv_key。"""
    key = derive_conv_key(channel, reply_context)
    if key is None:
        return None
    return f"{key.channel}:{key.native_id}"


def _extract_parent_ref(channel: str, reply_context: dict) -> str | None:
    """Extract channel-native parent message id, if present."""
    if not reply_context:
        return None

    if channel == "feishu":
        parent = reply_context.get("parent_message_id")
        return str(parent) if parent else None

    if channel == "email":
        irt = reply_context.get("in_reply_to")
        if irt:
            return str(irt)
        refs = reply_context.get("references")
        if isinstance(refs, list) and refs:
            return str(refs[0])
        if isinstance(refs, str) and refs:
            return refs.split()[0]
        return None

    if channel in ("webhook", "ui_input"):
        cid = reply_context.get("conversation_id") or reply_context.get("thread_id")
        return str(cid) if cid else None

    return None


def classify(
    *,
    channel: str,
    sender: str = "",  # noqa: ARG001 — kept for call-site signature compat
    content: str = "",  # noqa: ARG001
    reply_context: dict | None = None,
    **_ignored: object,
) -> ClassifyResult:
    """Derive the resident-session conv_key for an incoming external message.

    纯函数：仅从 channel + reply_context 确定性派生，无 I/O、无 board。
    """
    reply_context = reply_context or {}

    conv_key = _extract_conv_key(channel, reply_context)
    if conv_key:
        logger.debug("classify L0: channel=%s → conv_key=%s", channel, conv_key)
        return ClassifyResult(conv_key=conv_key, parent_ref=None, layer="L0")

    parent_ref = _extract_parent_ref(channel, reply_context)
    if parent_ref:
        key = f"{channel}:ref:{parent_ref}"
        logger.debug("classify L1: channel=%s parent=%s → conv_key=%s", channel, parent_ref, key)
        return ClassifyResult(conv_key=key, parent_ref=parent_ref, layer="L1")

    logger.debug("classify: no conv unit for channel=%s → fallback session", channel)
    return ClassifyResult(conv_key=None, parent_ref=None, layer="none")
