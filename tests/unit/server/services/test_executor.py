"""Tests for Executor._read_final_assistant_text and _notify_pa session_id fix."""

import json
import os
import sys
import time
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from frago.server.services.executor import Executor


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _make_jsonl_path(home: Path, session_id: str) -> Path:
    cwd_slug = str(home).replace("/", "-")
    return home / ".claude" / "projects" / cwd_slug / f"{session_id}.jsonl"


def _assistant(text: str | None, stop_reason: str | None = "end_turn",
               extra_blocks: list | None = None) -> dict:
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if extra_blocks:
        content.extend(extra_blocks)
    return {
        "type": "assistant",
        "message": {"stop_reason": stop_reason, "content": content},
    }


class TestReadFinalAssistantText:
    def test_returns_none_when_jsonl_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        assert Executor._read_final_assistant_text("nonexistent-sid") is None

    def test_single_msg_no_separator(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-1"
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant("only answer"),
        ])
        assert Executor._read_final_assistant_text(sid) == "only answer"

    def test_collects_last_5_in_chronological_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-2"
        labels = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant(label, stop_reason="tool_use" if i < 5 else "end_turn")
            for i, label in enumerate(labels)
        ])
        result = Executor._read_final_assistant_text(sid, max_turns=5)
        assert result is not None
        # last 5 = bravo..foxtrot in chronological order, alpha dropped
        assert "alpha" not in result  # oldest dropped
        for label in labels[1:]:
            assert label in result
        # separators present for multi-msg
        assert "--- msg 1/5 ---" in result
        assert "--- msg 5/5 ---" in result
        # chronological: bravo appears before foxtrot
        assert result.index("bravo") < result.index("foxtrot")

    def test_skips_tool_use_only_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-3"
        tool_only = {
            "type": "assistant",
            "message": {
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": "tu1", "name": "Bash", "input": {}}],
            },
        }
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant("text 1"),
            tool_only,
            tool_only,
            _assistant("text 2"),
        ])
        result = Executor._read_final_assistant_text(sid, max_turns=5)
        assert result is not None
        assert "text 1" in result
        assert "text 2" in result
        # tool_use records contribute nothing, so just 2 msgs
        assert "--- msg 1/2 ---" in result
        assert "--- msg 2/2 ---" in result

    def test_mixed_content_only_text_extracted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-4"
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            _assistant("narration", extra_blocks=[
                {"type": "tool_use", "id": "t1", "name": "X", "input": {}},
                {"type": "thinking", "thinking": "private thoughts"},
            ]),
        ])
        result = Executor._read_final_assistant_text(sid)
        assert result == "narration"
        assert "private thoughts" not in result
        assert "tool_use" not in result

    def test_returns_none_when_no_text_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-5"
        _write_jsonl(_make_jsonl_path(tmp_path, sid), [
            {
                "type": "assistant",
                "message": {
                    "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": "t1", "name": "X", "input": {}}],
                },
            },
        ])
        assert Executor._read_final_assistant_text(sid) is None

    def test_malformed_json_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)
        sid = "sess-6"
        path = _make_jsonl_path(tmp_path, sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json\n", encoding="utf-8")
        assert Executor._read_final_assistant_text(sid) is None


class TestNotifyPASessionId:
    @pytest.mark.asyncio
    async def test_uses_updated_session_id(self, tmp_path, monkeypatch):
        """_notify_pa MUST read session_id from the live board task,
        not from the input context (which was a snapshot before launch)."""
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)

        enqueued: list[dict] = []

        async def fake_enqueue(msg):
            enqueued.append(msg)

        from frago.server.services.executor import _TaskContext

        board = MagicMock()
        # fresh task on board, post-launch with bound session
        fresh_task = MagicMock()
        fresh_task.session.run_id = "run-20260418-abc"
        fresh_task.session.started_at = None
        result_obj = MagicMock()
        result_obj.summary = "hello world"
        result_obj.error = None
        fresh_task.result = result_obj
        board.get_task.return_value = fresh_task

        ctx = _TaskContext(
            task_id="task-123",
            prompt="p", description="d",
            channel="feishu",
            channel_message_id="om_xxx",
            thread_id=None,
            reply_context={},
            created_at=None,
        )

        executor = Executor(
            board=board,
            pa_enqueue_message=fake_enqueue,
            broadcast_pa_event=AsyncMock(),
        )

        await executor._notify_pa(ctx, run_id="run-20260418-abc", stop_reason="end_turn")

        assert len(enqueued) == 1
        assert enqueued[0]["session_id"] == "run-20260418-abc"
        assert enqueued[0]["result_summary"] == "hello world"
        assert enqueued[0]["type"] == "agent_completed"

    @pytest.mark.asyncio
    async def test_falls_back_when_board_task_missing(self, tmp_path, monkeypatch):
        """If board.get_task returns None we still notify with a synthesized summary."""
        monkeypatch.setattr("frago.server.services.executor.Path.home", lambda: tmp_path)

        enqueued: list[dict] = []

        async def fake_enqueue(msg):
            enqueued.append(msg)

        from frago.server.services.executor import _TaskContext

        board = MagicMock()
        board.get_task.return_value = None

        ctx = _TaskContext(
            task_id="task-xyz",
            prompt="p", description="d",
            channel="feishu",
            channel_message_id="om_yyy",
            thread_id=None,
            reply_context={},
            created_at=None,
        )

        executor = Executor(
            board=board,
            pa_enqueue_message=fake_enqueue,
            broadcast_pa_event=AsyncMock(),
        )

        await executor._notify_pa(ctx, run_id="run-x", stop_reason="end_turn")

        assert len(enqueued) == 1
        # session_id is None when board.get_task returned None
        assert enqueued[0]["session_id"] is None
        # synthesized fallback summary uses stop_reason
        assert "end_turn" in enqueued[0]["result_summary"]


class TestMonitorUntilDoneWindowsOSError:
    """Bug 2026-05-20: Windows raises OSError(WinError 6, "invalid handle")
    when os.kill(pid, 0) is called on an already-exited process — not
    ProcessLookupError as on POSIX. The monitor loop's except clause only
    caught ProcessLookupError/PermissionError, so the OSError propagated
    out of _safe_execute_run and the task was marked failed even though
    the agent completed normally. Regression: OSError must be caught and
    treated as "process is gone".
    """

    @pytest.mark.asyncio
    async def test_oserror_from_os_kill_treated_as_exited(
        self, tmp_path, monkeypatch,
    ):
        import os

        from frago.server.services.executor import Executor

        # Simulate Windows behavior: os.kill(pid, 0) raises OSError(WinError 6)
        call_count = {"n": 0}

        def _fake_kill(_pid, sig):
            call_count["n"] += 1
            if sig == 0:
                # Equivalent of Windows WinError 6
                raise OSError(6, "invalid handle")
            return None

        monkeypatch.setattr(os, "kill", _fake_kill)
        monkeypatch.setattr(
            "frago.server.services.executor.Path.home", lambda: tmp_path,
        )

        board = MagicMock()
        board.get_task.return_value = None
        executor = Executor(board=board)

        ctx = MagicMock()
        ctx.task_id = "t1"
        ctx.thread_id = "th1"
        ctx.channel_message_id = None

        # _monitor_until_done must return cleanly when os.kill raises OSError,
        # not propagate to _safe_execute_run.
        result = await executor._monitor_until_done(ctx, pid=99999)
        assert result == 99999
        assert call_count["n"] >= 1


class TestFinalizeRunDatetimeAwareness:
    """Bug 2026-05-20 Test 6: board.append_task stores task.created_at as
    datetime.now().astimezone() (tz-aware), but _finalize_run computed
    duration as `datetime.now() - ctx.created_at` (naive minus aware) →
    TypeError on every successful run. The executor crashed before
    _notify_pa fired, so PA never got agent_completed and the user was
    stuck on the interim "稍等一下" reply even though the sub-agent had
    finished its investigation.
    """

    @pytest.mark.asyncio
    async def test_aware_created_at_does_not_raise(self, tmp_path, monkeypatch):
        """ctx.created_at as tz-aware datetime must not break duration calc."""
        from datetime import datetime

        from frago.server.services.executor import Executor, _TaskContext

        monkeypatch.setattr(
            "frago.server.services.executor.Path.home", lambda: tmp_path,
        )

        # Aware created_at matching what board.append_task produces
        aware_created = datetime.now(UTC).astimezone()

        ctx = _TaskContext(
            task_id="t1",
            prompt="x",
            description="x",
            channel="feishu",
            channel_message_id="om_x",
            thread_id="th1",
            reply_context={},
            created_at=aware_created,
        )

        board = MagicMock()
        board.get_task.return_value = None
        # Avoid touching real disk for sub-agent JSONL
        executor = Executor(
            board=board,
            pa_enqueue_message=AsyncMock(),
            broadcast_pa_event=AsyncMock(),
        )

        # Force _monitor_until_done to be a no-op for this test
        async def _no_wait(_ctx, _pid):
            return _pid
        monkeypatch.setattr(executor, "_monitor_until_done", _no_wait)
        monkeypatch.setattr(
            executor, "_read_stop_reason", lambda _sid: "end_turn",
        )
        monkeypatch.setattr(
            executor, "_read_final_assistant_text", lambda _sid: "done",
        )
        # Stub TabGroupManager + RunManager cleanup paths
        monkeypatch.setattr(executor, "_get_or_create_run_for_thread",
                            AsyncMock(return_value="run-x"))

        # _finalize_run is the path that crashed. It used to do
        #   datetime.now() - ctx.created_at
        # which raises TypeError when sides differ in tz-awareness.
        # Just running it without raising is the regression assertion.
        await executor._finalize_run(ctx, pid=99999, run_id="run-x")


@pytest.mark.skipif(sys.platform == "win32", reason="waitpid/fork are POSIX-only")
class TestPidExited:
    """Executor._pid_exited must report an exited child as gone AND reap it,
    so an unreaped zombie can't keep os.kill(pid,0) succeeding forever — the
    silent ~9-min monitor hang observed 2026-05-21 00:00."""

    def test_running_process_not_exited(self):
        import subprocess
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            assert Executor._pid_exited(p.pid) is False
        finally:
            p.kill()
            p.wait()

    def test_exited_zombie_detected_and_reaped(self):
        # fork a child that exits immediately → becomes a zombie until reaped.
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        exited = False
        for _ in range(100):
            if Executor._pid_exited(pid):  # waitpid(WNOHANG) reaps the zombie
                exited = True
                break
            time.sleep(0.02)
        assert exited, "exited child (zombie) must be detected as exited"
        # already reaped → still reports exited, never re-hangs
        assert Executor._pid_exited(pid) is True


class TestClaudeJsonlPathSlugRobust:
    """Bug 2026-05-21 (Windows host Aliciiiiiia): the claude JSONL path was
    rebuilt as home.replace('/', '-'), wrong on Windows where the project-dir
    slug also maps '\\' and the drive ':' (cwd 'C:\\Users\\choka' → dir
    'C--Users-choka'). The file was never found, so _read_stop_reason always
    returned None and every task was wrongly FAILED. Fix globs by the globally
    unique session id instead of recomputing the slug.
    """

    def test_finds_jsonl_under_windows_style_slug(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "frago.server.services.executor.Path.home", lambda: tmp_path,
        )
        csid = "40caeadb-d2b4-492a-b9e8-e6b6e72dcf34"
        # A slug that home.replace('/', '-') could never produce on this host.
        proj = tmp_path / ".claude" / "projects" / "C--Users-choka"
        proj.mkdir(parents=True)
        (proj / f"{csid}.jsonl").write_text(
            json.dumps({"type": "assistant",
                        "message": {"stop_reason": "end_turn"}}) + "\n",
            encoding="utf-8",
        )
        found = Executor._claude_jsonl_path(csid)
        assert found is not None and found.name == f"{csid}.jsonl"
        assert Executor._read_stop_reason(csid) == "end_turn"

    def test_missing_session_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "frago.server.services.executor.Path.home", lambda: tmp_path,
        )
        (tmp_path / ".claude" / "projects").mkdir(parents=True)
        assert Executor._claude_jsonl_path("does-not-exist") is None
        assert Executor._read_stop_reason("does-not-exist") is None


class TestMonitorUntilDoneWindowsPidStub:
    """Bug 2026-05-21 (Windows host Aliciiiiiia): the launched pid is a
    console-script stub that exits within ms while the real claude worker runs
    detached. _pid_exited fired 'process_exit' on the first poll → monitoring
    ended before a terminal stop_reason → stop_reason=None → task wrongly FAILED
    ~3ms after launch. On Windows the pid-exit signal must be ignored;
    completion comes from the claude JSONL stop_reason.
    """

    @pytest.mark.asyncio
    async def test_windows_ignores_early_pid_exit_waits_for_stop_reason(
        self, tmp_path, monkeypatch,
    ):
        from frago.server.services import executor as exec_mod

        monkeypatch.setattr(exec_mod, "PID_POLL_INTERVAL", 0.01)
        monkeypatch.setattr(os, "name", "nt")  # simulate Windows
        monkeypatch.setattr(
            "frago.server.services.executor.Path.home", lambda: tmp_path,
        )

        # Real JSONL on disk so _jsonl_mtime != None (launch-grace won't fire).
        csid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        proj = tmp_path / ".claude" / "projects" / "C--Users-x"
        proj.mkdir(parents=True)
        (proj / f"{csid}.jsonl").write_text("{}\n", encoding="utf-8")

        task_obj = MagicMock()
        task_obj.session.claude_session_id = csid
        board = MagicMock()
        board.get_task.return_value = task_obj
        executor = Executor(board=board)

        # Windows stub: pid always looks exited. With the bug this ends monitoring
        # immediately; with the fix the Windows path never consults it.
        monkeypatch.setattr(Executor, "_pid_exited", staticmethod(lambda _pid: True))

        # stop_reason: None for the first two polls, then end_turn.
        calls = {"n": 0}

        def _sr(_sid):
            calls["n"] += 1
            return "end_turn" if calls["n"] >= 3 else None

        monkeypatch.setattr(Executor, "_read_stop_reason", staticmethod(_sr))

        ctx = MagicMock()
        ctx.task_id = "t1"
        ctx.thread_id = "th1"
        ctx.channel_message_id = None

        result = await executor._monitor_until_done(ctx, pid=4440)
        assert result == 4440
        # Proves it did NOT bail on the early pid-exit — it kept polling
        # stop_reason until end_turn.
        assert calls["n"] >= 3
