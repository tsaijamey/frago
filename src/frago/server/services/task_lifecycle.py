"""Task Lifecycle — coordination point for ingestion, reply, and recovery.

Execution (run) tasks are handled by executor.py, not here.
TaskLifecycle handles: ingestion, reply via notify recipe, stale lock detection,
and PENDING task recovery.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.models import IngestedTask, TaskStatus
from frago.server.services.ingestion.store import TaskStore

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"
CONFIG_FILE = FRAGO_HOME / "config.json"


class TaskLifecycle:
    """Single coordination point for task state transitions.

    Not a singleton — instantiated by PrimaryAgentService with injected deps.
    """

    def __init__(
        self,
        task_store: TaskStore | None = None,
    ) -> None:
        self._store = task_store or TaskStore()

    # -- ingestion --

    def ingest(
        self,
        channel: str,
        messages: list[dict],
    ) -> list[str]:
        """Ingest messages from a channel: dedup → create PENDING task.

        Returns list of new task_ids.
        """
        import uuid

        new_task_ids: list[str] = []
        for msg in messages:
            msg_id = str(msg.get("id", ""))
            if not msg_id or "prompt" not in msg:
                logger.warning("Channel %s: message missing required fields, skipping", channel)
                continue

            if self._store.exists(channel, msg_id):
                logger.debug("Channel %s: message %s already exists, skipping", channel, msg_id)
                continue

            task = IngestedTask(
                id=str(uuid.uuid4()),
                channel=channel,
                channel_message_id=msg_id,
                prompt=msg["prompt"],
                reply_context=msg.get("reply_context", {}),
            )
            self._store.add(task)
            new_task_ids.append(task.id)
            logger.info("Ingested task %s from %s", task.id[:8], channel)

        return new_task_ids

    # -- reply --

    def reply(self, task_id: str, channel: str, reply_params: dict) -> dict[str, Any]:
        """Execute a reply via notify recipe. Returns {"status": "ok"/"error"}.

        Enriches params with reply_context, runs notify recipe.
        Caller (_send_reply) handles task status updates.
        """
        # Enrich reply_params with reply_context from TaskStore
        if task_id:
            task = self._store.get(task_id)

            # Safety check: verify task_id matches the declared channel
            if task and task.channel != channel:
                logger.warning(
                    "Channel mismatch: task %s belongs to channel '%s' but PA declared '%s'. "
                    "Using task's actual channel to prevent cross-channel reply.",
                    task_id, task.channel, channel,
                )
                channel = task.channel

            if task and task.reply_context:
                full_params = {
                    "text": reply_params.get("text", ""),
                    "reply_context": task.reply_context,
                }
                if reply_params.get("html_body"):
                    full_params["html_body"] = reply_params["html_body"]
                reply_params = full_params

        # Find and run notify recipe for channel
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            channels = raw.get("task_ingestion", {}).get("channels", [])
            notify_recipe = None
            for ch in channels:
                if ch.get("name") == channel:
                    notify_recipe = ch.get("notify_recipe")
                    break

            if not notify_recipe:
                logger.warning("No notify_recipe configured for channel %s", channel)
                return {"status": "error", "error": f"no notify_recipe for {channel}"}

            from frago.recipes.runner import RecipeRunner
            runner = RecipeRunner()
            logger.info(
                "Reply params for %s: %s",
                notify_recipe,
                json.dumps(reply_params, ensure_ascii=False, default=str),
            )
            runner.run(notify_recipe, params=reply_params)
            logger.info("Reply sent via %s for channel %s", notify_recipe, channel)
            return {"status": "ok"}

        except Exception as e:
            logger.exception("Failed to send reply for channel %s", channel)
            return {"status": "error", "error": str(e)}

    # -- heartbeat helpers --

    def check_stale_run_lock(self) -> bool:
        """Check and release stale run locks. Returns True if a lock was released."""
        from frago.run.context import ContextManager

        try:
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            current_run_id = ctx_mgr.get_current_run_id()
            if not current_run_id:
                return False

            # Check for completion marker — if found, just release lock
            step, _summary = self._read_completion_info(current_run_id)
            if step is not None:
                ctx_mgr.release_context()
                logger.info("Released stale run lock %s (completion marker found)", current_run_id)
                return True

            # No completion marker — check timeout + process liveness
            lock_file = FRAGO_HOME / "current_run"
            if not lock_file.exists():
                return False

            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            last_accessed_str = lock_data.get("last_accessed", "")
            if not last_accessed_str:
                return False

            last_accessed = datetime.fromisoformat(last_accessed_str)
            elapsed = (datetime.now() - last_accessed).total_seconds()
            stale_threshold = 1800  # 30 minutes

            if elapsed < stale_threshold:
                return False

            # Check if process is still running
            run_still_alive = False
            try:
                for pid_dir in Path("/proc").iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    try:
                        environ = (pid_dir / "environ").read_bytes()
                        if f"FRAGO_CURRENT_RUN={current_run_id}".encode() in environ:
                            run_still_alive = True
                            break
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
            except Exception:
                return False

            if not run_still_alive:
                ctx_mgr.release_context()
                # Mark any EXECUTING task associated with this run as FAILED
                executing = self._store.get_by_status(TaskStatus.EXECUTING)
                for task in executing:
                    if task.session_id == current_run_id:
                        self._store.update_status(
                            task.id, TaskStatus.FAILED,
                            error="stale run lock timeout",
                        )
                        break
                logger.info(
                    "Released stale run lock %s (timed out after %ds, process gone)",
                    current_run_id, int(elapsed),
                )
                return True

        except Exception:
            logger.debug("Stale run lock check failed", exc_info=True)

        return False

    def recover_pending_tasks(self) -> list[dict]:
        """Scan TaskStore for PENDING and FAILED tasks, return as queue messages.

        PENDING → re-enqueue as user_message for PA to decide.
        FAILED → notify PA so it knows (PA will inform user after 2 failures).

        Does NOT enqueue — returns the messages for the caller to handle.
        """

        pending = self._store.get_by_status(TaskStatus.PENDING)
        failed = self._store.get_by_status(TaskStatus.FAILED)

        if not pending and not failed:
            return []

        MAX_RECOVERY = 2

        messages = []
        for task in pending:
            if task.recovery_count >= MAX_RECOVERY:
                logger.warning(
                    "Task %s recovered %d times without completion — marking stale",
                    task.id[:8], task.recovery_count,
                )
                self._store.update_status(
                    task.id, TaskStatus.FAILED,
                    error=f"stale: recovered {task.recovery_count} times without resolution",
                )
                continue
            self._store.increment_recovery_count(task.id)
            messages.append({
                "type": "user_message",
                "task_id": task.id,
                "channel": task.channel,
                "channel_message_id": task.channel_message_id,
                "prompt": task.prompt,
                "reply_context": task.reply_context,
                "_recovered": True,
            })

        for task in failed:
            # Reset to PENDING so PA can re-dispatch
            self._store.update_status(task.id, TaskStatus.PENDING)
            # Use user_message type (valid queue message) with failure context prepended
            failure_context = (
                f"[恢复失败任务] task: {task.id} channel: {task.channel}\n"
                f"上次错误: {task.error or 'unknown'}\n"
                f"该任务已重置为 PENDING，请决定如何处理（重新 run 或 reply 告知用户）。\n\n"
            )
            messages.append({
                "type": "user_message",
                "task_id": task.id,
                "channel": task.channel,
                "channel_message_id": task.channel_message_id,
                "prompt": failure_context + task.prompt,
                "reply_context": task.reply_context,
                "_recovered": True,
            })

        return messages

    def get_task(self, task_id: str) -> IngestedTask | None:
        """Look up a task by id (exact + prefix match)."""
        return self._store.get(task_id)

    def find_task_for_run(self, run_id: str) -> IngestedTask | None:
        """Find the IngestedTask associated with a run_id."""
        executing = self._store.get_by_status(TaskStatus.EXECUTING)
        for task in executing:
            if task.session_id == run_id:
                return task
        return None

    # -- static helpers --

    @staticmethod
    def _read_completion_info(run_id: str) -> tuple[str | None, str | None]:
        """Read completion step and summary from run's execution.jsonl."""
        log_file = PROJECTS_DIR / run_id / "logs" / "execution.jsonl"
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-20:]):
                if not line.strip():
                    continue
                entry = json.loads(line)
                step = entry.get("step")
                if step in ("TASK_COMPLETE", "TASK_FAILED"):
                    summary = entry.get("data", {}).get("summary")
                    return step, summary
        except Exception:
            pass
        return None, None
