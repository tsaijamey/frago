"""Environment variables service.

Provides functionality for managing user-level environment variables
stored in ~/.frago/.env file.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EnvService:
    """Service for environment variable management."""

    @staticmethod
    def get_env_vars() -> Dict[str, Any]:
        """Get user-level environment variables from ~/.frago/.env.

        Returns:
            Dictionary with 'vars' (env dict) and 'file_exists' (bool).
        """
        from frago.recipes.env_loader import EnvLoader

        try:
            env_path = EnvLoader.USER_ENV_PATH
            loader = EnvLoader()

            # Load user-level .env file
            env_vars = loader.load_env_file(env_path)

            return {
                "vars": env_vars,
                "file_exists": env_path.exists(),
            }
        except Exception as e:
            logger.error("Failed to load environment variables: %s", e)
            return {
                "vars": {},
                "file_exists": False,
            }

    @staticmethod
    def update_env_vars(updates: Dict[str, Optional[str]]) -> Dict[str, Any]:
        """Batch update environment variables.

        Args:
            updates: Dictionary of key-value pairs. Value=None means delete.

        Returns:
            Dictionary with 'status', 'vars', and optionally 'error'.
        """
        from frago.recipes.env_loader import EnvLoader, update_env_file

        try:
            env_path = EnvLoader.USER_ENV_PATH

            # Update .env file
            update_env_file(env_path, updates)

            # Reload and return
            loader = EnvLoader()
            env_vars = loader.load_env_file(env_path)

            return {
                "status": "ok",
                "vars": env_vars,
                "file_exists": True,
            }
        except Exception as e:
            logger.error("Failed to update environment variables: %s", e)
            return {
                "status": "error",
                "error": str(e),
            }

    @staticmethod
    def get_recipe_env_requirements() -> List[Dict[str, Any]]:
        """Scan all recipe environment variable requirements.

        Returns:
            List of requirement dictionaries with:
            - recipe_name: Name of the recipe
            - var_name: Environment variable name
            - required: Whether the variable is required
            - description: Variable description
            - configured: Whether the variable is currently set
        """
        try:
            import frontmatter
        except ImportError:
            logger.warning(
                "python-frontmatter not installed, "
                "unable to scan recipe environment variable requirements"
            )
            return []

        from frago.recipes.env_loader import EnvLoader

        requirements = []
        recipe_dirs = [
            Path.home() / ".frago" / "recipes",
        ]

        # Load current environment variables
        try:
            current_env = EnvLoader().load_all()
        except Exception:
            current_env = {}

        # Scan recipe directories
        for recipe_dir in recipe_dirs:
            if not recipe_dir.exists():
                continue

            for md_file in recipe_dir.rglob("recipe.md"):
                try:
                    # Parse frontmatter
                    post = frontmatter.load(md_file)
                    env_vars = post.metadata.get("env", {})

                    if not env_vars:
                        continue

                    recipe_name = post.metadata.get("name", md_file.parent.name)

                    for var_name, var_def in env_vars.items():
                        # var_def may be a dict or a simple default value
                        if isinstance(var_def, dict):
                            required = var_def.get("required", False)
                            description = var_def.get("description", "")
                        else:
                            required = False
                            description = ""

                        requirements.append({
                            "recipe_name": recipe_name,
                            "var_name": var_name,
                            "required": required,
                            "description": description,
                            "configured": var_name in current_env,
                        })
                except Exception as e:
                    logger.warning("Failed to parse %s: %s", md_file, e)
                    continue

        # Deduplicate (same variable used by multiple recipes)
        unique: Dict[str, Dict[str, Any]] = {}
        for req in requirements:
            key = req["var_name"]
            if key not in unique:
                unique[key] = req
            else:
                # Merge recipe_name
                unique[key]["recipe_name"] += f", {req['recipe_name']}"
                # Keep higher priority (if any required=True, set to True)
                if req["required"]:
                    unique[key]["required"] = True

        return list(unique.values())
