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
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from frago.init.profile_targets import DEFAULT_TARGETS

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
    # Which agent CLIs the active profile was written into. Empty when nothing
    # is active. A store written before targets existed has no such key at all,
    # and load_profiles fills it in — see there for why.
    active_targets: list[str] = Field(default_factory=list)
    profiles: list[APIProfile] = Field(default_factory=list)


def load_profiles() -> ProfileStore:
    """Load profiles from ~/.frago/profiles.json.

    Returns empty ProfileStore if file doesn't exist or is corrupted.

    A store saved before activation had targets records an active profile with
    no target list. That profile is in force in Claude Code right now, so the
    missing list is read as ``["claude"]`` rather than "nowhere" — otherwise the
    first deactivation after upgrading would decide there was nothing to undo
    and leave the endpoint in settings.json forever.
    """
    if not PROFILES_PATH.exists():
        return ProfileStore()

    try:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        store = ProfileStore(**data)
        if data.get("active_profile_id") and "active_targets" not in data:
            store.active_targets = list(DEFAULT_TARGETS)
        return store
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


def _validate_profile(name: str, endpoint_type: str, url: Optional[str]) -> None:
    """Reject the profile shapes that break something later and quietly.

    A nameless profile is unreachable in any list and, worse, is written to
    disk as a null the store cannot parse back — one blank field would take
    every other saved profile down with it. An unknown endpoint type falls
    through to the "custom" branch when settings are built, and a custom
    endpoint with no URL writes a null base URL; neither fails at save time,
    they fail at the first request with a connection error that says nothing
    about which profile caused it. Catching all three here means the person
    editing the profile hears about it while still looking at the form.

    Raises:
        ValueError: With a message meant to be shown to the user as-is.
    """
    from frago.init.configurator import PRESET_ENDPOINTS, validate_endpoint_url

    if not (name or "").strip():
        raise ValueError("Profile name cannot be empty")

    if endpoint_type != "custom" and endpoint_type not in PRESET_ENDPOINTS:
        known = ", ".join([*PRESET_ENDPOINTS, "custom"])
        raise ValueError(f"Unknown endpoint type '{endpoint_type}' (expected one of: {known})")

    if endpoint_type == "custom" and not validate_endpoint_url(url or ""):
        raise ValueError("A custom endpoint needs an API URL starting with http:// or https://")


def add_profile(profile: APIProfile) -> ProfileStore:
    """Add a new profile and save.

    Raises:
        ValueError: If the endpoint type / URL combination is unusable.
    """
    _validate_profile(profile.name, profile.endpoint_type, profile.url)
    store = load_profiles()
    store.profiles.append(profile)
    save_profiles(store)
    return store


def update_profile(profile_id: str, updates: dict) -> ProfileStore:
    """Update an existing profile's fields.

    If the edited profile is the active one, the change is re-applied to every
    agent CLI it was activated on. Without that, editing the profile that is
    currently in force saved the new model to disk and left the old one
    running: the UI said "saved", and the next session still talked to the
    endpoint the user thought they had just replaced. The stored target list is
    passed back in so that re-applying does not quietly narrow an activation
    that covered several CLIs down to Claude Code alone.

    Args:
        profile_id: Profile ID to update.
        updates: Dict of fields to update. Keys that don't exist are ignored.
                 api_key=None or api_key="" means keep existing key.

    Raises:
        ValueError: If profile not found, or the result would be unusable.
    """
    store = load_profiles()

    for profile in store.profiles:
        if profile.id == profile_id:
            _validate_profile(
                updates.get("name", profile.name),
                updates.get("endpoint_type") or profile.endpoint_type,
                updates.get("url", profile.url),
            )
            for key, value in updates.items():
                if key == "api_key" and not value:
                    continue  # Preserve existing key
                if hasattr(profile, key) and key not in ("id", "created_at"):
                    setattr(profile, key, value)
            profile.updated_at = datetime.now()
            save_profiles(store)

            if store.active_profile_id == profile_id:
                activate_profile(profile_id, store.active_targets or None)
            return store

    raise ValueError(f"Profile not found: {profile_id}")


def delete_profile(profile_id: str) -> ProfileStore:
    """Delete a profile. If active, sets active_profile_id to None
    but does NOT clear the agent CLIs it was written into.

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
        store.active_targets = []

    save_profiles(store)
    return store


def get_profile(profile_id: str) -> Optional[APIProfile]:
    """Get a single profile by ID."""
    store = load_profiles()
    for profile in store.profiles:
        if profile.id == profile_id:
            return profile
    return None


def activate_profile(
    profile_id: str, targets: Optional[Sequence[str]] = None
) -> list[str]:
    """Activate a profile on the chosen agent CLIs.

    Each target gets this profile written into its own configuration, so that
    sessions the person starts by hand pick it up too — not just the ones frago
    launches.

    Args:
        profile_id: Profile to activate.
        targets: Agent CLIs to write it into. ``None`` keeps the historical
            behavior (Claude Code only), so callers that predate targets are
            unaffected.

    Returns:
        The targets the profile is now active on.

    Raises:
        ValueError: If the profile is not found, or a requested target cannot
            take a frago profile / is not installed here.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.profile_targets import apply_profile, resolve_targets, revert_targets

    # Validate the request before touching anything: a half-applied activation
    # is worse than a refused one, because nothing on screen would say which
    # half went through.
    resolved = resolve_targets(targets)

    store = load_profiles()
    profile = None
    for p in store.profiles:
        if p.id == profile_id:
            profile = p
            break

    if not profile:
        raise ValueError(f"Profile not found: {profile_id}")

    previous = list(store.active_targets)
    apply_profile(profile, resolved)

    # Targets that were in force and are not chosen this time have to be handed
    # back. Skipping this is the silent-stale-config bug: unchecking opencode
    # would leave it running the old profile while the UI showed it as off.
    dropped = [t for t in previous if t not in resolved]
    if dropped:
        revert_targets(dropped)

    # frago's own auth_method describes Claude Code specifically — it is what
    # the init flow and the WebUI status card read. It only moves when claude's
    # own state moves.
    if "claude" in resolved:
        config = load_config()
        config.auth_method = "custom"
        config.api_endpoint = None
        save_config(config)
    elif "claude" in dropped:
        config = load_config()
        config.auth_method = "official"
        config.api_endpoint = None
        save_config(config)

    store.active_profile_id = profile_id
    store.active_targets = resolved
    save_profiles(store)
    return resolved


def deactivate_profile(targets: Optional[Sequence[str]] = None) -> list[str]:
    """Deactivate the current profile, restoring each target's own config.

    Args:
        targets: Agent CLIs to hand back. ``None`` means all the ones this
            profile is currently active on.

    Returns:
        The targets that were handed back.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.profile_targets import DEFAULT_TARGETS, revert_targets

    store = load_profiles()
    # An empty stored list on a store that predates targets still means Claude
    # Code — see load_profiles. Falling back here as well covers a store whose
    # active id was set directly rather than through activate_profile.
    active = list(store.active_targets) or list(DEFAULT_TARGETS)
    handing_back = [t for t in active if t in targets] if targets is not None else active

    revert_targets(handing_back)

    if "claude" in handing_back:
        config = load_config()
        config.auth_method = "official"
        config.api_endpoint = None
        save_config(config)

    remaining = [t for t in active if t not in handing_back]
    store.active_targets = remaining
    if not remaining:
        store.active_profile_id = None
    save_profiles(store)
    return handing_back


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
    # Bearer-style endpoints (Tencent, OpenRouter) keep the credential in
    # ANTHROPIC_AUTH_TOKEN and blank out ANTHROPIC_API_KEY. Reading only the
    # latter reported "no custom configuration found" to users who were, at
    # that very moment, running on one.
    api_key = env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN") or ""

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
    # Mark this profile as active since it matches current config. The config it
    # was read from is Claude Code's, so that is the one target it is active on
    # — claiming any other CLI here would be claiming a file frago never wrote.
    store.active_profile_id = profile.id
    store.active_targets = list(DEFAULT_TARGETS)
    save_profiles(store)

    return profile
