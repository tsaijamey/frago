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

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from frago.agent_driver.pool import WarmSessionPool


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

    def run(
        self,
        session_key: str | None,
        prompt: str,
        *,
        bootstrap: str | None = None,
        timeout_s: float = 180.0,
    ) -> str:
        """取/建该 key 的常驻会话，投喂一轮，返回完整答案文本。

        首次创建（pool 未持有活会话）且给了 bootstrap 时，bootstrap 作为独立一轮
        先注入（丢弃回复），再发本轮 prompt；之后只发 prompt。阻塞调用（tmux +
        轮询），调用方应在线程里跑以免阻塞事件循环。
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
                timeout_s=timeout_s,
            )

        result = self._pool.run(
            prompt,
            agent_type=self._agent_type,
            session_id=key,
            cwd=self._cwd,
            timeout_s=timeout_s,
        )
        return result.text

    def evict(self, session_key: str | None) -> bool:
        """驱逐该 key 的常驻会话（rotation 用）。返回是否命中。"""
        return self._pool.evict(self._key(session_key))

    def shutdown(self) -> None:
        """关闭全部常驻会话（server 停机用）。"""
        self._pool.shutdown()
