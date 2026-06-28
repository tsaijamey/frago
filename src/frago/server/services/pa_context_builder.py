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
    PA_BOOTSTRAP_REBORN_RESPAWN,
    PA_BOOTSTRAP_REBORN_RESTART,
    PA_BOOTSTRAP_REBORN_ROTATION_TEMPLATE,
    PA_BOOTSTRAP_SYSTEM_ENV_TEMPLATE,
    PA_BOOTSTRAP_TURN_PA_DISPATCH_LINE_TEMPLATE,
    PA_BOOTSTRAP_TURN_PA_NOTED_LINE_TEMPLATE,
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


def detect_reborn_reason(
    rotation_count: int,
    create_reason: str | None = None,
) -> str:
    """Detect why this PA session is being created.

    If create_reason is provided by the caller, it takes precedence over
    the rotation_count heuristic — callers know their intent precisely,
    whereas rotation_count alone cannot distinguish the first rotation
    (count still 0 pre-increment) from a genuine server restart, nor
    distinguish a server restart from a PA subprocess respawn.

    create_reason mapping:
      - "rotation"                        → "rotation"
      - "heartbeat" / "queue_consumer"    → "respawn"
      - "initialize" / None / other       → heuristic (history → server_restart,
                                            otherwise fresh_start)
    """
    if create_reason == "rotation":
        return "rotation"
    if create_reason in ("heartbeat", "queue_consumer"):
        return "respawn"
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
    if reason == "respawn":
        return PA_BOOTSTRAP_REBORN_RESPAWN
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
        if turn.action == "noted":
            lines.append(PA_BOOTSTRAP_TURN_PA_NOTED_LINE_TEMPLATE.format(
                ts=ts,
                pa_response=turn.pa_response or "(无 action)",
            ))
        elif turn.pa_response:
            if turn.action == "dispatch" and turn.task_id:
                lines.append(PA_BOOTSTRAP_TURN_PA_DISPATCH_LINE_TEMPLATE.format(
                    ts=ts,
                    pa_response=turn.pa_response,
                    task_id=turn.task_id,
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


def _build_knowledge_index() -> str | None:
    try:
        knowledge_file = Path(__file__).parent / "agent_knowledge.json"
        knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
        return PA_BOOTSTRAP_KNOWLEDGE_TEMPLATE.format(
            knowledge_json=json.dumps(knowledge, ensure_ascii=False, indent=2),
        )
    except Exception:
        return None


def build_bootstrap(
    rotation_count: int,
    create_reason: str | None = None,
    thread_id: str | None = None,
) -> tuple[str, str]:
    """Build the full bootstrap prompt for a new PA session.

    ``thread_id`` optional: when set, the board view is filtered to only that
    thread (Phase 3 per-conversation routing). Default None = full view.

    Returns (bootstrap_prompt, reborn_reason).
    reborn_reason is one of: "rotation", "server_restart", "respawn", "fresh_start".
    """
    reason = detect_reborn_reason(rotation_count, create_reason=create_reason)

    sections: list[str] = []

    model_id = _detect_model_id()
    sections.append(_build_system_env(model_id))

    reborn_info = _build_reborn_info(reason, rotation_count)
    if reborn_info:
        sections.append(reborn_info)

    # Phase 3 (去账本): 不再注入 board view / thread folded view——历史与任务状态由
    # 常驻会话自带上下文 + claude 原生 transcript 承担。bootstrap 只留系统环境 +
    # 人格(reborn) + 会话回顾 + 知识索引。``thread_id`` 形参保留以兼容调用方签名。
    _ = thread_id
    conversation = _build_conversation_history()
    if conversation:
        sections.append(conversation)

    knowledge = _build_knowledge_index()
    if knowledge:
        sections.append(knowledge)

    return "\n\n".join(sections), reason
