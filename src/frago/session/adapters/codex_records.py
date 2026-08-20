"""codex 会话记录 → 统一记录的翻译层。

数据源是 codex 的 rollout JSONL（见 :mod:`frago.session.codex_store`）。它是
append-only 的一行一条，所以 ``seq`` 直接取**文件物理行序**——与 Claude Code 那侧
同一个口径，NEVER 按时间戳排（并行工具调用落盘时调用与结果本来就会交错）。

## 同一句话在 rollout 里出现两遍，取哪一遍

codex 把一次对话同时记两份：``response_item`` 是发给模型的那份，``event_msg`` 是
给界面看的那份。两份内容并不等价，所以逐类挑，NEVER 两份都收（会话详情里每句话
都出现两次）也 NEVER 随手挑一份：

- **用户发言取 ``event_msg``**。``response_item`` 那份的正文里裹着 codex 自己拼进去
  的 ``<environment_context>``，收它会让每条用户消息都顶着一段环境说明，真正的提问
  被淹没。那一份改归「注入内容」，人想看仍然看得到。
- **agent 正文取 ``response_item``**。它是模型确实产出过的那条记录；``event_msg``
  的 ``agent_message`` 是界面回显，一轮里可能只在最终相位出现。取前者才不会因为
  某种流程里没有回显而把答案整段丢掉——丢掉的记录在界面上等于没发生过。
- **工具调用与结果只有 ``response_item`` 一种表示**，直接取。

## frago 自己的注入去哪了

frago 经钩子注入的上下文在 rollout 里是 ``role: developer`` 的消息。这里把它翻成
「注入内容」而不是丢掉：会话工作台的价值之一就是让人看见 agent 当时到底被喂了什么。
（归档备份那条路走的是 ``codex_store.record_payloads``，那边不收 developer 消息，
因为那条路服务的是"这场对话说了什么"。两条路目的不同，各取各的。）

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from frago.session import codex_store
from frago.session.unified_record import RecordKind, ToolFamily, UnifiedRecord

logger = logging.getLogger(__name__)

# codex 的工具名 → 渲染大类。工具名不是封闭集合（MCP 与用户自定义会往里加），
# 所以按大类分支、认不出的一律 ``other``，NEVER 穷举。
_TOOL_FAMILIES: dict[str, ToolFamily] = {
    "bash": "shell",
    "shell": "shell",
    "exec_command": "shell",
    "unified_exec": "shell",
    "write_stdin": "shell",
    "local_shell": "shell",
    "apply_patch": "file-write",
    "read_file": "file-read",
    "view_image": "file-read",
    "update_plan": "todo",
    "web_search": "web",
    "spawn_agent": "agent",
    "request_user_input": "ask",
}

# 纯记账类记录：codex 自己的状态快照与用量统计。它们不是任何人说的话，也不是
# 任何动作，翻进时间线只会把真正的内容挤走。这份名单是**明确列举**的，名单之外
# 认不出的类型仍旧归「未识别的注入内容」而不是静默丢弃。
_BOOKKEEPING_EVENTS = frozenset(
    {"token_count", "agent_message", "turn_diff", "stream_error", "notification"}
)
_BOOKKEEPING_TYPES = frozenset({"world_state", "turn_context", "compacted"})


def tool_family_of(tool_name: str) -> ToolFamily:
    """工具名 → 渲染大类。认不出的一律 ``other``，NEVER 因为没见过的工具名炸。"""
    name = (tool_name or "").strip().lower()
    if name.startswith("mcp__") or name.startswith("mcp."):
        return "mcp"
    return _TOOL_FAMILIES.get(name, "other")


@dataclass
class _Draft:
    """一条待编号的记录。``seq`` 在整场翻完之后统一按物理序补。"""

    id: str
    ts: int
    kind: RecordKind
    group_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    raw_available: bool = True
    line: int = 0
    """产出它的那一行在文件里的行号，取原文时按它回查。"""


def _ms(raw: Any) -> int:
    """ISO 时间戳 → 毫秒整数。解不出来时给 0，NEVER 抛。"""
    parsed = codex_store._parse_timestamp(raw)
    if parsed is None:
        return 0
    return int(parsed.timestamp() * 1000)


def _text_of(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [
        block.get("text")
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    return "".join(parts)


def _turn_id(payload: dict[str, Any], current: str | None) -> str | None:
    """这条记录属于哪一轮。记录自带的优先，否则沿用当前轮。"""
    passthrough = payload.get("internal_chat_message_metadata_passthrough")
    if isinstance(passthrough, dict):
        turn = passthrough.get("turn_id")
        if isinstance(turn, str) and turn:
            return turn
    turn = payload.get("turn_id")
    if isinstance(turn, str) and turn:
        return turn
    return current


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _drafts_for(
    record: dict[str, Any], line: int, current_turn: str | None
) -> tuple[list[_Draft], str | None]:
    """一条 rollout 记录 → 0~2 条待编号记录，以及翻完之后的当前轮次。"""
    outer = record.get("type")
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    inner = payload.get("type")
    ts = _ms(record.get("timestamp"))
    turn = _turn_id(payload, current_turn)
    rid = _str_or_none(payload.get("id")) or f"cx{line}"

    def draft(kind: RecordKind, body: dict[str, Any], **kw: Any) -> list[_Draft]:
        return [
            _Draft(
                id=kw.pop("rid", rid),
                ts=ts,
                kind=kind,
                group_id=kw.pop("group_id", turn),
                payload=body,
                line=line,
                **kw,
            )
        ]

    if outer == "session_meta":
        return (
            draft(
                "session.state",
                {
                    "field": "session",
                    "from": None,
                    "to": _str_or_none(payload.get("session_id")),
                    "source": "codex",
                    "event_type": "session_meta",
                    "cwd": _str_or_none(payload.get("cwd")),
                },
                group_id=None,
            ),
            turn,
        )

    if outer == "event_msg":
        if inner == "task_started":
            turn = _turn_id(payload, None) or current_turn
            return (
                draft(
                    "call.envelope",
                    {"phase": "start", "turn_id": turn, "source": "codex"},
                    rid=f"cx{line}",
                    group_id=turn,
                ),
                turn,
            )
        if inner == "task_complete":
            drafts = draft(
                "call.envelope",
                {
                    "phase": "finish",
                    "turn_id": turn,
                    "source": "codex",
                    "final_message": _str_or_none(payload.get("last_agent_message")),
                },
                rid=f"cx{line}",
            )
            error = payload.get("error")
            if error:
                message = (
                    error.get("message")
                    if isinstance(error, dict)
                    else str(error)
                )
                drafts.append(
                    _Draft(
                        # 同一行拆两条记录，编号必须分开，否则按编号去重会吃掉一条。
                        id=f"cx{line}:error",
                        ts=ts,
                        kind="error",
                        group_id=turn,
                        # 报错只留三个字段，原文入口恒不可用。
                        payload={
                            "scope": "api",
                            "code": "task_complete",
                            "message": message
                            if isinstance(message, str)
                            else json.dumps(error, ensure_ascii=False),
                        },
                        raw_available=False,
                        line=line,
                    )
                )
            return drafts, turn
        if inner == "user_message":
            text = payload.get("message")
            if not isinstance(text, str) or not text.strip():
                return [], turn
            return (
                draft(
                    "user.say",
                    {
                        "text": text,
                        # codex 不记输入来源。留空，NEVER 默认成「人手打的」——那会把
                        # 机器发起的当成人发起的，是错误信息而不是信息缺失。
                        "input_mode": None,
                        "agent": None,
                    },
                    rid=f"cx{line}",
                    # 用户输入类不设分组键。
                    group_id=None,
                ),
                turn,
            )
        if inner == "error":
            return (
                [
                    _Draft(
                        id=f"cx{line}",
                        ts=ts,
                        kind="error",
                        group_id=turn,
                        payload={
                            "scope": "engine",
                            "code": "event_error",
                            "message": str(payload.get("message") or ""),
                        },
                        raw_available=False,
                        line=line,
                    )
                ],
                turn,
            )
        if inner in _BOOKKEEPING_EVENTS:
            return [], turn
        return _unrecognized(record, payload, line, ts, turn), turn

    if outer in _BOOKKEEPING_TYPES:
        return [], turn

    if outer != "response_item":
        return _unrecognized(record, payload, line, ts, turn), turn

    if inner == "message":
        role = payload.get("role")
        text = _text_of(payload)
        if role == "assistant":
            if not text.strip():
                return [], turn
            return draft("agent.say", {"text": text, "model": None, "provider": None}), turn
        if role == "developer":
            return (
                draft(
                    "context.inject",
                    {
                        "channel": "developer",
                        "label": "developer 消息（含 frago 钩子注入）",
                        "body": text,
                        "source": "codex",
                        "unrecognized": False,
                    },
                ),
                turn,
            )
        # role == "user"：模型侧那份，裹着 environment_context。归注入内容。
        return (
            draft(
                "context.inject",
                {
                    "channel": "environment",
                    "label": "发给模型的用户消息（含环境说明）",
                    "body": text,
                    "source": "codex",
                    "unrecognized": False,
                },
            ),
            turn,
        )

    if inner == "reasoning":
        content = payload.get("content")
        parts = [
            block.get("text")
            for block in (content if isinstance(content, list) else [])
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        text = "".join(parts)
        if not text.strip():
            return [], turn
        return draft("agent.think", {"text": text, "model": None, "provider": None}), turn

    if inner == "function_call":
        name = str(payload.get("name") or "")
        call_id = _str_or_none(payload.get("call_id")) or rid
        return (
            draft(
                "tool.call",
                {
                    "call_id": call_id,
                    "tool_name": name,
                    "tool_family": tool_family_of(name),
                    "args": codex_store._decode_arguments(payload.get("arguments")),
                    "title": None,
                },
            ),
            turn,
        )

    if inner == "function_call_output":
        call_id = _str_or_none(payload.get("call_id")) or rid
        output = payload.get("output")
        return (
            draft(
                "tool.result",
                {
                    "call_id": call_id,
                    "tool_name": None,
                    "tool_family": "other",
                    "status": "error" if payload.get("success") is False else "ok",
                    "body": output if isinstance(output, str) else "",
                    "truncation": "none",
                    "truncation_ref": None,
                },
            ),
            turn,
        )

    return _unrecognized(record, payload, line, ts, turn), turn


def _unrecognized(
    record: dict[str, Any],
    payload: dict[str, Any],
    line: int,
    ts: int,
    turn: str | None,
) -> list[_Draft]:
    """认不出的记录类型：归注入内容并标记未识别。

    NEVER 静默丢弃——丢掉的记录在界面上等于没发生过，人会以为这段时间什么都没发生。
    """
    return [
        _Draft(
            id=f"cx{line}",
            ts=ts,
            kind="context.inject",
            group_id=turn,
            payload={
                "channel": "unknown",
                "label": str(record.get("type") or ""),
                "body": "",
                "record_type": record.get("type"),
                "payload_type": payload.get("type"),
                "payload_keys": sorted(str(k) for k in payload),
                "unrecognized": True,
            },
            line=line,
        )
    ]


def _raw_lines(session_id: str) -> list[str]:
    """整场会话的原始行。定位不到 / 读不动时空列表，NEVER 抛。"""
    path = codex_store.find_rollout(session_id)
    if path is None:
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.debug("codex rollout read failed for %s: %s", session_id, exc)
        return []


def translate_session(session_id: str) -> list[UnifiedRecord]:
    """整场会话翻成统一记录，``seq`` 按物理行序从 0 递增。"""
    drafts: list[_Draft] = []
    turn: str | None = None
    for line, raw in enumerate(_raw_lines(session_id)):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        produced, turn = _drafts_for(record, line, turn)
        drafts.extend(produced)
    return [
        UnifiedRecord(
            id=draft.id,
            session_id=session_id,
            group_id=draft.group_id,
            seq=index,
            ts=draft.ts,
            kind=draft.kind,
            agent_path=[],
            payload=draft.payload,
            raw_available=draft.raw_available,
        )
        for index, draft in enumerate(drafts)
    ]


class CodexRecordAdapter:
    """codex 那一家的记录翻译层（``adapters`` 注册表按家族取它）。"""

    def to_unified(
        self, session_id: str, after: int, limit: int, tail: bool = False
    ) -> list[UnifiedRecord]:
        records = translate_session(session_id)
        if tail:
            return records[-limit:] if limit < len(records) else records
        start = max(after, 0)
        return records[start : start + limit]

    def read_raw(self, session_id: str, record_id: str) -> dict[str, Any] | None:
        """取单条记录的原文。取不到返回 None，NEVER 抛。

        报错类记录恒不给原文（``raw_available`` 为 False，服务层也会再拦一道）。
        """
        lines = _raw_lines(session_id)
        turn: str | None = None
        for line, raw in enumerate(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            produced, turn = _drafts_for(record, line, turn)
            for draft in produced:
                if draft.id != record_id:
                    continue
                if not draft.raw_available:
                    return None
                return record
        return None
