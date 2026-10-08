"""长跑会话的看护：没人看也要有摘要，静默太久要出声。

语料里 29 次旁路观察全部由「打开会话页」触发，122 场里 101 场从没人打开过、一份摘要
都没有；core_f61ea0541c594 静默 48.1 分钟、core_179d37cd74cb4 静默 99.3 分钟，这期间
没人知道它在干什么，人在两处被迫主动追问，分别等了 79 分钟与 2 小时 49 分。

这里补两件事，按同一个节拍跑，都不看有没有人开着页面：

1. **按节拍投一次旁路观察**（``OBSERVE_EVERY_S`` 一次）——右栏的槽位与摘要不再只是
   「有人打开页面」的副产品，长跑会话自己也会攒出摘要来；
2. **静默太久推一条通知**（``SILENT_AFTER_S`` 内一条新记录都没有）——人那时多半不在
   页面前，等的正是这一声。

**只管还开着、且屏上还在干活的那些。** 闲着的不算：一场等人打字的会话安静半个钟头是
正常的，一场正在跑却半个钟头没有新记录的才是卡住了。谁在跑、忙不忙都向各自的当家问
（CoreAgent 问常驻进程那条路，tmux 那几家问 tmux 本人），这里不自己推——会话卡片上那
个「在跑」是从记录文件推出来的，拿它当判据会把昨天那场也算成活着。

通知走 :func:`~frago.server.services.schedule_executor.deliver`，与定时任务同一条出站路
（没配 channel 时落到本机系统通知）。同一条通知至少隔 ``REPEAT_AFTER_S`` 才再发一次：
卡住的会话不会自己好，但每五分钟喊一遍只会把人练到不去看。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

#: 静默多久算卡住（秒）。
SILENT_AFTER_S = 30 * 60
#: 同一场会话两条通知之间至少隔多久（秒）。
REPEAT_AFTER_S = 60 * 60
#: 长跑会话没人看时，隔多久投一次旁路观察（秒）。
OBSERVE_EVERY_S = 10 * 60


def _minutes(seconds: float) -> str:
    total = int(seconds // 60)
    if total < 60:
        return f"{total} 分钟"
    hours, rest = divmod(total, 60)
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"


def silent_text(card: Any, quiet_s: float) -> str:
    """推给那个人的那段话。说清楚是哪一场、多久没动静、最后落下的是什么。"""
    when = datetime.fromtimestamp(card.last_active_at / 1000).strftime("%H:%M")
    name = card.title or card.session_id
    lines = [
        f"「{name}」已经 {_minutes(quiet_s)} 没有新记录了（最后一条在 {when}），"
        f"但它还开着、屏上还在干活——多半是卡住了。",
    ]
    last = card.digest_stuck or card.digest_done
    if last:
        lines.append(f"它最后留下的是：{last}")
    lines.append("去会话页看一眼，或者在那一场上按「结束运行」。")
    return "\n".join(lines)


def _live() -> dict[str, bool]:
    """此刻还开着的每一场 → 屏上忙不忙。

    **一趟只问两家当家的一次**，不逐张卡片去问：本机三千多张卡片，逐张问一次 tmux 要
    两分多钟，而按这个节拍这一趟每五分钟就要走一次。两家的「还开着」都是它们自己此刻的
    样子——CoreAgent 问常驻进程那条路，其余的问 tmux 本人，都不看卡片。
    """
    from frago.server.services import coreagent_runner, tmux_sessions_service

    live = coreagent_runner.live_states()
    for row in tmux_sessions_service.list_sessions():
        if row.session_id:
            live[row.session_id] = bool(row.busy)
    return live


def _observe(session_id: str) -> None:
    from frago.server.services.session_observer import CADENCE, get_observer

    get_observer().notify(session_id, CADENCE)


def _notify(text: str) -> dict[str, Any]:
    from frago.server.services import schedule_executor as ex

    return ex.deliver({"name": "长跑会话看护"}, text)


class SessionWatchdog:
    """按节拍看一遍还开着的会话。

    依赖全可以从外面换（会话清单、此刻谁还开着且忙不忙、投观察、推通知、此刻几点了），
    测试靠它们不碰真的 tmux、真的常驻进程和真的系统通知。
    """

    def __init__(
        self,
        *,
        cards: Callable[[], list[Any]] | None = None,
        live: Callable[[], dict[str, bool]] | None = None,
        observe: Callable[[str], None] | None = None,
        notify: Callable[[str], dict[str, Any]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._cards = cards or _cards
        self._live = live or _live
        self._observe = observe or _observe
        self._notify = notify or _notify
        self._now = now
        self._observed_at: dict[str, float] = {}
        self._notified_at: dict[str, float] = {}

    def sweep(self) -> list[dict[str, Any]]:
        """走一趟，返回这一趟干了什么。测试直接看它。"""
        done: list[dict[str, Any]] = []
        now = self._now()
        live = self._live()
        for card in self._cards():
            sid = card.session_id
            if sid not in live:
                # 不在跑了就把两笔账清掉，免得编号再被用上时带着上一场的时刻。
                self._observed_at.pop(sid, None)
                self._notified_at.pop(sid, None)
                continue
            if not live[sid]:
                continue
            if now - self._observed_at.get(sid, 0.0) >= OBSERVE_EVERY_S:
                self._observed_at[sid] = now
                try:
                    self._observe(sid)
                    done.append({"session_id": sid, "did": "observe"})
                except Exception:  # noqa: BLE001 — 投不进去不该拖住这一趟
                    logger.exception("watchdog: 投观察失败 (session=%s)", sid)

            quiet = now - card.last_active_at / 1000
            if quiet < SILENT_AFTER_S:
                continue
            if now - self._notified_at.get(sid, 0.0) < REPEAT_AFTER_S:
                continue
            text = silent_text(card, quiet)
            self._notified_at[sid] = now
            try:
                result = self._notify(text)
            except Exception as e:  # noqa: BLE001 — 推不出去是可惜，不是这一趟的失败
                logger.exception("watchdog: 推通知失败 (session=%s)", sid)
                result = {"status": "error", "error": str(e)}
            logger.warning(
                "[watchdog] %s 静默 %s，已通知（%s）", sid, _minutes(quiet), result.get("status")
            )
            done.append({
                "session_id": sid,
                "did": "notify",
                "quiet_s": int(quiet),
                "text": text,
                "result": result,
            })
        return done


def _cards() -> list[Any]:
    from frago.session import record_reader

    return record_reader.list_sessions()


_watchdog: SessionWatchdog | None = None


def get_watchdog() -> SessionWatchdog:
    global _watchdog
    if _watchdog is None:
        _watchdog = SessionWatchdog()
    return _watchdog


def reset_watchdog() -> None:
    """测试用：把那份记账清掉。"""
    global _watchdog
    _watchdog = None
