"""Ingestion scheduler — polls channels, ingests tasks into TaskStore.

Channels are config declarations (a pair of poll + notify recipes), not code components.
Adding a new channel requires zero code changes — just config + recipes.

The scheduler's job is:
1. Poll channels via recipes
2. Run ThinkingEngine short-circuit (NO_ACTION, REPLY_DIRECT)
3. Store remaining tasks as PENDING in TaskStore

Tasks are consumed by the Primary Agent's heartbeat loop, which checks
TaskStore for pending tasks and dispatches them to Run instances.
The scheduler does NOT deliver messages to the PA session directly.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from frago.server.services.ingestion.models import (
    ActionType,
    ExecutionStrategy,
    IngestedTask,
    TaskStatus,
)
from frago.server.services.ingestion.store import TaskStore
from frago.server.services.thinking import BaseThinkingEngine, ThinkingEngine

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """A channel declaration from config.json."""

    name: str
    poll_recipe: str
    notify_recipe: str
    poll_interval_seconds: int = 120
    task_timeout_seconds: int = 600


class IngestionScheduler:

    def __init__(
        self,
        channels: list[ChannelConfig],
        store: TaskStore,
        thinking_engine: BaseThinkingEngine | None = None,
    ) -> None:
        self._channels = channels
        self._store = store
        self._thinking_engine = thinking_engine  # For test injection; per-channel instances created in start()
        self._channel_tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._channel_tasks:
            logger.warning("IngestionScheduler already running")
            return
        self._stop_event.clear()
        for ch in self._channels:
            thinking = self._thinking_engine or ThinkingEngine()
            task = asyncio.create_task(
                self._channel_loop(ch, thinking),
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
        for task in self._channel_tasks.values():
            task.cancel()
        await asyncio.gather(
            *self._channel_tasks.values(),
            return_exceptions=True,
        )
        self._channel_tasks.clear()
        logger.info("IngestionScheduler stopped")

    async def _channel_loop(self, ch: ChannelConfig, thinking: BaseThinkingEngine) -> None:
        """Per-channel polling loop with its own interval."""
        await asyncio.sleep(5)  # Startup delay
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._poll_channel(ch, thinking),
                    timeout=ch.task_timeout_seconds,
                )
            except TimeoutError:
                logger.error(
                    "Poll channel %s timed out after %ds",
                    ch.name, ch.task_timeout_seconds,
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

    def _sync_task_index(
        self, thinking: BaseThinkingEngine, exclude_task_ids: set[str] | None = None,
    ) -> None:
        """Refresh ThinkingEngine's task index from the store."""
        try:
            index = self._store.get_index()
            if exclude_task_ids:
                index = [t for t in index if t.task_id not in exclude_task_ids]
            thinking.update_task_index(index)
        except Exception:
            logger.debug("Failed to sync task index", exc_info=True)

    async def _poll_channel(self, ch: ChannelConfig, thinking: BaseThinkingEngine) -> None:
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

        # Sync task index before processing
        new_task_ids: set[str] = set()

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
            logger.info("New task from %s: %s", ch.name, task.prompt[:80])
            self._store.add(task)
            new_task_ids.add(task.id)

            # ThinkingEngine short-circuit processing
            self._sync_task_index(thinking, exclude_task_ids=new_task_ids)
            thinking_result = thinking.process(task.prompt, task)

            # Short-circuit: NO_ACTION — pure info intake, no LLM needed
            if thinking_result.action_type == ActionType.NO_ACTION:
                logger.info(
                    "ThinkingEngine short-circuit: %s × %s → NO_ACTION (task=%s)",
                    thinking_result.semantic_type.value,
                    thinking_result.context_binding.value,
                    task.id[:8],
                )
                self._store.update_status(
                    task.id, TaskStatus.COMPLETED,
                    result_summary=f"ThinkingEngine: {thinking_result.semantic_type.value} → NO_ACTION",
                )
                continue

            # Short-circuit: REPLY_DIRECT — answer from task index, no LLM needed
            if (
                thinking_result.execution_plan
                and thinking_result.execution_plan.strategy == ExecutionStrategy.REPLY_DIRECT
            ):
                reply_content = thinking_result.execution_plan.target
                logger.info(
                    "ThinkingEngine short-circuit: REPLY_DIRECT (task=%s) → %s",
                    task.id[:8],
                    reply_content[:60],
                )
                self._store.update_status(
                    task.id, TaskStatus.COMPLETED,
                    result_summary=reply_content,
                )
                # Send direct reply
                task_with_result = self._store.get(task.id)
                if task_with_result:
                    task_with_result.result_summary = reply_content
                    await self._notify(task_with_result, ch)
                continue

            # Not short-circuited → stays PENDING in TaskStore
            # PA heartbeat will pick it up via _has_pending_tasks()
            logger.info(
                "Task %s stays PENDING for PA pickup (%s × %s → %s)",
                task.id[:8],
                thinking_result.semantic_type.value,
                thinking_result.context_binding.value,
                thinking_result.action_type.value,
            )

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
