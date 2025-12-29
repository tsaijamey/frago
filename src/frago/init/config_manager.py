"""Main configuration file management module

Provides read and write operations for ~/.frago/config.json with support for partial updates.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError

from frago.init.models import Config

logger = logging.getLogger(__name__)

# Main configuration file path
CONFIG_PATH = Path.home() / ".frago" / "config.json"


def load_config() -> Config:
    """Load main configuration file

    Returns:
        Config instance

    Notes:
        - If file does not exist, return default configuration
        - If file is corrupted, backup and try to recover valid fields
    """
    if not CONFIG_PATH.exists():
        return Config()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        return Config(**data)
    except json.JSONDecodeError as e:
        # JSON parsing failed, backup corrupted file
        _backup_corrupted_config(f"json_error_{e}")
        return Config()
    except ValidationError as e:
        # Pydantic validation failed, backup and try to recover valid fields
        _backup_corrupted_config("validation_error")
        logger.warning("Config validation failed: %s. Attempting recovery.", e)
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
            return _recover_config_from_data(data)
        except Exception:
            return Config()
    except Exception as e:
        # Other errors
        _backup_corrupted_config("unknown_error")
        return Config()


def save_config(config: Config) -> None:
    """Save configuration file

    Args:
        config: Config instance

    Notes:
        - Automatically creates parent directory
        - Uses JSON formatted output (indent=2)
        - Automatically updates updated_at field
    """
    # Ensure directory exists
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Update timestamp
    config.updated_at = datetime.now()

    # Serialize to JSON
    config_dict = config.model_dump(mode='json')

    # Write to file
    CONFIG_PATH.write_text(
        json.dumps(config_dict, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8'
    )


def update_config(updates: Dict[str, Any]) -> Config:
    """Partially update configuration file

    Args:
        updates: Dictionary of fields to update, e.g. {"sync_repo_url": "git@github.com:user/repo.git"}

    Returns:
        Updated Config instance

    Raises:
        ValidationError: If the updated configuration is invalid

    Examples:
        >>> config = update_config({"sync_repo_url": "git@github.com:user/repo.git"})
        >>> config = update_config({"auth_method": "custom"})
    """
    # Load existing configuration
    config = load_config()

    # Apply updates
    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)

    # Save configuration (triggers Pydantic validation)
    save_config(config)

    return config


def _backup_corrupted_config(reason: str) -> None:
    """Backup corrupted configuration file

    Args:
        reason: Corruption reason (used in backup filename)
    """
    if not CONFIG_PATH.exists():
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = CONFIG_PATH.with_suffix(f'.json.bak.{timestamp}')

    try:
        shutil.copy(CONFIG_PATH, backup_path)
    except Exception:
        pass  # Backup failure does not affect main flow


def _recover_config_from_data(data: Dict[str, Any]) -> Config:
    """Recover valid fields from corrupted config data.

    When config validation fails (e.g., invalid auth_method), this function
    preserves critical non-auth fields while resetting auth to a valid state.

    Args:
        data: Raw config data dictionary

    Returns:
        Config instance with recovered fields
    """
    safe_fields: Dict[str, Any] = {}

    # Preserve critical non-auth fields that don't affect validation
    preserve_fields = [
        'sync_repo_url',
        'resources_installed',
        'resources_version',
        'last_resource_update',
        'init_completed',
        'created_at',
        'schema_version',
        'node_version',
        'node_path',
        'npm_version',
        'claude_code_version',
        'claude_code_path',
        'ccr_enabled',
        'ccr_config_path',
    ]

    for field in preserve_fields:
        if field in data and data[field] is not None:
            safe_fields[field] = data[field]

    # Reset auth to valid default state (official without api_endpoint)
    safe_fields['auth_method'] = 'official'
    safe_fields['api_endpoint'] = None

    logger.info("Recovered config fields: %s", list(safe_fields.keys()))
    return Config(**safe_fields)
