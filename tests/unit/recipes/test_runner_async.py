"""Tests for RecipeRunner.run_async() and _run_with_execution()."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from frago.recipes.execution import ExecutionStatus
from frago.recipes.runner import RecipeRunner


@pytest.fixture
def runner(tmp_path):
    """Create a RecipeRunner with mock registry and tmp store."""
    mock_registry = MagicMock()
    runner = RecipeRunner(registry=mock_registry, project_root=tmp_path)
    runner.store = MagicMock()
    return runner


@pytest.fixture
def mock_recipe():
    """Create a mock recipe object."""
    recipe = MagicMock()
    recipe.metadata.name = "test_recipe"
    recipe.metadata.runtime = "python"
    recipe.metadata.env = {}
    recipe.metadata.system_packages = False
    recipe.script_path = "/fake/script.py"
    return recipe


@pytest.fixture(autouse=True)
def clean_executor():
    """Ensure background executor is shut down after each test."""
    yield
    from frago.recipes.background import shutdown_executor
    shutdown_executor(wait=True)


class TestRunWithExecution:
    def test_success_flow(self, runner, mock_recipe):
        """Should transition to RUNNING, execute, and complete as SUCCEEDED."""
        runner.store.transition = MagicMock()
        runner.store.complete = MagicMock()

        with patch.object(runner, "_run_python", return_value={"data": {"ok": True}, "stderr": ""}):
            result = runner._run_with_execution(
                execution_id="exec_test",
                name="test_recipe",
                recipe=mock_recipe,
                params={},
                resolved_env={},
            )

        assert result["success"] is True
        assert result["execution_id"] == "exec_test"
        assert result["data"] == {"ok": True}

        runner.store.transition.assert_called_once_with("exec_test", ExecutionStatus.RUNNING)
        runner.store.complete.assert_called_once()
        call_kwargs = runner.store.complete.call_args
        assert call_kwargs[1]["status"] == ExecutionStatus.SUCCEEDED

    def test_failure_flow(self, runner, mock_recipe):
        """Should complete as FAILED on RecipeExecutionError."""
        from frago.recipes.exceptions import RecipeExecutionError

        runner.store.transition = MagicMock()
        runner.store.complete = MagicMock()

        with patch.object(
            runner, "_run_python",
            side_effect=RecipeExecutionError(
                recipe_name="test_recipe", runtime="python", exit_code=1, stderr="boom"
            ),
        ), pytest.raises(RecipeExecutionError):
            runner._run_with_execution(
                    execution_id="exec_fail",
                    name="test_recipe",
                    recipe=mock_recipe,
                    params={},
                    resolved_env={},
                )

        runner.store.complete.assert_called_once()
        call_kwargs = runner.store.complete.call_args
        assert call_kwargs[1]["status"] == ExecutionStatus.FAILED


class TestRunAsync:
    def test_returns_execution_id(self, runner, mock_recipe):
        """Should return execution_id immediately without blocking."""
        mock_execution = MagicMock()
        mock_execution.id = "exec_async_123"

        runner.registry.find.return_value = mock_recipe
        runner.env_loader.resolve_for_recipe = MagicMock(return_value={})
        runner.store.create.return_value = mock_execution

        with patch.object(runner, "_run_with_execution"):
            execution_id = runner.run_async("test_recipe", params={"key": "val"})

        assert execution_id == "exec_async_123"
        runner.registry.find.assert_called_once()
        runner.store.create.assert_called_once()

    def test_executes_in_background(self, runner, mock_recipe):
        """Should execute _run_with_execution in a background thread."""
        mock_execution = MagicMock()
        mock_execution.id = "exec_bg"
        completed = threading.Event()

        runner.registry.find.return_value = mock_recipe
        runner.env_loader.resolve_for_recipe = MagicMock(return_value={})
        runner.store.create.return_value = mock_execution

        def mock_run_with_execution(**_kwargs):
            completed.set()
            return {"success": True, "data": None, "execution_id": "exec_bg"}

        with patch.object(runner, "_run_with_execution", side_effect=mock_run_with_execution):
            execution_id = runner.run_async("test_recipe")

        assert execution_id == "exec_bg"
        # Wait for background execution to complete
        assert completed.wait(timeout=5), "Background execution did not complete"

    def test_fail_fast_on_invalid_recipe(self, runner):
        """Should raise immediately if recipe not found (not in background)."""
        from frago.recipes.exceptions import RecipeNotFoundError

        runner.registry.find.side_effect = RecipeNotFoundError("bad_recipe")

        with pytest.raises(RecipeNotFoundError):
            runner.run_async("bad_recipe")

    def test_fail_fast_on_invalid_params(self, runner, mock_recipe):
        """Should raise immediately on validation error."""
        from frago.recipes.exceptions import RecipeValidationError

        runner.registry.find.return_value = mock_recipe

        with patch.object(
            runner, "_validate_params",
            side_effect=RecipeValidationError("test", ["missing required param"]),
        ), pytest.raises(RecipeValidationError):
            runner.run_async("test_recipe", params={"bad": "params"})

    def test_background_exception_logged(self, runner, mock_recipe):
        """Background execution errors should be logged, not propagated."""
        mock_execution = MagicMock()
        mock_execution.id = "exec_err"
        completed = threading.Event()

        runner.registry.find.return_value = mock_recipe
        runner.env_loader.resolve_for_recipe = MagicMock(return_value={})
        runner.store.create.return_value = mock_execution

        def mock_run_with_execution(**_kwargs):
            completed.set()
            raise RuntimeError("background boom")

        with patch.object(runner, "_run_with_execution", side_effect=mock_run_with_execution):
            execution_id = runner.run_async("test_recipe")

        assert execution_id == "exec_err"
        assert completed.wait(timeout=5)
        # Give logger time to fire
        time.sleep(0.1)

    def test_pre_registers_execution(self, runner, mock_recipe):
        """Execution should be created before background submission."""
        mock_execution = MagicMock()
        mock_execution.id = "exec_pre"

        runner.registry.find.return_value = mock_recipe
        runner.env_loader.resolve_for_recipe = MagicMock(return_value={})
        runner.store.create.return_value = mock_execution

        with patch.object(runner, "_run_with_execution"):
            runner.run_async("test_recipe", timeout=600)

        runner.store.create.assert_called_once_with(
            recipe_name="test_recipe",
            params={},
            source=None,
            timeout_seconds=600,
        )
