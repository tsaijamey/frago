"""长跑会话的看护：没人看页面时也该有摘要，静默太久该出声。

盯四件事：

1. 还开着、屏上还在干活、且静默过了线的，推且只推一条；
2. **闲着等人的那些一声不出**——一场等人打字的会话安静半个钟头是正常的；
3. 已经不在跑的不推，而且它那两笔记账要清掉；
4. 按节拍投旁路观察，别每一趟都投。

不碰真的 tmux、真的常驻进程和真的系统通知：会话清单、判活着、判忙、投观察、推通知
全换成替身，钟也是假的。
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

from frago.server.services import session_watchdog as wd
from frago.session.record_reader import SessionCard

#: 假钟的起点。卡片上的时刻和看护眼里的「现在」都从它算，两边才在同一个时间轴上。
NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def fresh_watchdog():
    """看护是单例，上一场留下的替身与记账会串到下一场。"""
    wd.reset_watchdog()
    yield
    wd.reset_watchdog()


def card(
    session_id: str = "core_silent",
    *,
    family: str = "coreagent",
    quiet_s: float = 45 * 60,
    title: str = "整理 agent-failure-modes",
    **extra,
) -> SessionCard:
    """一张「最后动于 quiet_s 秒前」的会话卡片。"""
    return SessionCard(
        session_id=session_id,
        family=family,  # type: ignore[arg-type]
        title=title,
        directory="/tmp",
        created_at=int((NOW - 86400) * 1000),
        last_active_at=int((NOW - quiet_s) * 1000),
        **extra,
    )


class Rig:
    """一套替身，外加那口假钟。"""

    def __init__(self, *cards: SessionCard, alive: bool = True, busy: bool = True) -> None:
        self.cards = list(cards)
        self.alive = alive
        self.busy = busy
        self.observed: list[str] = []
        self.notices: list[str] = []
        self.now = NOW

    def live(self) -> dict[str, bool]:
        """还开着的那些 → 忙不忙，与当家的一次给全同一个形状。"""
        return {c.session_id: self.busy for c in self.cards} if self.alive else {}

    def watchdog(self) -> wd.SessionWatchdog:
        return wd.SessionWatchdog(
            cards=lambda: self.cards,
            live=self.live,
            observe=self.observed.append,
            notify=lambda text: self.notices.append(text) or {"status": "ok"},
            now=lambda: self.now,
        )

    def tick(self, seconds: float) -> None:
        self.now += seconds


def test_a_session_quiet_past_the_line_pushes_one_notice():
    rig = Rig(card(quiet_s=34 * 60))
    done = rig.watchdog().sweep()

    assert [d["did"] for d in done] == ["observe", "notify"]
    assert len(rig.notices) == 1
    text = rig.notices[0]
    assert "整理 agent-failure-modes" in text, text
    assert "34 分钟" in text, text
    assert "结束运行" in text, "要告诉人怎么办，不只是报告一声"


def test_a_session_quiet_but_idle_says_nothing():
    """屏上没在干活 = 等人打下一句话。那不是卡住，不该吵人。"""
    rig = Rig(card(quiet_s=3 * 60 * 60), busy=False)
    assert rig.watchdog().sweep() == []
    assert rig.notices == []
    assert rig.observed == [], "闲着的不必按节拍投观察"


def test_a_session_that_is_gone_says_nothing():
    rig = Rig(card(quiet_s=3 * 60 * 60), alive=False)
    assert rig.watchdog().sweep() == []
    assert rig.notices == []


def test_the_same_session_is_not_announced_again_within_the_hour():
    rig = Rig(card(quiet_s=40 * 60))
    dog = rig.watchdog()

    dog.sweep()
    rig.tick(10 * 60)
    dog.sweep()

    assert len(rig.notices) == 1, "卡住的会话不会自己好，但每十分钟喊一遍只会让人不再看"


def test_an_hour_later_it_speaks_up_again():
    rig = Rig(card(quiet_s=40 * 60))
    dog = rig.watchdog()

    dog.sweep()
    rig.tick(wd.REPEAT_AFTER_S + 60)
    dog.sweep()

    assert len(rig.notices) == 2, "还卡着就该再提一次，不然这一声等于没响"


def test_a_long_run_nobody_watches_is_still_observed_on_a_cadence():
    rig = Rig(card(quiet_s=60))
    dog = rig.watchdog()

    dog.sweep()
    assert rig.observed == ["core_silent"], "第一趟就该投一次，不必等人打开页面"

    rig.tick(60)
    dog.sweep()
    assert rig.observed == ["core_silent"], "离上一趟不满节拍就不投"

    rig.tick(wd.OBSERVE_EVERY_S)
    dog.sweep()
    assert rig.observed == ["core_silent", "core_silent"]


def test_a_notice_that_cannot_be_delivered_does_not_stop_the_sweep():
    rig = Rig(card("core_a", quiet_s=40 * 60), card("core_b", quiet_s=40 * 60))

    def boom(_text: str):
        raise OSError("没有可用的系统通知命令")

    dog = wd.SessionWatchdog(
        cards=lambda: rig.cards,
        live=rig.live,
        observe=rig.observed.append,
        notify=boom,
        now=lambda: rig.now,
    )

    done = dog.sweep()

    notified = [d["session_id"] for d in done if d["did"] == "notify"]
    assert notified == ["core_a", "core_b"], "一场推不出去不该把后面那场也带掉"
    assert all(d["result"]["status"] == "error" for d in done if d["did"] == "notify")


def test_the_notice_quotes_what_the_run_last_landed():
    rig = Rig(card(quiet_s=50 * 60, digest_done="量出索引 41145 字符"))
    rig.watchdog().sweep()
    assert "量出索引 41145 字符" in rig.notices[0]


# ── 接线 ────────────────────────────────────────────────────────────────────
#
# 上面各条盯的是判据本身。下面两条盯的是它真的挂在服务上：默认那条通知走的是定时任务
# 同一条出站路，调度循环会自己把它叫起来——不然再准的判据也只是躺着的一段代码。


def test_the_default_notice_goes_out_through_the_scheduler_channel(monkeypatch):
    sent: list[tuple[dict, str]] = []
    from frago.server.services import schedule_executor as ex

    def fake_deliver(schedule, text):
        sent.append((schedule, text))
        return {"status": "ok"}

    monkeypatch.setattr(ex, "deliver", fake_deliver)

    wd._notify("「X」静默 34 分钟了")

    assert sent, "默认落点要真的推出去"
    schedule, text = sent[0]
    assert text == "「X」静默 34 分钟了"
    # 不带 notify 段 = 与定时任务同一个默认落点（没配 channel 就落本机通知）。
    assert not schedule.get("notify")
    assert "看护" in schedule["name"]


def _run_loop_once(monkeypatch) -> None:
    """把调度循环跑起来，等它走完第一跳再收掉。"""
    from frago.server.services import scheduler_service as ss

    monkeypatch.setattr(ss, "INITIAL_DELAY_S", 0.01)
    monkeypatch.setattr(ss, "TICK_INTERVAL", 0.01)
    # 不读真的 ~/.frago/schedules.json：这一条只问循环有没有把看护叫起来。
    monkeypatch.setattr(ss.SchedulerService, "_load", lambda self: setattr(self, "_schedules", []))

    async def go() -> None:
        svc = ss.SchedulerService()
        svc._schedules_path = Path("/nonexistent/schedules.json")
        task = asyncio.create_task(svc._loop())
        await asyncio.sleep(0.2)
        svc._stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    asyncio.run(go())


def test_the_scheduler_loop_calls_the_watchdog(monkeypatch):
    """调度循环会按节拍自己把看护叫起来。"""
    swept: list[str] = []
    monkeypatch.setattr(wd.SessionWatchdog, "sweep", lambda self: swept.append("swept") or [])

    _run_loop_once(monkeypatch)

    assert swept, "调度循环没把看护叫起来，这条判据就是躺着的一段代码"


def test_the_scheduler_loop_calls_the_real_watchdog(monkeypatch):
    """上一条把 ``sweep`` 换成了替身——这一条换成替身的是它最外面那两层（谁在跑、推给
    谁），确认循环叫的确实是看护本人，而不是替身拦住了别的东西。"""
    touched: list[str] = []

    def fake_live() -> dict[str, bool]:
        touched.append("asked")
        return {}

    monkeypatch.setattr(wd, "_cards", lambda: [card()])
    monkeypatch.setattr(wd, "_live", fake_live)

    _run_loop_once(monkeypatch)

    assert touched == ["asked"], "循环叫的应该是看护本人"
