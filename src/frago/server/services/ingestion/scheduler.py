"""Ingestion scheduler — polls channels, caches messages, delivers to PA.

Channels are config declarations (a pair of poll + notify recipes), not code components.
Adding a new channel requires zero code changes — just config + recipes.

The scheduler's job is:
1. Poll channels via recipes
2. Deduplicate by (channel, channel_message_id)
3. Cache raw message data in memory (NO task creation)
4. Enqueue messages to the PA message queue for immediate processing

Task creation happens later — when PA decides an action (reply/run),
the decision handler pulls cached data and creates the IngestedTask.
The scheduler does NOT classify, filter, or short-circuit any messages.
Every message reaches the PA.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.store import TaskStore

logger = logging.getLogger(__name__)

CACHE_FILE = Path.home() / ".frago" / "message_cache.json"


@dataclass
class CachedMessage:
    """Raw message data cached until PA decides what to do with it."""

    channel: str
    msg_id: str
    prompt: str
    reply_context: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.now)


@dataclass
class ChannelConfig:
    """A channel declaration from config.json."""

    name: str
    poll_recipe: str
    notify_recipe: str
    poll_interval_seconds: int = 120
    poll_timeout_seconds: int = 20


class IngestionScheduler:

    def __init__(
        self,
        channels: list[ChannelConfig],
        store: TaskStore,
    ) -> None:
        self._channels = channels
        self._store = store
        self._channel_tasks: dict[str, asyncio.Task[None]] = {}
        self._rotation_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        # Set by PrimaryAgentService after initialization
        self._pa_enqueue: asyncio.coroutines | None = None
        # Message cache: key = "channel:msg_id" → CachedMessage
        # Persisted to ~/.frago/message_cache.json to survive restarts
        self._message_cache: dict[str, CachedMessage] = self._load_cache()
        # In-memory dedup set (supplements store.exists() for archive check)
        self._seen_messages: set[str] = set(self._message_cache.keys())

    def set_pa_enqueue(self, enqueue_fn: object) -> None:
        """Register the PA message queue enqueue function.

        Called by PrimaryAgentService during server startup so the scheduler
        can deliver messages to the PA queue without a circular import.
        """
        self._pa_enqueue = enqueue_fn

    def get_cached_message(self, channel: str, msg_id: str) -> CachedMessage | None:
        """Retrieve a cached message by channel + msg_id.

        Called by PA decision handlers to get raw data for task creation.
        """
        return self._message_cache.get(f"{channel}:{msg_id}")

    def remove_cached_message(self, channel: str, msg_id: str) -> None:
        """Remove a processed message from cache. Called after task creation."""
        key = f"{channel}:{msg_id}"
        if key in self._message_cache:
            del self._message_cache[key]
            self._save_cache()
            logger.debug("Removed cached message %s", key)

    # -- cache persistence --

    @staticmethod
    def _load_cache() -> dict[str, CachedMessage]:
        """Load message cache from disk on startup."""
        if not CACHE_FILE.exists():
            return {}
        try:
            raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            cache: dict[str, CachedMessage] = {}
            for key, data in raw.items():
                cache[key] = CachedMessage(
                    channel=data["channel"],
                    msg_id=data["msg_id"],
                    prompt=data["prompt"],
                    reply_context=data.get("reply_context", {}),
                    received_at=datetime.fromisoformat(data["received_at"]),
                )
            logger.info("Loaded %d cached message(s) from %s", len(cache), CACHE_FILE.name)
            return cache
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("Failed to load message cache: %s", e)
            return {}

    def _save_cache(self) -> None:
        """Persist message cache to disk."""
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                key: {
                    "channel": msg.channel,
                    "msg_id": msg.msg_id,
                    "prompt": msg.prompt,
                    "reply_context": msg.reply_context,
                    "received_at": msg.received_at.isoformat(),
                }
                for key, msg in self._message_cache.items()
            }
            CACHE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to save message cache: %s", e)

    async def start(self) -> None:
        if self._channel_tasks:
            logger.warning("IngestionScheduler already running")
            return
        self._stop_event.clear()
        for ch in self._channels:
            task = asyncio.create_task(
                self._channel_loop(ch),
                name=f"ingestion-{ch.name}",
            )
            self._channel_tasks[ch.name] = task
        self._rotation_task = asyncio.create_task(
            self._rotation_loop(), name="ingestion-rotation"
        )
        logger.info(
            "IngestionScheduler started (channels=%s)",
            [c.name for c in self._channels],
        )

    async def stop(self) -> None:
        if not self._channel_tasks and not self._rotation_task:
            return
        self._stop_event.set()
        tasks_to_cancel = list(self._channel_tasks.values())
        if self._rotation_task:
            tasks_to_cancel.append(self._rotation_task)
        for task in tasks_to_cancel:
            task.cancel()
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._channel_tasks.clear()
        self._rotation_task = None
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
        """Call poll_recipe, parse return value, cache messages, deliver to PA."""
        from frago.recipes.runner import RecipeRunner

        runner = RecipeRunner()
        result = await asyncio.to_thread(
            runner.run, ch.poll_recipe,
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

        # Dedup + cache + enqueue (NO task creation)
        new_count = 0
        for msg in messages:
            msg_id = str(msg.get("id", ""))
            if not msg_id or "prompt" not in msg:
                logger.warning("Channel %s: message missing required fields, skipping", ch.name)
                continue

            key = f"{ch.name}:{msg_id}"

            # Dedup: in-memory set + archive history
            if key in self._seen_messages:
                logger.debug("Channel %s: message %s already seen, skipping", ch.name, msg_id)
                continue
            if self._store.exists(ch.name, msg_id):
                logger.debug("Channel %s: message %s exists in store/archive, skipping", ch.name, msg_id)
                self._seen_messages.add(key)
                continue

            # Cache raw message data
            cached = CachedMessage(
                channel=ch.name,
                msg_id=msg_id,
                prompt=msg["prompt"],
                reply_context=msg.get("reply_context", {}),
            )
            self._message_cache[key] = cached
            self._seen_messages.add(key)
            new_count += 1

            # Trace: scheduler received message
            from frago.server.services.trace import trace
            trace(msg_id, None, "scheduler", f"收到 {ch.name} 消息: {msg['prompt'][:80]}",
                  data={"event_type": "pa_ingestion", "channel": ch.name, "prompt": msg["prompt"]})

            # Enqueue to PA message queue
            if self._pa_enqueue:
                try:
                    await self._pa_enqueue({
                        "type": "user_message",
                        "msg_id": msg_id,
                        "channel": ch.name,
                        "channel_message_id": msg_id,
                        "prompt": msg["prompt"],
                        "reply_context": msg.get("reply_context", {}),
                    })
                    logger.info("Message %s enqueued to PA", msg_id)
                except Exception:
                    logger.exception("Failed to enqueue message %s to PA", msg_id)

        if new_count:
            self._save_cache()
            logger.info("Poll %s: %d new message(s) cached and persisted", ch.poll_recipe, new_count)

    async def _rotation_loop(self) -> None:
        """Archive terminal tasks daily at 0:00 UTC. Catch-up on startup."""
        if self._store.needs_rotation():
            logger.info("Startup: stale terminal tasks found, running catch-up rotation")
            self._store.rotate()

        while not self._stop_event.is_set():
            now = datetime.now()
            tomorrow = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            wait_seconds = (tomorrow - now).total_seconds()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=wait_seconds
                )
                break  # stop_event was set
            except TimeoutError:
                pass
            self._store.rotate()

    async def _notify(self, task: object, ch: ChannelConfig) -> None:
        """Call notify_recipe with contract-defined params."""
        from frago.recipes.runner import RecipeRunner

        try:
            runner = RecipeRunner()
            params = {
                "status": task.status.value,
                "reply_context": task.reply_context,
            }
            if task.result_summary is not None:
                params["result_summary"] = task.result_summary
            if task.error is not None:
                params["error"] = task.error
            await asyncio.to_thread(
                runner.run,
                ch.notify_recipe,
                params=params,
            )
            logger.info("Notified task result: %s via %s", task.id[:8], ch.name)
        except Exception:
            logger.exception("Failed to notify task: %s", task.id[:8])
