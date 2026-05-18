"""Tests for RecipeRunner cancel functionality and Popen-based process tracking."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from frago.recipes.execution import ExecutionStatus
from frago.recipes.runner import RecipeRunner, _active_processes, _process_lock


@pytest.fixture
def runner(tmp_path):
    """Create a RecipeRunner with a mock registry and tmp store."""
    mock_registry = MagicMock()
    runner = RecipeRunner(registry=mock_registry, project_root=tmp_path)
    runner.store = MagicMock()
    return runner


class TestRunSubprocess:
    def test_tracks_process_during_execution(self, runner):
        """Process should be in _active_processes while running."""
        seen_in_registry = []

        def check_registry(*_args, **_kwargs):
            with _process_lock:
                seen_in_registry.append("exec_test" in _active_processes)
            return (b'hello\n', b'')

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate = check_registry
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            result = runner._run_subprocess("exec_test", ["echo", "hello"], {})

        assert seen_in_registry == [True]
        assert result.returncode == 0
        assert result.stdout == "hello\n"
        # Process should be removed after completion
        with _process_lock:
            assert "exec_test" not in _active_processes

    def test_removes_process_on_timeout(self, runner):
        """Process should be cleaned up from registry on timeout."""
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.communicate = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 5))
            mock_proc.kill = MagicMock()
            # After kill, communicate should succeed
            mock_proc.communicate.side_effect = [
                subprocess.TimeoutExpired("cmd", 5),
                (b'', b''),
            ]
            mock_popen.return_value = mock_proc

            with pytest.raises(subprocess.TimeoutExpired):
                runner._run_subprocess("exec_timeout", ["sleep", "100"], {}, timeout=5)

        with _process_lock:
            assert "exec_timeout" not in _active_processes
        mock_proc.kill.assert_called_once()


class TestCancel:
    def test_cancel_running_process(self, runner):
        """Should terminate a tracked process and mark execution as CANCELLED."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_proc.wait.return_value = 0

        with _process_lock:
            _active_processes["exec_cancel"] = mock_proc

        result = runner.cancel("exec_cancel")

        assert result is True
        mock_proc.terminate.assert_called_once()
        runner.store.complete.assert_called_once_with(
            "exec_cancel",
            status=ExecutionStatus.CANCELLED,
            error={"code": "CANCELLED", "message": "Execution cancelled by user"},
            exit_code=-15,
        )

        # Cleanup
        _active_processes.pop("exec_cancel", None)

    def test_cancel_already_finished(self, runner):
        """Should return False for already finished process."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # already exited

        with _process_lock:
            _active_processes["exec_done"] = mock_proc

        result = runner.cancel("exec_done")

        assert result is False
        mock_proc.terminate.assert_not_called()
        runner.store.complete.assert_not_called()

        # Cleanup
        _active_processes.pop("exec_done", None)

    def test_cancel_nonexistent(self, runner):
        """Should return False for unknown execution ID."""
        result = runner.cancel("exec_nonexistent")
        assert result is False

    def test_cancel_force_kill_on_timeout(self, runner):
        """Should kill process if terminate doesn't work within timeout."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("cmd", 5),  # terminate didn't work
            0,  # kill worked
        ]

        with _process_lock:
            _active_processes["exec_stubborn"] = mock_proc

        result = runner.cancel("exec_stubborn")

        assert result is True
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        runner.store.complete.assert_called_once()

        # Cleanup
        _active_processes.pop("exec_stubborn", None)

    def test_cancel_cross_instance(self, tmp_path):
        """Cancel from a different RecipeRunner instance should work."""
        mock_registry = MagicMock()
        RecipeRunner(registry=mock_registry, project_root=tmp_path)  # runner1 starts process
        runner2 = RecipeRunner(registry=mock_registry, project_root=tmp_path)
        runner2.store = MagicMock()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0

        # Runner1 "starts" a process
        with _process_lock:
            _active_processes["exec_cross"] = mock_proc

        # Runner2 cancels it
        result = runner2.cancel("exec_cross")
        assert result is True
        mock_proc.terminate.assert_called_once()

        # Cleanup
        _active_processes.pop("exec_cross", None)
