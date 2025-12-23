"""dev-pack command - Sync user directory resources to package directory (for PyPI distribution)"""

import fnmatch
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

import click
import yaml

from frago.tools.sync import CommandSync, RecipeSync, SkillSync


# Manifest file path (in the same directory as this file)
MANIFEST_FILE = Path(__file__).parent / "pack-manifest.yaml"


def load_manifest() -> Dict[str, Any]:
    """Load packaging manifest configuration"""
    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(f"Manifest file not found: {MANIFEST_FILE}")

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    return manifest or {}


def match_pattern(name: str, patterns: List[str]) -> bool:
    """Check if name matches any pattern"""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


@click.command(name="dev-pack")
@click.option(
    "--files",
    type=str,
    default=None,
    help="Filter names with wildcard pattern, e.g. *stock* or clipboard*",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Only show operations that would be performed, do not actually sync",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    help="Clean files in target directory that are not in manifest",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed information",
)
@click.option(
    "--commands-only",
    is_flag=True,
    help="Sync commands only (skip recipes)",
)
@click.option(
    "--recipes-only",
    is_flag=True,
    help="Sync recipes only (skip commands and skills)",
)
@click.option(
    "--skills-only",
    is_flag=True,
    help="Sync skills only (skip commands and recipes)",
)
@click.option(
    "--all",
    "sync_all",
    is_flag=True,
    help="Ignore manifest, sync all resources (for debugging)",
)
def dev_pack(
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
    commands_only: bool,
    recipes_only: bool,
    skills_only: bool,
    sync_all: bool,
):
    """
    Sync user directory resources to package directory (for PyPI distribution)

    Based on pack-manifest.yaml whitelist configuration, sync allowed resources
    from user directory to src/frago/resources/ for packaging and distribution.

    Source directories:
      ~/.claude/commands/frago.*.md  → src/frago/resources/commands/
      ~/.claude/skills/frago-*       → src/frago/resources/skills/
      ~/.frago/recipes/              → src/frago/resources/recipes/

    \b
    Examples:
      frago dev-pack                    # Sync resources according to manifest
      frago dev-pack --all              # Ignore manifest, sync all
      frago dev-pack --commands-only    # Sync commands only
      frago dev-pack --recipes-only     # Sync recipes only
      frago dev-pack --skills-only      # Sync skills only
      frago dev-pack --files "*stock*"  # Additional filtering
      frago dev-pack --dry-run          # Preview files to be synced
      frago dev-pack --clean            # Clean resources not in manifest
    """
    try:
        # Load manifest
        if sync_all:
            manifest = {"commands": ["*"], "skills": ["*"], "recipes": ["*"]}
            click.echo("[!]  Ignoring manifest, syncing all resources\n")
        else:
            manifest = load_manifest()
            click.echo(f"📋 Manifest file: {MANIFEST_FILE.name}\n")

        # Determine sync scope
        sync_commands = not recipes_only and not skills_only
        sync_skills = not commands_only and not recipes_only
        sync_recipes = not commands_only and not skills_only

        if dry_run:
            click.echo("=== Dry Run Mode ===\n")

        # Sync Commands
        if sync_commands:
            _sync_commands(manifest, files, dry_run, do_clean, verbose)

        # Sync Skills
        if sync_skills:
            if sync_commands:
                click.echo()  # Separator
            _sync_skills(manifest, files, dry_run, do_clean, verbose)

        # Sync Recipes
        if sync_recipes:
            if sync_commands or sync_skills:
                click.echo()  # Separator
            _sync_recipes(manifest, files, dry_run, do_clean, verbose)

        if dry_run:
            click.echo("\n(Dry Run mode, no actual operations performed)")

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _sync_commands(
    manifest: Dict[str, Any],
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """Sync commands"""
    syncer = CommandSync()
    allowed_patterns = manifest.get("commands", [])

    # Check if source directory exists
    if not syncer.source_dir.exists():
        click.echo(f"Commands source directory not found: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Commands Sync")

    if not allowed_patterns:
        click.echo("  No commands configured in manifest, skipping")
        return

    if do_clean:
        # Clean mode: delete files not in manifest
        removed = syncer.clean(dry_run=dry_run)
        if removed:
            action_word = "Will delete" if dry_run else "Deleted"
            click.echo(f"  {action_word} {len(removed)} files:")
            for path in removed:
                click.echo(f"    - {path.name}")
        else:
            click.echo("  No command files to clean")
        return

    # Sync mode
    results = syncer.sync(pattern=files, dry_run=dry_run, verbose=verbose)

    if not results:
        if files:
            click.echo(f"  No commands found matching '{files}'")
        else:
            click.echo("  No frago.*.md command files found")
        return

    # Filter by manifest
    filtered_results = []
    excluded = []
    for r in results:
        source_name = r["source_name"]
        if match_pattern(source_name, allowed_patterns):
            filtered_results.append(r)
        else:
            excluded.append(r)

    # Statistics
    created = [r for r in filtered_results if r["action"] == "create"]
    updated = [r for r in filtered_results if r["action"] == "update"]
    skipped = [r for r in filtered_results if r["action"] == "skip"]

    action_word = "Will" if dry_run else ""

    # Display results
    if created:
        click.echo(f"  [OK] {action_word}Created {len(created)} commands:")
        for r in created:
            click.echo(f"    + {r['source_name']} → {r['target_name']}")

    if updated:
        click.echo(f"  [OK] {action_word}Updated {len(updated)} commands:")
        for r in updated:
            click.echo(f"    ~ {r['source_name']} → {r['target_name']}")

    if skipped and verbose:
        click.echo(f"  - Skipped {len(skipped)} unchanged commands:")
        for r in skipped:
            click.echo(f"    = {r['source_name']}")

    if excluded and verbose:
        click.echo(f"  ⊘ Excluded {len(excluded)} commands by manifest:")
        for r in excluded:
            click.echo(f"    ⊘ {r['source_name']}")

    # Summary
    click.echo(
        f"  Total: {len(created)} created, {len(updated)} updated, {len(skipped)} skipped"
        + (f", {len(excluded)} excluded" if excluded else "")
    )

    # Sync frago/ subdirectory
    _sync_frago_subdir(syncer, manifest, dry_run, verbose)


def _sync_frago_subdir(
    syncer: CommandSync,
    manifest: Dict[str, Any],
    dry_run: bool,
    verbose: bool,
):
    """Sync frago/ subdirectory"""
    import shutil

    allowed_patterns = manifest.get("commands", [])

    # Check if frago/* or frago/ is allowed
    frago_allowed = any(
        p.startswith("frago/") or p == "frago/*"
        for p in allowed_patterns
    )

    if not frago_allowed:
        if verbose:
            click.echo("  ⊘ frago/ subdirectory not in manifest")
        return

    frago_source = syncer.source_dir / "frago"
    frago_target = syncer.target_dir / "frago"

    if not frago_source.exists():
        return

    # Check if update is needed
    needs_update = not frago_target.exists()

    if not needs_update:
        for src_file in frago_source.rglob("*"):
            if src_file.is_file():
                rel_path = src_file.relative_to(frago_source)
                target_file = frago_target / rel_path
                if not target_file.exists() or src_file.stat().st_mtime > target_file.stat().st_mtime:
                    needs_update = True
                    break

    action_word = "Will sync" if dry_run else "Synced"

    if needs_update:
        if not dry_run:
            if frago_target.exists():
                shutil.rmtree(frago_target)
            shutil.copytree(
                frago_source,
                frago_target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        click.echo(f"  [OK] {action_word} frago/ subdirectory")
    else:
        if verbose:
            click.echo("  - frago/ subdirectory unchanged")


def _sync_skills(
    manifest: Dict[str, Any],
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """Sync skills"""
    import shutil

    syncer = SkillSync()
    allowed_patterns = manifest.get("skills", [])

    # Check if source directory exists
    if not syncer.source_dir.exists():
        click.echo(f"Skills source directory not found: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Skills Sync")

    if not allowed_patterns:
        click.echo("  No skills configured in manifest, skipping")
        return

    if do_clean:
        # Clean mode
        removed = syncer.clean(dry_run=dry_run)
        if removed:
            action_word = "Will delete" if dry_run else "Deleted"
            click.echo(f"  {action_word} {len(removed)} Skills:")
            for path in removed:
                click.echo(f"    - {path.name}")
        else:
            click.echo("  No Skills to clean")
        return

    # Get all skills (without copying)
    skill_dirs = syncer.find_skills(pattern=files)

    if not skill_dirs:
        if files:
            click.echo(f"  No Skills found matching '{files}'")
        else:
            click.echo("  No Skills found")
        return

    # Filter by manifest first, then decide whether to sync
    filtered_dirs = []
    excluded = []
    for skill_dir in skill_dirs:
        skill_name = skill_dir.name

        if match_pattern(skill_name, allowed_patterns):
            filtered_dirs.append(skill_dir)
        else:
            excluded.append(skill_name)

    # Perform sync on filtered skills
    created = []
    updated = []
    skipped = []

    for skill_dir in filtered_dirs:
        skill_name = skill_dir.name
        target_dir = syncer.target_dir / skill_name

        # Determine operation type
        if target_dir.exists():
            needs_update = False
            for src_file in skill_dir.rglob("*"):
                if src_file.is_file() and "__pycache__" not in str(src_file):
                    rel_file = src_file.relative_to(skill_dir)
                    tgt_file = target_dir / rel_file
                    if not tgt_file.exists() or src_file.stat().st_mtime > tgt_file.stat().st_mtime:
                        needs_update = True
                        break
            action = "update" if needs_update else "skip"
        else:
            action = "create"

        result = {
            "skill_name": skill_name,
            "source_dir": skill_dir,
            "target_dir": target_dir,
            "action": action,
        }

        if action == "skip":
            skipped.append(result)
            continue

        # Execute copy
        if not dry_run:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                skill_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

        if action == "create":
            created.append(result)
        else:
            updated.append(result)

    action_word = "Will" if dry_run else ""

    # Display results
    if created:
        click.echo(f"  [OK] {action_word}Created {len(created)} Skills:")
        for r in created:
            click.echo(f"    + {r['skill_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if updated:
        click.echo(f"  [OK] {action_word}Updated {len(updated)} Skills:")
        for r in updated:
            click.echo(f"    ~ {r['skill_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if skipped and verbose:
        click.echo(f"  - Skipped {len(skipped)} unchanged Skills:")
        for r in skipped:
            click.echo(f"    = {r['skill_name']}")

    if excluded and verbose:
        click.echo(f"  ⊘ Excluded {len(excluded)} Skills by manifest:")
        for name in excluded:
            click.echo(f"    ⊘ {name}")

    # Summary
    click.echo(
        f"  Total: {len(created)} created, {len(updated)} updated, {len(skipped)} skipped"
        + (f", {len(excluded)} excluded" if excluded else "")
    )


def _sync_recipes(
    manifest: Dict[str, Any],
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """Sync recipes"""
    import shutil

    syncer = RecipeSync()
    allowed_patterns = manifest.get("recipes", [])

    # Check if source directory exists
    if not syncer.source_dir.exists():
        click.echo(f"Recipes source directory not found: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Recipes Sync")

    if not allowed_patterns:
        click.echo("  No recipes configured in manifest, skipping")
        return

    if do_clean:
        # Clean mode
        removed = syncer.clean(dry_run=dry_run)
        if removed:
            action_word = "Will delete" if dry_run else "Deleted"
            click.echo(f"  {action_word} {len(removed)} Recipes:")
            for path in removed:
                click.echo(f"    - {path.name}")
        else:
            click.echo("  No Recipes to clean")
        return

    # Get all recipes (without copying)
    recipe_dirs = syncer.find_recipes(pattern=files)

    if not recipe_dirs:
        if files:
            click.echo(f"  No Recipes found matching '{files}'")
        else:
            click.echo("  No Recipes found")
        return

    # Filter by manifest first, then decide whether to sync
    filtered_dirs = []
    excluded = []
    for recipe_dir in recipe_dirs:
        rel_path = recipe_dir.relative_to(syncer.source_dir)
        rel_path_str = str(rel_path)

        if match_pattern(rel_path_str, allowed_patterns):
            filtered_dirs.append(recipe_dir)
        else:
            excluded.append(rel_path_str)

    # Perform sync on filtered recipes
    created = []
    updated = []
    skipped = []

    for recipe_dir in filtered_dirs:
        rel_path = recipe_dir.relative_to(syncer.source_dir)
        recipe_name = recipe_dir.name
        target_dir = syncer.target_dir / rel_path

        # Determine operation type
        if target_dir.exists():
            needs_update = False
            for src_file in recipe_dir.rglob("*"):
                if src_file.is_file() and "__pycache__" not in str(src_file):
                    rel_file = src_file.relative_to(recipe_dir)
                    tgt_file = target_dir / rel_file
                    if not tgt_file.exists() or src_file.stat().st_mtime > tgt_file.stat().st_mtime:
                        needs_update = True
                        break
            action = "update" if needs_update else "skip"
        else:
            action = "create"

        result = {
            "recipe_name": recipe_name,
            "source_dir": recipe_dir,
            "target_dir": target_dir,
            "action": action,
        }

        if action == "skip":
            skipped.append(result)
            continue

        # Execute copy
        if not dry_run:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                recipe_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

        if action == "create":
            created.append(result)
        else:
            updated.append(result)

    action_word = "Will" if dry_run else ""

    # Display results
    if created:
        click.echo(f"  [OK] {action_word}Created {len(created)} Recipes:")
        for r in created:
            click.echo(f"    + {r['recipe_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if updated:
        click.echo(f"  [OK] {action_word}Updated {len(updated)} Recipes:")
        for r in updated:
            click.echo(f"    ~ {r['recipe_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if skipped and verbose:
        click.echo(f"  - Skipped {len(skipped)} unchanged Recipes:")
        for r in skipped:
            click.echo(f"    = {r['recipe_name']}")

    if excluded and verbose:
        click.echo(f"  ⊘ Excluded {len(excluded)} Recipes by manifest:")
        for name in excluded:
            click.echo(f"    ⊘ {name}")

    # Summary
    click.echo(
        f"  Total: {len(created)} created, {len(updated)} updated, {len(skipped)} skipped"
        + (f", {len(excluded)} excluded" if excluded else "")
    )
