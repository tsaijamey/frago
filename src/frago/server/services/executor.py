"""Single-threaded task executor.

Takes QUEUED tasks from TaskStore one at a time, launches sub-agents,
monitors until exit, extracts results, updates status, and notifies PA.

All task status transitions for run-type tasks flow through here —
no other code path modifies QUEUED → EXECUTING → COMPLETED/FAILED.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.models import IngestedTask, TaskStatus
from frago.server.services.ingestion.store import TaskStore

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"

# How often to poll for queued tasks when idle
POLL_INTERVAL = 1.0

# How often to check if a run lock held by external CLI has been released
EXTERNAL_LOCK_RETRY_INTERVAL = 10.0

# PID polling interval while monitoring agent
PID_POLL_INTERVAL = 5.0


class Executor:
    """Single-threaded task executor.

    从 TaskStore 内存取 queued 任务，一次一个，串行执行。
    所有状态变更写内存 → 异步刷盘。

    Loop:
      1. store.get_first_queued()
      2. check run lock (external CLI may hold it)
      3. acquire lock → launch agent → mark executing → 回填 session_id + pid
      4. monitor PID
      5. on exit: check _killed_by_resume → 如果是就跳过，重新监听新 pid
      6. extract results → mark completed/failed
      7. build system_notify → enqueue to PA
      8. release lock → next task
    """

    def __init__(
        self,
        store: TaskStore,
        pa_enqueue_message: Any = None,
        broadcast_pa_event: Any = None,
    ) -> None:
        self._store = store
        self._pa_enqueue_message = pa_enqueue_message  # async callable
        self._broadcast_pa_event = broadcast_pa_event  # async callable
        self._killed_by_resume: set[int] = set()
        self._loop_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the executor loop as an asyncio task."""
        if self._loop_task and not self._loop_task.done():
            logger.warning("Executor loop already running")
            return
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info("Executor started")

    async def stop(self) -> None:
        """Stop the executor loop."""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        logger.info("Executor stopped")

    # -- main loop --

    async def _run_loop(self) -> None:
        while True:
            task = self._store.get_first_queued()
            if not task:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            try:
                await self._execute_run(task)
            except Exception:
                logger.error("Executor: unhandled error executing task %s", task.id[:8], exc_info=True)
                self._store.update_status(task.id, TaskStatus.FAILED, error="executor internal error")
                from frago.server.services.trace import trace as _trace
                _trace(task.channel_message_id, task.id, "executor", "标记 FAILED: executor internal error")

    async def _execute_run(self, task: IngestedTask) -> None:
        """Execute a single queued task end-to-end."""
        from frago.run.context import ContextManager

        # 1. Check run lock (external CLI user may hold it)
        ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
        current_run = ctx_mgr.get_current_run_id()
        if current_run:
            logger.info(
                "Executor: run lock held by %s, retrying in %ds",
                current_run, int(EXTERNAL_LOCK_RETRY_INTERVAL),
            )
            await asyncio.sleep(EXTERNAL_LOCK_RETRY_INTERVAL)
            return  # task stays QUEUED, next loop iteration retries

        # 2. Launch agent
        run_id, pid = await self._launch_agent(task)
        if not run_id or not pid:
            return  # error already handled in _launch_agent

        # 3. Monitor PID until exit (with resume awareness)
        final_pid = await self._monitor_until_done(task, pid)
        if final_pid is None:
            # Killed by resume → resume handler re-entered monitoring
            return

        # 4. Determine success/failure from Claude Code session JSONL
        # Wait briefly for JSONL flush — Claude Code process may have exited
        # before the final assistant message was fsynced to disk.
        await asyncio.sleep(2.5)
        updated_task = self._store.get(task.id)
        claude_sid = updated_task.claude_session_id if updated_task else None
        stop_reason = self._read_stop_reason(claude_sid) if claude_sid else None

        # Trace: raw diagnosis before status decision
        from frago.server.services.trace import trace as _trace
        _trace(task.channel_message_id, task.id, "executor",
               f"读取结果: claude_sid={claude_sid and claude_sid[:8]}, stop_reason={stop_reason}")

        # 5. Update status based on Claude JSONL stop_reason
        #    (from 3940-session statistical analysis):
        #      end_turn / stop_sequence → agent finished naturally → COMPLETED
        #      None / tool_use / max_tokens → interrupted/crashed → FAILED
        _SUCCESS_STOP_REASONS = {"end_turn", "stop_sequence"}
        if stop_reason in _SUCCESS_STOP_REASONS:
            final_status = "COMPLETED"
            self._store.update_status(task.id, TaskStatus.COMPLETED,
                                      result_summary=f"completed (stop_reason: {stop_reason})")
        else:
            final_status = "FAILED"
            self._store.update_status(
                task.id, TaskStatus.FAILED,
                error=f"sub-agent exited abnormally (stop_reason: {stop_reason})",
            )

        # Trace: agent execution finished
        has_completion = stop_reason in _SUCCESS_STOP_REASONS
        duration = int((datetime.now() - task.created_at).total_seconds()) if task.created_at else 0
        from frago.server.services.trace import trace as _trace
        _trace(task.channel_message_id, task.id, "agent",
               f"执行结束 {final_status}: stop_reason={stop_reason}, run={run_id}",
               data={"event_type": "pa_agent_exited", "run_id": run_id, "task_id": task.id,
                     "has_completion": has_completion, "duration_seconds": duration})

        # 6. Release context lock
        try:
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            if ctx_mgr.get_current_run_id() == run_id:
                ctx_mgr.release_context()
        except Exception:
            logger.debug("Failed to release context lock for %s", run_id, exc_info=True)

        # 7. Archive run
        try:
            from frago.run.manager import RunManager
            manager = RunManager(PROJECTS_DIR)
            manager.archive_run(run_id)
        except Exception:
            logger.debug("Failed to archive run %s", run_id, exc_info=True)

        # 8. Broadcast event
        if self._broadcast_pa_event:
            await self._broadcast_pa_event("pa_agent_exited", {
                "run_id": run_id,
                "task_id": task.id,
                "has_completion": has_completion,
                "duration_seconds": duration,
            })

        # 9. Notify PA via system message
        await self._notify_pa(task, run_id, stop_reason)

    async def _launch_agent(self, task: IngestedTask) -> tuple[str | None, int | None]:
        """Create Run, acquire lock, build prompt, launch sub-agent process.

        On success: marks task EXECUTING, backfills session_id + pid.
        On failure: marks task FAILED.
        Returns (run_id, pid) or (None, None).
        """
        from frago.run.context import ContextManager
        from frago.run.exceptions import ContextAlreadySetError
        from frago.run.manager import RunManager
        from frago.server.services.agent_service import AgentService

        description = task.run_descriptions[-1] if task.run_descriptions else ""
        prompt = task.run_prompts[-1] if task.run_prompts else ""

        if not prompt:
            logger.error("Executor: task %s has no run_prompt", task.id[:8])
            self._store.update_status(task.id, TaskStatus.FAILED, error="missing run_prompt")
            from frago.server.services.trace import trace as _trace
            _trace(task.channel_message_id, task.id, "executor", "标记 FAILED: missing run_prompt")
            return None, None

        # Create Run instance
        manager = RunManager(PROJECTS_DIR)
        run = manager.create_run(
            description or prompt
        )
        run_id = run.run_id
        logger.info("Executor: created Run %s for task %s", run_id, task.id[:8])

        # Set mutex
        ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
        try:
            ctx_mgr.set_current_run(run_id, run.theme_description)
        except ContextAlreadySetError:
            logger.warning("Executor: run lock race for task %s", task.id[:8])
            return None, None  # stay QUEUED, retry next loop

        # Mark EXECUTING
        self._store.update_status(task.id, TaskStatus.EXECUTING, session_id=run_id)

        # Build sub-agent prompt
        from frago.server.services.primary_agent_service import PrimaryAgentService
        agent_prompt = PrimaryAgentService._build_sub_agent_prompt(
            task_id=task.id,
            task_prompt=prompt,
            run_id=run_id,
        )

        # Launch — pre-generate Claude Code session UUID for traceability
        import uuid as _uuid
        claude_session_id = str(_uuid.uuid4())

        result = AgentService.start_task(
            prompt=agent_prompt,
            project_path=str(Path.home()),
            env_extra={"FRAGO_CURRENT_RUN": run_id},
            claude_session_id=claude_session_id,
        )

        if result.get("status") != "ok":
            logger.error("Executor: failed to start agent for task %s: %s", task.id[:8], result.get("error"))
            ctx_mgr.release_context()
            self._store.update_status(task.id, TaskStatus.FAILED, error=result.get("error"))
            from frago.server.services.trace import trace as _trace
            _trace(task.channel_message_id, task.id, "executor",
                   f"标记 FAILED: agent 启动失败, error={result.get('error')}")
            return None, None

        pid = result["pid"]
        self._store.update_run_info(task.id, session_id=run_id, pid=pid,
                                    claude_session_id=claude_session_id)
        logger.info("Executor: agent launched for task %s (run=%s, claude=%s, pid=%d)",
                     task.id[:8], run_id, claude_session_id[:8], pid)

        _launched_data = {
            "run_id": run_id,
            "task_id": task.id,
            "description": description,
        }
        if self._broadcast_pa_event:
            await self._broadcast_pa_event("pa_agent_launched", _launched_data)
        # Trace: executor launched agent
        from frago.server.services.trace import trace as _trace
        _trace(task.channel_message_id, task.id, "executor",
               f"启动 agent, run={run_id}, pid={pid}",
               data={"event_type": "pa_agent_launched", **_launched_data})

        return run_id, pid

    async def _monitor_until_done(self, task: IngestedTask, pid: int) -> int | None:
        """Poll PID until process exits. Handles resume kills.

        Returns final PID on normal exit, or None if killed by resume
        (resume handler takes over monitoring).
        """
        while True:
            try:
                os.kill(pid, 0)
                await asyncio.sleep(PID_POLL_INTERVAL)
            except (ProcessLookupError, PermissionError):
                # Process exited
                if pid in self._killed_by_resume:
                    self._killed_by_resume.discard(pid)
                    # Re-read task to get new PID from resume
                    updated = self._store.get(task.id)
                    if updated and updated.pid and updated.pid != pid:
                        # Resume installed a new PID — continue monitoring
                        pid = updated.pid
                        logger.info("Executor: resume detected, now monitoring pid %d for task %s", pid, task.id[:8])
                        continue
                    # No new PID yet or same PID — unusual, treat as normal exit
                    logger.warning("Executor: resume kill but no new pid for task %s", task.id[:8])
                return pid

    # -- resume --

    async def execute_resume(self, task_id: str, new_prompt: str) -> None:
        """即时执行：kill 当前 agent → resume session → 回填新 pid。

        Called by PrimaryAgentService when PA decides 'resume'.
        """
        task = self._store.get(task_id)
        if not task or not task.pid or not task.session_id:
            logger.warning("Executor: cannot resume task %s (missing pid/session)", task_id[:8])
            return

        # Mark pid as killed-by-resume so monitor won't mark it failed
        self._killed_by_resume.add(task.pid)

        try:
            os.kill(task.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            logger.debug("Executor: pid %d already gone for task %s", task.pid, task_id[:8])

        # Resume session with new prompt
        from frago.server.services.agent_service import AgentService

        result = AgentService.continue_task(task.session_id, new_prompt)
        if result.get("status") != "ok":
            logger.error("Executor: failed to resume task %s: %s", task_id[:8], result.get("error"))
            self._killed_by_resume.discard(task.pid)
            return

        # Backfill new PID
        new_pid = result.get("pid")
        if new_pid:
            self._store.update_run_info(task_id, pid=new_pid)
            logger.info("Executor: resumed task %s with new pid %d", task_id[:8], new_pid)

    # -- result extraction --

    @staticmethod
    def _read_stop_reason(claude_session_id: str) -> str | None:
        """Read stop_reason from the last assistant message that has one set.

        Claude Code may append multiple assistant records per turn — only the
        record that concludes an API response carries a non-null stop_reason.
        Streaming text chunks and tool-use blocks without stop_reason are skipped.

        Returns: "end_turn" / "stop_sequence" (success), "tool_use" / "max_tokens"
                 (interrupted), or None (no assistant message found / crash).
        """
        # Derive JSONL path: ~/.claude/projects/{cwd-slug}/{uuid}.jsonl
        # cwd is Path.home() → slug is home path with / replaced by -
        home = str(Path.home())
        cwd_slug = home.replace("/", "-")
        jsonl_path = Path.home() / ".claude" / "projects" / cwd_slug / f"{claude_session_id}.jsonl"

        if not jsonl_path.exists():
            return None

        try:
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            # Scan from end, find the last assistant record with a non-null stop_reason
            for line in reversed(lines):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("type") == "assistant" and "message" in entry:
                    sr = entry["message"].get("stop_reason")
                    if sr is not None:
                        return str(sr)
        except Exception:
            pass

        return None

    @staticmethod
    def _extract_recent_logs(run_id: str, limit: int = 10) -> list[str]:
        """Extract recent log entries from run's execution.jsonl."""
        log_file = PROJECTS_DIR / run_id / "logs" / "execution.jsonl"
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            result = []
            for line in lines[-limit:]:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    step = entry.get("step", "")
                    status = entry.get("status", "")
                    result.append(f"[{ts}] {step}: {status}")
                except json.JSONDecodeError:
                    continue
            return result
        except Exception:
            return []

    @staticmethod
    def _extract_output_files(run_id: str) -> list[str]:
        """List files in run's outputs/ directory."""
        outputs_dir = PROJECTS_DIR / run_id / "outputs"
        if not outputs_dir.is_dir():
            return []
        try:
            return [f.name for f in outputs_dir.iterdir() if f.is_file()]
        except Exception:
            return []

    async def _notify_pa(
        self,
        task: IngestedTask,
        run_id: str,
        stop_reason: str | None = None,
    ) -> None:
        """Construct system message and enqueue to PA."""
        if not self._pa_enqueue_message:
            return

        outputs = self._extract_output_files(run_id)
        recent_logs = self._extract_recent_logs(run_id)

        _SUCCESS_STOP_REASONS = {"end_turn", "stop_sequence"}
        msg_type = "agent_completed" if stop_reason in _SUCCESS_STOP_REASONS else "agent_failed"

        # Use task's own result/error as summary
        updated = self._store.get(task.id)
        result_summary = (updated.result_summary or updated.error) if updated else None

        msg: dict[str, Any] = {
            "type": msg_type,
            "task_id": task.id,
            "channel": task.channel,
            "session_id": task.session_id,
            "run_id": run_id,
            "result_summary": result_summary or f"agent exited (stop_reason: {stop_reason})",
            "output_files": outputs,
            "recent_logs": recent_logs,
        }

        # Trace: executor notifying PA
        from frago.server.services.trace import trace as _trace
        _trace(task.channel_message_id, task.id, "executor", f"通知 PA: {msg_type}")

        try:
            await self._pa_enqueue_message(msg)
        except Exception:
            logger.error("Executor: failed to notify PA for task %s", task.id[:8], exc_info=True)
