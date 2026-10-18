"""让 vibe teaming 自己转起来的那条循环。

两侧的 agent 都不会主动去中继取信——agent 只在被说话时醒着。所以要有一个一直醒着
的东西替它取：这条循环每隔一段时间，把本机参加的每个 team 各跑一轮同步，取到的
消息直接投进对应的那场会话。

**为什么是服务端的一条循环，不是定时任务、也不是常驻命令。** 投递要驱动 tmux 里
那场会话，而那件事本来就是这台 frago 服务端在做；换成别的进程去做，等于在两个地方
各有一份「谁在驱动这场会话」的答案。而服务端本来就一直开着，team 这件事不该再多要
一个需要人记得启动的东西。

**两边一起用：长连接喊醒，定时兜底。** 每条长连接（``frago/team/live.py``）挂着中继，
对面一有动静中继就喊一声，这边立刻跑一轮——这是常路。十五秒那条照旧留着，管两件事：
长连接断了的时候它顶上来，以及本机自己这边的节奏（读会话新记录、推上去）。所以
**长连接压根没挂上也不影响能用**，只是慢回十五秒。

**没有 team 时它什么都不做，也不碰网络。** 本机没参加任何 team，循环空转，一条长
连接都不挂；这是常态，不是降级。

分层：服务层。可以 import ``session/``、``team/`` 与 ``agent_driver/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: 长连接喊醒之后，等这么久再跑。
#:
#: 对面连着推几条记录会连着喊好几声，而我们跑一轮就把它们都取回来了；不等一下，
#: 一次会话活跃能叫出十几轮同步，每一轮都是一串 HTTP。这个等待落在**已经跑起来的
#: 那个 task** 上，后面的通知看见它还在就直接返回（见 :meth:`TeamSyncService._sync_now`），
#: 所以它带来的最坏延迟只有这一下。
NOTICE_DEBOUNCE_SECONDS = 0.15

#: 本机会话尾部还有没推完的批次时，下一轮隔多久接着推。
#: 一轮 sync_once 最多连推 MAX_PUSH_ROUNDS 批；还没推完就隔 0.2 秒紧接着补下一轮，
#: 而不是干等 15 秒。
CATCHUP_INTERVAL_SECONDS = 0.2


class TeamSyncService:
    """替两侧的 agent 定时去中继取信、送信，并在对面有动静时立刻去取。"""

    _instance: TeamSyncService | None = None
    _lock = threading.Lock()

    #: 同一时刻只让一轮同步在读状态文件。
    #:
    #: 定时那一条和长连接喊醒的那一条跑在不同的工作线程上，而一轮同步要读会话记录、
    #: 要取信、要往状态文件里写游标。两轮同时跑同一个 team，会把游标和待送清单写回
    #: 去过——消息于是要么重复投递，要么再也投不进去。
    _sync_lock = threading.Lock()

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._links: dict[str, Any] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._inflight: set[str] = set()

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
        self._event_loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("vibe teaming 同步循环起来了")

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._close_links()
        logger.info("vibe teaming 同步循环停了")

    # ── 长连接 ──────────────────────────────────────────────────────────

    async def _refresh_links(self) -> None:
        """本机参加的每个 team 各挂一条长连接，退出的摘掉。

        读状态文件挪到线程里：它是磁盘上的一个文件，而这里在事件循环上，服务端
        的每一单请求都排在它后面。
        """
        from frago.team.live import TeamLiveLink
        from frago.team.state import load_state

        state = await asyncio.to_thread(load_state)
        active = state.active_teams() if state.relay.configured() else []

        wanted = set()
        for binding in active:
            wanted.add(binding.code)
            if binding.code in self._links:
                continue
            link = TeamLiveLink(
                state.relay.base(),
                binding.code,
                state.member,
                binding.secret,
                self._activity_note(binding.code),
            )
            link.start()
            self._links[binding.code] = link

        for code in list(self._links):
            if code not in wanted:
                self._links.pop(code).stop()

    def _close_links(self) -> None:
        for link in self._links.values():
            link.stop()
        self._links.clear()

    def _activity_note(self, code: str) -> Callable[[str], None]:
        """做一个「对面动了」的转交动作，交给那条长连接。

        它在长连接自己的线程里被叫，所以要跨回事件循环：跑一轮同步要读文件、还要往
        tmux 里打字，在收消息的线程上做会把后面的通知全堵在门外。
        """

        def note(action: str) -> None:
            loop = self._event_loop
            if loop is None or loop.is_closed():
                return
            logger.debug("team %s：对面动了（%s），立刻跑一轮", code, action)
            asyncio.run_coroutine_threadsafe(self._sync_now(code), loop)

        return note

    async def _sync_now(self, code: str) -> None:
        """对面动了，立刻给这个 team 跑一轮。

        同一个 team 上已经有一轮在跑时不排队：那一轮取的就是当下的东西，再跑一遍
        拿到的是同一份。
        """
        if code in self._inflight:
            return
        self._inflight.add(code)
        try:
            await asyncio.sleep(NOTICE_DEBOUNCE_SECONDS)
            while await asyncio.to_thread(self._round_one, code):
                await asyncio.sleep(CATCHUP_INTERVAL_SECONDS)
        except Exception as err:  # noqa: BLE001 — 一次即时同步失败，兜底那轮会补上
            logger.debug("team %s：被喊醒的这一轮没跑成：%s", code, err)
        finally:
            self._inflight.discard(code)
        await self._announce(code)

    @staticmethod
    async def _announce(code: str) -> None:
        """告诉开着的界面：这个 team 对面动了，右栏那份镜像该重取一次。

        「对面动了」也意味着右栏（对方会话的镜像）多半有新东西可看，而它原来只能
        每十五秒自己去问一次。这句推给浏览器，让它当场跟手；那条轮询照旧留着，
        长连接断了的时候它顶上。

        **推不出去不算错。** 没人在看结对页、界面没连上，都是常态——这条推送的
        全部意义是「快一点」，不是「送到」。
        """
        from frago.server.websocket import MessageType, create_message, manager

        try:
            await manager.broadcast(
                create_message(MessageType.TEAM_PEER_ACTIVITY, {"code": code})
            )
        except Exception:  # noqa: BLE001
            logger.debug("team %s：这声动静没能推给界面", code, exc_info=True)

    # ── 定时那一轮 ──────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        from frago.team.state import DEFAULT_INTERVAL_SECONDS

        while not self._stop_event.is_set():
            interval: int | float = DEFAULT_INTERVAL_SECONDS
            try:
                await self._refresh_links()
            except Exception as err:  # noqa: BLE001 — 长连接理不顺，轮询照跑
                logger.debug("vibe teaming：长连接这一趟没理好：%s", err)
            try:
                interval = await asyncio.to_thread(self._round)
            except Exception as err:  # noqa: BLE001 — 一轮失败不该让循环死掉
                logger.debug("vibe teaming 这一轮没跑成：%s", err)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                break
            except TimeoutError:
                continue

    @classmethod
    def _round(cls) -> int | float:
        """跑一轮，返回下一轮该隔多久（秒）。

        每个 team 各自成败，互不牵连：一个 team 的中继连不上，不该让另一个 team 停摆。
        若仍有未推完的尾部批次，返回极短间隔当场续推，不干等 15 秒。
        """
        from frago.team.state import load_state

        state = load_state()
        if not state.relay.configured():
            return max(state.interval_seconds, 30)
        active = state.active_teams()
        if not active:
            return max(state.interval_seconds, 30)

        has_more = False
        for binding in active:
            with cls._sync_lock:
                if _sync_one(state, binding):
                    has_more = True
        return CATCHUP_INTERVAL_SECONDS if has_more else state.interval_seconds

    @classmethod
    def _round_one(cls, code: str) -> bool:
        """只跑一个 team 的一轮。长连接喊醒时走这条；返回是否还有未推完的批次。"""
        from frago.team.state import load_state

        state = load_state()
        if not state.relay.configured():
            return False
        binding = state.teams.get(code)
        # 走到这儿时它可能已经被退掉了——退出与通知会撞上，退出的那个说了算。
        if binding is None or not binding.active:
            return False
        with cls._sync_lock:
            return _sync_one(state, binding)


def _sync_one(state: Any, binding: Any) -> bool:
    """一个 team 的一轮同步。成败自己扛，不往外抛；返回是否还有未推完的批次。"""
    from frago.team import sync as team_sync
    from frago.team.state import PUSH_TROUBLE_AFTER_ROUNDS

    try:
        outcome = team_sync.sync_once(state, binding, deliver_to(binding.session_id))
    except Exception as err:  # noqa: BLE001
        logger.debug("team %s 这一轮没跑成：%s", binding.code, err)
        return False
    if outcome.delivered or outcome.pushed or outcome.waiting:
        logger.info(
            "team %s：推了 %d 条记录，投了 %d 条消息%s%s",
            binding.code,
            outcome.pushed,
            outcome.delivered,
            f"，跳过重复 {outcome.skipped} 条" if outcome.skipped else "",
            f"，{outcome.waiting} 条等会话空闲再送" if outcome.waiting else "",
        )
    if outcome.note:
        # 偶尔没够着中继是常事，下一轮就补上；中继不收、或者连续一阵都不通，
        # 才值得一条警告。
        serious = (
            not binding.push_trouble_transient
            or binding.push_fail_rounds >= PUSH_TROUBLE_AFTER_ROUNDS
        )
        (logger.warning if serious else logger.info)("team %s：%s", binding.code, outcome.note)
    return bool(getattr(outcome, "has_more", False))


def deliver_to(session_id: str):
    """做一个「把这段话投进那场会话」的动作交给同步层。

    走 :func:`~frago.server.services.session_send.send_when_idle`：会话空闲才送，送完
    等它出现在记录里，最多等半分钟，**不等这一轮答完**——等一整轮会让同步循环被一场
    跑四十分钟的会话卡住，另一个 team 跟着一起停。会话在忙就这一轮不送，下一轮再问。

    从前走 ``send_queued``：不管会话忙不忙都往输入框里打字，指望界面自己排队。回车
    在忙的时候会被吞，字留在输入框里没人知道，见 ``send_when_idle`` 那段事故说明。
    """

    def deliver(prompt: str, landed) -> str:
        from frago.server.services import session_send

        return session_send.send_when_idle(session_id, prompt, landed=landed)

    return deliver
