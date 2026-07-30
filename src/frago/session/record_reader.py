"""会话记录的统一入口（spec 20260729-session-workbench-webui Phase 1）。

服务层只跟这个模块打交道：要清单叫 :func:`list_sessions`，要记录叫
:func:`read_records`，要原文叫 :func:`read_raw`。哪一家、怎么翻，全在这一层里判完，
上面不需要知道 Claude Code 的记录躺在 JSONL 里而 opencode 的在 SQLite 里。

哪一家的翻译层由 :mod:`frago.session.adapters` 的注册表给出，这里不写 if/else——以后
再接第三个 CLI，只要它登记进注册表，这个模块一个字不用改。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from frago.session import adapters, opencode_store, session_index
from frago.session.session_index import SessionStatus, TailSignals, derive_status
from frago.session.unified_record import RecordFamily, UnifiedRecord

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "SessionCard",
    "UnknownSessionFamily",
    "detect_family",
    "list_sessions",
    "read_raw",
    "read_records",
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
    """毫秒时间戳。清单按它倒序。"""

    agent_paths: list[str] = field(default_factory=list)
    """这场会话下出现过的子 agent 轨迹。主会话一条也没有时是 ``[]``。"""

    status: SessionStatus = "idle"
    """四档之一。判定顺序见 :func:`~frago.session.session_index.derive_status`。"""

    digest_done: str | None = None
    """最近一件确定做完的事：末尾最近那条 agent 回复的头一行。没有就留空。"""

    digest_stuck: str | None = None
    """当前阻塞点：状态为报错时那条报错的消息。其余情况恒为空。"""


def detect_family(session_id: str) -> RecordFamily:
    """按会话编号的形状判出属于哪一家。

    判据是编号本身的形状，不落盘查一遍。两家的编号空间实测完全不相交：本机
    1121 个 Claude Code 会话文件，编号全部是 UUID 形状；opencode 库里 33 场会话，
    编号全部带 ``ses_`` 前缀；两边求交集为 0 条。UUID 的字符集不含下划线，
    ``ses_`` 前缀的编号也永远凑不出 UUID 的分段形状，所以这不是"目前没撞上"，
    是两套编号规则天生撞不上。

    形状都不像时抛 :class:`UnknownSessionFamily`，NEVER 默认当成 Claude Code——
    默认一家会让 opencode 那侧的编号被拿去翻 JSONL，翻出空的，看起来像会话没记录。
    """
    sid = session_id.strip()
    if sid.startswith(_OPENCODE_SESSION_PREFIX):
        return "opencode"
    if _UUID_SHAPE.match(sid):
        return "claude-code"
    raise UnknownSessionFamily(f"会话编号 {session_id!r} 不属于已知的任何一家")


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


def _claude_cards() -> list[SessionCard]:
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
                # 子 agent 轨迹要翻完整场会话才数得出来，本机 1127 个文件全翻一遍是分钟
                # 量级。清单这一层不给，展开某一场时由记录本身的 ``agent_path`` 表达。
                agent_paths=[],
                status=status,
                digest_done=digest_done,
                digest_stuck=digest_stuck,
            )
        )
    return cards


def _opencode_cards() -> list[SessionCard]:
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
                agent_paths=[],
                status=status,
                digest_done=digest_done,
                digest_stuck=digest_stuck,
            )
        )
    return cards


def list_sessions() -> list[SessionCard]:
    """两家的会话合并成一份清单，按最后活动时刻倒序。

    一家读不出来（库不存在、目录不存在）不影响另一家——两家的读取层各自把失败收敛成
    空列表，这里不做二次兜底，也 NEVER 因为一家没数据就整份返回空。
    """
    cards = _claude_cards() + _opencode_cards()
    # 同刻时按会话编号定序，让同一份数据两次调用的结果一致。
    cards.sort(key=lambda card: (card.last_active_at, card.session_id), reverse=True)
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
