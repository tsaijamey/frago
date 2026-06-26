"""WarmSessionPool —— 常驻 tmux 会话池，兑现延迟收益。

冷启动只在每个会话一生付一次：同一 session_id 的后续消息直接送进活着的 TUI。
职责：按 session_id 保活与复用、LRU 驱逐、探测崩溃后重建。resume 恢复（把跨重启
的历史重新注入）由调用方在重建回调里提供，pool 只负责"何时该重建"。
"""

from __future__ import annotations

import contextlib
import time
from collections import OrderedDict
from collections.abc import Callable

from frago.agent_driver.driver import load_driver
from frago.agent_driver.tmux_session import (
    TmuxAgentSession,
    TmuxRunner,
    TurnResult,
)

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

    # ── 查询 ────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._sessions)

    def has(self, session_id: str) -> bool:
        return session_id in self._sessions

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
        resume_hook: ResumeHook | None = None,
    ) -> TmuxAgentSession:
        existing = self._sessions.get(session_id)
        if existing is not None:
            if existing.is_alive():
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
            runner=self._runner,
        )
        # 重启后内存池为空，但同名 tmux 会话可能作为孤儿仍存活；直接 new-session
        # 会撞名 exit 1。先探测：存在则 kill 掉，保证 open() 能干净重建并重新注入
        # bootstrap（孤儿会话的 claude TUI 上下文已不可信，复用反而错乱）。
        if session.is_alive():
            self._safe_close(session)
        session.open()
        if resume_hook is not None:
            resume_hook(session)
        self._sessions[session_id] = session
        self._sessions.move_to_end(session_id)
        self._evict_if_needed()
        return session

    def run(
        self,
        prompt: str,
        *,
        agent_type: str,
        session_id: str,
        cwd: str,
        native_session_id: bool = False,
        timeout_s: float = 120.0,
        resume_hook: ResumeHook | None = None,
    ) -> TurnResult:
        """取活会话 → 投喂一轮；会话保活留待复用。"""
        session = self.acquire(
            agent_type,
            session_id,
            cwd,
            native_session_id=native_session_id,
            resume_hook=resume_hook,
        )
        return session.send(prompt, timeout_s=timeout_s)

    # ── 生命周期 ─────────────────────────────────────────────────────
    def evict(self, session_id: str) -> bool:
        """主动驱逐一个会话（kill tmux）。返回是否命中。"""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        self._safe_close(session)
        return True

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

    # ── 内部 ────────────────────────────────────────────────────────
    def _evict_if_needed(self) -> None:
        while len(self._sessions) > self._max_size:
            # OrderedDict 头部即最久未用。
            old_id, old_session = next(iter(self._sessions.items()))
            del self._sessions[old_id]
            self._safe_close(old_session)

    @staticmethod
    def _safe_close(session: TmuxAgentSession) -> None:
        with contextlib.suppress(Exception):
            session.close()
