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
