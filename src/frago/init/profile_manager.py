"""API endpoint profile management.

Provides CRUD operations for ~/.frago/profiles.json.
Profiles store saved API endpoint configurations for quick switching.
"""

import json
import logging
import os
import platform
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PROFILES_PATH = Path.home() / ".frago" / "profiles.json"


class APIProfile(BaseModel):
    """A saved API endpoint configuration."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    endpoint_type: str  # deepseek, aliyun, kimi, minimax, custom
    api_key: str
    url: Optional[str] = None
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ProfileStore(BaseModel):
    """Container for all saved profiles."""

    schema_version: str = "1.0"
    active_profile_id: Optional[str] = None
    profiles: list[APIProfile] = Field(default_factory=list)


def load_profiles() -> ProfileStore:
    """Load profiles from ~/.frago/profiles.json.

    Returns empty ProfileStore if file doesn't exist or is corrupted.
    """
    if not PROFILES_PATH.exists():
        return ProfileStore()

    try:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        return ProfileStore(**data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to load profiles.json: %s. Using empty store.", e)
        return ProfileStore()


def save_profiles(store: ProfileStore) -> None:
    """Save profiles to ~/.frago/profiles.json with 0o600 permissions on Unix."""
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(store.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    PROFILES_PATH.write_text(content, encoding="utf-8")

    # Set file permissions on Unix
    if platform.system() != "Windows":
        os.chmod(PROFILES_PATH, 0o600)


def add_profile(profile: APIProfile) -> ProfileStore:
    """Add a new profile and save."""
    store = load_profiles()
    store.profiles.append(profile)
    save_profiles(store)
    return store


def update_profile(profile_id: str, updates: dict) -> ProfileStore:
    """Update an existing profile's fields.

    Args:
        profile_id: Profile ID to update.
        updates: Dict of fields to update. Keys that don't exist are ignored.
                 api_key=None or api_key="" means keep existing key.

    Raises:
        ValueError: If profile not found.
    """
    store = load_profiles()

    for profile in store.profiles:
        if profile.id == profile_id:
            for key, value in updates.items():
                if key == "api_key" and not value:
                    continue  # Preserve existing key
                if hasattr(profile, key) and key not in ("id", "created_at"):
                    setattr(profile, key, value)
            profile.updated_at = datetime.now()
            save_profiles(store)
            return store

    raise ValueError(f"Profile not found: {profile_id}")


def delete_profile(profile_id: str) -> ProfileStore:
    """Delete a profile. If active, sets active_profile_id to None
    but does NOT clear ~/.claude/settings.json.

    Raises:
        ValueError: If profile not found.
    """
    store = load_profiles()

    original_len = len(store.profiles)
    store.profiles = [p for p in store.profiles if p.id != profile_id]

    if len(store.profiles) == original_len:
        raise ValueError(f"Profile not found: {profile_id}")

    if store.active_profile_id == profile_id:
        store.active_profile_id = None

    save_profiles(store)
    return store


def get_profile(profile_id: str) -> Optional[APIProfile]:
    """Get a single profile by ID."""
    store = load_profiles()
    for profile in store.profiles:
        if profile.id == profile_id:
            return profile
    return None


def activate_profile(profile_id: str) -> None:
    """Activate a profile: write its credentials to ~/.claude/settings.json
    and update frago config.

    Raises:
        ValueError: If profile not found.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.configurator import (
        build_claude_env_config,
        ensure_claude_json_for_custom_auth,
        save_claude_settings,
    )

    store = load_profiles()
    profile = None
    for p in store.profiles:
        if p.id == profile_id:
            profile = p
            break

    if not profile:
        raise ValueError(f"Profile not found: {profile_id}")

    # Build env config and write to ~/.claude/settings.json
    env_config = build_claude_env_config(
        endpoint_type=profile.endpoint_type,
        api_key=profile.api_key,
        custom_url=profile.url if profile.endpoint_type == "custom" else None,
        default_model=profile.default_model,
        sonnet_model=profile.sonnet_model,
        haiku_model=profile.haiku_model,
    )
    ensure_claude_json_for_custom_auth()
    save_claude_settings({"env": env_config})

    # Update frago config
    config = load_config()
    config.auth_method = "custom"
    config.api_endpoint = None
    save_config(config)

    # Update active profile
    store.active_profile_id = profile_id
    save_profiles(store)


def deactivate_profile() -> None:
    """Deactivate current profile: switch back to official auth."""
    from frago.init.config_manager import load_config, save_config
    from frago.init.configurator import clear_api_env_from_settings

    clear_api_env_from_settings()

    config = load_config()
    config.auth_method = "official"
    config.api_endpoint = None
    save_config(config)

    store = load_profiles()
    store.active_profile_id = None
    save_profiles(store)


def create_profile_from_current(name: str) -> Optional[APIProfile]:
    """Create a profile from the current ~/.claude/settings.json configuration.

    Args:
        name: Name for the new profile.

    Returns:
        The created APIProfile, or None if no custom config is active.
    """
    from frago.init.configurator import (
        _infer_endpoint_type_from_url,
        load_claude_settings,
    )

    settings = load_claude_settings()
    env = settings.get("env", {})
    api_key = env.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        return None

    base_url = env.get("ANTHROPIC_BASE_URL", "")
    endpoint_type = _infer_endpoint_type_from_url(base_url)

    profile = APIProfile(
        name=name,
        endpoint_type=endpoint_type,
        api_key=api_key,
        url=base_url if endpoint_type == "custom" else None,
        default_model=env.get("ANTHROPIC_MODEL"),
        sonnet_model=env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"),
        haiku_model=env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"),
    )

    store = load_profiles()
    store.profiles.append(profile)
    # Mark this profile as active since it matches current config
    store.active_profile_id = profile.id
    save_profiles(store)

    return profile
