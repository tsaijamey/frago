"""Task Lifecycle — coordination point for ingestion, reply, and recovery.

Spec 20260512-msg-task-board-redesign v1.2 freeze: board.timeline.jsonl is
the single source of persistence. TaskStore + ingested_tasks.json are gone.

The lifecycle reads task / msg / thread context directly from board public
methods (get_task / get_msg_for_task / get_thread_for_task / get_queued_tasks
/ get_executing_tasks / increment_recovery_count / mark_task_failed).
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from frago.server.services.taskboard import get_board

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"
CONFIG_FILE = FRAGO_HOME / "config.json"


@dataclass
class TaskView:
    """Read-only projection used by PA / reply paths.

    Aggregates fields from board.Task + board.Msg + board.Thread so callers
    do not need to navigate the live object graph. Returned by ``get_task``
    and ``find_task_for_run``.
    """

    task_id: str
    status: str
    prompt: str
    channel: str
    channel_message_id: str
    thread_id: str | None
    reply_context: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    claude_session_id: str | None = None
    pid: int | None = None
    result_summary: str | None = None
    error: str | None = None
    recovery_count: int = 0


def _board_task_to_view(board, task_id: str) -> TaskView | None:
    task = board.get_task(task_id)
    if task is None:
        return None
    msg = board.get_msg_for_task(task_id)
    thread = board.get_thread_for_task(task_id)
    if msg is None:
        return None
    channel = msg.source.channel
    channel_msg_id = msg.msg_id
    if channel_msg_id.startswith(f"{channel}:"):
        channel_msg_id = channel_msg_id[len(channel) + 1:]
    sess = task.session
    res = task.result
    return TaskView(
        task_id=task.task_id,
        status=task.status,
        prompt=task.intent.prompt or msg.source.text,
        channel=channel,
        channel_message_id=channel_msg_id,
        thread_id=thread.thread_id if thread else None,
        reply_context=dict(msg.source.reply_context or {}),
        session_id=sess.run_id if sess else None,
        claude_session_id=sess.claude_session_id if sess else None,
        pid=sess.pid if sess else None,
        result_summary=res.summary if res else None,
        error=res.error if res else None,
        recovery_count=task.recovery_count,
    )


class TaskLifecycle:
    """Single coordination point for task state transitions.

    Not a singleton — instantiated by PrimaryAgentService.
    """

    def __init__(self) -> None:
        # Per-run already-auto-sent image paths. Keyed by run_id because multiple
        # tasks can reuse the same Run (shared outputs/ dir). Scoped to the
        # lifecycle instance — not persisted across server restarts.
        self._sent_image_paths: dict[str, set[str]] = {}

    # -- ingestion --

    def ingest(
        self,
        channel: str,
        messages: list[dict[str, Any]],
    ) -> list[str]:
        """Ingest messages from a channel: dedup → create board msg/task.

        Returns the list of board.Task ids appended this call (only the
        tasks freshly created; dup msg_ids that already had tasks are skipped).
        """
        from datetime import datetime

        from frago.server.services.taskboard.ingestor import Ingestor
        from frago.server.services.taskboard.models import IllegalTransitionError

        new_task_ids: list[str] = []
        board = get_board()
        for msg in messages:
            msg_id = str(msg.get("id", ""))
            if not msg_id or "prompt" not in msg:
                logger.warning("Channel %s: message missing required fields, skipping", channel)
                continue

            # Dedup on the board (msg_id already known → duplicate_msg_ingest).
            view = board.view_for_pa()
            board_msg_id = f"{channel}:{msg_id}"
            already_present = any(
                m.get("id") == board_msg_id
                for t in view.get("threads", [])
                for m in t.get("msgs", [])
            )
            if already_present:
                logger.debug("Channel %s: message %s already on board, skipping", channel, msg_id)
                continue

            # Thread attribution
            from frago.server.services.thread_classifier import (
                classify as _thread_classify,
            )
            from frago.server.services.thread_classifier import (
                ensure_thread as _ensure_thread,
            )

            _reply_ctx = msg.get("reply_context", {})
            _sender = _reply_ctx.get("sender_id") or _reply_ctx.get("sender") or ""
            _classify = _thread_classify(
                channel=channel,
                sender=_sender,
                content=msg["prompt"],
                reply_context=_reply_ctx,
            )
            _ensure_thread(
                _classify,
                channel=channel,
                sender=_sender,
                msg_id=msg_id,
                root_summary=msg["prompt"][:80],
            )

            # Mirror into board via Ingestor; dedup inside board.append_msg.
            try:
                import contextlib as _contextlib

                with _contextlib.suppress(IllegalTransitionError):
                    board.create_thread(
                        thread_id=_classify.thread_id,
                        origin="external",
                        subkind=channel,
                        root_summary=msg["prompt"][:80],
                        by="TaskLifecycle",
                    )
                Ingestor(board).ingest_external(
                    channel=channel,
                    msg_id=msg_id,
                    sender_id=_sender,
                    text=msg["prompt"],
                    parent_ref=_classify.parent_ref,
                    received_at=datetime.now(),
                    reply_context=_reply_ctx,
                    thread_id=_classify.thread_id,
                )
            except Exception:
                logger.debug("TaskLifecycle: TaskBoard ingest failed", exc_info=True)
                continue

            # Collect freshly appended task ids (tasks on the just-seen msg).
            board_msg = board._find_msg(board_msg_id)  # noqa: SLF001 — internal lookup
            if board_msg:
                for tk in board_msg.tasks:
                    new_task_ids.append(tk.task_id)

        return new_task_ids

    # -- reply --

    def reply(self, task_id: str, channel: str, reply_params: dict[str, Any]) -> dict[str, Any]:
        """Execute a reply via notify recipe. Returns {"status": "ok"/"error"}.

        Enriches params with reply_context (from board.Msg.source.reply_context),
        runs notify recipe. Caller (_send_reply) handles task status updates.
        """
        if channel == "cli":
            return {"status": "ok"}

        # Enrich reply_params with reply_context from the board task
        if task_id:
            view = _board_task_to_view(get_board(), task_id)

            # Safety check: verify task_id matches the declared channel
            if view and view.channel != channel:
                logger.warning(
                    "Channel mismatch: task %s belongs to channel '%s' but PA declared '%s'. "
                    "Using task's actual channel to prevent cross-channel reply.",
                    task_id, view.channel, channel,
                )
                channel = view.channel

            if view and view.reply_context:
                full_params = {
                    "text": reply_params.get("text", ""),
                    "reply_context": view.reply_context,
                }
                if reply_params.get("html_body"):
                    full_params["html_body"] = reply_params["html_body"]
                # Preserve attachment fields — previously these were silently
                # dropped whenever a task had reply_context, causing PA's
                # file_path / image_path to vanish (problem 6 of 2026-04-19 audit).
                if reply_params.get("file_path"):
                    full_params["file_path"] = reply_params["file_path"]
                if reply_params.get("image_path"):
                    full_params["image_path"] = reply_params["image_path"]
                reply_params = full_params

        # Find and run notify recipe for channel
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            channels = (raw.get("task_ingestion") or {}).get("channels") or []
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

            # Auto-send output image files for completed tasks
            if task_id:
                self._send_output_images(task_id, reply_params, notify_recipe, runner)

            return {"status": "ok"}

        except Exception as e:
            logger.exception("Failed to send reply for channel %s", channel)
            return {"status": "error", "error": str(e)}

    _IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

    def _send_output_images(
        self,
        task_id: str,
        reply_params: dict[str, Any],
        notify_recipe: str,
        runner: Any,
    ) -> None:
        """Send image files from task outputs dir after text reply."""
        view = _board_task_to_view(get_board(), task_id)
        if not view:
            return
        run_id = view.session_id
        if not run_id:
            return
        outputs_dir = PROJECTS_DIR / run_id / "outputs"
        if not outputs_dir.is_dir():
            return

        chat_id = reply_params.get("chat_id") or reply_params.get("reply_context", {}).get("chat_id")
        if not chat_id:
            return

        # Dedup: skip images already auto-sent for this run, and skip the image
        # explicitly declared in this reply (feishu_send_message handles that).
        sent = self._sent_image_paths.setdefault(run_id, set())
        explicit = reply_params.get("image_path")
        if explicit:
            sent.add(str(explicit))

        # Only broadcast images produced (or modified) after this task started,
        # so we don't re-send historical PNGs left in a shared outputs/ dir by
        # prior tasks in the same Run (root cause: dup_image_root_cause.md R1+R2).
        task = get_board().get_task(task_id)
        task_start_ts = (
            task.created_at.timestamp() if task and task.created_at else 0
        )
        images = [
            f for f in sorted(outputs_dir.iterdir())
            if f.is_file()
            and f.suffix.lower() in self._IMAGE_SUFFIXES
            and str(f) not in sent
            and f.stat().st_mtime >= task_start_ts
        ]
        for img in images:
            try:
                image_params = {"chat_id": chat_id, "image_path": str(img)}
                logger.info("Auto-sending output image via %s: %s", notify_recipe, img.name)
                runner.run(notify_recipe, params=image_params)
                sent.add(str(img))
                logger.info("Output image sent: %s", img.name)
            except Exception:
                logger.exception("Failed to send output image: %s", img.name)

    def recover_pending_tasks(self) -> list[dict[str, Any]]:
        """Scan the board for non-terminal msgs/tasks needing PA attention.

        Returns a list of message payloads (user_message / recovered_failed_task)
        for the caller to enqueue. Does NOT enqueue itself.
        """
        board = get_board()
        view = board.view_for_pa()

        # Collect task ids whose board view indicates non-terminal work.
        non_terminal_task_statuses = {"queued", "executing", "resume_failed"}
        failed_task_ids: list[str] = []
        pending_task_ids: list[str] = []
        for t in view.get("threads", []):
            for m in t.get("msgs", []):
                for tk in m.get("tasks", []):
                    if tk.get("status") in non_terminal_task_statuses:
                        pending_task_ids.append(tk["id"])
                    elif tk.get("status") == "failed":
                        # Allow PA to retry a small number of failed tasks per
                        # restart (matches legacy behaviour). Whether to retry
                        # is decided after MAX_RECOVERY check below.
                        failed_task_ids.append(tk["id"])

        MAX_RECOVERY = 2

        messages: list[dict[str, Any]] = []
        for tid in pending_task_ids:
            view_tk = _board_task_to_view(board, tid)
            if view_tk is None:
                continue
            if view_tk.recovery_count >= MAX_RECOVERY:
                logger.warning(
                    "Task %s recovered %d times without completion — marking stale",
                    tid[:8], view_tk.recovery_count,
                )
                board.mark_task_failed(
                    tid,
                    error=f"stale: recovered {view_tk.recovery_count} times without resolution",
                    by="lifecycle",
                )
                continue
            board.increment_recovery_count(tid, by="lifecycle")
            from datetime import datetime

            task_obj = board.get_task(tid)
            received_at = (
                task_obj.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if task_obj and task_obj.created_at else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            messages.append({
                "type": "user_message",
                "task_id": tid,
                "channel": view_tk.channel,
                "channel_message_id": view_tk.channel_message_id,
                "prompt": view_tk.prompt,
                "reply_context": view_tk.reply_context,
                "_recovered": True,
                "received_at": received_at,
            })

        for tid in failed_task_ids:
            view_tk = _board_task_to_view(board, tid)
            if view_tk is None:
                continue
            # Safety: cap FAILED recovery (without this, a task that keeps
            # dying mid-run oscillates failed ↔ pending forever).
            if view_tk.recovery_count >= MAX_RECOVERY:
                logger.warning(
                    "FAILED task %s already recovered %d times — leaving as failed (stale)",
                    tid[:8], view_tk.recovery_count,
                )
                continue
            board.increment_recovery_count(tid, by="lifecycle")
            messages.append({
                "type": "recovered_failed_task",
                "task_id": tid,
                "channel": view_tk.channel,
                "channel_message_id": view_tk.channel_message_id,
                "original_prompt": view_tk.prompt,
                "original_error": view_tk.error or "unknown",
                "reply_context": view_tk.reply_context,
            })

        return messages

    def get_task(self, task_id: str) -> TaskView | None:
        """Look up a task by id (exact match against board)."""
        return _board_task_to_view(get_board(), task_id)

    def find_task_for_run(self, run_id: str) -> TaskView | None:
        """Find the TaskView associated with a run_id."""
        board = get_board()
        for task in board.get_executing_tasks():
            if task.session and task.session.run_id == run_id:
                return _board_task_to_view(board, task.task_id)
        return None
