"""WarmSessionPool —— 常驻 tmux 会话池，兑现延迟收益。

冷启动只在每个会话一生付一次：同一 session_id 的后续消息直接送进活着的 TUI。
职责：按 session_id 保活与复用、LRU 驱逐、探测崩溃后重建。resume 恢复（把跨重启
的历史重新注入）由调用方在重建回调里提供，pool 只负责"何时该重建"。

**贯穿全模块的一条：活着的会话不杀。** 人在页面上发一句话，等的是这句话进到那场会话
里；每一次多余的 kill + resume 都是十几秒的白等，会话要是正干着活，那一轮的工具调用与
后台 worker 还会一起丢——而界面上看不出发生过这件事，人只觉得"它怎么从头开始了"。
三个杀点因此各有各的闸：

- **抢名**（内存池不认识、但同名 tmux 还在，服务重启后就是这个状态）：先问里面那个
  agent 还活着没有。活着就**接管**，一秒不花；只剩 shell 壳才清掉重建。
- **数量上限**：跳过正在干活的，也跳过调用方刚要到手的那一场；全都动不得时宁可暂时
  超编，等空闲巡检去收。
- **空闲巡检**（``evict_idle``）：判据本来就只认"最新一轮确已终结"，仍在干活的一律
  返回"判不出"、绝不回收。这一条一直是对的。
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime

from frago.agent_driver.driver import load_driver
from frago.agent_driver.tmux_session import (
    TmuxAgentSession,
    TmuxRunner,
    TurnResult,
)

logger = logging.getLogger(__name__)

# 会话重建时的可选回调：拿到刚开好的会话，注入跨重启需要恢复的历史/上下文。
ResumeHook = Callable[[TmuxAgentSession], None]


class WarmSessionPool:
    """保活一组常驻会话，按 session_id 复用。"""

    def __init__(
        self,
        *,
        max_size: int = 8,
        runner: TmuxRunner | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max_size = max_size
        self._runner = runner
        self._clock = clock
        # OrderedDict 充当 LRU：末尾为最近使用。
        self._sessions: OrderedDict[str, TmuxAgentSession] = OrderedDict()
        # 别名 → 池里的真实键。见 ``alias``。
        self._aliases: dict[str, str] = {}

    # ── 查询 ────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._sessions)

    def _key(self, session_id: str) -> str:
        """把可能是别名的编号翻成池里的真实键。不是别名就原样返回。"""
        return self._aliases.get(session_id, session_id)

    def alias(self, alias_id: str, session_id: str) -> bool:
        """让 ``alias_id`` 也指向池里 ``session_id`` 那一场。命中返回 True。

        给"编号是事后认领来的"那两家用（codex / opencode）：新建会话时 frago 只有
        自己 mint 的一个把手，agent 起来之后才分配真正的会话编号。这两个名字指的是
        **同一个 TUI**，池里 MUST 只有一份。

        不这样做的后果很具体：页面认到编号后紧接着再发一句话，池里查不到那个编号，
        于是又起一个 tmux 去 ``codex resume <同一个编号>``。codex 0.149 给每场会话上了
        单写者锁，第二次 resume 会在 TUI bootstrap 阶段直接失败退出（20260902 实测），
        这一轮就此报废——而失败屏上启动横幅还在，读屏差一点就把它当成一场活会话。

        别名**只登记不新建**：目标不在池里就什么都不做、返回 False。凭空造一条指向
        空处的别名，只会让下一次 acquire 拿着一个不存在的键去起会话。

        会话对象自己的 ``session_id`` 一个字都不改：driver 侧的认领映射
        （codex/opencode 的 binding）正是拿它当键，改了等于让 driver 重认一遍，
        两场会话的记录就此互串。
        """
        if session_id not in self._sessions or alias_id == session_id:
            return False
        self._aliases[alias_id] = session_id
        return True

    def has(self, session_id: str) -> bool:
        return self._key(session_id) in self._sessions

    def peek(self, session_id: str) -> TmuxAgentSession | None:
        """取一个已常驻的会话对象（不触发重建 / 不刷新 LRU）。无则 None。"""
        return self._sessions.get(self._key(session_id))

    def active_ids(self) -> list[str]:
        return list(self._sessions.keys())

    # ── 核心：取一个活会话（复用 / 重建 / 新建） ──────────────────────
    def acquire(
        self,
        agent_type: str,
        session_id: str,
        cwd: str,
        *,
        native_session_id: bool = False,
        conv_key: str | None = None,
        resume_hook: ResumeHook | None = None,
        env: dict[str, str] | None = None,
    ) -> TmuxAgentSession:
        # 别名先翻成真实键：认领来的原生编号与新建时那个把手指的是同一个 TUI，
        # 不翻的话这里会为同一场会话再起一个 tmux（见 ``alias``）。
        session_id = self._key(session_id)
        existing = self._sessions.get(session_id)
        if existing is not None:
            # 两问都要问：tmux 窗口在不在，以及里面那个 agent 还活着没有。只问前一个
            # 会把"agent 退了、只剩 shell 壳"当成活会话复用——话打进去落在 shell 提示符
            # 上，探针等不到任何东西，这一轮永久静默。
            #
            # 判据取 ``is not False``：只有**明确看见前台是 shell** 才丢弃。问不出来
            # （tmux 这一拍不答）当成还活着——这是一场本进程自己起、一直在驱动的会话，
            # 为一次瞬时查询失败把它杀了重建，正是要消灭的那种浪费。
            if existing.is_alive() and existing.has_live_agent() is not False:
                self._sessions.move_to_end(session_id)  # 标记最近使用
                return existing
            # 探测到崩溃 → 丢弃，走重建（可 resume 恢复）。
            del self._sessions[session_id]

        driver = load_driver(agent_type)
        session = TmuxAgentSession(
            session_id=session_id,
            driver=driver,
            cwd=cwd,
            native_session_id=native_session_id,
            conv_key=conv_key,
            runner=self._runner,
            env=env,
        )
        # 内存池不认识这场会话，但同名 tmux 会话可能还在——服务重启就是这个状态：
        # 池随进程没了，而 tmux 是独立守护进程，一场都不会跟着死。
        #
        # 这时**先问它里面那个 agent 还活着没有**，再决定接管还是重建：
        #
        # - 还活着 → **接管**。它就是这场会话本人（会话名由同一个编号派生），上下文
        #   原样在那个 TUI 里。杀掉再 ``--resume`` 得到的是同一段上下文，代价却是十几
        #   秒冷启动，而且它要是正干着活，那一轮的工具调用与后台 worker 一起丢——
        #   人只会看到"它怎么从头开始了"。健康的会话 NEVER 杀了重来。
        # - 只剩一个 shell 壳（agent 早退了）→ 清掉重建。直接 new-session 会撞名 exit 1，
        #   而那个壳里的上下文也确实不存在了。
        if session.is_alive():
            # 这里判据取 ``is True``：只有**明确看见 agent 还在跑**才接管。这一场不是
            # 本进程起的，问不出来就等于不知道那个窗口里现在是什么——宁可多花十几秒
            # 重建，也不能把用户的话打进一个没人接的窗口然后静默到超时。
            if session.has_live_agent() is True:
                self._adopt(session)
                self._sessions[session_id] = session
                self._sessions.move_to_end(session_id)
                self._evict_if_needed(protect=session_id)
                return session
            self._safe_close(session)
        session.open()
        if resume_hook is not None:
            resume_hook(session)
        self._sessions[session_id] = session
        self._sessions.move_to_end(session_id)
        self._evict_if_needed(protect=session_id)
        return session

    def run(
        self,
        prompt: str,
        *,
        agent_type: str,
        session_id: str,
        cwd: str,
        native_session_id: bool = False,
        conv_key: str | None = None,
        timeout_s: float | None = None,
        resume_hook: ResumeHook | None = None,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        """取活会话 → 投喂一轮；会话保活留待复用。

        ``timeout_s`` 缺省 None = 这一轮不设时间上限（见 ``TmuxAgentSession.send``）；
        调用方要墙钟上限就自己传一个正数。
        """
        session = self.acquire(
            agent_type,
            session_id,
            cwd,
            native_session_id=native_session_id,
            conv_key=conv_key,
            resume_hook=resume_hook,
            env=env,
        )
        return session.send(prompt, timeout_s=timeout_s)

    # ── 生命周期 ─────────────────────────────────────────────────────
    def evict(self, session_id: str) -> bool:
        """主动驱逐一个会话（kill tmux）。返回是否命中。

        指向它的别名一并清掉：留着的话，下一次 acquire 会拿这条别名去查一个已经不在
        池里的键，落到"翻不出来 → 原样当新会话"的路上，行为与没有别名时一致，但排查
        时会看见一张对不上号的映射表。
        """
        key = self._key(session_id)
        session = self._sessions.pop(key, None)
        if session is None:
            return False
        self._drop_aliases(key)
        self._safe_close(session)
        return True

    def _drop_aliases(self, session_id: str) -> None:
        for alias_id in [a for a, target in self._aliases.items() if target == session_id]:
            del self._aliases[alias_id]

    def evict_idle(
        self,
        idle_age_fn: Callable[[TmuxAgentSession], float | None],
        timeout_s: float,
    ) -> list[str]:
        """按空闲时长驱逐会话——叠加在数量 LRU 之上的时间维度回收。

        ``idle_age_fn(session)`` 返回该会话「自上次实质停顿以来的秒数」；返回 None
        表示无法判定空闲（仍在干活 / 无锚点），这类会话 NEVER 被回收。空闲秒数
        严格大于 ``timeout_s`` 才驱逐。返回被驱逐的 session_id 列表。
        """
        evicted: list[str] = []
        # 先快照再驱逐，避免在迭代中改字典。
        for session_id, session in list(self._sessions.items()):
            age = idle_age_fn(session)
            if age is not None and age > timeout_s and self.evict(session_id):
                evicted.append(session_id)
        return evicted

    def shutdown(self) -> None:
        """关闭全部会话。"""
        for session in self._sessions.values():
            self._safe_close(session)
        self._sessions.clear()
        self._aliases.clear()

    # ── 内部 ────────────────────────────────────────────────────────
    @staticmethod
    def _adopt(session: TmuxAgentSession) -> None:
        """接管一个还活着的孤儿会话：标活，并把输入框里的残留清掉。

        **清残留是接管的必要条件，不是顺手做的。** 这个 TUI 不是本进程起的，输入框里
        可能躺着上一个人打了一半没发出去的话（本机实测就有：某场会话的框里留着一整句
        待发的指令）。不清就打字，用户那句话会被这段陌生的残留顶在前面送出去——他看到
        的是自己没写过的内容，而且完全无从解释。

        清不干净不阻断接管：driver 没提供清空动作、或者清了确认不了，最坏是这一轮带上
        残留，比起把一个健康会话杀掉重来仍然是小得多的代价；两种情况都留一条日志。
        """
        session.status = "idle"
        session.adopted = True
        session.last_active_at = datetime.now(UTC)

        # 先看一眼输入框：空的就什么都不用做。清空动作本身要发键、打探针字符、再轮询
        # 确认重绘，最坏能耗掉好几秒——那是这条路上唯一新增的等待，只该花在真有残留的
        # 时候。会话正忙着的时候框本来就是空的，走的也是这条免费的路。
        try:
            if session.driver.ready_signal.matches(session.capture_pane()):
                return
        except Exception:
            # 读屏失败就当框里有东西，照常清一遍：多清一次是几百毫秒，漏清一次是把
            # 别人的半句话拼在用户消息前面发出去。
            logger.debug("could not read pane of %s before adopting", session.tmux_name)

        clear = session.driver.clear_input
        if clear is None:
            logger.info(
                "adopted orphan tmux session %s; driver %s cannot clear the input box",
                session.tmux_name,
                session.driver.agent_type,
            )
            return
        try:
            if not clear(session):
                logger.warning(
                    "adopted orphan tmux session %s but could not confirm the input box "
                    "is empty; this turn may carry leftover text",
                    session.tmux_name,
                )
        except Exception:
            logger.warning(
                "adopted orphan tmux session %s; clearing the input box failed",
                session.tmux_name,
                exc_info=True,
            )

    def _evict_if_needed(self, *, protect: str | None = None) -> None:
        """超出数量上限时按最久未用回收，**两类会话一个都不动**。

        一是 ``protect`` 指的那一场——调用方刚要到手、正要往里投喂的那一场。不排除它，
        在"其余的全都在忙"时会选中它本人：刚起好的会话当场被自己挤掉，调用方拿着一个
        已经被 kill 的把手去投喂。

        二是**正在干活的**。从前这里只看"谁最久没被碰过"：一场跑了二十分钟的长任务，
        期间人在页面上点开并发话给另外若干场会话，它就会被挤掉——那一轮的工具调用、
        后台起的 worker，连同还没落盘的产出一起没，而界面上看不出发生过这件事。

        两类都排除完还是超编就**宁可超着**：多留一个 tmux 进程的代价，远小于杀掉一个
        正在干活的会话。空闲巡检随后会把真正闲下来的收走。
        """
        while len(self._sessions) > self._max_size:
            victim = next(
                (
                    sid
                    for sid, s in self._sessions.items()
                    if sid != protect and s.status != "busy"
                ),
                None,
            )
            if victim is None:
                logger.info(
                    "warm pool over capacity (%d > %d): every other session is busy, "
                    "keeping them all until one finishes",
                    len(self._sessions),
                    self._max_size,
                )
                return
            old_session = self._sessions.pop(victim)
            self._drop_aliases(victim)
            self._safe_close(old_session)

    @staticmethod
    def _safe_close(session: TmuxAgentSession) -> None:
        with contextlib.suppress(Exception):
            session.close()
