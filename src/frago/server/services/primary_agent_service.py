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
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.pa_prompts import (
    PA_AGENT_COMPLETED_TEMPLATE,
    PA_AGENT_FAILED_TEMPLATE,
    PA_MERGED_MESSAGES_TEMPLATE,
    PA_MESSAGE_TEMPLATE,
    PA_QUEUE_GROUP_LINE_TEMPLATE,
    PA_QUEUE_LAST_STATUS_LINE_TEMPLATE,
    PA_QUEUE_LOGS_SECTION_TEMPLATE,
    PA_QUEUE_OUTPUTS_LINE_TEMPLATE,
    PA_QUEUE_RECIPE_LINE_TEMPLATE,
    PA_QUEUE_RECOVERED_NOTE,
    PA_QUEUE_TIME_HEADER_TEMPLATE,
    PA_QUEUE_UNKNOWN_FALLBACK_TEMPLATE,
    PA_RECOVERED_FAILED_TASK_TEMPLATE,
    PA_REPLY_FAILED_TEMPLATE,
    PA_SCHEDULED_TASK_TEMPLATE,
    SUB_AGENT_PROMPT_TEMPLATE,
)
from frago.server.services.pa_prompts import (
    PA_SYSTEM_PROMPT as PRIMARY_AGENT_SYSTEM_PROMPT,
)
from frago.server.services.task_lifecycle import TaskLifecycle

logger = logging.getLogger(__name__)

# Queue message types PA accepts (Phase 2: the validator collapsed from
# pa_validators.py to this minimal gate — only the enqueue path still needs it;
# the JSON-output validator is gone with the decision protocol).
VALID_QUEUE_MESSAGE_TYPES = {
    "user_message",
    "agent_completed", "agent_failed", "reply_failed",
    "scheduled_task",
    "recovered_failed_task",
    "resume_failed",
    "run_failed",
    "schedule_failed",
    # Phase 3 (去账本): worker（agent 用 `frago agent start` 起的 sub-agent）完成后
    # 以一条新消息带 conv 归属重入队列，PA 下一轮组织最终回复。
    "worker_done",
}

# Internal queue message types that have NO outbound user channel. When a turn
# consumes one of these and produces text, that text must NOT be delivered as a
# reply (there is nowhere to send it) and a failed delivery must NOT be re-fed as
# a reply_failed message — doing so creates a self-sustaining loop (reply_failed
# → deliver → no notify_recipe → reply_failed → ...).
# Note: agent_completed / worker_done carry the original user's real channel in
# their route, so they are deliverable and intentionally excluded here.
NON_DELIVERABLE_CHANNELS = frozenset({
    "reply_failed",
    "resume_failed",
    "run_failed",
    "schedule_failed",
})


def _validate_queue_message(msg: dict[str, Any]) -> tuple[bool, str]:
    """Minimal structural gate before a message enters the PA queue.

    Returns (ok, error). Keeps the dirty-data-out-of-the-queue guarantee that
    the old validate_queue_message gave, without the JSON decision machinery.
    """
    if not isinstance(msg, dict):
        return False, f"Expected dict, got {type(msg).__name__}."
    msg_type = msg.get("type")
    if msg_type not in VALID_QUEUE_MESSAGE_TYPES:
        return False, f'Invalid message type "{msg_type}".'
    if msg_type == "user_message":
        has_id = bool(msg.get("msg_id") or msg.get("task_id"))
        missing = [f for f in ("channel", "prompt") if not msg.get(f)]
        if not has_id:
            missing.insert(0, "msg_id")
        if missing:
            return False, f'user_message missing required fields: {", ".join(missing)}.'
    elif msg_type in ("agent_completed", "agent_failed"):
        missing = [f for f in ("task_id", "channel") if not msg.get(f)]
        if missing:
            return False, f'{msg_type} missing required fields: {", ".join(missing)}.'
    elif msg_type == "scheduled_task":
        missing = [f for f in ("msg_id", "schedule_id", "prompt") if not msg.get(f)]
        if missing:
            return False, f'scheduled_task missing required fields: {", ".join(missing)}.'
    elif msg_type == "recovered_failed_task":
        missing = [f for f in ("task_id", "channel", "original_prompt") if not msg.get(f)]
        if missing:
            return False, f'recovered_failed_task missing required fields: {", ".join(missing)}.'
    elif msg_type == "worker_done":
        # conv 归属至少要有 conv_key 或 channel 之一，否则无从路由回会话/投递。
        if not (msg.get("conv_key") or msg.get("channel")):
            return False, "worker_done missing conv attribution (conv_key/channel)."
    return True, ""

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


def _render_domain_peek(peek: dict[str, Any] | None) -> str:
    """Render a domain peek payload as compact prior-context for sub-agent bootstrap."""
    if not peek:
        return ""
    lines: list[str] = []
    domain = peek.get("domain") or ""
    lines.append(f"\nDomain 先验摘要 ({domain})")
    sess_count = peek.get("session_count")
    insi_count = peek.get("insight_count")
    last = peek.get("last_accessed")
    if sess_count is not None or insi_count is not None or last:
        lines.append(
            f"  status={peek.get('status')} sessions={sess_count} insights={insi_count} last={last}"
        )

    insights = peek.get("top_insights") or []
    if insights:
        lines.append("  Top insights:")
        for ins in insights:
            payload = (ins.get("payload") or "").replace("\n", " ").strip()
            if len(payload) > 160:
                payload = payload[:157] + "..."
            lines.append(
                f"    - [{ins.get('type')}] (conf={ins.get('confidence')}) {payload}"
            )

    sessions = peek.get("recent_sessions") or []
    if sessions:
        lines.append("  Recent sessions:")
        for s in sessions:
            sid = s.get("session_id") or ""
            head = (s.get("summary_head") or "").replace("\n", " | ")
            if len(head) > 120:
                head = head[:117] + "..."
            lines.append(f"    - {sid} {head}")
    lines.append("")
    return "\n".join(lines) + "\n"


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

    @staticmethod
    def _resolve_thread_id(msg: dict) -> str | None:
        """Resolve which resident session a queue message routes to (Phase 3: conv_key).

        去账本后路由退化成纯 conv_key：入站消息在 ingestion 时已派生 ``conv_key``
        并随消息携带；这里直接读它。无 conv_key（scheduled / internal / reflection
        等无会话单元的消息）返回 None → 路由到 fallback 常驻会话。
        """
        conv_key = msg.get("conv_key")
        if conv_key:
            return str(conv_key)
        # 兼容旧字段名 thread_id（worker_done / 内部消息可能仍带）。
        tid = msg.get("thread_id")
        return str(tid) if tid else None

    @staticmethod
    def _set_msg_thread_id(msg: dict, thread_id: str | None) -> None:
        """Backfill thread_id on msg dict for downstream tracing."""
        if thread_id is not None:
            msg["thread_id"] = thread_id

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

    async def _queue_consumer_loop(self) -> None:
        """Router loop: drain queue, derive conv_key, fan out to per-conv workers.

        Phase 4 (删 claude-p): the resident tmux session IS the PA.去喂料门后这里
        从「串行派发」改成「路由分发」：把每条消息按 conv_key 路由到各自的子队列，
        每个 conv 一条独立 worker 协程串行处理（保序）但跨 conv 并发——一个 conv 跑
        长回合（含「先回稍等、后台 worker 续干」）不再阻塞其他 conv 的派发与回复。
        投递仍由 transcript 持续转发器逐 conv 独立完成，与本路由解耦。
        """
        logger.info("PA queue router started (per-conv concurrent dispatch)")
        while True:
            try:
                first = await self._message_queue.get()
                await asyncio.sleep(0.1)

                messages = [first]
                while not self._message_queue.empty():
                    try:
                        messages.append(self._message_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Resolve conv_key for each message, group by conv_key.
                from collections import defaultdict
                grouped: dict[str | None, list[dict]] = defaultdict(list)
                for m in messages:
                    tid = self._resolve_thread_id(m)
                    self._set_msg_thread_id(m, tid)
                    grouped[tid].append(m)

                # 路由到各 conv 的子队列，并确保该 conv 有 worker 在跑。
                for tid, group in grouped.items():
                    q = self._conv_queues.get(tid)
                    if q is None:
                        q = asyncio.Queue()
                        self._conv_queues[tid] = q
                    q.put_nowait(group)
                    self._ensure_conv_worker(tid)

            except asyncio.CancelledError:
                logger.info("PA queue router cancelled")
                raise
            except Exception:
                logger.exception("Queue router error")
                await asyncio.sleep(1)

    def _ensure_conv_worker(self, tid: str | None) -> None:
        """确保该 conv 有一条活 worker 协程；已死/不存在则（重）建。"""
        t = self._conv_workers.get(tid)
        if t is None or t.done():
            self._conv_workers[tid] = asyncio.create_task(self._conv_worker_loop(tid))

    async def _conv_worker_loop(self, tid: str | None) -> None:
        """单个 conv 的 worker：串行消费本 conv 子队列，逐组 ``_dispatch_group_tmux``。

        闲置超阈值自行退出回收 worker，子队列保留供下条消息复用（NEVER 删队列，
        避免与 router 的 put 竞态丢消息）；退出后下条路由到该 conv 时由
        ``_ensure_conv_worker`` 的 done 分支重建。
        """
        q = self._conv_queues[tid]
        idle_exit_s = 300.0
        while True:
            try:
                try:
                    group = await asyncio.wait_for(q.get(), timeout=idle_exit_s)
                except TimeoutError:
                    if q.empty():
                        self._conv_workers.pop(tid, None)
                        return
                    continue
                await self._dispatch_group_tmux(tid, group)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("conv worker error (thread=%s)", tid)
                await asyncio.sleep(1)

    def _format_queue_messages(self, messages: list[dict[str, Any]]) -> str:
        """Format a batch of queued messages into a single text block for PA."""
        now = datetime.now()
        msg_parts: list[str] = []
        msg_parts.append(PA_QUEUE_TIME_HEADER_TEMPLATE.format(
            current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
        ))

        for msg in messages:
            msg_type = msg.get("type", "unknown")
            msg_parts.append("")

            if msg_type == "user_message":
                recovered_note = PA_QUEUE_RECOVERED_NOTE if msg.get("_recovered") else ""
                channel_name = msg.get("channel", "?")
                reply_ctx = msg.get("reply_context") or {}
                chat_name = reply_ctx.get("chat_name")
                group_line = (
                    PA_QUEUE_GROUP_LINE_TEMPLATE.format(chat_name=chat_name)
                    if chat_name else ""
                )

                msg_parts.append(PA_MESSAGE_TEMPLATE.format(
                    channel=channel_name,
                    channel_message_id=msg.get("channel_message_id", msg.get("msg_id", "?")),
                    prompt=msg.get("prompt", ""),
                    group_line=group_line,
                    received_at=msg.get("received_at") or "unknown",
                ) + recovered_note)

            elif msg_type == "agent_completed":
                outputs = msg.get("output_files", [])
                outputs_section = (
                    PA_QUEUE_OUTPUTS_LINE_TEMPLATE.format(outputs_list=", ".join(outputs))
                    if outputs else ""
                )
                logs_section = self._format_logs_section(msg.get("recent_logs", []))

                msg_parts.append(PA_AGENT_COMPLETED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    run_id=msg.get("run_id", "?"),
                    session_id=msg.get("session_id", "?"),
                    result_summary=msg.get("result_summary", "(无)"),
                    outputs_section=outputs_section,
                    recent_logs_section=logs_section,
                    event_at=msg.get("event_at") or "unknown",
                ))

            elif msg_type == "agent_failed":
                logs_section = self._format_logs_section(msg.get("recent_logs", []))

                msg_parts.append(PA_AGENT_FAILED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    run_id=msg.get("run_id", "?"),
                    session_id=msg.get("session_id", "?"),
                    result_summary=msg.get("result_summary", "(无)"),
                    recent_logs_section=logs_section,
                    event_at=msg.get("event_at") or "unknown",
                ))

            elif msg_type == "scheduled_task":
                recipe = msg.get("recipe")
                recipe_line = (
                    PA_QUEUE_RECIPE_LINE_TEMPLATE.format(recipe=recipe)
                    if recipe else ""
                )
                last_status = msg.get("last_status")
                last_status_line = (
                    PA_QUEUE_LAST_STATUS_LINE_TEMPLATE.format(last_status=last_status)
                    if last_status else ""
                )
                msg_channel = msg.get("channel", "schedule")
                msg_parts.append(PA_SCHEDULED_TASK_TEMPLATE.format(
                    msg_id=msg.get("msg_id", "?"),
                    channel=msg_channel,
                    schedule_id=msg.get("schedule_id", "?"),
                    schedule_name=msg.get("schedule_name", "?"),
                    prompt=msg.get("prompt", ""),
                    recipe_line=recipe_line,
                    last_status_line=last_status_line,
                    run_count=msg.get("run_count", 0),
                    fired_at=msg.get("triggered_at") or "unknown",
                ))
                # Phase finish: scheduled_task reply_context is now carried inline on
                # board.Source (ingest_scheduled writes it through Ingestor) and on the
                # queue dict above. No separate cache_message shim needed.
                if msg.get("msg_id") and msg.get("schedule_id"):
                    self._schedule_msg_map[msg["msg_id"]] = msg["schedule_id"]

            elif msg_type in ("reply_failed", "task_failed"):
                if msg.get("content"):
                    msg_parts.append(msg["content"])
                else:
                    msg_parts.append(PA_REPLY_FAILED_TEMPLATE.format(
                        task_id=msg.get("task_id", "?"),
                        channel=msg.get("channel", "?"),
                        error=msg.get("error", "unknown"),
                        reply_text=msg.get("reply_text", msg.get("original_text", "")),
                    ))

            elif msg_type == "recovered_failed_task":
                msg_parts.append(PA_RECOVERED_FAILED_TASK_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    original_error=msg.get("original_error", "unknown"),
                    original_prompt=msg.get("original_prompt", ""),
                ))

            elif msg_type == "worker_done":
                # Phase 3: worker(frago agent start 起的 sub-agent)完成重入。带 conv
                # 归属 + 结果摘要，PA 读完组织最终回复。无专用模板，用简洁自然语言块。
                status = msg.get("status", "completed")
                summary = msg.get("result_summary") or msg.get("summary") or "(无摘要)"
                outputs = msg.get("output_files") or []
                outputs_line = f"\n输出文件: {', '.join(outputs)}" if outputs else ""
                msg_parts.append(
                    f"[worker 完成] agent_type={msg.get('agent_type', '?')} "
                    f"status={status} worker={msg.get('worker_id', '?')}\n"
                    f"结果摘要:\n{summary}{outputs_line}\n"
                    f"（这是你之前派出去的 worker 跑完后的回传，读完组织最终回复给用户。）"
                )

            elif msg_type == "resume_failed":
                from frago.server.services.pa_prompts import (
                    PA_RESUME_FAILED_TEMPLATE,
                )
                msg_parts.append(PA_RESUME_FAILED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    reason=msg.get("reason", "unknown"),
                    detail=msg.get("detail", "") or f"(original prompt: {msg.get('original_prompt', '')[:200]})",
                ))

            elif msg_type == "run_failed":
                from frago.server.services.pa_prompts import (
                    PA_RUN_FAILED_TEMPLATE,
                )
                msg_parts.append(PA_RUN_FAILED_TEMPLATE.format(
                    msg_id=msg.get("msg_id", "-") or "-",
                    task_id=msg.get("task_id", "-") or "-",
                    reason=msg.get("reason", "unknown"),
                    detail=msg.get("detail", ""),
                ))

            else:
                msg_parts.append(PA_QUEUE_UNKNOWN_FALLBACK_TEMPLATE.format(
                    msg_type=msg_type,
                    msg_json=json.dumps(msg, ensure_ascii=False, default=str),
                ))

        return PA_MERGED_MESSAGES_TEMPLATE.format(
            count=len(messages),
            messages_body="\n".join(msg_parts),
        )

    @staticmethod
    def _format_logs_section(recent_logs: list[str]) -> str:
        """Format recent log lines into PA_QUEUE_LOGS_SECTION_TEMPLATE body."""
        if not recent_logs:
            return ""
        body = "\n".join(f"  {line}" for line in recent_logs)
        return PA_QUEUE_LOGS_SECTION_TEMPLATE.format(logs_body=body)

    # -- heartbeat --

    def _load_watch_config(self) -> dict[str, Any]:
        """Load Phase 6 transcript-watch / idle config from config.json."""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                pa = raw.get("primary_agent") or {}
                user = {**(pa.get("watch") or {}), **(pa.get("idle") or {})}
                return {**WATCH_DEFAULTS, **user}
        except (json.JSONDecodeError, OSError):
            pass
        return dict(WATCH_DEFAULTS)

    def _load_heartbeat_config(self) -> dict[str, Any]:
        """Load heartbeat config from config.json."""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                user_config = (raw.get("primary_agent") or {}).get("heartbeat") or {}
                return {**HEARTBEAT_DEFAULTS, **user_config}
        except (json.JSONDecodeError, OSError):
            pass
        return dict(HEARTBEAT_DEFAULTS)

    def _load_warm_convs(self) -> list[str]:
        """读 config 里 primary_agent.warm_convs（最近在前的 conv_key 列表）。"""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                convs = (raw.get("primary_agent") or {}).get("warm_convs") or []
                return [str(c) for c in convs if c]
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _record_warm_conv(self, conv_key: str) -> None:
        """把 conv_key 提到 warm_convs 最前、去重、截断到上限，持久化回 config.json。

        read-modify-write 只改 ``primary_agent.warm_convs`` 一个字段，NEVER 整体覆盖
        把别的字段冲掉。列表无变化（已在最前）时不写盘，避免每次派发都打 IO。
        """
        if not conv_key or conv_key == PaTmuxRunner_FALLBACK:
            return
        # 只记真实 channel 会话：conv_key 形如 "<已注册channel>:<id>"（feishu:/voice:/
        # email:/slack:）。内部消息的裸 ULID thread_id（反思 tick 等）和无 channel 前缀的
        # 测试夹具值（thread-A）一律不记——否则 warm_convs 会被反思 ULID 持续刷满、把真实
        # 会话挤出去，预热还会白拉一堆空会话。
        from frago.server.services.routing.conv_key import CONV_KEY_DERIVERS

        channel = conv_key.split(":", 1)[0] if ":" in conv_key else ""
        if channel not in CONV_KEY_DERIVERS:
            return
        try:
            raw = (
                json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if CONFIG_FILE.exists()
                else {}
            )
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(raw, dict):
            return
        pa = raw.get("primary_agent")
        if not isinstance(pa, dict):
            pa = {}
        old = [str(c) for c in (pa.get("warm_convs") or []) if c]
        new = [conv_key] + [c for c in old if c != conv_key]
        new = new[:WARM_CONVS_MAX]
        if new == old:
            return
        pa["warm_convs"] = new
        raw["primary_agent"] = pa
        try:
            CONFIG_FILE.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logger.debug("warm_convs persist failed", exc_info=True)

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

    async def _start_heartbeat(self) -> None:
        config = self._load_heartbeat_config()
        if not config.get("enabled", True):
            logger.info("PA heartbeat disabled by config")
            return

        self._heartbeat_stop.clear()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                interval=config["interval_seconds"],
                initial_delay=config["initial_delay_seconds"],
            )
        )
        logger.info("PA heartbeat started (interval=%ds)", config["interval_seconds"])

    async def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            return
        self._heartbeat_stop.set()
        self._heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat_task
        self._heartbeat_task = None
        logger.info("PA heartbeat stopped")


    async def _heartbeat_loop(self, interval: int, initial_delay: int) -> None:
        logger.info("Heartbeat loop: waiting %ds initial delay", initial_delay)
        await asyncio.sleep(initial_delay)
        logger.info("Heartbeat loop: starting main loop")
        while not self._heartbeat_stop.is_set():
            try:
                await self._send_heartbeat()
            except Exception:
                logger.exception("Heartbeat failed")
            try:
                await asyncio.wait_for(
                    self._heartbeat_stop.wait(), timeout=interval
                )
                break
            except TimeoutError:
                continue

    async def _send_heartbeat(self) -> None:
        """Heartbeat: keep the queue consumer alive + idle rotation check.

        Phase 4: with the resident tmux backend as the sole path, turn accounting
        and rotation happen inline in ``_dispatch_group_tmux``. The heartbeat only
        resurrects a dead consumer task and triggers idle rotation for any conv
        whose token window crossed the threshold while sitting quiet.
        """
        logger.info("Heartbeat [%d]: tick", self._heartbeat_seq)

        if self._queue_consumer_task is None or self._queue_consumer_task.done():
            if self._queue_consumer_task and self._queue_consumer_task.done():
                exc = self._queue_consumer_task.exception() if not self._queue_consumer_task.cancelled() else None
                logger.error(
                    "Queue consumer task died (exc=%s), restarting",
                    exc,
                )
            self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())
            logger.info("Queue consumer task restarted by heartbeat [%d]", self._heartbeat_seq)

        if self._busy:
            logger.debug("Heartbeat skipped: PA is busy")
            return

        # Idle rotation check: iterate all conv keys with accrued token counters.
        for tid in list(self._accumulated_tokens.keys()):
            if self._should_rotate(tid):
                await self._compact_tmux_session(tid)
        if self._should_rotate(None):
            await self._compact_tmux_session(None)

        # Phase 6: 周期回收真空闲超阈值的常驻会话（关 tmux）。仅当真空闲才参与回收，
        # 在跑活的会话返回 None 永不回收；回收后再来消息走 Phase 5 --resume 接回。
        await self._evict_idle_sessions()

        # 去账本：不再 recover board pending tasks，也不再托管 executor 回路。
        # 会话按需建；跨重启连续性交给 claude 原生 transcript。
        self._heartbeat_seq += 1

    async def _evict_idle_sessions(self) -> None:
        """heartbeat 周期回收真空闲超阈值的常驻会话。

        idle_age_fn：仅当会话真空闲（四信号成立）且能取到 transcript 终结时间戳时，
        才以「自该时间戳起的静默秒数」计；仍在干活 / 无锚点返回 None → NEVER 回收。
        """
        runner = self._pa_tmux_runner
        if runner is None:
            return
        from datetime import UTC

        from frago.agent_driver.drivers.claude import is_truly_idle

        silence = float(self._watch_config["idle_silence_seconds"])
        timeout_s = float(self._watch_config["idle_evict_seconds"])
        now = datetime.now(UTC)

        def idle_age(session: Any) -> float | None:
            if not is_truly_idle(session, silence_s=silence):
                return None
            # idle 时长用「会话在本池里自己的最后活动时间」(open/send 刷新)，NEVER 用
            # transcript 时间戳——预热是 --resume 一个旧 transcript，其最后记录可能几小时前，
            # 那样会让刚预热的会话被秒判「闲了几小时」当场回收（预热与回收咬死）。
            last = getattr(session, "last_active_at", None)
            if last is None:
                return None
            return (now - last).total_seconds()

        try:
            evicted = await asyncio.to_thread(
                runner._pool.evict_idle, idle_age, timeout_s
            )
        except Exception:
            logger.debug("PA idle eviction error", exc_info=True)
            return
        for sid in evicted:
            logger.info("PA idle eviction: closed resident session conv=%s", sid)
            # 重置该 key 的轮换计数（与 rotation 一致），下条消息触发干净重建 + resume。
            self._total_turns.pop(sid, None)
            self._accumulated_tokens.pop(sid, None)
            self._last_delivered_marker.pop(sid, None)
            self._watch_mtime.pop(sid, None)

    # -- PA output handling (Phase 2: 透传，无 JSON 决策协议) --

    @staticmethod
    def _route_for_group(group: list[dict]) -> dict[str, Any]:
        """Pick the representative inbound message that carries the reply target.

        Prefers a message with a ``channel``; falls back to the first dict.
        Used as the ``route`` arg to ``deliver`` (channel + reply_context + ids).
        """
        for m in group:
            if isinstance(m, dict) and m.get("channel"):
                return m
        return group[0] if group and isinstance(group[0], dict) else {}

    @staticmethod
    def _warn_bareword_paths(
        text: str, attachments: list[dict[str, Any]], conv_key: str,
    ) -> None:
        """兜底观测：扫正文里「像存在的文件路径却没进 outbox」的，记日志。

        agent 漏调 ``frago agent attach`` 直接在正文写路径时，用户收到的还是路径
        文字而非附件。这里只记日志（可观测 + 后续补救线索），NEVER 自动投递——
        嗅探出的路径未必是要交付的制品（可能是引用的源码、日志等）。
        """
        import re

        attached = {Path(a.get("path", "")).resolve() for a in attachments}
        # 绝对路径 / ~ 起头 / 带至少一个目录分隔且含扩展名的相对路径。
        candidates = set(re.findall(r"(?:~|/|\.{1,2}/)[\w./\-]+\.\w+", text))
        missed: list[str] = []
        for cand in candidates:
            try:
                p = Path(cand).expanduser()
            except (OSError, ValueError):
                continue
            if p.exists() and p.is_file() and p.resolve() not in attached:
                missed.append(str(p))
        if missed:
            logger.warning(
                "deliver: %d bareword path(s) in text exist but were not attached "
                "(conv=%s) — agent should use `frago agent attach`: %s",
                len(missed), conv_key, missed,
            )

    async def deliver(self, text: str, route: dict[str, Any]) -> None:
        """Push the agent's natural-language text back to the source channel.

        Phase 2: the resident agent's final text IS the reply content. ``route``
        is the inbound queue message (carries channel + reply_context, optionally
        task_id / msg_id for board fallback). Empty text is skipped — no empty
        reply is pushed (Edge Cases: agent 最终输出为空 → 跳过、记日志、不重试).
        """
        from frago.server.services.trace import trace_entry

        text = (text or "").strip()
        channel = route.get("channel", "") or route.get("type", "")
        if not text:
            logger.info("deliver skipped: empty agent output (channel=%s)", channel)
            return
        if not channel:
            logger.warning("deliver skipped: no channel on route (route keys=%s)", list(route))
            return
        if channel in NON_DELIVERABLE_CHANNELS:
            logger.info(
                "deliver skipped: internal channel %s has no outbound destination "
                "(text dropped, no reply_failed re-enqueued)", channel,
            )
            return

        conv_key = route.get("conv_key")
        reply_context = (
            route.get("reply_context")
            or (self._reply_context_cache.get(f"conv:{conv_key}") if conv_key else None)
            or self._reply_context_cache.get(f"channel:{channel}")
        )
        task_id = route.get("task_id", "") or ""
        msg_id = route.get("msg_id", "") or ""

        # Phase 8（spec 20260627 交付即核心）：转发 pane 文本前 drain 该 conv 的
        # outbox——agent 经 ``frago agent attach`` 登记的文件作真附件随文本一起送达。
        # 兜底：扫正文里「像文件路径却没进 outbox」的，记日志（frago-core 现无 Stop
        # 事件接「收尾校验」，先放交付层观测；自动补救为后续 follow-up）。
        attachments: list[dict[str, Any]] = []
        if conv_key:
            from frago.server.services import pa_outbox

            attachments = await asyncio.to_thread(pa_outbox.drain, conv_key)
            self._warn_bareword_paths(text, attachments, conv_key)

        result = await asyncio.to_thread(
            self._lifecycle.deliver,
            channel,
            {"text": text},
            reply_context=reply_context,
            attachments=attachments,
            task_id=task_id,
            msg_id=msg_id,
        )

        if result.get("status") == "ok":
            _reply_data = {
                "task_id": task_id or "",
                "msg_id": msg_id or "",
                "channel": channel or "",
                "reply_text": text,
            }
            await self._broadcast_pa_event("pa_reply", _reply_data)
            from frago.server.services.trace import trace as _trace
            _trace(msg_id, task_id, "pa", f"回复 {channel}: {text[:80]}",
                   data={"event_type": "pa_reply", **_reply_data})
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=task_id or None,
                data={"action": "reply", "status": "ok",
                      "channel": channel, "text_len": len(text)},
                msg_id=msg_id or None,
                event=f"reply 成功: {channel}",
            )
        elif result.get("status") == "error":
            error_detail = result.get("error", "unknown")
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=task_id or None,
                data={"action": "reply", "status": "failed",
                      "reason": "send_failed", "detail": error_detail,
                      "channel": channel},
                msg_id=msg_id or None,
                event=f"reply 失败: {error_detail[:80]}",
            )
            await self.enqueue_message({
                "type": "reply_failed",
                "task_id": task_id,
                "channel": channel,
                "error": error_detail,
                "original_text": text,
            })

    def _writeback_schedules(self, group: list[dict]) -> None:
        """Mark scheduled_task entries in this group as handled after a turn.

        Phase 2: with the JSON decision protocol gone, schedule status no longer
        keys off run/reply actions. A delivered turn that consumed a scheduled_task
        marks that schedule ``dispatched`` so the scheduler doesn't see it as stuck.
        """
        if not self._scheduler_service:
            return
        for m in group:
            if not isinstance(m, dict):
                continue
            sid = self._schedule_msg_map.pop(m.get("msg_id", ""), None)
            if sid:
                self._scheduler_service.update_schedule_result(sid, "dispatched")


    # -- helpers --

    # -- Phase 3: tmux 常驻后端执行路径 --

    # -- Phase 6: transcript 持续转发器（修「漏接真结果」根因）--

    def _eval_conv_transcript(self, conv_key: str) -> Any | None:
        """读该 conv 常驻会话的 claude transcript，返回 TurnCompletion（无则 None）。

        定位走 ``locate_transcript(uuid5(conv_key), cwd=$HOME)``——与 claude driver
        的 completion_probe 同一套派生，路径在起会话那刻就锁定。
        """
        from frago.agent_driver.drivers.claude import _claude_session_uuid
        from frago.server.services.transcript_completion import (
            evaluate_file,
            locate_transcript,
        )

        sid = _claude_session_uuid(conv_key)
        path = locate_transcript(sid, cwd=str(Path.home()))
        if path is None:
            return None
        return evaluate_file(path)

    def _watch_poll(
        self, conv_key: str, since_mtime: float | None
    ) -> tuple[float | None, Any | None]:
        """转发器专用：stat transcript，mtime 没变就跳过全量解析（省每拍重读几 MB）。

        返回 ``(mtime, TurnCompletion | None)``：mtime 与上拍相同 → ``(mtime, None)``
        不解析；变了 / 首次 → 全量 ``evaluate_file``；文件不存在 → ``(None, None)``。
        stat 是微秒级，evaluate 是 O(文件大小)（十几 MB ~ 几十 ms），故空闲期只付 stat。
        """
        import os as _os

        from frago.agent_driver.drivers.claude import _claude_session_uuid
        from frago.server.services.transcript_completion import (
            evaluate_file,
            locate_transcript,
        )

        sid = _claude_session_uuid(conv_key)
        path = locate_transcript(sid, cwd=str(Path.home()))
        if path is None:
            return None, None
        try:
            mtime = _os.path.getmtime(path)
        except OSError:
            return None, None
        if since_mtime is not None and mtime <= since_mtime:
            return mtime, None  # 未变，跳过全量解析
        return mtime, evaluate_file(path)

    def _seed_marker(self, conv_key: str | None) -> None:
        """把该 conv 的 last_delivered_marker 锚到 transcript 当前 tail（baseline）。

        喂真实 prompt 之前调用：bootstrap 那一轮（及 --resume 载回的历史）的终结
        marker 都落在 baseline 之内，转发器只投 baseline 之后新增的终答。
        """
        if not conv_key:
            return
        tc = self._eval_conv_transcript(conv_key)
        self._last_delivered_marker[conv_key] = tc.last_uuid if tc else None

    async def _transcript_watch_loop(self) -> None:
        """每个常驻 PA 会话的 transcript 持续转发器（单任务轮询全部活会话）。

        把「投递」从「喂的那一轮」解耦：PA 常「先回一句稍等、再用自己的 harness 异步
        续干」，真正完整结果在第一个 end_turn 之后才写进同一 transcript。本循环持续
        盯每个活会话的 transcript，每出现一条新的、答完的 assistant 终答就投递、推进
        marker，每个 marker 只投一次。NEVER 转发 user 记录 / 工具调用 / thinking /
        流式半截——只投 evaluate_file 判 done 的终答。
        """
        interval = float(self._watch_config["watch_interval_seconds"])
        logger.info("PA transcript watcher started (interval=%.1fs)", interval)
        while True:
            try:
                await asyncio.sleep(interval)
                await self._watch_tick()
            except asyncio.CancelledError:
                logger.info("PA transcript watcher cancelled")
                raise
            except Exception:
                logger.exception("PA transcript watcher tick error")

    async def _watch_tick(self) -> None:
        """转发器一拍：遍历活会话，投递每条新终答。"""
        runner = self._pa_tmux_runner
        if runner is None:
            return
        for key in runner.active_session_keys():
            if key == PaTmuxRunner_FALLBACK:
                continue  # fallback 无 conv 归属，无处投递
            conv_key = key
            if conv_key in self._bootstrapping_convs or conv_key in self._compacting_convs:
                continue  # baseline 未锚定 / 正在 /compact，跳过本拍避免误投该轮产出
            route = self._conv_route_cache.get(conv_key)
            if not route:
                continue
            since = self._watch_mtime.get(conv_key)
            mtime, tc = await asyncio.to_thread(self._watch_poll, conv_key, since)
            if mtime is not None:
                self._watch_mtime[conv_key] = mtime
            if tc is None or not tc.done:
                continue  # 文件没变（stat 短路，未解析）/ 解析了但本轮未答完
            marker = tc.last_uuid
            if not marker or self._last_delivered_marker.get(conv_key) == marker:
                continue  # 无新终答 / 已投过该 marker
            # 推进 marker 后再投：投递失败不回退 marker，避免失败重投把同一终答刷屏。
            self._last_delivered_marker[conv_key] = marker
            text = (tc.final_text or "").strip()
            if text:
                logger.info(
                    "Transcript watcher: delivering new终答 (%d chars, conv=%s)",
                    len(text), conv_key,
                )
                await self.deliver(text, route)

    # -- Phase 6: 真空闲判定（喂料门 + 回收共用）--

    def _is_truly_idle(self, session_key: str) -> bool:
        """该 key 的常驻会话当前是否真空闲（四信号缺一不可）。无活会话视为空闲。"""
        runner = self._pa_tmux_runner
        if runner is None:
            return True
        session = runner.session(session_key)
        if session is None:
            return True
        from frago.agent_driver.drivers.claude import is_truly_idle

        return is_truly_idle(
            session, silence_s=float(self._watch_config["idle_silence_seconds"])
        )

    async def _wait_until_truly_idle(self, session_key: str) -> None:
        """等到该会话真空闲再返回（喂料门 / 回合收尾用）。

        给足够大的上限 + 超时日志，别死等一个永远不空闲的会话。无活会话立即返回。
        """
        runner = self._pa_tmux_runner
        if runner is None or runner.session(session_key) is None:
            return
        max_wait = float(self._watch_config["feeding_gate_max_seconds"])
        poll = float(self._watch_config["idle_poll_seconds"])
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait
        while True:
            if await asyncio.to_thread(self._is_truly_idle, session_key):
                return
            if loop.time() >= deadline:
                logger.warning(
                    "feeding gate: waited %.0fs for conv=%s to go truly idle, "
                    "proceeding anyway", max_wait, session_key,
                )
                return
            await asyncio.sleep(poll)

    def _get_pa_tmux_runner(self) -> Any:
        """Lazily construct the resident-tmux PA executor (backend=="tmux")."""
        if self._pa_tmux_runner is None:
            from frago.server.services.pa_tmux_runner import PaTmuxRunner

            self._pa_tmux_runner = PaTmuxRunner(cwd=str(Path.home()))
        return self._pa_tmux_runner

    async def _dispatch_group_tmux(self, tid: str | None, group: list[dict]) -> None:
        """Feed a message group to PA's resident session; delivery is decoupled (Phase 6).

        喂 prompt + 等到真空闲再 return——本方法不再负责投递。Phase 6（spec 20260627）
        把「投递」从「喂的那一轮」解耦：PA 常「先回一句稍等、再用自己的 harness 异步
        续干」，真结果在第一个 end_turn 之后才落进同一 transcript。投递的唯一来源是
        transcript 持续转发器（``_transcript_watch_loop``），ok 分支 NEVER 再自己
        ``deliver``（否则与转发器双投）。

        本方法的职责收敛为三步：① 喂料门——喂之前等该会话真空闲，别插话打断在跑的活；
        ② 喂 prompt（on_ready 锚定转发器 baseline，使本轮及其后台续干的终答都被转发）；
        ③ 等到真空闲再 return——return 只为给下一组喂料让路。Phase 1 的 needs_input 分支
        仍单独保留（它不是 transcript 终答，走 _deliver_needs_input）。
        """
        from frago.server.services.trace import trace_entry

        for _m in group:
            if not isinstance(_m, dict):
                continue
            _mtype = _m.get("type", "")
            _channel = _m.get("channel", "") or _mtype
            trace_entry(
                origin="internal",
                subkind="pa",
                data_type="message",
                thread_id=_m.get("thread_id"),
                parent_id=None,
                task_id=_m.get("task_id"),
                data={"queue_msg_type": _mtype, "channel": _m.get("channel")},
                msg_id=_m.get("msg_id"),
                role="pa",
                event=f"收到消息队列: {_channel}",
            )

        merged = self._format_queue_messages(group)
        bootstrap, _ = self._build_bootstrap_prompt(
            thread_id=tid, create_reason="message_dispatch"
        )
        full_bootstrap = PRIMARY_AGENT_SYSTEM_PROMPT + "\n\n" + bootstrap
        session_key = tid or PaTmuxRunner_FALLBACK

        # 真实 conv_key（非 None / 非 __fallback__）这条路径：把它提到 warm_convs 最前、
        # 去重、截断到上限并持久化，供 server 重启后预热——消首句冷启动。
        if tid:
            self._record_warm_conv(tid)

        runner = self._get_pa_tmux_runner()
        input_len = len(merged)
        logger.info(
            "Queue consumer [tmux]: sending %d merged messages to PA (thread=%s, %d chars)",
            len(group), tid, len(merged),
        )

        from frago.agent_driver.tmux_session import TmuxStartupError

        # 前置喂料门已去除：真实 claude 客户端对提前输入是「进客户端自带消息队列、
        # 不打断在跑回合」，无需等真空闲再喂；且同一 conv 的下一组派发由本方法末尾的
        # 收尾 _wait_until_truly_idle 保证会话已空闲，前置门对同 conv 纯属冗余。跨 conv
        # 不再共享等待——各 conv 由独立 worker 协程并发派发。

        # on_ready：bootstrap 注入后、真实 prompt 提交前锚定转发器 baseline。期间把
        # conv 标记 bootstrapping，转发器跳过该 conv，规避「bootstrap 回复被当新终答
        # 抢先投出」的竞态；seed 完成即清标记，转发器恢复盯本轮终答。
        if tid:
            self._bootstrapping_convs.add(tid)

        def _on_ready(_key: str) -> None:
            self._seed_marker(tid)
            if tid:
                self._bootstrapping_convs.discard(tid)

        try:
            result = await asyncio.to_thread(
                runner.run, session_key, merged,
                bootstrap=full_bootstrap, on_ready=_on_ready,
            )
        except TmuxStartupError:
            # 启动失败（认证墙 / 二进制缺失 / 撞 session-id 等），不是一轮超时。
            # 重投只会让同一具死会话反复重启失败 → 无限 re-enqueue 空转。故丢弃该轮
            # 并记 error；open() 已 kill 掉死壳、acquire 未把它放进池，不会留死会话被
            # 当活会话复用。下一条入站消息会触发干净重建（撞 id 那类下次走 --resume）。
            logger.exception(
                "PA tmux session failed to start (thread=%s); dropping this round "
                "to avoid infinite re-enqueue", tid,
            )
            if tid:
                self._bootstrapping_convs.discard(tid)
            return
        except Exception:
            logger.exception("PA tmux run failed (thread=%s), re-enqueueing group", tid)
            if tid:
                self._bootstrapping_convs.discard(tid)
            for m in group:
                await self._message_queue.put(m)
            return

        text = result.text or ""

        # Token accounting drives rotation (rough char/4 estimate).
        estimated_tokens = (input_len + len(text)) // 4
        if tid:
            self._total_turns[tid] = self._total_turns.get(tid, 0) + 1
            self._accumulated_tokens[tid] = self._accumulated_tokens.get(tid, 0) + estimated_tokens
        else:
            self._fallback_total_turns += 1
            self._fallback_accumulated_tokens += estimated_tokens

        # Phase 1: 撞上阻断门（认证墙 / agent 自抛的选择菜单）。把当轮可见提示组织成
        # "需要你选/确认…"投递回 chat，会话原样停在门上——NEVER 重入队列、NEVER
        # rotate（rotate 会驱逐会话、丢掉这道门）。用户的回选作为普通入站消息透传进
        # 同一 conv 把门推过，由 ok 分支清除挂起标记。
        if result.status == "needs_input":
            logger.info(
                "Queue consumer [tmux]: PA needs_input at blocking gate (thread=%s)", tid
            )
            self._suspended_convs.add(tid)
            await self._deliver_needs_input(tid, group, result.raw_delta)
            return

        self._suspended_convs.discard(tid)

        # Phase 6: ok 分支 NEVER 自己 deliver——投递已交给 transcript 持续转发器
        # （runner.run 在第一个 end_turn 就返回，但 PA 可能还在异步续干；转发器持续盯
        # transcript，本轮及后台续干产出的每条新终答它都会投）。这里只等到真空闲再
        # return，让喂料门给下一组让路、且确认后台 worker 已收尾后才轮换/回收。
        # 空输出不再重投：真结果可能稍后异步到达，重投会重复处理。
        runner_text_logged = len(text)
        logger.info(
            "Queue consumer [tmux]: turn fed; delivery deferred to watcher "
            "(first-end_turn %d chars, thread=%s)", runner_text_logged, tid,
        )
        self._writeback_schedules(group)

        # 等到真空闲再收尾：确保本轮（含异步续干）全部落定、转发器已投，再考虑轮换。
        await self._wait_until_truly_idle(session_key)

        # Rotation is token-driven; Phase 7: 就地驱动 /compact 真压上下文、会话保活，
        # 不再 evict+resume（那是白杀+全量重载、不压缩）。
        if self._should_rotate(tid):
            await self._compact_tmux_session(tid)

    # Phase 1: 阻断门可见 pane → "需要你选/确认"回复文本。raw_delta 在 needs_input
    # 分支下是整屏可见 pane（含 TUI 边框/页脚 chrome），抠掉纯装饰行只留菜单/问题。
    _GATE_CHROME = re.compile(
        r"^\s*(?:[╭╮╯╰│─┌┐└┘├┤┬┴┼]+\s*$|[╭╮╯╰┌┐└┘├┤┬┴┼].*"
        r"|—\s*for shortcuts|esc to interrupt|⏵|\?\s+for shortcuts)",
    )

    @classmethod
    def _format_needs_input_prompt(cls, raw_delta: str) -> str:
        lines = [
            ln.strip(" │").rstrip()
            for ln in (raw_delta or "").splitlines()
            if ln.strip() and not cls._GATE_CHROME.match(ln)
        ]
        menu = "\n".join(ln for ln in lines if ln).strip()
        if not menu:
            return "需要你确认才能继续，请回复你的选择。"
        return f"需要你选择 / 确认才能继续：\n\n{menu}"

    async def _deliver_needs_input(
        self, tid: str | None, group: list[dict], raw_delta: str
    ) -> None:
        """把阻断门提示作为一条普通回复投递回触发该轮的渠道。"""
        text = self._format_needs_input_prompt(raw_delta)
        route = self._route_for_group(group)
        channel = route.get("channel", "") or route.get("type", "")
        if not channel:
            logger.warning(
                "needs_input gate hit but no channel to reply (thread=%s); dropping prompt", tid
            )
            return
        await self.deliver(text, route)

    async def _compact_tmux_session(self, thread_id: str | None = None) -> None:
        """token-rotation 触发时就地驱动常驻会话执行 ``/compact`` 真压上下文（Phase 7）。

        旧 ``_rotate_tmux_session`` 是 evict+resume：Phase 5 之后下条消息全量 ``--resume``
        回原上下文，rotation 沦为「白杀一次 + 全量重载」、不压缩。真正压上下文的是
        claude 自己的 ``/compact``。本方法据此把 rotation 改成「驱动会话就地 /compact、
        会话保活 NEVER kill」：

        a. 等真空闲才发 ``/compact``（busy 不插话；超时则跳过本次、NEVER 回退 kill）。
        b. 标记该 conv compacting，转发器此窗口跳过它（避免把 /compact 那轮产出投出）。
        c. 发 ``/compact`` + 提交。
        d. 等 /compact 完成（再次真空闲）。
        e. ``_seed_marker`` 重锚 baseline + 清 _watch_mtime + 清 compacting 标记（与 b
           的转发器跳过共同构成「/compact 产出 NEVER 被投递」的双保险）。
        f. 重置该 conv 的 token/轮次计数、rotation_count+1，会话保活。
        """
        is_fallback = thread_id is None
        tag = f"thread={thread_id}" if thread_id else "fallback"
        session_key = thread_id or PaTmuxRunner_FALLBACK

        if is_fallback:
            count = self._fallback_rotation_count
        else:
            count = self._rotation_count.get(thread_id, 0)

        runner = self._get_pa_tmux_runner()

        # 无活会话：无可压缩，直接复位计数（下条消息走 --resume 干净重建）。
        if runner.session(session_key) is None:
            logger.info(
                "PA compact (%s): no live session, resetting counters only", tag
            )
            self._reset_rotation_counters(thread_id, count)
            return

        # a. 等真空闲——busy 不发 /compact；超时则跳过本次，NEVER 回退 kill。
        await self._wait_until_truly_idle(session_key)
        if not await asyncio.to_thread(self._is_truly_idle, session_key):
            logger.warning(
                "PA compact (%s): session not truly idle within window, "
                "skipping this compact (NEVER fall back to kill)", tag,
            )
            return

        logger.info("PA compact (%s, rotation_count=%d): driving /compact in place", tag, count)

        # b. 标记 compacting，转发器跳过该 conv（fallback 无 conv 归属，转发器本就跳过）。
        if thread_id:
            self._compacting_convs.add(thread_id)
        try:
            # c. 发 /compact + 提交。
            sent = await asyncio.to_thread(runner.compact, session_key)
            if not sent:
                logger.warning("PA compact (%s): session vanished before /compact", tag)
                return
            # d. 等 /compact 完成（再次真空闲）。
            await self._wait_until_truly_idle(session_key)
            # e. 重锚 baseline + 清 mtime（/compact 产出落在 baseline 之内、绝不转发）。
            self._seed_marker(thread_id)
            self._watch_mtime.pop(session_key, None)
        finally:
            if thread_id:
                self._compacting_convs.discard(thread_id)

        # f. 重置计数，会话保活（NEVER evict）。
        self._reset_rotation_counters(thread_id, count)

    def _reset_rotation_counters(self, thread_id: str | None, count: int) -> None:
        """复位该 conv 的 token/轮次计数并 rotation_count+1（compact / rotation 共用）。"""
        if thread_id is None:
            self._fallback_total_turns = 0
            self._fallback_accumulated_tokens = 0
            self._fallback_rotation_count = count + 1
        else:
            self._total_turns[thread_id] = 0
            self._accumulated_tokens[thread_id] = 0
            self._rotation_count[thread_id] = count + 1

    async def _rotate_tmux_session(self, thread_id: str | None = None) -> None:
        """Rotate a resident-tmux PA session: evict it and reset that key's counters.

        No subprocess exists in the tmux backend — rotation just evicts the
        resident session from the warm pool. The next ``run`` for this key
        re-injects bootstrap on a fresh resident session.
        """
        is_fallback = thread_id is None
        tag = f"thread={thread_id}" if thread_id else "fallback"
        session_key = thread_id or PaTmuxRunner_FALLBACK

        if is_fallback:
            count = self._fallback_rotation_count
        else:
            count = self._rotation_count.get(thread_id, 0)

        logger.info("PA tmux session rotation (%s, rotation_count=%d)", tag, count)

        try:
            self._get_pa_tmux_runner().evict(session_key)
        except Exception:
            logger.debug("PA tmux evict error for %s", tag, exc_info=True)

        if is_fallback:
            self._fallback_total_turns = 0
            self._fallback_accumulated_tokens = 0
            self._fallback_rotation_count = count + 1
        else:
            self._total_turns[thread_id] = 0
            self._accumulated_tokens[thread_id] = 0
            self._rotation_count[thread_id] = count + 1

    def _should_rotate(self, thread_id: str | None = None) -> bool:
        """Check if session rotation is needed for a given thread.

        ``thread_id=None`` checks fallback session.
        """
        if thread_id is None:
            turns = self._fallback_total_turns
            tokens = self._fallback_accumulated_tokens
        else:
            turns = self._total_turns.get(thread_id, 0)
            tokens = self._accumulated_tokens.get(thread_id, 0)
        if ROTATION_TURN_THRESHOLD is not None and turns >= ROTATION_TURN_THRESHOLD:
            return True
        return tokens >= ROTATION_TOKEN_THRESHOLD

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
