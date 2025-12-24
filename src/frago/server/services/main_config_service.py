"""Main configuration service.

Provides functionality for reading and updating the main frago configuration
stored in ~/.frago/config.json.
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MainConfigService:
    """Service for main frago configuration management."""

    @staticmethod
    def get_config() -> Dict[str, Any]:
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
    def update_config(updates: Dict[str, Any]) -> Dict[str, Any]:
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
