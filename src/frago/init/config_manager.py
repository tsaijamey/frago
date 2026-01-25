"""Main configuration file management module

Provides read and write operations for ~/.frago/config.json with support for partial updates.
Includes one-time migration from api_endpoint in config.json to ~/.claude/settings.json.
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

# Migration flag file to track if migration has been performed
_MIGRATION_PERFORMED_FLAG = Path.home() / ".frago" / ".api_endpoint_migrated"

# Main configuration file path
CONFIG_PATH = Path.home() / ".frago" / "config.json"


def load_config() -> Config:
    """Load main configuration file

    Returns:
        Config instance

    Notes:
        - If file does not exist, return default configuration
        - If file is corrupted, backup and try to recover valid fields
        - Performs one-time migration of api_endpoint to settings.json
    """
    if not CONFIG_PATH.exists():
        return Config()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))

        # Perform one-time migration if needed
        _migrate_api_endpoint_if_needed(data)

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


def _migrate_api_endpoint_if_needed(data: Dict[str, Any]) -> None:
    """One-time migration: move api_endpoint from config.json to settings.json

    This migration runs once per installation. It:
    1. Checks if api_endpoint exists in config.json
    2. Checks if settings.json already has ANTHROPIC_API_KEY (skip if so)
    3. Migrates api_endpoint to settings.json
    4. Removes api_endpoint from config.json
    5. Creates a flag file to prevent re-migration

    Args:
        data: Raw config data dictionary (will be modified in place)
    """
    # Skip if migration already performed
    if _MIGRATION_PERFORMED_FLAG.exists():
        # Still need to clear api_endpoint from data if it exists (for validation)
        if "api_endpoint" in data:
            del data["api_endpoint"]
        return

    api_endpoint = data.get("api_endpoint")
    if not api_endpoint:
        # No api_endpoint to migrate, mark as done
        _mark_migration_complete()
        return

    # Import here to avoid circular imports
    from frago.init.configurator import (
        load_claude_settings,
        build_claude_env_config,
        save_claude_settings,
        ensure_claude_json_for_custom_auth,
    )

    # Check if settings.json already has API config
    settings = load_claude_settings()
    if settings.get("env", {}).get("ANTHROPIC_API_KEY"):
        # Already configured in settings.json, just clean up config.json
        logger.info("API config already in settings.json, skipping migration")
        del data["api_endpoint"]
        _save_data_without_api_endpoint(data)
        _mark_migration_complete()
        return

    # Perform migration
    logger.info("Migrating api_endpoint from config.json to settings.json")

    try:
        ep_type = api_endpoint.get("type", "custom")
        api_key = api_endpoint.get("api_key", "")

        if not api_key:
            # No API key to migrate
            logger.warning("api_endpoint has no api_key, skipping migration")
            del data["api_endpoint"]
            _save_data_without_api_endpoint(data)
            _mark_migration_complete()
            return

        # Build env config
        env_config = build_claude_env_config(
            endpoint_type=ep_type,
            api_key=api_key,
            custom_url=api_endpoint.get("url") if ep_type == "custom" else None,
            default_model=api_endpoint.get("default_model"),
            sonnet_model=api_endpoint.get("sonnet_model"),
            haiku_model=api_endpoint.get("haiku_model"),
        )

        # Ensure ~/.claude.json exists
        ensure_claude_json_for_custom_auth()

        # Save to settings.json
        save_claude_settings({"env": env_config})
        logger.info("Successfully migrated API config to ~/.claude/settings.json")

        # Clean up config.json
        del data["api_endpoint"]
        _save_data_without_api_endpoint(data)
        _mark_migration_complete()

    except Exception as e:
        logger.error("Failed to migrate api_endpoint: %s", e)
        # Still remove from data to prevent validation errors
        if "api_endpoint" in data:
            del data["api_endpoint"]


def _save_data_without_api_endpoint(data: Dict[str, Any]) -> None:
    """Save config data without api_endpoint field

    Args:
        data: Config data to save (should not contain api_endpoint)
    """
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8'
        )
    except Exception as e:
        logger.error("Failed to save config after migration: %s", e)


def _mark_migration_complete() -> None:
    """Create flag file to indicate migration is complete"""
    try:
        _MIGRATION_PERFORMED_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _MIGRATION_PERFORMED_FLAG.write_text(
            datetime.now().isoformat(),
            encoding='utf-8'
        )
    except Exception as e:
        logger.warning("Failed to create migration flag: %s", e)
