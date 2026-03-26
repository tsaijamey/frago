"""Task Lifecycle — single coordination point for all task state transitions.

TaskLifecycle does NOT store data. It orchestrates the sequence of operations
across TaskStore, RunManager, and ContextManager, with rollback on failure.
All task state changes go through here.

PA Service calls TaskLifecycle methods instead of directly manipulating stores.

Recovery is based on TaskStore status: PENDING/QUEUED tasks are re-delivered
to PA on server restart. No separate message journal needed.
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

    # -- dispatch --

    def dispatch(self, task_id: str, agent_params: dict) -> dict[str, Any]:
        """Dispatch a task as a sub-agent run.

        Steps: check lock → create run → set lock → update store → launch agent.
        On lock conflict: mark QUEUED.
        On failure: rollback to previous state.

        Returns {"status": "ok", "run_id": ..., "pid": ...} or {"status": "blocked"/"error", ...}.
        """
        from frago.run.constants import THEME_DESCRIPTION_MAX_LEN as THEME_DESC_MAX
        from frago.run.context import ContextManager
        from frago.run.exceptions import ContextAlreadySetError
        from frago.run.manager import RunManager
        from frago.server.services.agent_service import AgentService

        description = agent_params.get("description", "")
        prompt = agent_params.get("prompt", "")
        related_runs = agent_params.get("related_runs", [])

        if not prompt:
            logger.warning("dispatch: missing prompt for task %s", task_id)
            return {"status": "error", "error": "missing prompt"}

        # 1. Check run lock
        ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
        current_run = ctx_mgr.get_current_run_id()
        if current_run:
            logger.info(
                "Run lock active (held by %s), task %s → QUEUED",
                current_run, task_id,
            )
            if task_id:
                self._store.update_status(task_id, TaskStatus.QUEUED)
            return {"status": "blocked", "held_by": current_run}

        # 2. Create Run instance
        manager = RunManager(PROJECTS_DIR)
        run = manager.create_run(
            description[:THEME_DESC_MAX] if description else prompt[:THEME_DESC_MAX]
        )
        run_id = run.run_id
        logger.info("Created Run %s for task %s", run_id, task_id)

        # 3. Set mutex
        try:
            ctx_mgr.set_current_run(run_id, run.theme_description)
        except ContextAlreadySetError:
            logger.warning("Run lock race condition during dispatch of task %s", task_id)
            return {"status": "blocked", "error": "race condition"}

        # 4. Update TaskStore
        if task_id:
            self._store.update_status(
                task_id, TaskStatus.EXECUTING, session_id=run_id,
            )

        # 5. Build sub-agent prompt and launch
        from frago.server.services.primary_agent_service import PrimaryAgentService
        agent_prompt = PrimaryAgentService._build_sub_agent_prompt(
            task_id=task_id,
            task_prompt=prompt,
            run_id=run_id,
            related_runs=related_runs,
        )

        result = AgentService.start_task(
            prompt=agent_prompt,
            project_path=str(Path.home()),
            env_extra={"FRAGO_CURRENT_RUN": run_id},
        )

        if result.get("status") != "ok":
            # Rollback: release lock, revert task status
            logger.error("Failed to start sub-agent for run %s: %s", run_id, result.get("error"))
            ctx_mgr.release_context()
            if task_id:
                self._store.update_status(task_id, TaskStatus.PENDING)
            return {"status": "error", "error": result.get("error")}

        logger.info("Sub-agent launched for Run %s (agent_id=%s)", run_id, result.get("id", "?")[:8])
        return {
            "status": "ok",
            "run_id": run_id,
            "pid": result.get("pid"),
            "agent_id": result.get("id"),
        }

    # -- reply --

    def reply(self, task_id: str, channel: str, reply_params: dict) -> dict[str, Any]:
        """Execute a reply via notify recipe. Returns {"status": "ok"/"error"}.

        Steps: enrich params → mark EXECUTING → run recipe → mark COMPLETED.
        On recipe failure: mark FAILED + return error for PA notification.
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
                if reply_params.get("text"):
                    full_params = {
                        "text": reply_params["text"],
                        "reply_context": task.reply_context,
                    }
                else:
                    full_params = {
                        "status": reply_params.get("status", "completed"),
                        "reply_context": task.reply_context,
                    }
                    if reply_params.get("result_summary"):
                        full_params["result_summary"] = reply_params["result_summary"]
                    if reply_params.get("error"):
                        full_params["error"] = reply_params["error"]
                if reply_params.get("html_body"):
                    full_params["html_body"] = reply_params["html_body"]
                reply_params = full_params

        # Mark EXECUTING to prevent heartbeat re-enqueue
        if task_id:
            self._store.update_status(
                task_id, TaskStatus.EXECUTING, result_summary="sending reply",
            )

        # Find notify recipe for channel
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

            # Mark completed
            if task_id:
                self._store.update_status(
                    task_id, TaskStatus.COMPLETED,
                    result_summary=reply_params.get("result_summary", "replied"),
                )

            return {"status": "ok"}

        except Exception as e:
            logger.exception("Failed to send reply for channel %s", channel)
            error_msg = str(e)
            if task_id:
                task = self._store.get(task_id)
                retry_count = (task.retry_count + 1) if task else 1
                if retry_count >= 2:
                    # 2 consecutive failures → give up, PA will notify user
                    self._store.update_status(
                        task_id, TaskStatus.FAILED,
                        error=f"reply failed {retry_count} times: {error_msg}",
                    )
                else:
                    # Roll back to PENDING so PA can retry
                    self._store.update_status(
                        task_id, TaskStatus.PENDING,
                        error=f"reply failed (attempt {retry_count}): {error_msg}",
                    )
                self._store.update_retry_count(task_id, retry_count)
            # Build reply_failed notification for PA
            from frago.server.services.pa_prompts import PA_REPLY_FAILED_TEMPLATE
            reply_text = reply_params.get("text", "") if reply_params else ""
            return {
                "status": "error",
                "error": error_msg,
                "pa_notify": {
                    "type": "reply_failed",
                    "content": PA_REPLY_FAILED_TEMPLATE.format(
                        task_id=task_id or "unknown",
                        channel=channel,
                        error=error_msg,
                        reply_text=reply_text[:200],
                    ),
                },
            }

    # -- finalize --

    def finalize(
        self,
        task_id: str | None,
        run_id: str,
        reason: str = "normal",
    ) -> None:
        """Finalize a task after sub-agent exit.

        Reads completion marker → updates TaskStore → releases lock → archives run.
        """
        from frago.run.context import ContextManager
        from frago.run.manager import RunManager
        from frago.run.models import RunStatus

        # 1. Read completion info
        step, summary = self._read_completion_info(run_id)

        # 2. Update task status
        task = self._store.get(task_id) if task_id else None
        if not task:
            # Try to find by session_id == run_id
            executing = self._store.get_by_status(TaskStatus.EXECUTING)
            for t in executing:
                if t.session_id == run_id:
                    task = t
                    break

        if task and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
            if step == "TASK_COMPLETE":
                self._store.update_status(task.id, TaskStatus.COMPLETED, result_summary=summary)
            elif step == "TASK_FAILED":
                self._store.update_status(task.id, TaskStatus.FAILED, error=summary)
            elif reason == "timeout":
                self._store.update_status(task.id, TaskStatus.TIMEOUT, error="stale run lock timeout")
            else:
                self._store.update_status(
                    task.id, TaskStatus.FAILED,
                    error="sub-agent exited without completion marker",
                )
            logger.info("Finalized task %s (reason=%s, step=%s)", task.id, reason, step)

        # 3. Release context lock
        try:
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            if ctx_mgr.get_current_run_id() == run_id:
                ctx_mgr.release_context()
                logger.info("Released context lock for run %s", run_id)
        except Exception:
            logger.debug("Context release failed for run %s", run_id, exc_info=True)

        # 4. Archive run
        has_completion = step is not None
        if has_completion:
            try:
                manager = RunManager(PROJECTS_DIR)
                run = manager.find_run(run_id)
                if run.status == RunStatus.ACTIVE:
                    manager.archive_run(run_id)
                    logger.info("Archived run %s (reason=%s)", run_id, reason)
            except Exception:
                logger.debug("Failed to archive run %s", run_id, exc_info=True)

    # -- heartbeat helpers --

    def finalize_orphan_tasks(self) -> int:
        """Finalize EXECUTING tasks whose runs are archived or missing.

        Returns count of tasks finalized.
        """
        from frago.run.context import ContextManager
        from frago.run.manager import RunManager
        from frago.run.models import RunStatus

        executing = self._store.get_by_status(TaskStatus.EXECUTING)
        if not executing:
            return 0

        manager = RunManager(PROJECTS_DIR)
        ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
        count = 0

        for task in executing:
            run_id = task.session_id
            if not run_id:
                continue

            try:
                run = manager.find_run(run_id)
                if run.status == RunStatus.ACTIVE:
                    if ctx_mgr.get_current_run_id() == run_id:
                        continue  # current run, stale lock check handles it
                    # Active but not current — orphaned
                    try:
                        manager.archive_run(run_id)
                        logger.info("Archived orphan run %s", run_id)
                    except Exception:
                        logger.debug("Failed to archive orphan run %s", run_id, exc_info=True)
            except Exception:
                pass  # run not found — treat as gone

            self.finalize(task.id, run_id, reason="orphan_cleanup")
            count += 1
            logger.info("Finalized orphan task %s (run=%s)", task.id, run_id)

        return count

    def check_stale_run_lock(self) -> bool:
        """Check and release stale run locks. Returns True if a lock was released."""
        from frago.run.context import ContextManager

        try:
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            current_run_id = ctx_mgr.get_current_run_id()
            if not current_run_id:
                return False

            # Check for completion marker
            step, _summary = self._read_completion_info(current_run_id)
            if step is not None:
                ctx_mgr.release_context()
                self.finalize(None, current_run_id, reason="completion_marker")
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
                self.finalize(None, current_run_id, reason="timeout")
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

        messages = []
        for task in pending:
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

    def try_dispatch_queued(self) -> list[dict[str, Any]]:
        """Try to dispatch QUEUED tasks. Returns list of dispatch results.

        Called by heartbeat. QUEUED tasks already have PA's decision —
        they just need the run lock to be free.
        """
        queued = self._store.get_by_status(TaskStatus.QUEUED)
        if not queued:
            return []

        results = []
        for task in queued:
            result = self.dispatch(task.id, {
                "prompt": task.prompt,
                "description": task.prompt[:100],
            })
            results.append({"task_id": task.id, **result})
            if result["status"] == "ok":
                logger.info("Auto-dispatched QUEUED task %s", task.id[:8])
                break  # Only dispatch one at a time (single sub-agent constraint)
            elif result["status"] == "blocked":
                break  # Lock still held, no point trying more
        return results

    def update_task(self, task_id: str, status_str: str | None, result_summary: str | None) -> None:
        """Update task status and/or result_summary (PA action:'update')."""
        task = self._store.get(task_id)
        if not task:
            return

        status = task.status
        if status_str == "completed":
            status = TaskStatus.COMPLETED
        elif status_str == "failed":
            status = TaskStatus.FAILED

        self._store.update_status(task.id, status, result_summary=result_summary)

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
