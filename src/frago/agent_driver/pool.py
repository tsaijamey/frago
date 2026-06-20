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

from frago.agent_driver.recipe import load_recipe
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
        resume_hook: ResumeHook | None = None,
    ) -> TmuxAgentSession:
        existing = self._sessions.get(session_id)
        if existing is not None:
            if existing.is_alive():
                self._sessions.move_to_end(session_id)  # 标记最近使用
                return existing
            # 探测到崩溃 → 丢弃，走重建（可 resume 恢复）。
            del self._sessions[session_id]

        recipe = load_recipe(agent_type)
        session = TmuxAgentSession(
            session_id=session_id, recipe=recipe, cwd=cwd, runner=self._runner
        )
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
        timeout_s: float = 120.0,
        resume_hook: ResumeHook | None = None,
    ) -> TurnResult:
        """取活会话 → 投喂一轮；会话保活留待复用。"""
        session = self.acquire(
            agent_type, session_id, cwd, resume_hook=resume_hook
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
