"""本机 agent 会话进程的清点：tmux 里的 CLI agent + 不走 tmux 的 CoreAgent。

**浮窗管的是「所有 agent 会话进程」，tmux 只是其中一类 CLI agent 的承载方式。**
早先这个入口只问 tmux，于是两件事对不上：CoreAgent 没有终端、根本不在清单里，人
在页面上开着的它，到这个本该管它的地方反而看不见。本模块补的就是这一缺口——把
``tmux_sessions_service`` 那一份和 ``coreagent_runner`` 的常驻进程合成一份清单。

**两边的字段口径保持一致，界面才不必为来源分叉。** 闲置时长都是「自最后一次把话
说完起」；CoreAgent 那边取常驻进程收到上一轮 result 的时刻（``touched_at``），
与 tmux 那行取记录里最后一个终结时刻是同一件事。内存都按进程树算。
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from frago.server.services import coreagent_runner
from frago.server.services import tmux_sessions_service as tsvc
from frago.session import record_reader

logger = logging.getLogger(__name__)


def list_sessions(*, excerpt_chars: int = tsvc.DEFAULT_EXCERPT_CHARS) -> list[dict[str, Any]]:
    """本机此刻全部 agent 会话进程，按闲置由久到近排。

    每一行都带 ``kind``：``tmux`` 的那几行可以关闭，``coreagent`` 的那几行只能打开
    ——停掉 CoreAgent 是「结束这一轮」而不是「销毁这场会话」，与浮窗的关闭不是同一
    个动作，不放在同一颗按钮下。
    """
    core_rows = _coreagent_rows(excerpt_chars)
    core_sids = {r["session_id"] for r in core_rows if r.get("session_id")}
    core_tmux_names = {r.get("tmux_name") for r in core_rows if r.get("tmux_name")}
    tmux_rows = [
        {**asdict(row), "kind": "tmux", "state": None, "directory": None}
        for row in tsvc.list_sessions(excerpt_chars=excerpt_chars)
        if row.session_id not in core_sids and row.name not in core_tmux_names
    ]
    rows = tmux_rows + core_rows
    rows.sort(key=lambda r: (r["idle_secs"] is None, -float(r["idle_secs"] or 0.0)))
    return rows


def count_sessions() -> dict:
    """只要个数和内存，不读任何记录——左下角那个数字每分钟问一次。

    CoreAgent 的常驻进程也算进来。若某场 CoreAgent 已跑在 tmux 窗格里，``tsvc.count_sessions()``
    已经把它算进去了，这里只补算没挂在 tmux 里的那几场，避免重复计数。
    """
    tmux = tsvc.count_sessions()
    live = coreagent_runner.live_snapshot()
    if not live:
        return tmux
    open_names = tsvc.open_session_names()
    uncounted = [
        s for s in live if not getattr(s, "tmux_name", None) or s.tmux_name not in open_names
    ]
    if not uncounted:
        return tmux
    mem = tsvc.memory_by_pid()
    return {
        "total": tmux["total"] + len(uncounted),
        "total_memory_mb": tmux["total_memory_mb"]
        + sum(mem.get(s.pid, 0) for s in uncounted if s.pid is not None),
    }


def _coreagent_rows(excerpt_chars: int) -> list[dict[str, Any]]:
    """还开着进程的 CoreAgent 会话，一行一场。

    标题与正文来自会话索引（与左栏同源），进程号、状态、最近动静来自常驻进程自己
    的登记处。索引里还没有这一场时（刚起、还没写记录）退回登记处给的名字——不能
    因为记录晚到一步就让这一场从清单里消失。
    """
    live = coreagent_runner.live_snapshot()
    if not live:
        return []

    try:
        cards = {
            card.session_id: card
            for card in record_reader.list_sessions()
            if card.family == "coreagent"
        }
    except Exception as e:  # noqa: BLE001 — 索引读坏不该让常驻进程从清单里消失
        # 标题和正文退回登记处给的名字：这一行进得来，人才知道有一场 CoreAgent 在跑。
        logger.warning("读取 CoreAgent 会话索引失败，退回进程登记处的名字：%s", e)
        cards = {}
    mem = tsvc.memory_by_pid()
    now = time.time()
    rows: list[dict[str, Any]] = []
    for snap in live:
        card = cards.get(snap.session_id)
        digest = ""
        if card is not None:
            digest = card.digest_stuck or card.digest_done or ""
        rows.append(
            {
                # ``name`` 在清单里是唯一把手。CoreAgent 没有 tmux 名，用会话编号；
                # 前端按 ``kind`` 决定这颗把手能做什么，不会把它当 tmux 名去 kill。
                "name": snap.session_id,
                "label": (card.title if card is not None else None) or snap.title or snap.session_id,
                "session_id": snap.session_id,
                "stop_reason": None,
                "last_stop_at": datetime.fromtimestamp(snap.touched_at, tz=UTC).isoformat(),
                "idle_secs": max(0.0, now - snap.touched_at),
                "excerpt": digest[:excerpt_chars],
                "memory_mb": mem.get(snap.pid, 0) if snap.pid is not None else 0,
                # starting 也算在干活：它正在把这一场拉起来，此刻停掉等于半途撤火。
                "busy": snap.state in ("starting", "busy"),
                "managed": False,
                "client_alive": True,
                "awaiting_input": snap.state == "idle",
                "closing_text": "",
                "kind": "coreagent",
                "state": snap.state,
                "directory": (card.directory if card is not None else "") or snap.cwd,
                "tmux_name": getattr(snap, "tmux_name", None),
            }
        )
    return rows


__all__ = [
    "count_sessions",
    "list_sessions",
]
