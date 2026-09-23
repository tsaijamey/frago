"""Tests for RecipeRunner.run_async() and _run_with_execution()."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from frago.recipes import isolation
from frago.recipes.execution import ExecutionStatus
from frago.recipes.runner import RecipeRunner


@pytest.fixture
def runner(tmp_path, monkeypatch):
    """Create a RecipeRunner with mock registry and tmp store.

    家目录指到临时目录：跑一次配方会在 ``~/.frago/recipe-data/<配方>/`` 下登记放行
    （grants.json），不改的话测试会去写真人的那份。
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
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

        # 失败时运行器会去翻内核的拒绝记录，在 macOS 上要二十多秒；这一条不测那个。
        with patch.object(
            runner, "_run_python",
            side_effect=RecipeExecutionError(
                recipe_name="test_recipe", runtime="python", exit_code=1, stderr="boom"
            ),
        ), patch("frago.recipes.isolation.explain_refusals", return_value=""), \
                pytest.raises(RecipeExecutionError):
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


class TestAFailureIsToldWhatIsolationRefused:
    """Paths a library builds at run time are invisible to validate, and the
    library usually swallows the refusal. A failed run carries the refusals in
    its error and in its execution record."""

    def _fail(self, runner, mock_recipe, execution_id="exec_refused"):
        from frago.recipes.exceptions import RecipeExecutionError

        runner.store.transition = MagicMock()
        runner.store.complete = MagicMock()
        with patch.object(
            runner, "_run_python",
            side_effect=RecipeExecutionError(
                recipe_name="test_recipe", runtime=mock_recipe.metadata.runtime,
                exit_code=1, stderr="boom"),
        ), pytest.raises(RecipeExecutionError) as err:
            runner._run_with_execution(
                execution_id=execution_id, name="test_recipe", recipe=mock_recipe,
                params={}, resolved_env={},
            )
        return err.value

    def test_the_refusals_reach_the_error_and_the_record(self, runner, mock_recipe):
        note = "隔离拦下了这次运行的 1 处文件访问：\n  - python 新建 /Users/x/Library/Caches/y"
        with patch("frago.recipes.isolation.explain_refusals", return_value=note) as ask:
            err = self._fail(runner, mock_recipe)
        ask.assert_called_once()
        assert ask.call_args[0][0] == isolation.marker_for("exec_refused")
        assert "boom" in str(err) and "Library/Caches/y" in str(err)
        recorded = runner.store.complete.call_args[1]["error"]["message"]
        assert "Library/Caches/y" in recorded

    def test_nothing_refused_leaves_the_error_as_it_was(self, runner, mock_recipe):
        with patch("frago.recipes.isolation.explain_refusals", return_value=""):
            err = self._fail(runner, mock_recipe)
        assert str(err) == "Recipe 'test_recipe' execution failed (exit code: 1): boom"

    def test_a_runtime_outside_any_view_is_not_asked(self, runner, mock_recipe):
        """chrome-js runs in a browser, not in a view: there is nothing to read."""
        from frago.recipes.exceptions import RecipeExecutionError

        mock_recipe.metadata.runtime = "chrome-js"
        runner.store.transition = MagicMock()
        runner.store.complete = MagicMock()
        with patch("frago.recipes.isolation.explain_refusals") as ask, patch.object(
            runner, "_run_chrome_js",
            side_effect=RecipeExecutionError(
                recipe_name="test_recipe", runtime="chrome-js", exit_code=1, stderr="x"),
        ), pytest.raises(RecipeExecutionError):
            runner._run_with_execution(
                execution_id="exec_js", name="test_recipe", recipe=mock_recipe,
                params={}, resolved_env={},
            )
        ask.assert_not_called()


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
