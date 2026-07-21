"""Generic recipe daemon supervisor.

Keeps a single recipe alive as a long-lived subprocess, restarting it with
exponential backoff when it exits, and tearing it down on a shared stop event.

This is the supervision core extracted from
``ingestion/scheduler.py`` (``_stream_loop`` / ``_spawn_stream_recipe`` /
``_read_stream``), with the channel / message-ingestion coupling removed. What
to do with the subprocess's output is delegated to a ``ProcessSink``:

- ``LogSink`` (default) writes stdout/stderr into the server log.
- The ingestion scheduler supplies its own sink that parses each stdout line as
  a ``{"type": "message", ...}`` event and feeds it into ``ingest_message`` — so
  channel ``stream`` mode becomes one consumer of this supervisor rather than a
  second, parallel implementation.

Spawn behaviour (recipe discovery, FRAGO_SECRETS injection, ``no_proxy`` env
stripping, ``PYTHONIOENCODING=utf-8``, Windows subprocess kwargs) is identical
to the old ``_spawn_stream_recipe`` so ``uv run`` semantics match a normal
``frago recipe run`` invocation.
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import sys
from dataclasses import dataclass
from typing import Literal, Protocol

from frago.compat import get_windows_subprocess_kwargs

logger = logging.getLogger(__name__)

RestartPolicy = Literal["always", "on-failure", "never"]


@dataclass
class SupervisedRecipe:
    """A daemon declaration: one recipe kept alive as a subprocess."""

    recipe: str
    params: dict | None = None
    restart_policy: RestartPolicy = "on-failure"
    max_backoff: int = 60
    initial_backoff: int = 2
    # Startup delay before the first spawn (and not re-applied on restarts).
    # Defaults to 5s to match the original channel stream startup delay.
    startup_delay: float = 5.0
    # Human-facing label for logs; defaults to the recipe name.
    name: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.recipe


class ProcessSink(Protocol):
    """Decides what to do with a live subprocess's output lines."""

    async def on_stdout_line(self, line: bytes) -> None: ...

    async def on_stderr_line(self, line: bytes) -> None: ...


class LogSink:
    """Default sink: write subprocess output into the server log."""

    def __init__(self, label: str) -> None:
        self._label = label

    async def on_stdout_line(self, line: bytes) -> None:
        logger.info("[daemon:%s] %s", self._label, line.decode(errors="replace").rstrip())

    async def on_stderr_line(self, line: bytes) -> None:
        logger.info("[daemon:%s] %s", self._label, line.decode(errors="replace").rstrip())


class RecipeSupervisor:
    """Keep one recipe alive as a subprocess, restarting on exit with backoff."""

    def __init__(
        self,
        spec: SupervisedRecipe,
        sink: ProcessSink | None = None,
        *,
        runner: object | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self._spec = spec
        self._sink = sink or LogSink(spec.label)
        if runner is None:
            from frago.recipes.runner import RecipeRunner
            runner = RecipeRunner()
        self._runner = runner
        self._stop_event = stop_event or asyncio.Event()
        # Live subprocess handle + restart count for observability (status()).
        self._proc: asyncio.subprocess.Process | None = None
        self._restarts = 0

    async def run(self) -> None:
        """Supervise the recipe until the stop event fires.

        Loop: spawn → pump output until exit → decide (per restart_policy)
        whether to restart → backoff (interruptible by stop_event) → repeat.
        """
        backoff = self._spec.initial_backoff
        label = self._spec.label
        await asyncio.sleep(self._spec.startup_delay)
        while not self._stop_event.is_set():
            proc = None
            try:
                proc = await self._spawn()
                self._proc = proc
                logger.info(
                    "Daemon %s: recipe %s started (pid=%s)",
                    label, self._spec.recipe, proc.pid,
                )
                backoff = self._spec.initial_backoff  # successful spawn resets backoff
                await self._pump(proc)
                logger.warning(
                    "Daemon %s: recipe %s exited (code=%s)",
                    label, self._spec.recipe, proc.returncode,
                )
            except Exception:
                logger.exception("Daemon %s: spawn/read failed", label)
            finally:
                await self._terminate(proc)

            if self._stop_event.is_set():
                break

            returncode = proc.returncode if proc is not None else None
            if not self._should_restart(returncode):
                logger.info(
                    "Daemon %s: restart_policy=%s, exit code=%s — not restarting",
                    label, self._spec.restart_policy, returncode,
                )
                break

            # Backoff before restart (interruptible by stop_event)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                break  # stop_event set → exit loop
            except TimeoutError:
                backoff = min(backoff * 2, self._spec.max_backoff)
                self._restarts += 1  # backoff elapsed → about to respawn

    def _should_restart(self, returncode: int | None) -> bool:
        policy = self._spec.restart_policy
        if policy == "never":
            return False
        if policy == "always":
            return True
        # on-failure: restart unless the process exited cleanly (code 0).
        # A spawn failure (returncode None) counts as a failure → restart.
        return returncode != 0

    async def _spawn(self) -> asyncio.subprocess.Process:
        """Spawn the recipe as a subprocess via ``uv run``.

        Reuses RecipeRunner internals for recipe discovery + secret resolution
        so FRAGO_SECRETS injection and PEP 723 inline deps work identically to
        normal ``frago recipe run`` invocations.
        """
        runner = self._runner
        recipe = runner.registry.find(self._spec.recipe)

        env = os.environ.copy()
        # Force UTF-8 for child stdio so non-ASCII stderr/stdout (Chinese,
        # emoji, etc.) survives the pipe on Windows, where the default locale
        # codec (cp936) would otherwise corrupt bytes into U+FFFD and blow up
        # the parent's logger when it writes to server.log.
        env["PYTHONIOENCODING"] = "utf-8"
        if recipe.metadata.secrets:
            secrets = runner._resolve_secrets(self._spec.recipe, recipe.metadata.secrets)
            env["FRAGO_SECRETS"] = json.dumps(secrets)
        if getattr(recipe.metadata, "no_proxy", False):
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                      "http_proxy", "https_proxy", "all_proxy"):
                env.pop(k, None)

        uv_bin = shutil.which("uv") or "uv"
        params_json = json.dumps(self._spec.params or {})
        cmd = [uv_bin, "run", "--quiet", str(recipe.script_path), params_json]

        # POSIX: 起独立进程组（session），让 _terminate 能对整组发信号。
        # 直接子进程是 ``uv run``，真正的配方 python 是它的孙进程；只 terminate/kill
        # uv 会把孙进程遗留成孤儿（实测 voice_desktop_hud 窗口在 server 重启后残留）。
        kwargs: dict = get_windows_subprocess_kwargs()
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            **kwargs,
        )

    async def _pump(self, proc: asyncio.subprocess.Process) -> None:
        """Read subprocess stdout/stderr until it exits or stop_event fires.

        Each line is handed to the sink; the supervisor itself stays agnostic
        about whether the line becomes a message, a log entry, or is dropped.
        """

        async def pump_stderr() -> None:
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                await self._sink.on_stderr_line(line)

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
                await self._sink.on_stdout_line(line)
        finally:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stderr_task

    async def _terminate(self, proc: asyncio.subprocess.Process | None) -> None:
        """Terminate a still-running subprocess: terminate → wait(5s) → kill.

        On POSIX the signal goes to the whole process group (the child is
        spawned with ``start_new_session=True``), so grandchildren spawned by
        ``uv run`` die with it instead of being orphaned.
        """
        if proc is None or proc.returncode is not None:
            return
        try:
            self._signal_tree(proc, signal.SIGTERM)
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (TimeoutError, ProcessLookupError):
            try:
                self._signal_tree(proc, signal.SIGKILL if sys.platform != "win32" else None)
                await proc.wait()
            except ProcessLookupError:
                pass

    @staticmethod
    def _signal_tree(proc: asyncio.subprocess.Process, sig: "signal.Signals | None") -> None:
        """Send ``sig`` to the child's process group (POSIX) or terminate/kill it.

        Falls back to per-process terminate/kill when the group is gone or on
        Windows (where ``sig=None`` means kill).
        """
        if sys.platform != "win32" and sig is not None:
            try:
                os.killpg(proc.pid, sig)  # start_new_session → pgid == pid
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass  # 组已不存在/异常，退回单进程信号
        if sig is signal.SIGTERM:
            proc.terminate()
        else:
            proc.kill()
