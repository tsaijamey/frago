"""Recipe executor"""
import json
import logging
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .env_loader import EnvLoader, WorkflowContext
from .exceptions import RecipeExecutionError, RecipeValidationError
from .execution import ExecutionStatus
from .execution_store import ExecutionStore
from .metadata import validate_params
from .registry import RecipeRegistry

logger = logging.getLogger(__name__)

# Module-level process registry shared across all RecipeRunner instances.
# Enables cancel() from any runner instance (e.g., a different request handler).
_active_processes: dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()


class RecipeRunner:
    """Recipe runner, responsible for executing Recipes"""

    def __init__(
        self,
        registry: Optional[RecipeRegistry] = None,
        project_root: Optional[Path] = None
    ):
        """
        Initialize RecipeRunner

        Args:
            registry: Recipe registry (auto-created and scanned if not provided)
            project_root: Project root directory (used to load project-level .env)
        """
        if registry is None:
            registry = RecipeRegistry()
            registry.scan()

        self.registry = registry
        self.env_loader = EnvLoader(project_root=project_root)
        self.store = ExecutionStore()

    def run(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        output_target: str = 'stdout',
        output_options: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None,
        source: str | None = None,
        timeout: int | None = None,
        step_index: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute the specified Recipe

        Args:
            name: Recipe name
            params: Input parameters (JSON dictionary)
            output_target: Output target ('stdout' | 'file' | 'clipboard')
            output_options: Output options (e.g., 'path' required for file)
            env_overrides: Environment variable overrides provided by CLI --env parameter
            workflow_context: Workflow execution context (for sharing environment variables across Recipes)
            source: Specify recipe source ('project' | 'user' | 'example'), selects by priority when None

        Returns:
            Execution result dictionary in format:
            {
                "success": bool,
                "data": dict | None,
                "error": dict | None,
                "execution_time": float,
                "recipe_name": str,
                "runtime": str
            }

        Raises:
            RecipeNotFoundError: Recipe does not exist
            RecipeValidationError: Parameter validation failed
            RecipeExecutionError: Execution failed
        """
        params = params or {}
        output_options = output_options or {}

        # Find Recipe (supports specified source)
        recipe = self.registry.find(name, source=source)

        # Validate parameters
        self._validate_params(recipe.metadata, params)

        # Resolve environment variables
        try:
            resolved_env = self.env_loader.resolve_for_recipe(
                env_definitions=recipe.metadata.env,
                cli_overrides=env_overrides,
                workflow_context=workflow_context
            )
        except ValueError as e:
            raise RecipeValidationError(name, [str(e)])

        # Register Execution
        execution = self.store.create(
            recipe_name=name,
            params=params,
            source=source,
            timeout_seconds=timeout,
            workflow_id=getattr(workflow_context, 'execution_id', None) if workflow_context else None,
            step_index=step_index,
        )

        return self._run_with_execution(
            execution_id=execution.id,
            name=name,
            recipe=recipe,
            params=params,
            resolved_env=resolved_env,
            timeout=timeout,
        )

    def run_async(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        source: str | None = None,
        timeout: int | None = None,
    ) -> str:
        """Execute recipe asynchronously, return execution_id immediately.

        Validates parameters synchronously (fail fast), then submits
        execution to the background thread pool.

        Args:
            name: Recipe name.
            params: Input parameters.
            source: Recipe source filter.
            timeout: Timeout in seconds (default 300 for async).

        Returns:
            execution_id for status polling / cancellation.
        """
        from .background import get_executor

        params = params or {}

        # Fail fast: find/validate/resolve before submitting to background
        recipe = self.registry.find(name, source=source)
        self._validate_params(recipe.metadata, params)
        resolved_env = self.env_loader.resolve_for_recipe(
            env_definitions=recipe.metadata.env,
            cli_overrides=None,
            workflow_context=None,
        )

        # Pre-register Execution (PENDING state)
        execution = self.store.create(
            recipe_name=name,
            params=params,
            source=source,
            timeout_seconds=timeout,
        )

        def _run_in_background():
            try:
                self._run_with_execution(
                    execution_id=execution.id,
                    name=name,
                    recipe=recipe,
                    params=params,
                    resolved_env=resolved_env,
                    timeout=timeout,
                )
            except Exception:
                logger.exception("Background recipe execution failed: %s", name)

        executor = get_executor()
        executor.submit(_run_in_background)

        return execution.id

    def _run_with_execution(
        self,
        execution_id: str,
        name: str,
        recipe: Any,
        params: dict[str, Any],
        resolved_env: dict[str, str],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Core execution logic after find/validate/resolve/create.

        Handles: transition(RUNNING) -> subprocess execution -> complete(terminal).
        Called by both run() (sync) and run_async() (background thread).
        """
        # Transition to RUNNING
        self.store.transition(execution_id, ExecutionStatus.RUNNING)

        # Record start time
        start_time = time.time()

        try:
            # Resolve effective timeout (explicit > None = no limit for backward compat)
            effective_timeout = timeout

            # Execute Recipe based on runtime type
            if recipe.metadata.runtime == 'chrome-js':
                result_data = self._run_chrome_js(name, recipe.script_path, params, resolved_env, timeout=effective_timeout, execution_id=execution_id)
            elif recipe.metadata.runtime == 'python':
                # Check if system Python is needed (for scripts that depend on system packages like dbus)
                use_system_python = getattr(recipe.metadata, 'system_packages', False)
                result_data = self._run_python(name, recipe.script_path, params, resolved_env, use_system_python, timeout=effective_timeout, execution_id=execution_id)
            elif recipe.metadata.runtime == 'shell':
                result_data = self._run_shell(name, recipe.script_path, params, resolved_env, timeout=effective_timeout, execution_id=execution_id)
            else:
                raise RecipeExecutionError(
                    recipe_name=name,
                    runtime=recipe.metadata.runtime,
                    exit_code=-1,
                    stderr=f"Unsupported runtime type: {recipe.metadata.runtime}"
                )

            # Calculate execution time
            execution_time = time.time() - start_time

            # Complete Execution
            self.store.complete(
                execution_id,
                status=ExecutionStatus.SUCCEEDED,
                data=result_data.get("data"),
                duration_ms=int(execution_time * 1000),
                exit_code=0,
                runtime=recipe.metadata.runtime,
            )

            # Return success result
            return {
                "success": True,
                "data": result_data.get("data"),
                "stderr": result_data.get("stderr", ""),
                "error": None,
                "execution_time": execution_time,
                "execution_id": execution_id,
                "recipe_name": name,
                "runtime": recipe.metadata.runtime
            }

        except RecipeExecutionError as e:
            execution_time = time.time() - start_time
            status = (ExecutionStatus.TIMEOUT
                      if "timeout" in str(e).lower()
                      else ExecutionStatus.FAILED)
            self.store.complete(
                execution_id,
                status=status,
                error={"code": "EXECUTION_ERROR", "message": str(e)},
                exit_code=getattr(e, 'exit_code', 1),
                duration_ms=int(execution_time * 1000),
                runtime=recipe.metadata.runtime,
            )
            raise
        except Exception as e:
            # Convert other exceptions to RecipeExecutionError
            execution_time = time.time() - start_time
            self.store.complete(
                execution_id,
                status=ExecutionStatus.FAILED,
                error={"code": "EXECUTION_ERROR", "message": str(e)},
                exit_code=-1,
                duration_ms=int(execution_time * 1000),
                runtime=recipe.metadata.runtime,
            )
            raise RecipeExecutionError(
                recipe_name=name,
                runtime=recipe.metadata.runtime,
                exit_code=-1,
                stderr=str(e)
            )

    def cancel(self, execution_id: str) -> bool:
        """Cancel a running execution.

        Args:
            execution_id: The execution ID to cancel.

        Returns:
            True if the process was found and terminated, False otherwise.
        """
        with _process_lock:
            proc = _active_processes.get(execution_id)

        if proc is None or proc.poll() is not None:
            return False

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        self.store.complete(
            execution_id,
            status=ExecutionStatus.CANCELLED,
            error={"code": "CANCELLED", "message": "Execution cancelled by user"},
            exit_code=-15,
        )
        return True

    def _run_subprocess(
        self,
        execution_id: str,
        cmd: list[str],
        env: dict[str, str],
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a command via Popen, tracking the process for cancellation.

        Args:
            execution_id: Execution ID for process tracking.
            cmd: Command to run.
            env: Environment variables.
            timeout: Timeout in seconds (None = no limit).

        Returns:
            CompletedProcess with stdout, stderr, returncode.

        Raises:
            subprocess.TimeoutExpired: If the process exceeds timeout.
        """
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        with _process_lock:
            _active_processes[execution_id] = proc

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=proc.returncode,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)
            raise
        finally:
            with _process_lock:
                _active_processes.pop(execution_id, None)

    def _validate_params(self, metadata, params: dict[str, Any]) -> None:
        """
        Validate if parameters conform to metadata definition

        Args:
            metadata: Recipe metadata
            params: Input parameters

        Raises:
            RecipeValidationError: Parameter validation failed
        """
        # Use unified parameter validation function (includes required parameters and type checking)
        validate_params(metadata, params)

    def _run_chrome_js(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str],
        timeout: int | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute Chrome JavaScript Recipe

        Args:
            recipe_name: Recipe name
            script_path: JS script path
            params: Input parameters
            env: Resolved environment variables
            timeout: Timeout in seconds
            execution_id: Execution ID for process tracking

        Returns:
            Execution result JSON

        Raises:
            RecipeExecutionError: Execution failed
        """
        # If there are parameters, inject them into window.__FRAGO_PARAMS__ first
        if params:
            params_json = json.dumps(params)
            inject_cmd = [
                'uv', 'run', 'frago', 'chrome', 'exec-js',
                f'window.__FRAGO_PARAMS__ = {params_json}'
            ]
            try:
                inject_result = subprocess.run(
                    inject_cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=30,
                    check=False,
                    env=env
                )
                if inject_result.returncode != 0:
                    raise RecipeExecutionError(
                        recipe_name=recipe_name,
                        runtime='chrome-js',
                        exit_code=inject_result.returncode,
                        stderr=f"Parameter injection failed: {inject_result.stderr}"
                    )
            except subprocess.TimeoutExpired:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='chrome-js',
                    exit_code=-1,
                    stderr="Parameter injection timeout"
                )

        # Build command: uv run frago chrome exec-js <script_path> --return-value
        cmd = [
            'uv', 'run', 'frago', 'chrome', 'exec-js',
            str(script_path),
            '--return-value'
        ]

        try:
            result = self._run_subprocess(execution_id, cmd, env, timeout=timeout) if execution_id else subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False, env=env
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='chrome-js',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # Check output size (10MB limit)
            if len(result.stdout) > 10 * 1024 * 1024:  # 10MB
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='chrome-js',
                    exit_code=-1,
                    stderr=f"Recipe output too large: {len(result.stdout) / 1024 / 1024:.2f}MB (limit: 10MB)"
                )

            # Parse JSON output
            try:
                # exec-js output can be plain text or JSON
                # Try parsing as JSON, return as text if it fails
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Return text result
                data = {"result": result.stdout.strip()}

            return {"data": data, "stderr": result.stderr}

        except subprocess.TimeoutExpired:
            raise RecipeExecutionError(
                recipe_name=recipe_name,
                runtime='chrome-js',
                exit_code=-1,
                stderr=f"Execution timeout ({timeout}s)" if timeout else "Execution timeout"
            )

    def _run_python(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str],
        use_system_python: bool = False,
        timeout: int | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute Python Recipe

        By default, uses `uv run` to execute the script, supporting PEP 723 inline dependency declarations.
        If use_system_python=True, uses system Python (for scripts depending on system packages like dbus)

        Args:
            recipe_name: Recipe name
            script_path: Python script path
            params: Input parameters
            env: Resolved environment variables
            use_system_python: Whether to use system Python
            timeout: Timeout in seconds
            execution_id: Execution ID for process tracking

        Returns:
            Execution result JSON

        Raises:
            RecipeExecutionError: Execution failed
        """
        params_json = json.dumps(params)

        if use_system_python:
            # Use system Python (for scripts depending on system packages like dbus)
            # Must clear VIRTUAL_ENV to avoid inheriting uv's virtual environment
            if platform.system() == "Windows":
                # Windows: use current Python interpreter
                python_path = sys.executable
            else:
                # Unix: prefer system Python
                python_path = shutil.which('python3') or '/usr/bin/python3'
            cmd = [python_path, str(script_path), params_json]
            # Create environment without virtual environment variables
            clean_env = {k: v for k, v in env.items() if k not in ('VIRTUAL_ENV', 'PYTHONHOME')}
            env = clean_env
        else:
            # Build command: uv run <script_path> <params_json>
            # uv will automatically handle PEP 723 inline dependencies (# /// script ... # ///)
            cmd = ['uv', 'run', str(script_path), params_json]

        try:
            result = self._run_subprocess(execution_id, cmd, env, timeout=timeout) if execution_id else subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False, env=env
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='python',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # Check output size (10MB limit)
            if len(result.stdout) > 10 * 1024 * 1024:  # 10MB
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='python',
                    exit_code=-1,
                    stderr=f"Recipe output too large: {len(result.stdout) / 1024 / 1024:.2f}MB (limit: 10MB)"
                )

            # Parse JSON output
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='python',
                    exit_code=-1,
                    stderr=f"JSON parsing failed: {e}\nOutput: {result.stdout[:200]}"
                )

            return {"data": data, "stderr": result.stderr}

        except subprocess.TimeoutExpired:
            raise RecipeExecutionError(
                recipe_name=recipe_name,
                runtime='python',
                exit_code=-1,
                stderr=f"Execution timeout ({timeout}s)" if timeout else "Execution timeout"
            )

    def _run_shell(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str],
        timeout: int | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute Shell Recipe

        Args:
            recipe_name: Recipe name
            script_path: Shell script path
            params: Input parameters
            env: Resolved environment variables
            timeout: Timeout in seconds
            execution_id: Execution ID for process tracking

        Returns:
            Execution result JSON

        Raises:
            RecipeExecutionError: Execution failed
        """
        # Check execution permissions (Unix systems only, Windows does not use Unix permission mode)
        if platform.system() != "Windows":
            if not script_path.stat().st_mode & 0o100:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='shell',
                    exit_code=-1,
                    stderr=f"Script does not have execute permission: {script_path}"
                )

        # Build command: <script_path> <params_json>
        params_json = json.dumps(params)
        cmd = [str(script_path), params_json]

        try:
            result = self._run_subprocess(execution_id, cmd, env, timeout=timeout) if execution_id else subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False, env=env
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='shell',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # Check output size (10MB limit)
            if len(result.stdout) > 10 * 1024 * 1024:  # 10MB
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='shell',
                    exit_code=-1,
                    stderr=f"Recipe output too large: {len(result.stdout) / 1024 / 1024:.2f}MB (limit: 10MB)"
                )

            # Parse JSON output
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='shell',
                    exit_code=-1,
                    stderr=f"JSON parsing failed: {e}\nOutput: {result.stdout[:200]}"
                )

            return {"data": data, "stderr": result.stderr}

        except subprocess.TimeoutExpired:
            raise RecipeExecutionError(
                recipe_name=recipe_name,
                runtime='shell',
                exit_code=-1,
                stderr=f"Execution timeout ({timeout}s)" if timeout else "Execution timeout"
            )
