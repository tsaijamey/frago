"""Ingestion scheduler — polls channels, ingests messages into TaskBoard.

Channels are config declarations (a pair of poll + notify recipes), not code components.
Adding a new channel requires zero code changes — just config + recipes.

The scheduler's job is:
1. Poll channels via recipes
2. Classify each new message into a thread (L1/L2 via thread_classifier)
3. Ingest into TaskBoard via ``Ingestor.ingest_external`` (single source of truth)
4. Enqueue the message to the PA message queue for immediate processing

Phase 1 part B-2a (root-cause fix): the legacy per-channel disk dedup file is
removed. TaskBoard's append_msg dedup (same msg_id → duplicate_msg_ingest
timeline entry, no second task) is now the only dedup gate.

Phase finish (post-#74): the in-memory ``_message_cache`` shim is also removed
along with ``cache_message`` / ``get_cached_message`` / ``remove_cached_message``.
Callers that previously read the shim now read board.view_for_pa directly
(msg.reply_context, msg.channel are exposed there).
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from frago.compat import get_windows_subprocess_kwargs
from frago.server.services.taskboard.legacy_store import TaskStore

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """A channel declaration from config.json."""

    name: str
    poll_recipe: str
    notify_recipe: str
    poll_interval_seconds: int = 120
    poll_timeout_seconds: int = 20
    # "poll" → periodic recipe invocation returning a message batch (default).
    # "stream" → spawn poll_recipe as a long-lived subprocess; each stdout line
    # is one `{"type": "message", ...}` event fed straight into ingest_message.
    mode: str = "poll"


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
        # Shared runner — avoids recreating RecipeRegistry + ExecutionStore per poll
        from frago.recipes.runner import RecipeRunner
        self._runner = RecipeRunner()

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
            if ch.mode == "stream":
                task = asyncio.create_task(
                    self._stream_loop(ch),
                    name=f"ingestion-stream-{ch.name}",
                )
            else:
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
        """Call poll_recipe, parse return value, ingest each message, deliver to PA."""
        result = await asyncio.to_thread(
            self._runner.run, ch.poll_recipe,
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

        new_count = 0
        for msg in messages:
            if await self.ingest_message(ch, msg):
                new_count += 1

        if new_count:
            logger.info("Poll %s: %d new message(s) ingested into TaskBoard", ch.poll_recipe, new_count)

    async def ingest_message(self, ch: ChannelConfig, msg: dict[str, Any]) -> bool:
        """Classify + ingest a single message via TaskBoard.

        Shared by poll mode (_poll_channel) and stream mode (_stream_loop).
        Returns True if the message was newly ingested, False if skipped
        (malformed payload or store-level dedup hit).

        Dedup is TaskBoard's responsibility: ``board.append_msg`` of the same
        msg_id writes a ``duplicate_msg_ingest`` timeline entry instead of
        creating a second Msg. The legacy ``_seen_messages`` / persisted cache
        defenses are removed; TaskStore.exists (archive check) is the only
        secondary gate — it stops messages that were archived in a prior
        rotation from being re-ingested.
        """
        msg_id = str(msg.get("id", ""))
        if not msg_id or "prompt" not in msg:
            logger.warning("Channel %s: message missing required fields, skipping", ch.name)
            return False

        if self._store.exists(ch.name, msg_id):
            logger.debug("Channel %s: message %s exists in store/archive, skipping", ch.name, msg_id)
            return False

        from frago.server.services.taskboard import get_board
        from frago.server.services.taskboard.ingestor import Ingestor
        from frago.server.services.thread_classifier import (
            classify as thread_classify,
        )
        from frago.server.services.thread_classifier import (
            ensure_thread,
        )
        from frago.server.services.trace import trace_entry

        reply_ctx = msg.get("reply_context") or {}
        sender = reply_ctx.get("sender_id") or reply_ctx.get("sender") or ""
        classify_result = thread_classify(
            channel=ch.name,
            sender=sender,
            content=msg["prompt"],
            reply_context=reply_ctx,
        )
        ensure_thread(
            classify_result,
            channel=ch.name,
            sender=sender,
            msg_id=msg_id,
            root_summary=msg["prompt"][:80],
        )

        # B-2a single source: write to TaskBoard via Ingestor. Dedup happens
        # inside board.append_msg (same msg_id → duplicate_msg_ingest entry).
        board = get_board()
        # Ensure board.Thread exists (classifier wrote ThreadStore index but
        # board is a separate object graph). create_thread is idempotent-by-
        # caller-checking: we silently swallow IllegalTransitionError if a
        # previous ingest already created it on this side.
        import contextlib as _contextlib

        from frago.server.services.taskboard.models import IllegalTransitionError
        with _contextlib.suppress(IllegalTransitionError):
            board.create_thread(
                thread_id=classify_result.thread_id,
                origin="external",
                subkind=ch.name,
                root_summary=msg["prompt"][:80],
                by="IngestionScheduler",
            )

        ingestor = Ingestor(board)
        ingestor.ingest_external(
            channel=ch.name,
            msg_id=msg_id,
            sender_id=sender,
            text=msg["prompt"],
            parent_ref=classify_result.parent_ref,
            received_at=datetime.now(),
            reply_context=reply_ctx,
            thread_id=classify_result.thread_id,
        )

        trace_entry(
            origin="external",
            subkind=ch.name,
            data_type="message",
            thread_id=classify_result.thread_id,
            parent_id=None,
            task_id=None,
            data={
                "event_type": "pa_ingestion",
                "channel": ch.name,
                "prompt": msg["prompt"],
                "_classify_layer": classify_result.layer,
            },
            msg_id=msg_id,
            role="scheduler",
            event=f"收到 {ch.name} 消息: {msg['prompt'][:80]}",
        )

        if self._pa_enqueue:
            try:
                await self._pa_enqueue({
                    "type": "user_message",
                    "msg_id": msg_id,
                    "channel": ch.name,
                    "channel_message_id": msg_id,
                    "prompt": msg["prompt"],
                    "reply_context": msg.get("reply_context", {}),
                    "thread_id": classify_result.thread_id,
                    "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                logger.info(
                    "Message %s enqueued to PA (thread=%s, layer=%s)",
                    msg_id, classify_result.thread_id, classify_result.layer,
                )
            except Exception:
                logger.exception("Failed to enqueue message %s to PA", msg_id)
        return True

    # -- stream mode (long-connection recipes) --

    async def _stream_loop(self, ch: ChannelConfig) -> None:
        """Keep `poll_recipe` alive as a streaming subprocess.

        Each stdout line from the recipe must be a JSON object
        `{"type": "message", "id", "prompt", "reply_context"}`; lines with
        other `type` values are ignored (reserved for future control events).

        The recipe subprocess is expected to never exit voluntarily. If it
        does (crash, network error, flag day), we restart with exponential
        backoff capped at `max_backoff` seconds.
        """
        backoff = 2
        max_backoff = 60
        await asyncio.sleep(5)  # startup delay, match poll mode
        while not self._stop_event.is_set():
            proc = None
            try:
                proc = await self._spawn_stream_recipe(ch)
                logger.info(
                    "Stream channel %s: recipe %s started (pid=%s)",
                    ch.name, ch.poll_recipe, proc.pid,
                )
                backoff = 2  # successful spawn resets backoff
                await self._read_stream(ch, proc)
                logger.warning(
                    "Stream channel %s: recipe %s exited (code=%s)",
                    ch.name, ch.poll_recipe, proc.returncode,
                )
            except Exception:
                logger.exception("Stream channel %s: spawn/read failed", ch.name)
            finally:
                if proc is not None and proc.returncode is None:
                    try:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except (TimeoutError, ProcessLookupError):
                        try:
                            proc.kill()
                            await proc.wait()
                        except ProcessLookupError:
                            pass

            # Backoff before restart (interruptible by stop_event)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                break  # stop_event set → exit loop
            except TimeoutError:
                backoff = min(backoff * 2, max_backoff)

    async def _spawn_stream_recipe(self, ch: ChannelConfig) -> asyncio.subprocess.Process:
        """Spawn a stream-mode recipe as a persistent subprocess via `uv run`.

        Reuses RecipeRunner internals for recipe discovery + secret resolution
        so FRAGO_SECRETS injection and PEP 723 inline deps work identically to
        normal `frago recipe run` invocations.
        """
        runner = self._runner
        recipe = runner.registry.find(ch.poll_recipe)

        env = os.environ.copy()
        # Force UTF-8 for child stdio so non-ASCII stderr/stdout (Chinese,
        # emoji, etc.) survives the pipe on Windows, where the default
        # locale codec (cp936) would otherwise corrupt bytes into U+FFFD
        # and blow up the parent's logger when it writes to server.log.
        env["PYTHONIOENCODING"] = "utf-8"
        if recipe.metadata.secrets:
            secrets = runner._resolve_secrets(ch.poll_recipe, recipe.metadata.secrets)
            env["FRAGO_SECRETS"] = json.dumps(secrets)
        if getattr(recipe.metadata, "no_proxy", False):
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                      "http_proxy", "https_proxy", "all_proxy"):
                env.pop(k, None)

        uv_bin = shutil.which("uv") or "uv"
        params_json = json.dumps({"notify_recipe": ch.notify_recipe})
        cmd = [uv_bin, "run", "--quiet", str(recipe.script_path), params_json]

        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            **get_windows_subprocess_kwargs(),
        )

    async def _read_stream(
        self, ch: ChannelConfig, proc: asyncio.subprocess.Process
    ) -> None:
        """Read recipe stdout/stderr until it exits or stop_event fires."""

        async def pump_stderr() -> None:
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                logger.info(
                    "[stream:%s] %s",
                    ch.name,
                    line.decode(errors="replace").rstrip(),
                )

        stderr_task = asyncio.create_task(pump_stderr())
        try:
            assert proc.stdout is not None
            while not self._stop_event.is_set():
                line_task = asyncio.create_task(proc.stdout.readline())
                stop_task = asyncio.create_task(self._stop_event.wait())
                done, pending = await asyncio.wait(
                    {line_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if stop_task in done:
                    return
                line = line_task.result()
                if not line:
                    return  # EOF → subprocess exited
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    logger.warning(
                        "Stream %s: non-JSON stdout line: %s",
                        ch.name, line[:200],
                    )
                    continue
                if msg.get("type") != "message":
                    logger.debug(
                        "Stream %s: ignoring non-message event type=%s",
                        ch.name, msg.get("type"),
                    )
                    continue
                try:
                    await self.ingest_message(ch, msg)
                except Exception:
                    logger.exception(
                        "Stream %s: ingest_message failed for %s",
                        ch.name, msg.get("id"),
                    )
        finally:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stderr_task

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

    async def _notify(self, task: object, ch: ChannelConfig) -> None:
        """Call notify_recipe with contract-defined params."""
        try:
            params = {
                "status": task.status.value,
                "reply_context": task.reply_context,
            }
            if task.result_summary is not None:
                params["result_summary"] = task.result_summary
            if task.error is not None:
                params["error"] = task.error
            await asyncio.to_thread(
                self._runner.run,
                ch.notify_recipe,
                params=params,
            )
            logger.info("Notified task result: %s via %s", task.id[:8], ch.name)
        except Exception:
            logger.exception("Failed to notify task: %s", task.id[:8])
