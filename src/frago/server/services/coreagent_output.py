"""读 CoreAgent（``frago-core``）的机器输出，新老两种形状都认。

2026-09-24 起，CoreAgent 多轮模式的 ``--output-format json / stream-json`` 照 Claude Code 的
``claude -p`` 写：结论是一行 ``{"type":"result", …}``，过程是 ``system/init`` → ``assistant`` /
``user`` → ``result``。之前是 frago 自己的形状：结论是 ``{"type":"final", …}``，过程是
``thinking / tool / result / done / error``。

装在本机的内核可能还是旧的，服务端这边又不止一处在读它的输出，所以统一在这里读：
新形状翻回老形状交出去，各处原来按老形状写的判断一行不用动，新旧两版内核都接得住。
"""

from __future__ import annotations

import json
from typing import Any

# CoreAgent 在工具结果开头写的拒绝标记：不在允许范围、被 frago 规则拒、被用户 hook 拒。
_DENIAL_MARKS = ("〔not allowed〕", "〔rules refused〕", "〔hook refused〕")


def final_from(stdout: str) -> dict[str, Any] | None:
    """内核结束时交的那一行结论，按老形状（``type == "final"``）交出。

    认两种：老的 ``final`` 行原样返回；新的 Claude Code ``result`` 行翻成老形状。
    标准输出里别的行不认。
    """
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "final":
            return obj
        if _is_cc_result(obj):
            return _final_from_result(obj)
    return None


def _is_cc_result(obj: dict[str, Any]) -> bool:
    """Claude Code 的结论行。老形状里工具结果也叫 ``result``，但它带 ``tool_call_id``。"""
    return obj.get("type") == "result" and "tool_call_id" not in obj and "subtype" in obj


def _final_from_result(obj: dict[str, Any]) -> dict[str, Any]:
    failed = bool(obj.get("is_error"))
    body = str(obj.get("result") or "")
    kind = obj.get("error_kind") or (obj.get("subtype") if failed else None)
    return {
        "type": "final",
        "ok": not failed,
        "text": "" if failed else body,
        "rounds": obj.get("num_turns"),
        "mode": "agent",
        "role": obj.get("role"),
        "profile": obj.get("profile"),
        "model": obj.get("model"),
        "wire": obj.get("wire"),
        "duration_ms": obj.get("duration_ms"),
        "error_kind": kind,
        "error": body if failed else None,
        "usage": obj.get("usage"),
        "session_id": obj.get("session_id"),
    }


def legacy_events(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """一行事件翻成老形状的事件（可能是零条、一条或几条）。

    老形状的行原样交出；Claude Code 形状的：

    - ``assistant`` 里的文字 → ``thinking``，工具调用 → ``tool``
    - ``user`` 里的工具结果 → ``result``（``denied`` 看结果开头的拒绝标记）
    - ``result`` → ``done`` 或 ``error``
    - ``system`` 行（开场、hook 动作）不对应老形状的任何事件，丢掉
    """
    kind = obj.get("type")
    if kind in ("assistant", "user"):
        message = obj.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return []
        out: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if kind == "assistant" and btype == "text":
                out.append({"type": "thinking", "text": block.get("text") or ""})
            elif kind == "assistant" and btype == "tool_use":
                out.append({
                    "type": "tool",
                    "tool_call_id": block.get("id"),
                    "tool_name": block.get("name"),
                    "input": block.get("input") or {},
                })
            elif kind == "user" and btype == "tool_result":
                output = _text_of(block.get("content"))
                out.append({
                    "type": "result",
                    "tool_call_id": block.get("tool_use_id"),
                    "output": output,
                    "denied": bool(block.get("is_error")) and output.startswith(_DENIAL_MARKS),
                })
        return out
    if _is_cc_result(obj):
        if obj.get("is_error"):
            return [{"type": "error", "message": str(obj.get("result") or ""), "rounds": obj.get("num_turns")}]
        return [{"type": "done", "final_text": str(obj.get("result") or ""), "rounds": obj.get("num_turns")}]
    if kind == "system":
        return []
    return [obj]


def _text_of(content: Any) -> str:
    """工具结果的正文：字符串原样；块列表把文字块拼起来。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else str(content)
