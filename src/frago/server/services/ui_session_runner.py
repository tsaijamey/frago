"""WebUI 会话驱动后端 —— 把 claude-sessions 页面的输入接到常驻 tmux claude。

spec 20260625-webui-session-lifecycle-mediator / Phase 1：页面对某个会话发消息时，
不再走杀进程重启式的 send_message_attached，而是经一个 UI 专用 runner 把消息透传进
一个常驻 tmux claude 会话——活会话直接 send（保上下文）、冷/被驱逐会话由
WarmSessionPool resume 重建后再 send。

设计要点（对齐 spec Design Principles）：
- **独立 pool 实例**：本 runner 持有自己的 WarmSessionPool，NEVER 复用 PA 的
  PaTmuxRunner pool，避免 UI 驾驶驱逐或串扰 PA 的常驻会话。
- **上限可配**：pool 的 max_size 取自 ~/.frago/config.json 的
  webui_sessions.max_resident（缺省 10，由 config_manager 缺省自愈保证存在）。
- **激活态语义**：send 返回 SessionActivation。投喂前 pool 已持有该会话 → "ready"
  （零冷启动直送）；否则本轮触发冷启动 resume → "activating"（页面据此显示进度条）。

本类只薄封装 WarmSessionPool，NEVER 重写 driver/pool/transcript（母 spec 已落地）。
Phase 2 的空闲回收（idle eviction）与 last_terminal_ts 不在本文件范围。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from frago.agent_driver.pool import WarmSessionPool
from frago.session import transcript_completion as tc_mod

if TYPE_CHECKING:
    from frago.agent_driver.tmux_session import TmuxAgentSession


@dataclass
class SessionActivation:
    """一次 UI 投喂的激活结果。

    session_id 即 claude 的 jsonl 会话 id。status 反映本轮是否经历了冷启动：
    - ready      : 投喂前会话已常驻，直接 send（保上下文，零冷启动）。
    - activating : 投喂前会话为冷/被驱逐，本轮触发 pool resume 重建后投喂。
    text 为 tmux 一轮 send→done 的归一化答案文本（页面内容仍以 jsonl 为权威）。
    """

    session_id: str
    status: Literal["ready", "activating"]
    text: str


class UiSessionRunner:
    """把 WebUI 一轮 send→answer 跑进常驻 tmux 会话的薄封装（UI 专用）。"""

    def __init__(
        self,
        *,
        pool: WarmSessionPool | None = None,
        max_size: int | None = None,
        cwd: str | None = None,
        agent_type: str = "claude",
    ) -> None:
        if pool is None:
            if max_size is None:
                # 上限取自 config.json -> webui_sessions.max_resident（缺省自愈保证存在）。
                from frago.init.config_manager import load_config

                max_size = load_config().webui_sessions.max_resident
            pool = WarmSessionPool(max_size=max_size)
        self._pool = pool
        self._cwd = cwd or str(Path.home())
        self._agent_type = agent_type

    def send(
        self,
        session_id: str,
        text: str,
        *,
        cwd: str | None = None,
        timeout_s: float = 180.0,
    ) -> SessionActivation:
        """向该 session_id 的常驻会话投喂一轮，返回激活态。

        投喂前 pool 已持有活会话 → 直接 send，status="ready"；否则 pool 会 resume
        重建该会话后再 send，status="activating"。阻塞调用（tmux + 轮询），调用方应
        在线程里跑以免阻塞事件循环。
        """
        was_warm = self._pool.has(session_id)
        result = self._pool.run(
            text,
            agent_type=self._agent_type,
            session_id=session_id,
            cwd=cwd or self._cwd,
            # 页面列的 session_id 就是真实的 claude jsonl 会话 id，原样用、不派生，
            # 冷启动才能续上原会话而非另起新会话写进别的 jsonl。
            native_session_id=True,
            timeout_s=timeout_s,
        )
        status: Literal["ready", "activating"] = "ready" if was_warm else "activating"
        return SessionActivation(
            session_id=session_id, status=status, text=result.text
        )

    def evict_idle(self, timeout_s: float) -> list[str]:
        """回收空闲超阈值的常驻会话——空闲以 jsonl 的实质停顿为准，不看页面输入。

        每个常驻会话的「空闲秒数」由完成探针给出：读它的 jsonl，仅当最新一轮已
        出现终结性 stop_reason（done）且能取到终结记录时间戳时，才以「自该时间戳起
        的静默时长」计；仍在干活（探针 not done / tool_use / 流式中）或取不到锚点的
        会话返回 None，NEVER 被回收。返回被驱逐的 session_id 列表。
        """
        from datetime import datetime

        now = datetime.now(UTC)

        def idle_age(session: TmuxAgentSession) -> float | None:
            # UI 会话是 native：session_id 即真实 claude jsonl id，原样定位。
            path = tc_mod.locate_transcript(session.session_id, cwd=session.cwd)
            if path is None:
                return None
            completion = tc_mod.evaluate_file(path)
            if not completion.done or completion.last_terminal_ts is None:
                return None  # 干活中或无锚点 → 不参与回收
            return (now - completion.last_terminal_ts).total_seconds()

        return self._pool.evict_idle(idle_age, timeout_s)

    def has(self, session_id: str) -> bool:
        """该会话当前是否常驻。"""
        return self._pool.has(session_id)

    def evict(self, session_id: str) -> bool:
        """驱逐该会话（kill tmux）。返回是否命中。"""
        return self._pool.evict(session_id)

    def shutdown(self) -> None:
        """关闭全部常驻会话（server 停机用）。"""
        self._pool.shutdown()
