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
Phase 2 的空闲回收（idle eviction）落在 ``evict_idle`` + 模块级 ``_idle_age``
（静默多久，锚点是会话在池里的最后活动时刻）与 ``_turn_finished``（停没停，三家各问
各的档案），巡检的周期触发在 ``ui_session_lifecycle``。
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
        native_session_id: bool = True,
    ) -> SessionActivation:
        """向该 session_id 的常驻会话投喂一轮，返回激活态。

        投喂前 pool 已持有活会话 → 直接 send，status="ready"；否则 pool 会 resume
        重建该会话后再 send，status="activating"。阻塞调用（tmux + 轮询），调用方应
        在线程里跑以免阻塞事件循环。

        ``agent_type`` 是这场会话属于哪一家（claude / opencode / codex），由调用方按
        会话编号判定后传入；不给时退回构造时的缺省。**判错家等于静默开新会话**：
        把 codex 的编号交给 claude driver 不会报错，claude 会拿它当一个没见过的
        ``--session-id`` 当场开一场空白会话，原来那场一个字没动。

        ``native_session_id`` 缺省为真：页面清单里那些编号本来就是各家自己的真实会话
        编号，原样交给 driver、不派生，冷启动才续得回原会话。只有"页面新建一场编号由
        agent 自己分配的会话"（codex / opencode）才传假——那一刻 frago 手上只有自己
        mint 的一个把手，真编号要等会话起来后认领。
        """
        was_warm = self._pool.has(session_id)
        result = self._pool.run(
            text,
            agent_type=agent_type or self._agent_type,
            session_id=session_id,
            cwd=cwd or self._cwd,
            native_session_id=native_session_id,
            timeout_s=timeout_s,
        )
        # 「接管」也是零冷启动：tmux 里那场本来就活着，池只是重新拿到了它的把手。
        # 报成 activating 等于凭空宣称付了十几秒重建的代价，而实际上一秒都没付。
        adopted = getattr(self._pool.peek(session_id), "adopted", False)
        status: Literal["ready", "activating"] = (
            "ready" if (was_warm or adopted) else "activating"
        )
        return SessionActivation(
            session_id=session_id, status=status, text=result.text
        )

    def evict_idle(self, timeout_s: float) -> list[str]:
        """回收空闲超阈值的常驻会话——**停没停**看会话自己的记录，**停了多久**看池。

        「停没停」三家各问各的档案（见 :func:`_turn_finished`），「停了多久」一律从
        ``session.last_active_at`` 起算（见 :func:`_idle_age` 里那段事故说明）。任一
        问不出来、或本进程正驱动着这一轮，都返回 None，NEVER 被回收。返回被驱逐的
        session_id 列表。
        """
        from datetime import datetime

        now = datetime.now(UTC).timestamp()
        return self._pool.evict_idle(lambda session: _idle_age(session, now), timeout_s)

    def has(self, session_id: str) -> bool:
        """该会话当前是否常驻。"""
        return self._pool.has(session_id)

    def alias(self, alias_id: str, session_id: str) -> bool:
        """让认领来的原生编号也指向那一场常驻会话（见 ``WarmSessionPool.alias``）。"""
        return self._pool.alias(alias_id, session_id)

    def evict(self, session_id: str) -> bool:
        """驱逐该会话（kill tmux）。返回是否命中。"""
        return self._pool.evict(session_id)

    def shutdown(self) -> None:
        """关闭全部常驻会话（server 停机用）。"""
        self._pool.shutdown()


def _idle_age(session: TmuxAgentSession, now: float) -> float | None:
    """这个常驻会话已经静默了多少秒；判不出来（还在干活 / 没有锚点）返回 None。

    **两个问题分开问，缺一个都不许回收。**

    一、*它停下来了吗*——三家各问各的档案，见 :func:`_turn_finished`。

    二、*停了多久*——锚点一律是 ``session.last_active_at``，也就是「这场会话在本池里
    自己的最后活动时刻」（``open()`` 与每轮 ``send()`` 结束时刷新）。

    **锚点 NEVER 取档案里的时间戳**，这是一条用事故换来的判据。工作台点开一场几小时
    前的旧会话时，走的是 ``--resume``：tmux 起来、接回旧 transcript、把提示词一块块
    投喂进去，前后十几秒。这十几秒里那份 transcript 一个字都没变——它最后一条记录本
    来就是几小时前的、而且状态是「已终结」。于是每 60 秒路过一次的巡检看到的是「已
    说完 + 闲了几小时」，远超阈值，当场把这场刚起来的会话 kill 掉：人点了发送、转了
    十几秒、会话没了，重试往往又好了。阈值调多大都救不了——旧 transcript 的年龄可以
    是任意大。PA 那条路早把这一条钉在 ``primary/lifecycle.py`` 的注释上了，工作台这
    条路一直没跟上，本函数就是来跟上的。

    ``status == "busy"`` 时同样返回 None：本进程此刻正驱动着这一轮（投喂、等答），
    这是内存里的事实，比任何档案都新。档案的滞后正是上面那个窗口的成因。

    全程吞异常：判不出空闲只是这一轮不回收它，NEVER 让一次读盘失败把整趟巡检打死。
    """
    # 本进程正驱动着这一轮 → 不是空闲，一个字都不用再问。
    if getattr(session, "status", None) == "busy":
        return None
    # 没有锚点就算不出静默多久——算不出就不回收（与"档案里没有终结时刻"同一档）。
    last_active = getattr(session, "last_active_at", None)
    if last_active is None:
        return None
    if not _turn_finished(session):
        return None
    return now - last_active.timestamp()


def _turn_finished(session: TmuxAgentSession) -> bool:
    """这场会话最新一轮确已终结吗——三家各问各的档案。判不出一律 False。

    - claude：jsonl 完成探针（``stop_reason`` 是不是终结原因），再叠一道 PA 也在用的
      ``is_truly_idle``——空输入框 + 无 spinner + 无 "shells still running" + 记录已
      静默若干秒。探针只知道「最后一轮的话说完了」，它不知道那一轮派出去的后台 shell
      还在跑；把还在跑的那种当空闲回收，等于连着后台 worker 一起杀。
    - codex：rollout 里最新一轮已 ``task_complete``。
    - opencode：会话库里最新一轮已终结。

    哪一家**问会话自己**（``session.driver.agent_type``），不按编号形状去猜：这个
    会话是拿哪个 driver 起来的，它就是哪一家，没有再判一次的余地。问不出来就 False
    ——不知道该翻谁的档案时，宁可不回收，也不能拿另一家的判据去断它的生死。

    这里**只判"停没停"，NEVER 顺手把档案里的时间戳当空闲锚点**（理由见 ``_idle_age``）。
    另外两家没有与 claude 那套 pane 判据等价的东西：codex / opencode 的屏上信号得各自
    实测一遍才敢写，凭空编一组正则去断它们的生死，比现在这条只问档案的路更危险。
    """
    driver = getattr(session, "driver", None)
    family = getattr(driver, "agent_type", None)
    if family is None:
        return False
    try:
        if family == "claude":
            from frago.agent_driver.drivers import claude as claude_driver

            # 定位规则与 driver 自己那份共用（native 原样、否则 uuid5 派生），
            # NEVER 在这里另派生一份。
            path = claude_driver.transcript_path_for(session)
            if path is None:
                return False
            if not tc_mod.evaluate_file(path).done:
                return False
            return claude_driver.is_truly_idle(session)

        if family == "codex":
            turn = codex_store.latest_turn(session.session_id)
            return turn is not None and turn.done

        if family == "opencode":
            turn = opencode_store.latest_turn(session.session_id)
            return turn is not None and turn.done
    except Exception:  # noqa: BLE001 — 读盘/读库/读屏失败只是这一轮判不出空闲
        return False
    # 注册了新 driver 却没在这里给它一条判据：不回收，NEVER 拿别家的档案去断它。
    return False


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
