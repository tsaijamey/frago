"""Unified format validation for PA agent I/O.

Every validator is a function that accepts data and returns a ValidationResult.
Validation failure does NOT silently discard — the caller decides how to correct
(e.g., send error back to PA for re-output, return 400 to sub-agent, reject queue entry).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

VALID_PA_ACTIONS = {"reply", "run", "recipe", "update"}

VALID_QUEUE_MESSAGE_TYPES = {"user_message", "agent_notify", "agent_exit"}

# Required fields per PA action type (beyond the universal "action" field)
_PA_ACTION_REQUIRED_FIELDS: dict[str, list[str]] = {
    "reply": ["task_id", "channel", "reply_params"],
    "run": ["prompt"],
    "recipe": ["recipe_name"],
    "update": ["task_id"],
}


@dataclass
class ValidationResult:
    """Result of a validation check."""

    ok: bool
    error: str = ""
    raw_data: Any = field(default=None, repr=False)


# --------------------------------------------------------------------------
# [检查 PA 输出] [PA subprocess 返回后] [_handle_pa_output 入口]
# PA 必须输出 JSON 数组，每个元素必须有 action 字段。
# 校验失败 → 回传给 PA 要求重新输出（不是 rotate，给一次修正机会）。
# --------------------------------------------------------------------------
def validate_pa_output(text: str) -> ValidationResult:
    """Validate PA's JSON decision array output.

    Steps:
    1. Strip markdown code blocks (```json ... ```)
    2. Parse JSON
    3. Check it's a list
    4. Check each element has "action" field
    5. Check action is in VALID_PA_ACTIONS
    6. Check required fields per action type
    """
    cleaned = text.strip()

    # Strip markdown code block wrappers if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 3:
            # Remove first line (```json or ```) and last line (```)
            cleaned = "\n".join(lines[1:-1]).strip()
        else:
            return ValidationResult(
                ok=False,
                error="Output looks like a markdown code block but has fewer than 3 lines.",
                raw_data=text,
            )

    # Parse JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return ValidationResult(
            ok=False,
            error=f"JSON parse error: {e}",
            raw_data=text,
        )

    # Must be a list
    if not isinstance(data, list):
        return ValidationResult(
            ok=False,
            error=f"Expected JSON array, got {type(data).__name__}.",
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

    return ValidationResult(ok=True, raw_data=data)


# --------------------------------------------------------------------------
# [检查 pa/notify 输入] [POST /api/pa/notify 入口]
# sub-agent 的完成通知必须包含 run_id。
# 校验失败 → 返回 400，sub-agent 会看到错误并重试。
# --------------------------------------------------------------------------
def validate_agent_notify(data: dict) -> ValidationResult:
    """Validate sub-agent completion notification payload.

    Rules:
    1. Must have run_id
    2. Must have summary or error (at least one)
    3. outputs must be list if present
    """
    if not isinstance(data, dict):
        return ValidationResult(
            ok=False,
            error=f"Expected dict, got {type(data).__name__}.",
            raw_data=data,
        )

    if not data.get("run_id"):
        return ValidationResult(
            ok=False,
            error='Missing required field "run_id".',
            raw_data=data,
        )

    has_summary = bool(data.get("summary"))
    has_error = bool(data.get("error"))
    if not has_summary and not has_error:
        return ValidationResult(
            ok=False,
            error='Must have at least one of "summary" or "error".',
            raw_data=data,
        )

    outputs = data.get("outputs")
    if outputs is not None and not isinstance(outputs, list):
        return ValidationResult(
            ok=False,
            error=f'"outputs" must be a list if present, got {type(outputs).__name__}.',
            raw_data=data,
        )

    return ValidationResult(ok=True, raw_data=data)


# --------------------------------------------------------------------------
# [检查消息投递格式] [消息入队前]
# 所有进入 PA 消息队列的消息必须有 type 字段。
# 校验失败 → 日志告警 + 拒绝入队（不能让脏数据进队列）。
# --------------------------------------------------------------------------
def validate_queue_message(msg: dict) -> ValidationResult:
    """Validate a message before it enters the PA message queue.

    Rules:
    1. Must have type in VALID_QUEUE_MESSAGE_TYPES
    2. user_message must have task_id, channel, prompt
    3. agent_notify must have run_id
    4. agent_exit must have run_id
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
        missing = [f for f in ("task_id", "channel", "prompt") if not msg.get(f)]
        if missing:
            return ValidationResult(
                ok=False,
                error=f'user_message missing required fields: {", ".join(missing)}.',
                raw_data=msg,
            )

    elif msg_type == "agent_notify":
        if not msg.get("run_id"):
            return ValidationResult(
                ok=False,
                error='agent_notify missing required field "run_id".',
                raw_data=msg,
            )

    elif msg_type == "agent_exit":
        if not msg.get("run_id"):
            return ValidationResult(
                ok=False,
                error='agent_exit missing required field "run_id".',
                raw_data=msg,
            )

    return ValidationResult(ok=True, raw_data=msg)
