"""Recipe secrets service.

Provides read/write access to recipes.local.json,
merging recipe.md secrets schema with configured values.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RecipeSecretsService:
    """Service for recipe secrets management via recipes.local.json."""

    SECRETS_PATH = Path.home() / ".frago" / "recipes.local.json"

    @staticmethod
    def _load_secrets_file() -> dict[str, Any]:
        """Load and parse recipes.local.json."""
        path = RecipeSecretsService.SECRETS_PATH
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _save_secrets_file(data: dict[str, Any]) -> None:
        """Write data to recipes.local.json."""
        path = RecipeSecretsService.SECRETS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _get_recipe_metadata(recipe_name: str) -> Any | None:
        """Get RecipeMetadata for a recipe by name."""
        from frago.recipes.registry import get_registry

        registry = get_registry()
        try:
            recipe = registry.get(recipe_name)
            return recipe.metadata
        except Exception:
            return None

    @staticmethod
    def _resolve_ref(all_config: dict[str, Any], recipe_name: str) -> tuple[dict[str, Any], bool, str | None]:
        """Resolve $ref and return (config_data, is_ref, ref_target)."""
        raw = all_config.get(recipe_name, {})
        if "$ref" in raw:
            ref_target = raw["$ref"]
            resolved = all_config.get(ref_target, {})
            return resolved, True, ref_target
        return raw, False, None

    @staticmethod
    def get_recipe_secrets(recipe_name: str) -> dict[str, Any]:
        """Get secrets info for a recipe.

        Merges recipe.md secrets schema with configured values from recipes.local.json.
        Values are not returned (only has_value indicator).

        Returns:
            {
                "recipe_name": str,
                "fields": [{"key", "type", "required", "description", "has_value", "default"}],
                "is_ref": bool,
                "ref_target": str | None,
            }
        """
        metadata = RecipeSecretsService._get_recipe_metadata(recipe_name)
        secrets_schema = metadata.secrets if metadata else {}

        try:
            all_config = RecipeSecretsService._load_secrets_file()
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load recipes.local.json: %s", e)
            all_config = {}

        config_data, is_ref, ref_target = RecipeSecretsService._resolve_ref(all_config, recipe_name)

        fields: list[dict[str, Any]] = []
        for key, schema_def in secrets_schema.items():
            if not isinstance(schema_def, dict):
                continue
            field_info: dict[str, Any] = {
                "key": key,
                "type": schema_def.get("type", "string"),
                "required": schema_def.get("required", False),
                "description": schema_def.get("description", ""),
                "has_value": key in config_data and config_data[key] not in (None, ""),
            }
            if "default" in schema_def:
                field_info["default"] = schema_def["default"]
            fields.append(field_info)

        return {
            "recipe_name": recipe_name,
            "fields": fields,
            "is_ref": is_ref,
            "ref_target": ref_target,
        }

    @staticmethod
    def update_recipe_secrets(recipe_name: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update secrets for a recipe in recipes.local.json.

        If the recipe is a $ref, updates are written to the ref target.

        Args:
            recipe_name: Recipe name
            updates: Key-value pairs to set. None values remove the key.

        Returns:
            {"status": "ok"} or {"status": "error", "error": str}
        """
        try:
            all_config = RecipeSecretsService._load_secrets_file()
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load recipes.local.json: %s", e)
            return {"status": "error", "error": f"Failed to load recipes.local.json: {e}"}

        # Resolve $ref — write to the target
        write_key = recipe_name
        raw = all_config.get(recipe_name, {})
        if "$ref" in raw:
            write_key = raw["$ref"]

        current = all_config.get(write_key, {})
        # Don't overwrite $ref entries in the target
        if "$ref" in current:
            current = {}

        for k, v in updates.items():
            if v is None:
                current.pop(k, None)
            else:
                current[k] = v

        all_config[write_key] = current

        try:
            RecipeSecretsService._save_secrets_file(all_config)
        except OSError as e:
            logger.error("Failed to save recipes.local.json: %s", e)
            return {"status": "error", "error": f"Failed to save recipes.local.json: {e}"}

        return {"status": "ok"}
