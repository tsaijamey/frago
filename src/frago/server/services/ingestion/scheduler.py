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

from frago.server.services.ingestion.models import (
    ActionType,
    ContextBinding,
    ExecutionStrategy,
    IngestedTask,
    TaskStatus,
    ThinkingResult,
)
from frago.server.services.ingestion.store import TaskStore
from frago.server.services.thinking import ThinkingEngine

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
        thinking_engine: ThinkingEngine | None = None,
    ) -> None:
        self._channels = channels
        self._store = store
        self._thinking = thinking_engine or ThinkingEngine()
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

    def _sync_task_index(self, exclude_task_ids: set[str] | None = None) -> None:
        """Refresh ThinkingEngine's task index from the store.

        Args:
            exclude_task_ids: Task IDs to exclude (e.g., current batch being processed).
        """
        try:
            index = self._store.get_index()
            if exclude_task_ids:
                index = [t for t in index if t.task_id not in exclude_task_ids]
            self._thinking.update_task_index(index)
        except Exception:
            logger.debug("Failed to sync task index", exc_info=True)

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

        # Collect all new tasks from this poll
        new_tasks: list[IngestedTask] = []
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
            new_tasks.append(task)

        if not new_tasks:
            return

        # Batch deliver all new tasks in a single continue_task call
        await self._deliver_batch_to_primary(new_tasks, ch)

    async def _deliver_batch_to_primary(
        self, tasks: list[IngestedTask], ch: ChannelConfig
    ) -> None:
        """Deliver tasks to Primary Agent, with ThinkingEngine pre-processing.

        Short-circuits:
        - NO_ACTION → mark COMPLETED, skip LLM entirely
        - REPLY_DIRECT → auto-reply via notify recipe, skip LLM
        Other results → deliver to Primary Agent with ThinkingResult attached
        """
        from frago.server.services.primary_agent_service import (
            PrimaryAgentService,
        )

        # Sync task index before processing, excluding current batch
        # (they were just added as PENDING and shouldn't count as "pending backlog")
        self._sync_task_index(exclude_task_ids={t.id for t in tasks})

        # Phase 1: Run ThinkingEngine on each task, partition into short-circuit vs deliver
        # (task, thinking_summary, thinking_result)
        tasks_for_primary: list[tuple[IngestedTask, str, ThinkingResult]] = []
        for task in tasks:
            thinking_result = self._thinking.process(task.prompt, task)

            # Short-circuit: NO_ACTION — pure info intake, no LLM needed
            if thinking_result.action_type == ActionType.NO_ACTION:
                logger.info(
                    "ThinkingEngine short-circuit: %s × %s → NO_ACTION, skipped LLM (task=%s)",
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
                # Send the direct reply via notify recipe
                task_with_result = self._store.get(task.id)
                if task_with_result:
                    task_with_result.result_summary = reply_content
                    await self._notify(task_with_result, ch)
                continue

            # Not short-circuited → deliver to Primary Agent with thinking summary
            summary = (
                f"[ThinkingEngine 预判: {thinking_result.semantic_type.value}"
                f" × {thinking_result.context_binding.value}"
                f" → {thinking_result.action_type.value}"
            )
            if thinking_result.execution_plan:
                summary += f" ({thinking_result.execution_plan.strategy.value})"
                if (
                    thinking_result.execution_plan.strategy == ExecutionStrategy.RECIPE_EXACT
                    and thinking_result.execution_plan.target
                ):
                    summary += f": {thinking_result.execution_plan.target}"
            summary += "]"
            tasks_for_primary.append((task, summary, thinking_result))

        # Deliver remaining tasks to Primary Agent
        if not tasks_for_primary:
            return

        primary = PrimaryAgentService.get_instance()
        session_id = primary.get_session_id()
        if not session_id:
            for task, _, _ in tasks_for_primary:
                self._store.update_status(
                    task.id, TaskStatus.FAILED, error="Primary Agent session not available"
                )
        else:
            await self._execute_batch_delivery(
                [t for t, _, _ in tasks_for_primary], ch, primary, session_id,
                thinking_summaries={t.id: s for t, s, _ in tasks_for_primary},
                thinking_results={t.id: r for t, _, r in tasks_for_primary},
            )

        # Notify only for FAILED/TIMEOUT — COMPLETED tasks are notified by Primary Agent via frago reply
        for task, _, _ in tasks_for_primary:
            updated = self._store.get(task.id)
            if updated and updated.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT):
                await self._notify(updated, ch)

    async def _execute_batch_delivery(
        self,
        tasks: list[IngestedTask],
        ch: ChannelConfig,
        primary: object,
        session_id: str,
        thinking_summaries: dict[str, str] | None = None,
        thinking_results: dict[str, ThinkingResult] | None = None,
    ) -> None:
        """Execute the actual batch delivery to the Primary Agent."""
        primary.record_external_message()
        primary.set_busy(True)
        thinking_summaries = thinking_summaries or {}
        thinking_results = thinking_results or {}

        try:
            # Build combined message
            message_parts = []
            for task in tasks:
                recent = self._store.get_recent(channel=ch.name, limit=5)
                tr = thinking_results.get(task.id)
                part = self._format_primary_message(task, ch, recent, tr)
                # Attach ThinkingEngine pre-judgment if available
                ts = thinking_summaries.get(task.id)
                if ts:
                    part = f"{ts}\n\n{part}"
                message_parts.append(part)

            combined = "\n\n".join(message_parts)
            if len(tasks) > 1:
                combined = f"以下有 {len(tasks)} 条新消息，请依次处理：\n\n" + combined

            # Single delivery
            from frago.server.services.agent_service import AgentService

            result = AgentService.continue_task(session_id, combined)
            if result.get("status") != "ok":
                raise RuntimeError(
                    f"Primary Agent delivery failed: {result.get('error')}"
                )

            for task in tasks:
                self._store.update_status(
                    task.id, TaskStatus.EXECUTING, session_id=session_id
                )
            logger.info(
                "Delivered %d task(s) to Primary Agent (session=%s)",
                len(tasks),
                session_id[:8],
            )

            # Wait for completion
            completion = await self._wait_for_completion(
                session_id, ch.task_timeout_seconds
            )
            final_status = (
                TaskStatus.COMPLETED
                if completion["status"] == "completed"
                else TaskStatus.TIMEOUT
            )
            for task in tasks:
                self._store.update_status(
                    task.id, final_status, result_summary=completion["summary"]
                )

        except Exception as e:
            logger.exception("Failed to deliver batch to Primary Agent")
            for task in tasks:
                self._store.update_status(task.id, TaskStatus.FAILED, error=str(e))

        finally:
            primary.set_busy(False)

    @staticmethod
    def _format_primary_message(
        task: IngestedTask,
        ch: ChannelConfig,
        recent_tasks: list[IngestedTask],
        thinking_result: ThinkingResult | None = None,
    ) -> str:
        """Format a structured message for the Primary Agent.

        Uses different templates based on context_binding:
        - ACTIVE_TASK_SUPPLEMENT: "补充信息" — tell PA to append to existing task
        - COMPLETED_TASK_FOLLOWUP: "后续跟进" — tell PA this follows a completed task
        - NEW_AFFAIR / default: "新消息" — tell PA to handle as new task
        """
        recent_summaries = []
        for rt in recent_tasks:
            if rt.id == task.id:
                continue
            recent_summaries.append(
                f"  - [{rt.status.value}] {rt.prompt[:60]}"
            )

        recent_section = ""
        if recent_summaries:
            recent_section = (
                "\n\n近期相关任务:\n" + "\n".join(recent_summaries)
            )

        binding = thinking_result.context_binding if thinking_result else ContextBinding.NEW_AFFAIR

        if binding == ContextBinding.ACTIVE_TASK_SUPPLEMENT:
            return (
                f"--- 补充信息（关联已有任务）---\n"
                f"来源 channel: {ch.name}\n"
                f"消息 ID: {task.channel_message_id}\n"
                f"回复上下文: {json.dumps(task.reply_context, ensure_ascii=False)}\n"
                f"\n"
                f"内容:\n{task.prompt}"
                f"{recent_section}\n"
                f"\n"
                f"这是对已有任务的补充信息。将此信息纳入已有任务的上下文，不要重新执行任务。"
                f"如果已有任务已完成且结果需要更新，可以补充回复；否则仅记录即可。"
            )

        if binding == ContextBinding.COMPLETED_TASK_FOLLOWUP:
            return (
                f"--- 后续跟进（已完成任务）---\n"
                f"来源 channel: {ch.name}\n"
                f"消息 ID: {task.channel_message_id}\n"
                f"回复上下文: {json.dumps(task.reply_context, ensure_ascii=False)}\n"
                f"\n"
                f"内容:\n{task.prompt}"
                f"{recent_section}\n"
                f"\n"
                f"这是对已完成任务的后续跟进。根据内容判断是否需要追加操作。"
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
