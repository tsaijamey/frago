"""PA 投递路径（Phase 4 抽出）：把 agent 终答 + outbox 附件送回源 channel。

接 svc 首参的自由函数（route_for_group / warn_bareword_paths 无状态），跨方法调用走
svc.<method>。行为与原 PrimaryAgentService.deliver / _route_for_group /
_warn_bareword_paths 逐字一致（self → svc）。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from frago.server.services.primary.helpers import NON_DELIVERABLE_CHANNELS

logger = logging.getLogger(__name__)


def route_for_group(group: list[dict]) -> dict[str, Any]:
    """Pick the representative inbound message that carries the reply target.

    Prefers a message with a ``channel``; falls back to the first dict.
    Used as the ``route`` arg to ``deliver`` (channel + reply_context + ids).
    """
    for m in group:
        if isinstance(m, dict) and m.get("channel"):
            return m
    return group[0] if group and isinstance(group[0], dict) else {}


def warn_bareword_paths(
    text: str, attachments: list[dict[str, Any]], conv_key: str,
) -> None:
    """兜底观测：扫正文里「像存在的文件路径却没进 outbox」的，记日志。

    agent 漏调 ``frago agent attach`` 直接在正文写路径时，用户收到的还是路径
    文字而非附件。这里只记日志（可观测 + 后续补救线索），NEVER 自动投递——
    嗅探出的路径未必是要交付的制品（可能是引用的源码、日志等）。
    """
    import re

    attached = {Path(a.get("path", "")).resolve() for a in attachments}
    # 绝对路径 / ~ 起头 / 带至少一个目录分隔且含扩展名的相对路径。
    candidates = set(re.findall(r"(?:~|/|\.{1,2}/)[\w./\-]+\.\w+", text))
    missed: list[str] = []
    for cand in candidates:
        try:
            p = Path(cand).expanduser()
        except (OSError, ValueError):
            continue
        if p.exists() and p.is_file() and p.resolve() not in attached:
            missed.append(str(p))
    if missed:
        logger.warning(
            "deliver: %d bareword path(s) in text exist but were not attached "
            "(conv=%s) — agent should use `frago agent attach`: %s",
            len(missed), conv_key, missed,
        )


async def deliver(svc: Any, text: str, route: dict[str, Any]) -> None:
    """Push the agent's natural-language text back to the source channel.

    Phase 2: the resident agent's final text IS the reply content. ``route``
    is the inbound queue message (carries channel + reply_context, optionally
    task_id / msg_id for board fallback). Empty text is skipped — no empty
    reply is pushed (Edge Cases: agent 最终输出为空 → 跳过、记日志、不重试).
    """
    from frago.telemetry.trace import trace_entry

    text = (text or "").strip()
    channel = route.get("channel", "") or route.get("type", "")
    if not text:
        logger.info("deliver skipped: empty agent output (channel=%s)", channel)
        return
    if not channel:
        logger.warning("deliver skipped: no channel on route (route keys=%s)", list(route))
        return
    if channel in NON_DELIVERABLE_CHANNELS:
        logger.info(
            "deliver skipped: internal channel %s has no outbound destination "
            "(text dropped, no reply_failed re-enqueued)", channel,
        )
        return

    conv_key = route.get("conv_key")
    reply_context = (
        route.get("reply_context")
        or (svc._reply_context_cache.get(f"conv:{conv_key}") if conv_key else None)
        or svc._reply_context_cache.get(f"channel:{channel}")
    )
    task_id = route.get("task_id", "") or ""
    msg_id = route.get("msg_id", "") or ""

    # Phase 8（spec 20260627 交付即核心）：转发 pane 文本前 drain 该 conv 的
    # outbox——agent 经 ``frago agent attach`` 登记的文件作真附件随文本一起送达。
    # 兜底：扫正文里「像文件路径却没进 outbox」的，记日志（frago-core 现无 Stop
    # 事件接「收尾校验」，先放交付层观测；自动补救为后续 follow-up）。
    attachments: list[dict[str, Any]] = []
    if conv_key:
        from frago.server.services import pa_outbox

        attachments = await asyncio.to_thread(pa_outbox.drain, conv_key)
        svc._warn_bareword_paths(text, attachments, conv_key)

    result = await asyncio.to_thread(
        svc._lifecycle.deliver,
        channel,
        {"text": text},
        reply_context=reply_context,
        attachments=attachments,
        task_id=task_id,
        msg_id=msg_id,
    )

    if result.get("status") == "ok":
        _reply_data = {
            "task_id": task_id or "",
            "msg_id": msg_id or "",
            "channel": channel or "",
            "reply_text": text,
        }
        await svc._broadcast_pa_event("pa_reply", _reply_data)
        from frago.telemetry.trace import trace as _trace
        _trace(msg_id, task_id, "pa", f"回复 {channel}: {text[:80]}",
               data={"event_type": "pa_reply", **_reply_data})
        trace_entry(
            origin="internal", subkind="pa", data_type="action_result",
            thread_id=None, task_id=task_id or None,
            data={"action": "reply", "status": "ok",
                  "channel": channel, "text_len": len(text)},
            msg_id=msg_id or None,
            event=f"reply 成功: {channel}",
        )
    elif result.get("status") == "error":
        error_detail = result.get("error", "unknown")
        trace_entry(
            origin="internal", subkind="pa", data_type="action_result",
            thread_id=None, task_id=task_id or None,
            data={"action": "reply", "status": "failed",
                  "reason": "send_failed", "detail": error_detail,
                  "channel": channel},
            msg_id=msg_id or None,
            event=f"reply 失败: {error_detail[:80]}",
        )
        await svc.enqueue_message({
            "type": "reply_failed",
            "task_id": task_id,
            "channel": channel,
            "error": error_detail,
            "original_text": text,
        })
