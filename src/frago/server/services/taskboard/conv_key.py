"""Per-channel conversation-key contract (spec 20260623 Phase 2).

A ``ConvKey`` is the stable identity of one content topic on a channel. The
classifier's L0 layer uses it to land follow-up messages on the same thread.

Each channel derives its native conversation handle differently (feishu uses
chat_id, email the account address, slack the channel_id), so derivation lives
in a per-channel registry rather than a chain of ``if channel == ...`` blocks.
Channels not in the registry (scheduled / internal) have no conversation unit
and yield ``None``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ConvKey:
    """Stable identifier of a conversation unit on a single channel."""

    channel: str
    native_id: str

    @property
    def tag(self) -> str:
        return f"conv:{self.channel}:{self.native_id}"


def _feishu(_channel: str, reply_context: dict | None) -> ConvKey | None:
    if not reply_context:
        return None
    chat_id = reply_context.get("chat_id")
    return ConvKey("feishu", str(chat_id)) if chat_id else None


def _email(_channel: str, reply_context: dict | None) -> ConvKey | None:
    # 起步：单账号单 conversation，用发件账号地址作 native_id。reply_context 的
    # 发件账号字段沿用 ingestion 既有命名（sender_id，回落 sender）。
    if not reply_context:
        return None
    addr = reply_context.get("sender_id") or reply_context.get("sender")
    return ConvKey("email", str(addr)) if addr else None


def _slack(_channel: str, reply_context: dict | None) -> ConvKey | None:
    # 首版只用 channel_id（thread_ts 叠加留待后续）。
    if not reply_context:
        return None
    channel_id = reply_context.get("channel_id")
    return ConvKey("slack", str(channel_id)) if channel_id else None


CONV_KEY_DERIVERS: dict[str, Callable[[str, dict | None], ConvKey | None]] = {
    "feishu": _feishu,
    "email": _email,
    "slack": _slack,
}


def derive_conv_key(channel: str, reply_context: dict | None) -> ConvKey | None:
    """Resolve the conversation key for ``channel`` from its reply_context.

    Returns ``None`` for unregistered channels (scheduled / internal) or when
    the channel's native conversation field is absent.
    """
    deriver = CONV_KEY_DERIVERS.get(channel)
    if deriver is None:
        return None
    return deriver(channel, reply_context)
