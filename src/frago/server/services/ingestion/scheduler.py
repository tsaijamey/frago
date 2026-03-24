"""Ingestion scheduler — polls channels, ingests tasks into TaskStore.

Channels are config declarations (a pair of poll + notify recipes), not code components.
Adding a new channel requires zero code changes — just config + recipes.

The scheduler's job is:
1. Poll channels via recipes
2. Deduplicate by (channel, channel_message_id)
3. Store new tasks as PENDING in TaskStore
4. Enqueue messages to the PA message queue for immediate processing

Tasks are consumed by the PA via the message queue consumer loop.
The scheduler does NOT classify, filter, or short-circuit any messages.
Every message reaches the PA.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from frago.server.services.ingestion.models import IngestedTask
from frago.server.services.ingestion.store import TaskStore

logger = logging.getLogger(__name__)


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
        """Call poll_recipe, parse return value, ingest new tasks."""
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

        for msg in messages:
            # Defensive: skip messages missing required fields
            if "id" not in msg or "prompt" not in msg:
                logger.warning(
                    "Channel %s: message missing required fields (id/prompt), skipping",
                    ch.name,
                )
                continue

            msg_id = str(msg["id"])
            if self._store.exists(ch.name, msg_id):
                logger.debug("Channel %s: message %s already processed, skipping", ch.name, msg_id)
                continue

            task = IngestedTask(
                id=str(uuid.uuid4()),
                channel=ch.name,
                channel_message_id=msg_id,
                prompt=msg["prompt"],
                reply_context=msg.get("reply_context", {}),
            )
            logger.info("New task from %s: %s", ch.name, task.prompt)
            self._store.add(task)

            # Enqueue to PA message queue for immediate processing
            if self._pa_enqueue:
                try:
                    await self._pa_enqueue({
                        "type": "user_message",
                        "task_id": task.id,
                        "channel": ch.name,
                        "channel_message_id": msg_id,
                        "prompt": task.prompt,
                        "reply_context": task.reply_context,
                    })
                    logger.info("Task %s enqueued to PA", task.id[:8])
                except Exception:
                    logger.exception("Failed to enqueue task %s to PA", task.id[:8])
            else:
                logger.debug("Task %s stored as PENDING (no PA queue registered)", task.id[:8])

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

    async def _notify(self, task: IngestedTask, ch: ChannelConfig) -> None:
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
