"""Claude Code 原始记录 → 统一记录（spec 20260729-session-workbench-webui Phase 1）。

一行 JSONL 进来，零条到多条 :class:`UnifiedRecord` 出去。判据表照调研
``research-claude-session-format.md`` 第 4.4 节的 23 条**按序命中**，顺序即语义：
先命中先归类，换序会改变归类结果。三处硬纪律写在这里，别在别处再判一遍：

1. **顺序取物理行序** — 本机 1212 个会话文件里 850 个（70.1%）时间戳倒挂，共 3973 处，
   根因是并行工具调用落盘时调用与结果交错。``seq`` 是输出序号，随入参的物理顺序单调
   递增，NEVER 按 ``ts`` 排。
2. **``type=="user"`` 里 86% 不是人说的话** — 59173 条里 51002 条是工具结果、2012 条是
   引擎注入的伪消息，真正人手打的只有 4360 条。归 ``user.say`` 是判据表的最后一条兜底，
   前面五条判据先把工具结果、打断、伪消息摘干净。
3. **无法归类的记录归 ``context.inject`` 并标记未识别** — NEVER 静默丢弃。丢掉的记录在
   界面上会凭空消失，人会以为那件事没发生过。判据表里写明"丢弃"的那几类是显式判据，
   不是兜底，落在 :class:`TranslationStats` 里逐类计数，差额随时可解释。

时间：``ts`` 是毫秒整数。原始记录的时间戳是带 ``Z`` 的 ISO 串（252516 条实测 100% 一
致），这里只做"字符串 → 毫秒"的换算，不取当前时间、不格式化、不落 ``datetime``，因此
不触碰项目的 naive local time 约定。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session.unified_record import RecordKind, ToolFamily, UnifiedRecord

__all__ = [
    "ClaudeCodeRecordAdapter",
    "TranslationStats",
    "find_session_file",
    "to_unified",
    "translate_records",
    "translate_with_stats",
]


# ── 判据表序 1 用到的十二种旁挂状态 ──────────────────────────────────
# 这十二类没有 uuid、不参与父子链，同一个键被反复覆写（``ai-title`` 出现 13282 次，
# 实际只对应 1120 个会话的标题演化）。
_STANDING_TITLE_TYPES = ("ai-title", "custom-title", "agent-name")
_STANDING_MODE_TYPES = ("mode", "permission-mode")
_STANDING_DROP_TYPES = (
    "last-prompt",
    "queue-operation",
    "file-history-snapshot",
    "file-history-delta",
    "bridge-session",
    "pr-link",
    "frame-link",
)
_STANDING_TYPES = frozenset(_STANDING_TITLE_TYPES + _STANDING_MODE_TYPES + _STANDING_DROP_TYPES)

# 旁挂状态各自把值存在哪个键上。
_STANDING_VALUE_KEY = {
    "ai-title": "aiTitle",
    "custom-title": "customTitle",
    "agent-name": "agentName",
    "mode": "mode",
    "permission-mode": "permissionMode",
}

# ── 判据表序 4：引擎侧报错的三种 subtype ────────────────────────────
_ENGINE_ERROR_SUBTYPES = frozenset({"model_refusal_fallback", "model_consent_fallback"})

# ── 判据表序 8：并入附件卡的四种 attachment ─────────────────────────
_MEDIA_ATTACHMENT_TYPES = frozenset(
    {"file", "already_read_file", "nested_memory", "compact_file_reference"}
)

# ── 判据表序 15：派发子 agent 的两个工具名 ──────────────────────────
# 本机全部走 ``Agent``，``Task`` 一次都没出现，但两个名字都认——工具名不是封闭集合。
_SUBAGENT_TOOL_NAMES = frozenset({"agent", "task"})

# ── 工具大类 ────────────────────────────────────────────────────────
# 按大类分支，不按工具名穷举：MCP 工具名随用户配置变化，还出现过 ``bash`` / ``Bash``
# 的大小写变体，所以键一律小写后再查。
_TOOL_FAMILY_BY_NAME: dict[str, ToolFamily] = {
    "bash": "shell",
    "read": "file-read",
    "edit": "file-write",
    "write": "file-write",
    "notebookedit": "file-write",
    "grep": "search",
    "glob": "search",
    "toolsearch": "search",
    "webfetch": "web",
    "websearch": "web",
    "agent": "agent",
    "task": "agent",
    "taskcreate": "todo",
    "taskupdate": "todo",
    "tasklist": "todo",
    "taskget": "todo",
    "taskoutput": "todo",
    "taskstop": "todo",
    "todowrite": "todo",
    "askuserquestion": "ask",
    "schedulewakeup": "schedule",
    "croncreate": "schedule",
    "crondelete": "schedule",
    "cronlist": "schedule",
}

# 溢出转存的正文开头。转存时正文里没有任何"截断"字样，只有这一句加落盘路径。
_OFFLOAD_PREFIX = "Output too large ("

# 中段截断的标记形如 ``... [19339 characters truncated] ...``，保留头尾、中间挖空，
# 被挖掉的内容永久丢失。
_CLIPPED_HEAD = "characters truncated] ..."

# 内嵌图片的 base64 动辄二三十万字符，正文里不放，只留形状，原文按需取。
_IMAGE_PLACEHOLDER = "<image>"


@dataclass
class TranslationStats:
    """一次翻译的进出账。差额要能逐条解释，不能只报一个总数。

    ``lines_in`` 减去各类 ``dropped_*`` 与 ``merged_*``，再展开成块，等于
    ``records_out``。任何一条记录的去向都在这张账上，NEVER 出现"不知道去哪了"。
    """

    lines_in: int = 0
    """喂进来多少行（含解析失败的）。"""

    records_out: int = 0
    """吐出多少条统一记录。"""

    dropped_standing: int = 0
    """序 1：``last-prompt`` / ``queue-operation`` / ``file-history-*`` 等纯指针状态。"""

    dropped_standing_stale: int = 0
    """序 1：标题被后来的覆写、模式同值连发，去重掉的那些。"""

    dropped_hook_noise: int = 0
    """序 9：``hook_success`` 里正文空、标准输出没话说（空串或空对象）、退出码为 0 的纯噪音。"""

    dropped_stop_hook: int = 0
    """序 5：``stop_hook_summary`` 里没追加上下文也没拦截的那些。"""

    merged_truncation_notice: int = 0
    """序 7：并进对应工具结果的分页截断通知。"""

    merged_compact_summary: int = 0
    """序 17：并进压缩边界的摘要正文。"""

    merged_subagent_result: int = 0
    """序 19：并进子 agent 派发卡的返回。"""

    unparsable_lines: int = 0
    """JSON 解不开的行。仍会出一条标记未识别的记录，不静默吞。"""

    unrecognized: int = 0
    """判据表全落空、走兜底归 ``context.inject`` 的记录数。"""

    kinds: dict[str, int] = field(default_factory=dict)
    """各形态各出了多少条。"""


# ── 小工具 ──────────────────────────────────────────────────────────
def _as_dict(value: Any) -> dict[str, Any]:
    """取一个大概率是 dict 的值。``toolUseResult`` 同名不同型（49177 条 dict、1726 条
    纯字符串），取字段前必须判类型，否则失败的工具结果会当场把翻译层打断。"""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_ts(raw: Any) -> int | None:
    """ISO8601 串 → epoch 毫秒。解不开返回 None，让调用方沿用上一条的时刻。"""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _is_silent_stdout(value: Any) -> bool:
    """这个 hook 是不是「什么都没说」。

    原判据只认空串，结果零命中：本机 52604 条 hook 记录里标准输出没有一条是空串。
    hook 的惯例是吐一个空的 JSON 对象表示「我没话说」——46531 条走的正是这条路，
    只认空串等于放五万条纯噪音进时间线，中栏会被淹掉。

    带 ``hookSpecificOutput`` 的 6073 条是真有话说的，一条都不能拦。
    """
    if value is None or value == "":
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return True
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, dict) and not parsed


def _tool_family(tool_name: str) -> ToolFamily:
    """工具名 → 渲染分支用的大类。认不出的一律 ``other``，NEVER 抛。"""
    if tool_name.startswith("mcp__"):
        return "mcp"
    return _TOOL_FAMILY_BY_NAME.get(tool_name.lower(), "other")


def _text_of(content: Any) -> str:
    """把 ``content`` 收敛成一段可显示的文本。

    ``message.content`` 可以是字符串（7296 条）或块数组（51877 条）；块数组里还可能混
    着内嵌图片，base64 单张二三十万字符，正文里只留形状。
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    pieces: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            pieces.append(str(block.get("text", "")))
        elif btype in ("image", "document"):
            pieces.append(_IMAGE_PLACEHOLDER)
    return "\n".join(p for p in pieces if p)


def _media_blocks(content: Any) -> list[dict[str, Any]]:
    """挑出块数组里的图片与文档，只留形状与体量，不搬 base64。"""
    out: list[dict[str, Any]] = []
    for block in _as_list(content):
        if not isinstance(block, dict) or block.get("type") not in ("image", "document"):
            continue
        source = _as_dict(block.get("source"))
        data = source.get("data")
        out.append(
            {
                "media_type": source.get("media_type", ""),
                "source_kind": source.get("type", ""),
                "bytes": len(data) if isinstance(data, str) else 0,
                "block_type": block.get("type"),
            }
        )
    return out


def find_session_file(session_id: str, root: Path | None = None) -> Path | None:
    """按会话编号找到那个 JSONL。找不到返回 None，NEVER 抛。

    ``~/.claude/projects/`` 下每个项目一个目录，会话文件名就是会话编号加 ``.jsonl``。
    """
    base = root if root is not None else Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return None
    for candidate in base.glob(f"*/{session_id}.jsonl"):
        return candidate
    return None


# ── 翻译主体 ────────────────────────────────────────────────────────
class _Translator:
    """一场会话翻一次。状态只在这一次翻译里活着，翻完即弃。

    两趟：第一趟建索引（工具名、分页截断通知、压缩摘要、旁挂状态的末次位置），第二趟
    按判据表逐行归类。第一趟是必须的——序 19 要知道某个工具结果对应的调用是不是
    ``Agent``，而调用在结果之前；序 7 要把分页通知并进工具结果，而通知在结果之后。
    """

    def __init__(
        self,
        rows: Sequence[dict[str, Any]],
        session_id: str,
        trace_dir: Path | None = None,
    ) -> None:
        self._rows = rows
        self._session_id = session_id
        self._trace_dir = trace_dir
        self._records: list[UnifiedRecord] = []
        self._stats = TranslationStats(lines_in=len(rows))
        self._last_ts = 0

        # 第一趟索引
        self._tool_name_by_call: dict[str, str] = {}
        self._truncation_banner: dict[str, str] = {}
        self._summary_for_boundary: dict[int, str] = {}
        self._last_standing_index: dict[str, int] = {}
        self._last_title_index = -1

        # 第二趟游标
        self._dispatch_by_call: dict[str, UnifiedRecord] = {}
        self._group_by_call: dict[str, str | None] = {}
        self._standing_value: dict[str, str] = {}

    # ── 第一趟 ──────────────────────────────────────────────────
    def _build_index(self) -> None:
        pending_boundary: int | None = None
        for i, row in enumerate(self._rows):
            rtype = row.get("type")
            if rtype == "assistant":
                for block in _as_list(_as_dict(row.get("message")).get("content")):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        call_id = block.get("id")
                        if isinstance(call_id, str):
                            self._tool_name_by_call[call_id] = str(block.get("name", ""))
            elif rtype == "attachment":
                attachment = _as_dict(row.get("attachment"))
                if attachment.get("type") == "read_truncation_notice":
                    call_id = attachment.get("toolUseID")
                    if isinstance(call_id, str):
                        self._truncation_banner[call_id] = str(attachment.get("banner", ""))
            elif rtype == "system" and row.get("subtype") == "compact_boundary":
                pending_boundary = i
            # 摘要正文取紧随压缩边界之后的那一条；边界的 parentUuid 是 null，
            # 只按 parentUuid 串链的读法会在这里把会话断成两截。
            elif (
                rtype == "user"
                and row.get("isCompactSummary") is True
                and pending_boundary is not None
            ):
                self._summary_for_boundary[pending_boundary] = _text_of(
                    _as_dict(row.get("message")).get("content")
                )
                pending_boundary = None

            if isinstance(rtype, str) and rtype in _STANDING_TYPES:
                self._last_standing_index[rtype] = i
                if rtype in _STANDING_TITLE_TYPES:
                    self._last_title_index = i

    # ── 发条 ────────────────────────────────────────────────────
    def _emit(
        self,
        row: dict[str, Any],
        kind: RecordKind,
        payload: dict[str, Any],
        *,
        record_id: str | None = None,
        group_id: str | None = None,
        raw_available: bool = True,
    ) -> UnifiedRecord:
        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            # 旁挂状态没有时间字段。沿用上一条的时刻，好过写 0 让界面显示 1970 年。
            ts = self._last_ts
        else:
            self._last_ts = ts
        agent_id = row.get("agentId")
        record = UnifiedRecord(
            id=record_id or str(row.get("uuid") or f"{self._session_id}#{len(self._records)}"),
            session_id=str(row.get("sessionId") or self._session_id),
            group_id=group_id,
            seq=len(self._records),
            ts=ts,
            kind=kind,
            agent_path=[str(agent_id)] if isinstance(agent_id, str) and agent_id else [],
            payload=payload,
            # 报错类的原文入口恒不给挂——响应头里带 Cloudflare 登录凭据。
            raw_available=False if kind == "error" else raw_available,
        )
        self._records.append(record)
        self._stats.kinds[kind] = self._stats.kinds.get(kind, 0) + 1
        return record

    def _emit_unrecognized(self, row: dict[str, Any], label: str) -> None:
        """兜底。判据表全落空时走这里，NEVER 静默丢弃。"""
        self._stats.unrecognized += 1
        self._emit(
            row,
            "context.inject",
            {
                "channel": "unrecognized",
                "unrecognized": True,
                "label": label,
                "body": json.dumps(row, ensure_ascii=False),
            },
        )

    # ── 第二趟 ──────────────────────────────────────────────────
    def run(self) -> tuple[list[UnifiedRecord], TranslationStats]:
        self._build_index()
        for i, row in enumerate(self._rows):
            self._translate_row(i, row)
        self._stats.records_out = len(self._records)
        return self._records, self._stats

    def _translate_row(self, index: int, row: dict[str, Any]) -> None:
        rtype = row.get("type")
        if rtype == "__unparsable__":
            self._stats.unparsable_lines += 1
            self._emit_unrecognized(row, "这一行的 JSON 解不开")
            return
        if isinstance(rtype, str) and rtype in _STANDING_TYPES:
            self._rule_01_standing(index, rtype, row)
            return
        if rtype == "system":
            self._rules_02_to_05_system(index, row)
            return
        if rtype == "attachment":
            self._rules_06_to_10_attachment(row)
            return
        if rtype == "assistant":
            self._rules_11_to_16_assistant(row)
            return
        if rtype == "user":
            self._rules_17_to_23_user(row)
            return
        self._emit_unrecognized(row, f"未知的顶层类型 {rtype!r}")

    # 序 1：十二种旁挂状态
    def _rule_01_standing(self, index: int, rtype: str, row: dict[str, Any]) -> None:
        if rtype in _STANDING_DROP_TYPES:
            self._stats.dropped_standing += 1
            return
        value = str(row.get(_STANDING_VALUE_KEY[rtype], ""))
        if rtype in _STANDING_TITLE_TYPES:
            # 标题被反复覆写，同会话只保留最后一条。
            if index != self._last_title_index:
                self._stats.dropped_standing_stale += 1
                return
            field_name = "title"
        else:
            # 模式快照同值连发，去重。
            if self._standing_value.get(rtype) == value:
                self._stats.dropped_standing_stale += 1
                return
            field_name = rtype
        previous = self._standing_value.get(rtype)
        self._standing_value[rtype] = value
        self._emit(
            row,
            "session.state",
            {
                "field": field_name,
                "source_type": rtype,
                "from": previous,
                "to": value,
            },
            record_id=f"{self._session_id}#state-{index}",
        )

    # 序 2～5：引擎侧事件
    def _rules_02_to_05_system(self, index: int, row: dict[str, Any]) -> None:
        subtype = row.get("subtype")

        # 序 2：上下文压缩边界
        if subtype == "compact_boundary":
            meta = _as_dict(row.get("compactMetadata"))
            self._emit(
                row,
                "context.compact",
                {
                    "trigger": meta.get("trigger"),
                    "tokens_before": meta.get("preTokens"),
                    "tokens_after": meta.get("postTokens"),
                    "summary_text": self._summary_for_boundary.get(index, ""),
                    "bridge_from": row.get("logicalParentUuid"),
                },
            )
            return

        # 序 3：一次模型调用的边界。归 ``call.envelope``，载荷原样保留。
        # 早先按兜底塞进注入内容，本机 5324 条会把那一格淹掉——注入内容那一格是给真正
        # 被注入的东西留的，边界标记混进去，人分不出哪条是别人塞进来的话。
        if subtype == "turn_duration":
            self._emit(
                row,
                "call.envelope",
                {
                    "channel": "turn-duration",
                    "label": "轮次耗时",
                    "duration_ms": row.get("durationMs"),
                    "message_count": row.get("messageCount"),
                },
            )
            return

        # 序 4：引擎侧报错
        if subtype in _ENGINE_ERROR_SUBTYPES or (
            subtype == "informational" and row.get("level") == "warning"
        ):
            self._emit(
                row,
                "error",
                {
                    "scope": "engine",
                    "code": str(subtype or ""),
                    "message": str(row.get("content") or ""),
                },
            )
            return

        # 序 5：其余 subtype 归注入内容；Stop hook 汇总里没追加上下文也没拦截的丢弃
        if subtype == "stop_hook_summary":
            has_context = bool(_as_list(row.get("hookAdditionalContext")))
            if not has_context and row.get("preventedContinuation") is not True:
                self._stats.dropped_stop_hook += 1
                return
        self._emit(
            row,
            "context.inject",
            {
                "channel": str(subtype or "system"),
                "label": str(subtype or "system"),
                "body": _text_of(row.get("content")),
                "level": row.get("level"),
                "prevented_continuation": row.get("preventedContinuation"),
                "stop_reason": row.get("stopReason"),
            },
        )

    # 序 6～10：附件
    def _rules_06_to_10_attachment(self, row: dict[str, Any]) -> None:
        attachment = _as_dict(row.get("attachment"))
        atype = attachment.get("type")

        # 序 6：待办清单
        if atype == "task_reminder":
            items = _as_list(attachment.get("content"))
            self._emit(
                row,
                "todo.snapshot",
                {
                    "items": items,
                    "item_count": attachment.get("itemCount", len(items)),
                    # 引擎被动重发，一个字没改也发（本机 4964 条），界面默认折叠。
                    "source": "engine-reminder",
                },
            )
            return

        # 序 7：Read 分页截断通知不独立成条，第一趟已并进对应的工具结果
        if atype == "read_truncation_notice":
            self._stats.merged_truncation_notice += 1
            return

        # 序 8：文件类附件
        if atype in _MEDIA_ATTACHMENT_TYPES:
            self._emit(
                row,
                "media.attach",
                {
                    "media_type": "file",
                    "ref": attachment.get("filename") or attachment.get("path") or "",
                    "display_name": attachment.get("displayPath")
                    or attachment.get("filename")
                    or "",
                    "bytes": len(json.dumps(attachment.get("content"), ensure_ascii=False))
                    if attachment.get("content") is not None
                    else 0,
                    "attachment_type": atype,
                },
            )
            return

        # 序 9：hook 纯噪音（本机 52604 条 hook_success 里的 46531 条）
        if (
            atype == "hook_success"
            and not attachment.get("content")
            and _is_silent_stdout(attachment.get("stdout"))
            and attachment.get("exitCode") == 0
        ):
            self._stats.dropped_hook_noise += 1
            return

        # 序 10：其余附件
        body = attachment.get("content")
        self._emit(
            row,
            "context.inject",
            {
                "channel": str(atype or "attachment"),
                "label": str(attachment.get("hookName") or atype or "attachment"),
                "body": "\n".join(str(x) for x in body) if isinstance(body, list) else _text_of(body),
                "exit_code": attachment.get("exitCode"),
                "stdout": attachment.get("stdout"),
                "stderr": attachment.get("stderr"),
            },
        )

    # 序 11～16：模型回复
    def _rules_11_to_16_assistant(self, row: dict[str, Any]) -> None:
        message = _as_dict(row.get("message"))
        group_id = message.get("id")
        group = str(group_id) if isinstance(group_id, str) else None
        model = message.get("model")

        # 序 11：引擎伪造的报错气泡。type 也是 assistant、也有 text 块，不看这个布尔
        # 值就会在界面上显示成"模型说：API Error: ..."。
        if row.get("isApiErrorMessage") is True:
            self._emit(
                row,
                "error",
                {
                    "scope": "api",
                    "code": str(row.get("error") or row.get("apiErrorStatus") or ""),
                    "message": _text_of(message.get("content")),
                },
                group_id=group,
            )
            return

        blocks = _as_list(message.get("content"))
        if not blocks:
            self._emit_unrecognized(row, "assistant 记录没有任何内容块")
            return

        multi = len(blocks) > 1
        emitted = 0
        for pos, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            rid = f"{row.get('uuid')}#{pos}" if multi else str(row.get("uuid"))
            btype = block.get("type")

            # 序 12：模型降级
            if btype == "fallback":
                self._emit(
                    row,
                    "session.state",
                    {
                        "field": "model",
                        "from": _as_dict(block.get("from")).get("model"),
                        "to": _as_dict(block.get("to")).get("model"),
                    },
                    record_id=rid,
                    group_id=group,
                )
            # 序 13：思考（signature 与内容无关，丢弃）
            elif btype == "thinking":
                self._emit(
                    row,
                    "agent.think",
                    {"text": str(block.get("thinking", "")), "model": model},
                    record_id=rid,
                    group_id=group,
                )
            # 序 14：回复正文
            elif btype == "text":
                self._emit(
                    row,
                    "agent.say",
                    {"text": str(block.get("text", "")), "model": model},
                    record_id=rid,
                    group_id=group,
                )
            # 序 15 / 16：工具调用
            elif btype == "tool_use":
                self._emit_tool_call(row, block, rid, group)
            else:
                self._emit_unrecognized(row, f"assistant 内未知的块类型 {btype!r}")
            emitted += 1

        if emitted == 0:
            self._emit_unrecognized(row, "assistant 记录的内容块全部无法解析")

    def _emit_tool_call(
        self,
        row: dict[str, Any],
        block: dict[str, Any],
        record_id: str,
        group: str | None,
    ) -> None:
        call_id = str(block.get("id", ""))
        tool_name = str(block.get("name", ""))
        args = _as_dict(block.get("input"))
        # 模型吐出的 JSON 没解析成功时的原样兜底，参数结构不可信。
        args_unparsed = args.get("__unparsedToolInput")
        self._group_by_call[call_id] = group

        # 序 15：派发子 agent
        if tool_name.lower() in _SUBAGENT_TOOL_NAMES:
            record = self._emit(
                row,
                "subagent.dispatch",
                {
                    "call_id": call_id,
                    "agent_ref": None,
                    "agent_type": args.get("subagent_type"),
                    "description": args.get("description"),
                    "prompt": args.get("prompt"),
                    "status": None,
                    "stats": {},
                    # 93 次派发只有 92 个轨迹文件，"点了展开但没有轨迹"必须容忍。
                    "trace_available": False,
                },
                record_id=record_id,
                group_id=group,
            )
            self._dispatch_by_call[call_id] = record
            return

        # 序 16：普通工具调用
        self._emit(
            row,
            "tool.call",
            {
                "call_id": call_id,
                "tool_name": tool_name,
                "tool_family": _tool_family(tool_name),
                "args": args,
                "args_unparsed": args_unparsed,
            },
            record_id=record_id,
            group_id=group,
        )

    # 序 17～23：顶着 user 标记的五类东西
    def _rules_17_to_23_user(self, row: dict[str, Any]) -> None:
        # 序 17：压缩摘要不独立成条，第一趟已并进压缩边界
        if row.get("isCompactSummary") is True:
            self._stats.merged_compact_summary += 1
            return

        message = _as_dict(row.get("message"))
        content = message.get("content")
        blocks = _as_list(content)
        results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]

        # 序 18～20：工具结果（59173 条 user 里 51002 条走这条路）
        if results:
            multi = len(blocks) > 1
            for pos, block in enumerate(results):
                rid = f"{row.get('uuid')}#{pos}" if multi else str(row.get("uuid"))
                self._emit_tool_result(row, block, rid)
            leftovers = [
                b for b in blocks if isinstance(b, dict) and b.get("type") != "tool_result"
            ]
            if leftovers:
                self._emit_unrecognized(row, "工具结果记录里混着非工具结果的块")
            return

        # 序 21：用户打断。这类记录不带 isMeta，只看 isMeta 过滤不掉；正文里那句
        # ``[Request interrupted by user]`` 是伪造的，不当用户发言渲染。
        if row.get("interruptedMessageId"):
            text = _text_of(content)
            self._emit(
                row,
                "interrupt",
                {
                    "target": row.get("interruptedMessageId"),
                    "phase": "tool" if "for tool use" in text else "generating",
                    "text": text,
                },
            )
            return

        # 序 22：引擎注入的伪用户消息（本机 2012 条）
        if row.get("isMeta") is True:
            self._emit(
                row,
                "context.inject",
                {
                    "channel": "engine",
                    "label": "引擎注入",
                    "body": _text_of(content),
                    "images": _media_blocks(content),
                },
            )
            return

        # 序 23：其余归用户发言。到这里才是人说的话——本机 59173 条 user 里只剩 6156 条。
        self._emit(
            row,
            "user.say",
            {
                "text": _text_of(content),
                "images": _media_blocks(content),
                "input_mode": row.get("promptSource"),
                # 判据表的兜底不该被误读成"这是工具结果"，显式写死 False 供上层断言。
                "is_tool_result": False,
            },
        )

    def _emit_tool_result(
        self, row: dict[str, Any], block: dict[str, Any], record_id: str
    ) -> None:
        call_id = str(block.get("tool_use_id", ""))
        tool_use_result = row.get("toolUseResult")
        result_dict = _as_dict(tool_use_result)
        denial = row.get("toolDenialKind")
        group = self._group_by_call.get(call_id)

        # 序 19：子 agent 的返回并进派发卡，不独立成条
        dispatch = self._dispatch_by_call.get(call_id)
        is_subagent = self._tool_name_by_call.get(call_id, "").lower() in _SUBAGENT_TOOL_NAMES
        if is_subagent and dispatch is not None:
            agent_id = result_dict.get("agentId")
            dispatch.payload["agent_ref"] = agent_id
            dispatch.payload["status"] = result_dict.get("status") or (
                "denied" if denial else "completed"
            )
            dispatch.payload["stats"] = {
                "tool_stats": result_dict.get("toolStats", {}),
                "total_tokens": result_dict.get("totalTokens"),
                "total_duration_ms": result_dict.get("totalDurationMs"),
                "total_tool_use_count": result_dict.get("totalToolUseCount"),
                "resolved_model": result_dict.get("resolvedModel"),
            }
            dispatch.payload["content"] = result_dict.get("content")
            dispatch.payload["trace_available"] = self._has_trace(agent_id)
            self._stats.merged_subagent_result += 1
            return

        # 序 18：被拦截的调用出两条——拦截标记 + 状态为 denied 的结果
        if denial:
            self._emit(
                row,
                "permission.outcome",
                {
                    "call_id": call_id,
                    "decision": "denied",
                    "reason": str(denial),
                    "mode": row.get("permissionMode"),
                    "classifier_notes": row.get("classifierMetaLines"),
                },
                record_id=f"{record_id}#permission",
                group_id=group,
            )

        # 序 20：工具结果本体
        status = _result_status(block, result_dict, denial)
        body_kind, body = _result_body(block.get("content"))
        truncation, ref = self._result_truncation(call_id, result_dict, body)
        self._emit(
            row,
            "tool.result",
            {
                "call_id": call_id,
                "tool_name": self._tool_name_by_call.get(call_id, ""),
                "status": status,
                "body": body,
                "body_kind": body_kind,
                "truncation": truncation,
                "truncation_ref": ref,
                "duration_ms": result_dict.get("durationMs"),
            },
            record_id=record_id,
            group_id=group,
        )

    def _result_truncation(
        self, call_id: str, result_dict: dict[str, Any], body: str
    ) -> tuple[str, str | None]:
        """三条都要查。两家都有"看着完整其实不完整"的坑，用布尔一定会误判。"""
        persisted = result_dict.get("persistedOutputPath")
        if persisted or body.startswith(_OFFLOAD_PREFIX):
            return "offloaded", str(persisted) if persisted else body.split("\n", 1)[0]
        banner = self._truncation_banner.get(call_id)
        if banner:
            return "offloaded", banner
        if _CLIPPED_HEAD in body:
            return "clipped", None
        return "none", None

    def _has_trace(self, agent_id: Any) -> bool:
        if self._trace_dir is None or not isinstance(agent_id, str) or not agent_id:
            return False
        return (self._trace_dir / f"agent-{agent_id}.jsonl").is_file()


def _result_status(
    block: dict[str, Any], result_dict: dict[str, Any], denial: Any
) -> str:
    """被拒 → 出错 → 被打断 → 正常。**顺序不能换。**

    ``is_error`` 有三态，其中"键不存在"占 40.5%，所以只认 ``is True``：写
    ``"is_error" in block`` 或 ``not block["is_error"]`` 都会把两万条成功判成失败。
    """
    if denial:
        return "denied"
    if block.get("is_error") is True:
        return "error"
    if result_dict.get("interrupted") is True:
        return "interrupted"
    return "ok"


def _result_body(content: Any) -> tuple[str, str]:
    """工具结果的正文形状。图片只留形状，base64 不进 payload。"""
    if isinstance(content, str):
        return "text", content
    blocks = _as_list(content)
    kinds = {b.get("type") for b in blocks if isinstance(b, dict)}
    if kinds == {"image"}:
        return "image", f"{_IMAGE_PLACEHOLDER} × {len(blocks)}"
    return "blocks", _text_of(content)


# ── 对外入口 ────────────────────────────────────────────────────────
def translate_records(
    rows: Sequence[dict[str, Any]],
    session_id: str = "",
    trace_dir: Path | None = None,
) -> list[UnifiedRecord]:
    """一场会话的原始记录 → 统一记录。``seq`` 随入参物理顺序递增，NEVER 按 ``ts`` 排。"""
    records, _ = translate_with_stats(rows, session_id, trace_dir)
    return records


def translate_with_stats(
    rows: Sequence[dict[str, Any]],
    session_id: str = "",
    trace_dir: Path | None = None,
) -> tuple[list[UnifiedRecord], TranslationStats]:
    """同 :func:`translate_records`，另附一份进出账，用来解释行数与记录数的差额。"""
    return _Translator(rows, session_id, trace_dir).run()


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """逐行读，解不开的行不跳过——留一个占位让翻译层出一条标记未识别的记录。"""
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                rows.append({"type": "__unparsable__", "raw_line": stripped[:2000]})
                continue
            rows.append(parsed if isinstance(parsed, dict) else {"type": "__unparsable__"})
    return rows


def to_unified(source: Path | str | Iterable[dict[str, Any]]) -> list[UnifiedRecord]:
    """翻一个会话文件（或一串已解析好的原始记录）。

    传路径时会话编号取文件名；子 agent 的轨迹在同目录下的 ``<会话编号>/subagents/``
    里，用来判断派发卡的轨迹取不取得到。
    """
    if isinstance(source, str | Path):
        path = Path(source)
        rows = _read_rows(path)
        trace_dir = path.parent / path.stem / "subagents"
        return translate_records(rows, path.stem, trace_dir if trace_dir.is_dir() else None)
    return translate_records(list(source))


class ClaudeCodeRecordAdapter:
    """Claude Code 这一家的翻译层。形状对齐 ``adapters.RecordAdapter``。

    登记进注册表的动作留给统一入口那一步做，这里只提供能力。
    """

    family = "claude-code"

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    def to_unified(
        self, session_id: str, after: int = 0, limit: int = 200, tail: bool = False
    ) -> list[UnifiedRecord]:
        """取这场会话从 ``after`` 起的统一记录，最多 ``limit`` 条。

        ``after`` 是本批第一条的 ``seq``，下一批传"上一批最后一条的 seq 加一"。默认 0
        即从头取，正好落在第一条上。这里没有把它做成"上一批最后一条的 seq"的排他游标，
        否则默认值 0 会把第 0 条吃掉——会话的第一条通常正是用户开口那句。

        ``after`` 不是绝对下标：会话被重新解析后 ``seq`` 可能变，界面拿着过期的游标只
        会错位，过期时从 0 重拉。

        ``tail=True`` 时忽略 ``after``，取整场最后 ``limit`` 条。整场本来就要全翻一遍，
        尾部读取不比头部贵。
        """
        path = find_session_file(session_id, self._root)
        if path is None:
            return []
        if tail:
            return to_unified(path)[-limit:]
        return [r for r in to_unified(path) if r.seq >= after][:limit]

    def read_raw(self, session_id: str, record_id: str) -> dict[str, Any] | None:
        """取单条记录的原文。取不到返回 None，NEVER 抛。

        报错类的原文恒不给取——响应头里带 Cloudflare 登录凭据。服务层拦一道，这里再
        拦一道，两道都不能省。
        """
        path = find_session_file(session_id, self._root)
        if path is None:
            return None
        record = next((r for r in to_unified(path) if r.id == record_id), None)
        if record is None or not record.is_raw_readable():
            return None
        base_id = record_id.split("#", 1)[0]
        return next((row for row in _read_rows(path) if row.get("uuid") == base_id), None)
