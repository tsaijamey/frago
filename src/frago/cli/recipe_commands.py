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


@recipe_group.command(name='install')
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
def install_recipe(source: str, force: bool, name_override: Optional[str], output_format: str):
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
    from frago.recipes.installer import RecipeInstaller
    from frago.recipes.exceptions import RecipeAlreadyExistsError, RecipeInstallError

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


@recipe_group.command(name='uninstall')
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
def uninstall_recipe(name: str, yes: bool, output_format: str):
    """
    Uninstall an installed recipe

    \b
    Examples:
      frago recipe uninstall stock-monitor
      frago recipe uninstall stock-monitor --yes
    """
    from frago.recipes.installer import RecipeInstaller

    installer = RecipeInstaller()

    # Check if recipe exists
    installed = installer.manifest.recipes.get(name)
    if not installed and not installer._find_installed_recipe(name):
        if output_format == 'json':
            result = {"success": False, "error": f"Recipe '{name}' not found", "code": "not_found"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: Recipe '{name}' not found in community-recipes", err=True)
        sys.exit(1)

    # Confirm
    if not yes and output_format != 'json':
        if not click.confirm(f"Uninstall recipe '{name}'?"):
            click.echo("Cancelled")
            return

    if installer.uninstall(name):
        if output_format == 'json':
            result = {"success": True, "recipe_name": name}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"[OK] Recipe '{name}' uninstalled")
    else:
        if output_format == 'json':
            result = {"success": False, "error": "Uninstall failed", "code": "uninstall_error"}
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Error: Failed to uninstall '{name}'", err=True)
        sys.exit(1)


@recipe_group.command(name='update')
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
def update_recipe(name: Optional[str], update_all: bool, output_format: str):
    """
    Update installed recipes by re-fetching from original source

    \b
    Examples:
      frago recipe update stock-monitor
      frago recipe update --all
    """
    from frago.recipes.installer import RecipeInstaller
    from frago.recipes.exceptions import RecipeInstallError

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


@recipe_group.command(name='search')
@click.argument('query', required=False)
@click.option(
    '--format',
    'output_format',
    type=click.Choice(['table', 'json'], case_sensitive=False),
    default='table',
    help='Output format'
)
def search_recipes(query: Optional[str], output_format: str):
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
            description = recipe.get('description', '')[:40]
            click.echo(f"{name:<30} {version:<10} {recipe_type:<10} {description}")

        click.echo()
        click.echo(f"Found {len(results)} recipe(s)")
        click.echo("Install with: frago recipe install community:<name>")


@recipe_group.command(name='share')
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
            encoding='utf-8'
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
                    if p.lower() == 'as':
                        if i + 1 < len(parts):
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
