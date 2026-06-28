"""Ingestion scheduler — polls channels, ingests messages into TaskBoard.

Channels are config declarations (a pair of poll + notify recipes), not code components.
Adding a new channel requires zero code changes — just config + recipes.

The scheduler's job is:
1. Poll channels via recipes
2. Classify each new message into a thread (L1/L2 via thread_classifier)
3. Ingest into TaskBoard via ``Ingestor.ingest_external`` (single source of truth)
4. Enqueue the message to the PA message queue for immediate processing

Dedup is TaskBoard's responsibility: ``board.append_msg`` of the same msg_id
writes a ``duplicate_msg_ingest`` timeline entry instead of creating a second
Msg. Spec 20260512 v1.2 freeze: TaskStore + ingested_tasks.json are gone;
board.timeline.jsonl is the only persistence layer.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """A channel declaration from config.json."""

    name: str
    poll_recipe: str
    notify_recipe: str
    poll_interval_seconds: int = 120
    poll_timeout_seconds: int = 20
    # "poll" → periodic recipe invocation returning a message batch (default).
    # "stream" → spawn poll_recipe as a long-lived subprocess; each stdout line
    # is one `{"type": "message", ...}` event fed straight into ingest_message.
    mode: str = "poll"
    # False → skip this channel at startup (no poll loop). Lets a channel stay
    # documented in config.json without spamming the log when its secrets /
    # recipe aren't configured (e.g. email needing email/password).
    enabled: bool = True


class IngestionScheduler:

    def __init__(
        self,
        channels: list[ChannelConfig],
    ) -> None:
        self._channels = channels
        self._channel_tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()
        # Phase 3 (去账本): 渠道重投防御从 board.append_msg 线性扫描降级为轻量内存
        # seen-set（够用——只防 lark WS / email re-poll 的 msg_id 重复）。FIFO 截断
        # 防无界增长；重启丢失无妨（重启后渠道游标本就重置）。
        self._seen_msg_ids: dict[str, None] = {}
        self._seen_cap = 5000
        # Set by PrimaryAgentService after initialization
        self._pa_enqueue: asyncio.coroutines | None = None
        # Shared runner — avoids recreating RecipeRegistry + ExecutionStore per poll
        from frago.recipes.runner import RecipeRunner
        self._runner = RecipeRunner()

    def set_pa_enqueue(self, enqueue_fn: object) -> None:
        """Register the PA message queue enqueue function.

        Called by PrimaryAgentService during server startup so the scheduler
        can deliver messages to the PA queue without a circular import.
        """
        self._pa_enqueue = enqueue_fn

    async def start(self) -> None:
        if self._channel_tasks:
            logger.warning("IngestionScheduler already running")
            return
        self._stop_event.clear()
        for ch in self._channels:
            if ch.mode == "stream":
                task = asyncio.create_task(
                    self._stream_loop(ch),
                    name=f"ingestion-stream-{ch.name}",
                )
            else:
                task = asyncio.create_task(
                    self._channel_loop(ch),
                    name=f"ingestion-{ch.name}",
                )
            self._channel_tasks[ch.name] = task
        logger.info(
            "IngestionScheduler started (channels=%s)",
            [c.name for c in self._channels],
        )

    async def stop(self) -> None:
        if not self._channel_tasks:
            return
        self._stop_event.set()
        tasks_to_cancel = list(self._channel_tasks.values())
        for task in tasks_to_cancel:
            task.cancel()
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._channel_tasks.clear()
        logger.info("IngestionScheduler stopped")

    async def _channel_loop(self, ch: ChannelConfig) -> None:
        """Per-channel polling loop with its own interval."""
        await asyncio.sleep(5)  # Startup delay
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._poll_channel(ch),
                    timeout=ch.poll_timeout_seconds,
                )
            except TimeoutError:
                logger.error(
                    "Poll channel %s timed out after %ds",
                    ch.name, ch.poll_timeout_seconds,
                )
            except Exception:
                logger.exception("Failed to poll channel: %s", ch.name)
            # Each channel sleeps its own interval
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=ch.poll_interval_seconds
                )
                break  # stop_event was set
            except TimeoutError:
                continue

    async def _poll_channel(self, ch: ChannelConfig) -> None:
        """Call poll_recipe, parse return value, ingest each message, deliver to PA."""
        result = await asyncio.to_thread(
            self._runner.run, ch.poll_recipe,
            params={"notify_recipe": ch.notify_recipe},
        )
        if not result.get("success"):
            logger.warning(
                "Poll recipe %s returned failure: %s",
                ch.poll_recipe,
                result.get("error", "unknown"),
            )
            return

        messages = result.get("data", {}).get("messages", [])
        if not messages:
            logger.info("Poll %s: no new messages", ch.poll_recipe)
            return
        logger.info("Poll %s: %d message(s) received", ch.poll_recipe, len(messages))

        new_count = 0
        for msg in messages:
            if await self.ingest_message(ch, msg):
                new_count += 1

        if new_count:
            logger.info("Poll %s: %d new message(s) ingested into TaskBoard", ch.poll_recipe, new_count)

    def _seen(self, msg_id: str) -> bool:
        """Record msg_id; return True if it was already seen (FIFO-capped)."""
        if msg_id in self._seen_msg_ids:
            return True
        self._seen_msg_ids[msg_id] = None
        if len(self._seen_msg_ids) > self._seen_cap:
            # drop oldest (insertion-ordered dict)
            oldest = next(iter(self._seen_msg_ids))
            self._seen_msg_ids.pop(oldest, None)
        return False

    async def ingest_message(self, ch: ChannelConfig, msg: dict[str, Any]) -> bool:
        """Classify + enqueue a single message to the PA queue (Phase 3: 去账本).

        Shared by poll mode (_poll_channel) and stream mode (_stream_loop).
        瘦成 classify → conv_key → enqueue(QueueMessage with reply_context)；不再写
        board / Ingestor / 账本 trace。Returns True if newly enqueued, False if
        skipped (malformed payload or in-memory seen-set dedup hit).
        """
        msg_id = str(msg.get("id", ""))
        if not msg_id or "prompt" not in msg:
            logger.warning("Channel %s: message missing required fields, skipping", ch.name)
            return False

        # Channel redelivery defense: lark WS / email re-poll can deliver the same
        # msg_id twice. Without this gate the second delivery produces a second PA
        # round-trip and a second reply.
        if self._seen(msg_id):
            logger.info(
                "Channel %s: duplicate msg %s (seen-set hit) — skip PA enqueue",
                ch.name, msg_id,
            )
            return False

        from frago.server.services.routing.thread_classifier import (
            classify as thread_classify,
        )

        reply_ctx = msg.get("reply_context") or {}
        sender = reply_ctx.get("sender_id") or reply_ctx.get("sender") or ""
        classify_result = thread_classify(
            channel=ch.name,
            sender=sender,
            content=msg["prompt"],
            reply_context=reply_ctx,
        )

        if self._pa_enqueue:
            try:
                await self._pa_enqueue({
                    "type": "user_message",
                    "msg_id": msg_id,
                    "channel": ch.name,
                    "channel_message_id": msg_id,
                    "prompt": msg["prompt"],
                    "reply_context": reply_ctx,
                    "conv_key": classify_result.conv_key,
                    "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                logger.info(
                    "Message %s enqueued to PA (conv_key=%s, layer=%s)",
                    msg_id, classify_result.conv_key, classify_result.layer,
                )
            except Exception:
                logger.exception("Failed to enqueue message %s to PA", msg_id)
        return True

    # -- stream mode (long-connection recipes) --

    async def _stream_loop(self, ch: ChannelConfig) -> None:
        """Keep `poll_recipe` alive as a streaming subprocess.

        Each stdout line from the recipe must be a JSON object
        `{"type": "message", "id", "prompt", "reply_context"}`; lines with
        other `type` values are ignored (reserved for future control events).

        The recipe subprocess is expected to never exit voluntarily; if it does
        (crash, network error, flag day) it is restarted with exponential
        backoff. The spawn + backoff + teardown loop lives in the generic
        ``RecipeSupervisor``; this method only wires a channel-ingestion sink
        into it (``restart_policy="always"`` to match the original
        "restart on any exit" stream behaviour).
        """
        from frago.server.services.recipe_supervisor import (
            RecipeSupervisor,
            SupervisedRecipe,
        )

        spec = SupervisedRecipe(
            recipe=ch.poll_recipe,
            params={"notify_recipe": ch.notify_recipe},
            restart_policy="always",
            max_backoff=60,
            initial_backoff=2,
            startup_delay=5.0,
            name=ch.name,
        )
        supervisor = RecipeSupervisor(
            spec,
            _ChannelIngestSink(self, ch),
            runner=self._runner,
            stop_event=self._stop_event,
        )
        await supervisor.run()


class _ChannelIngestSink:
    """RecipeSupervisor sink that turns each stdout line into an ingested msg.

    Preserves the original ``_read_stream`` semantics: parse the line as JSON,
    ignore non-``message`` event types, feed ``message`` events into
    ``ingest_message``; stderr lines are logged with the ``[stream:<name>]``
    prefix.
    """

    def __init__(self, scheduler: IngestionScheduler, ch: ChannelConfig) -> None:
        self._scheduler = scheduler
        self._ch = ch

    async def on_stdout_line(self, line: bytes) -> None:
        ch = self._ch
        try:
            msg = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            logger.warning(
                "Stream %s: non-JSON stdout line: %s",
                ch.name, line[:200],
            )
            return
        if msg.get("type") != "message":
            logger.debug(
                "Stream %s: ignoring non-message event type=%s",
                ch.name, msg.get("type"),
            )
            return
        try:
            await self._scheduler.ingest_message(ch, msg)
        except Exception:
            logger.exception(
                "Stream %s: ingest_message failed for %s",
                ch.name, msg.get("id"),
            )

    async def on_stderr_line(self, line: bytes) -> None:
        logger.info(
            "[stream:%s] %s",
            self._ch.name,
            line.decode(errors="replace").rstrip(),
        )

