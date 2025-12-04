"""Configuration persistence for Frago GUI.

Handles loading and saving user configuration to ~/.frago/gui_config.json.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from frago.gui.exceptions import ConfigValidationError
from frago.gui.models import UserConfig

CONFIG_DIR = Path.home() / ".frago"
CONFIG_FILE = CONFIG_DIR / "gui_config.json"


def ensure_config_dir() -> Path:
    """Ensure the configuration directory exists.

    Returns:
        Path to the configuration directory.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def load_config() -> UserConfig:
    """Load user configuration from file.

    Returns:
        UserConfig instance with loaded values or defaults.
    """
    if not CONFIG_FILE.exists():
        return UserConfig()

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        config = UserConfig(
            theme=data.get("theme", "dark"),
            font_size=data.get("font_size", 14),
            show_system_status=data.get("show_system_status", True),
            confirm_on_exit=data.get("confirm_on_exit", True),
            auto_scroll_output=data.get("auto_scroll_output", True),
            max_history_items=data.get("max_history_items", 100),
            shortcuts=data.get(
                "shortcuts",
                {
                    "send": "Ctrl+Enter",
                    "clear": "Ctrl+L",
                    "settings": "Ctrl+,",
                },
            ),
        )
        return config
    except (json.JSONDecodeError, KeyError, TypeError):
        return UserConfig()


def save_config(config: UserConfig) -> None:
    """Save user configuration to file.

    Args:
        config: UserConfig instance to save.

    Raises:
        ConfigValidationError: If configuration validation fails.
    """
    errors = config.validate()
    if errors:
        raise ConfigValidationError(errors)

    ensure_config_dir()
    data = asdict(config)
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def update_config(updates: dict) -> UserConfig:
    """Update configuration with partial values.

    Args:
        updates: Dictionary of configuration keys to update.

    Returns:
        Updated UserConfig instance.

    Raises:
        ConfigValidationError: If updated configuration is invalid.
    """
    config = load_config()

    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)

    save_config(config)
    return config


def get_config_value(key: str, default: Optional[any] = None) -> any:
    """Get a single configuration value.

    Args:
        key: Configuration key.
        default: Default value if key not found.

    Returns:
        Configuration value or default.
    """
    config = load_config()
    return getattr(config, key, default)
