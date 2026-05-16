"""Recipe management commands"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from frago.recipes import OutputHandler, RecipeRegistry, RecipeRunner
from frago.recipes.exceptions import MetadataParseError, RecipeError, RecipeValidationError
from frago.recipes.metadata import parse_metadata_file, validate_metadata
from frago.tools.sync_repo import _ensure_git_user_config

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup


@click.group(name='recipe', cls=AgentFriendlyGroup)
def recipe_group():
    """Recipe management command group"""
    pass


def _resolve_recipe_dir(name: str, type_: str | None, runtime: str | None) -> Path:
    """Resolve recipe directory path based on type and runtime."""
    base = Path.home() / '.frago' / 'recipes'
    if type_ == 'workflow':
        return base / 'workflows' / name
    if runtime == 'chrome-js':
        return base / 'atomic' / 'chrome' / name
    return base / 'atomic' / 'system' / name


def _find_recipe_dir_by_name(name: str) -> Path | None:
    """Find existing recipe directory by name from registry or filesystem."""
    base = Path.home() / '.frago' / 'recipes'
    # Check known locations
    for subdir in ['atomic/system', 'atomic/chrome', 'workflows']:
        candidate = base / subdir / name
        if candidate.exists():
            return candidate
    return None


def _run_frago_agent(prompt_text: str) -> int:
    """Run frago agent as subprocess with the given prompt.

    Returns the process exit code.
    """
    # Write prompt to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(prompt_text)
        prompt_file = f.name

    try:
        # Resolve frago binary: prefer the entry point next to current Python interpreter,
        # same strategy as server/services/agent_service.py::_get_frago_agent_command
        venv_dir = Path(sys.executable).parent
        frago_in_venv = shutil.which("frago", path=str(venv_dir))
        if frago_in_venv:
            frago_cmd = [frago_in_venv]
        elif shutil.which("uv"):
            frago_cmd = ["uv", "run", "frago"]
        else:
            frago_cmd = ["frago"]
        cmd = [*frago_cmd, "agent", "--yes", "--quiet", "--prompt-file", prompt_file]

        result = subprocess.run(cmd, timeout=600)
        return result.returncode
    except subprocess.TimeoutExpired:
        click.echo("Error: Agent execution timed out (600s)", err=True)
        return 1
    finally:
        Path(prompt_file).unlink(missing_ok=True)


@recipe_group.command(name='plan', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option(
    '--prompt', '-p',
    type=str,
    default=None,
    help='Requirement description'
)
@click.option(
    '--prompt-file',
    type=click.Path(exists=True),
    default=None,
    help='Read requirement from file'
)
@click.option(
    '--type', 'type_',
    type=click.Choice(['atomic', 'workflow'], case_sensitive=False),
    default=None,
    help='Preset type (atomic/workflow)'
)
@click.option(
    '--runtime',
    type=click.Choice(['python', 'chrome-js', 'shell'], case_sensitive=False),
    default=None,
    help='Preset runtime'
)
@click.option(
    '--force', '-f',
    is_flag=True,
    help='Overwrite existing spec.md'
)
def plan_recipe(name: str, prompt: str | None, prompt_file: str | None, type_: str | None, runtime: str | None, force: bool):
    """
    Generate a recipe spec via agent

    Creates a spec.md file defining requirements for a recipe.
    The agent will consult frago book recipe-spec-writing for guidelines.

    \b
    Examples:
      frago recipe plan my_scraper --prompt "从指定网站提取文章标题和链接"
      frago recipe plan my_tool --prompt-file requirements.txt
      frago recipe plan my_tool --prompt "..." --type atomic --runtime python
    """
    # Read prompt
    if prompt_file:
        prompt_text = Path(prompt_file).read_text(encoding='utf-8').strip()
    elif prompt:
        prompt_text = prompt
    else:
        click.echo("Error: --prompt or --prompt-file is required", err=True)
        click.echo("[Fix] frago recipe plan <name> --prompt \"<requirement>\"", err=True)
        sys.exit(1)

    # Resolve directory
    recipe_dir = _resolve_recipe_dir(name, type_, runtime)
    spec_path = recipe_dir / "spec.md"

    # Check conflict
    if spec_path.exists() and not force:
        click.echo(f"Error: spec.md already exists at {spec_path}", err=True)
        click.echo("[Fix] Use --force to overwrite, or review the existing spec", err=True)
        sys.exit(1)

    # Create directory
    recipe_dir.mkdir(parents=True, exist_ok=True)

    # Build agent prompt
    type_hint = f"\n预设 type: {type_}" if type_ else ""
    runtime_hint = f"\n预设 runtime: {runtime}" if runtime else ""

    agent_prompt = f"""你是 frago recipe spec 撰写专家。

任务：为 recipe '{name}' 撰写需求 spec。

先运行以下命令获取规范：
  uv run frago book recipe-spec-writing

用户需求：
{prompt_text}
{type_hint}{runtime_hint}

将 spec 写入：{spec_path}
"""

    click.echo(f"[Plan] Generating spec for recipe '{name}'...")
    click.echo(f"  Directory: {recipe_dir}")

    exit_code = _run_frago_agent(agent_prompt)

    if exit_code != 0:
        click.echo("Error: Agent failed to generate spec", err=True)
        sys.exit(1)

    if spec_path.exists():
        click.echo(f"[OK] Spec written: {spec_path}")
        click.echo("Review and edit the spec, then run:")
        click.echo(f"  frago recipe create {name}")
    else:
        click.echo("Error: Agent did not produce spec.md", err=True)
        sys.exit(1)


@recipe_group.command(name='create', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option(
    '--prompt', '-p',
    type=str,
    default=None,
    help='Requirement description (one-step creation, skip spec)'
)
@click.option(
    '--prompt-file',
    type=click.Path(exists=True),
    default=None,
    help='Read requirement from file'
)
@click.option(
    '--spec',
    'spec_path',
    type=click.Path(exists=True),
    default=None,
    help='Path to spec file (default: recipe_dir/spec.md)'
)
@click.option(
    '--force', '-f',
    is_flag=True,
    help='Overwrite existing recipe.md and script'
)
def create_recipe(name: str, prompt: str | None, prompt_file: str | None, spec_path: str | None, force: bool):
    """
    Create a recipe via agent from spec or prompt

    Two modes:
    1. From spec: reads spec.md and generates recipe code
    2. One-step: --prompt creates spec + code in one pass

    \b
    Examples:
      frago recipe create my_scraper
      frago recipe create my_tool --prompt "打印 hello world"
      frago recipe create my_tool --spec /path/to/spec.md
    """
    from frago.recipes.registry import get_registry, invalidate_registry

    # Determine spec source
    if prompt or prompt_file:
        # One-step mode
        user_prompt = prompt if prompt else Path(prompt_file).read_text(encoding='utf-8').strip()
        spec_content = None
        recipe_dir = _find_recipe_dir_by_name(name) or _resolve_recipe_dir(name, None, None)
    else:
        # Two-step mode: read from spec.md
        user_prompt = None
        recipe_dir = _find_recipe_dir_by_name(name)

        resolved_spec = Path(spec_path) if spec_path else (recipe_dir / "spec.md" if recipe_dir else None)
        if not resolved_spec or not resolved_spec.exists():
            click.echo(f"Error: No spec found for recipe '{name}'", err=True)
            click.echo(f"[Fix] Run 'frago recipe plan {name} --prompt \"...\"' first, or use --prompt for direct creation", err=True)
            sys.exit(1)

        spec_content = resolved_spec.read_text(encoding='utf-8')
        if not recipe_dir:
            recipe_dir = resolved_spec.parent

    # Check conflict
    if recipe_dir and (recipe_dir / "recipe.md").exists() and not force:
        click.echo(f"Error: recipe.md already exists at {recipe_dir / 'recipe.md'}", err=True)
        click.echo("[Fix] Use --force to overwrite", err=True)
        sys.exit(1)

    # Ensure directory exists
    recipe_dir.mkdir(parents=True, exist_ok=True)

    # Build agent prompt
    if spec_content:
        agent_prompt = f"""你是 frago recipe 开发专家。

任务：根据 spec 创建 recipe '{name}'。

先运行以下命令获取规范：
  uv run frago book recipe-creation

Spec 内容（位于 {resolved_spec}）：
{spec_content}

创建 recipe.md 和对应脚本文件到 {recipe_dir}/。
创建完成后，运行 uv run frago recipe validate {recipe_dir}。
如果 validate 失败，根据错误信息修复后重试，最多 3 轮。
"""
    else:
        agent_prompt = f"""你是 frago recipe 开发专家。

任务：创建 recipe '{name}'。

先运行以下命令获取规范：
  uv run frago book recipe-spec-writing
  uv run frago book recipe-creation

用户需求：
{user_prompt}

先在 {recipe_dir}/ 写 spec.md，再创建 recipe.md 和脚本文件。
创建完成后，运行 uv run frago recipe validate {recipe_dir}。
如果 validate 失败，根据错误信息修复后重试，最多 3 轮。
"""

    click.echo(f"[Create] Creating recipe '{name}'...")
    click.echo(f"  Directory: {recipe_dir}")

    exit_code = _run_frago_agent(agent_prompt)

    if exit_code != 0:
        click.echo("Error: Agent failed to create recipe", err=True)
        sys.exit(1)

    # Refresh registry and verify
    invalidate_registry()
    registry = get_registry()
    try:
        registry.find(name)
        click.echo(f"[OK] Recipe '{name}' created successfully")
        click.echo(f"  frago recipe info {name}")
        click.echo(f"  frago recipe run {name} --params '{{...}}'")
    except Exception:
        click.echo(f"Warning: recipe '{name}' not found in registry after creation", err=True)
        click.echo(f"Check the files in {recipe_dir}", err=True)
        sys.exit(1)


@recipe_group.command(name='list', cls=AgentFriendlyCommand)
@click.option(
    '--source',
    type=click.Choice(['user', 'community', 'official', 'all'], case_sensitive=False),
    default='all',
    help='Filter by source (user | community | official | all)'
)
@click.option(
    '--type',
    'recipe_type',
    type=click.Choice(['atomic', 'workflow', 'all'], case_sensitive=False),
    default='all',
    help='Filter by type'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json', 'names'], case_sensitive=False),
    default='table',
    help='Output format'
)
def list_recipes(source: str, recipe_type: str, output_format: str):
    """List all available recipes"""
    try:
        registry = RecipeRegistry()
        registry.scan()

        # Filter recipes
        recipes = registry.get_by_source(source) if source != 'all' else registry.list_all()

        if recipe_type != 'all':
            recipes = [r for r in recipes if r.metadata.type == recipe_type]

        # Output
        if output_format == 'json':
            # AI-friendly JSON output
            output = [
                {
                    "name": r.metadata.name,
                    "type": r.metadata.type,
                    "runtime": r.metadata.runtime,
                    "description": r.metadata.description,
                    "use_cases": r.metadata.use_cases,
                    "tags": r.metadata.tags,
                    "output_targets": r.metadata.output_targets,
                    "version": r.metadata.version,
                    "source": r.source,
                    "path": str(r.script_path)
                }
                for r in recipes
            ]
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        elif output_format == 'names':
            for r in recipes:
                click.echo(r.metadata.name)
        else:  # table
            if not recipes:
                click.echo("No recipes found")
                return

            # Table output
            click.echo(f"{'SOURCE':<10} {'TYPE':<10} {'NAME':<40} {'RUNTIME':<10} {'VERSION':<8}")
            click.echo("-" * 80)
            for r in recipes:
                click.echo(
                    f"{r.source:<10} {r.metadata.type:<10} {r.metadata.name:<40} "
                    f"{r.metadata.runtime:<10} {r.metadata.version:<8}"
                )

            # Check for recipes with the same name
            recipe_names = [r.metadata.name for r in recipes]
            duplicates = []
            for recipe_name in set(recipe_names):
                all_sources = registry.find_all_sources(recipe_name)
                if len(all_sources) > 1:
                    duplicates.append((recipe_name, [s for s, _ in all_sources]))

            if duplicates:
                click.echo()
                click.echo("Note: The following recipes exist in multiple sources (using higher priority):")
                for name, sources in duplicates:
                    click.echo(f"  - {name}: {' > '.join(sources)}")

            click.echo()
            click.echo("Next: recipe info <name> | recipe run <name>")

    except RecipeError as e:
        click.echo(f"Error: {e}", err=True)


@recipe_group.command(name='info', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option(
    '--source',
    type=click.Choice(['user', 'community', 'official'], case_sensitive=False),
    default=None,
    help='Specify recipe source (defaults to auto-select by priority)'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json', 'yaml'], case_sensitive=False),
    default='text',
    help='Output format'
)
def recipe_info(name: str, source: str | None, output_format: str):
    """Display detailed information about a specific recipe"""
    try:
        registry = RecipeRegistry()
        registry.scan()
        recipe = registry.find(name, source=source)

        if output_format == 'json':
            # Get list of example files
            examples = [str(e.name) for e in recipe.list_examples()]

            output = {
                "name": recipe.metadata.name,
                "type": recipe.metadata.type,
                "runtime": recipe.metadata.runtime,
                "version": recipe.metadata.version,
                "source": recipe.source,
                "base_dir": str(recipe.base_dir) if recipe.base_dir else None,
                "script_path": str(recipe.script_path),
                "metadata_path": str(recipe.metadata_path),
                "description": recipe.metadata.description,
                "use_cases": recipe.metadata.use_cases,
                "tags": recipe.metadata.tags,
                "output_targets": recipe.metadata.output_targets,
                "inputs": recipe.metadata.inputs,
                "outputs": recipe.metadata.outputs,
                "dependencies": recipe.metadata.dependencies,
                "secrets": recipe.metadata.secrets,
                "flow": recipe.metadata.flow,
                "examples": examples,
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        else:  # text
            m = recipe.metadata
            click.echo(f"Recipe: {m.name}")
            click.echo("=" * 50)
            click.echo()
            click.echo("Basic Information")
            click.echo("-" * 50)
            click.echo(f"Name:     {m.name}")
            click.echo(f"Type:     {m.type}")
            click.echo(f"Runtime:  {m.runtime}")
            click.echo(f"Version:  {m.version}")
            click.echo(f"Source:   {recipe.source}")

            # Check if there are recipes with the same name in other sources
            all_sources = registry.find_all_sources(name)
            if len(all_sources) > 1:
                other_sources = [s for s, _ in all_sources if s != recipe.source]
                if other_sources:
                    click.echo(f"          (Recipe with same name also exists in: {', '.join(other_sources)})")

            click.echo(f"Path:     {recipe.script_path}")
            click.echo()
            click.echo("Description")
            click.echo("-" * 50)
            click.echo(m.description)
            click.echo()
            if m.use_cases:
                click.echo("Use Cases")
                click.echo("-" * 50)
                for case in m.use_cases:
                    click.echo(f"- {case}")
                click.echo()
            if m.tags:
                click.echo("Tags")
                click.echo("-" * 50)
                click.echo(", ".join(m.tags))
                click.echo()
            click.echo("Output Targets")
            click.echo("-" * 50)
            click.echo(", ".join(m.output_targets))
            click.echo()
            if m.inputs:
                click.echo("Input Parameters")
                click.echo("-" * 50)
                for param_name, param_def in m.inputs.items():
                    required = "required" if param_def.get('required', False) else "optional"
                    param_type = param_def.get('type', 'unknown')
                    desc = param_def.get('description', '')
                    click.echo(f"- {param_name} ({param_type}, {required}): {desc}")
                click.echo()
            if m.dependencies:
                click.echo("Dependencies")
                click.echo("-" * 50)
                click.echo(", ".join(m.dependencies))
                click.echo()
            else:
                click.echo("Dependencies")
                click.echo("-" * 50)
                click.echo("None")
                click.echo()

            # Display example files
            examples = recipe.list_examples()
            click.echo("Example Files")
            click.echo("-" * 50)
            if examples:
                for example in examples:
                    click.echo(f"- {example.name}")
            else:
                click.echo("None")

    except RecipeError as e:
        click.echo(f"Error: {e}", err=True)


@recipe_group.command(name='run', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option(
    '--source',
    type=click.Choice(['user', 'community', 'official'], case_sensitive=False),
    default=None,
    help='Specify recipe source (defaults to auto-select by priority)'
)
@click.option(
    '--params',
    type=str,
    default='{}',
    help='JSON format parameter string'
)
@click.option(
    '--params-file',
    type=click.Path(exists=True),
    help='Read parameters from file (JSON format)'
)
@click.option(
    '--env', '-e',
    'env_vars',
    multiple=True,
    help='Environment variable override, format: KEY=VALUE (can be used multiple times)'
)
@click.option(
    '--output-file',
    type=click.Path(),
    help='Write result to file'
)
@click.option(
    '--output-clipboard',
    is_flag=True,
    help='Copy result to clipboard'
)
@click.option(
    '--timeout',
    type=int,
    default=300,
    help='Execution timeout (seconds)'
)
@click.option(
    '--async', 'async_exec',
    is_flag=True,
    help='Run in background, print execution_id'
)
def run_recipe(
    name: str,
    source: str | None,
    params: str,
    params_file: str | None,
    env_vars: tuple,
    output_file: str | None,
    output_clipboard: bool,
    timeout: int,
    async_exec: bool,
):
    """Execute specified recipe"""
    try:
        # Parse parameters
        if params_file:
            with open(params_file, encoding='utf-8') as f:
                params_dict = json.load(f)
        else:
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError as e:
                click.echo(f"Error: Invalid parameter format\n{e}", err=True)
                sys.exit(2)

        # Parse environment variable overrides
        env_overrides: dict[str, str] = {}
        for env_var in env_vars:
            if '=' not in env_var:
                click.echo(f"Error: Invalid environment variable format: '{env_var}' (should be KEY=VALUE)", err=True)
                sys.exit(2)
            key, value = env_var.split('=', 1)
            env_overrides[key] = value

        # Async execution: submit to background, print execution_id, return
        if async_exec:
            runner = RecipeRunner()
            execution_id = runner.run_async(
                name,
                params_dict,
                source=source,
                timeout=timeout,
            )
            click.echo(execution_id)
            click.echo(f"Started: {execution_id}", err=True)
            return

        # Determine output target
        if output_clipboard:
            output_target = 'clipboard'
            output_options = {}
        elif output_file:
            output_target = 'file'
            output_options = {'path': output_file}
        else:
            output_target = 'stdout'
            output_options = {}

        # Execute recipe
        runner = RecipeRunner()
        result = runner.run(
            name,
            params_dict,
            output_target,
            output_options,
            env_overrides=env_overrides if env_overrides else None,
            source=source
        )

        # Output stderr (logs during script execution)
        stderr_output = result.get('stderr', '')
        if stderr_output:
            click.echo("--- Recipe Logs ---", err=True)
            click.echo(stderr_output, err=True)
            click.echo("--- End Logs ---", err=True)

        # Execution summary to stderr (human-readable, doesn't pollute stdout)
        exec_id = result.get('execution_id', '')
        click.echo(
            f"[recipe] {result.get('recipe_name', name)} | "
            f"{exec_id + ' | ' if exec_id else ''}"
            f"{'OK' if result.get('success') else 'FAIL'} | "
            f"{result.get('execution_time', 0):.1f}s",
            err=True
        )

        # Handle output (stdout/file/clipboard now only contain recipe data)
        if output_target == 'stdout':
            OutputHandler.handle(result, 'stdout')
        elif output_target == 'file':
            OutputHandler.handle(result, 'file', output_options)
            if result.get('success'):
                click.echo(f"[OK] Result saved to: {output_file}", err=True)
        elif output_target == 'clipboard':
            OutputHandler.handle(result, 'clipboard')
            if result.get('success'):
                click.echo("[OK] Result copied to clipboard", err=True)

        # If execution fails, return non-zero exit code
        if not result.get('success'):
            click.echo("Recipe execution failed", err=True)
            sys.exit(1)

    except RecipeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _parse_interval(value: str) -> int:
    """Parse interval string to seconds.

    Supports: "30s", "10m", "2h", "1h30m", "600" (pure number = seconds).
    Minimum: 10 seconds.
    """
    import re
    value = value.strip()

    # Pure number → seconds
    if value.isdigit():
        seconds = int(value)
    else:
        match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', value)
        if not match or not any(match.groups()):
            raise click.BadParameter(f"Invalid interval format: '{value}'. Use e.g. 30s, 10m, 2h, 1h30m")
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        secs = int(match.group(3) or 0)
        seconds = hours * 3600 + minutes * 60 + secs

    if seconds < 10:
        raise click.BadParameter(f"Interval too short ({seconds}s). Minimum is 10 seconds.")
    return seconds


def _parse_datetime(value: str):  # -> datetime.datetime
    """Parse datetime string. Supports ISO 8601 and HH:MM."""
    from datetime import datetime, timedelta

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(value, fmt).time()
            today = datetime.now().replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
            if today <= datetime.now():
                today = today + timedelta(days=1)
            return today
        except ValueError:
            continue

    raise click.BadParameter(f"Cannot parse datetime: '{value}'. Use ISO 8601 or HH:MM format.")


@recipe_group.command(name='schedule', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option('--interval', required=True, help='Run interval (e.g., 30s, 10m, 2h, 1h30m)')
@click.option('--params', type=str, default='{}', help='Recipe parameters (JSON)')
@click.option('--params-file', type=click.Path(exists=True), help='Read parameters from file')
@click.option('--source', type=click.Choice(['user', 'community', 'official']), default=None, help='Recipe source')
@click.option('--env', '-e', 'env_vars', multiple=True, help='Env override KEY=VALUE')
@click.option('--start-at', 'start_at', help='Start time (ISO 8601 or HH:MM), default: now')
@click.option('--stop-at', 'stop_at', help='Stop time (ISO 8601 or HH:MM), default: never')
@click.option('--max-runs', type=int, help='Max number of runs, then exit')
@click.option('--timeout', type=int, default=300, help='Per-execution timeout (seconds)')
def schedule_recipe(
    name: str,
    interval: str,
    params: str,
    params_file: str | None,
    source: str | None,
    env_vars: tuple,
    start_at: str | None,
    stop_at: str | None,
    max_runs: int | None,
    timeout: int,
):
    """Run a recipe repeatedly at fixed intervals.

    Runs in the foreground. Press Ctrl+C to stop.

    Examples:

        frago recipe schedule price_check --interval 10m

        frago recipe schedule backup --interval 1h --stop-at "2026-03-19 08:00"

        frago recipe schedule poll_api --interval 30s --max-runs 100
    """
    import signal
    import time
    from datetime import datetime

    # Parse interval
    interval_seconds = _parse_interval(interval)

    # Parse params
    if params_file:
        with open(params_file, encoding='utf-8') as f:
            params_dict = json.load(f)
    else:
        try:
            params_dict = json.loads(params)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid parameter format\n{e}", err=True)
            sys.exit(2)

    # Parse env overrides
    env_overrides: dict[str, str] = {}
    for env_var in env_vars:
        if '=' not in env_var:
            click.echo(f"Error: Invalid env format: '{env_var}' (use KEY=VALUE)", err=True)
            sys.exit(2)
        key, value = env_var.split('=', 1)
        env_overrides[key] = value

    # Parse time bounds
    start_dt = _parse_datetime(start_at) if start_at else None
    stop_dt = _parse_datetime(stop_at) if stop_at else None

    # Wait for start_at
    if start_dt:
        wait = (start_dt - datetime.now()).total_seconds()
        if wait > 0:
            click.echo(f"[schedule] waiting until {start_dt.isoformat()}", err=True)
            time.sleep(wait)

    # Schedule loop
    runner = RecipeRunner()
    run_count = 0
    ok_count = 0
    fail_count = 0
    interrupted = False

    def handle_sigint(_sig, _frame):
        nonlocal interrupted
        interrupted = True

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_sigint)

    click.echo(
        f"[schedule] {name} | interval={interval} | "
        f"start={'now' if not start_dt else start_dt.isoformat()} | "
        f"stop={'never' if not stop_dt else stop_dt.isoformat()}"
        f"{f' | max_runs={max_runs}' if max_runs else ''}",
        err=True
    )

    try:
        while not interrupted:
            # Check stop_at
            if stop_dt and datetime.now() >= stop_dt:
                click.echo("[schedule] stop time reached", err=True)
                break

            # Check max_runs
            if max_runs and run_count >= max_runs:
                click.echo(f"[schedule] max runs ({max_runs}) reached", err=True)
                break

            run_count += 1
            click.echo(f"[schedule] #{run_count} started at {datetime.now().strftime('%H:%M:%S')}", err=True)

            try:
                result = runner.run(
                    name,
                    params_dict,
                    env_overrides=env_overrides if env_overrides else None,
                    source=source,
                    timeout=timeout,
                )
                success = result.get('success', False)
                if success:
                    ok_count += 1
                else:
                    fail_count += 1

                stderr_output = result.get('stderr', '')
                if stderr_output:
                    click.echo(stderr_output, err=True)

                exec_id = result.get('execution_id', '')
                click.echo(
                    f"[recipe] {name} | {exec_id + ' | ' if exec_id else ''}"
                    f"{'OK' if success else 'FAIL'} | "
                    f"{result.get('execution_time', 0):.1f}s",
                    err=True
                )
            except Exception as e:
                fail_count += 1
                click.echo(f"[schedule] #{run_count} error: {e}", err=True)

            # Sleep until next run (interruptible, 1s granularity)
            if not interrupted:
                next_time = time.time() + interval_seconds
                if stop_dt:
                    stop_ts = stop_dt.timestamp()
                    if next_time > stop_ts:
                        remaining = stop_ts - time.time()
                        if remaining > 0:
                            click.echo("[schedule] final wait until stop time", err=True)
                            while not interrupted and time.time() < stop_ts:
                                time.sleep(min(1.0, stop_ts - time.time()))
                        break

                next_str = datetime.fromtimestamp(next_time).strftime('%H:%M:%S')
                click.echo(f"[schedule] next run at {next_str}", err=True)
                while not interrupted and time.time() < next_time:
                    time.sleep(min(1.0, next_time - time.time()))
    finally:
        signal.signal(signal.SIGINT, original_handler)

    click.echo(
        f"[schedule] {'interrupted' if interrupted else 'completed'}, "
        f"{run_count} runs ({ok_count} ok, {fail_count} failed)",
        err=True
    )


@recipe_group.command(name='executions', cls=AgentFriendlyCommand)
@click.option(
    '--recipe',
    'recipe_name',
    type=str,
    default=None,
    help='Filter by recipe name'
)
@click.option(
    '--limit',
    type=int,
    default=20,
    help='Max results (default 20)'
)
@click.option(
    '--status',
    type=click.Choice(['pending', 'running', 'succeeded', 'failed', 'timeout', 'cancelled'], case_sensitive=False),
    default=None,
    help='Filter by status'
)
@click.option(
    '--workflow',
    'workflow_id',
    type=str,
    default=None,
    help='Filter by parent workflow execution ID'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json'], case_sensitive=False),
    default='table',
    help='Output format'
)
def list_executions(recipe_name: str | None, limit: int, status: str | None, workflow_id: str | None, output_format: str):
    """List recent recipe executions"""
    from frago.recipes.execution import ExecutionStatus
    from frago.recipes.execution_store import ExecutionStore

    store = ExecutionStore()
    if workflow_id:
        executions = store.list_by_workflow(workflow_id)
    else:
        status_filter = ExecutionStatus(status) if status else None
        executions = store.list_recent(recipe_name=recipe_name, limit=limit, status=status_filter)

    if output_format == 'json':
        output = [e.to_dict() for e in executions]
        click.echo(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if not executions:
            click.echo("No executions found")
            return

        click.echo(f"{'ID':<20} {'RECIPE':<25} {'STATUS':<12} {'DURATION':<10} {'CREATED'}")
        click.echo("-" * 90)
        for e in executions:
            duration = f"{e.duration_ms}ms" if e.duration_ms is not None else "-"
            created = e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "-"
            click.echo(f"{e.id:<20} {e.recipe_name:<25} {e.status.value:<12} {duration:<10} {created}")


@recipe_group.command(name='execution', cls=AgentFriendlyCommand)
@click.argument('execution_id')
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='Output format'
)
def show_execution(execution_id: str, output_format: str):
    """Show details of a specific execution"""
    from frago.recipes.execution_store import ExecutionStore

    store = ExecutionStore()
    execution = store.get(execution_id)

    if execution is None:
        click.echo(f"Error: Execution '{execution_id}' not found", err=True)
        sys.exit(1)

    if output_format == 'json':
        click.echo(json.dumps(execution.to_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(f"Execution: {execution.id}")
        click.echo("=" * 50)
        click.echo(f"Recipe:     {execution.recipe_name}")
        click.echo(f"Status:     {execution.status.value}")
        click.echo(f"Runtime:    {execution.runtime or '-'}")
        click.echo(f"Source:     {execution.source or '-'}")
        click.echo(f"Created:    {execution.created_at}")
        click.echo(f"Started:    {execution.started_at or '-'}")
        click.echo(f"Completed:  {execution.completed_at or '-'}")
        click.echo(f"Duration:   {execution.duration_ms}ms" if execution.duration_ms is not None else "Duration:   -")
        click.echo(f"Exit code:  {execution.exit_code}" if execution.exit_code is not None else "Exit code:  -")
        if execution.timeout_seconds:
            click.echo(f"Timeout:    {execution.timeout_seconds}s")
        if execution.workflow_id:
            click.echo(f"Workflow:   {execution.workflow_id}")
        if execution.step_index is not None:
            click.echo(f"Step:       {execution.step_index}")
        if execution.params:
            click.echo()
            click.echo("Parameters")
            click.echo("-" * 50)
            click.echo(json.dumps(execution.params, ensure_ascii=False, indent=2))
        if execution.data:
            click.echo()
            click.echo("Data")
            click.echo("-" * 50)
            click.echo(json.dumps(execution.data, ensure_ascii=False, indent=2))
        if execution.error:
            click.echo()
            click.echo("Error")
            click.echo("-" * 50)
            click.echo(json.dumps(execution.error, ensure_ascii=False, indent=2))


@recipe_group.command(name='cancel', cls=AgentFriendlyCommand)
@click.argument('execution_id')
def cancel_execution(execution_id: str):
    """Cancel a running execution"""
    from frago.recipes.runner import RecipeRunner

    runner = RecipeRunner()
    cancelled = runner.cancel(execution_id)

    if cancelled:
        click.echo(f"Cancelled: {execution_id}", err=True)
    else:
        click.echo(f"Error: Execution '{execution_id}' not found or already finished", err=True)
        sys.exit(1)


_SECRET_ENV_PATTERN = re.compile(
    r'''os\.environ(?:\.get)?\s*[\[(]\s*['"]([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|ACCESS_KEY))['"]''',
    re.IGNORECASE,
)
_SECRET_ENV_PATTERN_SHELL = re.compile(r'\$\{?([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|ACCESS_KEY))\}?')
_PARAMS_SECRETS_PATTERN = re.compile(r'''params\s*(?:\.get\s*\(\s*['"]secrets['"]|\[\s*['"]secrets['"]\s*\])''')


def _scan_secrets_usage(content: str, metadata) -> list[str]:
    """Scan recipe script for non-standard secrets usage.

    Enforces FRAGO_SECRETS as the only channel (see book recipe-authoring):
      - params["secrets"] / params.get("secrets") is never populated by runner
      - Hardcoded *_API_KEY / *_TOKEN / *_SECRET env reads bypass the profile system
      - If recipe.md declares secrets:, script must reference FRAGO_SECRETS
    """
    errors: list[str] = []
    has_secrets_schema = bool(getattr(metadata, 'secrets', None))
    uses_frago_secrets = 'FRAGO_SECRETS' in content

    if _PARAMS_SECRETS_PATTERN.search(content):
        errors.append(
            "Secrets must not be read from params (found params[\"secrets\"] or params.get(\"secrets\")). "
            "Runner injects secrets via FRAGO_SECRETS env var only. "
            "See: frago book recipe-authoring"
        )

    pattern = _SECRET_ENV_PATTERN if metadata.runtime == 'python' else _SECRET_ENV_PATTERN_SHELL
    hardcoded = {m.group(1) for m in pattern.finditer(content) if m.group(1) != 'FRAGO_SECRETS'}
    if hardcoded:
        names = ', '.join(sorted(hardcoded))
        errors.append(
            f"Recipe-specific env vars are not supported: {names}. "
            f"Declare credentials in recipe.md 'secrets:' and read via json.loads(os.environ['FRAGO_SECRETS']). "
            f"See: frago book recipe-authoring"
        )

    if has_secrets_schema and not uses_frago_secrets:
        errors.append(
            "recipe.md declares 'secrets:' but script never references FRAGO_SECRETS. "
            "Read credentials via json.loads(os.environ.get('FRAGO_SECRETS', '{}')). "
            "See: frago book recipe-authoring"
        )

    return errors


@recipe_group.command('validate', cls=AgentFriendlyCommand)
@click.argument('path', type=click.Path(exists=True))
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='Output format'
)
def validate_recipe(path: str, output_format: str):
    """
    Validate field completeness and correctness of recipe directory

    PATH can be:
    - Recipe directory path (containing recipe.md and script file)
    - recipe.md file path
    """
    recipe_path = Path(path)

    # Determine recipe.md and recipe directory
    if recipe_path.is_file():
        if recipe_path.name != 'recipe.md':
            click.echo(f"Error: Specified file is not recipe.md: {recipe_path.name}", err=True)
            return
        metadata_path = recipe_path
        recipe_dir = recipe_path.parent
    else:
        # Directory form
        metadata_path = recipe_path / 'recipe.md'
        recipe_dir = recipe_path
        if not metadata_path.exists():
            click.echo(f"Error: recipe.md not found in recipe directory: {recipe_dir}", err=True)
            return

    errors: list[str] = []
    warnings: list[str] = []
    metadata = None

    # 1. Parse metadata
    try:
        metadata = parse_metadata_file(metadata_path)
    except MetadataParseError as e:
        errors.append(f"Metadata parsing failed: {e.reason}")

    # 2. Validate metadata fields
    if metadata:
        try:
            validate_metadata(metadata)
        except RecipeValidationError as e:
            errors.extend(e.errors)

    # 3. Check script file
    if metadata:
        script_extensions = {
            'chrome-js': '.js',
            'python': '.py',
            'shell': '.sh'
        }
        ext = script_extensions.get(metadata.runtime, '')
        script_path = recipe_dir / f"recipe{ext}"

        if not script_path.exists():
            errors.append(f"Script file does not exist: recipe{ext} (runtime: {metadata.runtime})")
        else:
            # Check if script is empty
            content = script_path.read_text(encoding='utf-8').strip()
            if not content:
                errors.append(f"Script file is empty: recipe{ext}")

            # Check basic script syntax (optional simple check)
            if metadata.runtime == 'python':
                try:
                    compile(content, str(script_path), 'exec')
                except SyntaxError as e:
                    errors.append(f"Python syntax error: {e.msg} (line {e.lineno})")
            elif metadata.runtime == 'chrome-js' and 'return' not in content and 'console' not in content:
                    warnings.append("JavaScript script does not contain return statement or console output")

            # 3.5 Scan secrets usage — enforce FRAGO_SECRETS as the only channel
            if metadata.runtime in ('python', 'shell'):
                secrets_errors = _scan_secrets_usage(content, metadata)
                errors.extend(secrets_errors)

    # 4. Check examples directory (optional)
    examples_dir = recipe_dir / 'examples'
    if examples_dir.exists():
        example_files = list(examples_dir.glob('*'))
        if not example_files:
            warnings.append("examples directory exists but is empty")

    # 5. Check dependencies (if workflow)
    if metadata and metadata.type == 'workflow' and metadata.dependencies:
        registry = RecipeRegistry()
        registry.scan()
        for dep in metadata.dependencies:
            if dep not in registry.recipes:
                errors.append(f"Dependent recipe does not exist: {dep}")

    # 6. Check flow field (if workflow)
    if metadata and metadata.type == 'workflow':
        if not metadata.flow:
            errors.append("Workflow recipes must include a 'flow' field describing execution steps")
        else:
            seen_steps = set()
            for i, step in enumerate(metadata.flow):
                step_num = step.get('step')
                if step_num is None:
                    errors.append(f"Flow step {i+1}: missing 'step' number")
                elif step_num in seen_steps:
                    errors.append(f"Flow step {step_num}: duplicate step number")
                else:
                    seen_steps.add(step_num)

                if not step.get('action'):
                    errors.append(f"Flow step {step_num or i+1}: missing 'action'")
                if not step.get('description'):
                    errors.append(f"Flow step {step_num or i+1}: missing 'description'")

                # Verify recipe references exist in dependencies
                if step.get('recipe') and (not metadata.dependencies or step['recipe'] not in metadata.dependencies):
                        errors.append(f"Flow step {step_num}: recipe '{step['recipe']}' not in dependencies")

    # Output results
    is_valid = len(errors) == 0

    if output_format == 'json':
        result = {
            "valid": is_valid,
            "path": str(recipe_dir),
            "name": metadata.name if metadata else None,
            "type": metadata.type if metadata else None,
            "runtime": metadata.runtime if metadata else None,
            "errors": errors,
            "warnings": warnings,
        }
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # text format
        if is_valid:
            click.echo(f"[OK] Recipe validation passed: {recipe_dir}")
            if metadata:
                click.echo(f"  Name: {metadata.name}")
                click.echo(f"  Type: {metadata.type}")
                click.echo(f"  Runtime: {metadata.runtime}")
            if warnings:
                click.echo()
                click.echo("[!] Warnings:")
                for w in warnings:
                    click.echo(f"  - {w}")
        else:
            click.echo(f"[X] Recipe validation failed: {recipe_dir}", err=True)
            click.echo()
            click.echo("Errors:")
            for e in errors:
                click.echo(f"  - {e}", err=True)
            if warnings:
                click.echo()
                click.echo("Warnings:")
                for w in warnings:
                    click.echo(f"  - {w}")


@recipe_group.command(name='install', cls=AgentFriendlyCommand)
@click.argument('source')
@click.option(
    '--force', '-f',
    is_flag=True,
    help='Overwrite existing recipe if it exists'
)
@click.option(
    '--name',
    'name_override',
    type=str,
    default=None,
    help='Override the recipe name'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='Output format'
)
def install_recipe(source: str, force: bool, name_override: str | None, output_format: str):
    """
    Install a recipe from various sources

    SOURCE can be:

    \b
    - community:<name>     Install from frago community recipes
    - /path/to/recipe      Install from local directory

    \b
    Examples:
      frago recipe install community:stock-monitor
      frago recipe install /path/to/recipe --name custom-name
      frago recipe install community:stock-monitor --force
    """
    from frago.recipes.exceptions import RecipeAlreadyExistsError, RecipeInstallError
    from frago.recipes.installer import RecipeInstaller

    try:
        installer = RecipeInstaller()
        recipe_name = installer.install(source, force=force, name_override=name_override)

        if output_format == 'json':
            result = {
                "success": True,
                "recipe_name": recipe_name,
                "source": source,
            }
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"[OK] Recipe '{recipe_name}' installed successfully")
            click.echo(f"  Source: {source}")
            click.echo()
            click.echo(f"Run 'frago recipe info {recipe_name}' to see details")

    except RecipeAlreadyExistsError as e:
        if output_format == 'json':
            result = {"success": False, "error": str(e), "code": "already_exists"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    except RecipeInstallError as e:
        if output_format == 'json':
            result = {"success": False, "error": str(e), "code": "install_error"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    except RecipeError as e:
        if output_format == 'json':
            result = {"success": False, "error": str(e), "code": "error"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@recipe_group.command(name='uninstall', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option(
    '--yes', '-y',
    is_flag=True,
    help='Skip confirmation prompt'
)
@click.option(
    '--source',
    type=click.Choice(['user', 'community'], case_sensitive=False),
    default=None,
    help='Specify source to uninstall when recipe exists in multiple sources'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='Output format'
)
def uninstall_recipe(name: str, yes: bool, source: str | None, output_format: str):
    """
    Uninstall a recipe (User or Community)

    Supports all sources via registry lookup. Official recipes cannot be uninstalled.
    Checks for dependent recipes before deletion.

    \b
    Examples:
      frago recipe uninstall stock-monitor
      frago recipe uninstall stock-monitor --yes
      frago recipe uninstall my-tool --source user
    """
    from frago.recipes.registry import get_registry, invalidate_registry

    registry = get_registry()

    # Check if recipe exists
    if name not in registry.recipes:
        if output_format == 'json':
            result = {"success": False, "error": f"Recipe '{name}' not found", "code": "not_found"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: Recipe '{name}' not found", err=True)
            click.echo("[Fix] frago recipe list --format names", err=True)
        sys.exit(1)

    sources_dict = registry.recipes[name]

    # Determine target source
    if source:
        source_label = source.capitalize()
        if source_label not in sources_dict:
            if output_format == 'json':
                result = {"success": False, "error": f"Recipe '{name}' not found in {source}", "code": "not_found"}
                click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                available = ", ".join(sources_dict.keys())
                click.echo(f"Error: Recipe '{name}' not found in {source}. Available: {available}", err=True)
            sys.exit(1)
    else:
        # Auto-select: User > Community, skip Official
        source_label = None
        for s in ['User', 'Community']:
            if s in sources_dict:
                source_label = s
                break
        if not source_label:
            if output_format == 'json':
                result = {"success": False, "error": f"Recipe '{name}' is Official and cannot be uninstalled", "code": "official"}
                click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                click.echo(f"Error: Recipe '{name}' is an Official recipe and cannot be uninstalled", err=True)
            sys.exit(1)

    # Official guard
    if source_label == 'Official':
        if output_format == 'json':
            result = {"success": False, "error": "Cannot uninstall Official recipe", "code": "official"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: Cannot uninstall Official recipe '{name}'. It is bundled with frago.", err=True)
        sys.exit(1)

    # Dependency check
    dependents = _check_dependents(name, registry)
    if dependents:
        dep_list = "\n".join(f"  - {dep}" for dep in dependents)
        if output_format == 'json':
            result = {"success": False, "error": f"Depended on by: {', '.join(dependents)}", "code": "has_dependents", "dependents": dependents}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: Cannot uninstall '{name}': depended on by:", err=True)
            click.echo(dep_list, err=True)
            click.echo("\nUninstall or update these recipes first.", err=True)
        sys.exit(1)

    # Confirm
    if not yes and output_format != 'json' and not click.confirm(f"Uninstall recipe '{name}' ({source_label})?"):
        click.echo("Cancelled")
        return

    # Delete
    recipe = sources_dict[source_label]
    recipe_dir = recipe.base_dir or recipe.metadata_path.parent
    shutil.rmtree(recipe_dir)

    # Clean up community manifest if needed
    if source_label == 'Community':
        try:
            from frago.recipes.installer import RecipeInstaller
            installer = RecipeInstaller()
            if name in installer.manifest.recipes:
                del installer.manifest.recipes[name]
                installer._save_manifest()
        except Exception:
            pass  # Non-fatal: directory already deleted

    invalidate_registry()

    if output_format == 'json':
        result = {"success": True, "recipe_name": name, "source": source_label}
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"[OK] Recipe '{name}' ({source_label}) uninstalled")


def _check_dependents(name: str, registry: RecipeRegistry) -> list[str]:
    """Find all recipes that depend on the given recipe name."""
    dependents = []
    for recipe_name, sources in registry.recipes.items():
        for source_label, recipe in sources.items():
            deps = getattr(recipe.metadata, 'dependencies', []) or []
            if name in deps:
                dependents.append(f"{recipe_name} ({source_label})")
    return dependents


@recipe_group.command(name='update', cls=AgentFriendlyCommand)
@click.argument('name', required=False)
@click.option(
    '--all', 'update_all',
    is_flag=True,
    help='Update all installed recipes'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='Output format'
)
def update_recipe(name: str | None, update_all: bool, output_format: str):
    """
    Update installed recipes by re-fetching from original source

    \b
    Examples:
      frago recipe update stock-monitor
      frago recipe update --all
    """
    from frago.recipes.exceptions import RecipeInstallError
    from frago.recipes.installer import RecipeInstaller

    if not name and not update_all:
        click.echo("Error: Specify a recipe name or use --all", err=True)
        sys.exit(1)

    installer = RecipeInstaller()

    if update_all:
        # Update all installed recipes
        results = installer.update_all()
        if output_format == 'json':
            output = {
                "success": all(r[1] for r in results),
                "results": [
                    {"name": r[0], "success": r[1], "message": r[2]}
                    for r in results
                ]
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not results:
                click.echo("No installed recipes to update")
                return

            success_count = sum(1 for r in results if r[1])
            fail_count = len(results) - success_count

            for recipe_name, success, message in results:
                if success:
                    click.echo(f"[OK] {recipe_name}: {message}")
                else:
                    click.echo(f"[X] {recipe_name}: {message}", err=True)

            click.echo()
            click.echo(f"Updated: {success_count}, Failed: {fail_count}")
    else:
        # Update single recipe
        try:
            installer.update(name)
            if output_format == 'json':
                result = {"success": True, "recipe_name": name}
                click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                click.echo(f"[OK] Recipe '{name}' updated successfully")
        except RecipeInstallError as e:
            if output_format == 'json':
                result = {"success": False, "error": str(e), "code": "update_error"}
                click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                click.echo(f"Error: {e}", err=True)
            sys.exit(1)


@recipe_group.command(name='search', cls=AgentFriendlyCommand)
@click.argument('query', required=False)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json'], case_sensitive=False),
    default='table',
    help='Output format'
)
def search_recipes(query: str | None, output_format: str):
    """
    Search for recipes in community repository

    QUERY supports '|' separated multiple keywords (OR logic).

    \b
    Examples:
      frago recipe search twitter
      frago recipe search "twitter|x"
      frago recipe search
    """
    from frago.recipes.installer import RecipeInstaller

    installer = RecipeInstaller()
    results = installer.search_community(query)

    if output_format == 'json':
        click.echo(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            if query:
                click.echo(f"No recipes found matching '{query}'")
            else:
                click.echo("No community recipes available")
            return

        click.echo(f"{'NAME':<30} {'VERSION':<10} {'TYPE':<10} {'DESCRIPTION'}")
        click.echo("-" * 80)
        for recipe in results:
            name = recipe.get('name', '')
            version = recipe.get('version', '')
            recipe_type = recipe.get('type', '')
            description = recipe.get('description', '')
            click.echo(f"{name:<30} {version:<10} {recipe_type:<10} {description}")

        click.echo()
        click.echo(f"Found {len(results)} recipe(s)")
        click.echo("Install with: frago recipe install community:<name>")


@recipe_group.command(name='share', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option(
    '--yes', '-y',
    is_flag=True,
    help='Skip confirmation prompt'
)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['text', 'json'], case_sensitive=False),
    default='text',
    help='Output format'
)
def share_recipe(name: str, yes: bool, output_format: str):
    """
    Share a recipe to the community repository via GitHub PR

    This command will:
    1. Validate the recipe format
    2. Fork the frago repository (if needed)
    3. Create a branch and copy the recipe
    4. Submit a Pull Request

    Prerequisites:
    - GitHub CLI (gh) must be installed and authenticated
    - Recipe must pass validation

    \b
    Examples:
      frago recipe share my-recipe
      frago recipe share my-recipe --yes
    """
    import subprocess
    import tempfile

    # Helper functions
    def run_cmd(cmd: list[str], capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
        """Run a command and return result"""
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=check,
            encoding='utf-8',
            errors='replace'
        )

    def echo_step(step: int, total: int, message: str, status: str = ""):
        """Print step progress"""
        if output_format == 'text':
            if status:
                click.echo(f"[{step}/{total}] {message}")
                click.echo(f"  {status}")
            else:
                click.echo(f"[{step}/{total}] {message}")

    def echo_item(prefix: str, message: str):
        """Print item"""
        if output_format == 'text':
            click.echo(f"  {prefix} {message}")

    # Step 1: Check prerequisites
    echo_step(1, 4, "Checking prerequisites...")

    # Check gh is installed
    try:
        run_cmd(["gh", "--version"])
    except FileNotFoundError:
        if output_format == 'json':
            click.echo(json.dumps({"success": False, "error": "gh CLI not installed", "code": "gh_not_found"}))
        else:
            click.echo("Error: GitHub CLI (gh) is not installed", err=True)
            click.echo("Install from: https://cli.github.com/", err=True)
        sys.exit(1)

    # Check gh is authenticated
    try:
        result = run_cmd(["gh", "auth", "status"])
        # Extract username from output
        gh_user = None
        for line in result.stderr.split('\n'):
            if 'Logged in to github.com account' in line:
                # Format: "Logged in to github.com account USERNAME"
                parts = line.strip().split()
                if parts:
                    gh_user = parts[-1].strip('()')
                    break
            elif 'as' in line.lower() and 'account' in line.lower():
                # Alternative format
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.lower() == 'as' and i + 1 < len(parts):
                            gh_user = parts[i + 1].strip('()')
                            break
    except subprocess.CalledProcessError:
        if output_format == 'json':
            click.echo(json.dumps({"success": False, "error": "gh not authenticated", "code": "gh_not_auth"}))
        else:
            click.echo("Error: GitHub CLI is not authenticated", err=True)
            click.echo("Run: gh auth login", err=True)
        sys.exit(1)

    echo_item("✓", f"gh authenticated{f' as: {gh_user}' if gh_user else ''}")

    # Find and validate the recipe
    registry = RecipeRegistry()
    registry.scan()

    try:
        recipe = registry.find(name, source='user')
    except RecipeError:
        if output_format == 'json':
            click.echo(json.dumps({"success": False, "error": f"Recipe '{name}' not found in user recipes", "code": "not_found"}))
        else:
            click.echo(f"Error: Recipe '{name}' not found in user recipes", err=True)
            click.echo("Only user recipes (in ~/.frago/recipes/) can be shared", err=True)
        sys.exit(1)

    # Validate recipe
    from frago.recipes.metadata import parse_metadata_file, validate_metadata
    try:
        metadata = parse_metadata_file(recipe.metadata_path)
        validate_metadata(metadata)
        echo_item("✓", f"Recipe '{name}' validated")
    except Exception as e:
        if output_format == 'json':
            click.echo(json.dumps({"success": False, "error": f"Recipe validation failed: {e}", "code": "validation_failed"}))
        else:
            click.echo(f"Error: Recipe validation failed: {e}", err=True)
            click.echo(f"Run: frago recipe validate {recipe.base_dir}", err=True)
        sys.exit(1)

    # Check if recipe already exists in community
    from frago.recipes.installer import RecipeInstaller
    installer = RecipeInstaller()
    community_recipes = installer.search_community(name)
    exact_match = any(r.get('name') == name for r in community_recipes)
    if exact_match:
        if output_format == 'json':
            click.echo(json.dumps({"success": False, "error": f"Recipe '{name}' already exists in community", "code": "already_exists"}))
        else:
            click.echo(f"Error: Recipe '{name}' already exists in community repository", err=True)
        sys.exit(1)

    echo_item("✓", "Recipe name available in community")

    # Confirm before proceeding
    if not yes and output_format != 'json':
        click.echo()
        click.echo(f"Recipe to share: {name}")
        click.echo(f"  Type: {metadata.type}")
        click.echo(f"  Runtime: {metadata.runtime}")
        click.echo(f"  Description: {metadata.description}")
        click.echo()
        if not click.confirm("Proceed with sharing?"):
            click.echo("Cancelled")
            return

    # Step 2: Prepare submission
    echo_step(2, 4, "Preparing submission...")

    # Community repository (configurable via config file)
    from frago.init.config_manager import load_config
    config = load_config()
    UPSTREAM_REPO = config.community_repo
    BRANCH_NAME = f"recipe/{name}"

    # Check if user has push permission to upstream (owner or collaborator)
    can_push_directly = False
    try:
        result = run_cmd(["gh", "api", f"repos/{UPSTREAM_REPO}", "--jq", ".permissions.push"], check=False)
        can_push_directly = result.stdout.strip().lower() == "true"
    except Exception:
        pass  # Default to fork flow

    if can_push_directly:
        # User has push permission, push directly to upstream
        echo_item("✓", f"Push permission verified for {UPSTREAM_REPO}")
        clone_repo = UPSTREAM_REPO
        pr_head = BRANCH_NAME
    else:
        # No push permission, need to fork
        repo_name = UPSTREAM_REPO.split("/")[-1]
        try:
            result = run_cmd(["gh", "repo", "view", f"{gh_user}/{repo_name}", "--json", "name"], check=False)
            if result.returncode != 0:
                # Fork doesn't exist, create it
                echo_item("→", "Forking repository...")
                run_cmd(["gh", "repo", "fork", UPSTREAM_REPO, "--clone=false"])
                echo_item("✓", f"Fork created: {gh_user}/{repo_name}")
            else:
                echo_item("✓", f"Fork exists: {gh_user}/{repo_name}")
            clone_repo = f"{gh_user}/{repo_name}"
            pr_head = f"{gh_user}:{BRANCH_NAME}"
        except subprocess.CalledProcessError as e:
            if output_format == 'json':
                click.echo(json.dumps({"success": False, "error": f"Failed to check/create fork: {e}", "code": "fork_failed"}))
            else:
                click.echo(f"Error: Failed to check/create fork: {e}", err=True)
            sys.exit(1)

    # Step 3: Clone, copy files, commit
    echo_step(3, 4, "Copying recipe files...")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        repo_path = temp_path / "frago"

        try:
            # Clone the repository
            run_cmd(["gh", "repo", "clone", clone_repo, str(repo_path), "--", "--depth", "1"])

            if can_push_directly:
                # User has push permission: fetch latest main and create branch
                run_cmd(["git", "-C", str(repo_path), "fetch", "origin", "main"])
                run_cmd(["git", "-C", str(repo_path), "checkout", "-b", BRANCH_NAME, "origin/main"])
            else:
                # No push permission: add upstream and create branch from upstream/main
                run_cmd(["git", "-C", str(repo_path), "remote", "add", "upstream", f"https://github.com/{UPSTREAM_REPO}.git"])
                run_cmd(["git", "-C", str(repo_path), "fetch", "upstream", "main"])
                run_cmd(["git", "-C", str(repo_path), "checkout", "-b", BRANCH_NAME, "upstream/main"])

            # Copy recipe files
            target_dir = repo_path / "community-recipes" / "recipes" / name
            target_dir.mkdir(parents=True, exist_ok=True)

            import shutil
            for item in recipe.base_dir.iterdir():
                if item.name.startswith('.'):
                    continue
                if item.is_file():
                    shutil.copy2(item, target_dir / item.name)
                    echo_item("→", f"{name}/{item.name}")
                elif item.is_dir():
                    shutil.copytree(item, target_dir / item.name)
                    echo_item("→", f"{name}/{item.name}/")

            # Ensure git user is configured before commit
            success, error = _ensure_git_user_config(repo_path)
            if not success:
                if output_format == 'json':
                    click.echo(json.dumps({"success": False, "error": error, "code": "git_config_failed"}))
                else:
                    click.echo(f"Error: {error}", err=True)
                sys.exit(1)

            # Commit
            run_cmd(["git", "-C", str(repo_path), "add", "."])
            commit_msg = f"feat(recipe): add {name} recipe\n\n{metadata.description}"
            run_cmd(["git", "-C", str(repo_path), "commit", "-m", commit_msg])

            # Push to fork
            run_cmd(["git", "-C", str(repo_path), "push", "-u", "origin", BRANCH_NAME, "--force"])

        except subprocess.CalledProcessError as e:
            if output_format == 'json':
                click.echo(json.dumps({"success": False, "error": f"Git operation failed: {e.stderr or e}", "code": "git_failed"}))
            else:
                click.echo(f"Error: Git operation failed: {e.stderr or e}", err=True)
            sys.exit(1)

        # Step 4: Create PR
        echo_step(4, 4, "Creating Pull Request...")

        try:
            pr_title = f"feat(recipe): add {name} recipe"
            pr_body = f"""## New Recipe: {name}

**Type:** {metadata.type}
**Runtime:** {metadata.runtime}
**Version:** {metadata.version}

### Description

{metadata.description}

### Use Cases

{chr(10).join(f'- {uc}' for uc in metadata.use_cases)}

---

*Submitted via `frago recipe share`*
"""
            result = run_cmd([
                "gh", "pr", "create",
                "--repo", UPSTREAM_REPO,
                "--head", pr_head,
                "--title", pr_title,
                "--body", pr_body
            ])

            # Extract PR URL from output
            pr_url = result.stdout.strip()

            if output_format == 'json':
                click.echo(json.dumps({
                    "success": True,
                    "recipe_name": name,
                    "pr_url": pr_url
                }, ensure_ascii=False, indent=2))
            else:
                click.echo()
                click.echo(f"✓ PR created: {pr_url}")
                click.echo()
                click.echo("Your recipe has been submitted for review!")
                click.echo("The maintainers will review and merge your contribution.")

        except subprocess.CalledProcessError as e:
            if output_format == 'json':
                click.echo(json.dumps({"success": False, "error": f"Failed to create PR: {e.stderr or e}", "code": "pr_failed"}))
            else:
                click.echo(f"Error: Failed to create PR: {e.stderr or e}", err=True)
            sys.exit(1)


# --- Background schedule management (persistent, server-side) ---
# Moved to top-level: frago schedule (registered in main.py)
