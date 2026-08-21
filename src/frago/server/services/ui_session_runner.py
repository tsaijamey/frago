"""WebUI 会话驱动后端 —— 把会话工作台的输入接到常驻 tmux 会话。

spec 20260625-webui-session-lifecycle-mediator / Phase 1：页面对某个会话发消息时，
不再走杀进程重启式的 send_message_attached，而是经一个 UI 专用 runner 把消息透传进
一个常驻 tmux 会话——活会话直接 send（保上下文）、冷/被驱逐会话由
WarmSessionPool resume 重建后再 send。

驱动哪一家由**每一轮**的调用方给（``send(..., agent_type=...)``），不再是构造时钉死的
一个 claude：三家的会话摆在同一份清单里，发送这条通道得能按会话所属的那一家去续接。
判家族与查工作目录在 ``session_send`` 里做完，本类只管把结果透传给 pool。

设计要点（对齐 spec Design Principles）：
- **独立 pool 实例**：本 runner 持有自己的 WarmSessionPool，NEVER 复用 PA 的
  PaTmuxRunner pool，避免 UI 驾驶驱逐或串扰 PA 的常驻会话。
- **上限可配**：pool 的 max_size 取自 ~/.frago/config.json 的
  webui_sessions.max_resident（缺省 10，由 config_manager 缺省自愈保证存在）。
- **激活态语义**：send 返回 SessionActivation。投喂前 pool 已持有该会话 → "ready"
  （零冷启动直送）；否则本轮触发冷启动 resume → "activating"（页面据此显示进度条）。

本类只薄封装 WarmSessionPool，NEVER 重写 driver/pool/transcript（母 spec 已落地）。
Phase 2 的空闲回收（idle eviction）落在 ``evict_idle`` + 模块级 ``_idle_age``，
巡检的周期触发在 ``ui_session_lifecycle``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from frago.agent_driver.pool import WarmSessionPool
from frago.session import codex_store, opencode_store
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
        agent_type: str | None = None,
        cwd: str | None = None,
        timeout_s: float = 180.0,
    ) -> SessionActivation:
        """向该 session_id 的常驻会话投喂一轮，返回激活态。

        投喂前 pool 已持有活会话 → 直接 send，status="ready"；否则 pool 会 resume
        重建该会话后再 send，status="activating"。阻塞调用（tmux + 轮询），调用方应
        在线程里跑以免阻塞事件循环。

        ``agent_type`` 是这场会话属于哪一家（claude / opencode / codex），由调用方按
        会话编号判定后传入；不给时退回构造时的缺省。**判错家等于静默开新会话**：
        把 codex 的编号交给 claude driver 不会报错，claude 会拿它当一个没见过的
        ``--session-id`` 当场开一场空白会话，原来那场一个字没动。
        """
        was_warm = self._pool.has(session_id)
        result = self._pool.run(
            text,
            agent_type=agent_type or self._agent_type,
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
        """回收空闲超阈值的常驻会话——空闲以**会话自己的记录**为准，不看页面输入。

        三家各问各的档案（见 :func:`_idle_age`），共同的判据只有一条：仅当最新一轮
        确已终结、且能取到那一刻的时间戳时，才以「自那一刻起的静默时长」计；仍在
        干活或取不到锚点的会话返回 None，NEVER 被回收。返回被驱逐的 session_id 列表。
        """
        from datetime import datetime

        now = datetime.now(UTC).timestamp()
        return self._pool.evict_idle(lambda session: _idle_age(session, now), timeout_s)

    def has(self, session_id: str) -> bool:
        """该会话当前是否常驻。"""
        return self._pool.has(session_id)

    def evict(self, session_id: str) -> bool:
        """驱逐该会话（kill tmux）。返回是否命中。"""
        return self._pool.evict(session_id)

    def shutdown(self) -> None:
        """关闭全部常驻会话（server 停机用）。"""
        self._pool.shutdown()


def _idle_age(session: TmuxAgentSession, now: float) -> float | None:
    """这个常驻会话已经静默了多少秒；判不出来（还在干活 / 没有锚点）返回 None。

    三家的"停顿"各有各的证据，判据 MUST 各问各的档案：

    - claude：jsonl 的完成探针，锚点是最新一轮终结记录的时间戳；
    - codex：rollout 里最新一轮已 ``task_complete``，锚点是 rollout 文件的修改时刻
      （codex 不给会话存"最后更新时刻"，文件被动过的那一刻就是它）；
    - opencode：会话库里最新一轮已终结，锚点是那条终结消息的 ``time.completed``。

    从前这里只有 claude 那一条路：另外两家的编号在 claude 的档案里定位不到文件，
    一律返回 None，于是它们的常驻会话**永远不参与空闲回收**，只能等数量 LRU 把它们
    挤掉——tmux 进程因此白占着，而回收本来是按"人已经不管它了"来的。

    哪一家**问会话自己**（``session.driver.agent_type``），不按编号形状去猜：这个
    会话是拿哪个 driver 起来的，它就是哪一家，没有再判一次的余地。问不出来就返回
    None——不知道该翻谁的档案时，宁可不回收，也不能拿另一家的判据去断它的生死。

    全程吞异常：判不出空闲只是这一轮不回收它，NEVER 让一次读盘失败把整趟巡检打死。
    """
    driver = getattr(session, "driver", None)
    family = getattr(driver, "agent_type", None)
    if family is None:
        return None
    try:
        if family == "claude":
            # UI 会话是 native：session_id 即真实 claude jsonl id，原样定位。
            path = tc_mod.locate_transcript(session.session_id, cwd=session.cwd)
            if path is None:
                return None
            completion = tc_mod.evaluate_file(path)
            if not completion.done or completion.last_terminal_ts is None:
                return None
            return now - completion.last_terminal_ts.timestamp()

        if family == "codex":
            turn = codex_store.latest_turn(session.session_id)
            if turn is None or not turn.done:
                return None
            path = codex_store.find_rollout(session.session_id)
            if path is None:
                return None
            return now - path.stat().st_mtime

        if family == "opencode":
            turn = opencode_store.latest_turn(session.session_id)
            if turn is None or not turn.done or turn.completed_at is None:
                return None
            return now - turn.completed_at / 1000
    except Exception:  # noqa: BLE001 — 读盘/读库失败只是这一轮判不出空闲
        return None
    # 注册了新 driver 却没在这里给它一条判据：不回收，NEVER 拿别家的档案去断它。
    return None


# ── UI runner 单例 ──────────────────────────────────────────────────
# server 进程内常驻一份，跨请求复用同一个会话池。路由层与空闲巡检 MUST 取同一个
# 实例：各取各的等于两个池，巡检回收的不是页面正在用的那些会话。
_ui_runner: UiSessionRunner | None = None


def get_runner() -> UiSessionRunner:
    """取 UI 专用 runner 单例（懒加载）。"""
    global _ui_runner
    if _ui_runner is None:
        _ui_runner = UiSessionRunner()
    return _ui_runner
