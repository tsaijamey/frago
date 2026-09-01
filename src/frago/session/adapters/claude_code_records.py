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
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from frago.session.unified_record import RecordKind, ToolFamily, UnifiedRecord

__all__ = [
    "ClaudeCodeRecordAdapter",
    "TranslationStats",
    "clear_cache",
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
    # 这三类同属纯指针，一个字的人类内容都没有，从前全落进兜底、在中栏铺成一张张
    # 「未识别」的原始 JSON 卡。``atis-latch`` 尤其密（抽样 120 场里 1070 条，平均一场
    # 九条），够把系统那一档淹掉。
    "atis-latch",
    "artifact-comment-monitor",
    "artifact-autoreact-ledger",
)
# 同一个键被反复覆写，只留最后那一条。花费账本每轮都重写一次，全留下来等于把同一件事
# 说几十遍；一条都不留又会让"这场烧了多少钱"彻底看不见。
_STANDING_LAST_ONLY_TYPES = ("cost-state",)
_STANDING_TYPES = frozenset(
    _STANDING_TITLE_TYPES
    + _STANDING_MODE_TYPES
    + _STANDING_DROP_TYPES
    + _STANDING_LAST_ONLY_TYPES
)

# 旁挂状态各自把值存在哪个键上。
_STANDING_VALUE_KEY = {
    "ai-title": "aiTitle",
    "custom-title": "customTitle",
    "agent-name": "agentName",
    "mode": "mode",
    "permission-mode": "permissionMode",
}

# ── 引擎自己写的那几种旁白 ──────────────────────────────────────────
# 机器标记名直接摆给人看等于没说。这几种在本机数据里真出现过，各给一句人话。
_SYSTEM_SUBTYPE_LABEL = {
    "away_summary": "你不在时的小结",
    "local_command": "本地命令",
    "informational": "引擎提示",
}

# ── 判据表序 4：引擎侧报错的三种 subtype ────────────────────────────
_ENGINE_ERROR_SUBTYPES = frozenset({"model_refusal_fallback", "model_consent_fallback"})

# ── 判据表序 8：并入附件卡的四种 attachment ─────────────────────────
_MEDIA_ATTACHMENT_TYPES = frozenset(
    {"file", "already_read_file", "nested_memory", "compact_file_reference"}
)

# ── 判据表序 10：其余附件各自叫什么、正文在哪个键上 ──────────────────
# 机器名直接摆给人看等于没说。``total_tokens_reminder`` 抽样 120 场里 3250 条，是这一档
# 里最响的一个，从前它在界面上叫「total_tokens_reminder」。
#
# 正文的键**随类型而变**，取错的下场是卡片正文全空，看起来像"这次注入什么都没说"。
# 插话的三种下场各自怎么说。**标签直接写结果，不写过程**——"排队的输入"只交代了它
# 进过队列，而人要知道的是它到底送没送到。
_QUEUE_STATE_LABEL = {
    "absorbed": "插话 · 已并入当时那一轮",
    "submitted": "插话 · 已作为独立一轮发出",
    "pending": "插话 · 还在队列里",
}

_ATTACHMENT_LABEL = {
    "goal_status": "迭代目标",
    "queued_command": "插话",
    "total_tokens_reminder": "上下文余量",
    "skill_listing": "可用技能",
    "deferred_tools_delta": "工具清单变化",
    "agent_listing_delta": "可用 agent 变化",
    "edited_text_file": "文件被外部改过",
    "auto_mode": "自动模式",
    "plan_mode": "计划模式",
    "plan_mode_exit": "退出计划模式",
    "date_change": "日期换了",
    "command_permissions": "命令授权",
    "hook_cancelled": "旁路注入被取消",
    "task_reminder": "待办清单",
    "read_truncation_notice": "读取被截断",
}

# 正文取哪个键。列在这里的一律优先于默认的 ``content``。
_ATTACHMENT_BODY_KEY = {
    "goal_status": "condition",
    "queued_command": "prompt",
    "total_tokens_reminder": "text",
    "skill_listing": "content",
    "edited_text_file": "snippet",
    "date_change": "newDate",
    "plan_mode_exit": "planFilePath",
    "plan_mode": "planFilePath",
}

# 正文本身是个字符串数组的那几种：拼起来才是人话。
_ATTACHMENT_BODY_LIST_KEY = {
    "deferred_tools_delta": "addedNames",
    "agent_listing_delta": "addedLines",
    "command_permissions": "allowedTools",
}

# ── hook 注入 ───────────────────────────────────────────────────────
# 旁路的轻量 ai 把话塞进上下文，落盘时分两条走：hook 进程自己的执行记录
# （``hook_success``，正文是那一坨原始标准输出），以及引擎最终真的注进上下文的那份
# （``hook_additional_context``，正文已经解析成一段段人话）。同一句话记两遍，谁都不
# 标记谁，中栏于是把同一次注入摆两张卡，其中一张还是 JSON。
#
# 两条的对应关系由 ``toolUseID`` 给出（同一次 PreToolUse 的两条编号一模一样），
# SessionStart 那种多个 hook 合并成一条的情况则靠正文原样相等兜住。
_HOOK_CONTEXT_TYPE = "hook_additional_context"
_HOOK_RESULT_TYPE = "hook_success"

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

    dropped_hook_echo: int = 0
    """序 9：``hook_success`` 说的话已经由 ``hook_additional_context`` 原样记过一遍，
    去掉的那一份回声。同一次注入摆两张卡，其中一张还是 JSON，人只会以为注了两次。"""

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


def _hook_blocks(value: Any) -> list[str]:
    """一次 hook 注入的正文，按段拆开。

    ``content`` 一律是字符串数组：一次事件上挂了几个 hook，就有几段，各说各的
    （SessionStart 那次实测两段）。合成一整块会让人分不出这是两个 hook 各说了一句
    还是一个 hook 说了很长一句，所以段界保留到界面。
    """
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    blocks: list[str] = []
    for item in _as_list(value):
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        text = text.strip()
        if text:
            blocks.append(text)
    return blocks


def _hook_stdout_context(stdout: Any) -> str:
    """hook 进程的标准输出里，真正被注进上下文的那一段。

    约定的形状是 ``{"hookSpecificOutput": {"additionalContext": "..."}}``。解不开、
    或者里面根本没有这一段时返回空串——那说明这次 hook 没往上下文里塞话，它的标准
    输出只是自言自语。
    """
    if not isinstance(stdout, str) or not stdout.strip():
        return ""
    try:
        parsed = json.loads(stdout)
    except (ValueError, TypeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    specific = _as_dict(parsed.get("hookSpecificOutput"))
    context = specific.get("additionalContext")
    return context.strip() if isinstance(context, str) else ""


def _hook_event_of(hook_name: str, fallback: Any = None) -> tuple[str, str]:
    """``PreToolUse:Bash`` → ``("PreToolUse", "Bash")``。

    冒号后那半截是这次 hook 挂在哪个工具上（``SessionStart:clear`` 则是启动方式）。
    界面靠它一眼分出「这是拦在 Bash 前面的那条」还是「开场就注进来的那条」。
    """
    name = hook_name or (fallback if isinstance(fallback, str) else "") or ""
    event, _, target = name.partition(":")
    return event, target


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


def _attachment_body(attachment: dict[str, Any], atype: str) -> str:
    """这种附件的正文在哪个键上。查不到就退回 ``content``。

    退回是明写的：本表没登记过的附件类型仍然要有正文，NEVER 因为不认识就留空——留空
    在界面上跟"这次什么都没说"长得一模一样，人分不出是引擎没说还是我们没读。
    """
    list_key = _ATTACHMENT_BODY_LIST_KEY.get(atype)
    if list_key is not None:
        return "\n".join(str(x) for x in _as_list(attachment.get(list_key)))
    key = _ATTACHMENT_BODY_KEY.get(atype)
    if key is not None:
        value = attachment.get(key)
        if value:
            return str(value)
    body = attachment.get("content")
    if isinstance(body, list):
        return "\n".join(str(x) for x in body)
    return _text_of(body)


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

    两趟：第一趟建索引（工具名、分页截断通知、压缩摘要、旁挂状态的末次位置、引擎最终
    注进上下文的那些话），第二趟按判据表逐行归类。第一趟是必须的——序 19 要知道某个
    工具结果对应的调用是不是 ``Agent``，而调用在结果之前；序 7 要把分页通知并进工具
    结果，而通知在结果之后；序 9 要判 hook 进程说的话是不是已经被原样记过一遍，而那
    条记录可能在它前面也可能在它后面。
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
        # 引擎最终注进上下文的那些话，按 toolUseID 与原文两个口径各存一份。hook 进程
        # 自己那条执行记录靠它判「我说的话已经有人原样记过了」。
        self._injected_by_call: dict[str, set[str]] = {}
        self._injected_texts: set[str] = set()
        self._last_standing_index: dict[str, int] = {}
        self._last_title_index = -1
        # 插话的下场：正文 → 依次的结局（同一句话可能被插过不止一次）。
        self._queue_outcome: dict[str, list[str]] = {}

        # 第二趟游标
        self._dispatch_by_call: dict[str, UnifiedRecord] = {}
        self._group_by_call: dict[str, str | None] = {}
        self._standing_value: dict[str, str] = {}

    # ── 第一趟 ──────────────────────────────────────────────────
    def _build_index(self) -> None:
        self._index_queue_outcomes()
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
                atype = attachment.get("type")
                if atype == "read_truncation_notice":
                    call_id = attachment.get("toolUseID")
                    if isinstance(call_id, str):
                        self._truncation_banner[call_id] = str(attachment.get("banner", ""))
                elif atype == _HOOK_CONTEXT_TYPE:
                    blocks = set(_hook_blocks(attachment.get("content")))
                    self._injected_texts |= blocks
                    call_id = attachment.get("toolUseID")
                    if isinstance(call_id, str) and call_id:
                        self._injected_by_call.setdefault(call_id, set()).update(blocks)
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

    def _index_queue_outcomes(self) -> None:
        """人在 agent 干活时插的那些话，各自最后怎么了。

        这段话不在会话记录里以「用户消息」的形式存在——**它唯一的痕迹就是那张排队卡**，
        而卡本身只说进过队列，不说下场。下场记在另一类记录上，而那类记录从前被整条丢弃，
        于是界面上那句话永远停在"排队的输入"这个说法上：人看到"排队"，自然以为它还在等，
        或者压根没进去。实际上它九秒后就已经送达了。

        两种下场，判据取自实测（抽样 200 场）：

        - **并入当时那一轮**（``remove``，带正文，301 条里 298 条从未成为用户消息）：
          引擎把这句话折进正在跑的那一轮，模型收到了，但它不另立一条用户消息。新版本
          在 ``reason`` 里明写 ``absorbed_mid_turn``，老版本什么都不写，行为是一样的。
        - **作为独立一轮发出**（``dequeue``，207 条）：紧随其后就有一条内容一模一样的
          用户消息，四例四中。

        ``dequeue`` **不带正文**，所以对不上具体哪一句——只能按先进先出弹队首。带正文的
        ``remove`` 则直接按正文摘。两种匹配方式混用是数据形状逼的，不是偷懒。
        """
        pending: list[str] = []
        for row in self._rows:
            if row.get("type") != "queue-operation":
                continue
            op = row.get("operation")
            content = str(row.get("content") or "").strip()
            if op == "enqueue":
                pending.append(content)
                continue
            if op == "remove":
                if content:
                    if content in pending:
                        pending.remove(content)
                    self._queue_outcome.setdefault(content, []).append("absorbed")
                elif pending:
                    self._queue_outcome.setdefault(pending.pop(0), []).append("absorbed")
                continue
            if op == "dequeue" and pending:
                self._queue_outcome.setdefault(pending.pop(0), []).append("submitted")

    def _take_queue_outcome(self, prompt: str) -> str:
        """取这句插话的下场。对不上就说"还在队列里"，NEVER 猜一个。"""
        outcomes = self._queue_outcome.get(prompt.strip())
        if not outcomes:
            return "pending"
        return outcomes.pop(0)

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
                "source": "unrecognized",
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
        if rtype in _STANDING_LAST_ONLY_TYPES:
            self._rule_01_cost(index, rtype, row)
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

    def _rule_01_cost(self, index: int, rtype: str, row: dict[str, Any]) -> None:
        """这场会话的花费账本。每轮重写一次，只留最后那一条。

        账本本身是一坨数字，机器名摆出来等于没说。正文写成一句人话，原始数字留在载荷里
        给要细看的人。
        """
        if index != self._last_standing_index.get(rtype, index):
            self._stats.dropped_standing_stale += 1
            return
        cost = row.get("totalCostUSD")
        duration_ms = row.get("totalDuration")
        pieces: list[str] = []
        if isinstance(cost, int | float):
            pieces.append(f"花费 ${cost:.4f}")
        if isinstance(duration_ms, int | float) and duration_ms:
            pieces.append(f"历时 {duration_ms / 60000:.1f} 分钟")
        added, removed = row.get("totalLinesAdded"), row.get("totalLinesRemoved")
        if isinstance(added, int) and isinstance(removed, int) and (added or removed):
            pieces.append(f"改动 +{added} / -{removed} 行")
        self._emit(
            row,
            "session.state",
            {
                "field": "cost",
                "source_type": rtype,
                "from": None,
                "to": "，".join(pieces) or "（账本是空的）",
                "total_cost_usd": cost,
                "total_duration_ms": duration_ms,
                "model_usage": row.get("modelUsage"),
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
            blocks = _hook_blocks(row.get("hookAdditionalContext"))
            if not blocks and row.get("preventedContinuation") is not True:
                self._stats.dropped_stop_hook += 1
                return
            # 收尾时被拦下来的那次，追加的上下文就在 ``hookAdditionalContext`` 里，
            # 而 ``content`` 这个键在这类记录上压根不存在。照 ``content`` 取，正文永远
            # 是空的，人会以为拦是拦了但没说理由。
            self._emit(
                row,
                "context.inject",
                {
                    "channel": "hook",
                    "source": "hook",
                    "hook_event": "Stop",
                    "hook_target": "",
                    "label": "Stop",
                    "blocks": blocks,
                    "body": "\n\n".join(blocks),
                    "level": row.get("level"),
                    "prevented_continuation": row.get("preventedContinuation"),
                    "stop_reason": row.get("stopReason"),
                },
            )
            return
        self._emit(
            row,
            "context.inject",
            {
                "channel": str(subtype or "system"),
                "source": "system",
                "label": _SYSTEM_SUBTYPE_LABEL.get(str(subtype or ""), str(subtype or "system")),
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

        # 序 9a：引擎最终注进上下文的那份 hook 内容。旁路的轻量 ai 说的话就在这里，
        # 它跟"附件"是两回事，所以自带 ``source="hook"``，界面据此单独立一格。
        if atype == _HOOK_CONTEXT_TYPE:
            self._emit_hook_inject(row, attachment, _hook_blocks(attachment.get("content")))
            return

        # 序 9b：hook 进程自己的执行记录
        if atype == _HOOK_RESULT_TYPE:
            self._rule_09_hook_result(row, attachment)
            return

        # 序 10：其余附件。**正文取哪个键随附件类型而变**（见 ``_ATTACHMENT_BODY_KEY``），
        # 取错的下场是卡片正文全空，看起来像"这次注入什么都没说"。排队的输入正文在
        # ``prompt``、目标状态在 ``condition``、上下文余量在 ``text``，全是真有人写下或
        # 引擎真的说了的话，NEVER 让它们空着。
        key = str(atype or "")
        payload: dict[str, Any] = {
            "channel": key or "attachment",
            "source": "attachment",
            # 标签按「本表给的人话 > hook 名 > 机器类型名」依次退让。退到机器名说明这是
            # 一种本表还没认过的附件，那时把机器名摆出来好过摆一句编造的人话。
            "label": _ATTACHMENT_LABEL.get(key)
            or str(attachment.get("hookName") or key or "attachment"),
            "body": _attachment_body(attachment, key),
            "exit_code": attachment.get("exitCode"),
            "stdout": attachment.get("stdout"),
            "stderr": attachment.get("stderr"),
        }
        if atype == "queued_command":
            # 这是**人在 agent 干活时插的一句话**，不是引擎记账。它在会话记录里没有
            # 「用户消息」那种形态，这张卡是它唯一的痕迹——所以下场必须写在卡上：
            # 只说"进过队列"不说"后来怎么了"，等于让人以为它还在等或者压根没进去。
            state = self._take_queue_outcome(str(attachment.get("prompt") or ""))
            payload["queue_state"] = state
            payload["label"] = _QUEUE_STATE_LABEL[state]
        elif atype == "goal_status":
            payload["goal_met"] = attachment.get("met")
        elif atype == "edited_text_file":
            payload["ref"] = attachment.get("filename")
        elif atype == "hook_cancelled":
            # 这是一次 hook **没跑成**。当普通附件摆出来的话，界面上看不出它跟正常注入
            # 有什么区别，人会以为那句话注进去了。
            payload["hook_event"] = str(attachment.get("hookEvent") or "")
            payload["timed_out"] = attachment.get("timedOut")
            payload["duration_ms"] = attachment.get("durationMs")
            payload["body"] = payload["body"] or (
                f"{attachment.get('hookName') or 'hook'} 超时未返回"
                f"（{attachment.get('timeoutMs')} 毫秒）"
                if attachment.get("timedOut")
                else f"{attachment.get('hookName') or 'hook'} 被取消"
            )
        self._emit(row, "context.inject", payload)

    def _emit_hook_inject(
        self,
        row: dict[str, Any],
        attachment: dict[str, Any],
        blocks: list[str],
        extra: dict[str, Any] | None = None,
    ) -> None:
        """发一条 hook 注入卡。

        ``hook_event`` 与 ``hook_target`` 拆开给：界面要能一眼分出「开场注进来的」、
        「你按下回车时注进来的」和「拦在某个工具前面注进来的」，这三者对读的人意义
        完全不同，混成一个 ``PreToolUse:Bash`` 的机器串等于没分。
        """
        hook_name = str(attachment.get("hookName") or "")
        event, target = _hook_event_of(hook_name, attachment.get("hookEvent"))
        payload: dict[str, Any] = {
            "channel": "hook",
            "source": "hook",
            "hook_event": event or "hook",
            "hook_target": target,
            "label": hook_name or event or "hook",
            "blocks": blocks,
            "body": "\n\n".join(blocks),
        }
        if extra:
            payload.update(extra)
        self._emit(row, "context.inject", payload)

    def _rule_09_hook_result(self, row: dict[str, Any], attachment: dict[str, Any]) -> None:
        """序 9：hook 进程自己那条执行记录。

        两种情况不出卡：**什么都没说**（本机 52604 条里 46531 条，正文空、标准输出是
        空对象、退出码为 0），以及**说过的话引擎已经原样记过一遍**——那句话会由
        ``hook_additional_context`` 再出一张卡，两张摆在一起人只会以为注了两次，而
        这一张的正文还是没解析过的 JSON。

        退出码非零或有标准错误时一律出卡，哪怕它一个字没说：hook 挂了要看得见。
        """
        stdout = attachment.get("stdout")
        content = attachment.get("content")
        exit_code = attachment.get("exitCode")
        stderr = str(attachment.get("stderr") or "").strip()
        healthy = exit_code == 0 and not stderr

        if healthy and not content and _is_silent_stdout(stdout):
            self._stats.dropped_hook_noise += 1
            return

        injected = _hook_stdout_context(stdout)
        call_id = attachment.get("toolUseID")
        echoed = self._injected_by_call.get(call_id, set()) if isinstance(call_id, str) else set()
        if healthy and injected and (injected in echoed or injected in self._injected_texts):
            self._stats.dropped_hook_echo += 1
            return

        blocks = _hook_blocks(injected) or _hook_blocks(content) or _hook_blocks(stdout)
        self._emit_hook_inject(
            row,
            attachment,
            blocks,
            {
                "exit_code": exit_code,
                "stderr": stderr,
                # 标准输出原样留着：形状不合约定的 hook（比如只吐一句 ``decision``）
                # 正文里看不出全貌，那时人要看的就是它原来吐了什么。
                "stdout": stdout,
                "command": str(attachment.get("command") or ""),
                "duration_ms": attachment.get("durationMs"),
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
                    "source": "engine",
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


# ── 翻译结果的缓存 ──────────────────────────────────────────────────
# 一场会话被看的时候，同一个文件会被反复整翻：页面每五秒取一次增量、文件每动一次
# 推一次、取原文再来一次。本机最大那场 82 MB，翻一遍 0.33 秒——安静着不动也照烧不误。
#
# 失效判据是**文件大小加修改时刻**，与 ``session_index`` 那侧同口径：会话文件只会往
# 尾部追加，两者任一变了就是真的变了。判据一改必须 bump 版本号，否则改对了判据、
# 命令行现算是对的、界面上还是旧的。
#
# 只留最近几场：一场大会话的记录对象是十兆量级，留多了内存换不回速度。
_CACHE_CAPACITY = 4
_cache: OrderedDict[str, tuple[int, int, list[UnifiedRecord]]] = OrderedDict()
_cache_lock = Lock()


def _cache_get(path: Path) -> list[UnifiedRecord] | None:
    """缓存里那份还算不算数。文件读不到属性时当没缓存，NEVER 因此抛。"""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path)
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None or entry[0] != stat.st_size or entry[1] != stat.st_mtime_ns:
            return None
        _cache.move_to_end(key)
        return entry[2]


def _cache_put(path: Path, records: list[UnifiedRecord]) -> None:
    try:
        stat = path.stat()
    except OSError:
        return
    with _cache_lock:
        _cache[str(path)] = (stat.st_size, stat.st_mtime_ns, records)
        _cache.move_to_end(str(path))
        while len(_cache) > _CACHE_CAPACITY:
            _cache.popitem(last=False)


def clear_cache() -> None:
    """把缓存清空。给测试用，也给"判据改了要重算"那一刻用。"""
    with _cache_lock:
        _cache.clear()


def to_unified(source: Path | str | Iterable[dict[str, Any]]) -> list[UnifiedRecord]:
    """翻一个会话文件（或一串已解析好的原始记录）。

    传路径时会话编号取文件名；子 agent 的轨迹在同目录下的 ``<会话编号>/subagents/``
    里，用来判断派发卡的轨迹取不取得到。

    传路径这一路带缓存，**返回的列表是共享的**：调用方只许读与切片，NEVER 原地改动
    里面的记录——改了会串到下一个拿到同一份缓存的人身上。
    """
    if isinstance(source, str | Path):
        path = Path(source)
        cached = _cache_get(path)
        if cached is not None:
            return cached
        rows = _read_rows(path)
        trace_dir = path.parent / path.stem / "subagents"
        records = translate_records(rows, path.stem, trace_dir if trace_dir.is_dir() else None)
        _cache_put(path, records)
        return records
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
