"""Tests for RecipeSupervisor — the generic recipe daemon supervision core.

These exercise the spawn / backoff-restart / teardown loop and the
restart_policy semantics without a real recipe, by stubbing the spawn to return
a controllable fake subprocess.
"""

import asyncio

import pytest

from frago.server.services.recipe_supervisor import (
    LogSink,
    RecipeSupervisor,
    SupervisedRecipe,
)


class _FakeStream:
    """Minimal asyncio StreamReader stand-in: yields queued lines then EOF."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""  # EOF


class _FakeProc:
    """Controllable subprocess stand-in for RecipeSupervisor._spawn."""

    def __init__(self, returncode: int = 0, stdout_lines: list[bytes] | None = None) -> None:
        self.returncode = returncode
        self.pid = 4242
        self.stdout = _FakeStream(stdout_lines or [])
        self.stderr = _FakeStream([])
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = self.returncode if self.returncode is not None else -15

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def _supervisor(spec: SupervisedRecipe, procs: list[_FakeProc], stop_event=None):
    """Build a supervisor whose _spawn pops from a scripted list of fake procs."""
    sup = RecipeSupervisor(spec, LogSink(spec.label), runner=object(), stop_event=stop_event)
    spawn_calls: list[int] = []

    async def fake_spawn():
        spawn_calls.append(1)
        if not procs:
            # Out of scripted procs: hand back a clean exiter so the loop keeps
            # turning until stop_event ends it (used by the "always" case).
            return _FakeProc(returncode=0)
        return procs.pop(0)

    sup._spawn = fake_spawn  # type: ignore[method-assign]
    sup._spawn_calls = spawn_calls  # type: ignore[attr-defined]
    return sup


@pytest.mark.asyncio
async def test_on_failure_restarts_after_nonzero_exit():
    """on-failure: a crash (returncode != 0) triggers a backoff restart."""
    spec = SupervisedRecipe(
        recipe="x", restart_policy="on-failure",
        initial_backoff=0, max_backoff=0, startup_delay=0,
    )
    procs = [_FakeProc(returncode=1), _FakeProc(returncode=0)]
    sup = _supervisor(spec, procs)

    await asyncio.wait_for(sup.run(), timeout=2)
    # First proc crashed → restart; second exited cleanly → stop. 2 spawns.
    assert len(sup._spawn_calls) == 2


@pytest.mark.asyncio
async def test_on_failure_stops_after_clean_exit():
    """on-failure: a clean exit (0) on the first run means no restart."""
    spec = SupervisedRecipe(
        recipe="x", restart_policy="on-failure",
        initial_backoff=0, max_backoff=0, startup_delay=0,
    )
    procs = [_FakeProc(returncode=0), _FakeProc(returncode=0)]
    sup = _supervisor(spec, procs)

    await asyncio.wait_for(sup.run(), timeout=2)
    assert len(sup._spawn_calls) == 1


@pytest.mark.asyncio
async def test_never_does_not_restart():
    """never: even a crash does not restart."""
    spec = SupervisedRecipe(
        recipe="x", restart_policy="never",
        initial_backoff=0, max_backoff=0, startup_delay=0,
    )
    procs = [_FakeProc(returncode=1), _FakeProc(returncode=0)]
    sup = _supervisor(spec, procs)

    await asyncio.wait_for(sup.run(), timeout=2)
    assert len(sup._spawn_calls) == 1


@pytest.mark.asyncio
async def test_always_restarts_even_on_clean_exit():
    """always: a clean exit still triggers a restart; stop_event ends the loop."""
    spec = SupervisedRecipe(
        recipe="x", restart_policy="always",
        initial_backoff=0, max_backoff=0, startup_delay=0,
    )
    stop_event = asyncio.Event()
    procs = [_FakeProc(returncode=0), _FakeProc(returncode=0)]
    sup = _supervisor(spec, procs, stop_event=stop_event)

    async def stopper():
        # Let two clean exits restart, then end the loop.
        while len(sup._spawn_calls) < 2:
            await asyncio.sleep(0.01)
        stop_event.set()

    await asyncio.gather(
        asyncio.wait_for(sup.run(), timeout=2),
        stopper(),
    )
    assert len(sup._spawn_calls) >= 2


@pytest.mark.asyncio
async def test_stdout_lines_routed_to_sink():
    """Each stdout line is handed to the sink while the process is alive."""
    spec = SupervisedRecipe(
        recipe="x", restart_policy="never",
        initial_backoff=0, max_backoff=0, startup_delay=0,
    )
    received: list[bytes] = []

    class _CaptureSink:
        async def on_stdout_line(self, line: bytes) -> None:
            received.append(line)

        async def on_stderr_line(self, line: bytes) -> None:
            pass

    sup = RecipeSupervisor(spec, _CaptureSink(), runner=object(), stop_event=asyncio.Event())
    proc = _FakeProc(returncode=0, stdout_lines=[b'{"type":"message"}\n', b"plain\n"])

    async def fake_spawn():
        return proc

    sup._spawn = fake_spawn  # type: ignore[method-assign]
    await asyncio.wait_for(sup.run(), timeout=2)
    assert received == [b'{"type":"message"}\n', b"plain\n"]


@pytest.mark.asyncio
async def test_stop_event_terminates_running_proc():
    """stop_event set during pump → loop exits and the live proc is terminated."""
    spec = SupervisedRecipe(
        recipe="x", restart_policy="always",
        initial_backoff=0, max_backoff=0, startup_delay=0,
    )
    stop_event = asyncio.Event()

    # A proc that never yields stdout (readline blocks) so pump waits on stop_event.
    class _BlockingStream:
        async def readline(self) -> bytes:
            await asyncio.sleep(3600)
            return b""

    proc = _FakeProc(returncode=None)
    proc.stdout = _BlockingStream()
    proc.stderr = _FakeStream([])

    sup = RecipeSupervisor(spec, LogSink("x"), runner=object(), stop_event=stop_event)

    async def fake_spawn():
        return proc

    sup._spawn = fake_spawn  # type: ignore[method-assign]

    async def stopper():
        await asyncio.sleep(0.05)
        stop_event.set()

    await asyncio.gather(asyncio.wait_for(sup.run(), timeout=2), stopper())
    assert proc.terminated is True


def test_should_restart_matrix():
    """_should_restart truth table across policies and exit codes."""
    def sup(policy):
        return RecipeSupervisor(
            SupervisedRecipe(recipe="x", restart_policy=policy),
            LogSink("x"), runner=object(), stop_event=asyncio.Event(),
        )

    assert sup("always")._should_restart(0) is True
    assert sup("always")._should_restart(1) is True
    assert sup("never")._should_restart(0) is False
    assert sup("never")._should_restart(1) is False
    assert sup("on-failure")._should_restart(0) is False
    assert sup("on-failure")._should_restart(1) is True
    assert sup("on-failure")._should_restart(None) is True  # spawn failure → restart
