"""让 vibe teaming 自己转起来的那条循环。

两侧的 agent 都不会主动去中继取信——agent 只在被说话时醒着。所以要有一个一直醒着
的东西替它取：这条循环每隔一段时间，把本机参加的每个 team 各跑一轮同步，取到的
消息直接投进对应的那场会话。

**为什么是服务端的一条循环，不是定时任务、也不是常驻命令。** 投递要驱动 tmux 里
那场会话，而那件事本来就是这台 frago 服务端在做；换成别的进程去做，等于在两个地方
各有一份「谁在驱动这场会话」的答案。而服务端本来就一直开着，team 这件事不该再多要
一个需要人记得启动的东西。

**没有 team 时它什么都不做，也不碰网络。** 本机没参加任何 team，循环空转；
这是常态，不是降级。

分层：服务层。可以 import ``session/``、``team/`` 与 ``agent_driver/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading

logger = logging.getLogger(__name__)


class TeamSyncService:
    """替两侧的 agent 定时去中继取信、送信。"""

    _instance: TeamSyncService | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @classmethod
    def get_instance(cls) -> TeamSyncService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("vibe teaming 同步循环起来了")

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("vibe teaming 同步循环停了")

    async def _loop(self) -> None:
        from frago.team.state import DEFAULT_INTERVAL_SECONDS

        while not self._stop_event.is_set():
            interval = DEFAULT_INTERVAL_SECONDS
            try:
                interval = await asyncio.to_thread(self._round)
            except Exception as err:  # noqa: BLE001 — 一轮失败不该让循环死掉
                logger.debug("vibe teaming 这一轮没跑成：%s", err)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                break
            except TimeoutError:
                continue

    @staticmethod
    def _round() -> int:
        """跑一轮，返回下一轮该隔多久（秒）。

        每个 team 各自成败，互不牵连：一个 team 的中继连不上，不该让另一个 team 停摆。
        """
        from frago.team import sync as team_sync
        from frago.team.state import PUSH_TROUBLE_AFTER_ROUNDS, load_state

        state = load_state()
        if not state.relay.configured():
            return max(state.interval_seconds, 30)
        active = state.active_teams()
        if not active:
            return max(state.interval_seconds, 30)

        for binding in active:
            try:
                outcome = team_sync.sync_once(
                    state, binding, _deliver_to(binding.session_id)
                )
            except Exception as err:  # noqa: BLE001
                logger.debug("team %s 这一轮没跑成：%s", binding.code, err)
                continue
            if outcome.delivered or outcome.pushed:
                logger.info(
                    "team %s：推了 %d 条记录，投了 %d 条消息%s",
                    binding.code,
                    outcome.pushed,
                    outcome.delivered,
                    f"，跳过重复 {outcome.skipped} 条" if outcome.skipped else "",
                )
            if outcome.note:
                # 偶尔没够着中继是常事，下一轮就补上；中继不收、或者连续一阵都不通，
                # 才值得一条警告。
                serious = (not binding.push_trouble_transient
                           or binding.push_fail_rounds >= PUSH_TROUBLE_AFTER_ROUNDS)
                (logger.warning if serious else logger.info)(
                    "team %s：%s", binding.code, outcome.note
                )

        return state.interval_seconds


def _deliver_to(session_id: str):
    """做一个「把这段话投进那场会话」的动作交给同步层。

    用 :func:`~frago.server.services.session_send.send_queued` 而不是 ``send``：
    那场会话这一轮可能还在跑，而 agent 的界面本来就会把干活期间到达的话排队，等这
    一轮停下来接着处理。在这里等一整轮结束，会让同步循环被一场跑四十分钟的会话卡住，
    另一个 team 跟着一起停。
    """

    def deliver(prompt: str) -> None:
        from frago.server.services import session_send

        session_send.send_queued(session_id, prompt)

    return deliver
