"""Ingestion scheduler — polls channels, delivers to Primary Agent for processing.

Channels are config declarations (a pair of poll + notify recipes), not code components.
Adding a new channel requires zero code changes — just config + recipes.

The scheduler delivers messages to the Primary Agent (managed by
PrimaryAgentService), which decides how to handle each incoming task.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from frago.server.services.ingestion.models import IngestedTask, TaskStatus
from frago.server.services.ingestion.store import TaskStore

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
    ) -> None:
        self._channels = channels
        self._store = store
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.warning("IngestionScheduler already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "IngestionScheduler started (channels=%s)",
            [c.name for c in self._channels],
        )

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("IngestionScheduler stopped")

    async def _loop(self) -> None:
        # Startup delay to let other services initialize
        await asyncio.sleep(5)

        while not self._stop_event.is_set():
            for ch in self._channels:
                try:
                    await self._poll_channel(ch)
                except Exception:
                    logger.exception("Failed to poll channel: %s", ch.name)

            # Use the minimum interval across channels
            interval = min(c.poll_interval_seconds for c in self._channels)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=interval
                )
                break  # stop_event was set
            except asyncio.TimeoutError:
                continue

    async def _poll_channel(self, ch: ChannelConfig) -> None:
        """Call poll_recipe, parse return value per data contract."""
        from frago.recipes.runner import RecipeRunner

        runner = RecipeRunner()
        result = await asyncio.to_thread(runner.run, ch.poll_recipe, params={})
        if not result.get("success"):
            logger.warning(
                "Poll recipe %s returned failure: %s",
                ch.poll_recipe,
                result.get("error", "unknown"),
            )
            return

        messages = result.get("data", {}).get("messages", [])
        if not messages:
            logger.debug("Poll %s: no new messages", ch.poll_recipe)
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
            logger.info("New task from %s: %s", ch.name, task.prompt[:80])
            self._store.add(task)
            await self._deliver_to_primary(task, ch)

    async def _deliver_to_primary(
        self, task: IngestedTask, ch: ChannelConfig
    ) -> None:
        """Deliver an ingested task to the Primary Agent for processing."""
        try:
            from frago.server.services.primary_agent_service import (
                PrimaryAgentService,
            )

            primary = PrimaryAgentService.get_instance()
            session_id = primary.get_session_id()
            if not session_id:
                raise RuntimeError("Primary Agent session not available")

            primary.record_external_message()

            # Build structured message with source context and recent tasks
            recent_tasks = self._store.get_recent(channel=ch.name, limit=5)
            message = self._format_primary_message(task, ch, recent_tasks)

            # Deliver via continue_task (--resume on the primary session)
            from frago.server.services.agent_service import AgentService

            result = AgentService.continue_task(session_id, message)
            if result.get("status") != "ok":
                raise RuntimeError(
                    f"Primary Agent delivery failed: {result.get('error')}"
                )

            self._store.update_status(
                task.id, TaskStatus.EXECUTING, session_id=session_id
            )
            logger.info(
                "Delivered task %s to Primary Agent (session=%s)",
                task.id[:8],
                session_id[:8],
            )

            # Wait for completion and notify
            completion = await self._wait_for_completion(
                session_id, ch.task_timeout_seconds
            )
            final_status = (
                TaskStatus.COMPLETED
                if completion["status"] == "completed"
                else TaskStatus.FAILED
            )
            self._store.update_status(
                task.id, final_status, result_summary=completion["summary"]
            )

        except Exception as e:
            logger.exception("Failed to deliver task to Primary Agent: %s", task.id)
            self._store.update_status(task.id, TaskStatus.FAILED, error=str(e))

        # Always attempt notification
        updated_task = self._store.get(task.id)
        if updated_task:
            await self._notify(updated_task, ch)

    @staticmethod
    def _format_primary_message(
        task: IngestedTask,
        ch: ChannelConfig,
        recent_tasks: list[IngestedTask],
    ) -> str:
        """Format a structured message for the Primary Agent."""
        recent_summaries = []
        for rt in recent_tasks:
            if rt.id == task.id:
                continue  # Skip the current task itself
            recent_summaries.append(
                f"  - [{rt.status.value}] {rt.prompt[:60]}"
            )

        recent_section = ""
        if recent_summaries:
            recent_section = (
                "\n\n近期相关任务:\n" + "\n".join(recent_summaries)
            )

        return (
            f"--- 新消息 ---\n"
            f"来源 channel: {ch.name}\n"
            f"消息 ID: {task.channel_message_id}\n"
            f"回复上下文: {json.dumps(task.reply_context, ensure_ascii=False)}\n"
            f"\n"
            f"内容:\n{task.prompt}"
            f"{recent_section}\n"
            f"\n"
            f"请处理这个任务。"
        )

    async def _wait_for_completion(self, session_id: str, timeout: int) -> dict:
        """Poll agent log file to detect completion."""
        log_file = (
            Path.home() / ".frago" / "logs" / f"agent-resume-{session_id[:8]}.log"
        )
        start = time.monotonic()
        last_size = -1
        logger.info("Waiting for task completion (session=%s, timeout=%ds)", session_id[:8], timeout)

        while time.monotonic() - start < timeout:
            await asyncio.sleep(10)
            if not log_file.exists():
                continue
            current_size = log_file.stat().st_size
            if current_size == last_size and last_size > 0:
                elapsed = int(time.monotonic() - start)
                logger.info("Task completed (session=%s, elapsed=%ds)", session_id[:8], elapsed)
                content = log_file.read_text(encoding="utf-8", errors="replace")
                summary = content[-2000:] if len(content) > 2000 else content
                return {"status": "completed", "summary": summary}
            last_size = current_size

        logger.warning("Task timed out (session=%s, timeout=%ds)", session_id[:8], timeout)
        return {"status": "timeout", "summary": f"任务执行超时（{timeout}秒）"}

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
