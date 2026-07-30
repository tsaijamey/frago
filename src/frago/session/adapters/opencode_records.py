"""opencode 片段 → 统一记录的翻译层（spec 20260729-session-workbench-webui Phase 1c）。

opencode 把一场会话摊成三层：会话 → 消息 → 片段。界面要的是一层——一条记录一张卡。
这个模块负责那一次摊平，规则全部来自本机 33 场会话 / 559 条消息 / 1947 个片段的全量
实测（``~/.frago/data/20260728-agent-session-workbench/``），不是从文档推的。

四条不能松的口子：

1. **调用与结果拆成两条。** opencode 把工具的参数与返回放在同一条片段的 ``state.input``
   与 ``state.output`` 里，Claude Code 那边天生是两条记录。统一后恒为两条，共用同一个
   ``call_id``，界面才能两家一套渲染。
2. **带报错标记的用户中断不归报错。** 消息信封上带 ``error`` 的 12 条里 11 条的 name 是
   ``MessageAbortedError``——那是人按了停止，不是崩了。照「信封有 error 就归 error」执行，
   界面上这些会话会看起来像老崩。按 name 分流，中断归 ``interrupt``。
3. **待办要带来源标记。** opencode 的 19 条待办全是 agent 主动写入（``todowrite`` 工具），
   与 Claude Code 那边引擎被动重发的 5026 条不是一回事。``payload["source"]`` 写死
   ``"agent-write"``，界面据此决定折不折叠。
4. **无法归类的片段归注入内容并标记未识别，NEVER 静默丢弃。** 丢掉的记录在界面上等于
   没发生过，比归错类更坏。

时间：opencode 存的是毫秒整数，``ts`` 直接照抄，本模块不产生任何 ``datetime``，因此也
不存在时区问题。NEVER 出现 ``datetime.now(timezone.utc)`` / ``utcnow()`` / ``Z`` 后缀。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。读库一律复用
:mod:`frago.session.opencode_store`——只读打开（``mode=ro``）的保证只此一份，NEVER 在
这里另起一套连接逻辑。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from frago.session import opencode_store
from frago.session.unified_record import RecordKind, ToolFamily, UnifiedRecord

logger = logging.getLogger(__name__)

__all__ = [
    "OpencodeRecordAdapter",
    "read_raw",
    "to_unified",
]

# ── 片段类型 ────────────────────────────────────────────────────────
_PART_TEXT = "text"
_PART_REASONING = "reasoning"
_PART_TOOL = "tool"
_PART_FILE = "file"
_PART_PATCH = "patch"
_PART_STEP_START = "step-start"
_PART_STEP_FINISH = "step-finish"

_STEP_PART_TYPES = frozenset({_PART_STEP_START, _PART_STEP_FINISH})

# ── 工具名 → 渲染大类 ──────────────────────────────────────────────
# 按大类分支，不按工具名穷举：工具名不是封闭集合，随用户配置变化。本机实测出现过
# bash / read / edit / glob / todowrite / write / grep / webfetch / task / websearch /
# question 十一种，落表之外的一律走 ``other``，MCP 工具按名字前缀单独收口。
_TOOL_FAMILIES: dict[str, ToolFamily] = {
    "bash": "shell",
    "shell": "shell",
    "read": "file-read",
    "list": "file-read",
    "edit": "file-write",
    "write": "file-write",
    "patch": "file-write",
    "multiedit": "file-write",
    "glob": "search",
    "grep": "search",
    "webfetch": "web",
    "websearch": "web",
    "task": "agent",
    "todowrite": "todo",
    "todoread": "todo",
    "question": "ask",
}

# 拆走不走 ``tool.call`` + ``tool.result`` 的两个工具。抽取规则与 Claude Code 侧对齐：
# 派发子 agent 归 ``subagent.dispatch``、写待办归 ``todo.snapshot``，各自一条记录，
# 调用与结果合并在同一张卡上（结果就是那次派发/写入的产物，不是独立事件）。
_TOOL_SUBAGENT = "task"
_TOOL_TODO = "todowrite"

# 用户拒绝某次调用时 opencode 留下的唯一痕迹：工具片段的 ``state.error`` 文本。
# ``permission`` 表本机 0 行，权限弹窗的过程不落盘，只能从这句话反推。
_DENIED_MARKER = "rejected permission"

# 消息信封上表示「人按了停止」的报错名。见模块文档第 2 条。
_ABORTED_ERROR_NAME = "MessageAbortedError"

# 报错原文里必须剥掉的字段：APIError 的响应头带 Cloudflare 的 ``set-cookie`` 令牌，
# 响应体可能带同源信息。取原文这条路对 ``error`` 类本来就是关的，这里是第二道闸。
_SENSITIVE_ERROR_FIELDS = ("responseHeaders", "responseBody")


@dataclass
class _Draft:
    """一条还没定序号的记录。``seq`` 在整场会话翻完之后统一按物理序编。"""

    id: str
    ts: int
    kind: RecordKind
    group_id: str | None
    payload: dict[str, Any]
    raw_available: bool = True


@dataclass(frozen=True)
class _Envelope:
    """一条消息的信封。正文在片段里，这里只有身份、时刻与报错。"""

    message_id: str
    role: str
    time_created: int
    time_completed: int | None
    error: dict[str, Any] | None
    model_id: str | None
    provider_id: str | None
    agent: str | None
    synthetic: bool = False
    """库里没有这条消息、只有挂在它下面的片段时为真（孤儿片段的兜底信封）。"""


# ── 读库 ────────────────────────────────────────────────────────────
def _as_dict(raw: Any) -> dict[str, Any]:
    """把 ``data`` 列的 JSON 文本解析成字典；损坏时当空字典，NEVER 抛。"""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    """字典就照用，别的一律当空字典。库里同名字段两种类型并存（``diagnostics`` 在一处是
    对象、在另一处是字符串），取值一律走这里，NEVER 直接 ``value["k"]``。"""
    return value if isinstance(value, dict) else {}


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _read_envelopes(session_id: str) -> list[_Envelope]:
    """这场会话的全部消息信封，按 ``(time_created, id)`` 升序。

    ``opencode_store`` 没有暴露「只要信封」的读法（它的 ``latest_turn`` 只回最新一轮），
    所以这一条查询写在这里，连接仍然走 ``opencode_store`` 的只读打开。正文一个字都不取，
    避开 ``summary.diffs`` 那几条 22 万字符的用户消息。
    """
    conn = opencode_store._connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, time_created, "
            "json_extract(data, '$.role')       AS role, "
            "json_extract(data, '$.time.completed') AS completed, "
            "json_extract(data, '$.error')      AS error, "
            "json_extract(data, '$.modelID')    AS model_id, "
            "json_extract(data, '$.providerID') AS provider_id, "
            "json_extract(data, '$.agent')      AS agent "
            "FROM message WHERE session_id = ? ORDER BY time_created ASC, id ASC",
            (session_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("opencode _read_envelopes failed: %s", exc)
        return []
    finally:
        conn.close()

    envelopes: list[_Envelope] = []
    for mid, created, role, completed, error, model_id, provider_id, agent in rows:
        envelopes.append(
            _Envelope(
                message_id=str(mid),
                role=role if isinstance(role, str) else "assistant",
                time_created=created if isinstance(created, int) else 0,
                time_completed=_int_or_none(completed),
                error=_as_dict(error) or None,
                model_id=_str_or_none(model_id),
                provider_id=_str_or_none(provider_id),
                agent=_str_or_none(agent),
            )
        )
    return envelopes


def _read_session_events(session_id: str) -> list[tuple[str, str, int, dict[str, Any]]]:
    """会话级系统事件（切 agent / 切模型），按 ``(time_created, seq)`` 升序。

    这些行不在 ``message`` 表里，要与消息时间线归并渲染，两张表的 ``seq`` 不共享。
    """
    conn = opencode_store._connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, type, time_created, data FROM session_message "
            "WHERE session_id = ? ORDER BY time_created ASC, seq ASC",
            (session_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        # 早期版本没有这张表，取不到就当这场会话没切过 agent / 模型。
        logger.debug("opencode _read_session_events failed: %s", exc)
        return []
    finally:
        conn.close()

    events: list[tuple[str, str, int, dict[str, Any]]] = []
    for rid, rtype, created, raw in rows:
        events.append(
            (
                str(rid),
                rtype if isinstance(rtype, str) else "",
                created if isinstance(created, int) else 0,
                _as_dict(raw),
            )
        )
    return events


# ── 工具片段 ────────────────────────────────────────────────────────
def tool_family_of(tool_name: str) -> ToolFamily:
    """工具名 → 渲染大类。认不出的一律 ``other``，NEVER 因为没见过的工具名炸。"""
    name = (tool_name or "").strip().lower()
    if name.startswith("mcp__") or name.startswith("mcp."):
        return "mcp"
    return _TOOL_FAMILIES.get(name, "other")


def _tool_status(state: dict[str, Any]) -> str:
    """工具结果的状态。顺序不能换：先看拒绝，再看中断，最后才是普通失败。"""
    error_text = state.get("error")
    error_text = error_text if isinstance(error_text, str) else ""
    metadata = state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if _DENIED_MARKER in error_text:
        return "denied"
    if metadata.get("interrupted") is True:
        return "interrupted"
    if state.get("status") == "error":
        return "error"
    return "ok"


def _tool_truncation(state: dict[str, Any]) -> tuple[str, str | None]:
    """工具结果的截断状态与全文位置。

    **``outputPath`` 必须先查。** 溢出转存与截断标记是两套机制：本机唯一那条溢出记录，
    ``state.output`` 只剩「提示 + 尾段」，全文在 ``tool-output/`` 下的独立文件里，而
    ``truncated`` 标志在不同版本上写 true 也写过 false。只看标志一定误判。
    """
    metadata = state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    output_path = _str_or_none(metadata.get("outputPath"))
    if output_path:
        return "offloaded", output_path
    if metadata.get("truncated") is True:
        return "clipped", None
    return "none", None


def _tool_duration_ms(state: dict[str, Any]) -> int | None:
    """这次工具执行花了多久。两端时刻缺一就不给，NEVER 用 0 冒充「很快」。"""
    time_info = state.get("time")
    time_info = time_info if isinstance(time_info, dict) else {}
    start = _int_or_none(time_info.get("start"))
    end = _int_or_none(time_info.get("end"))
    if start is None or end is None:
        return None
    return end - start


def _tool_body(state: dict[str, Any], status: str) -> str:
    """结果正文。失败时 ``output`` 不存在，正文取 ``error`` 那句话。"""
    output = state.get("output")
    if isinstance(output, str) and output:
        return output
    if status != "ok":
        error_text = state.get("error")
        if isinstance(error_text, str):
            return error_text
    return output if isinstance(output, str) else ""


def _todo_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    """待办清单正文。三处重复（input / metadata / output），按可靠性依次取一份。

    ``output`` 是同一份数组的 JSON **字符串**形式，要二次 parse。``priority`` 列实测出
    现过 ``pending`` 这样的脏值，这里一个字不改地照搬，判枚举是界面的事。
    """
    for source in (state.get("input"), state.get("metadata")):
        if isinstance(source, dict):
            todos = source.get("todos")
            if isinstance(todos, list):
                return [item for item in todos if isinstance(item, dict)]
    output = state.get("output")
    if isinstance(output, str) and output.strip():
        try:
            parsed = json.loads(output)
        except (ValueError, TypeError):
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _tool_drafts(part: dict[str, Any], part_id: str, ts: int, group_id: str) -> list[_Draft]:
    """一个工具片段 → 一到三条记录。

    - 派发子 agent（``task``）→ 一条 ``subagent.dispatch``
    - 写待办（``todowrite``）→ 一条 ``todo.snapshot``，带 ``source="agent-write"``
    - 其余 → ``tool.call`` + ``tool.result`` 两条，共用同一个 ``call_id``；用户拒绝过的
      再多一条 ``permission.outcome``
    """
    state = _dict_or_empty(part.get("state"))
    metadata = _dict_or_empty(state.get("metadata"))
    tool_name = _str_or_empty(part.get("tool"))
    # callID 形态由供应商决定（``call_00_x`` / ``bash_19`` / ``chatcmpl-tool-x`` 都见过），
    # NEVER 试图从它解析工具名。缺失时退回片段编号，配对照样成立。
    call_id = _str_or_none(part.get("callID")) or part_id
    args = _dict_or_empty(state.get("input"))
    # 空标题与没有标题是两回事：glob 的标题实测是空串，出错的那几条根本没有这个字段。
    raw_title = state.get("title")
    title: str | None = raw_title if isinstance(raw_title, str) else None
    status = _tool_status(state)
    truncation, truncation_ref = _tool_truncation(state)

    if tool_name == _TOOL_SUBAGENT:
        return [
            _Draft(
                id=part_id,
                ts=ts,
                kind="subagent.dispatch",
                group_id=group_id,
                payload={
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "agent_type": args.get("subagent_type"),
                    "description": args.get("description"),
                    "prompt": args.get("prompt"),
                    "child_session_id": _str_or_none(metadata.get("sessionId")),
                    "parent_session_id": _str_or_none(metadata.get("parentSessionId")),
                    "status": status,
                    "body": _tool_body(state, status),
                    "truncation": truncation,
                    "truncation_ref": truncation_ref,
                    "duration_ms": _tool_duration_ms(state),
                    "trace_available": bool(_str_or_none(metadata.get("sessionId"))),
                    "title": title,
                },
            )
        ]

    if tool_name == _TOOL_TODO:
        items = _todo_items(state)
        return [
            _Draft(
                id=part_id,
                ts=ts,
                kind="todo.snapshot",
                group_id=group_id,
                payload={
                    "call_id": call_id,
                    "tool_name": tool_name,
                    # 来源标记：opencode 的待办全是 agent 主动写入，与 Claude Code 那边
                    # 引擎被动重发的清单不是一回事。界面按这个字段决定折不折叠。
                    "source": "agent-write",
                    "items": items,
                    "item_count": len(items),
                    "status": status,
                    "title": title,
                },
            )
        ]

    drafts = [
        _Draft(
            id=part_id,
            ts=ts,
            kind="tool.call",
            group_id=group_id,
            payload={
                "call_id": call_id,
                "tool_name": tool_name,
                "tool_family": tool_family_of(tool_name),
                "args": args,
                "title": title,
            },
        ),
        _Draft(
            # 同一条片段拆两条记录，编号必须分开，否则按编号去重会吃掉一条。
            id=f"{part_id}:result",
            ts=ts,
            kind="tool.result",
            group_id=group_id,
            payload={
                "call_id": call_id,
                "tool_name": tool_name,
                "tool_family": tool_family_of(tool_name),
                "status": status,
                "body": _tool_body(state, status),
                "body_kind": "text",
                "truncation": truncation,
                "truncation_ref": truncation_ref,
                "duration_ms": _tool_duration_ms(state),
                "exit_code": _int_or_none(metadata.get("exit")),
                # 命令的原始输出。bash 上它与 ``output`` 有 23 条不等——差的就是被前置
                # 注入进去喂给模型的那一段。界面要展示「命令实际输出了什么」取这个。
                "raw_output": metadata.get("output")
                if isinstance(metadata.get("output"), str)
                else None,
            },
        ),
    ]
    if status == "denied":
        drafts.append(
            _Draft(
                id=f"{part_id}:permission",
                ts=ts,
                kind="permission.outcome",
                group_id=group_id,
                payload={
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "decision": "denied",
                    "reason": state.get("error") if isinstance(state.get("error"), str) else "",
                    "mode": None,
                    "source": "tool-error-text",
                },
            )
        )
    return drafts


# ── 片段 → 记录 ────────────────────────────────────────────────────
def _part_drafts(
    item: dict[str, Any], envelope: _Envelope, step_counts: tuple[int, int]
) -> list[_Draft]:
    """一个片段 → 零到三条记录。零条只可能因为片段本身解析不出类型，那时也不丢弃。"""
    part = item["part"]
    part_id = str(item["part_id"])
    ts = int(item["time_created"])
    group_id = envelope.message_id
    part_type = part.get("type")

    if part_type == _PART_TEXT:
        text = part.get("text")
        text = text if isinstance(text, str) else ""
        if part.get("synthetic"):
            # 注入的编辑器上下文：挂在用户消息下，但不是用户打的字。
            metadata = part.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            return [
                _Draft(
                    id=part_id,
                    ts=ts,
                    kind="context.inject",
                    group_id=group_id,
                    payload={
                        "channel": "editor-context",
                        "label": _str_or_none(metadata.get("kind")) or "editor_context",
                        "body": text,
                        "source": _str_or_none(metadata.get("source")),
                        "file_path": _str_or_none(metadata.get("filePath")),
                        "unrecognized": False,
                    },
                )
            ]
        if envelope.role == "user":
            return [
                _Draft(
                    id=part_id,
                    ts=ts,
                    # 用户输入类不设分组键。
                    group_id=None,
                    kind="user.say",
                    payload={
                        "text": text,
                        # opencode 不落输入来源，缺失就留空。NEVER 默认成「人手打的」——
                        # 那会把机器发起的当成人发起的，是错误信息而不是信息缺失。
                        "input_mode": None,
                        "agent": envelope.agent,
                    },
                )
            ]
        return [
            _Draft(
                id=part_id,
                ts=ts,
                kind="agent.say",
                group_id=group_id,
                payload={
                    "text": text,
                    "model": envelope.model_id,
                    "provider": envelope.provider_id,
                },
            )
        ]

    if part_type == _PART_REASONING:
        text = part.get("text")
        return [
            _Draft(
                id=part_id,
                ts=ts,
                kind="agent.think",
                group_id=group_id,
                payload={
                    "text": text if isinstance(text, str) else "",
                    "model": envelope.model_id,
                    "provider": envelope.provider_id,
                },
            )
        ]

    if part_type == _PART_TOOL:
        return _tool_drafts(part, part_id, ts, group_id)

    if part_type == _PART_FILE:
        source = part.get("source")
        source = source if isinstance(source, dict) else {}
        url = part.get("url")
        return [
            _Draft(
                id=part_id,
                ts=ts,
                kind="media.attach",
                group_id=group_id,
                payload={
                    "media_type": _str_or_none(part.get("mime")),
                    "display_name": _str_or_none(part.get("filename")),
                    # 正文是 ``data:`` 协议的整段 base64，单条见过 1.9 MB。这里只留长度与
                    # 磁盘位置，NEVER 把 base64 塞进 payload——一次列表查询就能打死浏览器。
                    "ref": _str_or_none(source.get("path")),
                    "bytes": len(url) if isinstance(url, str) else None,
                    "inline": isinstance(url, str) and url.startswith("data:"),
                },
            )
        ]

    if part_type == _PART_PATCH:
        files = part.get("files")
        return [
            _Draft(
                id=part_id,
                ts=ts,
                kind="context.inject",
                group_id=group_id,
                payload={
                    "channel": "diff",
                    "label": "文件改动汇总",
                    "files": files if isinstance(files, list) else [],
                    "hash": _str_or_none(part.get("hash")),
                    "unrecognized": False,
                },
            )
        ]

    if part_type in _STEP_PART_TYPES:
        return [_step_draft(part, part_id, ts, group_id, step_counts)]

    # 认不出的片段类型：归注入内容并标记未识别。NEVER 静默丢弃——丢掉的记录在界面上等于
    # 没发生过，人会以为这段时间什么都没发生。
    return [
        _Draft(
            id=part_id,
            ts=ts,
            kind="context.inject",
            group_id=group_id,
            payload={
                "channel": "unknown",
                "label": str(part_type) if part_type is not None else "",
                "body": "",
                "part_type": part_type,
                "part_keys": sorted(str(k) for k in part),
                "unrecognized": True,
            },
        )
    ]


def _step_draft(
    part: dict[str, Any], part_id: str, ts: int, group_id: str, step_counts: tuple[int, int]
) -> _Draft:
    """步骤边界 → 一条调用信封。

    这一格是实现期补的第十五种形态。步骤开始与结束标的正是「模型被调了一次」的两端，
    早先没有归处、按兜底塞进注入内容，本机 936 条占了那一格的 38%，把真正被注入的东西
    淹掉。调研当初建议的 ``turn.marker`` 不是同一件事——那个说的是「人问了一次」，与这
    里的调用边界同名异物，合不到一起，所以另开一格而不是复用。载荷一个字段没删。

    配对只在单条消息内做，不跨消息。opencode 的步骤开始与结束差 8 条，全是用户中断且全
    部缺尾不缺头；跨消息栈式配对会让被中断那条的开始与下一条的结束配上，从此每个回合都
    偏一位。``step_counts`` 是所属消息内的 (开始数, 结束数)，单边缺失照常渲染。
    """
    starts, finishes = step_counts
    phase = "start" if part.get("type") == _PART_STEP_START else "finish"
    payload: dict[str, Any] = {
        "channel": "step-marker",
        "label": phase,
        "phase": phase,
        "snapshot": _str_or_none(part.get("snapshot")),
        "step_start_count": starts,
        "step_finish_count": finishes,
        "paired": starts == finishes,
        # 有归处了，但字段不删——上层已经在按它挑「翻译层没认出来的东西」。
        "unrecognized": False,
    }
    if phase == "finish":
        payload["finish_reason"] = _str_or_none(part.get("reason"))
        payload["tokens"] = part.get("tokens") if isinstance(part.get("tokens"), dict) else None
        payload["cost"] = part.get("cost")
    return _Draft(id=part_id, ts=ts, kind="call.envelope", group_id=group_id, payload=payload)


# ── 消息信封上的报错 ────────────────────────────────────────────────
def _interrupt_phase(parts: list[dict[str, Any]]) -> str:
    """人在哪一步按的停止。从最后一个内容片段反推，推不出就照实写「未知」。

    步骤边界与文件改动汇总不算内容，跳过。中断消息里有三条一个片段都没有——模型还没吐出
    任何东西就被叫停，只剩一个空信封，那时只能是未知。
    """
    for item in reversed(parts):
        part_type = item["part"].get("type")
        if part_type in _STEP_PART_TYPES or part_type == _PART_PATCH:
            continue
        if part_type == _PART_TOOL:
            return "tool-executing"
        if part_type in (_PART_TEXT, _PART_REASONING):
            return "generating"
        return "unknown"
    return "unknown"


def _envelope_error_draft(envelope: _Envelope, parts: list[dict[str, Any]]) -> _Draft | None:
    """消息信封上的报错 → 一条中断或一条报错。没有报错就没有这条记录。

    **分流规则是这个模块最要紧的一条。** 本机 12 条带 error 的消息里，11 条的 name 是
    ``MessageAbortedError``——人按了停止。照「有 error 就归 error」执行，界面上会显示
    11 次崩溃，看的人会以为这个 agent 老出事，实际是他自己喊的停。
    """
    error = envelope.error
    if not error:
        return None
    name = _str_or_none(error.get("name")) or "UnknownError"
    data = error.get("data")
    data = data if isinstance(data, dict) else {}
    message = data.get("message")
    message = message if isinstance(message, str) else ""
    ts = envelope.time_completed if envelope.time_completed is not None else envelope.time_created

    if name == _ABORTED_ERROR_NAME:
        return _Draft(
            id=f"{envelope.message_id}:interrupt",
            ts=ts,
            kind="interrupt",
            group_id=envelope.message_id,
            payload={
                "target": envelope.message_id,
                "phase": _interrupt_phase(parts),
                "reason": message,
                "source": "message-error",
            },
        )

    status_code = _int_or_none(data.get("statusCode"))
    return _Draft(
        id=f"{envelope.message_id}:error",
        ts=ts,
        kind="error",
        group_id=envelope.message_id,
        # 报错只留三个字段：scope / code / message。响应头里带 Cloudflare 的登录凭据，
        # 连原文入口都不给挂——``raw_available`` 恒为 False，取原文一律拒。
        payload={
            "scope": "api" if name == "APIError" else "engine",
            "code": f"{name}:{status_code}" if status_code is not None else name,
            "message": message,
        },
        raw_available=False,
    )


# ── 会话级系统事件 ──────────────────────────────────────────────────
def _event_draft(row: tuple[str, str, int, dict[str, Any]]) -> _Draft:
    """切 agent / 切模型 → 一条会话状态变更。"""
    row_id, row_type, ts, data = row
    if row_type == "agent-switched":
        field_name: str = "agent"
        target: Any = _str_or_none(data.get("agent"))
    elif row_type == "model-switched":
        field_name = "model"
        model = data.get("model")
        model = model if isinstance(model, dict) else {}
        target = _str_or_none(model.get("id"))
    else:
        field_name = row_type or "unknown"
        target = None
    return _Draft(
        id=row_id,
        ts=ts,
        kind="session.state",
        group_id=None,
        payload={
            "field": field_name,
            # opencode 只记切成了什么，不记切之前是什么。留空，NEVER 拿上一条猜。
            "from": None,
            "to": target,
            "source": "opencode",
            "event_type": row_type,
        },
    )


# ── 整场会话 ────────────────────────────────────────────────────────
def _step_counts(parts: list[dict[str, Any]]) -> tuple[int, int]:
    """这条消息里的 (步骤开始数, 步骤结束数)。配对只在这个范围内做。"""
    starts = sum(1 for item in parts if item["part"].get("type") == _PART_STEP_START)
    finishes = sum(1 for item in parts if item["part"].get("type") == _PART_STEP_FINISH)
    return starts, finishes


def translate_session(session_id: str) -> list[UnifiedRecord]:
    """把整场会话翻成统一记录，按物理序编号，从 0 递增。

    顺序取会话内的片段物理序（``time_created``, ``id``），NEVER 按记录时刻重排——
    这一条与 Claude Code 那边取文件行序是同一个道理：时刻只用于显示。

    一条消息一个片段都没有（本机 4 条，全是被中断或出错的助手消息）照常处理，不当作损坏：
    它的信封里还有报错可渲染。
    """
    envelopes = _read_envelopes(session_id)
    parts_by_message: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in opencode_store.session_parts(session_id):
        parts_by_message[str(item["message_id"])].append(item)

    known = {envelope.message_id for envelope in envelopes}
    # 片段挂着一条查不到的消息：给它补一个兜底信封，NEVER 让这些片段悄悄消失。
    for message_id, items in parts_by_message.items():
        if message_id in known:
            continue
        logger.debug("opencode 片段挂在未知消息上，已补兜底信封: %s", message_id)
        envelopes.append(
            _Envelope(
                message_id=message_id,
                role="assistant",
                time_created=int(items[0]["time_created"]),
                time_completed=None,
                error=None,
                model_id=None,
                provider_id=None,
                agent=None,
                synthetic=True,
            )
        )
    envelopes.sort(key=lambda envelope: (envelope.time_created, envelope.message_id))

    # 会话事件与消息按时刻归并。同刻时事件在前——切 agent / 切模型发生在那条发言之前。
    blocks: list[tuple[int, int, Any]] = [
        (row[2], 0, row) for row in _read_session_events(session_id)
    ]
    blocks += [(envelope.time_created, 1, envelope) for envelope in envelopes]
    blocks.sort(key=lambda block: (block[0], block[1]))

    drafts: list[_Draft] = []
    for _ts, marker, payload in blocks:
        if marker == 0:
            drafts.append(_event_draft(payload))
            continue
        envelope: _Envelope = payload
        parts = parts_by_message.get(envelope.message_id, [])
        counts = _step_counts(parts)
        for item in parts:
            drafts.extend(_part_drafts(item, envelope, counts))
        error_draft = _envelope_error_draft(envelope, parts)
        if error_draft is not None:
            drafts.append(error_draft)

    return [
        UnifiedRecord(
            id=draft.id,
            session_id=session_id,
            group_id=draft.group_id,
            seq=index,
            ts=draft.ts,
            kind=draft.kind,
            # opencode 的子 agent 是一等公民会话（``session.parent_id`` 非空），不混在父
            # 会话的记录流里。轨迹关系由 ``subagent.dispatch`` 的 ``child_session_id`` 指出。
            agent_path=[],
            payload=draft.payload,
            raw_available=draft.raw_available,
        )
        for index, draft in enumerate(drafts)
    ]


def to_unified(
    session_id: str, after: int = 0, limit: int | None = None, tail: bool = False
) -> list[UnifiedRecord]:
    """这场会话从第 ``after`` 条起的记录，最多 ``limit`` 条。

    ``after`` 是**序号本身、含首条**：``after=0`` 拿到的第一条 ``seq`` 就是 0。用序号而不
    用绝对下标，是因为会话被重新解析后下标会错位；界面拿着过期的序号重拉即可。
    ``limit`` 给 None 或非正数表示不限。

    ``tail=True`` 时忽略 ``after``，取整场最后 ``limit`` 条——中栏打开会话要直接落在
    最新内容上。
    """
    records = translate_session(session_id)
    if tail:
        if limit is None or limit <= 0:
            return records
        return records[-limit:]
    start = max(after, 0)
    if limit is None or limit <= 0:
        return records[start:]
    return records[start : start + limit]


# ── 取单条原文 ──────────────────────────────────────────────────────
def _scrub(data: dict[str, Any]) -> dict[str, Any]:
    """剥掉报错原文里的凭据字段。第二道闸，第一道是 ``error`` 类根本不给原文入口。"""
    error = data.get("error")
    if not isinstance(error, dict):
        return data
    inner = error.get("data")
    if not isinstance(inner, dict):
        return data
    if not any(key in inner for key in _SENSITIVE_ERROR_FIELDS):
        return data
    cleaned = dict(data)
    cleaned_error = dict(error)
    cleaned_inner = {k: v for k, v in inner.items() if k not in _SENSITIVE_ERROR_FIELDS}
    cleaned_error["data"] = cleaned_inner
    cleaned["error"] = cleaned_error
    return cleaned


def read_raw(session_id: str, record_id: str) -> dict[str, Any] | None:
    """取单条记录的原文。取不到返回 None，NEVER 抛。

    报错类记录恒返回 None：那条原文里带着 Cloudflare 的登录凭据，连入口都不给挂。
    """
    head, _, suffix = record_id.partition(":")
    if suffix == "error":
        return None

    for item in opencode_store.session_parts(session_id):
        if str(item["part_id"]) != head:
            continue
        return {
            "source": "part",
            "part_id": str(item["part_id"]),
            "message_id": str(item["message_id"]),
            "time_created": item["time_created"],
            "time_updated": item["time_updated"],
            "role": item["role"],
            "data": item["part"],
        }

    conn = opencode_store._connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT id, time_created, data FROM message WHERE id = ? AND session_id = ?",
            (head, session_id),
        ).fetchone()
        if row is not None:
            return {
                "source": "message",
                "message_id": str(row[0]),
                "time_created": row[1],
                "data": _scrub(_as_dict(row[2])),
            }
        row = conn.execute(
            "SELECT id, type, time_created, data FROM session_message "
            "WHERE id = ? AND session_id = ?",
            (head, session_id),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("opencode read_raw failed: %s", exc)
        return None
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "source": "session_message",
        "event_id": str(row[0]),
        "event_type": row[1],
        "time_created": row[2],
        "data": _as_dict(row[3]),
    }


# ── 注册表要的那个形状 ──────────────────────────────────────────────
class OpencodeRecordAdapter:
    """opencode 那一家的翻译层。形状按 ``adapters.RecordAdapter`` 协议。

    登记动作留给统一入口（Phase 1d）做，这个模块只提供实现。
    """

    family = "opencode"

    def to_unified(
        self, session_id: str, after: int, limit: int, tail: bool = False
    ) -> list[UnifiedRecord]:
        return to_unified(session_id, after, limit, tail)

    def read_raw(self, session_id: str, record_id: str) -> dict[str, Any] | None:
        return read_raw(session_id, record_id)
