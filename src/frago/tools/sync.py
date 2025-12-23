"""
Pack module - Sync user directory resources to package directory

Sync Recipes from ~/.frago/recipes/ to src/frago/resources/recipes/
Sync commands from ~/.claude/commands/ to src/frago/resources/commands/
Sync Skills from ~/.claude/skills/ to src/frago/resources/skills/

Provides functionality to sync Recipes and Claude Code commands from user directory
to Python package resource directory, enabling latest content to be included during packaging.

Note: This is an internal feature for PyPI packaging.
Developers edit resources directly in ~/.claude/ and ~/.frago/, then use dev pack to sync to package.
"""

import fnmatch
import shutil
from pathlib import Path
from typing import Optional


class CommandSync:
    """Claude Code command synchronizer"""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ):
        """
        Initialize synchronizer

        Args:
            source_dir: Source directory (~/.claude/commands/), defaults to user directory
            target_dir: Target directory (src/frago/resources/commands/), defaults to auto-detect
        """
        # Auto-detect project root directory (for target_dir)
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        # Change source directory to user directory
        self.source_dir = source_dir or (Path.home() / ".claude" / "commands")
        self.target_dir = target_dir or (
            project_root / "src" / "frago" / "resources" / "commands"
        )

    def find_commands(self, pattern: Optional[str] = None) -> list[Path]:
        """
        Find all frago.*.md command files

        Args:
            pattern: Optional wildcard pattern for filtering command names

        Returns:
            List of command file paths
        """
        commands = []

        if not self.source_dir.exists():
            return commands

        # Find frago.*.md files (user directory uses official naming)
        for cmd_file in self.source_dir.glob("frago.*.md"):
            if not cmd_file.is_file():
                continue

            cmd_name = cmd_file.name

            # If pattern specified, perform matching
            if pattern:
                if not fnmatch.fnmatch(cmd_name, pattern):
                    continue

            commands.append(cmd_file)

        return commands

    def get_target_name(self, source_name: str) -> str:
        """
        Get target filename (directly use source filename)

        Args:
            source_name: Source filename, e.g. frago.recipe.md

        Returns:
            Target filename, same as source filename
        """
        # User directory already uses official naming, no conversion needed
        return source_name

    def sync(
        self,
        pattern: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """
        Execute sync operation

        Args:
            pattern: Optional wildcard pattern for filtering command names
            dry_run: If True, only show operations to be executed, don't actually execute
            verbose: Show detailed information

        Returns:
            Sync result list, each element contains source_name, target_name, source_file, target_file, action
        """
        results = []
        cmd_files = self.find_commands(pattern)

        if not cmd_files:
            return results

        for src_file in cmd_files:
            source_name = src_file.name
            target_name = self.get_target_name(source_name)
            target_file = self.target_dir / target_name

            # Determine operation type
            if target_file.exists():
                # Check if update needed (compare modification time)
                if src_file.stat().st_mtime > target_file.stat().st_mtime:
                    action = "update"
                else:
                    action = "skip"
            else:
                action = "create"

            result = {
                "source_name": source_name,
                "target_name": target_name,
                "source_file": src_file,
                "target_file": target_file,
                "action": action,
            }

            if action == "skip":
                results.append(result)
                continue

            if not dry_run:
                # Ensure target directory exists
                self.target_dir.mkdir(parents=True, exist_ok=True)
                # Copy file
                shutil.copy2(src_file, target_file)

            results.append(result)

        return results

    def list_synced(self) -> list[Path]:
        """List command files synced to resources"""
        synced = []

        if not self.target_dir.exists():
            return synced

        for cmd_file in self.target_dir.glob("frago.*.md"):
            if cmd_file.is_file():
                synced.append(cmd_file)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        Clean command files in target directory that don't exist in source directory

        Args:
            dry_run: If True, only show files to be deleted, don't actually execute

        Returns:
            List of deleted (or to be deleted) files
        """
        removed = []

        for target_file in self.list_synced():
            target_name = target_file.name
            # Source filename is same as target filename
            source_file = self.source_dir / target_name

            if not source_file.exists():
                if not dry_run:
                    target_file.unlink()
                removed.append(target_file)

        return removed


class RecipeSync:
    """Recipe synchronizer"""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ):
        """
        Initialize synchronizer

        Args:
            source_dir: Source directory (~/.frago/recipes/), defaults to user directory
            target_dir: Target directory (src/frago/resources/recipes/), defaults to auto-detect
        """
        # Auto-detect project root directory (for target_dir)
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        # Change source directory to user directory
        self.source_dir = source_dir or (Path.home() / ".frago" / "recipes")
        self.target_dir = target_dir or (
            project_root / "src" / "frago" / "resources" / "recipes"
        )

    def find_recipes(self, pattern: Optional[str] = None) -> list[Path]:
        """
        Find all Recipe directories

        Args:
            pattern: Optional wildcard pattern for filtering Recipe names

        Returns:
            List of recipe directory paths
        """
        recipes = []

        # Traverse subdirectories under examples/ (atomic/chrome, atomic/system, workflows)
        for subdir in ["atomic/chrome", "atomic/system", "workflows"]:
            category_path = self.source_dir / subdir
            if not category_path.exists():
                continue

            # Find all recipe directories (directories containing recipe.md)
            for recipe_dir in category_path.iterdir():
                if not recipe_dir.is_dir():
                    continue
                # Skip __pycache__ directory
                if recipe_dir.name == "__pycache__":
                    continue

                # Check if recipe.md exists
                metadata_path = recipe_dir / "recipe.md"
                if not metadata_path.exists():
                    continue

                # Get Recipe name (directory name)
                recipe_name = recipe_dir.name

                # If pattern specified, perform matching
                if pattern:
                    if not fnmatch.fnmatch(recipe_name, pattern):
                        continue

                recipes.append(recipe_dir)

        return recipes

    def sync(
        self,
        pattern: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """
        Execute sync operation (directory-based recipes)

        Args:
            pattern: Optional wildcard pattern for filtering Recipe names
            dry_run: If True, only show operations to be executed, don't actually execute
            verbose: Show detailed information

        Returns:
            Sync result list, each element contains recipe_name, source_dir, target_dir, action
        """
        results = []
        recipe_dirs = self.find_recipes(pattern)

        if not recipe_dirs:
            return results

        for recipe_dir in recipe_dirs:
            # Calculate relative path
            rel_path = recipe_dir.relative_to(self.source_dir)
            recipe_name = recipe_dir.name

            # Target path
            target_dir = self.target_dir / rel_path

            # Determine operation type
            if target_dir.exists():
                # Check if update needed (compare modification time of all files in directory)
                needs_update = False
                for src_file in recipe_dir.rglob("*"):
                    if src_file.is_file() and "__pycache__" not in str(src_file):
                        rel_file = src_file.relative_to(recipe_dir)
                        tgt_file = target_dir / rel_file
                        if not tgt_file.exists():
                            needs_update = True
                            break
                        if src_file.stat().st_mtime > tgt_file.stat().st_mtime:
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
                results.append(result)
                continue

            if not dry_run:
                # Delete old directory (if exists)
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                # Copy entire directory (excluding __pycache__)
                shutil.copytree(
                    recipe_dir,
                    target_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )

            results.append(result)

        return results

    def list_synced(self) -> list[Path]:
        """List Recipe directories synced to resources"""
        synced = []

        # Traverse subdirectories under target_dir
        for subdir in ["atomic/chrome", "atomic/system", "workflows"]:
            category_path = self.target_dir / subdir
            if not category_path.exists():
                continue

            for recipe_dir in category_path.iterdir():
                if recipe_dir.is_dir() and (recipe_dir / "recipe.md").exists():
                    synced.append(recipe_dir)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        Clean Recipes in target directory that don't exist in source directory

        Args:
            dry_run: If True, only show directories to be deleted, don't actually execute

        Returns:
            List of deleted (or to be deleted) directories
        """
        removed = []

        for target_dir in self.list_synced():
            # Calculate corresponding source path
            rel_path = target_dir.relative_to(self.target_dir)
            source_dir = self.source_dir / rel_path

            if not source_dir.exists():
                if not dry_run:
                    shutil.rmtree(target_dir)
                removed.append(target_dir)

        return removed


class SkillSync:
    """Skill synchronizer"""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ):
        """
        Initialize synchronizer

        Args:
            source_dir: Source directory (~/.claude/skills/), defaults to user directory
            target_dir: Target directory (src/frago/resources/skills/), defaults to auto-detect
        """
        # Auto-detect project root directory (for target_dir)
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        # Change source directory to user directory
        self.source_dir = source_dir or (Path.home() / ".claude" / "skills")
        self.target_dir = target_dir or (
            project_root / "src" / "frago" / "resources" / "skills"
        )

    def find_skills(self, pattern: Optional[str] = None) -> list[Path]:
        """
        Find all Skill directories (starting with frago-)

        Args:
            pattern: Optional wildcard pattern for filtering Skill names

        Returns:
            List of Skill directory paths
        """
        skills = []

        if not self.source_dir.exists():
            return skills

        for skill_dir in self.source_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            # Skip __pycache__ directory
            if skill_dir.name == "__pycache__":
                continue
            # Only sync skills starting with frago-
            if not skill_dir.name.startswith("frago-"):
                continue

            # Check if SKILL.md exists
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill_name = skill_dir.name

            # If pattern specified, perform matching
            if pattern:
                if not fnmatch.fnmatch(skill_name, pattern):
                    continue

            skills.append(skill_dir)

        return skills

    def sync(
        self,
        pattern: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """
        Execute sync operation (directory-based skills)

        Args:
            pattern: Optional wildcard pattern for filtering Skill names
            dry_run: If True, only show operations to be executed, don't actually execute
            verbose: Show detailed information

        Returns:
            Sync result list, each element contains skill_name, source_dir, target_dir, action
        """
        results = []
        skill_dirs = self.find_skills(pattern)

        if not skill_dirs:
            return results

        for skill_dir in skill_dirs:
            skill_name = skill_dir.name
            target_dir = self.target_dir / skill_name

            # Determine operation type
            if target_dir.exists():
                # Check if update needed (compare modification time of all files in directory)
                needs_update = False
                for src_file in skill_dir.rglob("*"):
                    if src_file.is_file() and "__pycache__" not in str(src_file):
                        rel_file = src_file.relative_to(skill_dir)
                        tgt_file = target_dir / rel_file
                        if not tgt_file.exists():
                            needs_update = True
                            break
                        if src_file.stat().st_mtime > tgt_file.stat().st_mtime:
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
                results.append(result)
                continue

            if not dry_run:
                # Delete old directory (if exists)
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                # Copy entire directory (excluding __pycache__)
                shutil.copytree(
                    skill_dir,
                    target_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )

            results.append(result)

        return results

    def list_synced(self) -> list[Path]:
        """List Skill directories synced to resources"""
        synced = []

        if not self.target_dir.exists():
            return synced

        for skill_dir in self.target_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                synced.append(skill_dir)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        Clean Skills in target directory that don't exist in source directory

        Args:
            dry_run: If True, only show directories to be deleted, don't actually execute

        Returns:
            List of deleted (or to be deleted) directories
        """
        removed = []

        for target_dir in self.list_synced():
            skill_name = target_dir.name
            source_dir = self.source_dir / skill_name

            if not source_dir.exists():
                if not dry_run:
                    shutil.rmtree(target_dir)
                removed.append(target_dir)

        return removed
