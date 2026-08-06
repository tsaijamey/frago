"""Tests for what start_daemon reports when the daemon never comes up.

A spawn that returns a pid is not a server. Windows Smart App Control refusing
the interpreter is one way to get a pid for a process that dies on the spot;
an import error at startup is another. Either way the caller used to be told
"started (PID: n)", with a PID file written to back it up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.server import daemon


class FakeProc:
    """A spawned child that reports whether it is still alive."""

    def __init__(self, pid: int = 4242, exit_code: int | None = None) -> None:
        self.pid = pid
        self._exit_code = exit_code

    def poll(self) -> int | None:
        return self._exit_code


@pytest.fixture
def spawnable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Get start_daemon as far as the spawn, with the environment neutralised."""
    # Gate 2 refuses to spawn from the checkout venv, which is exactly where the
    # suite runs; the gate has its own tests.
    monkeypatch.setattr(
        "frago.server.launch_guard.assert_system_install", lambda: None
    )
    pid_file = tmp_path / "server.pid"
    monkeypatch.setattr(daemon, "get_pid_file", lambda: pid_file)
    monkeypatch.setattr(daemon, "get_log_file", lambda: tmp_path / "server.log")
    monkeypatch.setattr(daemon, "_is_systemd_managed", lambda: False)
    monkeypatch.setattr(daemon, "cleanup_stale_pid", lambda: False)
    monkeypatch.setattr(daemon, "is_server_running", lambda: (False, None))
    monkeypatch.setattr(daemon, "check_port_available", lambda: (True, None))
    monkeypatch.setattr(daemon, "get_accessible_urls", lambda: ["http://127.0.0.1:8093"])

    def spawn(proc: FakeProc) -> None:
        monkeypatch.setattr(daemon.subprocess, "Popen", lambda *_a, **_k: proc)

    return spawn, pid_file


class TestStartDaemonReporting:
    def test_dead_child_is_reported_as_failure(
        self, spawnable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn, pid_file = spawnable
        spawn(FakeProc(exit_code=1))
        monkeypatch.setattr(
            daemon, "_wait_for_healthy", lambda **_k: (False, "process exited with code 1")
        )

        success, message = daemon.start_daemon()

        assert success is False
        assert "never answered" in message
        assert "code 1" in message

    def test_no_pid_file_is_left_behind_on_failure(
        self, spawnable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale PID file would make the next status check report a live server."""
        spawn, pid_file = spawnable
        spawn(FakeProc(exit_code=1))
        monkeypatch.setattr(daemon, "_wait_for_healthy", lambda **_k: (False, "gone"))

        daemon.start_daemon()

        assert not pid_file.exists()

    def test_healthy_child_reports_success(
        self, spawnable, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn, pid_file = spawnable
        spawn(FakeProc(pid=4242))
        monkeypatch.setattr(daemon, "_wait_for_healthy", lambda **_k: (True, "port=8093"))

        success, message = daemon.start_daemon()

        assert success is True
        assert "4242" in message
        assert pid_file.read_text() == "4242"


@pytest.fixture
def nothing_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the health probe fail without touching the network.

    Left real, these tests would reach whatever is on port 8093 — including the
    developer's own running frago — and invert depending on it.
    """

    def refuse(*_a: object, **_k: object) -> None:
        raise ConnectionRefusedError("nothing listening")

    monkeypatch.setattr(daemon.http.client, "HTTPConnection", refuse)


@pytest.mark.usefixtures("nothing_listening")
class TestWaitForHealthy:
    def test_exiting_child_ends_the_wait_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise a dead process burns the whole timeout before reporting."""
        slept: list[float] = []
        monkeypatch.setattr(daemon.time, "sleep", slept.append)

        ok, detail = daemon._wait_for_healthy(timeout=30, proc=FakeProc(exit_code=3))

        assert ok is False
        assert "exited with code 3" in detail
        assert slept == []  # gave up before the first sleep

    def test_a_live_child_keeps_the_wait_going(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Still starting up is not a failure — only exiting is."""
        monkeypatch.setattr(daemon.time, "sleep", lambda _s: None)
        clock = iter([0.0, 0.0, 1.0, 2.0, 99.0])
        monkeypatch.setattr(daemon.time, "time", lambda: next(clock))

        ok, detail = daemon._wait_for_healthy(timeout=30, proc=FakeProc(exit_code=None))

        assert ok is False
        assert "timeout after 30s" in detail

    def test_without_a_proc_it_waits_out_the_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The systemd path has no child to watch and must keep its old behaviour."""
        monkeypatch.setattr(daemon.time, "sleep", lambda _s: None)
        clock = iter([0.0, 0.0, 1.0, 2.0, 99.0])
        monkeypatch.setattr(daemon.time, "time", lambda: next(clock))

        ok, detail = daemon._wait_for_healthy(timeout=30)

        assert ok is False
        assert "timeout after 30s" in detail
