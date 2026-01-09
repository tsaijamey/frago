"""Recipe management service.

Provides functionality for listing, viewing, and executing recipes.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.server.services.base import get_utf8_env, prepare_command_for_windows, run_subprocess

logger = logging.getLogger(__name__)


class RecipeService:
    """Service for recipe management operations."""

    # Cache for loaded recipes
    _cache: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def get_recipes(cls, force_reload: bool = False) -> List[Dict[str, Any]]:
        """Get list of available recipes.

        Args:
            force_reload: If True, bypass cache and reload.

        Returns:
            List of recipe dictionaries.
        """
        if cls._cache is None or force_reload:
            cls._cache = cls._load_recipes()
        return cls._cache

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the recipe cache."""
        cls._cache = None

    @classmethod
    def _load_recipes(cls) -> List[Dict[str, Any]]:
        """Load recipes from frago recipe list command.

        Returns:
            List of recipe dictionaries.
        """
        recipes = []
        try:
            result = run_subprocess(
                ["frago", "recipe", "list", "--format", "json"],
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for item in data:
                    recipes.append({
                        "name": item.get("name", ""),
                        "description": item.get("description"),
                        "category": item.get("type", "atomic"),
                        "tags": item.get("tags", []),
                        "path": item.get("path"),
                        "source": item.get("source"),
                        "runtime": item.get("runtime"),
                    })
        except Exception as e:
            logger.warning("Failed to load recipes from command: %s", e)

        # Fallback to filesystem if no recipes loaded
        if not recipes:
            recipes = cls._load_recipes_from_filesystem()

        return recipes

    @staticmethod
    def _load_recipes_from_filesystem() -> List[Dict[str, Any]]:
        """Load recipes from filesystem as fallback.

        Returns:
            List of recipe dictionaries.
        """
        recipes = []
        recipe_dirs = [
            Path.home() / ".frago" / "recipes",
        ]

        for recipe_dir in recipe_dirs:
            if not recipe_dir.exists():
                continue

            for path in recipe_dir.rglob("*.js"):
                recipes.append({
                    "name": path.stem,
                    "description": None,
                    "category": "atomic" if "atomic" in str(path) else "workflow",
                    "tags": [],
                    "path": str(path),
                })

            for path in recipe_dir.rglob("*.py"):
                if path.stem != "__init__":
                    recipes.append({
                        "name": path.stem,
                        "description": None,
                        "category": "atomic" if "atomic" in str(path) else "workflow",
                        "tags": [],
                        "path": str(path),
                    })

        return recipes

    @classmethod
    def get_recipe(cls, name: str) -> Optional[Dict[str, Any]]:
        """Get recipe details by name.

        Args:
            name: Recipe name.

        Returns:
            Recipe dictionary or None if not found.
        """
        # Try to get detailed info via frago recipe info command
        try:
            result = run_subprocess(
                ["frago", "recipe", "info", name, "--format", "json"],
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                # Read source code if script_path exists
                script_path = data.get("script_path")
                if script_path:
                    try:
                        data["source_code"] = Path(script_path).read_text(encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to read recipe source code: %s", e)
                        data["source_code"] = None
                return data
        except Exception as e:
            logger.warning("Failed to get recipe info from command: %s", e)

        # Fallback to list lookup
        recipes = cls.get_recipes()
        for recipe in recipes:
            if recipe.get("name") == name:
                return recipe

        return None

    @staticmethod
    def run_recipe(
        name: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 300,
        async_exec: bool = False,
    ) -> Dict[str, Any]:
        """Execute a recipe.

        Args:
            name: Recipe name.
            params: Optional parameters.
            timeout: Timeout in seconds (default 300).
            async_exec: If True, start recipe in background and return immediately.

        Returns:
            Result dictionary with status, output, and optionally error.
        """
        import subprocess
        import time

        start_time = time.time()

        try:
            cmd = ["frago", "recipe", "run", name]
            if params:
                cmd.extend(["--params", json.dumps(params)])

            if async_exec:
                # Start process in background without waiting
                # Need to pass environment and avoid suppressing output for interactive recipes
                subprocess.Popen(
                    prepare_command_for_windows(cmd),
                    env=get_utf8_env(),
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {
                    "status": "ok",
                    "output": "Recipe started in background",
                    "error": None,
                    "duration_ms": 0,
                }

            # Synchronous execution
            result = run_subprocess(cmd, timeout=timeout)

            duration_ms = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                output = result.stdout.strip()
                return {
                    "status": "ok",
                    "output": output,
                    "error": None,
                    "duration_ms": duration_ms,
                }
            else:
                error = result.stderr.strip() or "Recipe execution failed"
                return {
                    "status": "error",
                    "output": None,
                    "error": error,
                    "duration_ms": duration_ms,
                }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if "TimeoutExpired" in error_msg or "timed out" in error_msg.lower():
                error_msg = "Execution timed out"
            logger.error("Recipe execution failed: %s", e)
            return {
                "status": "error",
                "output": None,
                "error": error_msg,
                "duration_ms": duration_ms,
            }
