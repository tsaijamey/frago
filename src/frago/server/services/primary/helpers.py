"""Stateless queue-validation constants/helpers + sub-agent bootstrap rendering.

从 primary_agent_service.py 抽出（Phase 4 第一步）：这些是模块级、无共享状态的纯函数与
常量，搬来零行为变化。primary_agent_service.py 仍 re-export 它们以保持对外符号与模块路径。
"""

from __future__ import annotations

from typing import Any

# Queue message types PA accepts (Phase 2: the validator collapsed from
# pa_validators.py to this minimal gate — only the enqueue path still needs it;
# the JSON-output validator is gone with the decision protocol).
VALID_QUEUE_MESSAGE_TYPES = {
    "user_message",
    "agent_completed", "agent_failed", "reply_failed",
    "scheduled_task",
    "recovered_failed_task",
    "resume_failed",
    "run_failed",
    "schedule_failed",
    # Phase 3 (去账本): worker（agent 用 `frago agent start` 起的 sub-agent）完成后
    # 以一条新消息带 conv 归属重入队列，PA 下一轮组织最终回复。
    "worker_done",
}

# Internal queue message types that have NO outbound user channel. When a turn
# consumes one of these and produces text, that text must NOT be delivered as a
# reply (there is nowhere to send it) and a failed delivery must NOT be re-fed as
# a reply_failed message — doing so creates a self-sustaining loop (reply_failed
# → deliver → no notify_recipe → reply_failed → ...).
# Note: agent_completed / worker_done carry the original user's real channel in
# their route, so they are deliverable and intentionally excluded here.
NON_DELIVERABLE_CHANNELS = frozenset({
    "reply_failed",
    "resume_failed",
    "run_failed",
    "schedule_failed",
})


def _validate_queue_message(msg: dict[str, Any]) -> tuple[bool, str]:
    """Minimal structural gate before a message enters the PA queue.

    Returns (ok, error). Keeps the dirty-data-out-of-the-queue guarantee that
    the old validate_queue_message gave, without the JSON decision machinery.
    """
    if not isinstance(msg, dict):
        return False, f"Expected dict, got {type(msg).__name__}."
    msg_type = msg.get("type")
    if msg_type not in VALID_QUEUE_MESSAGE_TYPES:
        return False, f'Invalid message type "{msg_type}".'
    if msg_type == "user_message":
        has_id = bool(msg.get("msg_id") or msg.get("task_id"))
        missing = [f for f in ("channel", "prompt") if not msg.get(f)]
        if not has_id:
            missing.insert(0, "msg_id")
        if missing:
            return False, f'user_message missing required fields: {", ".join(missing)}.'
    elif msg_type in ("agent_completed", "agent_failed"):
        missing = [f for f in ("task_id", "channel") if not msg.get(f)]
        if missing:
            return False, f'{msg_type} missing required fields: {", ".join(missing)}.'
    elif msg_type == "scheduled_task":
        missing = [f for f in ("msg_id", "schedule_id", "prompt") if not msg.get(f)]
        if missing:
            return False, f'scheduled_task missing required fields: {", ".join(missing)}.'
    elif msg_type == "recovered_failed_task":
        missing = [f for f in ("task_id", "channel", "original_prompt") if not msg.get(f)]
        if missing:
            return False, f'recovered_failed_task missing required fields: {", ".join(missing)}.'
    elif msg_type == "worker_done":
        # conv 归属至少要有 conv_key 或 channel 之一，否则无从路由回会话/投递。
        if not (msg.get("conv_key") or msg.get("channel")):
            return False, "worker_done missing conv attribution (conv_key/channel)."
    return True, ""


def _render_domain_peek(peek: dict[str, Any] | None) -> str:
    """Render a domain peek payload as compact prior-context for sub-agent bootstrap."""
    if not peek:
        return ""
    lines: list[str] = []
    domain = peek.get("domain") or ""
    lines.append(f"\nDomain 先验摘要 ({domain})")
    sess_count = peek.get("session_count")
    insi_count = peek.get("insight_count")
    last = peek.get("last_accessed")
    if sess_count is not None or insi_count is not None or last:
        lines.append(
            f"  status={peek.get('status')} sessions={sess_count} insights={insi_count} last={last}"
        )

    insights = peek.get("top_insights") or []
    if insights:
        lines.append("  Top insights:")
        for ins in insights:
            payload = (ins.get("payload") or "").replace("\n", " ").strip()
            if len(payload) > 160:
                payload = payload[:157] + "..."
            lines.append(
                f"    - [{ins.get('type')}] (conf={ins.get('confidence')}) {payload}"
            )

    sessions = peek.get("recent_sessions") or []
    if sessions:
        lines.append("  Recent sessions:")
        for s in sessions:
            sid = s.get("session_id") or ""
            head = (s.get("summary_head") or "").replace("\n", " | ")
            if len(head) > 120:
                head = head[:117] + "..."
            lines.append(f"    - {sid} {head}")
    lines.append("")
    return "\n".join(lines) + "\n"
