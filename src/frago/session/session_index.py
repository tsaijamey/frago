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
import json
import os
import time
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from frago.session.adapters.claude_code_records import translate_records
from frago.session.adapters.opencode_records import translate_session
from frago.session.claude_sessions import (
    _COMMAND_ECHO,
    CLAUDE_PROJECTS_DIR,
    _extract_text,
)
from frago.session.opencode_store import OpencodeSessionRow
from frago.session.unified_record import UnifiedRecord

__all__ = [
    "CACHE_FILE",
    "OPENCODE_CACHE_FILE",
    "RUNNING_WINDOW_SECONDS",
    "SessionStatus",
    "SessionSummary",
    "TailSignals",
    "clear_cache",
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

# 提取规则改了就得让旧条目全部失效，否则会拿着按老规则算出来的字段一直用下去。
# 版本 2 起条目里多了状态与摘要三个字段。
_CACHE_VERSION = 2

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
# 跳过的这四类共同点是：没有发言人，也没有动作对象。会话状态变更（改标题、切模式、切模
# 型）、一次模型调用的边界（轮次耗时、步骤起止）、注入内容（hook 输出、引擎小结、附件）、
# 待办快照（引擎一个字没改也重发）——它们说明不了这场会话停在哪儿。
_BOOKKEEPING_KINDS = frozenset(
    {"call.envelope", "session.state", "context.inject", "todo.snapshot"}
)

# 从文件尾往回读多少条。先取小的，两样都齐了就停；不齐再退到下一档。
#
# 头一档取 3 是实测出来的：本机 1139 场会话上，3 / 6 / 12 三种起点算出来的状态与摘要
# 一字不差（判不出末条的 7 场、取不到摘要的 64 场，三种起点完全相同），而冷启动 3 是
# 2.54 秒、6 是 2.94 秒。既然结果一样，就该读得更少。
_TAIL_WINDOWS = (3, 24, 60)

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


def tail_signals_of(records: Sequence[UnifiedRecord]) -> TailSignals:
    """一批**末尾**统一记录 → 状态与摘要要用的三个信号。

    两家共用这一份，NEVER 各写各的：opencode 的末条是步骤结束、Claude Code 的末条是轮次
    耗时，形态名不同但都是引擎记账，跳过的规则必须一模一样。
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
    for record in reversed(records):
        if record.kind != "agent.say":
            continue
        digest_done = _one_line(record.payload.get("text"))
        if digest_done:
            break

    return TailSignals(
        last_kind=last_kind, error_message=error_message, digest_done=digest_done
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


def _tail_signals(buf: bytes, sid: str) -> TailSignals:
    """从文件尾往回读，凑够就停。

    先读 6 条：末条记录长什么样、末尾最近那条 agent 回复说了什么，绝大多数会话这一档
    就齐了。不齐再退到 24 条、60 条。读到文件开头仍不齐就照实交白卷，NEVER 为此把整个
    文件翻一遍。
    """
    lines = _iter_lines_backwards(buf)
    newest_first: list[dict[str, Any]] = []
    exhausted = False
    signals = TailSignals()

    for window in _TAIL_WINDOWS:
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
        if signals.last_kind is not None and signals.digest_done is not None:
            return signals
        if exhausted:
            return signals
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


def _extract(path: Path, sid: str, mtime: float) -> SessionSummary | None:
    """读一个会话文件，取出左栏要的字段。读不动返回 None。

    取值规则逐条对齐 ``claude_sessions._scan_file()``：``slug``/``cwd``/起始时刻/开口第一
    句取**首个**命中，``custom-title``/``ai-title`` 取**末个**（后写的覆盖先写的）。
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
            if txt and txt.strip() and not _COMMAND_ECHO.match(txt):
                first_user = txt.strip()
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

    return SessionSummary(
        sid=sid,
        slug=slug,
        custom_title=custom_title,
        ai_title=ai_title,
        first_user=first_user,
        cwd=cwd,
        first_ts=first_ts,
        last_active_ts=mtime,
        # 整块字节已经在手上，末尾那几条不再碰一次磁盘。
        tail=_tail_signals(buf, sid),
    )


def _as_entry(summary: SessionSummary, size: int, mtime_ns: int) -> dict[str, Any]:
    """缓存条目 = 失效判据（大小 + 修改时刻）+ 字段本身。"""
    return {
        "size": size,
        "mtime_ns": mtime_ns,
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
    }


def _from_entry(entry: dict[str, Any]) -> SessionSummary | None:
    """缓存条目 → 字段。形状不对就当没缓存，重算那一份。"""
    try:
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
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _load_cache(cache_file: Path) -> dict[str, dict[str, Any]]:
    """读索引。读不出来、版本对不上，都当成空——最坏结果是这次全量重算。"""
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != _CACHE_VERSION:
        return {}
    entries = raw.get("entries")
    return entries if isinstance(entries, dict) else {}


def _save_cache(cache_file: Path, entries: dict[str, dict[str, Any]]) -> None:
    """落索引。先写临时文件再改名，让并发的读者要么读到旧的要么读到新的，NEVER 读到半份。

    写不进去只是下次列会话慢一点，不该让列会话本身失败。
    """
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
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def clear_cache(cache_file: Path | None = None) -> None:
    """删掉索引。下一次列会话会全量重算。

    不指定路径时两家的索引一起删——只删一半会让下一次列会话半新半旧，比全删更难解释。
    """
    targets = [cache_file] if cache_file is not None else [CACHE_FILE, OPENCODE_CACHE_FILE]
    for target in targets:
        with contextlib.suppress(OSError):
            target.unlink()


def _extract_many(
    stale: list[tuple[str, Path, str, os.stat_result]],
) -> list[tuple[str, os.stat_result, SessionSummary | None]]:
    """把要重算的文件分头算完。

    这里必须是进程而不是线程。真正的开销在整块字节里找标记，那在 CPython 里是不放 GIL
    的纯计算，多个线程只会互相排队——实测 8 线程 5.23 秒，比单线程的 4.80 秒还慢；换成
    8 个进程是 1.33 秒。

    只变了几份时不起池子：池子本身的启动成本比重算几份还贵。
    """
    if not stale:
        return []
    if len(stale) >= _POOL_THRESHOLD:
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
            # 进程池在受限环境里可能压根起不来（已经身处 daemon 进程、被沙箱掐掉 fork
            # 等等），失败形态五花八门。列会话不该因为提速手段用不了就整个失败，退回
            # 单进程算完——慢，但结果一模一样。
            pass
    return [(item[0], item[3], _extract(item[1], item[2], item[3].st_mtime)) for item in stale]


def list_session_summaries(
    projects_root: Path | None = None,
    cache_file: Path | None = None,
) -> list[SessionSummary]:
    """本机全部 Claude Code 会话的清单字段，读过的文件走缓存。

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

    for proj_dir in sorted(root.iterdir()):
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            try:
                st = jsonl.stat()
            except OSError:
                continue
            key = str(jsonl)
            entry = cached.get(key)
            if (
                isinstance(entry, dict)
                and entry.get("size") == st.st_size
                and entry.get("mtime_ns") == st.st_mtime_ns
            ):
                hit = _from_entry(entry)
                if hit is not None:
                    summaries.append(hit)
                    fresh[key] = entry
                    continue
            stale.append((key, jsonl, jsonl.stem, st))

    for key, st, summary in _extract_many(stale):
        if summary is None:
            continue
        summaries.append(summary)
        fresh[key] = _as_entry(summary, st.st_size, st.st_mtime_ns)

    # 删掉的会话文件不该继续留在索引里，所以整份覆盖而不是增量合并。
    if fresh != cached:
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

    for row in rows:
        sid = row.session_id
        entry = cached.get(sid)
        if isinstance(entry, dict) and entry.get("time_updated") == row.time_updated:
            signals[sid] = TailSignals(
                last_kind=entry.get("last_kind"),
                error_message=entry.get("error_message"),
                digest_done=entry.get("digest_done"),
            )
            fresh[sid] = entry
            continue
        tail = tail_signals_of(translate_session(sid))
        signals[sid] = tail
        fresh[sid] = {
            "time_updated": row.time_updated,
            "last_kind": tail.last_kind,
            "error_message": tail.error_message,
            "digest_done": tail.digest_done,
        }

    # 删掉的会话不该继续留在索引里，所以整份覆盖而不是增量合并。
    if fresh != cached:
        _save_cache(target_cache, fresh)
    return signals
