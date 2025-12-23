"""
Resource Installation Module

Provides resource installation functionality for frago init command:
- Install Claude Code slash commands to ~/.claude/commands/
- Install example recipes to ~/.frago/recipes/
"""

import shutil
from pathlib import Path
from typing import Optional

from frago.init.models import InstallResult, ResourceStatus, ResourceType


# Resource installation target paths
INSTALL_TARGETS = {
    "commands": Path.home() / ".claude" / "commands",
    "skills": Path.home() / ".claude" / "skills",
    "recipes": Path.home() / ".frago" / "recipes",
}


def get_package_resources_path(resource_type: str) -> Path:
    """
    Get package resource directory path

    Args:
        resource_type: Resource type ("commands", "skills", "recipes")

    Returns:
        Path object of the resource directory

    Raises:
        ValueError: Invalid resource type
        FileNotFoundError: Resource directory does not exist
    """
    valid_types = ("commands", "skills", "recipes")
    if resource_type not in valid_types:
        raise ValueError(f"Invalid resource type: {resource_type}, valid values: {valid_types}")

    # Use importlib.resources to get package resource path
    try:
        from importlib.resources import files
        package_files = files("frago.resources")
        resource_path = package_files.joinpath(resource_type)
        # Convert to Path (compatible with dev and installed environments)
        return Path(str(resource_path))
    except (ImportError, FileNotFoundError, AttributeError):
        # Fallback: use relative path in development environment
        import frago.resources
        base_path = Path(frago.resources.__file__).parent
        resource_path = base_path / resource_type
        if not resource_path.exists():
            raise FileNotFoundError(f"Resource directory does not exist: {resource_path}")
        return resource_path


def get_target_path(resource_type: str) -> Path:
    """
    Get resource installation target directory

    Args:
        resource_type: Resource type ("commands", "skills", "recipes")

    Returns:
        Path object of the target directory

    Raises:
        ValueError: Invalid resource type
    """
    if resource_type not in INSTALL_TARGETS:
        raise ValueError(f"Invalid resource type: {resource_type}")
    return INSTALL_TARGETS[resource_type]


def install_commands(source_dir: Optional[Path] = None, target_dir: Optional[Path] = None) -> InstallResult:
    """
    Install Claude Code slash commands (always overwrites)

    Args:
        source_dir: Source directory, defaults to package resources
        target_dir: Target directory, defaults to ~/.claude/commands/

    Returns:
        InstallResult containing installation results
    """
    result = InstallResult(resource_type=ResourceType.COMMAND)

    try:
        if source_dir is None:
            source_dir = get_package_resources_path("commands")
        if target_dir is None:
            target_dir = get_target_path("commands")

        # Check if source directory exists and has content
        if not source_dir.exists():
            result.errors.append(f"Source resource directory does not exist: {source_dir}")
            return result

        command_files = list(source_dir.glob("frago.*.md"))
        if not command_files:
            result.errors.append(f"Source resource directory is empty or corrupted: no frago.*.md files in {source_dir}")
            return result

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy all frago.*.md files (always overwrite)
        for src_file in command_files:
            target_file = target_dir / src_file.name
            shutil.copy2(src_file, target_file)
            result.installed.append(src_file.name)

        # Copy frago/ subdirectory (if exists)
        frago_subdir = source_dir / "frago"
        if frago_subdir.exists() and frago_subdir.is_dir():
            target_frago_dir = target_dir / "frago"
            if target_frago_dir.exists():
                shutil.rmtree(target_frago_dir)
            shutil.copytree(
                frago_subdir,
                target_frago_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            result.installed.append("frago/ (subdirectory)")

    except FileNotFoundError as e:
        result.errors.append(f"Resource directory does not exist: {e}")
    except PermissionError as e:
        result.errors.append(f"Permission error: Cannot write to {target_dir}, please check directory permissions")
    except Exception as e:
        result.errors.append(f"Error installing commands: {e}")

    return result


def install_skills(
    source_dir: Optional[Path] = None,
    target_dir: Optional[Path] = None,
    force_update: bool = False,
) -> InstallResult:
    """
    Install Claude Code skills (by default only on first install, does not overwrite existing directories)

    Args:
        source_dir: Source directory, defaults to package resources
        target_dir: Target directory, defaults to ~/.claude/skills/
        force_update: Whether to force update (overwrite existing directories)

    Returns:
        InstallResult containing lists of installed and skipped skills
    """
    result = InstallResult(resource_type=ResourceType.SKILL)

    try:
        if source_dir is None:
            source_dir = get_package_resources_path("skills")
        if target_dir is None:
            target_dir = get_target_path("skills")

        # Check if source directory exists
        if not source_dir.exists():
            result.errors.append(f"Source resource directory does not exist: {source_dir}")
            return result

        # Find all skill directories (directories containing SKILL.md)
        skill_dirs = []
        for skill_dir in source_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skill_dirs.append(skill_dir)

        if not skill_dirs:
            result.errors.append(f"Source resource directory is empty or corrupted: no valid skills in {source_dir}")
            return result

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy skill directories
        for src_skill_dir in skill_dirs:
            skill_name = src_skill_dir.name
            target_skill_dir = target_dir / skill_name

            if target_skill_dir.exists() and not force_update:
                # Directory exists and not in force update mode, skip
                result.skipped.append(skill_name)
            elif target_skill_dir.exists() and force_update:
                # Force update mode, delete then copy
                shutil.rmtree(target_skill_dir)
                shutil.copytree(
                    src_skill_dir,
                    target_skill_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                result.installed.append(skill_name)
            else:
                # New directory, copy directly
                shutil.copytree(
                    src_skill_dir,
                    target_skill_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                result.installed.append(skill_name)

    except FileNotFoundError as e:
        result.errors.append(f"Resource directory does not exist: {e}")
    except PermissionError as e:
        result.errors.append(f"Permission error: Cannot write to {target_dir}, please check directory permissions")
    except Exception as e:
        result.errors.append(f"Error installing skills: {e}")

    return result


def install_recipes(
    source_dir: Optional[Path] = None,
    target_dir: Optional[Path] = None,
    force_update: bool = False,
) -> InstallResult:
    """
    Install example recipes (by default only on first install, does not overwrite existing files)

    Args:
        source_dir: Source directory, defaults to package resources
        target_dir: Target directory, defaults to ~/.frago/recipes/
        force_update: Whether to force update (overwrite existing files, will backup first)

    Returns:
        InstallResult containing lists of installed, skipped, and backed up files
    """
    result = InstallResult(resource_type=ResourceType.RECIPE)

    try:
        if source_dir is None:
            source_dir = get_package_resources_path("recipes")
        if target_dir is None:
            target_dir = get_target_path("recipes")

        # Check if source directory exists
        if not source_dir.exists():
            result.errors.append(f"Source resource directory does not exist: {source_dir}")
            return result

        # Check if source directory has content
        recipe_files = list(source_dir.rglob("*"))
        if not any(f.is_file() for f in recipe_files):
            result.errors.append(f"Source resource directory is empty or corrupted: no files in {source_dir}")
            return result

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Traverse all files in source directory
        for src_file in source_dir.rglob("*"):
            if src_file.is_file():
                # Calculate relative path
                rel_path = src_file.relative_to(source_dir)
                target_file = target_dir / rel_path

                if target_file.exists() and not force_update:
                    # File exists and not in force update mode, skip
                    result.skipped.append(str(rel_path))
                elif target_file.exists() and force_update:
                    # Force update mode, backup then overwrite
                    backup_file = target_file.with_suffix(target_file.suffix + ".bak")
                    shutil.copy2(target_file, backup_file)
                    result.backed_up.append(str(rel_path))
                    shutil.copy2(src_file, target_file)
                    result.installed.append(str(rel_path))
                else:
                    # New file, install directly
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, target_file)
                    result.installed.append(str(rel_path))

    except FileNotFoundError as e:
        result.errors.append(f"Resource directory does not exist: {e}")
    except PermissionError as e:
        result.errors.append(f"Permission error: Cannot write to {target_dir}, please check directory permissions")
    except Exception as e:
        result.errors.append(f"Error installing recipes: {e}")

    return result


def install_all_resources(skip_recipes: bool = False, force_update: bool = False) -> ResourceStatus:
    """
    Install all resources (main entry point)

    Args:
        skip_recipes: Whether to skip recipe installation
        force_update: Whether to force update all resources

    Returns:
        ResourceStatus containing installation status of all resources
    """
    from datetime import datetime
    from frago import __version__

    status = ResourceStatus(
        frago_version=__version__,
        install_time=datetime.now(),
    )

    # Install slash commands (always overwrite)
    status.commands = install_commands()

    # Install skills
    status.skills = install_skills(force_update=force_update)

    # Install example recipes (optional)
    if not skip_recipes:
        status.recipes = install_recipes(force_update=force_update)

    return status


def format_install_summary(status: ResourceStatus) -> str:
    """
    Format installation summary output

    Args:
        status: Resource installation status

    Returns:
        Formatted summary string
    """
    lines = []

    # Commands summary
    if status.commands:
        cmd = status.commands
        if cmd.installed:
            lines.append("[*] Installing Claude Code commands...")
            for name in cmd.installed:
                lines.append(f"  [OK] {name}")
        if cmd.errors:
            for error in cmd.errors:
                lines.append(f"  [X] {error}")

    # Skills summary
    if status.skills:
        skill = status.skills
        if skill.installed or skill.skipped:
            lines.append("\n[*] Installing Claude Code Skills...")
            for name in skill.installed:
                lines.append(f"  [OK] {name}")
            for name in skill.skipped:
                lines.append(f"  ⏭️  {name} (already exists)")
        if skill.errors:
            for error in skill.errors:
                lines.append(f"  [X] {error}")

    # Recipes summary
    if status.recipes:
        rec = status.recipes
        if rec.installed or rec.skipped or rec.backed_up:
            lines.append("\n[*] Installing example Recipes...")
            for name in rec.installed:
                if name in rec.backed_up:
                    lines.append(f"  🔄 {name} (updated, old file backed up as .bak)")
                else:
                    lines.append(f"  [OK] {name}")
            for name in rec.skipped:
                lines.append(f"  ⏭️  {name} (already exists)")
        if rec.errors:
            for error in rec.errors:
                lines.append(f"  [X] {error}")

    # Totals
    total_installed = 0
    total_skipped = 0
    total_backed_up = 0
    if status.commands:
        total_installed += len(status.commands.installed)
    if status.skills:
        total_installed += len(status.skills.installed)
        total_skipped += len(status.skills.skipped)
    if status.recipes:
        total_installed += len(status.recipes.installed)
        total_skipped += len(status.recipes.skipped)
        total_backed_up += len(status.recipes.backed_up)

    if total_installed > 0 or total_skipped > 0:
        summary_parts = [f"{total_installed} files installed"]
        if total_backed_up > 0:
            summary_parts.append(f"{total_backed_up} backed up")
        if total_skipped > 0:
            summary_parts.append(f"{total_skipped} skipped")
        lines.append(f"\n[OK] Resource installation complete ({', '.join(summary_parts)})")

    return "\n".join(lines)


def count_installed_commands(target_dir: Optional[Path] = None) -> int:
    """
    Count installed frago commands

    Args:
        target_dir: Target directory, defaults to ~/.claude/commands/

    Returns:
        Number of installed frago.*.md files
    """
    if target_dir is None:
        target_dir = get_target_path("commands")

    if not target_dir.exists():
        return 0

    return len(list(target_dir.glob("frago.*.md")))


def count_installed_recipes(target_dir: Optional[Path] = None) -> int:
    """
    Count installed recipes

    Args:
        target_dir: Target directory, defaults to ~/.frago/recipes/

    Returns:
        Number of installed recipe files (.md metadata files)
    """
    if target_dir is None:
        target_dir = get_target_path("recipes")

    if not target_dir.exists():
        return 0

    # Count .md files as recipe count (each recipe has one .md metadata file)
    return len(list(target_dir.rglob("*.md")))


def get_resources_status() -> dict:
    """
    Get installed resources status information

    Returns:
        Dictionary containing resource status:
        {
            "commands": {"installed": int, "path": str, "files": list},
            "recipes": {"installed": int, "path": str},
            "frago_version": str,
        }
    """
    from frago import __version__

    commands_path = get_target_path("commands")
    recipes_path = get_target_path("recipes")

    # Get list of installed command files
    command_files = []
    if commands_path.exists():
        command_files = [f.name for f in commands_path.glob("frago.*.md")]

    return {
        "commands": {
            "installed": len(command_files),
            "path": str(commands_path),
            "files": command_files,
        },
        "recipes": {
            "installed": count_installed_recipes(),
            "path": str(recipes_path),
        },
        "frago_version": __version__,
    }


def format_resources_status() -> str:
    """
    Format resource status output (for --show-config)

    Returns:
        Formatted status string
    """
    status = get_resources_status()
    lines = []

    lines.append("[*] Installed resources:")
    lines.append("")

    # Commands status
    cmd = status["commands"]
    lines.append(f"  Claude Code commands: {cmd['installed']} files")
    lines.append(f"  Location: {cmd['path']}")
    if cmd["files"]:
        for f in cmd["files"]:
            lines.append(f"    - {f}")
    lines.append("")

    # Recipes status
    rec = status["recipes"]
    lines.append(f"  Example Recipes: {rec['installed']} files")
    lines.append(f"  Location: {rec['path']}")
    lines.append("")

    lines.append(f"  Frago version: {status['frago_version']}")

    return "\n".join(lines)
