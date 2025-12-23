"""Recipe management commands"""
import json
import sys
from pathlib import Path
from typing import Optional

import click

from frago.recipes import RecipeRegistry, RecipeRunner, OutputHandler
from frago.recipes.exceptions import RecipeError, MetadataParseError, RecipeValidationError
from frago.recipes.metadata import parse_metadata_file, validate_metadata
from .agent_friendly import AgentFriendlyGroup


@click.group(name='recipe', cls=AgentFriendlyGroup)
def recipe_group():
    """Recipe management command group"""
    pass


@recipe_group.command(name='list')
@click.option(
    '--source',
    type=click.Choice(['project', 'user', 'example', 'all'], case_sensitive=False),
    default='all',
    help='Filter by source'
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
        if source != 'all':
            # When source is specified, get recipes from that source directly
            recipes = registry.get_by_source(source)
        else:
            # When source is not specified, return the highest priority version of each recipe
            recipes = registry.list_all()

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
            click.echo("─" * 80)
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

    except RecipeError as e:
        click.echo(f"Error: {e}", err=True)


@recipe_group.command(name='info')
@click.argument('name')
@click.option(
    '--source',
    type=click.Choice(['project', 'user', 'example'], case_sensitive=False),
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
def recipe_info(name: str, source: Optional[str], output_format: str):
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
                "env": recipe.metadata.env,
                "examples": examples,
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        else:  # text
            m = recipe.metadata
            click.echo(f"Recipe: {m.name}")
            click.echo("=" * 50)
            click.echo()
            click.echo("Basic Information")
            click.echo("─" * 50)
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
            click.echo("─" * 50)
            click.echo(m.description)
            click.echo()
            if m.use_cases:
                click.echo("Use Cases")
                click.echo("─" * 50)
                for case in m.use_cases:
                    click.echo(f"- {case}")
                click.echo()
            if m.tags:
                click.echo("Tags")
                click.echo("─" * 50)
                click.echo(", ".join(m.tags))
                click.echo()
            click.echo("Output Targets")
            click.echo("─" * 50)
            click.echo(", ".join(m.output_targets))
            click.echo()
            if m.inputs:
                click.echo("Input Parameters")
                click.echo("─" * 50)
                for param_name, param_def in m.inputs.items():
                    required = "required" if param_def.get('required', False) else "optional"
                    param_type = param_def.get('type', 'unknown')
                    desc = param_def.get('description', '')
                    click.echo(f"- {param_name} ({param_type}, {required}): {desc}")
                click.echo()
            if m.env:
                click.echo("Environment Variables")
                click.echo("─" * 50)
                for env_name, env_def in m.env.items():
                    required = "required" if env_def.get('required', False) else "optional"
                    default = env_def.get('default', '')
                    desc = env_def.get('description', '')
                    if default:
                        click.echo(f"- {env_name} ({required}, default: {default}): {desc}")
                    else:
                        click.echo(f"- {env_name} ({required}): {desc}")
                click.echo()
            if m.dependencies:
                click.echo("Dependencies")
                click.echo("─" * 50)
                click.echo(", ".join(m.dependencies))
                click.echo()
            else:
                click.echo("Dependencies")
                click.echo("─" * 50)
                click.echo("None")
                click.echo()

            # Display example files
            examples = recipe.list_examples()
            click.echo("Example Files")
            click.echo("─" * 50)
            if examples:
                for example in examples:
                    click.echo(f"- {example.name}")
            else:
                click.echo("None")

    except RecipeError as e:
        click.echo(f"Error: {e}", err=True)


@recipe_group.command(name='run')
@click.argument('name')
@click.option(
    '--source',
    type=click.Choice(['project', 'user', 'example'], case_sensitive=False),
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
def run_recipe(
    name: str,
    source: Optional[str],
    params: str,
    params_file: Optional[str],
    env_vars: tuple,
    output_file: Optional[str],
    output_clipboard: bool,
    timeout: int
):
    """Execute specified recipe"""
    try:
        # Parse parameters
        if params_file:
            with open(params_file, 'r', encoding='utf-8') as f:
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

        # Handle output
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

    except RecipeError as e:
        click.echo(f"Error: {e}", err=True)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@recipe_group.command('validate')
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
            elif metadata.runtime == 'chrome-js':
                # Simple JavaScript check: whether it contains basic structure
                if 'return' not in content and 'console' not in content:
                    warnings.append("JavaScript script does not contain return statement or console output")

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
