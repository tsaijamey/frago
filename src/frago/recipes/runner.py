"""Recipe executor"""
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from frago.compat import get_windows_subprocess_kwargs

from . import context
from .env_loader import EnvLoader, WorkflowContext
from .exceptions import RecipeExecutionError, RecipeValidationError
from .execution import ExecutionStatus
from .execution_store import ExecutionStore
from .metadata import validate_params
from .registry import RecipeRegistry, get_registry

logger = logging.getLogger(__name__)


def _frago_argv() -> list[str]:
    """Return argv prefix to invoke frago.

    Always the bare command. frago is installed as a uv tool and resolved
    from PATH; the source checkout never runs frago from its own venv (see
    frago.server.launch_guard), so there is exactly one binary to find.
    """
    return ["frago"]

# Module-level process registry shared across all RecipeRunner instances.
# Enables cancel() from any runner instance (e.g., a different request handler).
_active_processes: dict[str, subprocess.Popen[bytes]] = {}
_process_lock = threading.Lock()


class UnconvertedRecipe(RecipeExecutionError):
    """This file was not built on the contract, so nothing will start it."""


def _refuse_unconverted(name: str, recipe) -> None:
    """Refuse a recipe that never came from the template.

    The header is the only thing checked here, and it is checked at the moment
    of starting rather than at some earlier point somebody may have skipped.
    Everything else the contract asks for — the base class, the declared modes,
    the exported surface — is checked by `frago recipe validate`, which can
    afford to read the whole file. This one question has to be answered on
    every single run, so it is the cheapest possible one: are the first few
    lines of this file the ones the template writes.
    """
    from frago.recipes.birth import Birth, check

    # Only runtimes the contract actually covers. The base class is Python; a
    # chrome-js recipe runs inside a browser and has nothing to inherit from,
    # so refusing it would leave it unrunnable with no way forward — and the
    # refusal even told the author to regenerate from a template that only
    # produces Python, which would have destroyed the recipe. A gate whose
    # instructions break the thing it is protecting is worse than no gate.
    runtime = getattr(recipe.metadata, "runtime", "") or ""
    if runtime not in ("python",):
        return

    script = getattr(recipe, "script_path", None)
    if not script:
        return
    try:
        head = "\n".join(
            Path(script).read_text(encoding="utf-8", errors="ignore").splitlines()[:12]
        )
    except OSError:
        return
    state, why = check(name, head)
    if state == Birth.MARKED:
        return
    raise UnconvertedRecipe(
        recipe_name=name,
        runtime=getattr(recipe.metadata, "runtime", "") or "",
        exit_code=-1,
        stderr=(f"{why}\n"
                f"这个配方还没建在基类上，平台不会启动它。"
                f"改造它：frago recipe create {name} --force 生成模板，"
                f"把现有逻辑搬进 mode_* 方法。"),
    )


def _bus_token() -> str:
    """This machine's server token, or empty when it has none."""
    try:
        from frago.server.security import read_token
        return read_token() or ""
    except Exception:
        return ""


def _bus_url() -> str:
    """Where the hub is listening for this machine.

    Read from the same config the server starts from rather than hardcoded, so
    a machine that moved its port does not silently hand every recipe an
    address nothing answers on.
    """
    port = os.environ.get("FRAGO_SERVER_PORT")
    if not port:
        try:
            from frago.config import get_config
            port = str(get_config().get("server", {}).get("port", 8093))
        except Exception:
            port = "8093"
    return f"http://127.0.0.1:{port}"


#: The message kinds a recipe puts on stdout. A recipe built on the base class
#: writes one JSON object per line and its last line is the result; anything
#: older writes a single JSON object and nothing else. Both are read here,
#: because three hundred recipes cannot change on the same afternoon.
_MSG_RESULT = "result"
_MSG_PROGRESS = "progress"
_MSG_WARN = "warn"


def _read_messages(stdout: str) -> tuple[dict | None, list[dict]]:
    """Split a recipe's stdout into (result, everything said along the way).

    Returns ``(None, [])`` when this is not a message stream, so the caller can
    fall back to parsing the whole of stdout as one object.

    A stream is recognised by its messages, not by a flag: a recipe that emits
    progress and then dies leaves a stream with no result, and that has to be
    distinguishable from a recipe that printed nothing at all. The first tells
    you how far it got; the second tells you it never started.
    """
    result: dict | None = None
    trail: list[dict] = []
    saw_message = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        kind = msg.get("t")
        if kind in (_MSG_PROGRESS, _MSG_WARN):
            saw_message = True
            trail.append(msg)
        elif kind == _MSG_RESULT:
            saw_message = True
            result = msg
    return (result, trail) if saw_message else (None, [])


def _unwrap(stdout: str) -> dict:
    """What this run returned, whichever shape the recipe speaks.

    A recipe on the module contract returns an envelope: the payload sits under
    ``data`` with ``ok``/``warnings``/``error`` around it, one shape across
    every module so a caller can handle any of them without knowing which it
    called. Older recipes return the payload bare. Both end up as one dict
    here; what is lost in the old shape — how far it got, what it warned about
    — was never there to begin with.
    """
    result, trail = _read_messages(stdout)
    if result is None and not trail:
        return json.loads(stdout)
    if result is None:
        raise RecipeExecutionError(
            recipe_name="", runtime="python", exit_code=-1,
            stdout=stdout,
            stderr=("配方开始说话了却没给出结果：收到 "
                    f"{len(trail)} 条过程消息，没有 result。"
                    "多半是跑到一半退出了，最后一条过程消息就是它走到的地方。"),
        )
    data = result.get("data")
    out = dict(data) if isinstance(data, dict) else {"result": data}
    out.setdefault("success", bool(result.get("ok")))
    if result.get("warnings"):
        out.setdefault("warnings", result["warnings"])
    if result.get("error"):
        out.setdefault("error", result["error"])
    return out


class RecipeRunner:
    """Recipe runner, responsible for executing Recipes"""

    def __init__(
        self,
        registry: RecipeRegistry | None = None,
        project_root: Path | None = None
    ):
        """
        Initialize RecipeRunner

        Args:
            registry: Recipe registry (auto-created and scanned if not provided)
            project_root: Project root directory (used to load project-level .env)
        """
        if registry is None:
            registry = get_registry()

        self.registry = registry
        self.env_loader = EnvLoader(project_root=project_root)
        self.store = ExecutionStore()

    def run(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        output_target: str = 'stdout',  # noqa: ARG002 — passed by CLI, output handling is caller's responsibility
        output_options: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None,
        source: str | None = None,
        timeout: int | None = None,
        step_index: int | None = None,
        ctx: context.InvocationContext | None = None,
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
            ctx: Who this run is for. None is the owner, which is every run
                started from this machine; the server passes a visitor context.

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
                env_definitions={},
                cli_overrides=env_overrides,
                workflow_context=workflow_context
            )
        except ValueError as e:
            raise RecipeValidationError(name, [str(e)]) from e

        # Load and inject secrets from recipes.local.json
        if recipe.metadata.secrets:
            secrets = self._resolve_secrets(name, recipe.metadata.secrets)
            resolved_env["FRAGO_SECRETS"] = json.dumps(secrets)

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
            ctx=ctx,
        )

    def run_async(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        source: str | None = None,
        timeout: int | None = None,
        ctx: context.InvocationContext | None = None,
    ) -> str:
        """Execute recipe asynchronously, return execution_id immediately.

        Validates parameters synchronously (fail fast), then submits
        execution to the background thread pool.

        Args:
            name: Recipe name.
            params: Input parameters.
            source: Recipe source filter.
            timeout: Timeout in seconds (default 300 for async).
            ctx: Who this run is for. None is the owner.

        Returns:
            execution_id for status polling / cancellation.
        """
        from .background import get_executor

        params = params or {}

        # Fail fast: find/validate/resolve before submitting to background
        recipe = self.registry.find(name, source=source)
        self._validate_params(recipe.metadata, params)
        resolved_env = self.env_loader.resolve_for_recipe(
            env_definitions={},
            cli_overrides=None,
            workflow_context=None,
        )

        # Load and inject secrets from recipes.local.json
        if recipe.metadata.secrets:
            secrets = self._resolve_secrets(name, recipe.metadata.secrets)
            resolved_env["FRAGO_SECRETS"] = json.dumps(secrets)

        # Pre-register Execution (PENDING state)
        execution = self.store.create(
            recipe_name=name,
            params=params,
            source=source,
            timeout_seconds=timeout,
        )

        def _run_in_background() -> None:
            try:
                self._run_with_execution(
                    execution_id=execution.id,
                    name=name,
                    recipe=recipe,
                    params=params,
                    resolved_env=resolved_env,
                    timeout=timeout,
                    ctx=ctx,
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
        ctx: context.InvocationContext | None = None,
    ) -> dict[str, Any]:
        """Core execution logic after find/validate/resolve/create.

        Handles: transition(RUNNING) -> subprocess execution -> complete(terminal).
        Called by both run() (sync) and run_async() (background thread).
        """
        # Both callers land here, so this is the one place the invocation
        # context has to be stamped on — and it is stamped after `resolved_env`
        # is fully assembled, so no `.env` file, `--env` flag or workflow
        # context can outrank it. `apply_to_env` overwrites rather than filling
        # in; see its docstring for why "we do not write it" would not have been
        # enough.
        #
        # No caller means the owner, and until now that meant a run that could
        # not say whose it was. It can now: the machine records one identity and
        # every run carries it, so the recipe no longer has to invent a place to
        # write. Where its data has not been copied to the new layout yet, the
        # directory is deliberately withheld and the recipe keeps its old
        # behaviour — see `context.for_owner`.
        if ctx is None:
            try:
                ctx = context.for_owner(name)
            except context.NoIdentity:
                # This machine cannot say whose run this is. Refusing here would
                # stop every recipe on a machine with one damaged file, which is
                # worse than the thing being prevented — so the run proceeds the
                # way it always did, and the damage is reported where it can be
                # acted on rather than raised into a person's recipe.
                logger.warning(
                    "此机器的身份记录读不出，本次运行按旧行为进行（数据落点由配方自己决定）。"
                    "修好 ~/.frago/identity.json 之后新落点才会生效。",
                    exc_info=True,
                )
        context.apply_to_env(resolved_env, ctx)

        # What a recipe is built on, and how it reaches the hub. Both are handed
        # over the same way the landing spot is, and for the same reason: a
        # recipe cannot import frago (most carry a PEP 723 block, so `uv run`
        # builds an isolated environment holding only what that recipe
        # declared). Putting the base class on PYTHONPATH means a recipe uses
        # it without declaring a dependency — and means fixing the contract is
        # one edit here rather than one edit in each of three hundred copies.
        runtime_dir = str(Path(__file__).parent / "runtime")
        existing = resolved_env.get("PYTHONPATH") or ""
        resolved_env["PYTHONPATH"] = (
            f"{runtime_dir}{os.pathsep}{existing}" if existing else runtime_dir
        )
        resolved_env[context.BUS_ENV] = _bus_url()
        # On a deployed server nothing is trusted by address, so the recipe
        # needs the token to reach the hub at all. Read here rather than left
        # to the recipe: the file is 0600 and a recipe that had to find it
        # would be a recipe that knows where the server's secrets live.
        token = _bus_token()
        if token:
            resolved_env["FRAGO_BUS_TOKEN"] = token
        if execution_id:
            resolved_env["FRAGO_EXECUTION_ID"] = execution_id

        # And this is where the run gets somewhere to stand. Until now a recipe
        # started in whatever directory its caller happened to be in — a shell,
        # the server's working directory, an agent's project root — so a recipe
        # that wanted to keep anything had no choice but to name an absolute
        # path, and the only absolute path its author could know was one on
        # their own machine. That path is exactly what breaks when the recipe is
        # copied to a server: the page it serves ends up pointing at a file that
        # does not exist there, and nobody finds out until a visitor opens it.
        #
        # Handing it a prepared directory removes the reason to name a path at
        # all. `open("ledger.json", "w")` is now correct everywhere, and correct
        # without the author having read anything.
        try:
            run_cwd: str | None = str(context.prepare_working_dir(name, ctx))
        except OSError:
            # Somewhere unwritable is not a reason to refuse the run: recipes
            # that name absolute paths do not care where they stand, and that is
            # most of them. Fall back to the old behaviour of inheriting.
            run_cwd = None

        # Transition to RUNNING
        self.store.transition(execution_id, ExecutionStatus.RUNNING)

        # Record start time
        start_time = time.time()

        # Strip proxy env vars if recipe declares no_proxy: true
        if getattr(recipe.metadata, 'no_proxy', False):
            for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                              "http_proxy", "https_proxy", "all_proxy"):
                resolved_env.pop(proxy_key, None)

        # Bind recipe subprocess to a chrome tab group so `frago browser ...`
        # inside the recipe resolves a group context without needing --group.
        # Priority: existing env (agent/executor already injected) → current
        # run instance (CLI with active run context) → execution_id fallback
        # (standalone run, at least get an isolated group).
        if "FRAGO_CURRENT_RUN" not in resolved_env:
            run_id: str | None = None
            try:
                from frago.run.context import ContextManager
                frago_home = Path.home() / ".frago"
                run_id = ContextManager(
                    frago_home, frago_home / "projects"
                ).get_current_run_id()
            except Exception:
                run_id = None
            resolved_env["FRAGO_CURRENT_RUN"] = run_id or execution_id

        try:
            # Nothing starts without the contract header. This is the choke
            # point on purpose: `frago recipe validate` is a command a person
            # chooses to run, and a rule that only holds when somebody
            # remembers to check is not a rule. Proved on this machine —
            # validate refused cookbook_dashboard and it ran anyway.
            _refuse_unconverted(name, recipe)

            # Resolve effective timeout (explicit > None = no limit for backward compat)
            effective_timeout = timeout

            # Execute Recipe based on runtime type
            if recipe.metadata.runtime == 'chrome-js':
                # No cwd here on purpose: this runtime does not run the recipe as
                # a local process at all — the script executes inside the browser
                # and reaches the disk, if ever, through frago's own commands.
                # A working directory would describe nothing.
                result_data = self._run_chrome_js(name, recipe.script_path, params, resolved_env, timeout=effective_timeout, execution_id=execution_id)
            elif recipe.metadata.runtime == 'python':
                # Check if system Python is needed (for scripts that depend on system packages like dbus)
                use_system_python = getattr(recipe.metadata, 'system_packages', False)
                result_data = self._run_python(name, recipe.script_path, params, resolved_env, use_system_python, timeout=effective_timeout, execution_id=execution_id, cwd=run_cwd)
            elif recipe.metadata.runtime == 'shell':
                result_data = self._run_shell(name, recipe.script_path, params, resolved_env, timeout=effective_timeout, execution_id=execution_id, cwd=run_cwd)
            else:
                raise RecipeExecutionError(
                    recipe_name=name,
                    runtime=recipe.metadata.runtime,
                    exit_code=-1,
                    stderr=f"Unsupported runtime type: {recipe.metadata.runtime}"
                )

            # Calculate execution time
            execution_time = time.time() - start_time

            # Handle open_url directive from recipe output
            data = result_data.get("data")
            if isinstance(data, dict) and data.get("open_url"):
                # On the owner's machine this is a feature: the recipe finishes
                # and the page it made opens. Started by a visitor it is a
                # stranger making a window appear on somebody else's screen —
                # the recipe is the same, the person who pressed the button is
                # not. The instruction is dropped rather than obeyed quietly, so
                # a recipe that relies on it can be found in the log.
                if ctx is not None and ctx.is_visitor:
                    logger.info(
                        "recipe %s asked to open a browser; ignored because this run "
                        "was started by a visitor", name,
                    )
                else:
                    self._handle_open_url(data["open_url"])

            # Complete Execution
            self.store.complete(
                execution_id,
                status=ExecutionStatus.SUCCEEDED,
                data=data,
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
            ) from e

    def _handle_open_url(self, url: str) -> None:
        """Open a URL in the user's default browser.

        Called when recipe output contains open_url. The page is for the human
        to look at, so it goes to the default browser rather than the CDP-driven
        Chrome that `frago browser` operates on.
        """
        try:
            import webbrowser

            webbrowser.open(url)
            logger.info("Opened URL in default browser: %s", url)
        except Exception:
            logger.exception("Failed to open URL in default browser: %s", url)

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
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command via Popen, tracking the process for cancellation.

        Args:
            execution_id: Execution ID for process tracking.
            cmd: Command to run.
            env: Environment variables.
            timeout: Timeout in seconds (None = no limit).
            cwd: Directory to start the process in (the run's own directory).

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
            cwd=cwd,
            **get_windows_subprocess_kwargs(),
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

    def _resolve_secrets(self, recipe_name: str, secrets_schema: dict[str, Any]) -> dict[str, Any]:
        """从 recipes.local.json 加载凭证，解析 $ref，校验 required 字段。

        Args:
            recipe_name: recipe name（recipes.local.json 的 key）
            secrets_schema: recipe.md 中声明的 secrets 字段定义

        Returns:
            凭证字典（只包含 schema 中声明的字段）

        Raises:
            RecipeValidationError: 缺少 required 字段
        """
        config_path = Path.home() / ".frago" / "recipes.local.json"
        if not config_path.exists():
            raw = {}
        else:
            all_config = json.loads(config_path.read_text(encoding="utf-8"))
            raw = all_config.get(recipe_name, {})
            if "$ref" in raw:
                raw = all_config.get(raw["$ref"], {})

        # 按 schema 过滤 — 只提取 secrets: 中声明的字段
        filtered = {k: raw[k] for k in secrets_schema if k in raw}

        # 校验 required
        missing = [
            k for k, v in secrets_schema.items()
            if isinstance(v, dict) and v.get("required") and k not in filtered
        ]
        if missing:
            raise RecipeValidationError(recipe_name, [
                f"Missing required secrets: {', '.join(missing)}. "
                f"Configure in Web UI or edit ~/.frago/recipes.local.json"
            ])

        return filtered

    def _validate_params(self, metadata: Any, params: dict[str, Any]) -> None:
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
                *_frago_argv(), 'browser', 'exec-js',
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
                    env=env,
                    **get_windows_subprocess_kwargs(),
                )
                if inject_result.returncode != 0:
                    raise RecipeExecutionError(
                        recipe_name=recipe_name,
                        runtime='chrome-js',
                        exit_code=inject_result.returncode,
                        stderr=f"Parameter injection failed: {inject_result.stderr}"
                    )
            except subprocess.TimeoutExpired as e:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='chrome-js',
                    exit_code=-1,
                    stderr="Parameter injection timeout"
                ) from e

        # Build command: <frago_launcher> browser exec-js <script_path> --return-value
        cmd = [
            *_frago_argv(), 'browser', 'exec-js',
            str(script_path),
            '--return-value'
        ]

        try:
            result = self._run_subprocess(execution_id, cmd, env, timeout=timeout) if execution_id else subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False, env=env,
                **get_windows_subprocess_kwargs(),
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='chrome-js',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    detail=self._recipe_failure_reason(result.stdout, result.stderr),
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
                data = _unwrap(result.stdout)
            except json.JSONDecodeError:
                # Return text result
                data = {"result": result.stdout.strip()}

            return {"data": data, "stderr": result.stderr}

        except subprocess.TimeoutExpired as e:
            raise RecipeExecutionError(
                recipe_name=recipe_name,
                runtime='chrome-js',
                exit_code=-1,
                stderr=f"Execution timeout ({timeout}s)" if timeout else "Execution timeout"
            ) from e

    @staticmethod
    def _recipe_failure_reason(stdout: str, stderr: str) -> str:
        """Extract the most human-readable reason a recipe failed.

        Recipes conventionally print {"success": false, "error": "..."} to
        stdout for a handled failure (e.g. missing params). Surface that error
        string; otherwise fall back to the last non-empty stderr line. Returns
        "" when nothing useful is found, leaving just the exit-code message.
        """
        # A recipe on the module contract puts its reason in the last message's
        # envelope. Read that first: without it the runner reports a bare
        # "exit code: 1" and swallows whatever the recipe took the trouble to
        # say — so the more carefully a recipe explains itself, the less anyone
        # sees. Every recipe written against the new contract was affected.
        result, trail = _read_messages(stdout)
        if result is not None:
            err = result.get("error") or {}
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
        elif trail:
            last = trail[-1]
            note = last.get("note")
            if note:
                return f"跑到「{note}」就没下文了（收到 {len(trail)} 条过程消息，没有结果）"

        if stdout:
            try:
                data = json.loads(stdout)
            except (json.JSONDecodeError, ValueError):
                data = None
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, str) and err.strip():
                    return err.strip()
        if stderr and stderr.strip():
            lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
            if lines:
                return lines[-1].strip()
        return ""

    def _run_python(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str],
        use_system_python: bool = False,
        timeout: int | None = None,
        execution_id: str | None = None,
        cwd: str | None = None,
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

        # Force UTF-8 stdio in child Python so recipes printing 中文/UTF-8 to
        # stderr don't crash on Windows consoles whose default encoding is
        # cp936/cp932/etc. Applies to both system-python and uv-run paths.
        env["PYTHONIOENCODING"] = "utf-8"

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
            result = self._run_subprocess(execution_id, cmd, env, timeout=timeout, cwd=cwd) if execution_id else subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False, env=env,
                cwd=cwd,
                **get_windows_subprocess_kwargs(),
            )

            if result.returncode != 0:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='python',
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    detail=self._recipe_failure_reason(result.stdout, result.stderr),
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
                data = _unwrap(result.stdout)
            except json.JSONDecodeError as e:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='python',
                    exit_code=-1,
                    stderr=f"JSON parsing failed: {e}\nOutput: {result.stdout}"
                ) from e

            return {"data": data, "stderr": result.stderr}

        except subprocess.TimeoutExpired as e:
            raise RecipeExecutionError(
                recipe_name=recipe_name,
                runtime='python',
                exit_code=-1,
                stderr=f"Execution timeout ({timeout}s)" if timeout else "Execution timeout"
            ) from e

    def _run_shell(
        self,
        recipe_name: str,
        script_path: Path,
        params: dict[str, Any],
        env: dict[str, str],
        timeout: int | None = None,
        execution_id: str | None = None,
        cwd: str | None = None,
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
        if platform.system() != "Windows" and not script_path.stat().st_mode & 0o100:
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
            result = self._run_subprocess(execution_id, cmd, env, timeout=timeout, cwd=cwd) if execution_id else subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False, env=env,
                cwd=cwd,
                **get_windows_subprocess_kwargs(),
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
                data = _unwrap(result.stdout)
            except json.JSONDecodeError as e:
                raise RecipeExecutionError(
                    recipe_name=recipe_name,
                    runtime='shell',
                    exit_code=-1,
                    stderr=f"JSON parsing failed: {e}\nOutput: {result.stdout}"
                ) from e

            return {"data": data, "stderr": result.stderr}

        except subprocess.TimeoutExpired as e:
            raise RecipeExecutionError(
                recipe_name=recipe_name,
                runtime='shell',
                exit_code=-1,
                stderr=f"Execution timeout ({timeout}s)" if timeout else "Execution timeout"
            ) from e
