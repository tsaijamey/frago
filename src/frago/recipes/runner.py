"""Recipe executor"""
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .env_loader import EnvLoader, WorkflowContext
from .exceptions import RecipeExecutionError, RecipeValidationError
from .metadata import validate_params
from .registry import RecipeRegistry


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

    def run(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        output_target: str = 'stdout',
        output_options: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None,
        source: str | None = None
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

        # Record start time
        start_time = time.time()

        try:
            # Execute Recipe based on runtime type
            if recipe.metadata.runtime == 'chrome-js':
                result_data = self._run_chrome_js(name, recipe.script_path, params, resolved_env)
            elif recipe.metadata.runtime == 'python':
                # Check if system Python is needed (for scripts that depend on system packages like dbus)
                use_system_python = getattr(recipe.metadata, 'system_packages', False)
                result_data = self._run_python(name, recipe.script_path, params, resolved_env, use_system_python)
            elif recipe.metadata.runtime == 'shell':
                result_data = self._run_shell(name, recipe.script_path, params, resolved_env)
            else:
                raise RecipeExecutionError(
                    recipe_name=name,
                    runtime=recipe.metadata.runtime,
                    exit_code=-1,
                    stderr=f"Unsupported runtime type: {recipe.metadata.runtime}"
                )

            # Calculate execution time
            execution_time = time.time() - start_time

            # Return success result
            return {
                "success": True,
                "data": result_data.get("data"),
                "stderr": result_data.get("stderr", ""),
                "error": None,
                "execution_time": execution_time,
                "recipe_name": name,
                "runtime": recipe.metadata.runtime
            }

        except RecipeExecutionError:
            # Re-raise RecipeExecutionError directly
            raise
        except Exception as e:
            # Convert other exceptions to RecipeExecutionError
            execution_time = time.time() - start_time
            raise RecipeExecutionError(
                recipe_name=name,
                runtime=recipe.metadata.runtime,
                exit_code=-1,
                stderr=str(e)
            )

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
        env: dict[str, str]
    ) -> dict[str, Any]:
        """
        Execute Chrome JavaScript Recipe

        Args:
            recipe_name: Recipe name
            script_path: JS script path
            params: Input parameters
            env: Resolved environment variables

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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=None,  # No timeout limit
                check=False,
                env=env
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
                stderr="Execution timeout (5 minutes)"
            )

    def _run_python(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str],
        use_system_python: bool = False
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

        Returns:
            Execution result JSON

        Raises:
            RecipeExecutionError: Execution failed
        """
        params_json = json.dumps(params)
        import os

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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=None,  # No timeout limit
                check=False,
                env=env
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
                stderr="Execution timeout (5 minutes)"
            )

    def _run_shell(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str]
    ) -> dict[str, Any]:
        """
        Execute Shell Recipe

        Args:
            recipe_name: Recipe name
            script_path: Shell script path
            params: Input parameters
            env: Resolved environment variables

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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=None,  # No timeout limit
                check=False,
                env=env
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
                stderr="Execution timeout (5 minutes)"
            )
