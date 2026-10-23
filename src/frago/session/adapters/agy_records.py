"""agy (Antigravity CLI) 会话记录 → 统一记录的翻译层。

数据源是 agy 的 ``brain/<conversation_id>/.system_generated/logs/transcript.jsonl``
（见 :mod:`frago.session.agy_store`）。一行一条、只追加，所以 ``seq`` 取**文件物理行序**
——与 Claude Code、codex 两侧同一个口径，NEVER 按时间戳排。

## 一行里可能翻出好几条记录

agy 的一行是它的一"步"，而一步里能同时发生几件事：``PLANNER_RESPONSE`` 可以同时带
``thinking``（想了什么）、``tool_calls``（要动手）与 ``content``（说了什么）。这三样在
时间线上是三条形态不同的记录，所以一行翻成多条——**编号必须分开**（``ag<行号>:think``
之类），否则按编号去重会把后面那几条吃掉。摆的次序按「先想、再动手、后说话」，一次模型
产出在界面上就是读得通的顺序。

## 哪一行是工具跑完那一步

``type`` 字段有两个含义：``USER_INPUT`` / ``PLANNER_RESPONSE`` / ``CONVERSATION_HISTORY``
是 agy 自己的记账名，**其余的按工具名的大写形式写**（实测 ``SEARCH_WEB`` 正对应
``tool_calls`` 里的 ``search_web``）。所以工具结果**不靠工具名白名单认**——认白名单的话，
agy 每加一个工具，它那一步在界面上都会退化成一条空的「未识别注入」。判据是**来源**：
``source`` 为 ``MODEL`` 又不是上面那两个模型记账名的，就是某个工具跑完写下的那一步。

## 用户那句话里裹着 agy 自己拼的元数据

``USER_INPUT`` 的 ``content`` 不是人打的那句话，而是
``<USER_REQUEST>原话</USER_REQUEST><ADDITIONAL_METADATA>…</ADDITIONAL_METADATA>…``。
正文取 ``<USER_REQUEST>`` 里那一段，外面那些块翻成「注入内容」而不是丢掉——会话工作台
的价值之一就是让人看见 agent 当时到底被喂了什么（与 codex 侧处理 ``<environment_context>``
同一个做法；那份也不收进用户发言，否则一条提问会被顶上一大段环境说明）。

## 用量与模型：转录只给了一半

每一次模型回复都带 ``input_tokens`` / ``cache_read_tokens`` / ``output_tokens``，界面上
那道用量刻度由它们换算（见 :func:`_usage_tick`）。但**是谁答的，转录一个字没写**——模型
slug 全机只有一处记着，见 :func:`frago.session.agy_store.session_model`。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session import agy_store
from frago.session.unified_record import RecordKind, ToolFamily, UnifiedRecord
from frago.session.usage_tick import breakdown_from_agy_record, build_tick

logger = logging.getLogger(__name__)

# ``record_payloads`` 产出的种类名。只告诉调用方这是哪一类，形状与 codex 那一侧
# （``codex_store`` 的同名常量）逐字对齐——两家的 adapter 共用同一个消费方。
RECORD_USER_TEXT = "user_text"
RECORD_TEXT = "text"
RECORD_TOOL_CALL = "tool_call"
RECORD_TOOL_RESULT = "tool_result"

# agy 的工具名 → 渲染大类。工具名不是封闭集合（MCP 与用户自定义会往里加），所以按大类
# 分支、认不出的一律 ``other``，NEVER 穷举。
#
# 这份表里的名字有两个出处，都不是猜的：转录里实测到的一个（``search_web``），其余取自
# agy 二进制里的字符串表（``view_file`` / ``edit_file`` / ``run_command`` / ``grep_search``
# 等，见 2026-10-13 的取证）。拿不准归哪一类的（如 ``manage_task`` 既像跑命令又像管任务
# 清单）宁可不写，落进 ``other`` 只是少一个图标，写错是断言了一件不成立的事。
_TOOL_FAMILIES: dict[str, ToolFamily] = {
    # 联网
    "search_web": "web",
    "read_url": "web",
    "execute_url": "web",
    "web_search": "web",
    "list_browser_pages": "web",
    "browser_scroll_dom": "web",
    "browser_move_mouse": "web",
    "browser_mouse_down": "web",
    # 检索（含 agy 自己的代码库检索）
    "grep_search": "search",
    "code_search": "search",
    "moma_search": "search",
    "search_marketplace": "search",
    # 读文件
    "read_file": "file-read",
    "view_file": "file-read",
    "multimodal_view_file": "file-read",
    # 写文件
    "write_file": "file-write",
    "write_to_file": "file-write",
    "create_file": "file-write",
    "edit_file": "file-write",
    "replace_file_content": "file-write",
    "multi_replace_file_content": "file-write",
    "edit_notebook": "file-write",
    "delete_file": "file-write",
    # 跑命令
    "run_command": "shell",
}

# 纯记账类记录：不是任何人说的话，也不是任何动作，翻进时间线只会把真正的内容挤走。
# 这份名单是**明确列举**的，名单之外认不出的照旧摆出来（见 :func:`_unrecognized`），
# NEVER 静默丢弃——丢掉的记录在界面上等于没发生过。
_BOOKKEEPING_TYPES = frozenset({agy_store.RECORD_CONVERSATION_HISTORY})

# 人那句话裹在这对标签里。外面还有 ``<ADDITIONAL_METADATA>`` 与
# ``<USER_SETTINGS_CHANGE>`` 两块，另归「注入内容」。
_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.DOTALL)

# agy 自己给「这条系统消息是 hook 注进来的」打的那句标签，紧跟其后就是注入的正文：
#
#     The following system message was injected by a SessionStart hook:
#     【必须遵守】(source=userdir，仅用户可改)
#     …
#
# 事件名从标签里读，不另猜：同一条记录类型下还躺着 agy 自己的系统通知（"所有子代理因
# 服务重启已停止"），两者只有这句话分得开。
_HOOK_INJECTION_RE = re.compile(
    r"The following system message was injected by a (?P<event>\w+) hook:\s*\n?(?P<body>.*)",
    re.DOTALL,
)


def tool_family_of(tool_name: str) -> ToolFamily:
    """工具名 → 渲染大类。认不出的一律 ``other``，NEVER 因为没见过的工具名炸。"""
    name = (tool_name or "").strip().lower()
    if name.startswith("mcp__") or name.startswith("mcp."):
        return "mcp"
    return _TOOL_FAMILIES.get(name, "other")


def _ms(raw: Any) -> int:
    """转录行上的 ISO 时刻 → 毫秒整数。解不出来时给 0，NEVER 抛。"""
    parsed = agy_store._parse_timestamp(raw)
    if parsed is None:
        return 0
    return int(parsed.timestamp() * 1000)


def _split_user_input(content: str) -> tuple[str, str]:
    """``USER_INPUT`` 的正文拆成（人那句话, agy 自己拼的元数据）。

    **拆不出标签时整段都算人那句话。** 那种情况下按标签切会把正文整段丢掉，界面上这场
    会话就一句用户发言都没有，清单里连标题都取不到——丢内容比多带一段元数据糟得多。
    """
    match = _USER_REQUEST_RE.search(content)
    if match is None:
        return content.strip(), ""
    request = match.group(1).strip()
    rest = (content[: match.start()] + content[match.end() :]).strip()
    return request, rest


#: agy 的事件名 → 界面认识的那一套（引擎 / claude 的词表）。
#:
#: 界面上「什么时候注进来的」那张对照表是按引擎的事件名写的，agy 的 ``PreInvocation``
#: 不在里面，原样摆出来就是一句机器名。两边本来就是同一件事——agy 的 PreInvocation 就是
#: 引擎的 UserPromptSubmit（见 ``cli/agy_hook.py`` 的 ``EVENT_MAP``）。
_HOOK_EVENT_LABEL: dict[str, str] = {"PreInvocation": "UserPromptSubmit"}


def _hook_inject_payload(event: str, body: str, record: dict[str, Any]) -> dict[str, Any]:
    """一条 hook 注入卡的载荷。两种注入形态（带标签的系统消息、裸的即弃消息）共用。"""
    payload: dict[str, Any] = {
        # 与 claude 那边同形：``source="hook"`` 是界面把这一档单独数出来的唯一判据
        # （``RecordStream`` 的 ``lensOf``），缺了它这条卡会落进「系统」那一档。
        "channel": "hook",
        "source": "hook",
        "hook_event": _HOOK_EVENT_LABEL.get(event, event),
        # agy 的 hook 注入只发生在会话开场与每轮提交前，都不针对某个工具。
        "hook_target": None,
        "label": _HOOK_EVENT_LABEL.get(event, event),
        "blocks": [body] if body else [],
        "body": body,
        "unrecognized": False,
    }
    if _is_clipped(record):
        payload["truncation"] = "clipped"
    return payload


def _hook_injection(content: str) -> tuple[str, str] | None:
    """这条 ``SYSTEM_MESSAGE`` 是不是 hook 注进来的。是的话返回（事件名, 正文）。

    **判据是 agy 自己写的那句标签，不是"凡是 SYSTEM_MESSAGE 都算 hook"。** agy 拿同一个
    记录类型发它自己的通知（本机见过一条"所有子代理因服务重启已停止"），把它算成 hook
    注入，界面上 Hooks 那一档就掺进了不是 hook 的东西。认不出标签的一律返回 None，照旧
    走未识别那条路——摆出来、标着未识别，好过挂错档。

    正文尾上那截 ``</SYSTEM_MESSAGE>`` 是 agy 包注入内容用的闭合标签，不属于正文。
    """
    match = _HOOK_INJECTION_RE.search(content)
    if match is None:
        return None
    body = match.group("body").split("</SYSTEM_MESSAGE>")[0].strip()
    return match.group("event"), body


def _is_clipped(record: dict[str, Any]) -> bool:
    """agy 自己交代过这条记录的 ``content`` 被截过。

    ``truncated_fields`` 里列着 ``content`` 就是它说的。照着说，NEVER 把一段截断的正文
    摆成完整的——本机那条 SessionStart 注入的宪法，1882 个字符里尾部已经被切掉一截。
    """
    truncated = record.get("truncated_fields")
    return isinstance(truncated, list) and "content" in truncated


def record_payloads(
    record: dict[str, Any], session_id: str, *, include_user: bool = False
) -> list[tuple[str, dict[str, Any]]]:
    """把一行转录翻成 0~1 条 ``(种类, 归一化记录字典)``（``session.monitor`` 的入参形状）。

    **一行最多出一条。** agy 的一行可以同时带 ``thinking``、``tool_calls`` 与 ``content``
    （见模块开头），而这条路的消费方（``session.monitor.AgyAdapter``）一次只收一条记录，
    所以这里按「**说了什么 > 要动手**」挑一件：人都读得到的正文优先，只有正文缺席时才
    摆出工具调用。``thinking`` 一律丢——codex 那边的 ``reasoning`` 也是这么处理的。

    想要一行里全部几条（想、动手、说话各一条）的走
    :func:`translate_session`：那是会话工作台读记录那条路，它一次收一整批。两条路目的
    不同，NEVER 为了对齐而互相迁就。

    ``include_user`` 为假时不产出用户那半轮（实时流里用户消息由主路径自己投递，重复
    投会在前端出现两遍）；归档那一路要它。
    """
    rtype = record.get("type")
    step = record.get("step_index")
    base = {
        "session_id": session_id,
        "timestamp": agy_store._parse_timestamp(record.get("created_at")) or datetime.now(),
        "role": "assistant",
    }

    if rtype in _BOOKKEEPING_TYPES:
        return []

    if rtype == agy_store.RECORD_USER_INPUT:
        if not include_user:
            return []
        content = record.get("content")
        # 只取人打的那句；外面那几段元数据留给工作台那条路当注入内容。
        text, _meta = _split_user_input(content if isinstance(content, str) else "")
        if not text:
            return []
        return [
            (
                RECORD_USER_TEXT,
                {**base, "role": "user", "uuid": f"user_input:{step}", "content": text},
            )
        ]

    if rtype == agy_store.RECORD_PLANNER:
        answer = record.get("content")
        if isinstance(answer, str) and answer.strip():
            return [(RECORD_TEXT, {**base, "uuid": f"planner:{step}", "content": answer})]
        calls = [call for call in (record.get("tool_calls") or []) if isinstance(call, dict)]
        if not calls:
            return []
        return [
            (
                RECORD_TOOL_CALL,
                {
                    **base,
                    "uuid": f"planner:{step}",
                    "content": "",
                    "tool_calls": [
                        {
                            # **编号就用工具名。** agy 不给调用编号，而消费方拿它对上
                            # 「这条结果是谁的」只为取一个名字（见
                            # ``agent_service`` 的 ``_pending_tool_calls``）。编一个
                            # 假的流水号反而对不上：结果那一步里没有编号可用，只能凭空
                            # 猜它属于哪次调用。用工具名则两侧都算得出来，且 NEVER 挂错
                            # ——退一步说，一轮里同名工具调两次，对出来的名字还是对的。
                            "id": str(call.get("name") or ""),
                            "name": str(call.get("name") or ""),
                            "input": (
                                call.get("args") if isinstance(call.get("args"), dict) else {}
                            ),
                        }
                        for call in calls
                    ],
                },
            )
        ]

    if record.get("source") == "MODEL" and isinstance(rtype, str):
        body = record.get("content")
        return [
            (
                RECORD_TOOL_RESULT,
                {
                    **base,
                    "uuid": f"step:{step}",
                    "content": "",
                    "tool_results": [
                        {
                            # 工具名在上面那次调用里也是编号，两边因此对得上（见那里）。
                            "tool_use_id": rtype.lower(),
                            "content": body if isinstance(body, str) else "",
                            "is_error": _result_status(record.get("status")) != "ok",
                        }
                    ],
                },
            )
        ]

    return []


def _result_status(raw: Any) -> str:
    """工具那一步跑成了没有。

    **只有明写 ``DONE`` 才算成功。** agy 的状态词表是它自己的 ``CORTEX_STEP_STATUS_*``：
    CANCELED / CLEARED / ERROR / HALTED / INTERRUPTED / INVALID 都是没跑成，取不到值时
    同样按没跑成算。方向是**故意挑的**：把一次没跑成摆成成功，比把成功摆成失败坏得多
    ——前者会让人以为那个动作真的发生了（与 codex 侧 ``_custom_output_status`` 同一条
    理由）。
    """
    return "ok" if raw == "DONE" else "error"


@dataclass
class _Usage:
    """整场累计，逐行往前推。

    刻度是**流水**不是水位（两个数的区别见 :mod:`frago.session.usage_tick`），所以累计
    只能一行一行加出来，没法从哪一行单独算得。
    """

    total: int = 0


def _usage_tick(record: dict[str, Any], usage: _Usage, model: str | None) -> dict[str, Any] | None:
    """一条模型回复的用量刻度。这一条没带用量就返回 None。

    分项换算走 :func:`frago.session.usage_tick.breakdown_from_agy_record`，与用量月历共用
    同一份判据。
    """
    breakdown = breakdown_from_agy_record(record)
    if breakdown is None:
        return None
    payload = build_tick(breakdown, total_before=usage.total, model=model)
    usage.total = int(payload["total_tokens"])
    return payload


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


def _drafts_for(
    record: dict[str, Any],
    line: int,
    turn: str | None,
    pending: dict[str, list[str]],
    usage: _Usage,
    model: str | None,
) -> tuple[list[_Draft], str | None]:
    """一行转录 → 0~n 条待编号记录，以及翻完之后的当前轮次。

    ``pending`` 是「发出去还没等到回话的工具调用」：工具名 → 还没被认领的 ``call_id``
    队列。agy 的工具结果那一步**不带调用编号**，只有工具名，所以靠这个队列把调用与结果
    配成对；队列空时按行号编一个，NEVER 编一个假的对上去。

    ``usage`` 是整场累计（跨行状态，刻度要它），``model`` 是这场会话的模型 slug
    （整场一个，由 :func:`translate_session` 先问好）。
    """
    rtype = record.get("type")
    ts = _ms(record.get("created_at"))

    if rtype in _BOOKKEEPING_TYPES:
        return [], turn

    if rtype == agy_store.RECORD_USER_INPUT:
        content = record.get("content")
        text, extra = _split_user_input(content if isinstance(content, str) else "")
        if not text and not extra:
            return [], turn
        # 本轮的分组键取这条用户输入的 ``step_index``：agy 自己用它给每一轮编号，完成探针
        # （:func:`frago.session.agy_store.latest_turn`）用的也是同一个锚点，两边对得上。
        step = record.get("step_index")
        turn = str(step) if step is not None else turn
        drafts: list[_Draft] = []
        if text:
            drafts.append(
                _Draft(
                    id=f"ag{line}",
                    ts=ts,
                    kind="user.say",
                    # 用户输入类不设分组键。
                    group_id=None,
                    payload={
                        "text": text,
                        # agy 不记这句话是怎么进来的。留空，NEVER 默认成「人手打的」——
                        # 那会把机器发起的当成人发起的，是错误信息而不是信息缺失。
                        "input_mode": None,
                        "agent": None,
                    },
                    line=line,
                )
            )
        if extra:
            drafts.append(
                _Draft(
                    id=f"ag{line}:meta",
                    ts=ts,
                    kind="context.inject",
                    group_id=None,
                    payload={
                        "channel": "environment",
                        "label": "agy 拼进用户消息的元数据",
                        "body": extra,
                        "source": "agy",
                        "unrecognized": False,
                    },
                    line=line,
                )
            )
        return drafts, turn

    if rtype == agy_store.RECORD_PLANNER:
        drafts = []
        thinking = record.get("thinking")
        if isinstance(thinking, str) and thinking.strip():
            drafts.append(
                _Draft(
                    id=f"ag{line}:think",
                    ts=ts,
                    kind="agent.think",
                    group_id=turn,
                    payload={"text": thinking, "model": None, "provider": None},
                    line=line,
                )
            )
        for index, call in enumerate(record.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "")
            # agy 不给调用编号，这里按「行号 + 行内第几个」编一个：整场唯一、同一次翻
            # 结果稳定，取原文时按它回查得到。
            call_id = f"ag{line}:call{index}"
            args = call.get("args")
            drafts.append(
                _Draft(
                    id=call_id,
                    ts=ts,
                    kind="tool.call",
                    group_id=turn,
                    payload={
                        "call_id": call_id,
                        "tool_name": name,
                        "tool_family": tool_family_of(name),
                        "args": args if isinstance(args, dict) else {},
                        "title": None,
                    },
                    line=line,
                )
            )
            if name:
                pending.setdefault(name.lower(), []).append(call_id)
        answer = record.get("content")
        if isinstance(answer, str) and answer.strip():
            drafts.append(
                _Draft(
                    id=f"ag{line}:say",
                    ts=ts,
                    kind="agent.say",
                    group_id=turn,
                    payload={"text": answer, "model": model, "provider": None},
                    line=line,
                )
            )
        # 刻度摆在**这一行所有内容之后**：它说的是"这次调用烧了多少"，读的人先看到这次
        # 说了什么、做了什么，再看到账。摆最前会把答案挤到一行记账后面去。
        tick = _usage_tick(record, usage, model)
        if tick is not None:
            drafts.append(
                _Draft(
                    id=f"ag{line}:usage",
                    ts=ts,
                    kind="usage.tick",
                    # 分组键留空，与 claude 那边一致：刻度说的不是"这次回复的一部分"，
                    # 是"到这里为止一共烧了多少"，它独立成一行横在两次回复之间。
                    group_id=None,
                    payload=tick,
                    # 刻度是算出来的，不是档案里的某一行，按编号回查原文必定落空。挂一个
                    # 点不开的入口比不挂更糟——人会以为是取原文这条路坏了。
                    raw_available=False,
                    line=line,
                )
            )
        return drafts, turn

    if rtype == agy_store.RECORD_SYSTEM_MESSAGE:
        content = record.get("content")
        hook = _hook_injection(content) if isinstance(content, str) else None
        if hook is None:
            # agy 自己的系统通知（不是任何人注入的）。照旧摆出来、标未识别——丢掉的记录
            # 在界面上等于没发生过。
            return _unrecognized(record, line, ts, turn), turn
        event, injected = hook
        return (
            [
                _Draft(
                    id=f"ag{line}",
                    ts=ts,
                    kind="context.inject",
                    group_id=turn,
                    payload=_hook_inject_payload(event, injected, record),
                    line=line,
                )
            ],
            turn,
        )

    if rtype == agy_store.RECORD_EPHEMERAL_MESSAGE and record.get("source") == "SYSTEM_SDK":
        # 用完即弃的注入。**事件名是从类型推的，不是读来的**：正文里没有那句标签，而
        # frago 往 agy 的 injectSteps 里放 ephemeralMessage 只有一处——每轮提交前那次
        # 复核（``cli/agy_hook.py`` 的 PreInvocation 分支）。标成它对应的引擎事件名，
        # 界面那张对照表认得。
        content = record.get("content")
        return (
            [
                _Draft(
                    id=f"ag{line}",
                    ts=ts,
                    kind="context.inject",
                    group_id=turn,
                    payload=_hook_inject_payload(
                        "PreInvocation", content.strip() if isinstance(content, str) else "", record
                    ),
                    line=line,
                )
            ],
            turn,
        )

    # 走到这里：既不是记账、也不是用户输入或模型产出。``source`` 为 MODEL 的就是某个工具
    # 跑完写下的那一步（见模块说明），工具名是 ``type`` 的小写形式。
    if record.get("source") == "MODEL" and isinstance(rtype, str):
        name = rtype.lower()
        queue = pending.get(name)
        body = record.get("content")
        return (
            [
                _Draft(
                    id=f"ag{line}",
                    ts=ts,
                    kind="tool.result",
                    group_id=turn,
                    payload={
                        # 配不上调用时按行号编一个：宁可让界面知道"这一步有结果、不知道对应
                        # 哪次调用"，也不能把它挂到别的调用上去。
                        "call_id": queue.pop(0) if queue else f"ag{line}",
                        "tool_name": name,
                        "tool_family": tool_family_of(name),
                        "status": _result_status(record.get("status")),
                        "body": body if isinstance(body, str) else "",
                        # agy 自己交代了正文被截过（``truncated_fields`` 里列着 ``content``）。
                        # 照着说，NEVER 把一段截断的正文摆成完整的。
                        "truncation": "clipped" if _is_clipped(record) else "none",
                        "truncation_ref": None,
                    },
                    line=line,
                )
            ],
            turn,
        )

    return _unrecognized(record, line, ts, turn), turn


def _unrecognized(record: dict[str, Any], line: int, ts: int, turn: str | None) -> list[_Draft]:
    """认不出的记录类型：归注入内容并标记未识别。

    NEVER 静默丢弃——丢掉的记录在界面上等于没发生过，人会以为这段时间什么都没发生。
    """
    return [
        _Draft(
            id=f"ag{line}",
            ts=ts,
            kind="context.inject",
            group_id=turn,
            payload={
                "channel": "unknown",
                "label": str(record.get("type") or ""),
                "body": "",
                "record_type": record.get("type"),
                "source": record.get("source"),
                "keys": sorted(str(key) for key in record),
                "unrecognized": True,
            },
            line=line,
        )
    ]


def _raw_lines(session_id: str) -> list[str]:
    """整场会话的原始行。定位不到 / 读不动时空列表，NEVER 抛。

    **读给人看的那一份**（未截的优先，见 :func:`agy_store.display_transcript_path`）：
    主账把长正文剪短过，照它摆出去，人看到的是"当时注进来的只有这么点"。
    """
    path = agy_store.display_transcript_path(session_id)
    try:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        logger.debug("agy transcript read failed for %s: %s", session_id, exc)
        return []


def _walk(session_id: str) -> Iterator[tuple[int, dict[str, Any], list[_Draft]]]:
    """逐行翻，产出 ``(行号, 原始记录, 这一行翻出来的草稿)``。

    **整场翻译与取原文 MUST 走同一条路。** 编号是按行号与行内次序算出来的，两边各写一遍
    就会各算一套，按编号回查永远查不中，界面上那条记录就永远打不开原文。
    """
    turn: str | None = None
    pending: dict[str, list[str]] = {}
    usage = _Usage()
    # 模型名整场一个，先问一次。它是**另一处**记录里的东西（见 ``agy_store.session_model``），
    # 逐行去问等于把同一个库开几十遍。
    model = agy_store.session_model(session_id)
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
        produced, turn = _drafts_for(record, line, turn, pending, usage, model)
        yield line, record, produced


def translate_session(session_id: str) -> list[UnifiedRecord]:
    """整场会话翻成统一记录，``seq`` 按物理行序从 0 递增。"""
    drafts: list[_Draft] = []
    for _line, _record, produced in _walk(session_id):
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


#: 递给引擎那一趟复核的最多几行、每行最多几个字符。与 opencode 的桥同一档取值：
#: 复核要的是"前面说到哪儿了"，不是逐字复现；一屏装得下的提要读得完，也压得住引擎那边
#: 3000 字符的截断线。
_REVIEW_MAX_LINES = 12
_REVIEW_LINE_CHARS = 300


def _review_line(record: dict[str, Any]) -> str | None:
    """一行转录 → 递给复核的一行提要。不是人说的话、不是模型的产出，返回 None。"""
    rtype = record.get("type")
    if rtype in _BOOKKEEPING_TYPES:
        return None
    if rtype == agy_store.RECORD_USER_INPUT:
        content = record.get("content")
        text, _meta = _split_user_input(content if isinstance(content, str) else "")
        return f"[用户] {text}" if text else None
    if rtype == agy_store.RECORD_PLANNER:
        parts: list[str] = []
        calls = [call for call in (record.get("tool_calls") or []) if isinstance(call, dict)]
        if calls:
            parts.append("[调用] " + " | ".join(str(call.get("name") or "") for call in calls))
        answer = record.get("content")
        if isinstance(answer, str) and answer.strip():
            parts.append(f"[助手] {answer.strip()}")
        return "\n".join(parts) if parts else None
    return None


def review_context(
    transcript_path: str | Path | None,
    conversation_id: str | None = None,
    *,
    max_lines: int = _REVIEW_MAX_LINES,
    line_chars: int = _REVIEW_LINE_CHARS,
) -> tuple[str | None, str | None, bool]:
    """给引擎那一趟复核备料，并回答「这是本轮的第一次模型调用吗」。

    **为什么由垫片来备。** 引擎的 ``UserPromptSubmit`` 靠 ``prompt`` 判"用户到底要什么"、
    靠 ``recent_turns`` 判"前面说到哪儿了"。claude 那边这两样它自己从转录里读——那份格式
    它认识；agy 的转录是第三种格式，它读不动，只会读到一片空。opencode 的桥遇到同一件事
    （它的对话根本不在文件里），做法是把提要渲染好递过去；这里照办，只是提要能从转录里
    读到更多——模型的正文也在。

    本轮那句话**不重复进提要**：它自己有 ``prompt`` 那一栏，两边都给等于让复核把同一句
    读两遍。

    第三个返回值 ``should_review`` 判的是「这一次该不该跑复核」。agy 的 ``PreInvocation``
    是**每次模型调用**都触发（实测一轮 5 次），而引擎的 ``UserPromptSubmit`` 在 claude
    那边一轮只有一次。判据落在转录上，**两条任一成立就跑**：

    1. 本轮的第一次模型调用 —— 最后一条 ``USER_INPUT`` 之后还没出现过 ``PLANNER_RESPONSE``。
    2. 上一拍刚被拒 —— 这一轮最后一条记录是 ``status: ERROR``，工具调用在跑之前就被
       hook 挡下了，模型马上要换做法重来。

    第二条是补窟窿的：只跑首拍的话，首拍那趟复核要是超时或报错，整轮就再没人提醒了。
    认 ``status == ERROR`` 而非看正文，是因为命令自己 ``exit 1`` 的记录是
    ``status: DONE``——那不是被拒，模型照常往下走，不该为它多跑一趟。

    这条判据是无状态的——只读转录，不记事。不依赖 ``invocationNum``：实测它每次模型调用
    都 +1（0、1、2…），不是每轮一个值，拿它判「变化」等于每次都放行。

    返回 ``(prompt, recent_turns, should_review)``。转录读不到时有话直说：
    ``should_review`` 为 True，让引擎照旧干活——**复核少跑一次的代价，远小于它悄悄
    再也不跑**（那正是这套东西上一次栽的地方）。
    """
    path: Path | None = Path(transcript_path) if transcript_path else None
    if path is None or not path.is_file():
        path = agy_store.display_transcript_path(conversation_id) if conversation_id else None
    if path is None or not path.is_file():
        return None, None, True

    records = agy_store.read_records(path)
    if not records:
        return None, None, True

    last_user: int | None = None
    for index, record in enumerate(records):
        if record.get("type") == agy_store.RECORD_USER_INPUT:
            last_user = index

    prompt: str | None = None
    if last_user is not None:
        content = records[last_user].get("content")
        text, _meta = _split_user_input(content if isinstance(content, str) else "")
        prompt = text or None

    # 这一轮从 ``last_user`` 之后开始算。两个判据任一成立就跑复核：
    #
    # 1. **本轮的第一次模型调用** —— 之后还没出现过 ``PLANNER_RESPONSE``。这是常态。
    # 2. **上一拍刚被拒** —— 最后一条记录是 ``status: ERROR``。工具调用在跑之前就被
    #    hook 挡下了，模型马上要换个做法重来；这一刻最需要提醒，也正好补上"首拍那趟
    #    复核没成，整轮就没人提醒"的窟窿。
    #
    # 认 ``status == ERROR`` 而不是看正文里有没有 error：命令自己 exit 1 的记录是
    # ``status: DONE``、失败信息在正文里，那不是"被拒"，模型照常往下走，不该为此多跑一趟。
    in_this_turn = records[last_user + 1 :] if last_user is not None else records
    is_first_call = not any(
        record.get("type") == agy_store.RECORD_PLANNER for record in in_this_turn
    )
    just_denied = bool(in_this_turn) and (in_this_turn[-1].get("status") == agy_store.STATUS_ERROR)
    should_review = is_first_call or just_denied

    earlier = records[:last_user] if last_user is not None else records
    lines: list[str] = []
    for record in earlier:
        line = _review_line(record)
        if not line:
            continue
        lines.append(line if len(line) <= line_chars else line[:line_chars] + "…")

    return prompt, ("\n".join(lines[-max_lines:]) or None), should_review


def context_for_review(
    transcript_path: str | Path | None,
    conversation_id: str | None = None,
    *,
    max_lines: int = _REVIEW_MAX_LINES,
    line_chars: int = _REVIEW_LINE_CHARS,
) -> tuple[str | None, str | None]:
    """只要备料、不问轮次的老签名。转发给 :func:`review_context`。"""
    prompt, recent, _should_review = review_context(
        transcript_path,
        conversation_id,
        max_lines=max_lines,
        line_chars=line_chars,
    )
    return prompt, recent


class AgyRecordAdapter:
    """agy 那一家的记录翻译层（``adapters`` 注册表按家族取它）。"""

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

        agy 的转录是明文 JSON，没有加密与凭据，因此不设「这一类不给原文」的例外。
        """
        for _line, record, produced in _walk(session_id):
            for draft in produced:
                if draft.id != record_id:
                    continue
                if not draft.raw_available:
                    return None
                return record
        return None
