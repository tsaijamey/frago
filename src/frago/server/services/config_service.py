"""User configuration service.

Provides functionality for reading and updating user GUI configuration
stored in ~/.frago/gui_config.json.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".frago"
CONFIG_FILE = CONFIG_DIR / "gui_config.json"


@dataclass
class UserConfig:
    """User preferences, persisted to ~/.frago/gui_config.json."""

    theme: str = "dark"
    show_system_status: bool = True
    confirm_on_exit: bool = True
    auto_scroll_output: bool = True
    max_history_items: int = 100
    ai_title_enabled: bool = False  # Enable AI title generation using haiku model
    shortcuts: Dict[str, str] = field(
        default_factory=lambda: {
            "send": "Ctrl+Enter",
            "clear": "Ctrl+L",
            "settings": "Ctrl+,",
        }
    )

    def validate(self) -> List[str]:
        """Validate configuration values.

        Returns:
            List of validation error messages, empty if valid.
        """
        errors = []
        if self.theme not in ("dark", "light"):
            errors.append(f"theme must be 'dark' or 'light', got '{self.theme}'")
        if not 10 <= self.max_history_items <= 1000:
            errors.append(
                f"max_history_items must be between 10 and 1000, got {self.max_history_items}"
            )
        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed: {', '.join(errors)}")


class ConfigService:
    """Service for user configuration management."""

    @staticmethod
    def _ensure_config_dir() -> Path:
        """Ensure the configuration directory exists.

        Returns:
            Path to the configuration directory.
        """
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        return CONFIG_DIR

    @staticmethod
    def get_config() -> Dict[str, Any]:
        """Load user configuration from file.

        Returns:
            Configuration dictionary with user preferences.
        """
        if not CONFIG_FILE.exists():
            return UserConfig().to_dict()

        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            config = UserConfig(
                theme=data.get("theme", "dark"),
                show_system_status=data.get("show_system_status", True),
                confirm_on_exit=data.get("confirm_on_exit", True),
                auto_scroll_output=data.get("auto_scroll_output", True),
                max_history_items=data.get("max_history_items", 100),
                ai_title_enabled=data.get("ai_title_enabled", False),
                shortcuts=data.get(
                    "shortcuts",
                    {
                        "send": "Ctrl+Enter",
                        "clear": "Ctrl+L",
                        "settings": "Ctrl+,",
                    },
                ),
            )
            return config.to_dict()
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to load config, using defaults: %s", e)
            return UserConfig().to_dict()

    @staticmethod
    def update_config(updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update configuration with partial values.

        Args:
            updates: Dictionary of configuration keys to update.

        Returns:
            Updated configuration dictionary.

        Raises:
            ConfigValidationError: If updated configuration is invalid.
        """
        # Load current config
        current = ConfigService.get_config()
        config = UserConfig(**current)

        # Apply updates
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)

        # Validate
        errors = config.validate()
        if errors:
            raise ConfigValidationError(errors)

        # Save
        ConfigService._ensure_config_dir()
        data = config.to_dict()
        CONFIG_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.debug("Config updated: %s", updates.keys())
        return data

    @staticmethod
    def get_config_value(key: str, default: Optional[Any] = None) -> Any:
        """Get a single configuration value.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        config = ConfigService.get_config()
        return config.get(key, default)
