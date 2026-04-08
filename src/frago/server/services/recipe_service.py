"""Recipe management service.

Provides functionality for listing, viewing, and executing recipes.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RecipeService:
    """Service for recipe management operations.

    Note: This service always loads fresh from storage.
    For cached access, use StateManager.get_recipes().
    """

    @classmethod
    def get_recipes(cls, force_reload: bool = False) -> List[Dict[str, Any]]:
        """Get list of available recipes.

        Args:
            force_reload: Ignored. Always loads fresh. Use StateManager for caching.

        Returns:
            List of recipe dictionaries.
        """
        return cls._load_recipes()

    @classmethod
    def _load_recipes(cls) -> List[Dict[str, Any]]:
        """Load recipes directly from RecipeRegistry.

        Uses Python module directly instead of CLI to avoid cmd.exe flash on Windows.
        Uses singleton registry with mtime-based cache invalidation.

        Returns:
            List of recipe dictionaries.
        """
        recipes = []
        try:
            from frago.recipes.registry import get_registry, invalidate_registry

            registry = get_registry()
            # Check if registry needs refresh due to file changes
            if registry.needs_rescan():
                invalidate_registry()
                registry = get_registry()

            for recipe in registry.list_all():
                recipes.append({
                    "name": recipe.metadata.name,
                    "description": recipe.metadata.description,
                    "category": recipe.metadata.type,
                    "tags": recipe.metadata.tags or [],
                    "path": str(recipe.script_path) if recipe.script_path else None,
                    "source": recipe.source,
                    "runtime": recipe.metadata.runtime,
                })
        except Exception as e:
            logger.warning("Failed to load recipes from registry: %s", e)

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
        try:
            from frago.recipes.registry import get_registry, invalidate_registry

            registry = get_registry()
            if registry.needs_rescan():
                invalidate_registry()
                registry = get_registry()
            recipe = registry.find(name)

            m = recipe.metadata
            data = {
                "name": m.name,
                "type": m.type,
                "runtime": m.runtime,
                "version": m.version,
                "source": recipe.source,
                "base_dir": str(recipe.base_dir) if recipe.base_dir else None,
                "script_path": str(recipe.script_path),
                "metadata_path": str(recipe.metadata_path),
                "description": m.description,
                "use_cases": m.use_cases,
                "tags": m.tags,
                "output_targets": m.output_targets,
                "inputs": m.inputs,
                "outputs": m.outputs,
                "dependencies": m.dependencies,
                "secrets": m.secrets,
                "flow": m.flow,
            }

            # Read source code if script_path exists
            if recipe.script_path:
                try:
                    data["source_code"] = Path(recipe.script_path).read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning("Failed to read recipe source code: %s", e)
                    data["source_code"] = None

            return data
        except Exception as e:
            logger.warning("Failed to get recipe from registry: %s", e)

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
    ) -> Dict[str, Any]:
        """Execute a recipe synchronously.

        This is a blocking method. Callers in async context
        MUST use asyncio.to_thread() to avoid blocking the event loop.

        Args:
            name: Recipe name.
            params: Optional parameters.
            timeout: Timeout in seconds (default 300).

        Returns:
            Result dictionary with status, data, and optionally error.
        """
        import time

        start_time = time.time()

        try:
            from frago.recipes.runner import RecipeRunner

            runner = RecipeRunner()
            result = runner.run(name, params or {})

            duration_ms = int((time.time() - start_time) * 1000)

            return {
                "status": "ok" if result.get("success") else "error",
                "data": result.get("data"),
                "error": result.get("error"),
                "duration_ms": duration_ms,
                "execution_id": result.get("execution_id"),
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            if "TimeoutExpired" in error_msg or "timed out" in error_msg.lower():
                error_msg = "Execution timed out"
            logger.error("Recipe execution failed: %s", e)
            return {
                "status": "error",
                "data": None,
                "error": error_msg,
                "duration_ms": duration_ms,
            }

    @staticmethod
    def run_recipe_async(
        name: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 300,
    ) -> str:
        """Execute a recipe asynchronously, return execution_id.

        Validates parameters synchronously, then submits to background thread pool.

        Args:
            name: Recipe name.
            params: Optional parameters.
            timeout: Timeout in seconds (default 300).

        Returns:
            execution_id for polling via GET /api/executions/{id}.
        """
        from frago.recipes.runner import RecipeRunner

        runner = RecipeRunner()
        return runner.run_async(name, params, timeout=timeout)

    @staticmethod
    def get_execution(execution_id: str) -> Optional[Dict[str, Any]]:
        """Get a single execution by ID."""
        from frago.recipes.execution_store import ExecutionStore

        store = ExecutionStore()
        execution = store.get(execution_id)
        if execution:
            return execution.to_dict()
        return None

    @staticmethod
    def cancel_execution(execution_id: str) -> dict[str, Any]:
        """Cancel a running execution.

        Returns:
            Dict with status and message.
        """
        from frago.recipes.runner import RecipeRunner

        runner = RecipeRunner()
        cancelled = runner.cancel(execution_id)
        if cancelled:
            return {"status": "ok", "message": f"Execution {execution_id} cancelled"}
        return {"status": "error", "message": f"Execution {execution_id} not found or already finished"}

    @staticmethod
    def list_workflow_executions(workflow_id: str) -> list[dict[str, Any]]:
        """List all executions belonging to a workflow."""
        from frago.recipes.execution_store import ExecutionStore

        store = ExecutionStore()
        executions = store.list_by_workflow(workflow_id)
        return [e.to_dict() for e in executions]

    @staticmethod
    def list_executions(
        recipe_name: Optional[str] = None,
        limit: int = 20,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent executions."""
        from frago.recipes.execution import ExecutionStatus
        from frago.recipes.execution_store import ExecutionStore

        store = ExecutionStore()
        status_filter = ExecutionStatus(status) if status else None
        executions = store.list_recent(
            recipe_name=recipe_name,
            limit=limit,
            status=status_filter,
        )
        return [e.to_dict() for e in executions]
