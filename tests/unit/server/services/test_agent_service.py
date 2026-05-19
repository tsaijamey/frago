"""Tests for frago.server.services.agent_service module.

Tests agent task execution.
"""
from pathlib import Path
from unittest.mock import patch

from frago.server.services.agent_service import AgentService


class TestAgentServiceStartTask:
    """Test AgentService.start_task() method."""

    def test_rejects_empty_prompt(self):
        """Should return error for empty prompt."""
        result = AgentService.start_task("")
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()

    def test_rejects_whitespace_prompt(self):
        """Should return error for whitespace-only prompt."""
        result = AgentService.start_task("   ")
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()

    def test_returns_error_when_frago_not_found(self):
        """Should return error when frago command not in PATH."""
        with (
            patch("shutil.which", return_value=None),
            patch(
                "frago.server.services.agent_service.run_subprocess_background",
                side_effect=FileNotFoundError("frago not found"),
            ),
        ):
            result = AgentService.start_task("test prompt")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_starts_task_successfully(self, tmp_path, monkeypatch):
        """Should start task and return success."""
        # Set up home directory for logs
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ) as mock_bg,
        ):
            result = AgentService.start_task("Test task prompt")

        assert result["status"] == "ok"
        assert "id" in result
        assert result["title"] == "Test task prompt"
        assert result["agent_type"] == "claude"
        mock_bg.assert_called_once()

    def test_long_prompts_used_as_title(self, tmp_path, monkeypatch):
        """Long prompts are used as-is for title (no truncation)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        long_prompt = "x" * 100

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ),
        ):
            result = AgentService.start_task(long_prompt)

        assert result["status"] == "ok"
        assert result["title"] == long_prompt

    def test_includes_project_path_when_provided(self, tmp_path, monkeypatch):
        """Should include project_path in result when provided."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ),
        ):
            result = AgentService.start_task(
                "Test prompt", project_path="/home/user/project"
            )

        assert result["status"] == "ok"
        assert result["project_path"] == "/home/user/project"

    def test_creates_prompt_file(self, tmp_path, monkeypatch):
        """Should create prompt file with task content."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ),
        ):
            result = AgentService.start_task("My test prompt")

        assert result["status"] == "ok"
        # Check prompt file was created
        log_dir = tmp_path / ".frago" / "logs"
        prompt_files = list(log_dir.glob("prompt-*.txt"))
        assert len(prompt_files) == 1
        assert prompt_files[0].read_text() == "My test prompt"

    def test_handles_file_not_found_error(self, tmp_path, monkeypatch):
        """Should handle FileNotFoundError gracefully."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background",
                side_effect=FileNotFoundError,
            ),
        ):
            result = AgentService.start_task("Test prompt")

        assert result["status"] == "error"
        assert "not found" in result["error"]


class TestStartTaskCwd:
    """Test that start_task passes correct cwd."""

    def test_passes_project_path_as_cwd(self, tmp_path, monkeypatch):
        """Should pass project_path as cwd to subprocess."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ) as mock_bg,
        ):
            AgentService.start_task("Test prompt", project_path="/home/user/project")

        assert mock_bg.call_args[1]["cwd"] == "/home/user/project"

    def test_falls_back_to_home_when_no_project_path(self, tmp_path, monkeypatch):
        """Should use Path.home() as cwd when project_path is None."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ) as mock_bg,
        ):
            AgentService.start_task("Test prompt")

        assert mock_bg.call_args[1]["cwd"] == str(tmp_path)

    def test_no_project_flag_in_cmd(self, tmp_path, monkeypatch):
        """Should not pass --project flag (removed dead code)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with (
            patch("shutil.which", return_value="/usr/bin/frago"),
            patch(
                "frago.server.services.agent_service.run_subprocess_background"
            ) as mock_bg,
        ):
            AgentService.start_task("Test prompt", project_path="/some/path")

        cmd = mock_bg.call_args[0][0]
        assert "--project" not in cmd


class TestStreamEndOfTurnGating:
    """Bug 2026-05-20: DeepSeek (non-Anthropic backend in passthrough mode)
    sometimes emits message_delta(stop_reason=end_turn) right after a
    thinking block without producing any text yet, then keeps streaming the
    real text 60–90s later. The old stream reader terminated on the early
    end_turn signal and killed the subprocess mid-output. Regression: only
    honor end_turn termination after we've seen a text content_block.
    """

    def _make_session(self):
        from frago.server.services.agent_service import AgentSession
        sess = AgentSession.__new__(AgentSession)
        sess.internal_id = "test1234abcd"
        sess._claude_session_id = None
        sess._current_assistant_message = ""
        sess._current_tool_input_json = ""
        sess._pending_tool_calls = {}
        sess._on_assistant_message = None
        sess._saw_text_block_in_message = False
        sess._process = None
        return sess

    async def _handle(self, sess, event):
        # Bypass broadcast manager and process handle requirements during dispatch.
        from unittest.mock import patch
        with patch("frago.server.services.agent_service.manager") as mgr:
            async def _noop(*a, **kw):
                return None
            mgr.broadcast = _noop
            await sess._handle_stream_event(event)

    def test_end_turn_after_thinking_only_does_not_terminate(self):
        """Early end_turn without preceding text → must not call terminate."""
        import asyncio
        from unittest.mock import MagicMock

        sess = self._make_session()
        sess._process = MagicMock()
        sess._process.poll = MagicMock(return_value=None)

        async def run():
            await self._handle(sess, {"type": "message_start"})
            await self._handle(sess, {
                "type": "content_block_start",
                "content_block": {"type": "thinking"},
            })
            await self._handle(sess, {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "考虑中..."},
            })
            await self._handle(sess, {
                "type": "content_block_stop",
            })
            # Early end_turn (the failure mode)
            await self._handle(sess, {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
            })

        asyncio.run(run())
        sess._process.terminate.assert_not_called()
        assert sess._saw_text_block_in_message is False

    def test_end_turn_after_text_block_does_terminate(self):
        """end_turn AFTER a text block → terminate as before (fast path)."""
        import asyncio
        from unittest.mock import MagicMock

        sess = self._make_session()
        sess._process = MagicMock()
        sess._process.poll = MagicMock(return_value=None)

        async def run():
            await self._handle(sess, {"type": "message_start"})
            await self._handle(sess, {
                "type": "content_block_start",
                "content_block": {"type": "text"},
            })
            await self._handle(sess, {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
            })

        asyncio.run(run())
        sess._process.terminate.assert_called_once()
        assert sess._saw_text_block_in_message is True

    def test_message_start_resets_text_flag(self):
        """After a message that had text, the next message must start fresh —
        an early end_turn in message 2 (after only thinking) must not inherit
        message 1's text flag and falsely terminate.
        """
        import asyncio
        from unittest.mock import MagicMock

        sess = self._make_session()
        sess._process = MagicMock()
        sess._process.poll = MagicMock(return_value=None)

        async def run():
            # Message 1: text + end_turn (terminates, but we'll keep mocking
            # to observe message 2 behavior)
            await self._handle(sess, {"type": "message_start"})
            await self._handle(sess, {
                "type": "content_block_start",
                "content_block": {"type": "text"},
            })
            # (do not actually fire end_turn — simulate message rolling on)
            # Message 2 starts; flag must reset
            await self._handle(sess, {"type": "message_start"})
            assert sess._saw_text_block_in_message is False
            # Now thinking only + early end_turn in message 2
            await self._handle(sess, {
                "type": "content_block_start",
                "content_block": {"type": "thinking"},
            })
            await self._handle(sess, {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
            })

        asyncio.run(run())
        sess._process.terminate.assert_not_called()

    def test_tool_use_stop_reason_never_terminates(self):
        """Pre-existing behavior: stop_reason=tool_use means more turns coming.
        Must not terminate regardless of text flag.
        """
        import asyncio
        from unittest.mock import MagicMock

        sess = self._make_session()
        sess._process = MagicMock()
        sess._process.poll = MagicMock(return_value=None)

        async def run():
            await self._handle(sess, {"type": "message_start"})
            await self._handle(sess, {
                "type": "content_block_start",
                "content_block": {"type": "text"},
            })
            await self._handle(sess, {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
            })

        asyncio.run(run())
        sess._process.terminate.assert_not_called()
