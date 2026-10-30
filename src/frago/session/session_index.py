"""列会话用的会话索引（spec 20260729-session-workbench-webui Phase 2a / 2b）。

左栏清单要七样东西：标题、开口第一句、工作目录、起始时刻、最后活动时刻，再加上**这场
会话现在什么情况**与**最近一件确定做完的事**。前五样出自 Claude Code 的会话文件，后两样
要看每场会话**末尾**那几条记录，两者一起算、一起缓存（见下文第三处）。
``claude_sessions.scan_sessions()`` 为了凑齐它们会把每一行 JSON 都解析一遍——本机
1217 个文件 32.7 万行 2.7 GB，全解析要 7 秒出头。这个模块换一条路径拿同样的字段，
且 ``scan_sessions()`` 一个字不改，它的现有调用方（``/api/claude-sessions`` 背后那个
React 页面）行为不受影响。

两处提速，两处都不牺牲准确性：

**一｜只解析可能相关的行。** 卡片要的字段里，``cwd``/``timestamp``/开口第一句都出现在
文件开头（实测 1213 个文件中，最晚的也在第 5 行 / 第 12 行）；``slug``/``custom-title``/
``ai-title`` 则可能出现在任何位置。所以开头几行照常整行解析，等前三样凑齐之后，后续每
行先做一次字节子串判定，只有可能带标题的行才真去解析。判定用裸词（``b"slug"`` 而不是
``b'"slug":'``），因此不依赖 JSON 分隔符有没有空格：**误判成有只是白解析一行，误判成没有
才会丢字段，而裸词判定不可能漏。** 每一行都过了一遍，没有任何截断。

**二｜按文件大小与修改时刻缓存。** 会话文件只会被追加，追加必然同时改变大小与修改时刻。
缓存条目带着这两个数，对不上就重算那一份，NEVER 拿过期结果充数。

**三｜状态与摘要只读末尾那几条，且跟索引一起缓存。** 判「这场会话什么情况」只需要末条
记录长什么样，判「最近做完了什么」只需要末尾最近那条 agent 回复。所以从文件尾往回读，
先读 6 条，两样都齐了就停（实测绝大多数会话第一次就齐），不齐再退到 24 条、60 条。
NEVER 为了算状态把整个文件从头翻一遍——那正是这个模块存在的理由。

**判据只有一份。** 末尾那几行照样交给 :mod:`~frago.session.adapters.claude_code_records`
的判据表翻成统一记录，这里不另写一套"顶着 user 标记的到底是不是人说的话"。两份判据迟早
各走各的，那时同一场会话在左栏和中栏会长得不一样。

时间：``now`` 取 :func:`time.time` 的 epoch 秒，只做减法。本模块不产出 ``datetime``，
因此不触碰项目的 naive local time 约定，NEVER 出现 ``datetime.now(timezone.utc)``。

NEVER 用文件大小、行数比例之类的办法估算任何字段。这个模块不产出消息条数——左栏不显示
它，而估算出来的数字比不显示更糟，人会当真。真要计数就老老实实全文件数，那是
``scan_sessions()`` 的活。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from frago.session.adapters.agy_records import (
    translate_session as translate_agy_session,
)
from frago.session.adapters.claude_code_records import translate_records
from frago.session.adapters.codex_records import (
    translate_session as translate_codex_session,
)
from frago.session.adapters.opencode_records import translate_session
from frago.session.claude_sessions import (
    _COMMAND_ECHO,
    CLAUDE_PROJECTS_DIR,
    _extract_text,
)
from frago.session.opencode_store import OpencodeSessionRow
from frago.session.unified_record import UnifiedRecord
from frago.skills.skill_prompt import split_skill_blocks

__all__ = [
    "AGY_CACHE_FILE",
    "CACHE_FILE",
    "CODEX_CACHE_FILE",
    "COREAGENT_CACHE_FILE",
    "FRAGO_WAKE_MARKERS",
    "OPENCODE_CACHE_FILE",
    "RUNNING_WINDOW_SECONDS",
    "AgyIndexEntry",
    "CodexIndexEntry",
    "SessionStatus",
    "SessionSummary",
    "TailSignals",
    "agy_tail_signals",
    "clear_cache",
    "codex_tail_signals",
    "derive_status",
    "list_session_summaries",
    "opencode_tail_signals",
    "tail_signals_of",
]

# 索引落在工作台自己的目录下，与 ``~/.frago/cache`` 里那些别的东西分开，删掉它只会让下一
# 次列会话变慢，不会丢数据。
CACHE_DIR = Path.home() / ".frago" / "workbench"
CACHE_FILE = CACHE_DIR / "claude-session-index.json"

# opencode 的会话在 SQLite 里，没有"文件大小 + 修改时刻"可用，失效判据换成会话行自带的
# ``time_updated``。库里 33 场会话，整场翻一遍是毫秒量级，故不做尾部读取那一套。
OPENCODE_CACHE_FILE = CACHE_DIR / "opencode-session-index.json"

# codex 的会话是一个 append-only 的 rollout 文件，所以失效判据回到"文件大小 + 修改
# 时刻"这一对——与 Claude Code 同一个道理，只是不做尾部读取：整场翻一遍是毫秒量级，
# 而且只在真变过的那几场上发生。
CODEX_CACHE_FILE = CACHE_DIR / "codex-session-index.json"

# CoreAgent 的记录与 Claude Code 的形状一模一样，只是落在 ``~/.frago/coreagent/sessions/``
# 下，所以提取与失效判据整套照用，**只是索引另存一份**。混进同一份缓存的话，两侧任一方
# 的条目会被对方的整份覆盖清掉（见 ``list_session_summaries`` 末尾那句"整份覆盖"），
# 下一次列会话就得把另一侧全部重算一遍。
COREAGENT_CACHE_FILE = CACHE_DIR / "coreagent-session-index.json"

# agy 的会话原文落在 ``~/.gemini/antigravity-cli/brain/<cid>/.system_generated/logs/``，
# 本机会话长到上百场后逐场整翻一次要 1 秒以上；按摘要库时刻与转录文件（大小 + 修改时刻）
# 联合失效，没动过的会话直接复用索引。
AGY_CACHE_FILE = CACHE_DIR / "agy-session-index.json"

# 提取规则改了就得让旧条目全部失效，否则会拿着按老规则算出来的字段一直用下去。
# 版本 2 起条目里多了状态与摘要三个字段；版本 3 起多了"最后那句回复是什么时候说的"；
# 版本 4 起"哪句算回复"的判据变了（frago 自己戳出来的心跳不算）；版本 5 修了版本 4 那次
# 判漏的一半——窗口边界切在一轮中间时"没看清是谁戳的"被当成了"不是心跳"。
#
# **判据一改就得动这个数**，哪怕改的是同一条判据的第二版：条目里存的是判完的结果，
# 失效判据只看文件有没有变，文件没变就永远拿老结果顶着。版本 4 那次少动了一次这个数，
# 结果是判据改对了、界面上却还是错的，查了一轮才发现错在缓存。
# 版本 6 起记录文件内容摘要与回合收尾时刻：Claude Code 每小时 utimes 保活只改 mtime
# 不改内容，不再推进 last_active_ts 把已收尾旧会话误判成 running。
_CACHE_VERSION = 6

# 标题类字段可能出现在文件任何位置，所以开头之后的每一行都要做这两个判定。
#
# 用裸词而不是 ``b'"slug":'``：JSON 分隔符有没有空格、键值顺序如何，都影响不到裸词能不能
# 命中。``b"-title"`` 一个词同时罩住 ``custom-title`` 与 ``ai-title`` 两种记录，比分开找
# 少扫一整遍（实测 2.26 GB 上从 4.74 秒降到 3.57 秒），而两种记录的类型名都带这个后缀，
# 罩不漏。
_TITLE_MARKERS = (b"slug", b"-title")

# 冷启动要重算上千份时才值得起进程池——池子本身有启动成本，而增量场景通常只变了几份。
_POOL_THRESHOLD = 64

# ── 状态与摘要 ──────────────────────────────────────────────────────
SessionStatus = Literal["running", "error", "done", "idle"]
"""四档，没有第五档。判定顺序见 :func:`derive_status`，顺序即语义。"""

RUNNING_WINDOW_SECONDS = 90.0
"""最后活动距今在这个窗口内就算还在跑。"""

# 判「末条记录是什么」时要跳过的形态：它们都是引擎的记账，不是任何人做的事。
#
# 不跳过的话这一档基本判不出来。实测本机随机 40 场 Claude Code 会话，物理末行 78.5%
# 是 ``last-prompt``（指针状态）；翻成统一记录后仍有 15% 落在 ``away_summary``（人离开
# 时引擎自己写的小结）、7.5% 落在轮次耗时、5% 落在标题变更。opencode 那边更极端：33 场
# 里 21 场的末条是步骤结束标记，一场都不是 agent 回复。照字面取物理末条，「已完成」这一
# 档会几乎为空，而绝大多数会话明明是正常答完的。
#
# 跳过的这五类共同点是：没有发言人，也没有动作对象。会话状态变更（改标题、切模式、切模
# 型）、一次模型调用的边界（轮次耗时、步骤起止）、注入内容（hook 输出、引擎小结、附件）、
# 待办快照（引擎一个字没改也重发）、用量刻度（一次调用返回后的记账）——它们说明不了
# 这场会话停在哪儿。
_BOOKKEEPING_KINDS = frozenset(
    {"call.envelope", "session.state", "context.inject", "todo.snapshot", "usage.tick"}
)

# ── frago 自己戳的那一下 ────────────────────────────────────────────
# 常驻主控会话（PA）由 frago 的调度器按节拍唤醒：每隔几分钟把同一段角色定义当成
# 一条「用户消息」再送一遍，agent 回一句「没有新消息」就结束。实测本机那场 PA 会话
# 1549 行里，这段唤醒词出现 151 次，161 条回复里 150 条是「No response requested.」
# 或「(无新消息，保持静默待命。)」，真的说了点什么的只有 11 条，最后一条在 7 月 1 日。
#
# **落盘时这一下与人手打的一模一样**：唤醒词那条记录带着 ``origin: {"kind": "human"}``
# 与 ``promptSource: "typed"``，因为 frago 就是从正常输入口把它塞进去的。所以判据不能
# 靠记录自己的标记，只能靠「这段话是 frago 自己写的」这个事实。
#
# NEVER 改成按回复正文判（比如认「No response requested.」这句话）：那是在猜模型说了
# 什么，换个模型、换种措辞就失效，而且会误伤真的只回了一句短话的人类对话。
FRAGO_WAKE_MARKERS = ("你是 frago agent OS 的常驻主控会话（Primary Agent）。",)
"""frago 自己发出的唤醒词开头。**出处是 ``server/services/pa_prompts.py`` 的
``PA_SYSTEM_PROMPT``**，两处由单测钉在一起（改了那边这边的测试就红），本模块属核心
数据层不能反向 import ``server/``。"""

# 从文件尾往回读多少条。先取小的，凑齐了就停；不齐再退到下一档。
#
# 头一档从 3 提到 10：判「这条回复是不是 frago 自己戳出来的」要看得见戳它的那句话，
# 而一次心跳落盘 6～7 行（唤醒词、用量提醒、文件快照、回复、收尾 hook、轮次耗时）。
# 3 行只够看到回复本身，看不到是谁戳的。
_TAIL_WINDOWS = (10, 24, 60)

# 末路一档：整份文件。**只有确实看见心跳的会话才走到这里**——一场会话被 frago 按节拍
# 戳了上百次时，真话可能在几百条之前，60 条的窗口无论如何够不着。没看见心跳却也凑不齐
# 的会话（整场没有 agent 回复的那 80 场）NEVER 走这条路：那会让每次列会话都把它们整个
# 文件翻一遍，而翻完的结果仍然是空。
_FULL_SCAN_RECORDS = 100_000

# 摘要在卡片上只占一行，超出这个长度截断。
_DIGEST_MAX_CHARS = 100


@dataclass(frozen=True)
class TailSignals:
    """一场会话末尾读出来的三样东西。状态与摘要都由它们推出。"""

    last_kind: str | None = None
    """末条**实质**记录的形态。跳过引擎记账（见 :data:`_BOOKKEEPING_KINDS`）。
    一条记录都没有、或者末尾全是记账时为 None。"""

    error_message: str | None = None
    """末条是报错时那条报错的消息。其余情况恒为 None——「卡在」这一格只认有出处的。"""

    digest_done: str | None = None
    """末尾最近一条 agent 回复的头一行。窗口内一条都没有时为 None，NEVER 编一句。"""

    last_reply_ts: float | None = None
    """那条回复是什么时候说的（epoch 秒）。左栏按它排序。

    **NEVER 拿文件修改时刻代替它。** 文件被追加的原因太多了：hook 每拦一次工具就写一
    条、标题被模型改一次写一条、模式切一次写一条。照修改时刻排，一场只是被 hook 蹭过
    的老会话会浮到最前面，而人找的是"最近谁真的答了话"。窗口内一条回复都没有时为
    None，由调用方退回修改时刻——退回是明写的，不是悄悄用同一个数。"""

    heartbeat_only: bool = False
    """看得见的回复全是 frago 自己戳出来的心跳，真话还在更早的地方。

    只在**这一次**读取里有意义，不进缓存——缓存里存的是最后找到的那句真话。"""

    reply_unsettled: bool = False
    """收下的这条回复，没看清是谁戳出来的——窗口边界切在了那一轮中间。

    与上一格分开：一个是"看清了，是机器戳的"，一个是"没看清"。混成一个值的话，窗口
    开多大都会 settle 在最老的那条心跳上。同样不进缓存。"""

    turn_end_ts: float | None = None
    """末条实质记录是 agent 回复且尾部已有带时刻的轮次收尾记账（``turn_duration`` /
    ``stop_hook_summary``）时，记录那一轮真正收尾的时刻（epoch 秒）。"""


def derive_status(
    last_kind: str | None,
    last_active_ts: float,
    now: float | None = None,
) -> SessionStatus:
    """四档状态。**判定顺序不能换**，顺序即语义。

    ========  ============================  ========
    序        条件                          判为
    ========  ============================  ========
    1         末条记录是报错                ``error``
    2         最后活动距今 90 秒内          ``running``
    3         末条记录是 agent 回复         ``done``
    4         其余                          ``idle``
    ========  ============================  ========

    **「等你决策」这一档不做。** 会话停在等人输入时，末条记录就是 agent 的那句回复，与
    「已经答完了」在数据上一模一样。要分开必须读正文判断 agent 是不是在提问，那是语义
    理解。**NEVER 用「末条是 agent 回复且超过 N 分钟没动」凑一个出来**——本机一千多场里
    绝大多数是正常答完的，那样一凑，左栏会变成一片假的"在等你"，比没有这一档糟得多。

    ``now`` 取 epoch 秒（:func:`time.time`）。这里只做减法，不落 ``datetime``。
    """
    if last_kind == "error":
        return "error"
    current = time.time() if now is None else now
    if current - last_active_ts <= RUNNING_WINDOW_SECONDS:
        return "running"
    if last_kind == "agent.say":
        return "done"
    return "idle"


def _one_line(text: Any) -> str | None:
    """一段正文 → 卡片上那一行。取头一个非空行，太长就截。取不出返回 None。"""
    if not isinstance(text, str):
        return None
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if len(line) > _DIGEST_MAX_CHARS:
            return line[:_DIGEST_MAX_CHARS] + "…"
        return line
    return None


def is_wake_text(text: Any) -> bool:
    """这段正文是不是 frago 自己写的唤醒词（见 :data:`FRAGO_WAKE_MARKERS`）。

    按正文判，不按记录判：实时监听那条线上，新来的那批还没变成记录，只看得到正文。
    """
    if not isinstance(text, str):
        return False
    head = text.lstrip()
    return any(head.startswith(marker) for marker in FRAGO_WAKE_MARKERS)


def _is_wake_prompt(record: UnifiedRecord) -> bool:
    """这句话是不是 frago 自己写的唤醒词。"""
    return is_wake_text(record.payload.get("text"))


def _is_heartbeat_reply(records: Sequence[UnifiedRecord], index: int) -> bool | None:
    """第 ``index`` 条回复，是不是 frago 按节拍戳出来的一声"没事"。

    从这条回复往回走，走到**戳它的那句话**为止：

    * 半路遇到工具调用 → 这一轮真干了活，``False``（哪怕开场是唤醒词）。
    * 遇到的是 frago 自己的唤醒词 → ``True``。
    * 遇到的是别的话 → ``False``，那是有人真在问事。
    * 走到窗口开头都没看见是谁戳的 → ``None``，**判不出**。

    判不出与"不是心跳"是两回事，NEVER 混成同一个值：窗口边界常常正好切在一轮中间，
    把"没看清"当成"不是心跳"，结果就是每次都settle在窗口最老的那条心跳上，窗口开多大
    都一样错。调用方拿到 ``None`` 时按"这一档还不够宽"处理。
    """
    for j in range(index - 1, -1, -1):
        kind = records[j].kind
        if kind in ("tool.call", "tool.result", "subagent.dispatch"):
            return False
        if kind == "user.say":
            return _is_wake_prompt(records[j])
    return None


def tail_signals_of(records: Sequence[UnifiedRecord]) -> TailSignals:
    """一批**末尾**统一记录 → 状态与摘要要用的那几个信号。

    两家共用这一份，NEVER 各写各的：opencode 的末条是步骤结束、Claude Code 的末条是轮次
    耗时，形态名不同但都是引擎记账，跳过的规则必须一模一样。

    找"最后一句回复"时会跳过 frago 自己戳出来的心跳（见 :func:`_is_heartbeat_reply`）。
    跳完还没找到真话时 ``heartbeat_only`` 为真，调用方据此把窗口开到整份文件。
    """
    last_kind: str | None = None
    error_message: str | None = None
    for record in reversed(records):
        if record.kind in _BOOKKEEPING_KINDS:
            continue
        last_kind = record.kind
        if record.kind == "error":
            error_message = _one_line(record.payload.get("message"))
        break

    digest_done: str | None = None
    last_reply_ts: float | None = None
    heartbeat_only = False
    reply_unsettled = False
    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        if record.kind != "agent.say":
            continue
        line = _one_line(record.payload.get("text"))
        if not line:
            continue
        verdict = _is_heartbeat_reply(records, index)
        if verdict is True:
            heartbeat_only = True
            continue
        digest_done = line
        # 统一记录的时刻是毫秒，这里换回 epoch 秒——本模块对外只用秒，两种单位混着
        # 走会让 opencode 那侧的时刻大出一千倍，排序整个乱掉。
        last_reply_ts = record.ts / 1000 if record.ts else None
        # 没看清是谁戳的就先收下、同时挂个牌子：调用方会把窗口开宽再问一次，问不出
        # 更好的答案时这条照样作数。NEVER 因为"没看清"就把一条真回复扔掉。
        reply_unsettled = verdict is None
        if not reply_unsettled:
            heartbeat_only = False
        break

    return TailSignals(
        last_kind=last_kind,
        error_message=error_message,
        digest_done=digest_done,
        last_reply_ts=last_reply_ts,
        heartbeat_only=heartbeat_only,
        reply_unsettled=reply_unsettled,
    )


def _iter_lines_backwards(buf: bytes) -> Iterator[bytes]:
    """从末尾往开头逐行吐，空行跳过。整块字节已经在手上，这里不再碰磁盘。"""
    end = len(buf)
    while end > 0:
        start = buf.rfind(b"\n", 0, end)
        line = buf[start + 1 : end]
        end = start
        if line.strip():
            yield line
        if start == -1:
            return


def _completed_turn_ts(
    newest_first: Sequence[dict[str, Any]],
    last_kind: str | None,
) -> float | None:
    """末条实质记录是 agent 回复且尾部已有轮次收尾记账时，返回收尾记账时刻。

    Claude Code 对挂在终端里的已完成会话每小时调一次 ``utimes`` 刷新 ``st_mtime``，
    不改动任何字节。若直接拿 ``st_mtime`` 当最后活动时刻，冷启动重算索引时会把几天前
    早已写下 ``turn_duration`` 的旧会话当成「90 秒内刚动过」判成 ``running``。
    """
    if last_kind != "agent.say":
        return None
    turn_closed = False
    latest_ts: float | None = None
    for record in newest_first:
        ts = _iso_to_epoch(record.get("timestamp"))
        if ts is not None and (latest_ts is None or ts > latest_ts):
            latest_ts = ts
        rtype = record.get("type")
        if rtype == "system" and record.get("subtype") in (
            "turn_duration",
            "stop_hook_summary",
        ):
            if ts is not None:
                turn_closed = True
            continue
        if rtype == "assistant":
            break
    return latest_ts if turn_closed else None


def _tail_signals(buf: bytes, sid: str) -> TailSignals:
    """从文件尾往回读，凑够就停。

    先读 10 条：末条记录长什么样、末尾最近那条 agent 回复说了什么、以及戳出那条回复的
    是谁，绝大多数会话这一档就齐了。不齐再退到 24 条、60 条。读到文件开头仍不齐就照实
    交白卷，NEVER 为此把整个文件翻一遍。

    **只有一种情况例外**：看得见的回复全是 frago 自己戳出来的心跳。那种会话真话可能在
    几百条之前（实测那场 PA 会话里隔了 900 多条），60 条的窗口无论如何够不着，这时才把
    窗口开到整份文件。没看见心跳却也凑不齐的会话不走这条路——翻完仍然是空，白翻。
    """
    lines = _iter_lines_backwards(buf)
    newest_first: list[dict[str, Any]] = []
    exhausted = False
    signals = TailSignals()

    for window in (*_TAIL_WINDOWS, _FULL_SCAN_RECORDS):
        # 整份文件那一档只为心跳会话开：**确实看见 frago 戳过**才值得把整个文件翻一遍。
        # 只是"没看清是谁戳的"不算——那是长轮次的常态（一轮里几百条工具记录），为它全
        # 翻一遍会把每次列会话都拖成分钟级，而翻完的答案跟窗口里那条一模一样。
        if window == _FULL_SCAN_RECORDS and not signals.heartbeat_only:
            break
        while len(newest_first) < window:
            line = next(lines, None)
            if line is None:
                exhausted = True
                break
            record = _loads(line)
            if isinstance(record, dict):
                newest_first.append(record)
        # 判据表按物理顺序命中（序 1 的标题去重、序 7 的通知并入都依赖前后关系），
        # 所以喂进去之前要把顺序转回来。
        signals = tail_signals_of(translate_records(list(reversed(newest_first)), sid))
        settled = (
            signals.last_kind is not None
            and signals.digest_done is not None
            and not signals.reply_unsettled
        )
        if settled or exhausted:
            break
    turn_end_ts = _completed_turn_ts(newest_first, signals.last_kind)
    if turn_end_ts is not None:
        signals = replace(signals, turn_end_ts=turn_end_ts)
    return signals


@dataclass(frozen=True)
class SessionSummary:
    """一个会话文件里，左栏清单需要的全部内容。"""

    sid: str
    slug: str | None
    custom_title: str | None
    ai_title: str | None
    first_user: str | None
    cwd: str | None
    first_ts: float | None
    """会话第一条记录的时刻（epoch 秒）。文件里一条带时刻的记录都没有时为 None。"""

    last_active_ts: float
    """文件修改时刻（epoch 秒）。与 ``scan_sessions()`` 的口径一致。"""

    tail: TailSignals = TailSignals()
    """末尾那几条记录读出来的状态与摘要信号。判到底哪一档由 :func:`derive_status` 做，
    那件事跟"现在几点"有关，不能连同索引一起缓存。"""

    content_digest: str | None = None
    """文件内容摘要（8 字节 blake2b 十六进制），用于识别只刷 mtime 未改字节的保活触碰。"""


def _iso_to_epoch(raw: Any) -> float | None:
    """记录里的 ISO 时刻 → epoch 秒。解不动就当没有，NEVER 编一个出来。

    只做数值换算，不产出 ``datetime``，因此不触碰项目的 naive local time 约定。
    """
    if not raw or not isinstance(raw, str):
        return None
    with contextlib.suppress(ValueError, AttributeError):
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    return None


def _loads(line: bytes) -> Any:
    """解析一行。坏字节按 ``errors="replace"`` 兜底，与全量扫描的读法一致。"""
    try:
        return json.loads(line)
    except UnicodeDecodeError:
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            return json.loads(line.decode("utf-8", errors="replace"))
        return None
    except (json.JSONDecodeError, ValueError):
        return None


#: 斜杠命令写进档案时的壳。人在输入框里打的是 ``/goal 把日历挪到底部``，档案里躺着的是
#: ``<command-name>/goal</command-name>``、``<command-message>``、``<command-args>`` 三段。
_COMMAND_NAME_RE = re.compile(r"<command-name>([\s\S]*?)</command-name>")
_COMMAND_ARGS_RE = re.compile(r"<command-args>([\s\S]*?)</command-args>")


def _first_user_text(txt: str) -> str | None:
    """这条用户记录里，人**自己打的那句话**是什么；不是人打的返回 None。

    分界线是**这条命令里有没有人写的话**：

    - ``/goal 两个问题…``、``/frago.run 把日历挪到底部`` 这种带参数的，参数就是人打的
      那句话，只是被包在壳里。把壳拆开还原成"命令名 + 参数"。
    - ``/clear``、``/compact`` 这种光杆命令，是会话管理动作，不是一句话。跳过去问下一条。
    - ``<local-command-stdout>``，命令打印给人看的东西，同样不是人说的。跳过。
    - 其余照原样。

    **为什么要拆壳。** 从前带参数的那种也整个跳过，于是一场会话的第一句话如果是
    ``/goal 两个问题…``，它就没有"开口第一句"；左栏那一行的标题退到最后一档，写的是
    一串会话编号。人刚从页面开的会话在清单里没有名字，而他明明打了一整句话。

    **与 ``claude_sessions._scan_file()`` 在这一条上不同。** 那条路（``/api/claude-sessions``
    背后那个页面）把带参数的命令也算作"没有开口第一句"，而它拿这个值判这场会话是人开
    的还是 agent 开的——动它就动了那页的会话分类。所以两边只在这一条上分开：那边管分类，
    这边管左栏那一行叫什么名字。光杆命令与命令输出的处置两边完全一致。
    """
    body = txt.strip()
    # 会话页点名的 skill 整篇嵌在这句话前面。标题只要名字加人写的话，与斜杠命令同一个
    # 读法：``/git-push 帮我提交``。整篇 skill 进标题，左栏那一行只剩一串标签。
    skills, said = split_skill_blocks(body)
    if skills:
        return " ".join([*(f"/{n}" for n in skills), said]).strip()
    name = _COMMAND_NAME_RE.search(body)
    if name:
        args = _COMMAND_ARGS_RE.search(body)
        written = (args.group(1) if args else "").strip()
        if not written:
            return None
        return f"{name.group(1).strip()} {written}".strip()
    if _COMMAND_ECHO.match(body):
        return None
    return body


def _extract(path: Path, sid: str, mtime: float) -> SessionSummary | None:
    """读一个会话文件，取出左栏要的字段。读不动返回 None。

    取值规则逐条对齐 ``claude_sessions._scan_file()``：``slug``/``cwd``/起始时刻/开口第一
    句取**首个**命中，``custom-title``/``ai-title`` 取**末个**（后写的覆盖先写的）。
    唯一一处刻意不同是带参数的斜杠命令算不算"开口第一句"，理由写在 ``_first_user_text``。
    """
    slug: str | None = None
    custom_title: str | None = None
    ai_title: str | None = None
    first_user: str | None = None
    cwd: str | None = None
    first_ts: float | None = None

    try:
        with open(path, "rb") as fh:
            buf = fh.read()
    except OSError:
        return None

    # 第一段：从头逐行解析，直到工作目录、起始时刻、开口第一句三样都拿到。实测这三样
    # 最晚分别落在第 5 / 5 / 12 行，所以这一段只碰文件最开头几行。
    #
    # 三样凑不齐时（纯 agent 会话可能整场没有开口第一句，本机 1213 个文件里有 3 个）
    # 这一段会一直走到文件尾。宁可这几个文件慢，NEVER 猜一个值出来充数。
    pos = 0
    size = len(buf)
    while pos < size:
        nl = buf.find(b"\n", pos)
        line = buf[pos:nl] if nl != -1 else buf[pos:]
        pos = size if nl == -1 else nl + 1
        record = _loads(line)
        if not isinstance(record, dict):
            continue
        if slug is None and record.get("slug"):
            slug = record["slug"]
        rtype = record.get("type")
        if rtype == "custom-title" and record.get("customTitle"):
            custom_title = record["customTitle"]
        elif rtype == "ai-title" and record.get("aiTitle"):
            ai_title = record["aiTitle"]
        if cwd is None and record.get("cwd"):
            cwd = record["cwd"]
        if first_ts is None and record.get("timestamp"):
            first_ts = _iso_to_epoch(record.get("timestamp"))
        if first_user is None and rtype == "user" and not record.get("isMeta"):
            msg = record.get("message") or {}
            txt = _extract_text(msg.get("content", ""))
            if txt and txt.strip():
                first_user = _first_user_text(txt)
        if cwd is not None and first_ts is not None and first_user is not None:
            break

    # 第二段：剩下的部分只可能再贡献标题。与其逐行解析几十 KB 的助手回复和工具结果，
    # 不如直接在整块字节里找那三个标记，只把命中所在的那一行捞出来解析。
    #
    # 命中的行按在文件里的先后顺序处理，``slug`` 取首个、两种标题后写覆盖先写——与逐行
    # 扫描的取值规则完全一致。标记命中在正文里（比如某轮对话恰好聊到 slug）只是白解析
    # 一行，不影响结果；而标记不可能在真正的标题记录里缺席，所以不会漏。
    starts: set[int] = set()
    for marker in _TITLE_MARKERS:
        at = buf.find(marker, pos)
        while at != -1:
            line_start = buf.rfind(b"\n", pos - 1 if pos else 0, at) + 1
            starts.add(max(line_start, pos))
            line_end = buf.find(b"\n", at)
            if line_end == -1:
                break
            at = buf.find(marker, line_end + 1)

    for start in sorted(starts):
        end = buf.find(b"\n", start)
        record = _loads(buf[start:end] if end != -1 else buf[start:])
        if not isinstance(record, dict):
            continue
        if slug is None and record.get("slug"):
            slug = record["slug"]
        rtype = record.get("type")
        if rtype == "custom-title" and record.get("customTitle"):
            custom_title = record["customTitle"]
        elif rtype == "ai-title" and record.get("aiTitle"):
            ai_title = record["aiTitle"]

    # 整块字节已经在手上，末尾那几条不再碰一次磁盘。
    tail = _tail_signals(buf, sid)
    active_ts = tail.turn_end_ts if tail.turn_end_ts is not None else mtime
    digest = hashlib.blake2b(buf, digest_size=8).hexdigest()

    return SessionSummary(
        sid=sid,
        slug=slug,
        custom_title=custom_title,
        ai_title=ai_title,
        first_user=first_user,
        cwd=cwd,
        first_ts=first_ts,
        last_active_ts=active_ts,
        tail=tail,
        content_digest=digest,
    )


_DEFAULT_EXTRACT = _extract
_INCREMENTAL_MIN_BYTES = 64 * 1024
_INCREMENTAL_TAIL_BYTES = 512 * 1024


def _extract_incremental(
    path: Path,
    sid: str,
    mtime: float,
    prev: dict[str, Any],
) -> SessionSummary | None:
    """对正在运行、仅在文件末尾追加新行的会话做增量提取。

    当旧索引条目已具备 ``cwd`` / ``first_ts`` / ``first_user`` 且文件体积大于阈值、
    ``st_size > prev_size`` 时，不必每次轮询都从头重读并哈希数兆乃至数十兆的前缀字节：
    - 仅扫描 ``[prev_size:]`` 新增字节段中可能出现的标题标记（``slug`` / ``custom-title`` / ``ai-title``）；
    - 仅回读文件尾部窗口计算 ``_tail_signals``（若遇到心跳未决或长轮次未决则退回全量 ``_extract``）。
    """
    prev_size = prev.get("size")
    if not isinstance(prev_size, int) or prev_size < _INCREMENTAL_MIN_BYTES:
        return _extract(path, sid, mtime)
    if (
        prev.get("cwd") is None
        or prev.get("first_ts") is None
        or prev.get("first_user") is None
    ):
        return _extract(path, sid, mtime)

    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            total_size = fh.tell()
            if total_size <= prev_size:
                return _extract(path, sid, mtime)

            # 1. 读取新增段（往回多取一行边界，防止切在行中间）
            delta_start = max(0, prev_size - 4096)
            fh.seek(delta_start)
            delta_buf = fh.read(total_size - delta_start)

            # 2. 读取尾部窗口供 _tail_signals 判状态与摘要
            tail_start = max(0, total_size - _INCREMENTAL_TAIL_BYTES)
            if tail_start == delta_start:
                tail_buf = delta_buf
            else:
                fh.seek(tail_start)
                tail_buf = fh.read(total_size - tail_start)
    except OSError:
        return None

    if delta_start > 0:
        first_nl = delta_buf.find(b"\n")
        if first_nl != -1 and delta_start + first_nl < prev_size:
            delta_buf = delta_buf[first_nl + 1 :]
    if tail_start > 0:
        tail_nl = tail_buf.find(b"\n")
        if tail_nl != -1:
            tail_buf = tail_buf[tail_nl + 1 :]

    slug: str | None = prev.get("slug")
    custom_title: str | None = prev.get("custom_title")
    ai_title: str | None = prev.get("ai_title")

    starts: set[int] = set()
    for marker in _TITLE_MARKERS:
        at = delta_buf.find(marker, 0)
        while at != -1:
            line_start = delta_buf.rfind(b"\n", 0, at) + 1
            starts.add(line_start)
            line_end = delta_buf.find(b"\n", at)
            if line_end == -1:
                break
            at = delta_buf.find(marker, line_end + 1)

    for start in sorted(starts):
        end = delta_buf.find(b"\n", start)
        record = _loads(delta_buf[start:end] if end != -1 else delta_buf[start:])
        if not isinstance(record, dict):
            continue
        if slug is None and record.get("slug"):
            slug = record["slug"]
        rtype = record.get("type")
        if rtype == "custom-title" and record.get("customTitle"):
            custom_title = record["customTitle"]
        elif rtype == "ai-title" and record.get("aiTitle"):
            ai_title = record["aiTitle"]

    tail = _tail_signals(tail_buf, sid)
    if (tail.heartbeat_only or tail.reply_unsettled) and tail_start > 0:
        return _extract(path, sid, mtime)

    # 若尾部窗口内还没有新的 agent 回复，保留此前已确认的摘要与最后回复时刻
    if tail.digest_done is None and prev.get("digest_done") is not None:
        tail = replace(
            tail,
            digest_done=prev.get("digest_done"),
            last_reply_ts=prev.get("last_reply_ts"),
        )

    active_ts = tail.turn_end_ts if tail.turn_end_ts is not None else mtime
    prev_digest = str(prev.get("digest") or "").encode("ascii", errors="ignore")[:64]
    digest = hashlib.blake2b(delta_buf, key=prev_digest, digest_size=8).hexdigest()

    return SessionSummary(
        sid=sid,
        slug=slug,
        custom_title=custom_title,
        ai_title=ai_title,
        first_user=prev.get("first_user"),
        cwd=prev.get("cwd"),
        first_ts=prev.get("first_ts"),
        last_active_ts=active_ts,
        tail=tail,
        content_digest=digest,
    )


def _as_entry(summary: SessionSummary, size: int, mtime_ns: int) -> dict[str, Any]:
    """缓存条目 = 失效判据（大小 + 修改时刻 + 内容摘要）+ 字段本身。"""
    return {
        "size": size,
        "mtime_ns": mtime_ns,
        "digest": summary.content_digest,
        "sid": summary.sid,
        "slug": summary.slug,
        "custom_title": summary.custom_title,
        "ai_title": summary.ai_title,
        "first_user": summary.first_user,
        "cwd": summary.cwd,
        "first_ts": summary.first_ts,
        "last_active_ts": summary.last_active_ts,
        "last_kind": summary.tail.last_kind,
        "error_message": summary.tail.error_message,
        "digest_done": summary.tail.digest_done,
        "last_reply_ts": summary.tail.last_reply_ts,
        "turn_end_ts": summary.tail.turn_end_ts,
    }


def _from_entry(entry: dict[str, Any]) -> SessionSummary | None:
    """缓存条目 → 字段。形状不对就当没缓存，重算那一份。"""
    try:
        turn_end_raw = entry.get("turn_end_ts")
        turn_end_ts = float(turn_end_raw) if isinstance(turn_end_raw, (int, float)) else None
        digest_raw = entry.get("digest")
        content_digest = str(digest_raw) if isinstance(digest_raw, str) else None
        return SessionSummary(
            sid=str(entry["sid"]),
            slug=entry["slug"],
            custom_title=entry["custom_title"],
            ai_title=entry["ai_title"],
            first_user=entry["first_user"],
            cwd=entry["cwd"],
            first_ts=entry["first_ts"],
            last_active_ts=float(entry["last_active_ts"]),
            tail=TailSignals(
                last_kind=entry["last_kind"],
                error_message=entry["error_message"],
                digest_done=entry["digest_done"],
                last_reply_ts=entry["last_reply_ts"],
                turn_end_ts=turn_end_ts,
            ),
            content_digest=content_digest,
        )
    except (KeyError, TypeError, ValueError):
        return None


#: 内存态索引缓存：cache_file 路径 → (mtime_ns, size, entries)，省掉每轮重复读盘反序列化。
_MEM_INDEX_CACHE: dict[str, tuple[int, int, dict[str, dict[str, Any]]]] = {}

#: 内存态 SessionSummary 对象缓存：jsonl 路径 → (size, mtime_ns, SessionSummary)。
_SUMMARY_OBJ_CACHE: dict[str, tuple[int, int, SessionSummary]] = {}


def _load_cache(cache_file: Path) -> dict[str, dict[str, Any]]:
    """读索引。盘上索引未变时直接命中内存态；读不出来、版本对不上，都当成空。"""
    cache_key = str(cache_file)
    try:
        st = cache_file.stat()
    except OSError:
        _MEM_INDEX_CACHE.pop(cache_key, None)
        return {}
    mem_hit = _MEM_INDEX_CACHE.get(cache_key)
    if mem_hit is not None and mem_hit[0] == st.st_mtime_ns and mem_hit[1] == st.st_size:
        return mem_hit[2]
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        _MEM_INDEX_CACHE.pop(cache_key, None)
        return {}
    if not isinstance(raw, dict) or raw.get("version") != _CACHE_VERSION:
        _MEM_INDEX_CACHE.pop(cache_key, None)
        return {}
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        _MEM_INDEX_CACHE.pop(cache_key, None)
        return {}
    _MEM_INDEX_CACHE[cache_key] = (st.st_mtime_ns, st.st_size, entries)
    return entries


def _save_cache(cache_file: Path, entries: dict[str, dict[str, Any]]) -> None:
    """落索引并同步更新内存态缓存。先写临时文件再改名，NEVER 让读者读到半份。"""
    cache_key = str(cache_file)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(
                {"version": _CACHE_VERSION, "entries": entries},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(cache_file)
        st = cache_file.stat()
        _MEM_INDEX_CACHE[cache_key] = (st.st_mtime_ns, st.st_size, entries)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def clear_cache(cache_file: Path | None = None) -> None:
    """删掉索引并清空内存态缓存。下一次列会话会全量重算。"""
    if cache_file is not None:
        _MEM_INDEX_CACHE.pop(str(cache_file), None)
        targets = [cache_file]
    else:
        _MEM_INDEX_CACHE.clear()
        _SUMMARY_OBJ_CACHE.clear()
        targets = [
            CACHE_FILE,
            OPENCODE_CACHE_FILE,
            CODEX_CACHE_FILE,
            COREAGENT_CACHE_FILE,
            AGY_CACHE_FILE,
        ]
    for target in targets:
        with contextlib.suppress(OSError):
            target.unlink()


def _extract_many(
    stale: list[tuple[str, Path, str, os.stat_result]],
    cached: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[str, os.stat_result, SessionSummary | None]]:
    """把要重算的文件分头算完。

    这里必须是进程而不是线程。真正的开销在整块字节里找标记，那在 CPython 里是不放 GIL
    的纯计算，多个线程只会互相排队——实测 8 线程 5.23 秒，比单线程的 4.80 秒还慢；换成
    8 个进程是 1.33 秒。

    只变了几份时不起池子：池子本身的启动成本比重算几份还贵。且在单进程增量路径下，对已
    有前值、仅在尾部追加的大文件走 :func:`_extract_incremental`，避免重读整份历史前缀。
    """
    if not stale:
        return []
    if len(stale) >= _POOL_THRESHOLD and _extract is _DEFAULT_EXTRACT:
        try:
            workers = min(8, os.cpu_count() or 4, len(stale))
            with ProcessPoolExecutor(max_workers=workers) as pool:
                computed = list(
                    pool.map(
                        _extract,
                        [item[1] for item in stale],
                        [item[2] for item in stale],
                        [item[3].st_mtime for item in stale],
                        chunksize=16,
                    )
                )
            return [
                (item[0], item[3], summary)
                for item, summary in zip(stale, computed, strict=True)
            ]
        except Exception:  # noqa: BLE001 - 见下
            pass
    results: list[tuple[str, os.stat_result, SessionSummary | None]] = []
    for key, path, sid, st in stale:
        prev = cached.get(key) if cached is not None else None
        if isinstance(prev, dict) and st.st_size > (prev.get("size") or 0):
            summary = _extract_incremental(path, sid, st.st_mtime, prev)
            if summary is None:
                summary = _extract(path, sid, st.st_mtime)
        else:
            summary = _extract(path, sid, st.st_mtime)
        results.append((key, st, summary))
    return results


def list_session_summaries(
    projects_root: Path | None = None,
    cache_file: Path | None = None,
) -> list[SessionSummary]:
    """本机全部 Claude Code 会话的清单字段，读过的文件走内存态 + 磁盘双层缓存。

    缓存按「文件大小 + 修改时刻（纳秒）」判定失效。会话文件只会被追加，追加必然同时改变
    这两个数，所以对得上就一定没变过，对不上就重算那一份。
    """
    root = projects_root or CLAUDE_PROJECTS_DIR
    target_cache = cache_file or CACHE_FILE
    if not root.exists():
        return []

    cached = _load_cache(target_cache)
    fresh: dict[str, dict[str, Any]] = {}
    summaries: list[SessionSummary] = []
    stale: list[tuple[str, Path, str, os.stat_result]] = []
    dirty = False

    try:
        proj_entries = sorted(
            (e for e in os.scandir(root) if e.is_dir()),
            key=lambda e: e.name,
        )
    except OSError:
        return []

    for proj_entry in proj_entries:
        try:
            file_entries = list(os.scandir(proj_entry.path))
        except OSError:
            continue
        for fentry in file_entries:
            name = fentry.name
            if not name.endswith(".jsonl"):
                continue
            try:
                st = fentry.stat()
            except OSError:
                continue
            key = fentry.path
            entry = cached.get(key)
            if (
                isinstance(entry, dict)
                and entry.get("size") == st.st_size
                and entry.get("mtime_ns") == st.st_mtime_ns
            ):
                obj_hit = _SUMMARY_OBJ_CACHE.get(key)
                if (
                    obj_hit is not None
                    and obj_hit[0] == st.st_size
                    and obj_hit[1] == st.st_mtime_ns
                ):
                    summaries.append(obj_hit[2])
                    fresh[key] = entry
                    continue
                hit = _from_entry(entry)
                if hit is not None:
                    _SUMMARY_OBJ_CACHE[key] = (st.st_size, st.st_mtime_ns, hit)
                    summaries.append(hit)
                    fresh[key] = entry
                    continue
            dirty = True
            stale.append((key, Path(key), name[:-6], st))

    for key, st, summary in _extract_many(stale, cached):
        if summary is None:
            continue
        prev = cached.get(key)
        if (
            isinstance(prev, dict)
            and prev.get("size") == st.st_size
            and prev.get("digest")
            and prev.get("digest") == summary.content_digest
            and isinstance(prev.get("last_active_ts"), (int, float))
        ):
            summary = replace(summary, last_active_ts=float(prev["last_active_ts"]))
        _SUMMARY_OBJ_CACHE[key] = (st.st_size, st.st_mtime_ns, summary)
        summaries.append(summary)
        fresh[key] = _as_entry(summary, st.st_size, st.st_mtime_ns)

    # 删掉的会话文件不该继续留在索引里，所以整份覆盖而不是增量合并。
    if dirty or len(fresh) != len(cached):
        _save_cache(target_cache, fresh)
    return summaries


def opencode_tail_signals(
    rows: Iterable[OpencodeSessionRow],
    cache_file: Path | None = None,
) -> dict[str, TailSignals]:
    """opencode 那一侧每场会话的状态与摘要信号，读过的会话走缓存。

    失效判据是会话行自带的 ``time_updated``——它就是这一家的"修改时刻"，会话里落任何
    一条新片段都会推进它。对得上就沿用，对不上才重翻那一场。

    这一侧不做尾部读取：记录在 SQLite 里，没有"从文件尾往回读"这回事，而整场翻一遍实测
    每场 6.6 毫秒（本机 33 场共 0.22 秒），只在真变过的那几场上发生。库读不出来时全体
    交白卷，NEVER 让列会话整个失败。
    """
    target_cache = cache_file or OPENCODE_CACHE_FILE
    cached = _load_cache(target_cache)
    fresh: dict[str, dict[str, Any]] = {}
    signals: dict[str, TailSignals] = {}
    dirty = False

    for row in rows:
        sid = row.session_id
        entry = cached.get(sid)
        if isinstance(entry, dict) and entry.get("time_updated") == row.time_updated:
            signals[sid] = TailSignals(
                last_kind=entry.get("last_kind"),
                error_message=entry.get("error_message"),
                digest_done=entry.get("digest_done"),
                last_reply_ts=entry.get("last_reply_ts"),
            )
            fresh[sid] = entry
            continue
        dirty = True
        tail = tail_signals_of(translate_session(sid))
        signals[sid] = tail
        fresh[sid] = {
            "time_updated": row.time_updated,
            "last_kind": tail.last_kind,
            "error_message": tail.error_message,
            "digest_done": tail.digest_done,
            "last_reply_ts": tail.last_reply_ts,
        }

    # 删掉的会话不该继续留在索引里，所以整份覆盖而不是增量合并。
    if dirty or len(fresh) != len(cached):
        _save_cache(target_cache, fresh)
    return signals


# ── codex 那一侧 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class CodexIndexEntry:
    """codex 一场会话在索引里的一条。

    比另外两家多带一个标题：codex 不给会话存标题（``codex archive`` 的会话名是另一
    回事，绝大多数会话没有），只能从开口第一句里取。而取它要翻会话，正好与算状态
    信号是同一趟，所以一起算、一起缓存，NEVER 为了一个标题再翻一遍文件。
    """

    tail: TailSignals
    title: str | None


def _codex_first_user_line(records: Sequence[UnifiedRecord]) -> str | None:
    """整场会话里用户开口的第一句，截成卡片上那一行。一句都没有时 None。"""
    for record in records:
        if record.kind == "user.say":
            return _one_line(record.payload.get("text"))
    return None


def codex_tail_signals(
    metas: Iterable[Any],
    cache_file: Path | None = None,
) -> dict[str, CodexIndexEntry]:
    """codex 那一侧每场会话的状态、摘要与标题，读过的会话走缓存。

    ``metas`` 是 :func:`frago.session.codex_store.list_sessions` 给的会话门面。失效
    判据是 rollout 文件的**修改时刻**——文件只会被追加，追加必然推进它。对得上就沿用，
    对不上才重翻那一场。

    这一侧不做尾部读取：rollout 一行一条、整场翻一遍是毫秒量级，而且只发生在真变过的
    那几场上。读不出来的会话交白卷，NEVER 让列会话整个失败。
    """
    target_cache = cache_file or CODEX_CACHE_FILE
    cached = _load_cache(target_cache)
    fresh: dict[str, dict[str, Any]] = {}
    entries: dict[str, CodexIndexEntry] = {}
    dirty = False

    for meta in metas:
        sid = meta.session_id
        entry = cached.get(sid)
        if isinstance(entry, dict) and entry.get("mtime") == meta.mtime:
            entries[sid] = CodexIndexEntry(
                tail=TailSignals(
                    last_kind=entry.get("last_kind"),
                    error_message=entry.get("error_message"),
                    digest_done=entry.get("digest_done"),
                    last_reply_ts=entry.get("last_reply_ts"),
                ),
                title=entry.get("title"),
            )
            fresh[sid] = entry
            continue
        dirty = True
        try:
            records = translate_codex_session(sid)
        except Exception:  # noqa: BLE001 — 一场翻不动 NEVER 拖垮整份清单
            entries[sid] = CodexIndexEntry(tail=TailSignals(), title=None)
            continue
        tail = tail_signals_of(records)
        title = _codex_first_user_line(records)
        entries[sid] = CodexIndexEntry(tail=tail, title=title)
        fresh[sid] = {
            "mtime": meta.mtime,
            "last_kind": tail.last_kind,
            "error_message": tail.error_message,
            "digest_done": tail.digest_done,
            "last_reply_ts": tail.last_reply_ts,
            "title": title,
        }

    # 删掉的会话不该继续留在索引里，所以整份覆盖而不是增量合并。
    if dirty or len(fresh) != len(cached):
        _save_cache(target_cache, fresh)
    return entries


# ── agy 那一侧 ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class AgyIndexEntry:
    """agy 一场会话在索引里的一条。

    除状态与摘要信号外，连带缓存转录里第一条正时刻（``created_at``，毫秒整数）：
    摘要库不存创建时刻，与状态信号同一趟翻译出来后一并缓存，避免每轮列会话把上百场
    agy 转录从头重翻一遍。
    """

    tail: TailSignals
    created_at: int | None


def agy_tail_signals(
    convs: Iterable[Any],
    cache_file: Path | None = None,
    *,
    translate_fn: Callable[[str], Sequence[UnifiedRecord]] | None = None,
) -> dict[str, AgyIndexEntry]:
    """agy 那一侧每场会话的状态、摘要与创建时刻，读过的会话走内存态 + 磁盘双层缓存。

    失效判据由摘要库时刻（``last_modified`` / ``last_user_input``）与转录文件
    （``st_size`` + ``st_mtime_ns``）共同组成：任意一处推进都会触发该场重算。
    """
    from frago.session import agy_store

    target_cache = cache_file or AGY_CACHE_FILE
    cached = _load_cache(target_cache)
    fresh: dict[str, dict[str, Any]] = {}
    entries: dict[str, AgyIndexEntry] = {}
    translator = translate_fn or translate_agy_session
    dirty = False

    for conv in convs:
        cid = conv.conversation_id
        last_mod = getattr(conv, "last_modified", 0.0)
        last_input = getattr(conv, "last_user_input", 0.0)
        t_size = 0
        t_mtime_ns = 0
        try:
            t_path = getattr(conv, "transcript_path", None) or agy_store.transcript_path(cid)
            st = t_path.stat()
            t_size = st.st_size
            t_mtime_ns = st.st_mtime_ns
        except OSError:
            pass

        entry = cached.get(cid)
        if (
            isinstance(entry, dict)
            and entry.get("last_modified") == last_mod
            and entry.get("last_user_input") == last_input
            and entry.get("t_size") == t_size
            and entry.get("t_mtime_ns") == t_mtime_ns
        ):
            created_raw = entry.get("created_at")
            entries[cid] = AgyIndexEntry(
                tail=TailSignals(
                    last_kind=entry.get("last_kind"),
                    error_message=entry.get("error_message"),
                    digest_done=entry.get("digest_done"),
                    last_reply_ts=entry.get("last_reply_ts"),
                ),
                created_at=int(created_raw) if isinstance(created_raw, int) else None,
            )
            fresh[cid] = entry
            continue

        dirty = True
        try:
            records = translator(cid)
        except Exception:  # noqa: BLE001 — 一场翻不动 NEVER 拖垮整份清单
            records = []
        tail = tail_signals_of(records)
        created_at = next((r.ts for r in records if r.ts > 0), None)
        entries[cid] = AgyIndexEntry(tail=tail, created_at=created_at)
        fresh[cid] = {
            "last_modified": last_mod,
            "last_user_input": last_input,
            "t_size": t_size,
            "t_mtime_ns": t_mtime_ns,
            "last_kind": tail.last_kind,
            "error_message": tail.error_message,
            "digest_done": tail.digest_done,
            "last_reply_ts": tail.last_reply_ts,
            "created_at": created_at,
        }

    if dirty or len(fresh) != len(cached):
        _save_cache(target_cache, fresh)
    return entries

