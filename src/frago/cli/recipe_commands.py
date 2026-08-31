"""Recipe management commands"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from frago.cli.git_utils import _ensure_git_user_config
from frago.recipes import OutputHandler, RecipeRegistry, RecipeRunner
from frago.recipes.exceptions import MetadataParseError, RecipeError, RecipeValidationError
from frago.recipes.metadata import parse_metadata_file, validate_metadata
from frago.recipes.schedule import parse_datetime, parse_interval

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
        return base / 'atomic' / 'browser' / name
    return base / 'atomic' / 'system' / name


def _find_recipe_dir_by_name(name: str) -> Path | None:
    """Find existing recipe directory by name from registry or filesystem."""
    base = Path.home() / '.frago' / 'recipes'
    # Check known locations
    for subdir in ['atomic/system', 'atomic/browser', 'workflows']:
        candidate = base / subdir / name
        if candidate.exists():
            return candidate
    return None


def _run_frago_agent(
    prompt_text: str,
    *,
    agent_type: str = "claude",
) -> int:
    """Run frago agent as subprocess with the given prompt.

    ``agent_type`` defaults to claude (unchanged behavior); pass another agent
    to drive a different cli-agent recipe. 后端只剩 tmux（spec 20260607 Phase 5），
    故不再有 driver 选择。

    Returns the process exit code.
    """
    # Write prompt to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(prompt_text)
        prompt_file = f.name

    try:
        # Resolve frago binary via the shared server helper (single source of
        # truth for the venv-aware lookup). NOTE: the *execution model* stays
        # CLI-local on purpose — this command must block until the agent exits
        # and surface its returncode (with --quiet and a 600s timeout), whereas
        # AgentService.start_task is fire-and-forget background that returns a
        # task_id/pid immediately. Reusing start_task here would silently change
        # this command's behavior, so only the binary resolution is shared.
        from frago.server.services.agent_service import _resolve_frago_cmd
        frago_cmd = _resolve_frago_cmd()
        cmd = [
            *frago_cmd, "agent", "--quiet",
            "--agent-type", agent_type,
            "--prompt-file", prompt_file,
        ]

        result = subprocess.run(cmd, timeout=600)
        return result.returncode
    except subprocess.TimeoutExpired:
        click.echo("Error: Agent execution timed out (600s)", err=True)
        return 1
    finally:
        Path(prompt_file).unlink(missing_ok=True)


def _plan_into(name: str, prompt_text: str, spec_path: Path,
               *, type_: str | None, runtime: str | None) -> None:
    """Decide the module's shape and write it down. Shared by plan and create.

    One implementation on purpose: the two commands used to be two paths to a
    recipe, and only one of them went through planning. Whichever door a person
    walks in, the same four decisions get made and written down before any code
    exists — what modes there are, which of them other modules may call, whose
    surface this one depends on, whether it has a page.
    """
    from frago.recipes.template import render_spec

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(render_spec(name, kind=type_ or "atomic"), encoding="utf-8")

    type_hint = f"\n预设 type: {type_}" if type_ else ""
    runtime_hint = f"\n预设 runtime: {runtime}" if runtime else ""
    agent_prompt = f"""你是 frago recipe spec 撰写专家。

任务：为 recipe '{name}' 撰写需求 spec。

先运行以下命令获取规范：
  frago book recipe-spec-writing

用户需求：
{prompt_text}
{type_hint}{runtime_hint}

规格模板已经生成在 {spec_path}，**在它上面填**，NEVER 另起炉灶重写。

那份模板分两半：

  ```yaml 代码块里的字段是给机器读的。frago recipe create 会读它，
  写什么就长出什么——modes 变成方法，每个 mode 的访问级别变成方法上的标记，
  imports 变成对方能看见的依赖。这几个字段 MUST 想清楚再写：
    modes    这个模块能做哪几件事（一个 mode 一件），以及每件事对外开到什么程度。
             写成 `<mode>: <级别>`，级别只有三种，一个 mode 只写一个：
               export  只读契约。别的模块能调，这个配方自己的页面也读得到。
                       MUST 只读——不触网、不重算、不改状态、不开浏览器。
               action  这张页面上能按，允许干活。页面是最不可信的一层
                       （谁打得开谁就能按），按下去却是在主人的机器上
                       用主人的凭证跑。会花钱、会以主人身份对外做事的
                       mode NEVER 写 action。
               留空    只有主人能跑。默认，而且默认是对的：开出去容易，收回来难。
             只写一个级别：export 已经意味着页面读得到，
             「既导出又给页面按」本来就没有意义。
    default_mode  不写 mode 时跑哪一个。留空就是 modes 里第一个。
    imports  用了谁的哪个口
    page     要不要一张页面

  下半部分是给人读的：它解决什么问题、每个 mode 干什么、**它不做什么**、
  数据存什么、出错怎么办、怎么验。
  边界写清楚比能力写清楚更省事——下一个人照着扩展时知道哪儿不该伸手。

「怎么验」那一节 MUST 逐条写清依据的是上面哪条规则，而且 **MUST 自己先从头跑一遍**。
已经连着两个 agent 撞上同一件事：验收单的期望值跟规格正文算不出同一个结果，
照着验会得出「配方错了」的结论，而真正错的是规格。期望值是拍脑袋写的，
规则是想清楚的——对不上时先怀疑期望值。

填完不要自己写代码。
"""
    if _run_frago_agent(agent_prompt) != 0:
        click.echo("Error: Agent failed to generate spec", err=True)
        sys.exit(1)


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

    click.echo(f"[Plan] Generating spec for recipe '{name}'...")
    click.echo(f"  Directory: {recipe_dir}")
    _plan_into(name, prompt_text, spec_path, type_=type_, runtime=runtime)

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

    # One-step creation still goes through planning; it just does not make the
    # person run two commands. The step being skipped, not the second command,
    # was the problem: a probe run showed a fresh agent finding
    # `create --prompt`, writing no spec at all, and letting the agent typing
    # the implementation decide the module's exported surface as it went. An
    # exported mode is a promise other modules build on, and this is how such a
    # promise gets made by accident.
    if user_prompt is not None:
        spec_file = recipe_dir / "spec.md"
        if not spec_file.exists() or force:
            click.echo(f"[Plan] 先定规格：{spec_file}")
            _plan_into(name, user_prompt, spec_file, type_=None, runtime=None)
        spec_content = spec_file.read_text(encoding="utf-8")

    # Lay the template down before the agent is asked for anything. Creation
    # used to write no files at all: it handed an agent a prompt and whatever
    # came back was a recipe. That is where three hundred divergent answers to
    # the same four questions came from — where do I write, how do I report,
    # how do I reach another module, what shape do I return — each worked out
    # again, each reasonable alone, no two alike.
    from frago.recipes.template import read_spec, render

    # What planning decided is what this builds. Reading the spec's
    # machine-readable half is the join between the two halves of the pipeline;
    # without it they agree only by luck, and a spec that describes modes the
    # code never declares looks exactly like one that got built correctly.
    spec_fields = read_spec(spec_content) if spec_content else {}
    if not spec_fields:
        # One-step creation used to skip planning entirely, and a probe run
        # showed a fresh agent doing exactly that: it found `create --prompt`,
        # never wrote a spec, and let the agent writing the code decide the
        # module's exported surface as it went. An exported mode is a promise
        # other modules build on; deciding it while typing the implementation
        # is how a promise gets made by accident.
        click.echo("Error: 没有规格，不生成配方。", err=True)
        click.echo(f"[Fix] 先跑 frago recipe plan {name} --prompt \"<需求>\"，"
                   f"在规格里定下 modes（含每个 mode 的访问级别）/ imports / page 三项，"
                   f"再回来 create。", err=True)
        click.echo("      访问级别是这个模块对外的承诺——写代码时顺手定下来的承诺，"
                   "别的模块依赖上就收不回来了。", err=True)
        sys.exit(1)
    click.echo(f"[Template] 按规格生成：modes={spec_fields.get('modes')}")
    try:
        generated = render(name, spec=spec_fields)
    except ValueError as err:
        click.echo(f"Error: 规格自相矛盾——{err}", err=True)
        sys.exit(1)

    for rel, content in generated.items():
        target = recipe_dir / rel
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    click.echo("[Template] 模板已生成（含基类与空页面）")

    template_rules = f"""
模板已经生成在 {recipe_dir}/，**在它上面改**，NEVER 另起炉灶重写文件：

  recipe.py          配方本体。类继承 Recipe，头部的 frago-recipe 描述头 MUST 原样保留——
                     那是契约描述头，说明这个文件照哪一版规范写，NEVER 删掉。
  recipe.md          元信息。imports 字段 MUST 照实填。
                     NEVER 往里加 exports / page_actions——那两个字段已作废，
                     写了 validate 会报错。
  assets/            空页面。用不上就删掉整个目录，用得上就在它上面长。

必须守的：

  1. 能力建在基类上。落点用 self.store / self.data_dir，
     NEVER 自己拼路径，NEVER 留「平台没给就用我自己的」那种兜底。
  2. 一个 mode 一个 mode_<名字> 方法。NEVER 另写 modes / exports /
     page_actions 名单——平台从方法和方法上的标记直接读，手写会被拒。
     方法上标它对外开到什么程度：@export（只读契约，别的模块和页面都读得到）、
     @action（页面能按，允许干活）、不标（只有主人能跑）。
  3. 要别的模块的数据：先在 imports 里声明，再 self.ask(模块, mode)。
     NEVER 去读对方的文件，NEVER import 对方的代码。
  4. 标了 @export 的 mode MUST 只读：不触网、不重算、不改状态、不开浏览器。
  5. 页面是前端、配方是后端。publish 只发渲染状态，NEVER 发路径。
  6. 说话用 self.progress() / self.warn() / self.log()，
     NEVER 直接 print 到 stdout——stdout 是消息流，混一句进去整段就解不动。

写完跑 frago recipe validate {recipe_dir}。
"""

    # Build agent prompt
    if spec_content:
        agent_prompt = f"""你是 frago recipe 开发专家。

任务：根据 spec 创建 recipe '{name}'。

先运行以下命令获取规范：
  frago book recipe-creation

Spec 内容（位于 {resolved_spec}）：
{spec_content}

{template_rules}
创建完成后，运行 frago recipe validate {recipe_dir}。
如果 validate 失败，根据错误信息修复后重试，最多 3 轮。
"""
    else:
        agent_prompt = f"""你是 frago recipe 开发专家。

任务：创建 recipe '{name}'。

先运行以下命令获取规范：
  frago book recipe-spec-writing
  frago book recipe-creation

用户需求：
{user_prompt}

先在 {recipe_dir}/ 写 spec.md。
{template_rules}
创建完成后，运行 frago recipe validate {recipe_dir}。
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
    type=click.Choice(['user', 'community', 'all'], case_sensitive=False),
    default='all',
    help='Filter by source (user | community | all)'
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
    type=click.Choice(['user', 'community'], case_sensitive=False),
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
                "created_at": recipe.metadata.created_at,
                "updated_at": recipe.metadata.updated_at,
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
            if m.created_at:
                click.echo(f"Created:  {m.created_at}")
            if m.updated_at:
                click.echo(f"Updated:  {m.updated_at}")
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
    type=click.Choice(['user', 'community'], case_sensitive=False),
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


@recipe_group.command(name='schedule', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option('--interval', required=True, help='Run interval (e.g., 30s, 10m, 2h, 1h30m)')
@click.option('--params', type=str, default='{}', help='Recipe parameters (JSON)')
@click.option('--params-file', type=click.Path(exists=True), help='Read parameters from file')
@click.option('--source', type=click.Choice(['user', 'community']), default=None, help='Recipe source')
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
    interval_seconds = parse_interval(interval)

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
    start_dt = parse_datetime(start_at) if start_at else None
    stop_dt = parse_datetime(stop_at) if stop_at else None

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


@recipe_group.command(name='publish', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option('--slot', default='default', show_default=True,
              help='Which slot to publish to. Recipes that hold several projects '
                   'or sessions open at once give each one its own slot.')
@click.option('--state-file', type=click.Path(exists=True, dir_okay=False),
              help='Read the state JSON from this file instead of stdin.')
@click.option('--identity', is_flag=True,
              help='Publish to a signed-in account\'s own slot; --slot is then '
                   'that account id. Visitor runs do this by themselves.')
def publish_state(name: str, slot: str, state_file: str | None, identity: bool):
    """Publish the state a recipe's page should show, then print the page URL.

    An interactive recipe calls this at the end of a run instead of copying its
    assets somewhere and writing a config.json next to them. The page lives at a
    fixed address — /app/<name> — and this command decides what that address
    serves. Running the recipe again republishes; the address never changes.

    State arrives as JSON on stdin (or via --state-file, for recipes whose state
    is too large to pipe comfortably). Recipes run under their own interpreter
    and cannot import frago, so this command is how they reach the state layer.

    That last sentence is why the visitor rules live in `app_state.publish()`
    and not here: dozens of recipes publish by shelling out to this command, so
    a rule written in this function only would hold for the ones that import.
    Started inside a visitor run, this command writes that visitor's slot no
    matter what --slot and --identity say.
    """
    from frago.recipes import context
    from frago.recipes.app_state import InvalidSlotName, page_url, publish

    raw = Path(state_file).read_text(encoding='utf-8') if state_file else sys.stdin.read()
    try:
        state = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        click.echo(f"Error: state is not valid JSON: {e}", err=True)
        sys.exit(1)

    if not isinstance(state, dict):
        click.echo("Error: state must be a JSON object", err=True)
        sys.exit(1)

    try:
        publish(name, state, slot, identity=identity)
        visitor = context.current().is_visitor
    except (InvalidSlotName, context.InvalidInvocationContext) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # An identity slot has no `?key=` form. The gate decides which one a visitor
    # reads, so an address naming the slot would be both wrong and a copy of an
    # account id in whatever the recipe logs next.
    click.echo(page_url(name) if (identity or visitor) else page_url(name, slot))


_OPENABLE_SCHEMES = {'http', 'https', 'file'}


def _resolve_open_target(target: str, slot: str | None) -> str:
    """Turn what the caller typed into the address to hand the browser.

    Two spellings are accepted on purpose. A recipe that just published its
    state already holds the full address and passes that. A person or an agent
    standing outside a run only has the recipe's name, and asking them to
    remember `http://localhost:8093/app/<name>` is how they end up passing the
    bare name to something that expects a URL — so the bare name is spelled
    out here instead of failing silently in the browser.

    Anything else — a scheme we cannot open, a bare host:port, a path — is an
    error. Handing those to the browser produces a blank page, not a refusal.
    """
    from urllib.parse import urlsplit

    from frago.recipes.app_state import DEFAULT_SLOT, InvalidSlotName, list_slots, page_url

    scheme = urlsplit(target).scheme
    if scheme:
        if scheme not in _OPENABLE_SCHEMES:
            raise click.ClickException(
                f"cannot open {target!r}: only {'/'.join(sorted(_OPENABLE_SCHEMES))} addresses "
                f"can be opened"
            )
        if slot:
            raise click.ClickException(
                "--slot applies to a recipe name, not a full address; put ?key=<slot> in the URL"
            )
        return target

    try:
        page = page_url(target, slot or DEFAULT_SLOT)
    except InvalidSlotName:
        raise click.ClickException(
            f"{target!r} is neither a recipe name nor an address frago can open. "
            f"Pass a recipe name (frago recipe open my_recipe) or a full URL "
            f"(frago recipe open http://localhost:8093/app/my_recipe)."
        ) from None

    published = list_slots(target)
    if not published:
        raise click.ClickException(
            f"recipe {target!r} has never published a page, so it would open blank. "
            f"Run it first: frago recipe run {target}"
        )
    if (slot or DEFAULT_SLOT) not in published:
        raise click.ClickException(
            f"recipe {target!r} has no slot {slot or DEFAULT_SLOT!r}. "
            f"Published slots: {', '.join(published)}"
        )
    return page


@recipe_group.command(name='open', cls=AgentFriendlyCommand)
@click.argument('target', metavar='RECIPE_NAME_OR_URL')
@click.option('--slot', default=None, help='Which published slot to show (default: "default")')
def open_ui(target: str, slot: str | None):
    """Open a recipe's page for a human: `frago recipe open <recipe-name|url>`.

    Takes either the recipe's name or the page's full address; the name is
    expanded to http://localhost:8093/app/<name>. Interactive recipes call
    this with the address publish already handed them; people and agents
    outside a run have only the name, so both spellings work.

    It uses the OS default browser, NOT the CDP-controlled Chrome that
    `frago browser` drives: the page is for a person to read, and opening it
    here keeps the agent's CDP browser free and removes any dependency on
    that browser being up. This is the single seam for "open a recipe page
    for the human" — change the open behavior here, not in each recipe.

    A target that is not a known recipe or an openable address is refused
    rather than handed to the browser, because the browser answers a bad
    address with a blank page and no error.
    """
    import webbrowser

    url = _resolve_open_target(target, slot)

    try:
        opened = webbrowser.open(url)
    except Exception as e:
        click.echo(f"Error: failed to open URL '{url}': {e}", err=True)
        sys.exit(1)

    if opened:
        click.echo(f"Opened in default browser: {url}", err=True)
    else:
        click.echo(f"Error: no browser available to open URL '{url}'", err=True)
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


#: The variable that answers "where does this run write". A recipe that reads it
#: and then falls back to something of its own has re-opened the entrance.
_DATA_DIR_ENV = 'FRAGO_RECIPE_DATA_DIR'

#: A path literal pointing into the old per-subject data tree. A recipe naming
#: one of these is deciding its own location, which is what put one ledger in
#: four places on one machine.
_OWN_DATA_PATH = re.compile(r"""['"][^'"\n]*\.frago[/\\]+data[/\\]+[^'"]*['"]""")

#: Trees frago maintains for itself. A recipe writing into one of these keeps its
#: records inside somebody else's.
_PLATFORM_TREE_PATH = re.compile(
    r"""['"][^'"\n]*\.frago[/\\]+(?:sessions|app-state|executions|traces|projects|users|books|state)\b[^'"\n]*['"]"""
)

#: The one thing under ``users/`` that is *not* the platform's own: a recipe's
#: own data, which is exactly where the layout puts it. Without this the check
#: reports the correct answer as a violation — and a check that condemns the
#: thing it is asking for is worse than none, because the person reading it
#: fixes a document that was right into one that is wrong.
_RECIPE_DATA_UNDER_USERS = re.compile(
    r"""\.frago[/\\]+users[/\\]+[^'"\n/\\]+[/\\]+recipe-data[/\\]"""
)

#: Another recipe's directory. See book recipe-authoring: a recipe reading
#: another's files depends on a structure nobody knows they are maintaining.
_OTHER_RECIPE_PATH = re.compile(r"""['"][^'"\n]*\.frago[/\\]+recipes[/\\]+[^'"]*['"]""")

#: The platform writes this file inside every data directory. A recipe writing it
#: would overwrite the page's own note.
_RESERVED_STATE_FILE = re.compile(r"""['"]state\.json['"]""")


def _home_anchored_paths(content: str) -> list[str]:
    """Path expressions the recipe builds under the user's frago home.

    Parsed rather than pattern-matched, because the common shape is not a
    string at all — it is ``Path.home() / ".frago" / "data" / ...``, assembled
    a segment at a time, and a literal-scanning check walks straight past it.
    That is how the recipe at the centre of this whole exercise passed a first
    version of this check while holding four copies of one ledger.

    Only chains that name ``.frago`` count. Recipes legitimately locate the
    frago binary through ``Path.home() / ".local" / "bin"``, and flagging that
    would train people to ignore the checker.
    """
    import ast

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    def segments_of(node: ast.AST) -> list[str]:
        return [
            sub.value for sub in ast.walk(node)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
        ]

    # Which names stand for the frago home. Almost nobody writes the whole path
    # in one expression — they bind `FRAGO_HOME = Path.home() / ".frago"` once
    # and divide off it everywhere after, so a check that only looks at single
    # expressions sees `/ "data" / "etf"` with no `.frago` in sight and passes.
    # That is exactly how the recipe holding four copies of one ledger passed a
    # first version of this check.
    home_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and ".frago" in segments_of(node.value):
            home_names.add(target.id)

    def rooted_at_home(node: ast.AST) -> bool:
        return any(
            isinstance(sub, ast.Name) and sub.id in home_names
            for sub in ast.walk(node)
        )

    def in_order(node: ast.AST) -> list[str]:
        """Segments left to right, so the message reads like a path.

        ``ast.walk`` is breadth-first, which turns ``a / "b" / "c"`` into
        ``c, b`` — a message that names the segments in an order the reader has
        to un-shuffle before they can look for them on disk.
        """
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return in_order(node.left) + in_order(node.right)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        return []

    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        if ".frago" not in segments_of(node) and not rooted_at_home(node):
            continue
        rest = [x for x in in_order(node) if x != ".frago"]
        # Only the old data tree counts. A recipe legitimately locates the hook
        # engine under `.frago/bin` and writes a log under `.frago/logs`, and a
        # checker that flags those teaches people to skim past it — which costs
        # more than the two paths it would have caught.
        if rest and "data" in rest:
            found.append(".frago/" + "/".join(rest[:4]))
    return sorted(set(found))


def _module_level_env_reads(content: str) -> list[int]:
    """Line numbers where the data directory is resolved at import time.

    Parsed rather than pattern-matched, because what matters is *where* the read
    sits, not how it is spelled. A module-level read makes the file impossible to
    import — no checker, no test, no future metadata probe can touch it — and it
    raises a bare KeyError that tells the reader nothing about what to do.
    """
    import ast

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []  # reported separately; nothing useful to add here
    hits = []
    for node in tree.body:  # module level only, by construction
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and sub.value == _DATA_DIR_ENV:
                hits.append(node.lineno)
                break
    return hits


def _other_recipe_names(recipe_dir: Path) -> set[str]:
    """This machine's other recipes, by directory name.

    Read off disk rather than guessed from the path, because the thing that
    makes a path somebody else's is that a recipe by that name exists — not
    that it looks like a recipe directory.
    """
    root = Path.home() / ".frago" / "recipes"
    if not root.is_dir():
        return set()
    names = set()
    for kind in root.iterdir():
        if not kind.is_dir():
            continue
        for entry in kind.iterdir():
            if not entry.is_dir():
                continue
            if (entry / "recipe.md").is_file():
                names.add(entry.name)
                continue
            for sub in entry.iterdir():          # atomic/<group>/<recipe>
                if sub.is_dir() and (sub / "recipe.md").is_file():
                    names.add(sub.name)
    names.discard(recipe_dir.name)
    return names


def _scan_data_location(content: str, recipe_dir: Path) -> tuple[list[str], list[str]]:
    """Scan a recipe for the ways of deciding its own data location.

    Every rule here exists because of something that happened, and every one of
    them fails silently: none of these mistakes raises. The only symptom is that
    somebody eventually reads days-old numbers off a page that reports every
    refresh as a success. A check that runs is the whole difference between a
    rule and a document.

    See ``frago book must-recipe-data``.
    """
    errors: list[str] = []
    warnings: list[str] = []

    own = {m.group(0) for m in _OWN_DATA_PATH.finditer(content)}
    own |= set(_home_anchored_paths(content))

    # 自己读自己允许，跨配方禁止——两件事性质不同，报错也该分开。
    # 一条路径提到了别的配方的名字，就是在翻别人的柜子：那个配方不知道自己
    # 正在被读，它改自己的文件时看不到任何提示。
    others_data = {
        one for one in own
        if any(f"/{name}" in one or f"{name}/" in one
               for name in _other_recipe_names(recipe_dir))
    }
    own -= others_data
    if others_data:
        errors.append(
            f"配方直接读了别的配方的数据目录：{', '.join(sorted(others_data)[:3])}。"
            f"要它的数据就跑它的命令、读返回值——按路径去翻，对方改自己的文件时"
            f"看不到任何提示，断裂只在有人点开页面时才暴露。"
            f"见：frago book must-recipe-data"
        )

    if own:
        errors.append(
            f"配方自己拼了数据路径：{', '.join(sorted(own)[:3])}。"
            f"落点由平台交代（{_DATA_DIR_ENV}），配方不再自己决定——"
            f"「平台没给就用我自己的」那句是同一份数据散成好几份的入口，而且它不报错。"
            f"见：frago book must-recipe-data"
        )

    for line in _module_level_env_reads(content):
        errors.append(
            f"第 {line} 行在模块顶层读 {_DATA_DIR_ENV}。这样一 import 这个文件就死，"
            f"任何检查工具、测试、元信息探测都碰不了它，而且抛的是一句 KeyError，"
            f"看的人不知道该做什么。改成运行时求值。见：frago book must-recipe-data"
        )

    platform = {
        m.group(0)
        for m in _PLATFORM_TREE_PATH.finditer(content)
        if not _RECIPE_DATA_UNDER_USERS.search(m.group(0))
    }
    if platform:
        errors.append(
            f"配方在往 frago 自己维护的目录里写：{', '.join(sorted(platform)[:3])}。"
            f"那里面是平台的记录，不是这个配方的数据。见：frago book must-recipe-data"
        )

    others = {
        m.group(0)
        for m in _OTHER_RECIPE_PATH.finditer(content)
        if recipe_dir.name not in m.group(0)
    }
    if others:
        warnings.append(
            f"配方引用了别的配方的目录：{', '.join(sorted(others)[:3])}。"
            f"对方不知道自己正在被读，它改自己的代码时看不到任何提示，"
            f"断裂会发生在跟改动毫无关系的地方。改成跑对方的命令读返回值。"
            f"见：frago book recipe-authoring"
        )

    if _RESERVED_STATE_FILE.search(content):
        warnings.append(
            "配方写了 state.json 这个文件名。它是平台留给页面的那张便条，由平台写；"
            "配方要发布状态走 frago recipe publish。见：frago book must-recipe-data"
        )

    return errors, warnings

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
            sys.exit(1)
        metadata_path = recipe_path
        recipe_dir = recipe_path.parent
    else:
        # Directory form
        metadata_path = recipe_path / 'recipe.md'
        recipe_dir = recipe_path
        if not metadata_path.exists():
            click.echo(f"Error: recipe.md not found in recipe directory: {recipe_dir}", err=True)
            sys.exit(1)

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

            # 3.6 Scan where this recipe writes. Same shape as the secrets scan
            # above and for the same reason: a rule nobody can check is a
            # document, and every mistake it looks for fails silently.
            if metadata.runtime in ('python', 'shell'):
                data_errors, data_warnings = _scan_data_location(content, recipe_dir)
                # Is this a module at all — born here, built on the base class.
                # Checked only for the recipe's own entry script: a helper file
                # beside it is not a module and has no contract to keep.
                if script_path.stem == 'recipe':
                    born_errors, born_warnings = _scan_module_contract(
                        content, metadata.name
                    )
                    data_errors = born_errors + data_errors
                    data_warnings = born_warnings + data_warnings
                errors.extend(data_errors)
                warnings.extend(data_warnings)

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

    # 5b. A recipe that opened modes to its own page must honour the data
    # directory it is handed, or every reader's run writes the owner's one pile.
    # Checked here rather than at expose time because that is where the answer
    # now lives: the declaration travels with the recipe, so this is the same
    # verdict on every machine it reaches, and the author finds out while still
    # holding the file.
    from frago.recipes import checks as recipe_checks

    opened = recipe_checks.page_actions(recipe_dir)
    if opened:
        gap = _actions_readiness(recipe_dir)
        if gap:
            errors.append(
                f"这个配方用 @action 开了 {'、'.join(opened)}，"
                f"但它不读落点变量。{gap}"
            )

    # 5b-2. A recipe that says it reads another module's data, and will not be
    # able to. **An error, not a warning.** This used to be a warning because
    # the missing piece was an owner's signature, and a recipe waiting for one
    # was merely unfinished. It is now a disagreement between two declarations,
    # which means the run fails every time it happens — and the failure is the
    # quietest kind there is: the module reads an empty directory and reports,
    # accurately, that there is no data. On 2026-08-31 that shape ran every five
    # minutes for three days behind a board showing three-day-old numbers, with
    # the reason sitting in this command's warnings the whole time.
    shared_subtrees: dict[str, Path] = {}
    if metadata and metadata.reads_common:
        from frago.recipes.context import shared_with

        _, shared_subtrees, problems = shared_with(metadata.name)
        for problem in problems:
            errors.append(problem)

    # 5b-3. And what isolation itself will refuse. A recipe runs inside a view
    # holding its own landing spot, the blocks other modules declared, and the
    # machinery — nothing else. Whatever the kernel will refuse has to be
    # refused here first, by asking the same view rather than by keeping a
    # second list: two gates that describe different boundaries are not two
    # gates, they are one gate and one document.
    if metadata and metadata.runtime in ('python', 'shell'):
        from frago.recipes import isolation

        for blocked in isolation.foresee(
            recipe_dir, metadata.name,
            uses_frago_cli=bool(getattr(metadata, 'uses_frago_cli', False)),
            shared=shared_subtrees,
        ):
            errors.append(blocked.render(recipe_dir).replace("\n", " "))

    # 5c. Whatever would stop this recipe's page from working on another machine.
    # Reported here as well as at `expose` so an author can find out while still
    # writing, rather than at the moment they try to publish. Blocking findings
    # are warnings *here* on purpose: validate describes a recipe, it does not
    # decide anything, and a recipe that is never exposed is entitled to hard-code
    # whatever it likes on the machine it was written for.
    for finding in recipe_checks.audit(recipe_dir):
        warnings.append(finding.render(recipe_dir).replace("\n", " "))

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
        if not is_valid:
            sys.exit(1)
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
            sys.exit(1)


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

    frago ships no recipes of its own — everything runnable is either yours
    or installed from here.

    SOURCE can be:

    \b
    - community:<name>     Install from github.com/tsaijamey/frago-recipe-community
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

    Those are the only two places recipes live — frago itself ships none.
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
        # Auto-select: User > Community
        source_label = None
        for s in ['User', 'Community']:
            if s in sources_dict:
                source_label = s
                break
        if not source_label:
            # The registry only ever scans ~/.frago/recipes and
            # ~/.frago/community-recipes, so getting here means it grew a
            # search path somewhere else. frago did not put that directory
            # there and must not delete out of it.
            found = ", ".join(sorted(sources_dict)) or "unknown"
            hint = (
                f"Recipe '{name}' lives outside the directories frago manages "
                f"(source: {found}); remove it where it came from"
            )
            if output_format == 'json':
                result = {"success": False, "error": hint, "code": "unmanaged"}
                click.echo(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                click.echo(f"Error: {hint}", err=True)
                for src_label, recipe in sources_dict.items():
                    click.echo(f"  {src_label}: {recipe.base_dir}", err=True)
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
    Search the community recipe repository (tsaijamey/frago-recipe-community)

    QUERY supports '|' separated multiple keywords (OR logic).

    \b
    Examples:
      frago recipe search twitter
      frago recipe search "twitter|x"
      frago recipe search
    """
    from frago.recipes.installer import RecipeInstaller

    installer = RecipeInstaller()
    try:
        results = installer.search_community(query)
    except RuntimeError as e:
        # Almost always GitHub's anonymous quota: 60 requests an hour per IP.
        # Unhandled it surfaces as a traceback, which reads like frago is
        # broken and says nothing about the one action that fixes it.
        if output_format == 'json':
            click.echo(json.dumps(
                {"success": False, "error": str(e), "code": "search_failed"},
                ensure_ascii=False, indent=2,
            ))
        else:
            click.echo(f"Error: {e}", err=True)
            click.echo("[Fix] gh auth login   # raises the GitHub quota to 5000/hour", err=True)
        sys.exit(1)

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
    2. Fork the community recipe repository (if needed)
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

    # Community repository. Read it off the installer rather than the config
    # directly: the installer is what resolves a stale pre-split value, and a
    # PR opened against a different repo than the one `search_community` just
    # checked for name collisions would be checking one place and writing to
    # another.
    UPSTREAM_REPO = installer.COMMUNITY_REPO
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
        repo_path = temp_path / "community-recipes"

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

            # Copy recipe files. Same layout the installer reads from, taken
            # from the same constant so the two can never drift apart.
            target_dir = repo_path / installer.COMMUNITY_PATH / name
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


# --- Public exposure (deployed frago only) ---
#
# On a personal machine these are no-ops in spirit: /app/<name>/ is already
# reachable, because everything on loopback is. They matter when this frago runs
# on a server behind a reverse proxy, where the published list is the difference
# between "one dashboard is visible" and "the whole API is".


def _dangerous_data_dir(base: Path) -> str | None:
    """Why this directory must not be published, or None if it is fine.

    Publishing serves everything under `dataDir`, so a slot pointing at a
    directory that also holds other things hands those over too. The audit of
    20260817 pointed one at `~/.frago` and read the real `config.json` through
    the published page. A recipe writing its own output directory is the normal
    case and passes; the places worth refusing outright are few and nameable.
    """
    resolved = base.expanduser().resolve()
    home = Path.home().resolve()

    forbidden = {
        home: "your home directory",
        home / ".frago": "frago's own state directory",
        home / ".claude": "Claude Code's configuration",
        home / ".ssh": "your SSH keys",
        Path("/"): "the filesystem root",
    }
    if resolved in forbidden:
        return (
            f"Refusing to publish: dataDir is {resolved} ({forbidden[resolved]}). "
            f"Everything under it would become readable by anyone. Point the "
            f"recipe's dataDir at its own output directory instead."
        )
    if resolved in home.parents or resolved == home.parent:
        return (
            f"Refusing to publish: dataDir is {resolved}, which contains your "
            f"home directory. Point the recipe's dataDir at its own output "
            f"directory instead."
        )
    return None


def _borrowed_ui_owner(name: str) -> str | None:
    """The other recipe whose assets this one serves, if it borrows them."""
    from frago.recipes.exceptions import RecipeNotFoundError
    from frago.recipes.registry import get_registry

    try:
        recipe = get_registry().find(name)
    except (RecipeNotFoundError, Exception):
        return None
    owner = getattr(recipe.metadata, "ui_from", None)
    return owner if owner and owner != name else None


def _publish_audit(name: str, slot: str, *, require_identity: bool = False) -> tuple[dict, list[str]]:
    """What publishing this recipe would actually expose. Returns (state, notes)."""
    from frago.recipes.app_state import list_slots
    from frago.recipes.app_state import read as read_slot
    from frago.recipes.publish import public_view

    state = read_slot(name, slot)
    notes: list[str] = []

    if require_identity:
        # Everything below describes slot `slot`, which in this mode is not what
        # any visitor reads — it is only the shape the page is being checked
        # against. Saying so first stops the rest of the audit being read as a
        # list of what is about to become public.
        notes.append(
            "This page is being exposed per person, not to the public: only "
            "someone signed in can open it, and each of them reads their own "
            f"slot under ~/.frago/users/<account-id>/state/{name}.json. The slot '{slot}' "
            "audited below is what the page looks like, not what visitors get."
        )

    # A recipe may serve another's front end via `ui_from`. Publishing the
    # borrower publishes the lender's whole assets/ directory — which is what
    # sharing a front end means, but the lender was never published and its
    # author never agreed to it. Nobody should learn this by finding their own
    # .env on the internet.
    lender = _borrowed_ui_owner(name)
    if lender:
        notes.append(
            f"This page's files come from recipe '{lender}' (via ui_from), not from '{name}'. "
            f"Everything in {lender}'s assets/ becomes publicly readable — check it for "
            f".env files, notes and backups before continuing."
        )

    # Naming the other slots matters even though they stay private: slot names
    # are commonly a client or project code, and the person publishing should
    # see what else this recipe is holding before they point it at the internet.
    others = [s for s in list_slots(name) if s != slot]
    if others:
        notes.append(
            f"This recipe also holds {len(others)} other slot(s) — {', '.join(sorted(others))} "
            f"— which stay private. Only '{slot}' is being published."
        )

    exposed = public_view(state)
    if not exposed:
        notes.append(
            "This slot declares no `public` block, so visitors get no config beyond "
            "the page's own name. If the page needs values, publish them under "
            'state["public"] — everything else in the slot stays private.'
        )

    data_dir = state.get("dataDir")
    if data_dir:
        base = Path(str(data_dir)).expanduser()
        refusal = _dangerous_data_dir(base)
        if refusal:
            raise click.ClickException(refusal)
        resolved = base.resolve()
        if base.is_symlink() or resolved != base:
            notes.append(
                f"dataDir {base} resolves to {resolved} — that is the directory "
                f"that becomes public, not the path as written."
            )
        if base.is_dir():
            files = [p for p in base.rglob("*") if p.is_file()]
            notes.append(
                f"Every file under {base} becomes readable at /app/{name}/data/… "
                f"({len(files)} file(s) right now)."
            )
        else:
            notes.append(f"dataDir {base} does not exist yet; nothing is served from it.")
    else:
        notes.append(f"This slot declares no dataDir, so /app/{name}/data/… serves nothing.")

    return state, notes


def _resolve_allow(named: tuple[str, ...]) -> tuple[list[str], str | None]:
    """Turn what the operator typed into account ids. ``(ids, error)``.

    An email is a convenience for looking up an id, NEVER a thing that can be
    authorised on its own. Nothing in this system verifies an email address —
    whoever signs in with one first owns it — so writing an unclaimed address
    into an allow list would not authorise a colleague, it would hang a
    first-come ticket on the public internet. An address nobody has signed in
    with is therefore an error rather than a pre-authorisation.
    """
    from frago.server.identity import find_user_by_email, find_user_by_id

    ids: list[str] = []
    for raw in named:
        who = raw.strip()
        if not who:
            continue
        if "@" in who:
            user = find_user_by_email(who)
            if user is None:
                return [], (
                    f"No account has signed in with {who!r}, so there is no id to "
                    f"authorise. An unclaimed address cannot be allowed in advance — "
                    f"whoever registers it first would get in. Ask them to sign in "
                    f"once, then `frago user list` for their id."
                )
            resolved = user.id
        else:
            resolved = who
            if find_user_by_id(resolved) is None:
                return [], (
                    f"No account has the id {resolved!r}. Check `frago user list`."
                )
        if resolved not in ids:
            ids.append(resolved)

    if not ids:
        return [], (
            "--allow was given nothing to allow. To close a page to everyone, "
            "use `frago recipe unexpose` — an empty list would leave a published "
            "page nobody can open."
        )
    return ids, None


#: A page fetching from its own back end — the shape of the front-end/back-end
#: split. Matched loosely: what matters is that the page asks a mode for data at
#: run time rather than rendering files staged ahead of it.
_PAGE_CALLS_BACKEND = re.compile(r"""["'`]\s*api/|/app/[^"'`]*/api/""")


def _page_calls_backend(recipe_dir: Path) -> str | None:
    """Where this page asks its own recipe for data, or None if it never does.

    Asked when a page is about to be exposed to anonymous readers, because those
    two things cannot both be true. The anonymous zone admits GET and HEAD and
    nothing else — by design, and it is the reason a published page can be a
    read-only rendering of files already on disk. A page that asks a mode for
    its numbers asks by POST, so every one of those requests is refused, and the
    page renders its empty state with nothing anywhere reporting a fault.

    Found by reading the page rather than by waiting: the alternative is an
    operator who exposes the page, opens it, sees nothing, and has no reason to
    suspect the mode they chose an hour ago.
    """
    assets = recipe_dir / "assets"
    if not assets.is_dir():
        return None
    for path in sorted(assets.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".js", ".mjs", ".html", ".htm"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if line.startswith(("#", "//", "/*", "*", "<!--")):
                continue
            if _PAGE_CALLS_BACKEND.search(line):
                return f"{path.relative_to(recipe_dir)}:{number}  {line[:100]}"
    return None


def _actions_readiness(recipe_dir: Path) -> str | None:
    """Why this recipe's page actions cannot be honoured yet, or None if they can.

    The predicate itself lives in ``frago.recipes.checks`` and is shared with the
    audit that ``expose`` runs, because this function and that one used to be two
    copies of the same rule and the copies drifted — see
    ``checks.honours_the_landing_spot`` for what that cost.

    Refusing rather than warning, because opening a mode to a page happens a
    handful of times a year and a warning at that moment is a line of yellow text
    between an author and the thing they already decided to do. The cost of being
    wrong does not appear until the second reader arrives.
    """
    from frago.recipes.checks import honours_the_landing_spot

    if honours_the_landing_spot(recipe_dir):
        return None
    return (
        f"This recipe never reads {_DATA_DIR_ENV} and is not built on the base "
        f"class, so a page-triggered run would write wherever the recipe "
        f"hard-codes — the owner's directory — and every reader would share it. "
        f"Have it read that variable and fall back to its own default:\n"
        f"    data_dir = os.environ.get(\"{_DATA_DIR_ENV}\") or <its own default>\n"
        f"then expose it again."
    )


def _fail(output_format: str, message: str, code: str, **extra) -> None:
    """One refusal, spelled the same way in both output formats."""
    if output_format == 'json':
        click.echo(json.dumps(
            {"success": False, "error": message, "code": code, **extra},
            ensure_ascii=False))
    else:
        click.echo(f"Error: {message}", err=True)
    sys.exit(1)


@recipe_group.command(name='expose', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option('--slot', default=None,
              help="Which of the recipe's own slots this page serves. Meaningful "
                   "for a public page and for --shared; refused when each reader "
                   "has their own, where the slot is their account id.")
@click.option('--public', 'want_public', is_flag=True,
              help='Anyone may open it, with no sign-in.')
@click.option('--signed-in', 'want_signed_in', is_flag=True,
              help='Any signed-in account may open it. Drops an existing allow list, '
                   'which is why it has to be said rather than implied.')
@click.option('--require-identity', is_flag=True, help='Old spelling of --signed-in.')
@click.option('--allow', 'allow_who', multiple=True, metavar='ACCOUNT',
              help='Add an account to the list of who may open the page. Takes an '
                   'account id, or an email that already has one. Repeatable.')
@click.option('--deny', 'deny_who', multiple=True, metavar='ACCOUNT',
              help='Take an account back off the list. Repeatable.')
@click.option('--only', 'only_who', multiple=True, metavar='ACCOUNT',
              help='Replace the whole list with exactly these accounts. Repeatable.')
@click.option('--shared', 'want_shared', is_flag=True,
              help="Everyone on the list reads the recipe's own slot, read-only. "
                   "This is how a few named people see one body of work rather "
                   "than a copy each.")
@click.option('--each-their-own', 'want_own', is_flag=True,
              help='Each signed-in reader gets their own slot and their own directory.')
@click.option('--portal/--no-portal', 'want_portal', default=None,
              help='Register this page as the sign-in door people are sent to.')
@click.option('--runnable', is_flag=True, help='Retired; see the error it prints.')
@click.option('--force', is_flag=True, help='Retired; see the error it prints.')
@click.option('--yes', '-y', is_flag=True, help='Skip the confirmation prompt')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']), default='text')
def expose_recipe(name: str, slot: str | None, want_public: bool, want_signed_in: bool,
                  require_identity: bool, allow_who: tuple[str, ...],
                  deny_who: tuple[str, ...], only_who: tuple[str, ...],
                  want_shared: bool, want_own: bool, want_portal: bool | None,
                  runnable: bool, force: bool, yes: bool, output_format: str):
    """Decide who may open this recipe's page, and whose data they see.

    Exposing shows exactly three things and nothing else: the recipe's assets/,
    the `public` block of the slot being served, and the files under that slot's
    dataDir. The API that page would otherwise call — which can run recipes and
    read any path on this machine — stays closed.

    \b
    WHO MAY OPEN IT — one of these, and the first exposure must say which:
      --public          anyone, no sign-in
      --signed-in       any account that can sign in
      --allow <id>      only the accounts named (repeatable)

    \b
    WHOSE DATA THEY SEE — only meaningful once a sign-in is required:
      --each-their-own  each reader has their own slot and directory (default)
      --shared          they all read the recipe's own slot, read-only

    --shared is the answer to "these four people should see the numbers this
    recipe computed". The slot it serves is the recipe's own — the one under
    ~/.frago/app-state/, with no account anywhere in its path — so there is no
    copy per person and nothing to keep in step. It is not machine-level shared
    data, which is a data-layer mechanism for a different problem, and it is not
    --public with a password. Read-only by construction: nobody has a directory
    of their own on such a page, so there is nothing a run could write.

    Whether a page has buttons at all is no longer decided here. The recipe marks
    the modes its page may trigger with `@action`, on the methods themselves, and
    that answer is the same wherever the page is exposed. Exposure decides who is
    looking; the recipe decides what may be asked of it.

    \b
    Changing an existing exposure changes only what you name:
      frago recipe expose ledger --allow bob@example.com   # add Bob, keep the rest
      frago recipe expose ledger --deny bob@example.com    # take Bob off
      frago recipe expose ledger --only alice@example.com  # exactly Alice
      frago recipe expose ledger --signed-in               # drop the list entirely

    \b
    Examples:
        frago recipe expose weekly_report --public
        frago recipe expose kline_blind_trainer --signed-in
        frago recipe expose dma_plan --allow a@x.com --allow b@x.com --shared
        frago recipe expose frago_login_portal --public --portal
    """
    from frago.recipes.publish import (
        MODE_IDENTITY,
        MODE_PUBLIC,
        READS_OWN,
        READS_RECIPE,
        amend,
        legacy_runnable,
    )
    from frago.recipes.publish import (
        load as load_exposed,
    )
    from frago.recipes.publish import publish as mark_published
    from frago.recipes.publish import published_entry as _entry

    if runnable:
        _fail(output_format,
              "--runnable 已经取消。它是页面级开关：谁看得见就谁能按，而按下去是在主人的机器上、"
              "用主人的凭证跑。现在由配方逐个点名——在那个 mode 方法上标 @action，"
              "同一个配方在哪张页面上答案都一样。改完 recipe.py 再 expose，不用带任何开关。",
              "runnable_retired")
    if force:
        _fail(output_format,
              "--force 已经取消。它存在的唯一理由是抵消「每次 expose 整条重写」的副作用——"
              "少写一个 --allow 就把页面放开给全体登录用户。现在改动是增量的：没点名就不动，"
              "放宽必须说出口（--deny / --only / --signed-in）。",
              "force_retired")

    signed_in = want_signed_in or require_identity
    if want_public and (signed_in or allow_who or only_who):
        _fail(output_format,
              "--public 和「要登录」是同一个问题的两个答案，一次只能给一个。",
              "conflicting_audience")
    if want_shared and want_own:
        _fail(output_format, "--shared 和 --each-their-own 只能选一个。", "conflicting_reads")

    recipe_dir = _find_recipe_dir_by_name(name)
    if recipe_dir is None:
        _fail(output_format, f"Recipe not found: {name}", "not_found")

    if not (recipe_dir / 'assets').is_dir():
        _fail(output_format,
              f"Recipe '{name}' has no assets/ directory — there is no page to publish",
              "no_ui")

    existing = _entry(name) if name in load_exposed() else None

    # A first exposure has to state its audience out loud. There used to be a
    # default — no flags meant public — and it is the single most expensive
    # default in this command: the operator who has not decided yet is exactly
    # the operator who types the bare form, and what they get is the widest
    # answer available. There is no safe default here, only an unasked question.
    if existing is None and not (want_public or signed_in or allow_who or only_who):
        _fail(output_format,
              f"'{name}' 还没开放过，这一次必须说清楚谁能看：\n"
              f"  --public                    谁都能看，不用登录\n"
              f"  --signed-in                 任何登录用户\n"
              f"  --allow <账号id|邮箱>       只有点名的这几个（可重复）\n"
              f"没有默认值——这一问的答案只有你知道，猜错的代价是页面对全体注册用户敞开。",
              "audience_required")

    added, resolve_error = _resolve_allow(allow_who) if allow_who else ([], None)
    if resolve_error:
        _fail(output_format, resolve_error, "no_such_account")
    removed, resolve_error = _resolve_allow(deny_who) if deny_who else ([], None)
    if resolve_error:
        _fail(output_format, resolve_error, "no_such_account")
    exactly, resolve_error = _resolve_allow(only_who) if only_who else ([], None)
    if resolve_error:
        _fail(output_format, resolve_error, "no_such_account")

    # What the entry will say once this command has run. Worked out before
    # anything is written so the audit below describes the outcome rather than
    # the starting point.
    if want_public:
        mode = MODE_PUBLIC
    elif signed_in or allow_who or only_who:
        mode = MODE_IDENTITY
    else:
        mode = (existing or {}).get("mode") or MODE_PUBLIC

    if want_shared:
        reads = READS_RECIPE
    elif want_own:
        reads = READS_OWN
    elif mode == MODE_PUBLIC:
        reads = READS_RECIPE
    else:
        reads = (existing or {}).get("reads") or READS_OWN

    # `--slot` names one of the owner's slots, so it only means anything where
    # one of them is what gets served. Under `--each-their-own` the slot is the
    # reader's own account id, worked out by the server from their session, and
    # a reader carrying *any* `?key=` is refused outright — so a slot named here
    # would be written into the entry, enforce nothing, and change only a line of
    # the audit. It used to be accepted silently, which is how somebody spends an
    # afternoon wondering why their `--slot` had no effect.
    if slot and mode == MODE_IDENTITY and reads == READS_OWN:
        _fail(output_format,
              "--slot 在「各人读各人那份」下不起作用：读的槽位是他自己的账号 id，"
              "由服务端从会话算出，他自己带 ?key= 反而会被当场拒。\n"
              "要让点名的这几个人读配方自己的某一个槽，加上 --shared。",
              "slot_has_no_effect")

    next_slot = slot or (existing or {}).get("slot") or DEFAULT_SLOT_NAME

    if exactly:
        allow_ids: list[str] | None = list(exactly)
    elif signed_in and not allow_who:
        allow_ids = None
    else:
        held = (existing or {}).get("allow")
        allow_ids = list(held) if isinstance(held, list) else None
        if added:
            allow_ids = list(allow_ids or [])
            for who in added:
                if who not in allow_ids:
                    allow_ids.append(who)
        if removed and allow_ids is not None:
            allow_ids = [who for who in allow_ids if who not in removed]
    if mode == MODE_PUBLIC:
        allow_ids = None
    if allow_ids is not None and not allow_ids:
        _fail(output_format,
              "这样一来名单上就没人了，而「谁都打不开的已开放页面」不是一种配置。"
              "要关掉它用 frago recipe unexpose。",
              "would_empty_list")

    portal = (existing or {}).get("portal", False) if want_portal is None else want_portal
    if portal and mode != MODE_PUBLIC:
        _fail(output_format,
              "登录门口得让还没登录的人打得开，否则 302 过去只是换个地方 401。"
              "门口页面用 --public 开放。",
              "portal_needs_public")

    # A page that asks its own back end for data cannot be anonymous. The
    # anonymous zone admits GET and HEAD; that fetch is a POST, so every one of
    # them is refused and the page renders empty with nothing reporting a fault.
    # Told here rather than discovered later, because "which mode did I choose"
    # is the last thing anyone suspects when a page comes up blank.
    if mode == MODE_PUBLIC:
        where = _page_calls_backend(recipe_dir)
        if where:
            _fail(output_format,
                  f"这张页面会向自己的后端要数据（{where}），而匿名区只收 GET/HEAD——"
                  f"那个请求是 POST，开成 public 之后每一次都会被拒，页面白着但没有任何一层报错。\n"
                  f"两条路：把结果预先算成文件放进 dataDir，页面只渲染；"
                  f"或者用 --signed-in / --allow …（要一份共同的数据就再加 --shared）。",
                  "public_page_calls_backend")

    # Exposing is the moment to find out that this page cannot work anywhere but
    # here. Before this gate a page reading through the owner-only file endpoint
    # published cleanly and failed in front of the first visitor instead — the
    # error surfaced at the worst possible time, to the person least able to do
    # anything about it. The checks are text matches and say so in their own
    # docstrings; they catch the recipe that never considered the question.
    from frago.recipes import checks as recipe_checks

    findings = recipe_checks.audit(recipe_dir)
    fatal = recipe_checks.blocking(findings)
    warnings_found = [f for f in findings if f.severity == "warn"]

    if fatal:
        detail = "\n".join(f.render(recipe_dir) for f in fatal)
        headline = (
            f"这张页面有 {len(fatal)} 处在别人打开时必然失效，先改掉再开放："
        )
        if output_format == 'json':
            click.echo(json.dumps({
                "success": False,
                "error": headline,
                "code": "cannot_be_served",
                "findings": [
                    {"rule": f.rule, "severity": f.severity, "file": str(f.file),
                     "line": f.line, "excerpt": f.excerpt, "fix": f.fix}
                    for f in findings
                ],
            }, ensure_ascii=False))
        else:
            click.echo(f"Error: {headline}\n{detail}", err=True)
        sys.exit(1)

    state, notes = _publish_audit(
        name, next_slot, require_identity=mode == MODE_IDENTITY and reads == READS_OWN)

    for finding in warnings_found:
        notes.append(f"{finding.rule} — {finding.file.name}:{finding.line} {finding.fix}")

    notes.extend(_exposure_notes(
        name, recipe_dir, existing, mode, reads, allow_ids, next_slot, portal))

    if allow_ids is not None:
        audience = f"{len(allow_ids)} named account(s)"
    elif mode == MODE_IDENTITY:
        audience = "signed-in visitors"
    else:
        audience = "anonymous visitors"

    if legacy_runnable(load_exposed().get(name)):
        notes.append(
            "这条记录还带着老的 runnable=yes。它已经不授予任何东西了——"
            "页面能触发什么由配方方法上的 @action 决定。这次改写会把它抹掉。"
        )

    # The gate applies to both output formats. `--format json` is the path an
    # agent takes, and an agent is precisely the caller that should have to read
    # what it is about to expose and come back deliberately — leaving the
    # confirmation on the human-only branch put the check where it was least
    # needed and removed it where it was most.
    if not yes:
        if output_format == 'json':
            click.echo(json.dumps({
                "success": False,
                "code": "confirm_required",
                "error": (
                    f"Exposing '{name}' (slot: {next_slot}) to {audience}. "
                    "Read `notes`, then repeat with --yes."
                ),
                "recipe_name": name,
                "slot": next_slot,
                "mode": mode,
                "reads": reads,
                "notes": notes,
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        click.echo(f"Exposing '{name}' (slot: {next_slot}) to {audience}:")
        for note in notes:
            click.echo(f"  - {note}")
        click.echo()
        if not click.confirm("Expose this page on every network this server listens on?"):
            click.echo("Cancelled.")
            sys.exit(1)

    try:
        if existing is None:
            entry = mark_published(name, next_slot, mode, allow=allow_ids,
                                   reads=reads, portal=portal)
        else:
            entry = amend(name, slot=next_slot, mode=mode, allow_set=allow_ids,
                          open_to_all_signed_in=allow_ids is None,
                          reads=reads, portal=portal)
    except (ValueError, KeyError) as err:
        _fail(output_format, str(err), "refused")

    if output_format == 'json':
        click.echo(json.dumps({
            "success": True,
            "recipe_name": name,
            "slot": entry["slot"],
            "mode": entry["mode"],
            "allow": entry["allow"],
            "reads": entry["reads"],
            "portal": entry["portal"],
            "since": entry["since"],
            "path": f"/app/{name}/",
            "notes": notes,
        }, ensure_ascii=False, indent=2))
    else:
        click.echo(f"✓ Exposed at /app/{name}/")
        if mode == MODE_IDENTITY:
            click.echo("  Readers must sign in.")
        if allow_ids is not None:
            click.echo(f"  Restricted to {len(allow_ids)} named account(s).")
        if reads == READS_RECIPE and mode == MODE_IDENTITY:
            click.echo(f"  They all read the recipe's own slot '{entry['slot']}', read-only.")
        elif mode == MODE_IDENTITY:
            click.echo("  Each of them reads their own data.")
        if portal:
            click.echo("  This page is now the sign-in door.")
        click.echo("  Reverse-proxy only this prefix; everything else needs the server token.")


#: The slot name a recipe gets when nobody names one. Imported lazily elsewhere;
#: bound here so the expose command does not reach into app_state for a constant.
DEFAULT_SLOT_NAME = "default"


def _exposure_notes(name: str, recipe_dir: Path, existing: dict | None, mode: str,
                    reads: str, allow_ids: list[str] | None, slot: str,
                    portal: bool) -> list[str]:
    """What this exposure means, in the words of the decision rather than the flags."""
    from frago.recipes.checks import page_actions
    from frago.recipes.publish import MODE_IDENTITY, READS_RECIPE

    notes: list[str] = []

    if allow_ids is not None:
        notes.append(
            f"只有点名的 {len(allow_ids)} 个账号能打开。其他人——登录了也一样——"
            f"拿到的响应与「这页根本没发布」完全一致。"
        )
        held = (existing or {}).get("allow")
        if isinstance(held, list):
            going = [who for who in held if who not in allow_ids]
            coming = [who for who in allow_ids if who not in held]
            if going:
                notes.append(f"这次会移出 {len(going)} 个：{', '.join(going)}")
            if coming:
                notes.append(f"这次会加入 {len(coming)} 个：{', '.join(coming)}")
        elif existing is not None:
            notes.append("这张页面此前对所有登录用户开放，这次收窄到名单内。")
    elif mode == MODE_IDENTITY and isinstance((existing or {}).get("allow"), list):
        notes.append(
            f"注意这是放宽：原本只有 {len((existing or {})['allow'])} 个账号能开，"
            f"改完之后所有能登录的人都能开。"
        )

    if mode == MODE_IDENTITY and reads == READS_RECIPE:
        notes.append(
            f"这些人读的是配方自己那一份（app-state/<配方>/{slot}.json，路径里没有任何账号），"
            f"同一份，只读——没有人有自己的目录，所以这张页面不接受任何运行请求。"
        )
    elif mode == MODE_IDENTITY:
        notes.append(
            f"每个人读自己名下那一份（~/.frago/users/<账号id>/state/{name}.json）。"
            f"第一次打开时那份还没被写过，页面要能渲染空 state。"
        )

    actions = page_actions(recipe_dir)
    if actions:
        if mode == MODE_IDENTITY and reads != READS_RECIPE:
            notes.append(
                f"配方用 @action 开了 {'、'.join(actions)}：名单上的人能从页面触发它们。"
                f"跑的是这台机器、这个配方的凭证，产出落各人自己的目录。"
                f"会花钱、会以主人身份对外做事的 mode NEVER 标 @action。"
            )
        else:
            notes.append(
                f"配方标了 @action 的有 {'、'.join(actions)}，但这次的开放方式不给运行权，"
                f"所以页面上按不动。"
            )

    if portal:
        notes.append("这张页面会成为登录门口：没登录的人打开别的页面时会被送到这里。")

    return notes


@recipe_group.command(name='unexpose', cls=AgentFriendlyCommand)
@click.argument('name')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']), default='text')
def unexpose_recipe(name: str, output_format: str):
    """Take this recipe's page back off the public internet."""
    from frago.recipes.publish import unpublish

    removed = unpublish(name)
    if output_format == 'json':
        click.echo(json.dumps({"success": removed, "recipe_name": name}, ensure_ascii=False))
    elif removed:
        click.echo(f"✓ /app/{name}/ now requires the server token")
    else:
        click.echo(f"'{name}' was not published; nothing to do")


def _audited_json(one) -> dict:
    return {
        "recipe": one.recipe, "slot": one.slot,
        "source": str(one.source), "target": str(one.target),
        "migrated_at": one.when, "stage": one.stage,
        "reasons": list(one.reasons),
        "last_write": one.last_write, "quiet_days": one.quiet_days,
        "files": one.files, "bytes": one.size,
    }


def _report_audit(report, output_format: str, only_problems: bool, dm) -> None:
    """Print the three stages.

    `only_problems` says nothing at all when nothing is wrong, because the
    scheduled copy of this runs every day and a check that reports "fine" every
    day is a check nobody reads by the end of the week. The evidence that it
    ran is in `frago schedule history`, which is where an unattended run's
    record belongs — not in a line of output nobody was going to look at.
    """
    quiet = only_problems and report.needs_attention == 0 and report.ledger_exists

    if output_format == 'json':
        if quiet:
            return
        click.echo(json.dumps({
            "identity": report.identity,
            "ledger": str(report.ledger),
            "ledger_exists": report.ledger_exists,
            "ledger_lines": report.lines,
            "checked": len(report.checked),
            "needs_attention": report.needs_attention,
            "still_live": [_audited_json(x) for x in report.still_live],
            "ready_to_expire": [_audited_json(x) for x in report.ready],
            "sealed": [_audited_json(x) for x in report.sealed],
        }, ensure_ascii=False, indent=2))
        return

    if not report.ledger_exists:
        # Not the same as clean, and it must never be allowed to read as clean:
        # an empty result here means nothing was ever migrated, or the ledger
        # was moved — and the second one is the emergency.
        click.echo(f"账本不存在：{report.ledger}")
        click.echo("这不是「干净」——是从来没搬过，或者账本被挪走了。两种都不该沉默过去。")
        return
    if not report.checked:
        click.echo(f"账本在，{report.lines} 行，但一笔搬迁都读不出来：{report.ledger}")
        click.echo("扫过了，没有可查的对象。这和「查过、都干净」不是一回事。")
        return
    if quiet:
        return

    click.echo(f"账本 {report.lines} 行，{len(report.checked)} 笔搬迁。逐笔看现在什么状态：")

    if report.still_live:
        click.echo(f"\n【还没切干净】{len(report.still_live)} 笔——老的还在被读或被写，删不得")
        for one in report.still_live:
            click.echo(f"  {one.recipe}/{one.slot}")
            click.echo(f"    {one.source}")
            for why in one.reasons:
                click.echo(f"    · {why}")

    if report.ready:
        ripe = [x for x in report.ready if x.quiet_enough]
        click.echo(f"\n【可以定到期日】{len(report.ready)} 笔——没人碰老的了，等一个日期"
                   f"（其中静默满 {dm.QUIET_ENOUGH_DAYS} 天的 {len(ripe)} 笔）")
        for one in report.ready:
            days = f"静默 {one.quiet_days} 天" if one.quiet_days >= 0 else "空目录"
            click.echo(f"  {one.recipe}/{one.slot}  {days}  最后写入 {one.last_write or '—'}")
            click.echo(f"    {one.source}")

    if report.sealed:
        click.echo(f"\n【已封存】{len(report.sealed)} 笔——此路已封")
        for one in report.sealed:
            click.echo(f"  {one.recipe}/{one.slot}")
            click.echo(f"    {one.source}")
            for why in one.reasons:
                click.echo(f"    · {why}")

    click.echo(f"\n{len(report.checked)} 笔全扫过了，{report.needs_attention} 笔要人处理。"
               f"--audit 只读，一个字节都没动。")
    click.echo(f"账本：{report.ledger}")


@recipe_group.command(name='data-migrate', cls=AgentFriendlyCommand)
@click.option('--apply', 'do_apply', is_flag=True,
              help='Actually copy. Without it this only says what it would do.')
@click.option('--plan', 'plan_file', type=click.Path(exists=True, dir_okay=False),
              help='A JSON list of {recipe, slot?, source} for recipes that never '
                   'recorded their directory anywhere a machine can read. Goes '
                   'through the same three refusals as a derived plan.')
@click.option('--audit', 'do_audit', is_flag=True,
              help='看已经搬过的那些现在什么状态：老地方还在被写的、页面地址还指着老地方的、'
                   '源头根本不只属于一个配方的。只读，一个字节都不动。')
@click.option('--only-problems', 'only_problems', is_flag=True,
              help='配合 --audit：干净时一个字都不输出，给定时任务用。'
                   '「扫过了没事」和「根本没扫」的区别记在 frago schedule history 里，'
                   '不在这条命令的输出里。')
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']), default='text')
def data_migrate(do_apply: bool, plan_file: str | None, do_audit: bool,
                 only_problems: bool, output_format: str):
    """Move recipe data onto the layout in `frago book must-recipe-data`.

    Copies; never deletes. Every move is verified by file count and byte total
    afterwards and written to ~/.frago/migration-manifest.jsonl, and the original
    directory stays exactly where it was. Run it again after an interruption —
    anything already copied is recognised and skipped.

    Three things it refuses to move, each of which would look like a success:
    a directory two recipes both claim (copying it makes the one-thing-in-two-
    places problem it exists to fix), a dated deliverable directory that belongs
    to the other tree, and a directory inside a recipe's own package. Those are
    listed for a person to decide.

    `--audit` is the third face: not what would move, not moving it, but what
    has already moved and where it stands now. Copying without deleting leaves
    two copies of everything, and that is a state with no end unless somebody
    asks whether the old one is still being read. That question used to be
    answered by hand, by comparing timestamps.
    """
    from frago.recipes import context, data_migration

    try:
        who = context.default_identity()
    except context.NoIdentity as err:
        raise click.ClickException(str(err)) from err

    if do_audit:
        if do_apply:
            raise click.ClickException(
                '--audit 只读，--apply 要动手，一次只能是其中一件事')
        _report_audit(data_migration.audit(who), output_format, only_problems,
                      data_migration)
        return
    if only_problems:
        raise click.ClickException('--only-problems 是给 --audit 用的')

    if plan_file:
        entries = json.loads(Path(plan_file).read_text(encoding='utf-8'))
        if not isinstance(entries, list):
            raise click.ClickException(f'{plan_file} 里应当是一个数组')
        plan = data_migration.plan_from_entries(who, entries)
    else:
        plan = data_migration.plan(who)
    applied, failed = [], []
    if do_apply:
        for one in plan.moves:
            try:
                applied.append(data_migration.apply(one))
            except data_migration.MigrationFailed as err:
                failed.append({"recipe": one.recipe, "slot": one.slot, "error": str(err)})

    if output_format == 'json':
        click.echo(json.dumps({
            "identity": who,
            "applied": applied,
            "failed": failed,
            "would_move": [
                {"recipe": m.recipe, "slot": m.slot,
                 "source": str(m.source), "target": str(m.target)}
                for m in plan.moves
            ] if not do_apply else [],
            "blocked": [{"recipe": r, "slot": s, "why": w} for r, s, w in plan.blocked],
            "needs_a_person": [
                {"recipe": u.recipe, "slot": u.slot, "keys": list(u.keys)}
                for u in plan.unresolved
            ],
            "skipped": [{"recipe": r, "slot": s, "why": w} for r, s, w in plan.skipped],
            "manifest": str(data_migration.manifest_path()),
        }, ensure_ascii=False, indent=2))
        return

    if do_apply:
        for entry in applied:
            note = f"  {entry['note']}" if entry['note'] else ""
            click.echo(f"✓ {entry['recipe']}/{entry['slot']}  "
                       f"{entry['files']} files / {entry['bytes']} bytes{note}")
        for bad in failed:
            click.echo(f"✗ {bad['recipe']}/{bad['slot']}: {bad['error']}")
        click.echo(f"\n{len(applied)} copied, {len(failed)} failed. "
                   f"Originals untouched. Record: {data_migration.manifest_path()}")
    else:
        for m in plan.moves:
            click.echo(f"would copy  {m.recipe}/{m.slot}\n  {m.source}\n→ {m.target}")
        click.echo(f"\n{len(plan.moves)} would be copied. Nothing has happened; "
                   f"add --apply to do it.")

    if plan.blocked:
        click.echo(f"\n{len(plan.blocked)} need a decision before they can move:")
        for recipe, slot, why in plan.blocked:
            click.echo(f"  {recipe}/{slot}\n    {why}")
    if plan.unresolved:
        click.echo(f"\n{len(plan.unresolved)} record their directory under a name only "
                   f"the recipe knows; confirm these by hand:")
        for u in plan.unresolved:
            click.echo(f"  {u.recipe}/{u.slot}: {', '.join(u.keys)}")


@recipe_group.command(name='exposed', cls=AgentFriendlyCommand)
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']), default='text')
def list_exposed(output_format: str):
    """List the recipe pages visitors can currently reach, and on what terms."""
    from frago.recipes.contract import page_actions_of
    from frago.recipes.publish import legacy_runnable, load, published_entry, published_path

    entries = load()
    # Read back through `published_entry` so this list shows the mode the gate
    # will actually enforce, not the string in the file. An entry with a mode
    # nobody recognises is enforced as identity-only; printing it verbatim would
    # tell the owner their page is public when it is not, or the reverse.
    resolved = {name: published_entry(name) or {} for name in sorted(entries)}

    def _actions(name: str, entry: dict) -> list[str]:
        # A shared reading has no per-person directory, so it accepts nothing
        # however the recipe declared itself. Shown the way the gate answers it.
        if entry.get("mode") == "identity" and entry.get("reads") == "owner":
            return []
        return list(page_actions_of(name))

    if output_format == 'json':
        click.echo(json.dumps({
            "published": [
                {"recipe_name": n, "slot": e.get("slot", "default"),
                 "mode": e.get("mode"), "allow": e.get("allow"),
                 "reads": e.get("reads"), "portal": e.get("portal", False),
                 "actions": _actions(n, e),
                 "stale_runnable_flag": legacy_runnable(entries.get(n)),
                 "since": e.get("since"), "path": f"/app/{n}/"}
                for n, e in resolved.items()
            ],
            "source": str(published_path()),
        }, ensure_ascii=False, indent=2))
        return

    if not entries:
        click.echo("No recipe page is exposed. Everything requires the server token.")
        click.echo("Expose one with: frago recipe expose <name> --public|--signed-in|--allow <id>")
        return

    click.echo(f"{'Recipe':<30} {'Who':<16} {'Reads':<18} {'Actions':<16} Since")
    stale = []
    for name, entry in resolved.items():
        allow = entry.get("allow")
        if entry.get("mode") == "public":
            who = "anyone"
        elif allow is None:
            who = "signed-in"
        elif allow:
            who = f"{len(allow)} account(s)"
        else:
            # An empty list is unreachable through the CLI, so seeing one means
            # the file was hand-edited or damaged. Say so plainly rather than
            # printing "0 account(s)", which reads like a tidy configuration.
            who = "NOBODY (broken)"

        slot = entry.get("slot", "default")
        if entry.get("mode") == "identity" and entry.get("reads") == "own":
            reads = "each their own"
        else:
            reads = f"your '{slot}'"

        actions = _actions(name, entry)
        click.echo(
            f"{name:<30} {who:<16} {reads:<18} "
            f"{('、'.join(actions) or '-'):<16} {entry.get('since') or '?'}"
            + ("   ← 门口" if entry.get("portal") else "")
        )
        if legacy_runnable(entries.get(name)):
            stale.append(name)

    if stale:
        click.echo()
        click.echo(f"这 {len(stale)} 条还带着老的 runnable 标记，它已经不授予任何东西："
                   f"{', '.join(stale)}")
        click.echo("页面能触发什么现在写在配方的 mode 方法上（@action）。"
                   "重新 expose 一次即可把这个标记抹掉。")


@recipe_group.command(name='reads', cls=AgentFriendlyCommand)
@click.option('--format', 'output_format', type=click.Choice(['text', 'json']), default='text')
def list_reads(output_format: str):
    """Which modules read which other modules' data, and what they actually get.

    Derived from the two declarations rather than from a table somebody
    maintains, so it cannot drift from what a run will be handed: the same
    function answers both.
    """
    from frago.recipes.context import shared_with
    from frago.recipes.registry import get_registry

    registry = get_registry()
    rows = []
    for name in sorted(registry.recipes):
        try:
            recipe = registry.find(name)
        except Exception:
            continue
        declared = list(getattr(recipe.metadata, "reads_common", None) or [])
        shares = getattr(recipe.metadata, "shares", "") or ""
        if not declared and not shares:
            continue
        _, subtrees, problems = shared_with(name) if declared else (None, {}, [])
        rows.append({
            "recipe_name": name,
            "shares": shares,
            "reads": declared,
            "resolved": {k: str(v) for k, v in subtrees.items()},
            "problems": problems,
        })

    if output_format == 'json':
        click.echo(json.dumps({"reads": rows}, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo("没有任何模块共享数据，也没有任何模块声明要读别人的。")
        click.echo("被读的一方在 recipe.md 写 shares: <子路径>，读的一方写 reads_common: [<名字>]。")
        return

    for row in rows:
        if row["shares"]:
            click.echo(f"{row['recipe_name']}  共享  {row['shares']}（只读）")
        for one in row["reads"]:
            if one == row["recipe_name"]:
                # Reading its own shared block. Listed rather than hidden — the
                # recipes that compute a machine-level result do declare it —
                # but it is not a dependency: the platform hands a module its
                # own tree on every run, sharing or no sharing.
                click.echo(f"{row['recipe_name']}  读  自己那一份（平台本来就交给它）")
                continue
            got = row["resolved"].get(one)
            click.echo(f"{row['recipe_name']}  读  {one}"
                       + (f"  →  {got}" if got else "  →  拿不到"))
        for problem in row["problems"]:
            click.echo(f"    {problem}")


def _scan_module_contract(content: str, recipe_name: str) -> tuple[list[str], list[str]]:
    """Check a recipe against the module contract: born here, built on the base.

    Separate from the data-location scan because these two answer different
    questions. That one asks "does this file do the wrong thing"; this one asks
    "is this file a module at all". A file that never inherited the contract
    cannot violate it — it simply is not part of the system, and reporting it
    as a set of individual infractions would bury the one fact that matters.
    """
    import ast

    from frago.recipes.birth import Birth, check

    errors: list[str] = []
    warnings: list[str] = []

    state, why = check(recipe_name, content)
    if state == Birth.UNMARKED:
        # Reported, not refused: three hundred recipes were written before the
        # contract and the machine does not stop for it. But the word matters —
        # calling these "legacy" would hand not-converting a permanent licence,
        # and there is no such category. They are unconverted, which is a state
        # with an end. "Never checked" must never read as "checked and fine".
        warnings.append(f"尚未改造（还没建在基类上）：{why}")
        return errors, warnings
    if state == Birth.NEWER:
        errors.append(why)
        return errors, warnings

    try:
        tree = ast.parse(content)
    except SyntaxError as err:
        errors.append(f"这个文件解析不了：{err}")
        return errors, warnings

    subclass = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            isinstance(b, ast.Name) and b.id == "Recipe" for b in node.bases
        ):
            subclass = node
            break
    if subclass is None:
        errors.append(
            "带着出生号，却没有继承 Recipe。配方能力 MUST 建在基类上——"
            "落点、消息、跨模块调用、页面发布都在那里，绕过它就是把这四件事"
            "再各自实现一遍，而三百份各自的实现正是这轮要收拾的东西。"
        )
        return errors, warnings

    declared: dict[str, ast.expr] = {}
    methods: set[str] = set()
    for stmt in subclass.body:
        if isinstance(stmt, ast.FunctionDef):
            methods.add(stmt.name)
        targets = (
            [stmt.target] if isinstance(stmt, ast.AnnAssign)
            else getattr(stmt, "targets", [])
        )
        for t in targets:
            if isinstance(t, ast.Name):
                declared[t.id] = getattr(stmt, "value", None)

    if "name" not in declared:
        errors.append(
            "类上没有声明 name。页面、落点、总线都按这个名字找它，没声明平台只能猜。"
        )

    name_node = declared.get("name")
    if isinstance(name_node, ast.Constant) and name_node.value != recipe_name:
        errors.append(
            f"类里的 name 是 {name_node.value!r}，目录叫 {recipe_name!r}。"
            f"两者 MUST 一致——页面、落点、总线都按这个名字找它。"
        )

    # What this module opened and to whom, read off the marks on its methods.
    # Everything wrong with that declaration is the recipe author's mistake and
    # this is the one place they are looking, which is the whole reason it moved
    # here: a `page_actions` entry naming a mode that did not exist used to
    # raise nothing at all and surface as a 403 on a server, in front of a
    # stranger, days later.
    from frago.recipes.contract import read_source

    surface = read_source(content)
    if surface is not None:
        errors.extend(surface.problems)
        if not surface.modes:
            errors.append(
                "一个 mode_* 方法都没有。模块靠 mode 对外说话，没有 mode 就没有"
                "任何人能让它做任何事。"
            )

    if "main" in methods:
        warnings.append("覆盖了 main：那是基类的入口，改了消息形状和退出码就不再统一。")

    if not any(
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "main"
        for n in tree.body
    ):
        errors.append(
            "文件底部没有 <类名>.main()。没有它这个文件跑起来什么都不做，"
            "而它会安安静静地退出码 0——看起来像成功。"
        )

    return errors, warnings
