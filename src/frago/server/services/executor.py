"""Parallel task executor.

Takes QUEUED tasks from the board (single source of truth — timeline.jsonl)
launches sub-agents in parallel via asyncio.create_task, monitors until exit,
extracts results, transitions task status, and notifies PA.

All task status transitions for run-type tasks flow through here —
no other code path modifies QUEUED → EXECUTING → COMPLETED/FAILED.

Spec 20260512-msg-task-board-redesign v1.2 freeze: TaskStore is gone.
Board public methods (mark_task_executing / mark_task_completed /
mark_task_failed / update_task_session / increment_*_count) are the only
persistence path.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.resume_inbox import ResumeInbox
from frago.server.services.taskboard import TaskBoard
from frago.server.services.taskboard.models import (
    ClaudeSessionNotFoundError,
)

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"

# How often to poll for queued tasks when idle
POLL_INTERVAL = 1.0

# PID polling interval while monitoring agent
PID_POLL_INTERVAL = 5.0

# Idle-stuck detection: if the claude JSONL hasn't been touched for this many
# minutes while the process is still alive, declare the agent stuck and kill
# it so the task can advance. Guards against zombie sub-agents that wrote
# outputs but never emitted a terminating assistant message (observed in
# 2026-04-19 5cf89f19 incident: 4.5h idle with SUMMARY.md already on disk).
IDLE_STUCK_TIMEOUT_MIN = 15


@dataclass
class _TaskContext:
    """Per-run snapshot extracted from board.

    The executor needs a handful of cross-cutting fields (channel, prompt,
    reply_context, thread_id, ...) that live across board.Task / board.Msg /
    board.Thread. We freeze them into a small struct at task-pickup time so
    downstream methods do not need to keep refetching from the board.
    """

    task_id: str
    prompt: str
    description: str
    channel: str
    channel_message_id: str
    thread_id: str | None
    reply_context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


def _hydrate_context(board: TaskBoard, task_id: str) -> _TaskContext | None:
    """Build a _TaskContext from board lookups; return None if task missing."""
    task = board.get_task(task_id)
    if task is None:
        return None
    msg = board.get_msg_for_task(task_id)
    thread = board.get_thread_for_task(task_id)
    if msg is None:
        return None
    channel_msg_id = msg.msg_id
    # board.Msg.msg_id is stored as "<channel>:<original_id>" by Ingestor;
    # strip the prefix when the caller wants the channel-native id.
    if channel_msg_id.startswith(f"{msg.source.channel}:"):
        channel_msg_id = channel_msg_id[len(msg.source.channel) + 1:]
    return _TaskContext(
        task_id=task.task_id,
        prompt=task.intent.prompt or msg.source.text,
        # description (first line ≤80 chars of prompt) is what we previously
        # stored in IngestedTask.run_descriptions[-1]; reuse the prompt head.
        description=(task.intent.prompt or msg.source.text).split("\n", 1)[0][:80],
        channel=msg.source.channel,
        channel_message_id=channel_msg_id,
        thread_id=thread.thread_id if thread else None,
        reply_context=dict(msg.source.reply_context or {}),
        created_at=task.created_at,
    )


class Executor:
    """Parallel task executor (board-only, no TaskStore).

    Discovers queued tasks via board.get_queued_tasks(), spawns asyncio.Task
    per task, mutates state via board public methods, writes timeline entries
    as the single source of truth.

    Loop:
      1. board.get_queued_tasks()
      2. asyncio.create_task(_execute_run(ctx)) per task (after mark_executing)
      3. each task: launch agent → update_task_session(run_id, csid, pid)
      4. monitor PID
      5. on exit: extract results → mark_task_completed / mark_task_failed
      6. best-effort close TabGroup
      7. build system_notify → enqueue to PA

    Resume semantics: PA "resume" no longer kills the sub-agent. New
    prompts are appended to ``ResumeInbox`` and picked up by the
    PreToolUse hook on the agent's next tool call (spec
    20260501-pa-resume-hot-injection).
    """

    def __init__(
        self,
        board: TaskBoard,
        pa_enqueue_message: Any = None,
        broadcast_pa_event: Any = None,
    ) -> None:
        self._board = board
        self._pa_enqueue_message = pa_enqueue_message  # async callable
        self._broadcast_pa_event = broadcast_pa_event  # async callable
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
        """Discover queued tasks on the board and dispatch each in parallel.

        All status transitions go through board public methods so the
        timeline observes them; no parallel store updates remain.
        """
        while True:
            queued = self._board.get_queued_tasks()
            if not queued:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for task in queued:
                ctx = _hydrate_context(self._board, task.task_id)
                if ctx is None:
                    logger.debug(
                        "Executor: task %s missing context — skipping",
                        task.task_id[:8],
                    )
                    continue
                try:
                    self._board.mark_task_executing(task.task_id, by="executor")
                except Exception:
                    logger.debug(
                        "Executor: mark_task_executing failed (non-fatal)",
                        exc_info=True,
                    )
                    continue
                t = asyncio.create_task(self._safe_execute_run(ctx))
                self._active_tasks.add(t)
                t.add_done_callback(self._active_tasks.discard)
            await asyncio.sleep(POLL_INTERVAL)

    async def _safe_execute_run(self, ctx: _TaskContext) -> None:
        """Wrapper around _execute_run that catches unhandled errors."""
        try:
            await self._execute_run(ctx)
        except Exception:
            logger.error(
                "Executor: unhandled error executing task %s",
                ctx.task_id[:8], exc_info=True,
            )
            self._board.mark_task_failed(
                ctx.task_id,
                error="executor internal error",
                by="executor",
            )

    async def _execute_run(self, ctx: _TaskContext) -> None:
        """Execute a single queued task end-to-end."""
        # 1. Launch agent
        run_id, pid = await self._launch_agent(ctx)
        if not run_id or not pid:
            return  # error already handled in _launch_agent

        await self._finalize_run(ctx, pid, run_id)

    async def _finalize_run(
        self, ctx: _TaskContext, pid: int, run_id: str,
    ) -> None:
        """Monitor running agent to completion, record result, archive, notify PA."""
        # 2. Monitor PID until exit
        await self._monitor_until_done(ctx, pid)

        # 3. Determine success/failure from Claude Code session JSONL
        # Wait briefly for JSONL flush — Claude Code process may have exited
        # before the final assistant message was fsynced to disk.
        await asyncio.sleep(2.5)
        task_obj = self._board.get_task(ctx.task_id)
        claude_sid = (
            task_obj.session.claude_session_id
            if task_obj and task_obj.session else None
        )
        stop_reason = self._read_stop_reason(claude_sid) if claude_sid else None

        # Trace: raw diagnosis before status decision
        from frago.server.services.trace import trace_entry
        trace_entry(
            origin="internal", subkind="executor", data_type="tool_result",
            thread_id=ctx.thread_id, task_id=ctx.task_id,
            msg_id=ctx.channel_message_id, role="executor",
            event=f"读取结果: claude_sid={claude_sid and claude_sid[:8]}, stop_reason={stop_reason}",
            data={"claude_sid_prefix": claude_sid[:8] if claude_sid else None,
                  "stop_reason": stop_reason},
        )

        # 4. Update status based on Claude JSONL stop_reason
        #    (from 3940-session statistical analysis):
        #      end_turn / stop_sequence → agent finished naturally → COMPLETED
        #      None / tool_use / max_tokens → interrupted/crashed → FAILED
        _SUCCESS_STOP_REASONS = {"end_turn", "stop_sequence"}
        final_text = self._read_final_assistant_text(claude_sid) if claude_sid else None
        if stop_reason in _SUCCESS_STOP_REASONS:
            final_status = "COMPLETED"
            if final_text:
                summary = final_text
            else:
                summary = f"completed (stop_reason: {stop_reason}) — no assistant text captured"
            self._board.mark_task_completed(
                ctx.task_id, summary=summary, by="executor",
            )
        else:
            final_status = "FAILED"
            base_error = f"sub-agent exited abnormally (stop_reason: {stop_reason})"
            if final_text:
                base_error = f"{base_error}\n\n{final_text}"
            self._board.mark_task_failed(
                ctx.task_id, error=base_error, by="executor",
            )

        # Trace: agent execution finished
        has_completion = stop_reason in _SUCCESS_STOP_REASONS
        duration = int((datetime.now() - ctx.created_at).total_seconds()) if ctx.created_at else 0
        trace_entry(
            origin="internal", subkind="executor", data_type="task_state",
            thread_id=ctx.thread_id, task_id=ctx.task_id,
            msg_id=ctx.channel_message_id, role="agent",
            event=f"执行结束 {final_status}: stop_reason={stop_reason}, run={run_id}",
            data={
                "event_type": "pa_agent_exited",
                "run_id": run_id, "task_id": ctx.task_id,
                "has_completion": has_completion,
                "duration_seconds": duration,
                "stop_reason": stop_reason,
                "final_status": final_status,
            },
        )

        # 5. Best-effort close TabGroup
        try:
            from frago.chrome.cdp.config import CDPConfig
            from frago.chrome.cdp.session import CDPSession
            from frago.chrome.cdp.tab_group_manager import TabGroupManager
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
                "task_id": ctx.task_id,
                "msg_id": ctx.channel_message_id or "",
                "has_completion": has_completion,
                "duration_seconds": duration,
            })

        # 8. Notify PA via system message
        await self._notify_pa(ctx, run_id, stop_reason)

    async def _get_or_create_run_for_thread(
        self,
        *,
        manager: "RunManager",  # noqa: F821 — forward reference
        thread_id: str | None,
        description: str,
        task_short_id: str,
    ) -> str:
        """Resolve the run_instance for a thread, creating on first use."""
        from frago.run.exceptions import RunNotFoundError

        canonical = manager.resolve_domain_from_description(description) or "misc"

        if thread_id:
            tdict = self._board.get_thread(thread_id)
            bound_run = tdict.get("run_instance_id") if tdict else None
            if bound_run:
                try:
                    existing = manager.find_run(bound_run)
                    if existing.run_id == canonical:
                        logger.info(
                            "Executor: reusing Run %s for task %s (thread=%s)",
                            existing.run_id, task_short_id, thread_id,
                        )
                        return existing.run_id
                    logger.info(
                        "Executor: thread %s bound to %s but description maps to %s — rebinding",
                        thread_id, existing.run_id, canonical,
                    )
                except RunNotFoundError:
                    logger.warning(
                        "Executor: thread %s binds missing run %s — creating new",
                        thread_id, bound_run,
                    )

        run = manager.ensure_domain(canonical)
        if description and description != run.theme_description:
            try:
                manager.update_run(run.run_id, theme_description=description)
            except Exception:
                logger.debug("Executor: update theme_description failed", exc_info=True)
        if thread_id:
            self._board.bind_run(thread_id, run.run_id, by="executor")
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

    async def _launch_agent(self, ctx: _TaskContext) -> tuple[str | None, int | None]:
        """Create Run, build prompt, launch sub-agent process.

        On success: writes Task.session (run_id / claude_session_id / pid).
        On failure: marks task FAILED.
        Returns (run_id, pid) or (None, None).
        """
        from frago.run.manager import RunManager
        from frago.server.services.agent_service import AgentService

        if not ctx.prompt:
            logger.error("Executor: task %s has no prompt", ctx.task_id[:8])
            self._board.mark_task_failed(
                ctx.task_id, error="missing run_prompt", by="executor",
            )
            return None, None

        # Get-or-create Run instance for this thread
        # Same thread → reuse same run_instance → workspace accumulates across turns.
        manager = RunManager(PROJECTS_DIR)
        run_id = await self._get_or_create_run_for_thread(
            manager=manager,
            thread_id=ctx.thread_id,
            description=ctx.description or ctx.prompt,
            task_short_id=ctx.task_id[:8],
        )

        # Phase 3: peek the resolved domain so the sub-agent boots with prior
        # context (recent sessions + top insights). Best-effort: a peek failure
        # must not block task launch.
        peek_payload: dict | None = None
        try:
            peek_payload = manager.peek_domain(run_id, n_sessions=3, n_insights=5)
        except Exception:
            logger.debug("Executor: peek_domain failed for %s", run_id, exc_info=True)
            peek_payload = None

        # Build sub-agent prompt
        from frago.server.services.primary_agent_service import PrimaryAgentService
        agent_prompt = PrimaryAgentService._build_sub_agent_prompt(
            task_id=ctx.task_id,
            task_prompt=ctx.prompt,
            run_id=run_id,
            domain_peek=peek_payload,
        )

        # Launch — pre-generate Claude Code session UUID for traceability
        import uuid as _uuid
        claude_session_id = str(_uuid.uuid4())

        # Phase 3: also inject FRAGO_DOMAIN so PreToolUse hook reminders can
        # interpolate the domain name and `frago run insights --save` resolves
        # the target domain without requiring an explicit --domain.
        result = AgentService.start_task(
            prompt=agent_prompt,
            project_path=str(Path.home()),
            env_extra={
                "FRAGO_CURRENT_RUN": run_id,
                "FRAGO_DOMAIN": run_id,
            },
            claude_session_id=claude_session_id,
        )

        if result.get("status") != "ok":
            logger.error("Executor: failed to start agent for task %s: %s", ctx.task_id[:8], result.get("error"))
            self._board.mark_task_failed(
                ctx.task_id,
                error=str(result.get("error") or "agent start failed"),
                by="executor",
            )
            return None, None

        pid = result["pid"]
        self._board.update_task_session(
            ctx.task_id,
            run_id=run_id,
            claude_session_id=claude_session_id,
            pid=pid,
            by="executor",
        )
        logger.info("Executor: agent launched for task %s (run=%s, claude=%s, pid=%d)",
                     ctx.task_id[:8], run_id, claude_session_id[:8], pid)

        _launched_data = {
            "run_id": run_id,
            "task_id": ctx.task_id,
            "msg_id": ctx.channel_message_id or "",
            "description": ctx.description,
        }
        if self._broadcast_pa_event:
            await self._broadcast_pa_event("pa_agent_launched", _launched_data)
        # Trace: executor launched agent
        from frago.server.services.trace import trace_entry
        trace_entry(
            origin="internal", subkind="executor", data_type="task_state",
            thread_id=ctx.thread_id, task_id=ctx.task_id,
            msg_id=ctx.channel_message_id, role="executor",
            event=f"启动 agent, run={run_id}, pid={pid}",
            data={"event_type": "pa_agent_launched", **_launched_data, "pid": pid},
        )

        return run_id, pid

    async def _monitor_until_done(self, ctx: _TaskContext, pid: int) -> int:
        """Poll PID until process exits OR declares itself stuck.

        Returns final PID on exit (normal or idle-stuck kill).

        Idle-stuck detection: if the claude JSONL file hasn't grown for
        IDLE_STUCK_TIMEOUT_MIN minutes, kill the process and treat as exit
        so the task moves to a terminal state instead of waiting forever.
        """
        from pathlib import Path as _Path

        idle_timeout_sec = IDLE_STUCK_TIMEOUT_MIN * 60
        home_str = str(_Path.home())
        cwd_slug = home_str.replace("/", "-")

        def _jsonl_mtime() -> float | None:
            task_obj = self._board.get_task(ctx.task_id)
            claude_sid = (
                task_obj.session.claude_session_id
                if task_obj and task_obj.session else None
            )
            if not claude_sid:
                return None
            jsonl_path = _Path.home() / ".claude" / "projects" / cwd_slug / f"{claude_sid}.jsonl"
            try:
                return jsonl_path.stat().st_mtime
            except OSError:
                return None

        last_active = _jsonl_mtime() or time.time()

        while True:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                return pid

            await asyncio.sleep(PID_POLL_INTERVAL)

            # Idle-stuck check: refresh mtime; if unchanged for too long, declare stuck
            cur_mtime = _jsonl_mtime()
            if cur_mtime and cur_mtime > last_active:
                last_active = cur_mtime

            if time.time() - last_active > idle_timeout_sec:
                logger.warning(
                    "Executor: task %s idle for %.0f min (pid %d alive but JSONL not growing) "
                    "— declaring stuck, killing process",
                    ctx.task_id[:8], (time.time() - last_active) / 60, pid,
                )
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, signal.SIGTERM)
                # Mark task FAILED with a clear reason; outputs on disk are preserved.
                self._board.mark_task_failed(
                    ctx.task_id,
                    error=f"idle-stuck: no JSONL activity for {IDLE_STUCK_TIMEOUT_MIN}+ min",
                    by="executor",
                )
                from frago.server.services.trace import trace_entry
                trace_entry(
                    origin="internal", subkind="executor", data_type="os_event",
                    thread_id=ctx.thread_id, task_id=ctx.task_id,
                    msg_id=ctx.channel_message_id,
                    data={"kind": "idle_stuck_kill",
                          "idle_minutes": IDLE_STUCK_TIMEOUT_MIN,
                          "pid": pid},
                    event="idle-stuck kill",
                )
                return pid

    # -- B-2a: spawn_resume for ResumeApplier Case A (FRAGO_CASE_A_ENABLED) --
    def spawn_resume(
        self,
        csid: str | None,
        prompt: str,
    ) -> tuple[str, int]:
        """Spawn a brand-new sub-agent that resumes a Claude session by CSID.

        Used by ResumeApplier when ``task.status ∈ {completed, failed}`` (the
        prior session has already exited). Distinct from
        ``execute_resume`` which appends to ResumeInbox for live sessions.

        Returns ``(new_run_id, new_pid)``. Raises
        ``ClaudeSessionNotFoundError`` when the CSID file no longer exists on
        disk — ResumeApplier catches this and marks the task ``resume_failed``.
        """
        import uuid as _uuid

        from frago.server.services.agent_service import AgentService

        if csid:
            home = str(Path.home())
            cwd_slug = home.replace("/", "-")
            jsonl_path = Path.home() / ".claude" / "projects" / cwd_slug / f"{csid}.jsonl"
            if not jsonl_path.exists():
                raise ClaudeSessionNotFoundError(
                    f"Claude session jsonl not found: {jsonl_path}"
                )

        new_run_id = f"resume-{_uuid.uuid4().hex[:12]}"
        result = AgentService.start_task(
            prompt=prompt,
            project_path=str(Path.home()),
            env_extra={
                "FRAGO_CURRENT_RUN": new_run_id,
                "FRAGO_DOMAIN": new_run_id,
            },
            claude_session_id=csid,
        )
        if result.get("status") != "ok":
            raise RuntimeError(
                f"spawn_resume failed: {result.get('error', 'unknown')}"
            )
        return new_run_id, int(result["pid"])

    # -- resume --

    async def execute_resume(
        self, task_id: str, new_prompt: str,
    ) -> dict[str, Any]:
        """Resume via PreToolUse hot injection (spec 20260501).

        Appends the new prompt to the per-claude-session ``ResumeInbox``;
        the agent's next PreToolUse hook drains the inbox and surfaces
        the prompts as ``additionalContext``. The sub-agent process is
        not killed and not restarted — if it has already exited the
        injection is left pending until the session is revived (or
        cleaned up by the 7-day .consumed/ retention).

        Returns a structured result:
            {"status": "ok", "claude_session_id": str, "injection_id": str}
            {"status": "failed", "reason": str, "detail": str}
        """
        from frago.server.services.trace import trace_entry

        task = self._board.get_task(task_id)
        thread = self._board.get_thread_for_task(task_id)
        thread_id = thread.thread_id if thread else None

        if not task:
            reason = "task_not_found"
            detail = (
                "Task is not on the board (may have been archived or never "
                "existed). Resume cannot target an archived task."
            )
            logger.warning("Executor: resume %s failed — %s", task_id[:8], reason)
            trace_entry(
                origin="internal", subkind="executor", data_type="action_result",
                thread_id=None, task_id=task_id,
                data={"action": "resume", "status": "failed",
                      "reason": reason, "detail": detail},
                event=f"resume 失败: {reason}",
            )
            return {"status": "failed", "reason": reason, "detail": detail}

        session = task.session
        if session is None or not session.run_id:
            reason = "missing_session_id"
            detail = "Task has no bound session_id — never entered EXECUTING state."
            logger.warning("Executor: resume %s failed — %s", task_id[:8], reason)
            trace_entry(
                origin="internal", subkind="executor", data_type="action_result",
                thread_id=thread_id, task_id=task_id,
                data={"action": "resume", "status": "failed",
                      "reason": reason, "detail": detail},
                event=f"resume 失败: {reason}",
            )
            return {"status": "failed", "reason": reason, "detail": detail}

        if not session.claude_session_id:
            reason = "missing_claude_session_id"
            detail = (
                "Task has no claude_session_id — sub-agent never reached the "
                "init event. Hot injection requires a known Claude session UUID."
            )
            logger.warning("Executor: resume %s failed — %s", task_id[:8], reason)
            trace_entry(
                origin="internal", subkind="executor", data_type="action_result",
                thread_id=thread_id, task_id=task_id,
                data={"action": "resume", "status": "failed",
                      "reason": reason, "detail": detail},
                event=f"resume 失败: {reason}",
            )
            return {"status": "failed", "reason": reason, "detail": detail}

        try:
            injection = ResumeInbox.append(
                run_id=session.run_id,
                claude_session_id=session.claude_session_id,
                task_id=task_id,
                prompt=new_prompt,
                pa_thread_id=thread_id,
            )
        except Exception as e:
            reason = "inbox_write_failed"
            detail = f"Failed to write resume_inbox file: {e}"
            logger.error("Executor: resume %s failed — %s", task_id[:8], detail,
                         exc_info=True)
            trace_entry(
                origin="internal", subkind="executor", data_type="action_result",
                thread_id=thread_id, task_id=task_id,
                data={"action": "resume", "status": "failed",
                      "reason": reason, "detail": detail},
                event=f"resume 失败: {reason}",
            )
            return {"status": "failed", "reason": reason, "detail": detail}

        logger.info(
            "Executor: queued hot-injection %s for task %s (csid=%s)",
            injection.injection_id[:8], task_id[:8],
            session.claude_session_id[:8],
        )

        trace_entry(
            origin="internal", subkind="executor", data_type="action_result",
            thread_id=thread_id, task_id=task_id,
            data={"action": "resume", "status": "ok",
                  "injection_id": injection.injection_id,
                  "claude_session_id": session.claude_session_id,
                  "session_id": session.run_id},
            event=f"resume 排队: injection={injection.injection_id[:8]}",
        )

        return {
            "status": "ok",
            "injection_id": injection.injection_id,
            "claude_session_id": session.claude_session_id,
        }

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
    def _extract_output_files(run_id: str, since: "datetime | None" = None) -> list[str]:
        """List files in run's outputs/ directory.

        Phase 3 (run-as-domain): when ``since`` is given, only return files
        whose mtime is at or after that timestamp. Domains are long-lived so
        the directory accumulates historical artefacts; reporting them as
        "this session's outputs" is misleading.
        """
        outputs_dir = PROJECTS_DIR / run_id / "outputs"
        if not outputs_dir.is_dir():
            return []
        try:
            since_ts = since.timestamp() if since else None
            out: list[str] = []
            for f in outputs_dir.iterdir():
                if not f.is_file():
                    continue
                if since_ts is not None and f.stat().st_mtime < since_ts:
                    continue
                out.append(f.name)
            return out
        except Exception:
            return []

    async def _notify_pa(
        self,
        ctx: _TaskContext,
        run_id: str,
        stop_reason: str | None = None,
    ) -> None:
        """Construct system message and enqueue to PA."""
        if not self._pa_enqueue_message:
            return

        # Phase 3: only list outputs produced during this session window so
        # historical files in the long-lived domain dir don't pollute the
        # PA's "输出物" line.
        task_obj = self._board.get_task(ctx.task_id)
        session = task_obj.session if task_obj else None
        session_started_at = session.started_at if session else ctx.created_at
        outputs = self._extract_output_files(run_id, since=session_started_at)
        recent_logs = self._extract_recent_logs(run_id)

        _SUCCESS_STOP_REASONS = {"end_turn", "stop_sequence"}
        msg_type = "agent_completed" if stop_reason in _SUCCESS_STOP_REASONS else "agent_failed"

        # Use task's own result/error as summary
        result_summary: str | None = None
        if task_obj and task_obj.result is not None:
            result_summary = task_obj.result.summary or task_obj.result.error

        msg: dict[str, Any] = {
            "type": msg_type,
            "task_id": ctx.task_id,
            "channel": ctx.channel,
            "session_id": session.run_id if session else None,
            "run_id": run_id,
            "result_summary": result_summary or f"agent exited (stop_reason: {stop_reason})",
            "output_files": outputs,
            "recent_logs": recent_logs,
            "event_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Trace: executor notifying PA
        from frago.server.services.trace import trace_entry
        trace_entry(
            origin="internal", subkind="executor", data_type="os_event",
            thread_id=ctx.thread_id, task_id=ctx.task_id,
            msg_id=ctx.channel_message_id, role="executor",
            event=f"通知 PA: {msg_type}",
            data={"notify_type": msg_type},
        )

        try:
            await self._pa_enqueue_message(msg)
        except Exception:
            logger.error("Executor: failed to notify PA for task %s", ctx.task_id[:8], exc_info=True)
