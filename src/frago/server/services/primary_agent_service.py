"""Primary Agent service — manages the lifecycle of frago's PID 1 agent.

Phase 4 (spec 20260627-pa-deboard-resident-agent): the resident tmux agent is
the PA, and the *only* backend — claude-p is gone. Inbound messages route to it
near-raw by conv_key; its final natural-language text is delivered straight back
to the source channel via ``deliver`` — no JSON decision protocol, no
DecisionApplier, no board. The queue consumer is a single path: drain → group by
conv_key → ``_dispatch_group_tmux`` serially.

Key design properties:
- Logically immortal: scheduling continuity across server restarts
- Physically bounded: session rotation prevents context O(n²) growth
- Heartbeat layered: code-level checks first (0 token), LLM only when needed
- Execution isolated: sub-agent work happens in Run containers, never in PA session
"""

import asyncio
import contextlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.pa_prompts import (
    SUB_AGENT_PROMPT_TEMPLATE,
)
from frago.server.services.pa_prompts import (
    PA_SYSTEM_PROMPT as PRIMARY_AGENT_SYSTEM_PROMPT,
)
from frago.server.services.task_lifecycle import TaskLifecycle

logger = logging.getLogger(__name__)

# Queue-validation constants + validator moved to primary/helpers.py (Phase 4).
# Re-exported here so the module path (tests + internal callers) is unchanged.
from frago.server.services.primary import delivery as pa_delivery  # noqa: E402
from frago.server.services.primary import dispatcher as pa_dispatcher  # noqa: E402
from frago.server.services.primary import lifecycle as pa_lifecycle  # noqa: E402
from frago.server.services.primary import rendering as pa_rendering  # noqa: E402
from frago.server.services.primary import rotation as pa_rotation  # noqa: E402
from frago.server.services.primary import watcher as pa_watcher  # noqa: E402
from frago.server.services.primary.helpers import (  # noqa: E402,F401
    NON_DELIVERABLE_CHANNELS,
    VALID_QUEUE_MESSAGE_TYPES,
    _render_domain_peek,
    _validate_queue_message,
)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"
CONFIG_FILE = FRAGO_HOME / "config.json"

# Heartbeat defaults (overridable via config.json primary_agent.heartbeat)
HEARTBEAT_DEFAULTS = {
    "enabled": True,
    "interval_seconds": 300,       # 5 minutes
    "initial_delay_seconds": 30,   # wait after server startup
}

# Rotation thresholds
# Turn limit disabled (None): turns alone don't bloat context (each turn is
# already token-counted), so rotation is driven purely by accumulated tokens.
ROTATION_TURN_THRESHOLD = None
# Token window aligned to ~half of Claude's 1M context, leaving ample room
# for system prompt + bootstrap on rebuild.
ROTATION_TOKEN_THRESHOLD = 500000

# Task execution timeout (seconds)
TASK_TIMEOUT_SECONDS = 900

# Phase 6 (spec 20260627): transcript 持续转发器 + 真空闲回收/喂料门的节律默认值，
# 可被 config.json 的 primary_agent.{watch,idle} 覆盖。
WATCH_DEFAULTS = {
    # 持续转发器轮询每个常驻会话 transcript 的间隔（秒）。~1.5s 足够贴 PA「先应一句
    # 再异步续干」的节律，又不至于把 jsonl 读穿。
    "watch_interval_seconds": 1.5,
    # 真空闲的 transcript 静默判据：mtime 静默超过该秒数才算这一信号成立。
    "idle_silence_seconds": 3.0,
    # 喂料门最长等待真空闲的秒数；超过则记日志并放行（别死等一个永远不空闲的会话）。
    "feeding_gate_max_seconds": 600.0,
    # 喂料门 / wait-until-idle 的轮询间隔（秒）。
    "idle_poll_seconds": 1.0,
    # 空闲回收阈值：会话真空闲持续超过该秒数，由 heartbeat 周期 evict（关 tmux）。
    # 配合 Phase 5 --resume：回收后再来消息按 transcript 接回，记忆不丢。
    "idle_evict_seconds": 600.0,
}

# Resident-tmux session key used when a message has no bound thread (fallback).
# Kept in sync with PaTmuxRunner.FALLBACK_KEY.
PaTmuxRunner_FALLBACK = "__fallback__"

# 滚动记录最近用过的 conv_key 上限——重启后据此预热常驻会话、消首句冷启动。
WARM_CONVS_MAX = 10


class PrimaryAgentService:
    """Manages the Primary Agent lifecycle: attached session + heartbeat + Run dispatch.

    Singleton — use get_instance() to access.
    """

    _instance: "PrimaryAgentService | None" = None

    def __init__(self) -> None:
        # Per-thread (conv_key) rotation counters for the resident tmux sessions.
        self._total_turns: dict[str, int] = {}
        self._accumulated_tokens: dict[str, int] = {}
        self._rotation_count: dict[str, int] = {}

        # Currently active thread (serial dispatch: one at a time)
        self._current_thread_id: str | None = None

        # Server-level fallback rotation counters (messages with no conv_key).
        self._fallback_total_turns: int = 0
        self._fallback_accumulated_tokens: int = 0
        self._fallback_rotation_count: int = 0

        # Heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_stop = asyncio.Event()
        self._heartbeat_seq: int = 0

        # State tracking
        self._server_start_time: float = time.monotonic()
        self._busy: bool = False
        self._last_external_message_at: float | None = None

        # Phase 2 (去 JSON 协议) → Phase 3 衔接点：conv → reply_context 内存缓存。
        # 入队 user_message 时写入（reply_context 随消息带入），deliver 时读取，
        # 让出去投递不再依赖 board task 查 reply_context。重启丢失无妨——下一条入站
        # 消息会带着 reply_context 重建。Phase 2 暂以 channel 作 key（conv_key 派生在
        # Phase 3 落地），board 作兜底。
        self._reply_context_cache: dict[str, dict[str, Any]] = {}

        # Phase 6 (spec 20260627): transcript 持续转发器状态。
        # _conv_route_cache: conv_key → 完整 route（channel + conv_key + reply_context），
        #   入队时写入，转发器投递时按 conv_key 取它做 deliver 的 route。
        # _last_delivered_marker: conv_key → 最近已投递的 transcript 终结 marker，
        #   每个 marker 只投一次（去重）；喂 prompt 前由 on_ready 锚到 tail 做 baseline。
        # _bootstrapping_convs: 正在注入 bootstrap 的 conv，转发器此窗口内跳过该 conv，
        #   避免把 bootstrap 那一轮回复当新终答抢先投出（baseline 尚未锚定的竞态）。
        self._conv_route_cache: dict[str, dict[str, Any]] = {}
        self._last_delivered_marker: dict[str, str | None] = {}
        # _watch_mtime: conv_key → 上拍看到的 transcript mtime。转发器每拍先 stat（微秒级），
        #   mtime 没变就跳过全量解析——空闲会话（绝大多数时间）不再每 1.5s 重读重解几 MB。
        self._watch_mtime: dict[str, float] = {}
        self._bootstrapping_convs: set[str] = set()
        # Phase 7 (token-rotation 改就地 /compact)：正在执行 /compact 的 conv 集合，
        # 比照 _bootstrapping_convs——转发器 _watch_tick 在此窗口内跳过该 conv，避免把
        # /compact 那一轮的 transcript 产出当新终答投到 channel（baseline 在 compact
        # 完成后由 _seed_marker 重锚，双保险）。
        self._compacting_convs: set[str] = set()
        self._transcript_watch_task: asyncio.Task[None] | None = None
        # 重启后预热 warm_convs 的后台任务（串行拉起常驻会话，消首句冷启动）。
        self._preheat_task: asyncio.Task[None] | None = None
        self._watch_config: dict[str, Any] = self._load_watch_config()

        # Message queue
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queue_consumer_task: asyncio.Task[None] | None = None

        # 按 conv_key 并发派发：router 把消息按 conv 路由到各自的子队列，每个 conv 一条
        # 独立 worker 协程串行处理本 conv（保序）但跨 conv 并发——一个 conv 跑长回合
        # （含后台 worker）不再冻结其他 conv 的回复。
        self._conv_queues: dict[str | None, asyncio.Queue[list[dict[str, Any]]]] = {}
        self._conv_workers: dict[str | None, asyncio.Task[None]] = {}

        # Track scheduled_task msg_id → schedule_id for PA result write-back
        self._schedule_msg_map: dict[str, str] = {}

        # 常驻会话执行器：按 conv_key 复用 tmux claude TUI。懒初始化。这是唯一的
        # PA 执行后端（Phase 4 删 claude-p 后队列消费收敛到此单路径）。
        self._pa_tmux_runner: Any | None = None

        # Phase 1 (needs_input): convs 当前停在阻断门（认证墙 / 选择菜单）上的集合。
        # 撞门后标记，会话原样停住、不重入队列、不 rotate；用户下一条消息透传进同一
        # conv 把门推过后由 ok 分支清除。仅作可观测与防御性 guard，不驱动调度。
        self._suspended_convs: set[str | None] = set()

        # Task lifecycle coordinator
        self._lifecycle = TaskLifecycle()

        # Ingestion scheduler reference
        self._scheduler: Any = None

        # Recipe scheduler reference
        self._scheduler_service: Any = None

    def set_ingestion_scheduler(self, scheduler: Any) -> None:
        """Register ingestion scheduler for message cache access."""
        self._scheduler = scheduler

    def set_scheduler_service(self, scheduler: Any) -> None:
        """Register recipe scheduler for result write-back."""
        self._scheduler_service = scheduler

    @classmethod
    def get_instance(cls) -> "PrimaryAgentService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- lifecycle --

    async def initialize(self) -> None:
        """Initialize PA: start queue consumer, executor and heartbeat.

        Per-thread PA sessions are created on demand when messages arrive
        (Phase 3: no single default session at startup).
        """
        # 预构造常驻执行器，避免多个 conv worker 首次并发派发时竞争 lazy-init。
        self._get_pa_tmux_runner()
        self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())
        self._transcript_watch_task = asyncio.create_task(self._transcript_watch_loop())
        # 后台预热最近用过的 conv（串行、不阻塞 server 启动），消首句冷启动。
        self._preheat_task = asyncio.create_task(self._preheat_warm_convs())

        await self._start_heartbeat()
        # reflection tick 已退役：它是 taskboard/timeline 时代的设计，靠"扫 timeline +
        # 活跃 thread"找主动事项；账本(Phase 3)与 JSON 决策(Phase 2)都删了之后它只会空跑、
        # 还每轮 mint 一个垃圾 ULID 会话。
        # Phase 3 (去账本): 不再 _recover_pending_tasks——跨重启的连续性交给 claude
        # 原生 transcript + native_session_id 续接，重启前未答完的轮不复活。

    async def stop(self) -> None:
        """Stop queue consumer, heartbeat, and all PA sessions."""
        if self._queue_consumer_task and not self._queue_consumer_task.done():
            self._queue_consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_consumer_task
            self._queue_consumer_task = None

        # 取消所有 per-conv worker 协程。
        for t in list(self._conv_workers.values()):
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        self._conv_workers.clear()
        self._conv_queues.clear()

        if self._transcript_watch_task and not self._transcript_watch_task.done():
            self._transcript_watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._transcript_watch_task
            self._transcript_watch_task = None

        if self._preheat_task and not self._preheat_task.done():
            self._preheat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._preheat_task
            self._preheat_task = None

        await self._stop_heartbeat()
        if self._pa_tmux_runner is not None:
            try:
                self._pa_tmux_runner.shutdown()
            except Exception:
                logger.debug("PA tmux runner shutdown error", exc_info=True)
            self._pa_tmux_runner = None

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def record_external_message(self) -> None:
        self._last_external_message_at = time.monotonic()

    # -- PA session management (resident tmux backend only) --

    async def rotate_session(self, thread_id: str | None = None) -> None:
        """Rotate a conversation's resident tmux session (token-driven).

        Phase 7 (spec 20260627): token-rotation 不再 evict+resume（Phase 5 之后那是
        白杀一次 + 全量重载、不压缩），改为驱动常驻会话就地执行 ``/compact`` 真压
        上下文、会话保活不 kill。
        """
        await self._compact_tmux_session(thread_id)

    # conv_key 路由已抽到 primary/dispatcher.py；门面委托（_resolve_thread_id 被测试调用）。
    @staticmethod
    def _resolve_thread_id(msg: dict) -> str | None:
        """Resolve conv_key route for a queue message (delegates to dispatcher)."""
        return pa_dispatcher.resolve_thread_id(msg)

    @staticmethod
    def _set_msg_thread_id(msg: dict, thread_id: str | None) -> None:
        """Backfill thread_id on msg dict (delegates to dispatcher)."""
        pa_dispatcher.set_msg_thread_id(msg, thread_id)

    def _build_bootstrap_prompt(self, thread_id: str | None = None, create_reason: str | None = None) -> tuple[str, str]:
        """Build bootstrap context (board view + conversation history + knowledge).

        ``thread_id`` optional: when set, board view is filtered to that thread only
        (Phase 3 per-conversation routing). Default None = full view for fallback.
        """
        from frago.server.services.pa_context_builder import build_bootstrap

        return build_bootstrap(self._rotation_count.get(thread_id, 0) if thread_id else self._fallback_rotation_count, create_reason=create_reason, thread_id=thread_id)

    # -- PA event broadcast --

    async def _broadcast_pa_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a humanized timeline event to all connected WebSocket clients."""
        try:
            from frago.server.services.timeline_service import humanize_event
            from frago.server.websocket import MessageType, manager
            humanized = humanize_event(event_type, data)
            ts = datetime.now().isoformat()
            await manager.broadcast({
                "type": MessageType.TIMELINE_EVENT,
                "timestamp": ts,
                "event": {
                    "id": f"pa-{event_type}-{ts}",
                    "timestamp": ts,
                    **humanized,
                    "task_id": data.get("task_id", ""),
                    "msg_id": data.get("msg_id", ""),
                    "run_id": data.get("run_id"),
                    "raw_data": data,
                },
            })
        except Exception as e:
            logger.debug("Failed to broadcast PA event %s: %s", event_type, e)

    # -- message queue --

    async def enqueue_message(self, msg: dict[str, Any]) -> None:
        """Enqueue a message for PA consumption."""
        ok, error = _validate_queue_message(msg)
        if not ok:
            logger.warning("Rejected invalid queue message: %s (msg: %s)", error, msg)
            return

        # Phase 3: cache the inbound reply_context keyed by conv_key (and by
        # channel, for the by-channel online-notification lookup) so the outbound
        # deliver path routes without any board read. Freshest message wins.
        reply_ctx = msg.get("reply_context")
        conv_key = msg.get("conv_key")
        channel = msg.get("channel")
        if reply_ctx:
            if conv_key:
                self._reply_context_cache[f"conv:{conv_key}"] = reply_ctx
            if channel:
                self._reply_context_cache[f"channel:{channel}"] = reply_ctx

        # Phase 6: 持续转发器投递时需要一份完整 route（channel + conv_key +
        # reply_context）。入队即缓存，转发器按 conv_key 取它做 deliver 的 route，
        # 不必再回溯入队消息。最新消息覆盖（reply 目标随新消息更新）。
        if conv_key and channel:
            self._conv_route_cache[str(conv_key)] = {
                "channel": channel,
                "conv_key": str(conv_key),
                "reply_context": reply_ctx or {},
            }

        await self._message_queue.put(msg)
        logger.debug("Message enqueued: type=%s", msg.get("type", "unknown"))

        if msg.get("type") == "user_message":
            await self._broadcast_pa_event("pa_ingestion", {
                "task_id": msg.get("task_id", ""),
                "msg_id": msg.get("channel_message_id", msg.get("msg_id", "")),
                "channel": msg.get("channel", ""),
                "prompt": msg.get("prompt", ""),
            })

    async def enqueue_worker_done(
        self,
        *,
        conv_key: str | None,
        channel: str,
        result_summary: str,
        status: str = "completed",
        agent_type: str = "",
        worker_id: str = "",
        output_files: list[str] | None = None,
        reply_context: dict[str, Any] | None = None,
    ) -> None:
        """Re-enqueue a finished worker's result as a new PA queue message (Phase 3).

        spec item 5: worker（``frago agent start`` 起的 sub-agent）跑完，以一条带 conv
        归属的 ``worker_done`` 消息重入队列，PA 下一轮组织最终回复。这是"复用完成回调
        路径、把写 board 替换为 enqueue worker_done"的落点。

        [TBD] 触发侧：常驻 ``frago agent start`` worker 由 PA agent 自己驱动（tmux
        send/peek），目前服务端无统一的 worker 完成监听器；本方法提供重入入口，实际
        由谁在 worker 退出时调用它待后续 wiring（旧 executor 板任务监听已随账本退役）。
        """
        await self.enqueue_message({
            "type": "worker_done",
            "conv_key": conv_key,
            "channel": channel,
            "status": status,
            "result_summary": result_summary,
            "agent_type": agent_type,
            "worker_id": worker_id,
            "output_files": output_files or [],
            "reply_context": reply_context or {},
            "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    # 队列路由/按 conv 派发已抽到 primary/dispatcher.py（接 svc 自由函数）；门面委托。
    async def _queue_consumer_loop(self) -> None:
        """Router loop（delegates to dispatcher）。"""
        await pa_dispatcher.queue_consumer_loop(self)

    def _ensure_conv_worker(self, tid: str | None) -> None:
        """确保该 conv 有活 worker（delegates to dispatcher）。"""
        pa_dispatcher.ensure_conv_worker(self, tid)

    async def _conv_worker_loop(self, tid: str | None) -> None:
        """单个 conv 的 worker 循环（delegates to dispatcher）。"""
        await pa_dispatcher.conv_worker_loop(self, tid)

    # 队列消息渲染已抽到 primary/rendering.py（接 svc 的自由函数）；门面委托。
    def _format_queue_messages(self, messages: list[dict[str, Any]]) -> str:
        """Format queued messages into a text block (delegates to rendering)."""
        return pa_rendering.format_queue_messages(self, messages)

    @staticmethod
    def _format_logs_section(recent_logs: list[str]) -> str:
        """Format recent log lines (delegates to rendering)."""
        return pa_rendering.format_logs_section(recent_logs)

    # -- heartbeat --

    # 配置 helper 已抽到 primary/lifecycle.py（无状态自由函数）；门面保留方法委托，
    # 保持 svc._load_*() 调用点与测试 monkeypatch 点不变。
    def _load_watch_config(self) -> dict[str, Any]:
        """Load Phase 6 transcript-watch / idle config (delegates to lifecycle)."""
        return pa_lifecycle.load_watch_config(CONFIG_FILE, WATCH_DEFAULTS)

    def _load_heartbeat_config(self) -> dict[str, Any]:
        """Load heartbeat config (delegates to lifecycle)."""
        return pa_lifecycle.load_heartbeat_config(CONFIG_FILE, HEARTBEAT_DEFAULTS)

    def _load_warm_convs(self) -> list[str]:
        """读 config 里 primary_agent.warm_convs（delegates to lifecycle）。"""
        return pa_lifecycle.load_warm_convs(CONFIG_FILE)

    def _record_warm_conv(self, conv_key: str) -> None:
        """把 conv_key 提到 warm_convs 最前（delegates to lifecycle）。"""
        pa_lifecycle.record_warm_conv(
            conv_key, CONFIG_FILE, WARM_CONVS_MAX, PaTmuxRunner_FALLBACK
        )

    async def _preheat_warm_convs(self) -> None:
        """后台串行预热 warm_convs 里的常驻会话，消首句冷启动。NEVER 阻塞 server 启动。

        逐个（串行，不并行 10 个一起拉，避免一次起 10 个 claude 打爆机器）调会话获取
        路径把常驻 tmux 拉起来——走 acquire（--resume + bootstrap，Phase 5 保证 transcript
        存在则 resume）。已活的跳过。每个预热前后记 info 日志。预热是一次完整且慢的会话
        启动，所以放后台 + 串行。
        """
        convs = self._load_warm_convs()
        if not convs:
            return
        logger.info("PA preheat: warming %d resident conv(s): %s", len(convs), convs)
        runner = self._get_pa_tmux_runner()
        for conv_key in convs:
            if not conv_key or conv_key == PaTmuxRunner_FALLBACK:
                continue
            try:
                logger.info("PA preheat: warming conv=%s ...", conv_key)
                # 预热 MUST 把 bootstrap 那轮也跑掉（真实提交+等答完），NEVER 只 open 会话：
                # 只 open 会让会话进池（has()=True），首条真实消息那轮便跳过 bootstrap，
                # 成为刚 --resume、尚未可交互会话的第一次提交→回车被吞→卡死。详见 warm()。
                bootstrap, _ = self._build_bootstrap_prompt(
                    thread_id=conv_key, create_reason="preheat"
                )
                full_bootstrap = PRIMARY_AGENT_SYSTEM_PROMPT + "\n\n" + bootstrap
                self._bootstrapping_convs.add(conv_key)

                def _on_ready(_key: str, _ck: str = conv_key) -> None:
                    self._seed_marker(_ck)
                    self._bootstrapping_convs.discard(_ck)

                try:
                    created = await asyncio.to_thread(
                        runner.warm, conv_key,
                        bootstrap=full_bootstrap, on_ready=_on_ready,
                    )
                finally:
                    self._bootstrapping_convs.discard(conv_key)
                logger.info(
                    "PA preheat: conv=%s %s",
                    conv_key,
                    "warmed (bootstrap injected)" if created else "already alive, skipped",
                )
            except asyncio.CancelledError:
                logger.info("PA preheat cancelled")
                raise
            except Exception:
                logger.exception("PA preheat: warming conv=%s failed", conv_key)

    # 心跳/空闲回收运行时已抽到 primary/lifecycle.py（接 svc 自由函数）；门面委托，
    # 保住测试的 svc._{start,stop,send}_heartbeat / _evict_idle_sessions 调用与 patch 点。
    async def _start_heartbeat(self) -> None:
        await pa_lifecycle.start_heartbeat(self)

    async def _stop_heartbeat(self) -> None:
        await pa_lifecycle.stop_heartbeat(self)

    async def _heartbeat_loop(self, interval: int, initial_delay: int) -> None:
        await pa_lifecycle.heartbeat_loop(self, interval, initial_delay)

    async def _send_heartbeat(self) -> None:
        await pa_lifecycle.send_heartbeat(self)

    async def _evict_idle_sessions(self) -> None:
        await pa_lifecycle.evict_idle_sessions(self)

    # -- PA output handling (Phase 2: 透传，无 JSON 决策协议) --

    # 投递路径已抽到 primary/delivery.py（接 svc 自由函数）；门面委托，
    # 保住测试的 svc.deliver 调用与 patch 点。
    @staticmethod
    def _route_for_group(group: list[dict]) -> dict[str, Any]:
        """Pick representative inbound message (delegates to delivery)."""
        return pa_delivery.route_for_group(group)

    @staticmethod
    def _warn_bareword_paths(
        text: str, attachments: list[dict[str, Any]], conv_key: str,
    ) -> None:
        """兜底观测裸路径（delegates to delivery）。"""
        pa_delivery.warn_bareword_paths(text, attachments, conv_key)

    async def deliver(self, text: str, route: dict[str, Any]) -> None:
        """Push agent text back to source channel (delegates to delivery)."""
        await pa_delivery.deliver(self, text, route)

    def _writeback_schedules(self, group: list[dict]) -> None:
        """Mark scheduled_task entries handled (delegates to dispatcher)."""
        pa_dispatcher.writeback_schedules(self, group)


    # -- helpers --

    # -- Phase 3: tmux 常驻后端执行路径 --

    # -- Phase 6: transcript 持续转发器（修「漏接真结果」根因）--

    # transcript 转发器已抽到 primary/watcher.py（接 svc 自由函数）；门面委托，
    # 保住测试的 svc._watch_tick / _watch_poll / _seed_marker / _eval_conv_transcript 调用与 patch 点。
    def _eval_conv_transcript(self, conv_key: str) -> Any | None:
        """读 conv transcript，返回 TurnCompletion（delegates to watcher）。"""
        return pa_watcher.eval_conv_transcript(self, conv_key)

    def _watch_poll(
        self, conv_key: str, since_mtime: float | None
    ) -> tuple[float | None, Any | None]:
        """stat transcript + 条件解析（delegates to watcher）。"""
        return pa_watcher.watch_poll(self, conv_key, since_mtime)

    def _seed_marker(self, conv_key: str | None) -> None:
        """锚 baseline marker（delegates to watcher）。"""
        pa_watcher.seed_marker(self, conv_key)

    async def _transcript_watch_loop(self) -> None:
        """transcript 持续转发器循环（delegates to watcher）。"""
        await pa_watcher.transcript_watch_loop(self)

    async def _watch_tick(self) -> None:
        """转发器一拍（delegates to watcher）。"""
        await pa_watcher.watch_tick(self, PaTmuxRunner_FALLBACK)

    # -- Phase 6: 真空闲判定（喂料门 + 回收共用）--

    # 真空闲判定已抽到 primary/dispatcher.py（接 svc 自由函数）；门面委托，
    # 保住测试的 svc._is_truly_idle / _wait_until_truly_idle 调用与 patch 点。
    def _is_truly_idle(self, session_key: str) -> bool:
        """该 key 是否真空闲（delegates to dispatcher）。"""
        return pa_dispatcher.is_truly_idle(self, session_key)

    async def _wait_until_truly_idle(self, session_key: str) -> None:
        """等到真空闲再返回（delegates to dispatcher）。"""
        await pa_dispatcher.wait_until_truly_idle(self, session_key)

    def _get_pa_tmux_runner(self) -> Any:
        """Lazily construct the resident-tmux PA executor (backend=="tmux")."""
        if self._pa_tmux_runner is None:
            from frago.server.services.pa_tmux_runner import PaTmuxRunner

            self._pa_tmux_runner = PaTmuxRunner(cwd=str(Path.home()))
        return self._pa_tmux_runner

    # 核心喂料门 _dispatch_group_tmux 已抽到 primary/dispatcher.py（接 svc 自由函数）；
    # 门面委托，PaTmuxRunner_FALLBACK / 系统提示作参数传入，保住测试调用与 patch 点。
    async def _dispatch_group_tmux(self, tid: str | None, group: list[dict]) -> None:
        """Feed a message group to PA's resident session (delegates to dispatcher)."""
        await pa_dispatcher.dispatch_group_tmux(
            self, tid, group, PaTmuxRunner_FALLBACK, PRIMARY_AGENT_SYSTEM_PROMPT
        )

    # needs_input 阻断门已抽到 primary/dispatcher.py；门面委托。
    @staticmethod
    def _format_needs_input_prompt(raw_delta: str) -> str:
        """阻断门可见 pane → 回复文本（delegates to dispatcher）。"""
        return pa_dispatcher.format_needs_input_prompt(raw_delta)

    async def _deliver_needs_input(
        self, tid: str | None, group: list[dict], raw_delta: str
    ) -> None:
        """把阻断门提示作为回复投递（delegates to dispatcher）。"""
        await pa_dispatcher.deliver_needs_input(self, tid, group, raw_delta)

    # 轮换/compact/计数已抽到 primary/rotation.py（接 svc 自由函数）；门面委托，
    # 保住测试的 svc._compact_tmux_session / _should_rotate / _rotate_tmux_session 等调用与 patch 点。
    async def _compact_tmux_session(self, thread_id: str | None = None) -> None:
        """就地驱动常驻会话 /compact 真压上下文（delegates to rotation）。"""
        await pa_rotation.compact_tmux_session(self, thread_id, PaTmuxRunner_FALLBACK)

    def _reset_rotation_counters(self, thread_id: str | None, count: int) -> None:
        """复位 token/轮次计数 + rotation_count+1（delegates to rotation）。"""
        pa_rotation.reset_rotation_counters(self, thread_id, count)

    async def _rotate_tmux_session(self, thread_id: str | None = None) -> None:
        """Evict resident session + reset counters (delegates to rotation)."""
        await pa_rotation.rotate_tmux_session(self, thread_id, PaTmuxRunner_FALLBACK)

    def _should_rotate(self, thread_id: str | None = None) -> bool:
        """Check if session rotation is needed (delegates to rotation)."""
        return pa_rotation.should_rotate(
            self, thread_id, ROTATION_TURN_THRESHOLD, ROTATION_TOKEN_THRESHOLD
        )

    @staticmethod
    def _build_sub_agent_prompt(
        task_id: str | None,  # noqa: ARG004 reserved for related_runs lookup
        task_prompt: str,
        run_id: str,
        related_runs: list[str] | None = None,
        domain_peek: dict[str, Any] | None = None,
    ) -> str:
        """Build the prompt for a sub-agent working in a Run instance."""
        related_section = ""
        if related_runs:
            lines = ["相关历史 Run（可用 frago run info <run_id> 查看详情）:"]
            for rid in related_runs:
                lines.append(f"  - {rid}")
            related_section = "\n" + "\n".join(lines) + "\n"

        if domain_peek:
            related_section = (
                _render_domain_peek(domain_peek) + related_section
            )

        return SUB_AGENT_PROMPT_TEMPLATE.format(
            task_prompt=task_prompt,
            run_id=run_id,
            related_section=related_section,
        )

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}秒"
        if seconds < 3600:
            return f"{seconds // 60}分钟"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}小时{minutes}分钟"
        return f"{hours}小时"
