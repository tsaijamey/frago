"""PA bootstrap prompt builder — constructs context for new PA sessions.

Builds the bootstrap prompt from multiple data sources:
system environment, per-channel conversation history, and knowledge index.
"""

import json
import logging
import platform
import time
from datetime import datetime
from pathlib import Path

from frago.server.services.pa_prompts import (
    PA_BOOTSTRAP_CHANNEL_HEADER_TEMPLATE,
    PA_BOOTSTRAP_CONVERSATION_HEADER,
    PA_BOOTSTRAP_KNOWLEDGE_TEMPLATE,
    PA_BOOTSTRAP_REBORN_RESTART,
    PA_BOOTSTRAP_REBORN_ROTATION_TEMPLATE,
    PA_BOOTSTRAP_SYSTEM_ENV_TEMPLATE,
    PA_BOOTSTRAP_TURN_PA_DISPATCH_LINE_TEMPLATE,
    PA_BOOTSTRAP_TURN_PA_PENDING_LINE_TEMPLATE,
    PA_BOOTSTRAP_TURN_PA_REPLY_LINE_TEMPLATE,
    PA_BOOTSTRAP_TURN_USER_LINE_TEMPLATE,
)
from frago.server.services.trace import (
    ConversationTurn,
    load_conversation_turns,
    load_conversation_turns_by_channel,
)

logger = logging.getLogger(__name__)


def detect_reborn_reason(rotation_count: int) -> str:
    """Detect why this PA session is being created."""
    if rotation_count > 0:
        return "rotation"
    recent = load_conversation_turns(limit=1)
    if recent:
        return "server_restart"
    return "fresh_start"


def _build_system_env(model_id: str) -> str:
    tz_name = time.tzname[time.daylight] if time.daylight else time.tzname[0]
    now = datetime.now()
    return PA_BOOTSTRAP_SYSTEM_ENV_TEMPLATE.format(
        os_system=platform.system(),
        os_release=platform.release(),
        model_id=model_id,
        tz_name=tz_name,
        current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _detect_model_id() -> str:
    try:
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            custom_model = settings.get("ANTHROPIC_MODEL")
            if isinstance(custom_model, str) and custom_model:
                return custom_model
    except Exception:
        pass
    return "claude default"


def _build_reborn_info(reason: str, rotation_count: int) -> str | None:
    if reason == "rotation":
        return PA_BOOTSTRAP_REBORN_ROTATION_TEMPLATE.format(
            session_number=rotation_count + 1,
        )
    if reason == "server_restart":
        return PA_BOOTSTRAP_REBORN_RESTART
    return None


def _format_turn_lines(turns: list[ConversationTurn]) -> list[str]:
    lines: list[str] = []
    for turn in turns:
        ts = ""
        if turn.timestamp:
            try:
                dt = datetime.fromisoformat(turn.timestamp)
                ts = dt.strftime("%H:%M")
            except ValueError:
                ts = turn.timestamp[:5]

        lines.append(PA_BOOTSTRAP_TURN_USER_LINE_TEMPLATE.format(
            ts=ts,
            user_message=turn.user_message,
        ))
        if turn.pa_response:
            if turn.action == "dispatch" and turn.task_id:
                lines.append(PA_BOOTSTRAP_TURN_PA_DISPATCH_LINE_TEMPLATE.format(
                    ts=ts,
                    pa_response=turn.pa_response,
                    task_id_short=turn.task_id[:8],
                ))
            else:
                lines.append(PA_BOOTSTRAP_TURN_PA_REPLY_LINE_TEMPLATE.format(
                    ts=ts,
                    pa_response=turn.pa_response,
                ))
        elif turn.action == "pending":
            lines.append(PA_BOOTSTRAP_TURN_PA_PENDING_LINE_TEMPLATE.format(ts=ts))
    return lines


def _build_conversation_history(per_channel_limit: int = 10) -> str | None:
    by_channel = load_conversation_turns_by_channel(per_channel_limit=per_channel_limit)
    # Drop empty channels (defensive — load_conversation_turns_by_channel
    # already excludes channels with no turns).
    by_channel = {ch: turns for ch, turns in by_channel.items() if turns}
    if not by_channel:
        return None

    # Most-recently-active channel first; no channel is highlighted as primary.
    sorted_channels = sorted(
        by_channel.items(),
        key=lambda kv: kv[1][-1].timestamp,
        reverse=True,
    )

    lines = [PA_BOOTSTRAP_CONVERSATION_HEADER]
    for channel, turns in sorted_channels:
        lines.append("")
        lines.append(PA_BOOTSTRAP_CHANNEL_HEADER_TEMPLATE.format(
            channel=channel,
            turn_count=len(turns),
        ))
        lines.extend(_format_turn_lines(turns))

    return "\n".join(lines)


def _build_thread_section() -> str | None:
    """Thread-aware folded view (spec 20260418-timeline-consumer-unification Phase 2).

    Produces a compact text block showing hot threads expanded and warm threads
    as summaries. PA is hinted to use `frago thread search/hydrate` for cold
    threads not shown here.
    """
    try:
        from frago.server.services.timeline_service import get_thread_context
        ctx = get_thread_context()
    except Exception:
        logger.debug("Failed to build thread section", exc_info=True)
        return None

    if not ctx["hot"] and not ctx["warm"]:
        return None

    lines = ["## Active threads (timeline-folded view)"]
    lines.append(
        f"Hot: {ctx['counts']['hot']}, Warm: {ctx['counts']['warm']}, "
        f"Total known: {ctx['counts']['total_known']}"
    )

    if ctx["hot"]:
        lines.append("")
        lines.append("### Hot threads (active in last 24h)")
        for h in ctx["hot"]:
            d = h["digest"]
            head = (
                f"- [{d['thread_id']}] {d['origin']}/{d['subkind']} "
                f"— {d['root_summary']!r} (status={d['status']}, "
                f"last={d['last_active_ts'][:19]}, entries={d['entry_count']})"
            )
            lines.append(head)
            if d.get("task_status_summary"):
                lines.append(f"    tasks: {d['task_status_summary']}")
            if d.get("latest_event"):
                lines.append(f"    latest: {d['latest_event']}")

    if ctx["warm"]:
        lines.append("")
        lines.append("### Warm threads (24h–7d, digest only)")
        for d in ctx["warm"]:
            lines.append(
                f"- [{d['thread_id']}] {d['origin']}/{d['subkind']} "
                f"— {d['root_summary']!r} (last={d['last_active_ts'][:19]})"
            )

    lines.append("")
    lines.append(f"> {ctx['cold_hint']}")

    return "\n".join(lines)


def _build_knowledge_index() -> str | None:
    try:
        knowledge_file = Path(__file__).parent / "agent_knowledge.json"
        knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
        return PA_BOOTSTRAP_KNOWLEDGE_TEMPLATE.format(
            knowledge_json=json.dumps(knowledge, ensure_ascii=False, indent=2),
        )
    except Exception:
        return None


def build_bootstrap(rotation_count: int) -> tuple[str, str]:
    """Build the full bootstrap prompt for a new PA session.

    Returns (bootstrap_prompt, reborn_reason).
    reborn_reason is one of: "rotation", "server_restart", "fresh_start".
    """
    reason = detect_reborn_reason(rotation_count)

    sections: list[str] = []

    model_id = _detect_model_id()
    sections.append(_build_system_env(model_id))

    reborn_info = _build_reborn_info(reason, rotation_count)
    if reborn_info:
        sections.append(reborn_info)

    # 不代入任务快照：重启后任务由 ingestion 自然驱动；
    # 任务状态在消息触达 PA 时按需呈现，避免把"历史回顾"误当成"待办列表"。

    # Thread-aware view (spec 20260418-timeline-consumer-unification Phase 2)
    thread_section = _build_thread_section()
    if thread_section:
        sections.append(thread_section)

    # Legacy conversation turns (kept as complementary user-PA pairing view;
    # future: drop once thread view is proven sufficient).
    conversation = _build_conversation_history()
    if conversation:
        sections.append(conversation)

    knowledge = _build_knowledge_index()
    if knowledge:
        sections.append(knowledge)

    return "\n\n".join(sections), reason
