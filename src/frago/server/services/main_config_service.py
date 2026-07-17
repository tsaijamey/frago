"""Main configuration service.

Provides functionality for reading and updating the main frago configuration
stored in ~/.frago/config.json.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MainConfigService:
    """Service for main frago configuration management."""

    @staticmethod
    def get_config() -> dict[str, Any]:
        """Get main configuration from ~/.frago/config.json.

        Returns:
            Configuration dictionary with all fields plus working_directory_display.
        """
        from frago.init.config_manager import load_config

        try:
            config = load_config()
            result = config.model_dump(mode="json")
            # Add working directory display path
            result["working_directory_display"] = str(Path.home() / ".frago" / "projects")
            return result
        except Exception as e:
            logger.error("Failed to load main config: %s", e)
            # Return default config
            from frago.init.models import Config

            result = Config().model_dump(mode="json")
            result["working_directory_display"] = str(Path.home() / ".frago" / "projects")
            return result

    @staticmethod
    def update_config(updates: dict[str, Any]) -> dict[str, Any]:
        """Update main configuration.

        Args:
            updates: Partial update dictionary.

        Returns:
            Dictionary with 'status', 'config', and optionally 'error'.
        """
        from pydantic import ValidationError

        from frago.init.config_manager import update_config

        try:
            config = update_config(updates)
            result = config.model_dump(mode="json")
            result["working_directory_display"] = str(Path.home() / ".frago" / "projects")
            return {
                "status": "ok",
                "config": result,
            }
        except ValidationError as e:
            return {
                "status": "error",
                "error": f"Config validation failed: {e}",
            }
        except Exception as e:
            logger.error("Failed to update main config: %s", e)
            return {
                "status": "error",
                "error": str(e),
            }

    @staticmethod
    async def apply_custom_auth(
        endpoint_type: str,
        api_key: str,
        url: "str | None",
        default_model: "str | None",
        sonnet_model: "str | None",
        haiku_model: "str | None",
    ) -> None:
        """Apply custom API auth configuration.

        Shared between update_auth endpoint and profile activation.
        Writes to ~/.claude/settings.json and updates frago config.
        """
        from frago.init.config_manager import load_config, save_config
        from frago.init.configurator import (
            build_claude_env_config,
            ensure_claude_json_for_custom_auth,
            save_claude_settings,
        )
        from frago.server.state import StateManager

        env_config = build_claude_env_config(
            endpoint_type=endpoint_type,
            api_key=api_key,
            custom_url=url if endpoint_type == "custom" else None,
            default_model=default_model,
            sonnet_model=sonnet_model,
            haiku_model=haiku_model,
        )
        ensure_claude_json_for_custom_auth()
        save_claude_settings({"env": env_config})

        config = load_config()
        config.auth_method = "custom"
        config.api_endpoint = None
        save_config(config)

        state_manager = StateManager.get_instance()
        await state_manager.refresh_config(broadcast=True)

    @staticmethod
    async def apply_official_auth() -> None:
        """Switch back to official auth.

        Shared between update_auth endpoint and profile deactivation.
        """
        from frago.init.config_manager import load_config, save_config
        from frago.init.configurator import clear_api_env_from_settings
        from frago.server.state import StateManager

        clear_api_env_from_settings()

        config = load_config()
        config.auth_method = "official"
        config.api_endpoint = None
        save_config(config)

        state_manager = StateManager.get_instance()
        await state_manager.refresh_config(broadcast=True)
