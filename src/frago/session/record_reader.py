"""会话记录的统一入口（spec 20260729-session-workbench-webui Phase 1）。

服务层只跟这个模块打交道：要清单叫 :func:`list_sessions`，要记录叫
:func:`read_records`，要原文叫 :func:`read_raw`。哪一家、怎么翻，全在这一层里判完，
上面不需要知道 Claude Code 的记录躺在 JSONL 里而 opencode 的在 SQLite 里。

哪一家的翻译层由 :mod:`frago.session.adapters` 的注册表给出，这里不写 if/else——以后
再接第三个 CLI，只要它登记进注册表，这个模块一个字不用改。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from frago.session import (
    adapters,
    codex_store,
    coreagent_store,
    opencode_store,
    session_index,
    session_origin,
)
from frago.session.adapters import claude_code_records
from frago.session.session_index import SessionStatus, TailSignals, derive_status
from frago.session.session_origin import OriginIndex, SessionOrigin
from frago.session.unified_record import RecordFamily, UnifiedRecord

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "DeletedSession",
    "SessionCard",
    "SessionDeleteUnsupported",
    "SessionFilesMissing",
    "UnknownSessionFamily",
    "delete_session",
    "detect_family",
    "list_sessions",
    "read_raw",
    "read_records",
    "sort_key",
]

# 分页是硬要求，不是礼貌。单条工具结果见过 7.2 万字符、单条用户消息见过 22 万字符，
# 一次拉整场大会话会把浏览器打死。
DEFAULT_LIMIT = 200
MAX_LIMIT = 500

# opencode 的会话编号一律带这个前缀（``ses_058288655ffeYMxYC1AZKCcv56``），
# 消息与片段则是 ``msg_`` / ``prt_``。
_OPENCODE_SESSION_PREFIX = "ses_"

# Claude Code 的会话编号是文件名里的 UUID（``00a02979-7eb4-5c70-94ae-867c8281e3f6``）。
_UUID_SHAPE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class UnknownSessionFamily(ValueError):
    """这个会话编号两家的形状都不像。服务层据此回 404，NEVER 猜一家试试。"""


@dataclass
class SessionCard:
    """左栏清单里的一条会话。两家的会话行各自映射成这个形状后合并排序。"""

    session_id: str
    family: RecordFamily
    title: str
    directory: str
    created_at: int
    """毫秒时间戳。"""

    last_active_at: int
    """毫秒时间戳。会话文件最后被动过的时刻，判"还在跑吗"用它。"""

    last_reply_at: int | None = None
    """最后一句 agent 回复是什么时候说的（毫秒时间戳）。**清单按它倒序。**

    与上一格分开是因为两者会差很远：hook 每拦一次工具、模型每改一次标题都会推进"最后
    动过"，但那些都不是任何人说了话。取不到时为 None，排序退回上一格。"""

    agent_paths: list[str] = field(default_factory=list)
    """这场会话下出现过的子 agent 轨迹。主会话一条也没有时是 ``[]``。"""

    status: SessionStatus = "idle"
    """四档之一。判定顺序见 :func:`~frago.session.session_index.derive_status`。"""

    digest_done: str | None = None
    """最近一件确定做完的事：末尾最近那条 agent 回复的头一行。没有就留空。"""

    digest_stuck: str | None = None
    """当前阻塞点：状态为报错时那条报错的消息。其余情况恒为空。"""

    origin: SessionOrigin = "human"
    """这场是人自己开的，还是 frago 派出去干活的 worker。判据见
    :mod:`frago.session.session_origin`；判不出来一律算人开的。"""

    parent_session_id: str | None = None
    """派活的那场会话。只有认得出来的 worker 才有值；人开的会话恒为空。

    左栏据此把 worker 折到派活的那一场下面。认不出父亲的 worker 仍是 worker，
    只是没地方可挂——界面另有一处收它们，NEVER 在这里编一个父亲出来。"""


def detect_family(session_id: str) -> RecordFamily:
    """判出这个会话编号属于哪一家。

    opencode 与 CoreAgent 靠形状就能分出来：它们的编号一律带前缀（``ses_`` / ``core_``），
    而 UUID 的字符集不含下划线，几套编号规则天生撞不上。CoreAgent 的记录形状虽然与
    Claude Code 一模一样，编号却是 frago 自己发的，所以这一眼不用落盘。

    **Claude Code 与 codex 分不开。** codex 的会话编号也是 UUID 形状
    （``01a01a98-82e9-7013-b24e-e5e91b03995a`` 是 UUIDv7），与 Claude Code 的编号空间
    重叠。所以从第三家起，判定不再是纯形状匹配：形状像 UUID 时先去 codex 的 rollout
    目录看一眼有没有这场会话，有就是 codex，没有才当 Claude Code。

    次序是"先查 codex、查不到才退回 Claude Code"，不是反过来：Claude Code 是历史默认，
    把它放在退路上，codex 没装 / 没有这场会话时行为与从前一模一样。这一眼的代价是
    一次目录 glob，而且 codex 的 ``sessions/`` 不存在时立刻返回，装了 codex 才有开销。

    形状都不像时抛 :class:`UnknownSessionFamily`，NEVER 默认当成 Claude Code——
    默认一家会让别家的编号被拿去翻 JSONL，翻出空的，看起来像会话没记录。
    """
    sid = session_id.strip()
    if sid.startswith(_OPENCODE_SESSION_PREFIX):
        return "opencode"
    if sid.startswith(coreagent_store.SESSION_ID_PREFIX):
        return "coreagent"
    if _UUID_SHAPE.match(sid):
        if _is_codex_session(sid):
            return "codex"
        return "claude-code"
    raise UnknownSessionFamily(f"会话编号 {session_id!r} 不属于已知的任何一家")


def _is_codex_session(session_id: str) -> bool:
    """codex 那边有没有这场会话。查不动一律当"没有"，NEVER 因此让判定失败。"""
    try:
        if not codex_store.sessions_root().is_dir():
            return False
        return codex_store.find_rollout(session_id) is not None
    except Exception:  # noqa: BLE001 — 判家族 NEVER 因为一次读盘失败而炸
        return False


def _ms(seconds: float | None) -> int | None:
    """秒 → 毫秒。``scan_sessions()`` 用的是 epoch 秒（浮点），统一记录一律毫秒整数。

    这里只做数值换算，不落 ``datetime``，因此不触碰项目的 naive local time 约定。
    """
    return None if seconds is None else int(seconds * 1000)


def _digests(status: SessionStatus, tail: TailSignals) -> tuple[str | None, str | None]:
    """摘要两格：已完成、卡在。

    **「要你做」那一格不做，留空。** 判不出来——会话停在等人输入时，末条记录就是 agent
    的回复，与已经答完在数据上一模一样。硬凑一格出来会把所有正常结束的会话都标成在等你。

    「卡在」只在状态为报错时给：那句话的出处就是那条报错记录。状态不是报错却挂一句"卡在
    某处"，等于凭空断言一件没有出处的事。
    """
    return tail.digest_done, (tail.error_message if status == "error" else None)


def _claude_cards(origins: OriginIndex) -> list[SessionCard]:
    """Claude Code 那一侧的会话卡片。

    标题按「人定的 > 模型起的 > CLI 分配的 > 开口第一句 > 会话编号」依次退让，取到
    第一个非空的就停。全空时用会话编号，NEVER 留空串——左栏一行没有字，人点不动它。

    字段来自 :mod:`frago.session.session_index`，不走 ``scan_sessions()``。后者为了凑齐
    清单要的这几样会把 2.7 GB 里每一行 JSON 都解析一遍，7 秒出头；而它同时还在服务
    ``/api/claude-sessions`` 背后那个 React 页面，那条路上的行为一个字都不能动。所以这里
    另起一条路径，两边各读各的。
    """
    cards: list[SessionCard] = []
    # "还在跑吗"取决于现在几点，所以这一步在每次列会话时算，NEVER 连同索引一起缓存。
    # 全清单共用同一个 ``now``，免得同一份数据里前后两张卡按不同的当下判定。
    now = time.time()
    for row in session_index.list_session_summaries():
        sid = row.sid
        if not sid:
            continue
        last_active = _ms(row.last_active_ts) or 0
        created = _ms(row.first_ts)
        status = derive_status(row.tail.last_kind, row.last_active_ts, now)
        digest_done, digest_stuck = _digests(status, row.tail)
        title = (
            row.custom_title
            or row.ai_title
            or row.slug
            # 开口第一句在清单里只露头 100 字，与 ``scan_sessions()`` 的 preview 同口径。
            or (row.first_user or "")[:100]
            or sid
        )
        cards.append(
            SessionCard(
                session_id=sid,
                family="claude-code",
                title=str(title),
                directory=str(row.cwd or ""),
                created_at=created if created is not None else last_active,
                last_active_at=last_active,
                last_reply_at=_ms(row.tail.last_reply_ts),
                # 子 agent 轨迹要翻完整场会话才数得出来，本机 1127 个文件全翻一遍是分钟
                # 量级。清单这一层不给，展开某一场时由记录本身的 ``agent_path`` 表达。
                agent_paths=[],
                status=status,
                digest_done=digest_done,
                digest_stuck=digest_stuck,
                origin=origins.origin_of(sid),
                parent_session_id=origins.parent_of(sid),
            )
        )
    return cards


def _coreagent_cards(origins: OriginIndex) -> list[SessionCard]:
    """CoreAgent 那一侧的会话卡片。

    字段全部走 Claude Code 那条路径——记录的形状就是那一套，只是根目录换成 CoreAgent
    自己的，索引也另存一份（两侧的文件混在同一份缓存里，删掉一侧会连带另一侧重算）。

    **标题先认发起方给的名字，再退回开口第一句。** 起 CoreAgent 的人可以在启动时命名
    （``frago-core --title``），名字写在记录里，与 Claude Code 给会话命名用的是同一种行。
    定时任务、待办拟稿这些由程序发起的会话都有名字——它们的开口第一句是一整段说明书，
    二十场摆在左栏长得一模一样。没有名字时才用开口第一句：那正是人交给它的那句任务。
    两样都没有时用会话编号，NEVER 留空串——左栏一行没有字，人点不动它。
    """
    now = time.time()
    cards: list[SessionCard] = []
    for row in session_index.list_session_summaries(
        coreagent_store.sessions_root(), session_index.COREAGENT_CACHE_FILE
    ):
        sid = row.sid
        if not sid:
            continue
        last_active = _ms(row.last_active_ts) or 0
        created = _ms(row.first_ts)
        status = derive_status(row.tail.last_kind, row.last_active_ts, now)
        digest_done, digest_stuck = _digests(status, row.tail)
        cards.append(
            SessionCard(
                session_id=sid,
                family="coreagent",
                title=row.ai_title or (row.first_user or "")[:100] or sid,
                directory=str(row.cwd or ""),
                created_at=created if created is not None else last_active,
                last_active_at=last_active,
                last_reply_at=_ms(row.tail.last_reply_ts),
                agent_paths=[],
                status=status,
                digest_done=digest_done,
                digest_stuck=digest_stuck,
                origin=origins.origin_of(sid),
                parent_session_id=origins.parent_of(sid),
            )
        )
    return cards


def _opencode_cards(origins: OriginIndex) -> list[SessionCard]:
    """opencode 那一侧的会话卡片。时刻本来就是毫秒，直接照抄。

    状态与摘要跟 Claude Code 那侧共用同一套判据（``session_index``），只是这一家的失效
    判据是会话行的 ``time_updated`` 而不是文件大小加修改时刻。
    """
    rows = opencode_store.list_sessions()
    tails = session_index.opencode_tail_signals(rows)
    now = time.time()
    cards: list[SessionCard] = []
    for row in rows:
        tail = tails.get(row.session_id, TailSignals())
        # 这一家的时刻是毫秒，判"还在跑吗"要换回秒——两家的口径必须一致，否则 opencode
        # 那侧会因为数值大了一千倍而永远判成刚刚活动过。
        status = derive_status(tail.last_kind, row.time_updated / 1000, now)
        digest_done, digest_stuck = _digests(status, tail)
        cards.append(
            SessionCard(
                session_id=row.session_id,
                family="opencode",
                title=row.title or row.session_id,
                directory=row.directory,
                created_at=row.time_created,
                last_active_at=row.time_updated,
                last_reply_at=_ms(tail.last_reply_ts),
                agent_paths=[],
                status=status,
                digest_done=digest_done,
                digest_stuck=digest_stuck,
                origin=origins.origin_of(row.session_id),
                parent_session_id=origins.parent_of(row.session_id),
            )
        )
    return cards


def _codex_cards(origins: OriginIndex) -> list[SessionCard]:
    """codex 那一侧的会话卡片。

    时刻的来源与另外两家不同：codex 不给会话存"最后更新时刻"这种字段，rollout 文件的
    修改时刻就是它。起始时刻取 ``session_meta`` 里的那个，取不到时退回修改时刻，
    NEVER 留 0——那会让这场会话在按时间排的清单里沉到最底下，等于宣布它不存在。

    标题只能取开口第一句：codex 既不让人给会话起名（``codex archive`` 的会话名是另一
    回事，绝大多数会话没有），也不让模型生成标题。第一句都取不到时用会话编号，NEVER
    留空串——左栏一行没有字，人点不动它。
    """
    metas = codex_store.list_sessions()
    entries = session_index.codex_tail_signals(metas)
    now = time.time()
    cards: list[SessionCard] = []
    for meta in metas:
        entry = entries.get(meta.session_id)
        tail = entry.tail if entry is not None else TailSignals()
        status = derive_status(tail.last_kind, meta.mtime, now)
        digest_done, digest_stuck = _digests(status, tail)
        last_active = int(meta.mtime * 1000)
        created = (
            int(meta.started_at.timestamp() * 1000) if meta.started_at is not None else last_active
        )
        cards.append(
            SessionCard(
                session_id=meta.session_id,
                family="codex",
                title=(entry.title if entry is not None else None) or meta.session_id,
                directory=meta.cwd,
                created_at=created,
                last_active_at=last_active,
                last_reply_at=_ms(tail.last_reply_ts),
                agent_paths=[],
                status=status,
                digest_done=digest_done,
                digest_stuck=digest_stuck,
                origin=origins.origin_of(meta.session_id),
                parent_session_id=origins.parent_of(meta.session_id),
            )
        )
    return cards


def sort_key(card: SessionCard) -> int:
    """清单按哪个时刻排：**最后一句 agent 回复**，取不到才退回文件最后动过的时刻。

    人在左栏找的是"最近哪场真的答了话"。而文件被动过的原因太多——hook 每拦一次工具写
    一条、模型每改一次标题写一条、模式切一次写一条，全都推进修改时刻却一句话都没说。
    照修改时刻排，一场只是被 hook 蹭过的老会话会压在真正刚答完话的会话上面。

    退回是明写的：取不到回复时刻的会话（整场没有 agent 回复、或末尾窗口里没翻到）用
    文件修改时刻，NEVER 把它们一律沉底——那等于宣布这些会话不存在。
    """
    return card.last_reply_at if card.last_reply_at is not None else card.last_active_at


def list_sessions() -> list[SessionCard]:
    """四家的会话合并成一份清单，按最后一句回复的时刻倒序（见 :func:`sort_key`）。

    一家读不出来（库不存在、目录不存在）不影响其余几家——各家的读取层各自把失败收敛成
    空列表，这里不做二次兜底，也 NEVER 因为一家没数据就整份返回空。

    出身索引（人开的 / frago 派的 worker、以及谁派的）取**一份**给各家共用：各取各的，
    同一批卡片会按两份数据判，界面上就会出现一场会话在这一刻是主干、下一刻是子项。
    """
    origins = session_origin.load_origin_index()
    cards = (
        _claude_cards(origins)
        + _opencode_cards(origins)
        + _codex_cards(origins)
        + _coreagent_cards(origins)
    )
    # 同刻时按会话编号定序，让同一份数据两次调用的结果一致。
    cards.sort(key=lambda card: (sort_key(card), card.session_id), reverse=True)
    return cards


def read_records(
    session_id: str,
    after: int = 0,
    limit: int = DEFAULT_LIMIT,
    tail: bool = False,
) -> list[UnifiedRecord]:
    """取这场会话从 ``after`` 起的统一记录，最多 ``limit`` 条。

    ``after`` 是**本批第一条的 ``seq``，闭区间起点**：``after=0`` 从头取，拿到的第一条
    ``seq`` 就是 0；下一批传上一批末条的 ``seq`` 加一。

    ``after`` 不是绝对下标——会话被重新解析后 ``seq`` 可能变，界面拿着过期的游标会错位，
    过期时从 0 重拉。

    ``tail=True`` 时忽略 ``after``，取整场**最后** ``limit`` 条。中栏打开会话要直接落在
    最新内容上；从头一页页翻到尾会把大会话整个塞进浏览器。

    ``limit`` 上限硬卡在 :data:`MAX_LIMIT`。分页是硬要求不是礼貌：单条工具结果见过 7.2
    万字符、单条用户消息见过 22 万字符，一次拉整场大会话会把浏览器打死。
    """
    family = detect_family(session_id)
    adapter = adapters.get_adapter(family)
    count = min(max(limit, 1), MAX_LIMIT)
    if tail:
        return adapter.to_unified(session_id, 0, count, tail=True)
    start = max(after, 0)
    return adapter.to_unified(session_id, start, count)


def read_raw(session_id: str, record_id: str) -> dict[str, Any] | None:
    """取单条记录的原文，取不到返回 None。

    **报错类记录恒返回 None。** 那条原文的响应头里带着 Cloudflare 的登录凭据，连入口
    都不给挂——这是安全约束不是可选项。两家的翻译层各自在自己那侧硬拦（Claude Code 侧
    查 ``is_raw_readable()``，opencode 侧认报错记录的编号后缀），服务层再拦一道回 403，
    三道都不能省。

    会话编号形状不认时抛 :class:`UnknownSessionFamily`，NEVER 猜一家试试——猜错会把另一
    家的编号拿去翻空档案，翻出 None，看起来像"这条记录不存在"。
    """
    family = detect_family(session_id)
    return adapters.get_adapter(family).read_raw(session_id, record_id)


class SessionDeleteUnsupported(RuntimeError):
    """这一家的会话还没有删除入口。

    眼下三家都有入口，这个异常在正常路径上抛不出来。它守的是**以后**：``detect_family``
    多加一家、而 ``delete_session`` 还没跟上时，落进别家的删法里比报错危险得多——删的
    东西不一样，出了事没人看得出是这里错的。
    """


class SessionFilesMissing(FileNotFoundError):
    """这场会话在本机的原始记录已经不在了。"""


@dataclass(frozen=True)
class DeletedSession:
    """一场会话删掉之后的如实交代。

    ``removed`` 与 ``problems`` 都是可以直接摆到界面上的人话：前者说删掉了哪几样，
    后者说哪一样没删干净。**"删没删成"不看这个结构**——删不成一律抛异常；能返回就
    说明主要目的（会话清单里不再有它）已经达成，``problems`` 只是收尾上的瑕疵。
    把一件已经做成的事说成没做成，人会以为要重来一遍。
    """

    session_id: str
    family: RecordFamily
    removed: list[str]
    problems: list[str] = field(default_factory=list)


def delete_session(session_id: str) -> DeletedSession:
    """删掉一场会话，让它从会话清单里消失。

    三种结局，调用方各说各话：

    - 编号不属于任何一家 → 抛 :class:`UnknownSessionFamily`；
    - 本机已经没有这场会话 → 抛 :class:`SessionFilesMissing`；
    - 引擎拒绝动手 → 抛 :class:`~frago.session.engine_cli.EngineCliFailed`。

    **四家走两种路。** Claude Code 与 CoreAgent 的记录就是一个 JSONL（外加 Claude Code
    那边的同名目录），位置稳定、格式公开，直接删干净。另两家借引擎自己的删除命令——不是
    偷懒，是因为它们的会话
    横跨多张表与多个库，对着别人的库手写 ``DELETE`` 只会留下看不见的残渣（详见
    :mod:`frago.session.engine_cli` 开头）。

    **删掉引擎侧那一场之后，顺手摘掉 frago 这边指着它的映射。** 映射的键是 frago 侧
    的编号、值是引擎侧的编号，驱动碰见失效映射会自己清，但那是下一次起会话时的事；
    在那之前，已删的会话仍以「已认领」的样子留在映射里。摘不干净不算删除失败，
    如实放进 ``problems``。

    **这不等于抹掉这场会话存在过。** 删的是引擎自己那份原始记录；frago 在
    ``~/.frago/sessions/`` 下另存的副本不跟着动，命令行检索仍找得到它。这一步只承诺
    一件事：会话清单里不再有它。
    """
    sid = session_id.strip()
    family = detect_family(sid)

    if family == "claude-code":
        files = claude_code_records.delete_session_files(sid)
        if files is None:
            raise SessionFilesMissing(f"本机已经找不到这场会话的原始记录了：{sid}")
        removed = [f"原始记录 {files.file}"]
        if files.directory_removed:
            removed.append(f"会话目录 {files.directory}")
        return DeletedSession(sid, family, removed, list(files.problems))

    if family == "coreagent":
        files = coreagent_store.delete_session_files(sid)
        if files is None:
            raise SessionFilesMissing(f"本机已经找不到这场 CoreAgent 会话的记录了：{sid}")
        return DeletedSession(sid, family, [f"会话记录 {files.file}"], list(files.problems))

    if family == "opencode":
        if not opencode_store.session_exists(sid):
            raise SessionFilesMissing(f"opencode 库里已经没有这场会话了：{sid}")
        output = opencode_store.delete_session(sid)
        dropped = _drop_pointing_bindings(sid, opencode_store.drop_bindings_pointing_at)
        return DeletedSession(sid, family, [output or "opencode 里的会话记录"], dropped)

    if family == "codex":
        if not codex_store.find_rollout(sid):
            raise SessionFilesMissing(f"codex 那边已经没有这场会话了：{sid}")
        output = codex_store.delete_session(sid)
        dropped = _drop_pointing_bindings(sid, codex_store.drop_bindings_pointing_at)
        return DeletedSession(sid, family, [output or "codex 里的会话记录"], dropped)

    # 三家都在上面各归各的。走到这里说明 `detect_family` 认出了一个本函数还不认识的家
    # ——NEVER 让它落进上面任何一条分支：拿别家的删法去删这一家，删的东西不一样，出了事
    # 没人看得出是这里错的。
    raise SessionDeleteUnsupported(f"{family} 的会话还没有删除入口")


def _drop_pointing_bindings(sid: str, drop: Callable[[str], list[str]]) -> list[str]:
    """摘掉指向这场会话的 frago 映射，回"没摘干净"的那句话（摘干净了就是空表）。

    摘不干净 NEVER 让整个删除失败：要的结果（清单里不再有它）已经达成。但也不能吞
    ——映射里留着一个永远匹配不上的编号，是下一次起会话时才发作的那种毛病。
    """
    try:
        dropped = drop(sid)
    except OSError as exc:
        return [f"frago 这边指向它的会话映射没摘掉：{exc}"]
    if dropped:
        logger.info("dropped %d binding(s) pointing at deleted session %s", len(dropped), sid)
    return []
