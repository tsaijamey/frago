"""Tests for frago.server.services.base module.

Tests cross-platform subprocess utilities.
"""
import platform
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.base import (
    get_claude_command,
    get_gh_command,
    get_utf8_env,
    resolve_command_path,
    run_subprocess,
    run_subprocess_background,
)


class TestGetClaudeCommand:
    """Test get_claude_command() function."""

    def test_returns_simple_command_on_non_windows(self):
        """Should return ['claude'] on non-Windows platforms."""
        with patch("platform.system", return_value="Linux"):
            result = get_claude_command()
        assert result == ["claude"]

    def test_returns_simple_command_when_claude_not_found(self):
        """Should return ['claude'] when claude not in PATH on Windows."""
        with (
            patch("platform.system", return_value="Windows"),
            patch("shutil.which", return_value=None),
        ):
            result = get_claude_command()
        assert result == ["claude"]

    def test_returns_simple_command_for_non_cmd_file(self):
        """Should return ['claude'] if claude is not a .cmd file."""
        with (
            patch("platform.system", return_value="Windows"),
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            result = get_claude_command()
        assert result == ["claude"]


class TestGetGhCommand:
    """Test get_gh_command() function."""

    def test_returns_simple_command_on_non_windows(self):
        """Should return ['gh'] on non-Windows platforms."""
        with patch("platform.system", return_value="Linux"):
            result = get_gh_command()
        assert result == ["gh"]

    def test_returns_simple_command_when_gh_not_found(self):
        """Should return ['gh'] when gh not in PATH on Windows."""
        with (
            patch("platform.system", return_value="Windows"),
            patch("shutil.which", return_value=None),
        ):
            result = get_gh_command()
        assert result == ["gh"]


class TestGetUtf8Env:
    """Test get_utf8_env() function."""

    def test_includes_pythonioencoding(self):
        """Should include PYTHONIOENCODING=utf-8."""
        env = get_utf8_env()
        assert env["PYTHONIOENCODING"] == "utf-8"

    def test_includes_pythonutf8(self):
        """Should include PYTHONUTF8=1."""
        env = get_utf8_env()
        assert env["PYTHONUTF8"] == "1"

    def test_preserves_existing_env(self):
        """Should preserve existing environment variables."""
        with patch.dict("os.environ", {"MY_VAR": "my_value"}):
            env = get_utf8_env()
        assert env.get("MY_VAR") == "my_value"


class TestResolveCommandPath:
    """Test resolve_command_path() function."""

    def test_empty_command_returns_empty(self):
        """Should return empty list for empty input."""
        result = resolve_command_path([])
        assert result == []

    def test_resolves_found_command(self):
        """Should resolve command to full path when found."""
        with patch("shutil.which", return_value="/usr/bin/ls"):
            result = resolve_command_path(["ls", "-la"])
        assert result == ["/usr/bin/ls", "-la"]

    def test_returns_original_when_not_found(self):
        """Should return original command when not in PATH."""
        with patch("shutil.which", return_value=None):
            result = resolve_command_path(["nonexistent", "arg"])
        assert result == ["nonexistent", "arg"]


class TestRunSubprocess:
    """Test run_subprocess() function."""

    def test_basic_execution(self):
        """Should execute command and return result."""
        # Use a simple cross-platform command
        result = run_subprocess(["echo", "hello"], timeout=5)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_captures_stderr(self):
        """Should capture stderr output."""
        # Try to list a non-existent directory
        result = run_subprocess(["ls", "/nonexistent_dir_12345"], timeout=5)
        # Should have non-zero return code and stderr output
        assert result.returncode != 0

    def test_timeout_handling(self):
        """Should raise TimeoutExpired on timeout."""
        with pytest.raises(subprocess.TimeoutExpired):
            run_subprocess(["sleep", "10"], timeout=1)

    def test_custom_cwd(self, tmp_path):
        """Should execute in specified working directory."""
        result = run_subprocess(["pwd"], cwd=str(tmp_path), timeout=5)
        assert str(tmp_path) in result.stdout


class TestRunSubprocessBackground:
    """Test run_subprocess_background() function."""

    def test_starts_process(self):
        """Should start process and return Popen."""
        proc = run_subprocess_background(["sleep", "0.1"])
        assert isinstance(proc, subprocess.Popen)
        # Wait for completion
        proc.wait()
        assert proc.returncode == 0

    def test_runs_without_blocking(self):
        """Should return immediately without blocking."""
        import time

        start = time.time()
        proc = run_subprocess_background(["sleep", "1"])
        elapsed = time.time() - start

        # Should return quickly (within 0.5 seconds)
        assert elapsed < 0.5

        # Cleanup
        proc.terminate()
        proc.wait()

    def test_custom_stdout(self, tmp_path):
        """Should redirect stdout to file when specified."""
        log_file = tmp_path / "output.log"
        with open(log_file, "w") as f:
            proc = run_subprocess_background(["echo", "test output"], stdout=f)
            proc.wait()

        content = log_file.read_text()
        assert "test output" in content
