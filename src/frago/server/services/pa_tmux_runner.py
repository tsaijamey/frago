"""PA tmux 常驻执行后端 —— 把 PrimaryAgent 本体接到 WarmSessionPool。

Phase 3（spec 20260623-pa-tmux-resident-activation）：PA 本体不再每轮冷启动
``claude -p`` 子进程，而是按 session_key（=thread_id，无 thread 时用固定
``__fallback__``）取一个常驻 tmux claude TUI 会话，复用其上下文。

设计要点：
- 一个 session_key 对应 pool 里一个常驻会话（tmux_name=frago-agent-<key>）。
- 首次创建该 key 的会话时，把 bootstrap（PA system prompt + 历史视图）拼在本轮
  prompt 前一次性注入；会话已活时只发 prompt（claude TUI 自留上下文）。
  "是否首次"以 pool 当前是否持有该 key 的活会话判定——这同时覆盖 pool 因崩溃
  重建的情形：重建后 has() 为假，bootstrap 会被重新注入。
- ``evict`` 供 rotation 调用：kill 掉该 key 的会话，下一轮 run 自然重发 bootstrap。
- agent_type=claude，claude recipe 的 launch_command 已带
  ``--dangerously-skip-permissions``，TUI 启动即免权限门。

本类只包 WarmSessionPool，NEVER 重写 driver/pool/transcript（母 spec 已落地）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from frago.agent_driver.pool import WarmSessionPool
    from frago.agent_driver.tmux_session import TmuxAgentSession, TurnResult


class PaTmuxRunner:
    """把 PA 一轮 send→answer 跑进常驻 tmux 会话的薄封装。"""

    FALLBACK_KEY = "__fallback__"

    def __init__(
        self,
        *,
        pool: WarmSessionPool | None = None,
        cwd: str | None = None,
        agent_type: str = "claude",
    ) -> None:
        if pool is None:
            from frago.agent_driver.pool import WarmSessionPool

            pool = WarmSessionPool()
        self._pool = pool
        self._cwd = cwd or str(Path.home())
        self._agent_type = agent_type

    def _key(self, session_key: str | None) -> str:
        return session_key or self.FALLBACK_KEY

    def session(self, session_key: str | None) -> TmuxAgentSession | None:
        """取该 key 当前常驻的会话对象（真空闲判定 / 喂料门用）。无则 None。"""
        return self._pool.peek(self._key(session_key))

    def active_session_keys(self) -> list[str]:
        """当前常驻的全部 session_key（transcript 持续转发器遍历用）。"""
        return self._pool.active_ids()

    def run(
        self,
        session_key: str | None,
        prompt: str,
        *,
        bootstrap: str | None = None,
        timeout_s: float = 180.0,
        on_ready: Callable[[str], None] | None = None,
    ) -> TurnResult:
        """取/建该 key 的常驻会话，投喂一轮，返回完整 ``TurnResult``。

        首次创建（pool 未持有活会话）且给了 bootstrap 时，bootstrap 作为独立一轮
        先注入（丢弃回复），再发本轮 prompt；之后只发 prompt。阻塞调用（tmux +
        轮询），调用方应在线程里跑以免阻塞事件循环。

        返回整个 ``TurnResult``（含 ``status`` / ``raw_delta``）而非只取 ``.text``：
        调用方据 ``status==needs_input`` 把阻断门的可见提示投递回 chat 并挂起会话。
        """
        key = self._key(session_key)

        # 首轮（pool 未持有该 key 的活会话）且有 bootstrap 时，把 bootstrap 作为
        # **独立一轮**先注入、丢弃其回复，再发真实消息。NEVER 把 bootstrap 和消息
        # 拼成一个巨型多行 prompt 一次发——claude recipe 的 read_answer 靠"prompt
        # 回显行"定位本轮答案，巨型多行 prompt 在屏上找不到匹配回显会回退整屏、抠出
        # 启动垃圾。分两轮后，真实消息是一条干净可定位的 prompt。
        if bootstrap and not self._pool.has(key):
            self._pool.run(
                bootstrap,
                agent_type=self._agent_type,
                session_id=key,
                cwd=self._cwd,
                conv_key=session_key,
                timeout_s=timeout_s,
            )

        # bootstrap 注入完毕（或会话已活、无需 bootstrap）、真实 prompt 提交之前，
        # 回调一次：调用方在此把 transcript 持续转发器的 last_delivered_marker 锚到
        # 当前 tail，使 bootstrap 那一轮的回复落在 baseline 之内、绝不被转发，而真实
        # prompt 这一轮及其后台续干产出的每条终答都在 baseline 之后、由转发器投递。
        if on_ready is not None:
            on_ready(key)

        return self._pool.run(
            prompt,
            agent_type=self._agent_type,
            session_id=key,
            cwd=self._cwd,
            conv_key=session_key,
            timeout_s=timeout_s,
        )

    def warm(
        self,
        session_key: str | None,
        *,
        bootstrap: str | None = None,
        on_ready: Callable[[str], None] | None = None,
    ) -> bool:
        """预热该 key 的常驻会话（重启后预热用）。已活则直接复用、不重建，返回 ``False``。

        ``bootstrap`` 缺省时只 ``acquire``（``--resume`` 把上下文拉进活着的 TUI），不发轮。
        给了 ``bootstrap`` 时，把它作为**第一轮真实提交**注入并**等这一轮答完**——这正是
        冷路径首条消息派发时 ``run`` 做的事。这一轮有两个不可省的作用：①把 PA prompt 真正
        注进会话；②用一轮完整的「提交→答完」证明 claude 已可接收提交。少了它，刚 ``--resume``
        的会话会出现「空输入框已现、看似就绪，实则尚未可交互」的窗口，紧接着到来的首条真实
        消息成为该会话第一次提交、回车被吞、文本卡死在输入框（输入框从此非空→永远判不空闲→
        喂料门空等 600s→后续消息全堆死）。``on_ready`` 在 bootstrap 答完后回调，供调用方锚定
        转发器 baseline（使 bootstrap 那轮回复落在 baseline 内、绝不被转发）。
        """
        key = self._key(session_key)
        if self._pool.has(key):
            session = self._pool.peek(key)
            if session is not None and session.is_alive():
                return False
        if bootstrap is not None:
            self._pool.run(
                bootstrap,
                agent_type=self._agent_type,
                session_id=key,
                cwd=self._cwd,
                conv_key=session_key,
            )
            if on_ready is not None:
                on_ready(key)
        else:
            self._pool.acquire(self._agent_type, key, self._cwd, conv_key=session_key)
        return True

    def compact(self, session_key: str | None) -> bool:
        """向该 key 的常驻会话就地发 ``/compact`` slash 命令并提交（token-rotation 用）。

        Phase 7（spec 20260627）：rotation 不再 evict+resume（白杀+全量重载、不压缩），
        改为驱动常驻 claude 会话执行原生 ``/compact`` 真压上下文、会话保活不 kill。
        本方法只投命令 + 提交（结构信号，NEVER 语义）；等真空闲 / 重锚 baseline /
        重置计数由调用方负责。无活会话返回 ``False``（无可压缩）。
        """
        session = self._pool.peek(self._key(session_key))
        if session is None:
            return False
        session.send_text("/compact")
        session.send_keys("Enter")
        return True

    def evict(self, session_key: str | None) -> bool:
        """驱逐该 key 的常驻会话（rotation 用）。返回是否命中。"""
        return self._pool.evict(self._key(session_key))

    def shutdown(self) -> None:
        """关闭全部常驻会话（server 停机用）。"""
        self._pool.shutdown()
