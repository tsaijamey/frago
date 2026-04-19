"""Parallel task executor.

Takes QUEUED tasks from TaskStore, launches sub-agents in parallel via
asyncio.create_task, monitors until exit, extracts results, updates
status, and notifies PA.

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

# PID polling interval while monitoring agent
PID_POLL_INTERVAL = 5.0


class Executor:
    """Parallel task executor.

    从 TaskStore 取所有 queued 任务，每个 spawn asyncio.Task 并行执行。
    所有状态变更写内存 → 异步刷盘。

    Loop:
      1. store.get_by_status(QUEUED) → drain all
      2. asyncio.create_task(_execute_run(task)) per task
      3. each task: launch agent → mark executing → 回填 session_id + pid
      4. monitor PID
      5. on exit: check _killed_by_resume → 如果是就跳过，重新监听新 pid
      6. extract results → mark completed/failed
      7. best-effort close TabGroup
      8. build system_notify → enqueue to PA
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
        self._active_tasks: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        """Start the executor loop as an asyncio task."""
        if self._loop_task and not self._loop_task.done():
            logger.warning("Executor loop already running")
            return
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info("Executor started")

    async def stop(self) -> None:
        """Stop the executor loop and cancel active tasks."""
        # Cancel active tasks first
        for t in list(self._active_tasks):
            t.cancel()
        for t in list(self._active_tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._active_tasks.clear()

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        logger.info("Executor stopped")

    # -- main loop --

    async def _run_loop(self) -> None:
        while True:
            tasks = self._store.get_by_status(TaskStatus.QUEUED)
            if not tasks:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for task in tasks:
                self._store.update_status(task.id, TaskStatus.EXECUTING)
                t = asyncio.create_task(self._safe_execute_run(task))
                self._active_tasks.add(t)
                t.add_done_callback(self._active_tasks.discard)
            await asyncio.sleep(POLL_INTERVAL)

    async def _safe_execute_run(self, task: IngestedTask) -> None:
        """Wrapper around _execute_run that catches unhandled errors."""
        try:
            await self._execute_run(task)
        except Exception:
            logger.error("Executor: unhandled error executing task %s", task.id[:8], exc_info=True)
            # update_status emits task_state entry automatically (spec 20260418 Phase 4)
            self._store.update_status(task.id, TaskStatus.FAILED, error="executor internal error")

    async def _execute_run(self, task: IngestedTask) -> None:
        """Execute a single queued task end-to-end."""
        # 1. Launch agent
        run_id, pid = await self._launch_agent(task)
        if not run_id or not pid:
            return  # error already handled in _launch_agent

        # 2. Monitor PID until exit (with resume awareness)
        final_pid = await self._monitor_until_done(task, pid)
        if final_pid is None:
            # Killed by resume → resume handler re-entered monitoring
            return

        # 3. Determine success/failure from Claude Code session JSONL
        # Wait briefly for JSONL flush — Claude Code process may have exited
        # before the final assistant message was fsynced to disk.
        await asyncio.sleep(2.5)
        updated_task = self._store.get(task.id)
        claude_sid = updated_task.claude_session_id if updated_task else None
        stop_reason = self._read_stop_reason(claude_sid) if claude_sid else None

        # Trace: raw diagnosis before status decision (result observation, not state change)
        from frago.server.services.trace import trace_entry
        trace_entry(
            origin="internal", subkind="executor", data_type="tool_result",
            thread_id=task.thread_id, task_id=task.id,
            msg_id=task.channel_message_id, role="executor",
            event=f"读取结果: claude_sid={claude_sid and claude_sid[:8]}, stop_reason={stop_reason}",
            data={"claude_sid_prefix": claude_sid[:8] if claude_sid else None,
                  "stop_reason": stop_reason},
        )

        # 4. Update status based on Claude JSONL stop_reason
        #    (from 3940-session statistical analysis):
        #      end_turn / stop_sequence → agent finished naturally → COMPLETED
        #      None / tool_use / max_tokens → interrupted/crashed → FAILED
        _SUCCESS_STOP_REASONS = {"end_turn", "stop_sequence"}
        # 抽 sub-agent 最后一条 assistant 文本作为给 PA 的原料
        final_text = self._read_final_assistant_text(claude_sid) if claude_sid else None
        if stop_reason in _SUCCESS_STOP_REASONS:
            final_status = "COMPLETED"
            if final_text:
                summary = final_text
            else:
                summary = f"completed (stop_reason: {stop_reason}) — no assistant text captured"
            self._store.update_status(task.id, TaskStatus.COMPLETED,
                                      result_summary=summary)
        else:
            final_status = "FAILED"
            base_error = f"sub-agent exited abnormally (stop_reason: {stop_reason})"
            if final_text:
                base_error = f"{base_error}\n\n{final_text}"
            self._store.update_status(
                task.id, TaskStatus.FAILED,
                error=base_error,
            )

        # Trace: agent execution finished
        has_completion = stop_reason in _SUCCESS_STOP_REASONS
        duration = int((datetime.now() - task.created_at).total_seconds()) if task.created_at else 0
        trace_entry(
            origin="internal", subkind="executor", data_type="task_state",
            thread_id=task.thread_id, task_id=task.id,
            msg_id=task.channel_message_id, role="agent",
            event=f"执行结束 {final_status}: stop_reason={stop_reason}, run={run_id}",
            data={
                "event_type": "pa_agent_exited",
                "run_id": run_id, "task_id": task.id,
                "has_completion": has_completion,
                "duration_seconds": duration,
                "stop_reason": stop_reason,
                "final_status": final_status,
            },
        )

        # 5. Best-effort close TabGroup
        try:
            from frago.cdp.config import CDPConfig
            from frago.cdp.session import CDPSession
            from frago.cdp.tab_group_manager import TabGroupManager
            tgm = TabGroupManager()
            group = tgm.get_group(run_id)
            if group:
                session = CDPSession(CDPConfig())
                session.connect()
                try:
                    tgm.close_group(run_id, session)
                finally:
                    session.disconnect()
        except Exception:
            logger.debug("Failed to close tab group for %s", run_id, exc_info=True)

        # 6. Archive run
        try:
            from frago.run.manager import RunManager
            manager = RunManager(PROJECTS_DIR)
            manager.archive_run(run_id)
        except Exception:
            logger.debug("Failed to archive run %s", run_id, exc_info=True)

        # 7. Broadcast event
        if self._broadcast_pa_event:
            await self._broadcast_pa_event("pa_agent_exited", {
                "run_id": run_id,
                "task_id": task.id,
                "msg_id": task.channel_message_id or "",
                "has_completion": has_completion,
                "duration_seconds": duration,
            })

        # 8. Notify PA via system message
        await self._notify_pa(task, run_id, stop_reason)

    async def _get_or_create_run_for_thread(
        self,
        *,
        manager: "RunManager",  # noqa: F821 — forward reference
        thread_id: str | None,
        description: str,
        task_short_id: str,
    ) -> str:
        """Resolve the run_instance for a thread, creating on first use.

        If thread has a bound run_instance that still exists on disk → reuse.
        Otherwise create a new run and bind it to the thread. No thread_id → fresh run.
        """
        from frago.run.exceptions import RunNotFoundError
        from frago.server.services.thread_service import get_thread_store

        if thread_id:
            store = get_thread_store()
            idx = store.get(thread_id)
            if idx and idx.run_instance_id:
                # Thread already has a run — verify it still exists, else fall through to create
                try:
                    existing = manager.find_run(idx.run_instance_id)
                    logger.info(
                        "Executor: reusing Run %s for task %s (thread=%s)",
                        existing.run_id, task_short_id, thread_id,
                    )
                    return existing.run_id
                except RunNotFoundError:
                    logger.warning(
                        "Executor: thread %s binds missing run %s — creating new",
                        thread_id, idx.run_instance_id,
                    )

        run = manager.create_run(description)
        if thread_id:
            get_thread_store().bind_run(thread_id, run.run_id)
            logger.info(
                "Executor: created Run %s for task %s and bound to thread %s",
                run.run_id, task_short_id, thread_id,
            )
        else:
            logger.info(
                "Executor: created Run %s for task %s (no thread)",
                run.run_id, task_short_id,
            )
        return run.run_id

    async def _launch_agent(self, task: IngestedTask) -> tuple[str | None, int | None]:
        """Create Run, build prompt, launch sub-agent process.

        On success: backfills session_id + pid.
        On failure: marks task FAILED.
        Returns (run_id, pid) or (None, None).
        """
        from frago.run.manager import RunManager
        from frago.server.services.agent_service import AgentService

        description = task.run_descriptions[-1] if task.run_descriptions else ""
        prompt = task.run_prompts[-1] if task.run_prompts else ""

        if not prompt:
            logger.error("Executor: task %s has no run_prompt", task.id[:8])
            # update_status emits task_state entry automatically (spec 20260418 Phase 4)
            self._store.update_status(task.id, TaskStatus.FAILED, error="missing run_prompt")
            return None, None

        # Get-or-create Run instance for this thread (spec 20260418-thread-organization Phase 3)
        # Same thread → reuse same run_instance → workspace accumulates across turns.
        manager = RunManager(PROJECTS_DIR)
        run_id = await self._get_or_create_run_for_thread(
            manager=manager,
            thread_id=task.thread_id,
            description=description or prompt,
            task_short_id=task.id[:8],
        )

        # Update session_id on the already-EXECUTING task
        self._store.update_run_info(task.id, session_id=run_id)

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
            # update_status emits task_state entry automatically (spec 20260418 Phase 4)
            self._store.update_status(task.id, TaskStatus.FAILED, error=result.get("error"))
            return None, None

        pid = result["pid"]
        self._store.update_run_info(task.id, session_id=run_id, pid=pid,
                                    claude_session_id=claude_session_id)
        logger.info("Executor: agent launched for task %s (run=%s, claude=%s, pid=%d)",
                     task.id[:8], run_id, claude_session_id[:8], pid)

        _launched_data = {
            "run_id": run_id,
            "task_id": task.id,
            "msg_id": task.channel_message_id or "",
            "description": description,
        }
        if self._broadcast_pa_event:
            await self._broadcast_pa_event("pa_agent_launched", _launched_data)
        # Trace: executor launched agent (supplements the QUEUED→EXECUTING
        # task_state entry from update_status with run_id/pid context)
        from frago.server.services.trace import trace_entry
        trace_entry(
            origin="internal", subkind="executor", data_type="task_state",
            thread_id=task.thread_id, task_id=task.id,
            msg_id=task.channel_message_id, role="executor",
            event=f"启动 agent, run={run_id}, pid={pid}",
            data={"event_type": "pa_agent_launched", **_launched_data, "pid": pid},
        )

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
    def _read_final_assistant_text(claude_session_id: str, max_turns: int = 5) -> str | None:
        """抽取 session 结束前最后 max_turns 条有文本的 assistant 记录，按时间顺序拼接。

        与 _read_stop_reason 走同一份 JSONL。反向扫描：只要是 assistant 记录
        且含至少一个非空 type="text" content block 就收集（不管 stop_reason，
        因为中间 tool_use 轮次里也常有 text block 表达思考过程）。收集满
        max_turns 条即停；按时间顺序（最早→最晚）拼接，每条用
        `--- msg N/M ---` 分隔。无文本或异常返回 None。
        """
        home = str(Path.home())
        cwd_slug = home.replace("/", "-")
        jsonl_path = Path.home() / ".claude" / "projects" / cwd_slug / f"{claude_session_id}.jsonl"

        if not jsonl_path.exists():
            return None

        try:
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            collected: list[str] = []  # newest first during scan
            for line in reversed(lines):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("type") != "assistant" or "message" not in entry:
                    continue
                content = entry["message"].get("content")
                if not isinstance(content, list):
                    continue
                texts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                joined = "\n".join(t for t in texts if t)
                if joined:
                    collected.append(joined)
                if len(collected) >= max_turns:
                    break

            if not collected:
                return None

            ordered = list(reversed(collected))
            total = len(ordered)
            if total == 1:
                return ordered[0]
            parts = [f"--- msg {i + 1}/{total} ---\n{t}" for i, t in enumerate(ordered)]
            return "\n\n".join(parts)
        except Exception:
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
            "session_id": updated.session_id if updated else task.session_id,
            "run_id": run_id,
            "result_summary": result_summary or f"agent exited (stop_reason: {stop_reason})",
            "output_files": outputs,
            "recent_logs": recent_logs,
        }

        # Trace: executor notifying PA (cross-module message, treated as os_event)
        from frago.server.services.trace import trace_entry
        trace_entry(
            origin="internal", subkind="executor", data_type="os_event",
            thread_id=task.thread_id, task_id=task.id,
            msg_id=task.channel_message_id, role="executor",
            event=f"通知 PA: {msg_type}",
            data={"notify_type": msg_type},
        )

        try:
            await self._pa_enqueue_message(msg)
        except Exception:
            logger.error("Executor: failed to notify PA for task %s", task.id[:8], exc_info=True)
