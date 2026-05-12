"""Unified format validation for PA agent I/O.

Every validator is a function that accepts data and returns a ValidationResult.
Validation failure does NOT silently discard — the caller decides how to correct
(e.g., send error back to PA for re-output, return 400 to sub-agent, reject queue entry).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# spec freeze v1.1 §3: PA 对 Msg 输出的 action 词汇集 = {run, reply, resume, dismiss} 4 个
# schedule 是 PA 全局 action (注册 cron), 走独立 SchedulerService 通路, 不在 Msg loop 内.
# B-2a: schedule 已从 PA action 词汇集移除, SchedulerService 改由 cron-style trigger
# 直接调 Ingestor.ingest_scheduled (无需 PA 显式 "schedule" decision).
VALID_PA_ACTIONS = {"reply", "run", "resume", "dismiss"}

# Msg-action 词汇 (spec freeze v1.1 §3 严格 4 个, 用于 DecisionApplier 路由)
VALID_MSG_ACTIONS = {"run", "reply", "resume", "dismiss"}

VALID_QUEUE_MESSAGE_TYPES = {
    "user_message",
    "agent_completed", "agent_failed", "reply_failed",
    "scheduled_task",
    "recovered_failed_task",
    "internal_reflection",  # spec 20260418-timeline-event-coverage Phase 5
    # Action delivery feedback — PA needs to know when its decisions got silently dropped
    "resume_failed",
    "run_failed",
    "schedule_failed",
}

# Required fields per PA action type (beyond the universal "action" field)
# reply/run: require (task_id OR msg_id) + other fields
# resume: always requires task_id (only for existing tasks)
_PA_ACTION_REQUIRED_FIELDS: dict[str, list[str]] = {
    "reply": ["channel", "text"],       # + task_id OR msg_id (checked separately)
    "run": ["channel", "description", "prompt"],  # + task_id OR msg_id
    "resume": ["task_id", "prompt"],    # always task_id
    "dismiss": ["msg_id"],              # spec v1.1: PA 显式放弃 msg, 不创建 task
}


def validate_prompt_format(prompt: str) -> str | None:
    """spec freeze v1.1 §3 prompt 格式契约: 首行 ≤80 字摘要 + 空行 + 正文.

    Applier 调用此函数, 不符则 reject(reason=prompt_format_invalid).
    返回 None = 合法; 返回 str = 非法理由.
    """
    if not prompt:
        return "prompt is empty"
    parts = prompt.split("\n", 2)
    if len(parts) < 2:
        return "prompt missing newline (need '首行摘要\\n\\n正文')"
    first_line = parts[0]
    if len(first_line) > 80:
        return f"first line length {len(first_line)} > 80 chars"
    if "```" in first_line:
        return "first line contains code fence"
    if len(parts) >= 2 and parts[1].strip() != "":
        return "missing blank line between summary and body"
    return None

# Actions that require either task_id or msg_id
_ACTIONS_REQUIRING_ID: set[str] = {"reply", "run"}


@dataclass
class ValidationResult:
    """Result of a validation check."""

    ok: bool
    error: str = ""
    raw_data: Any = field(default=None, repr=False)


def _parse_json_array(text: str) -> list[Any] | None:
    """Parse a JSON array from text, tolerating all known PA output quirks.

    Handles: markdown code blocks, natural language prefix/suffix,
    real newlines in string values, trailing punctuation.
    Returns parsed list or None.
    """
    cleaned = text.strip()

    # Strip markdown code block wrappers
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()

    # Strategy 1: direct parse (covers clean output)
    try:
        data = json.loads(cleaned, strict=False)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 2: find last '[...]' block (PA may output [] then correct itself)
    last_bracket = cleaned.rfind("]")
    if last_bracket != -1:
        # Search backwards for the matching '['
        depth = 0
        for i in range(last_bracket, -1, -1):
            if cleaned[i] == "]":
                depth += 1
            elif cleaned[i] == "[":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[i : last_bracket + 1]
                    try:
                        data = json.loads(candidate, strict=False)
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        pass
                    break

    # Strategy 3: find first '[' and last ']', try that substring
    first_bracket = cleaned.find("[")
    if first_bracket != -1 and last_bracket is not None and last_bracket > first_bracket:
        candidate = cleaned[first_bracket : last_bracket + 1]
        try:
            data = json.loads(candidate, strict=False)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


# --------------------------------------------------------------------------
# [检查 PA 输出] [PA subprocess 返回后] [_handle_pa_output 入口]
# --------------------------------------------------------------------------
def validate_pa_output(text: str) -> ValidationResult:
    """Validate PA's JSON decision array output.

    Parsing is intentionally lenient (tolerates prefix text, real newlines,
    markdown wrappers). Validation of the parsed structure is strict.
    """
    data = _parse_json_array(text)
    if data is None:
        return ValidationResult(
            ok=False,
            error=f"No valid JSON array found in output (len={len(text.strip())})",
            raw_data=text,
        )

    # Empty list is valid (idle)
    if not data:
        return ValidationResult(ok=True, raw_data=data)

    # Validate each element
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return ValidationResult(
                ok=False,
                error=f"Element [{i}] is not a JSON object (got {type(item).__name__}).",
                raw_data=text,
            )

        action = item.get("action")
        if action is None:
            return ValidationResult(
                ok=False,
                error=f'Element [{i}] missing "action" field.',
                raw_data=text,
            )

        if action not in VALID_PA_ACTIONS:
            return ValidationResult(
                ok=False,
                error=f'Element [{i}] has unknown action "{action}". '
                      f"Valid actions: {', '.join(sorted(VALID_PA_ACTIONS))}.",
                raw_data=text,
            )

        # Check required fields for this action type
        required = _PA_ACTION_REQUIRED_FIELDS.get(action, [])
        for field_name in required:
            if field_name not in item:
                return ValidationResult(
                    ok=False,
                    error=f'Element [{i}] (action="{action}") missing required field "{field_name}".',
                    raw_data=text,
                )

        # reply/run must have either task_id or msg_id
        if action in _ACTIONS_REQUIRING_ID and not item.get("task_id") and not item.get("msg_id"):
                return ValidationResult(
                    ok=False,
                    error=f'Element [{i}] (action="{action}") missing "task_id" or "msg_id" — at least one is required.',
                    raw_data=text,
                )

    return ValidationResult(ok=True, raw_data=data)


# --------------------------------------------------------------------------
# [检查消息投递格式] [消息入队前]
# 所有进入 PA 消息队列的消息必须有 type 字段。
# 校验失败 → 日志告警 + 拒绝入队（不能让脏数据进队列）。
# --------------------------------------------------------------------------
def validate_queue_message(msg: dict[str, Any]) -> ValidationResult:
    """Validate a message before it enters the PA message queue.

    Rules:
    1. Must have type in VALID_QUEUE_MESSAGE_TYPES
    2. user_message must have task_id, channel, prompt
    3. agent_completed/agent_failed must have task_id, channel
    """
    if not isinstance(msg, dict):
        return ValidationResult(
            ok=False,
            error=f"Expected dict, got {type(msg).__name__}.",
            raw_data=msg,
        )

    msg_type = msg.get("type")
    if msg_type not in VALID_QUEUE_MESSAGE_TYPES:
        return ValidationResult(
            ok=False,
            error=f'Invalid message type "{msg_type}". '
                  f"Valid types: {', '.join(sorted(VALID_QUEUE_MESSAGE_TYPES))}.",
            raw_data=msg,
        )

    if msg_type == "user_message":
        # New flow: msg_id (from scheduler). Legacy flow: task_id (from recovery).
        has_id = bool(msg.get("msg_id") or msg.get("task_id"))
        missing = [f for f in ("channel", "prompt") if not msg.get(f)]
        if not has_id:
            missing.insert(0, "msg_id")
        if missing:
            return ValidationResult(
                ok=False,
                error=f'user_message missing required fields: {", ".join(missing)}.',
                raw_data=msg,
            )

    elif msg_type in ("agent_completed", "agent_failed"):
        missing = [f for f in ("task_id", "channel") if not msg.get(f)]
        if missing:
            return ValidationResult(
                ok=False,
                error=f'{msg_type} missing required fields: {", ".join(missing)}.',
                raw_data=msg,
            )

    elif msg_type == "scheduled_task":
        missing = [f for f in ("msg_id", "schedule_id", "prompt") if not msg.get(f)]
        if missing:
            return ValidationResult(
                ok=False,
                error=f'scheduled_task missing required fields: {", ".join(missing)}.',
                raw_data=msg,
            )

    elif msg_type == "recovered_failed_task":
        missing = [
            f for f in ("task_id", "channel", "original_prompt") if not msg.get(f)
        ]
        if missing:
            return ValidationResult(
                ok=False,
                error=f'recovered_failed_task missing required fields: {", ".join(missing)}.',
                raw_data=msg,
            )

    return ValidationResult(ok=True, raw_data=msg)
