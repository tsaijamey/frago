"""Settings API endpoints.

Provides endpoints for main config, environment variables, and GitHub integration.
"""

import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from frago.compat import get_windows_subprocess_kwargs
from frago.server.state import StateManager
from frago.server.services.github_service import GitHubService
from frago.server.services.main_config_service import MainConfigService
from frago.server.services.recipe_secrets_service import RecipeSecretsService
from frago.server.services.update_service import UpdateService
from frago.server.services.version_service import VersionCheckService

router = APIRouter()


# ============================================================
# Request/Response Models
# ============================================================


class GhCliStatusResponse(BaseModel):
    """GitHub CLI status response"""
    installed: bool
    authenticated: bool
    version: Optional[str] = None
    username: Optional[str] = None


class APIEndpointResponse(BaseModel):
    """API endpoint configuration response"""
    type: str
    url: Optional[str] = None
    api_key: str
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None


class MainConfigResponse(BaseModel):
    """Main configuration response"""
    working_directory: str
    auth_method: str
    api_endpoint: Optional[APIEndpointResponse] = None
    sync_repo: Optional[str] = None
    resources_installed: bool = True
    resources_version: Optional[str] = None
    init_completed: bool = True


class MainConfigUpdateRequest(BaseModel):
    """Main configuration update request"""
    working_directory: Optional[str] = None
    auth_method: Optional[str] = None
    sync_repo: Optional[str] = None


class APIEndpointRequest(BaseModel):
    """API endpoint configuration"""
    type: str  # deepseek, aliyun, kimi, minimax, custom
    api_key: Optional[str] = None  # Optional - if not provided, existing key is preserved
    url: Optional[str] = None  # Only for custom type
    default_model: Optional[str] = None  # Override for ANTHROPIC_MODEL
    sonnet_model: Optional[str] = None   # Override for ANTHROPIC_DEFAULT_SONNET_MODEL
    haiku_model: Optional[str] = None    # Override for ANTHROPIC_DEFAULT_HAIKU_MODEL


class AuthUpdateRequest(BaseModel):
    """Authentication update request"""
    auth_method: str  # official or custom
    api_endpoint: Optional[APIEndpointRequest] = None


class ApiResponse(BaseModel):
    """Generic API response"""
    status: str
    message: Optional[str] = None
    error: Optional[str] = None


class RecipeSecretsFieldResponse(BaseModel):
    """Single secret field info"""
    key: str
    type: str
    required: bool = False
    description: str = ""
    has_value: bool = False
    default: Any | None = None


class RecipeSecretsResponse(BaseModel):
    """Recipe secrets response"""
    recipe_name: str
    fields: list[RecipeSecretsFieldResponse]
    is_ref: bool = False
    ref_target: str | None = None


class RecipeSecretsUpdateRequest(BaseModel):
    """Recipe secrets update request"""
    updates: dict[str, Any]


class VSCodeStatusResponse(BaseModel):
    """VSCode installation status response"""
    available: bool  # True only if VSCode installed AND settings.json exists


class VersionInfoResponse(BaseModel):
    """Version information response"""
    current_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    checked_at: Optional[str] = None
    error: Optional[str] = None


class UpdateStatusResponse(BaseModel):
    """Self-update status response"""
    status: str  # idle, updating, restarting, completed, error
    progress: int = 0
    message: str = ""
    error: Optional[str] = None


# ============================================================
# GitHub CLI Endpoints
# ============================================================


@router.get("/settings/gh-cli", response_model=GhCliStatusResponse)
async def check_gh_cli() -> GhCliStatusResponse:
    """Check GitHub CLI installation and authentication status.

    Always refreshes the status to ensure accuracy.
    """
    state_manager = StateManager.get_instance()
    # Always refresh to get current status (user may have logged in/out externally)
    await state_manager.refresh_gh_status(broadcast=False)
    status = state_manager.get_gh_status()

    return GhCliStatusResponse(
        installed=status.get("installed", False),
        authenticated=status.get("authenticated", False),
        version=status.get("version"),
        username=status.get("username"),
    )


@router.post("/settings/gh-cli/login", response_model=ApiResponse)
async def gh_auth_login() -> ApiResponse:
    """Initiate GitHub CLI authentication."""
    result = GitHubService.auth_login()

    if result.get("status") == "ok":
        return ApiResponse(status="ok", message=result.get("message", "Authentication initiated"))
    return ApiResponse(status="error", error=result.get("error", "Authentication failed"))


# ============================================================
# Main Config Endpoints
# ============================================================


@router.get("/settings/main-config", response_model=MainConfigResponse)
async def get_main_config() -> MainConfigResponse:
    """Get main configuration.

    API config is read from ~/.claude/settings.json (source of truth).
    Other config is read from ~/.frago/config.json via cache.
    """
    from frago.init.configurator import (
        PRESET_ENDPOINTS,
        parse_api_config_from_claude_settings,
        get_auth_method_from_settings,
    )

    state_manager = StateManager.get_instance()
    config = state_manager.get_config()

    # Get actual auth_method from settings.json (source of truth)
    actual_auth_method = get_auth_method_from_settings()

    # Build api_endpoint response from settings.json
    api_endpoint = None
    api_config = parse_api_config_from_claude_settings()
    if api_config:
        ep_type = api_config.get("type", "custom")

        # Get preset defaults if available
        preset = PRESET_ENDPOINTS.get(ep_type, {})
        default_model = api_config.get("default_model") or preset.get("ANTHROPIC_MODEL")
        sonnet_model = api_config.get("sonnet_model") or preset.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        haiku_model = api_config.get("haiku_model") or preset.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")

        api_endpoint = APIEndpointResponse(
            type=ep_type,
            url=api_config.get("url"),
            api_key=api_config.get("api_key", ""),  # Already masked
            default_model=default_model,
            sonnet_model=sonnet_model,
            haiku_model=haiku_model,
        )

    return MainConfigResponse(
        working_directory=config.get("working_directory_display", "~/.frago"),
        auth_method=actual_auth_method,
        api_endpoint=api_endpoint,
        sync_repo=config.get("sync_repo_url"),
        resources_installed=config.get("resources_installed", True),
        resources_version=config.get("resources_version"),
        init_completed=config.get("init_completed", True),
    )


@router.put("/settings/main-config", response_model=MainConfigResponse)
async def update_main_config(request: MainConfigUpdateRequest) -> MainConfigResponse:
    """Update main configuration."""
    updates = {}
    if request.working_directory is not None:
        updates["working_directory"] = request.working_directory
    if request.auth_method is not None:
        updates["auth_method"] = request.auth_method
    if request.sync_repo is not None:
        updates["sync_repo_url"] = request.sync_repo

    result = MainConfigService.update_config(updates)

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # Refresh cache after update
    state_manager = StateManager.get_instance()
    await state_manager.refresh_config(broadcast=True)

    # Get the config field from the result
    config = result.get("config", result)

    return MainConfigResponse(
        working_directory=config.get("working_directory_display", "~/.frago"),
        auth_method=config.get("auth_method", "official"),
        sync_repo=config.get("sync_repo_url"),
    )


async def _apply_custom_auth(
    endpoint_type: str,
    api_key: str,
    url: Optional[str],
    default_model: Optional[str],
    sonnet_model: Optional[str],
    haiku_model: Optional[str],
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


async def _apply_official_auth() -> None:
    """Switch back to official auth.

    Shared between update_auth endpoint and profile deactivation.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.configurator import clear_api_env_from_settings

    clear_api_env_from_settings()

    config = load_config()
    config.auth_method = "official"
    config.api_endpoint = None
    save_config(config)

    state_manager = StateManager.get_instance()
    await state_manager.refresh_config(broadcast=True)


@router.post("/settings/update-auth", response_model=ApiResponse)
async def update_auth(request: AuthUpdateRequest) -> ApiResponse:
    """Update authentication method and API endpoint.

    When auth_method is 'custom', creates ~/.claude/settings.json with the API config.
    API config is ONLY stored in settings.json, NOT in config.json.
    When auth_method is 'official', clears API env vars from settings.json.

    If api_key is not provided but an existing config exists, the existing API key is preserved.
    """
    from frago.init.configurator import load_claude_settings

    try:
        if request.auth_method == "custom":
            if not request.api_endpoint:
                return ApiResponse(status="error", error="API endpoint required for custom auth")

            endpoint = request.api_endpoint

            # Get API key: use provided one, or preserve existing from settings.json
            api_key = endpoint.api_key
            if not api_key:
                existing_settings = load_claude_settings()
                existing_api_key = existing_settings.get("env", {}).get("ANTHROPIC_API_KEY")
                if existing_api_key:
                    api_key = existing_api_key
                else:
                    return ApiResponse(status="error", error="API key required for new custom auth configuration")

            await _apply_custom_auth(
                endpoint_type=endpoint.type,
                api_key=api_key,
                url=endpoint.url,
                default_model=endpoint.default_model,
                sonnet_model=endpoint.sonnet_model,
                haiku_model=endpoint.haiku_model,
            )
        else:  # official
            await _apply_official_auth()

        return ApiResponse(status="ok", message="Authentication updated")

    except Exception as e:
        return ApiResponse(status="error", error=str(e))


# ============================================================
# Recipe Secrets Endpoints
# ============================================================


@router.get("/settings/recipe-secrets/{recipe_name}", response_model=RecipeSecretsResponse)
async def get_recipe_secrets(recipe_name: str) -> RecipeSecretsResponse:
    """Get secrets schema and configured status for a recipe.

    Merges recipe.md secrets schema with recipes.local.json values.
    Values are masked — only has_value is returned.
    """
    result = RecipeSecretsService.get_recipe_secrets(recipe_name)

    return RecipeSecretsResponse(
        recipe_name=result["recipe_name"],
        fields=[RecipeSecretsFieldResponse(**f) for f in result["fields"]],
        is_ref=result["is_ref"],
        ref_target=result.get("ref_target"),
    )


@router.put("/settings/recipe-secrets/{recipe_name}", response_model=ApiResponse)
async def update_recipe_secrets(recipe_name: str, request: RecipeSecretsUpdateRequest) -> ApiResponse:
    """Update secrets for a recipe in recipes.local.json."""
    result = RecipeSecretsService.update_recipe_secrets(recipe_name, request.updates)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return ApiResponse(status="ok", message="Recipe secrets updated")


# ============================================================
# Working Directory Endpoints
# ============================================================


class OpenPathRequest(BaseModel):
    """Request for opening a path"""
    path: str
    reveal: bool = False


@router.post("/settings/open-path", response_model=ApiResponse)
async def open_path(request: OpenPathRequest) -> ApiResponse:
    """Open a file or directory in system file manager.

    If reveal=True, opens the parent directory and selects the file.
    """
    try:
        path = os.path.expanduser(request.path)

        if not os.path.exists(path):
            return ApiResponse(status="error", error=f"Path does not exist: {path}")

        system = platform.system()

        if request.reveal:
            # Reveal in file manager (select the file)
            if system == "Darwin":
                subprocess.run(["open", "-R", path], check=True)
            elif system == "Linux":
                # Linux: open parent directory
                parent = os.path.dirname(path)
                subprocess.run(["xdg-open", parent], check=True)
            elif system == "Windows":
                subprocess.run(
                    ["explorer", "/select,", path],
                    check=True,
                    **get_windows_subprocess_kwargs(),
                )
            else:
                return ApiResponse(status="error", error=f"Unsupported platform: {system}")
        else:
            # Open directly
            if system == "Darwin":
                subprocess.run(["open", path], check=True)
            elif system == "Linux":
                subprocess.run(["xdg-open", path], check=True)
            elif system == "Windows":
                os.startfile(path)  # type: ignore
            else:
                return ApiResponse(status="error", error=f"Unsupported platform: {system}")

        return ApiResponse(status="ok", message="Path opened")
    except subprocess.CalledProcessError as e:
        return ApiResponse(status="error", error=f"Failed to open path: {e}")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.post("/settings/open-working-directory", response_model=ApiResponse)
async def open_working_directory() -> ApiResponse:
    """Open working directory in system file manager."""
    try:
        config = MainConfigService.get_config()
        working_dir = config.get("working_directory", os.path.expanduser("~/.frago"))

        # Expand user path
        working_dir = os.path.expanduser(working_dir)

        if not os.path.exists(working_dir):
            return ApiResponse(status="error", error=f"Directory does not exist: {working_dir}")

        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", working_dir], check=True)
        elif system == "Linux":
            subprocess.run(["xdg-open", working_dir], check=True)
        elif system == "Windows":
            os.startfile(working_dir)  # type: ignore
        else:
            return ApiResponse(status="error", error=f"Unsupported platform: {system}")

        return ApiResponse(status="ok", message="Working directory opened")
    except subprocess.CalledProcessError as e:
        return ApiResponse(status="error", error=f"Failed to open directory: {e}")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


# ============================================================
# VSCode Integration Endpoints
# ============================================================


def _find_vscode() -> str | None:
    """Find VSCode executable path.

    Returns the path to use for opening files, or None if not found.
    - macOS: checks PATH first, then /Applications/Visual Studio Code.app
    - Linux/Windows: checks PATH
    """
    # First check if 'code' command is in PATH
    code_path = shutil.which("code")
    if code_path:
        return code_path

    # On macOS, check if VSCode.app exists
    if platform.system() == "Darwin":
        vscode_app = "/Applications/Visual Studio Code.app"
        if os.path.exists(vscode_app):
            return vscode_app

    return None


@router.get("/settings/vscode-status", response_model=VSCodeStatusResponse)
async def check_vscode() -> VSCodeStatusResponse:
    """Check if VSCode is installed AND ~/.claude/settings.json exists.

    The Edit button should only show when both conditions are met.
    ~/.claude/settings.json is created when user configures custom API endpoint.
    """
    vscode_path = _find_vscode()
    settings_path = os.path.expanduser("~/.claude/settings.json")
    settings_exists = os.path.exists(settings_path)

    return VSCodeStatusResponse(available=vscode_path is not None and settings_exists)


@router.post("/settings/open-in-vscode", response_model=ApiResponse)
async def open_in_vscode() -> ApiResponse:
    """Open ~/.claude/settings.json in VSCode."""
    try:
        settings_path = os.path.expanduser("~/.claude/settings.json")

        if not os.path.exists(settings_path):
            return ApiResponse(status="error", error="Settings file not found")

        vscode_path = _find_vscode()
        if not vscode_path:
            return ApiResponse(status="error", error="VSCode not found")

        # Use Popen to avoid blocking the server
        if vscode_path.endswith(".app"):
            # macOS: use 'open -a' to open with the app
            subprocess.Popen(["open", "-a", vscode_path, settings_path])
        else:
            # Linux/Windows: use the 'code' command directly
            subprocess.Popen(
                [vscode_path, settings_path],
                **get_windows_subprocess_kwargs(),
            )

        return ApiResponse(status="ok", message="Opened in VSCode")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


# ============================================================
# Official Resource Sync Endpoints
# ============================================================


class OfficialSyncStatusResponse(BaseModel):
    """Official resource sync status response"""
    enabled: bool
    last_sync: Optional[str] = None
    last_commit: Optional[str] = None
    repo: str
    branch: str


class OfficialSyncResultResponse(BaseModel):
    """Official resource sync result response"""
    status: str  # "ok", "running", "idle", "error", "partial"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    commit: Optional[str] = None
    commands: Optional[Dict] = None
    skills: Optional[Dict] = None
    error: Optional[str] = None
    message: Optional[str] = None


class OfficialSyncEnableRequest(BaseModel):
    """Request to enable/disable official resource sync"""
    enabled: bool


@router.get("/settings/official-resource-sync/status", response_model=OfficialSyncStatusResponse)
async def get_official_sync_status() -> OfficialSyncStatusResponse:
    """Get official resource sync configuration and status."""
    from frago.server.services.official_resource_sync_service import OfficialResourceSyncService

    status = OfficialResourceSyncService.get_sync_status()

    return OfficialSyncStatusResponse(
        enabled=status.get("enabled", False),
        last_sync=status.get("last_sync"),
        last_commit=status.get("last_commit"),
        repo=status.get("repo", ""),
        branch=status.get("branch", "main"),
    )


@router.post("/settings/official-resource-sync/run", response_model=OfficialSyncResultResponse)
async def run_official_sync() -> OfficialSyncResultResponse:
    """Start official resource sync from GitHub.

    Initiates sync in background and returns immediately.
    Use GET /settings/official-resource-sync/result to poll for completion.
    """
    from frago.server.services.official_resource_sync_service import OfficialResourceSyncService

    result = OfficialResourceSyncService.start_sync()

    return OfficialSyncResultResponse(
        status=result.get("status", "error"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.get("/settings/official-resource-sync/result", response_model=OfficialSyncResultResponse)
async def get_official_sync_result() -> OfficialSyncResultResponse:
    """Get the result of the current or last official sync operation.

    Returns "running" if sync is in progress, or the final result.
    """
    from frago.server.services.official_resource_sync_service import OfficialResourceSyncService

    result = OfficialResourceSyncService.get_sync_result()

    # Refresh cache after successful sync
    if result.get("status") == "ok":
        state_manager = StateManager.get_instance()
        await state_manager.refresh_skills(broadcast=True)

    return OfficialSyncResultResponse(
        status=result.get("status", "idle"),
        started_at=result.get("started_at"),
        completed_at=result.get("completed_at"),
        commit=result.get("commit"),
        commands=result.get("commands"),
        skills=result.get("skills"),
        error=result.get("error"),
    )


@router.put("/settings/official-resource-sync/enable", response_model=ApiResponse)
async def set_official_sync_enabled(request: OfficialSyncEnableRequest) -> ApiResponse:
    """Enable or disable auto-sync on startup."""
    from frago.server.services.official_resource_sync_service import OfficialResourceSyncService

    result = OfficialResourceSyncService.set_sync_enabled(request.enabled)

    if result.get("status") == "ok":
        return ApiResponse(
            status="ok",
            message=f"Official resource sync {'enabled' if request.enabled else 'disabled'}",
        )
    return ApiResponse(status="error", error=result.get("error", "Failed to update setting"))


# ============================================================
# Version Check Endpoints
# ============================================================


@router.get("/settings/version", response_model=VersionInfoResponse)
async def get_version_info() -> VersionInfoResponse:
    """Get current and latest version information.

    Returns cached version data from VersionCheckService.
    The service checks PyPI every hour in background.
    """
    service = VersionCheckService.get_instance()
    info = await service.get_version_info()

    return VersionInfoResponse(
        current_version=info.get("current_version", "0.0.0"),
        latest_version=info.get("latest_version"),
        update_available=info.get("update_available", False),
        checked_at=info.get("checked_at"),
        error=info.get("error"),
    )


# ============================================================
# Self-Update Endpoints
# ============================================================


@router.post("/settings/self-update", response_model=UpdateStatusResponse)
async def start_self_update() -> UpdateStatusResponse:
    """Start self-update process.

    Initiates `uv tool upgrade frago-cli` and restarts the server.
    Progress is broadcast via WebSocket (data_update_status).
    """
    service = UpdateService.get_instance()
    result = await service.start_update()

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    status = service.get_status()
    return UpdateStatusResponse(
        status=status["status"],
        progress=status["progress"],
        message=status["message"],
        error=status["error"],
    )


@router.get("/settings/self-update/status", response_model=UpdateStatusResponse)
async def get_update_status() -> UpdateStatusResponse:
    """Get current self-update status.

    Returns the current status of any ongoing update operation.
    """
    service = UpdateService.get_instance()
    status = service.get_status()

    return UpdateStatusResponse(
        status=status["status"],
        progress=status["progress"],
        message=status["message"],
        error=status["error"],
    )


# ============================================================
# API Profile Management Endpoints
# ============================================================


class ProfileResponse(BaseModel):
    """Single profile response (API key is always masked)"""
    id: str
    name: str
    endpoint_type: str
    api_key_masked: str
    url: Optional[str] = None
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None
    is_active: bool = False
    created_at: str
    updated_at: str


class ProfileListResponse(BaseModel):
    """Profile list response"""
    profiles: List[ProfileResponse]
    active_profile_id: Optional[str] = None


class CreateProfileRequest(BaseModel):
    """Create profile request"""
    name: str
    endpoint_type: str
    api_key: str
    url: Optional[str] = None
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    """Update profile request"""
    name: Optional[str] = None
    endpoint_type: Optional[str] = None
    api_key: Optional[str] = None  # None = keep existing
    url: Optional[str] = None
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None


class SaveCurrentAsProfileRequest(BaseModel):
    """Save current config as profile request"""
    name: str


def _profile_to_response(
    profile: "APIProfile", active_id: Optional[str]
) -> ProfileResponse:
    """Convert APIProfile to ProfileResponse with masked API key."""
    from frago.init.configurator import _mask_api_key

    return ProfileResponse(
        id=profile.id,
        name=profile.name,
        endpoint_type=profile.endpoint_type,
        api_key_masked=_mask_api_key(profile.api_key),
        url=profile.url,
        default_model=profile.default_model,
        sonnet_model=profile.sonnet_model,
        haiku_model=profile.haiku_model,
        is_active=profile.id == active_id,
        created_at=profile.created_at.isoformat() if hasattr(profile.created_at, 'isoformat') else str(profile.created_at),
        updated_at=profile.updated_at.isoformat() if hasattr(profile.updated_at, 'isoformat') else str(profile.updated_at),
    )


@router.get("/settings/profiles", response_model=ProfileListResponse)
async def get_profiles() -> ProfileListResponse:
    """Get all saved API profiles with masked API keys."""
    from frago.init.profile_manager import load_profiles

    store = load_profiles()
    profiles = [
        _profile_to_response(p, store.active_profile_id)
        for p in store.profiles
    ]

    return ProfileListResponse(
        profiles=profiles,
        active_profile_id=store.active_profile_id,
    )


@router.post("/settings/profiles", response_model=ApiResponse)
async def create_profile(request: CreateProfileRequest) -> ApiResponse:
    """Create a new API profile."""
    from frago.init.profile_manager import APIProfile, add_profile

    try:
        profile = APIProfile(
            name=request.name,
            endpoint_type=request.endpoint_type,
            api_key=request.api_key,
            url=request.url,
            default_model=request.default_model,
            sonnet_model=request.sonnet_model,
            haiku_model=request.haiku_model,
        )
        add_profile(profile)
        return ApiResponse(status="ok", message=f"Profile '{request.name}' created")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.put("/settings/profiles/{profile_id}", response_model=ApiResponse)
async def update_profile_endpoint(profile_id: str, request: UpdateProfileRequest) -> ApiResponse:
    """Update an existing API profile."""
    from frago.init.profile_manager import update_profile

    try:
        updates = {k: v for k, v in request.model_dump().items() if v is not None}
        update_profile(profile_id, updates)
        return ApiResponse(status="ok", message="Profile updated")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.delete("/settings/profiles/{profile_id}", response_model=ApiResponse)
async def delete_profile_endpoint(profile_id: str) -> ApiResponse:
    """Delete an API profile. If active, configuration is preserved."""
    from frago.init.profile_manager import delete_profile

    try:
        delete_profile(profile_id)
        return ApiResponse(status="ok", message="Profile deleted")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.post("/settings/profiles/{profile_id}/activate", response_model=ApiResponse)
async def activate_profile_endpoint(profile_id: str) -> ApiResponse:
    """Activate a profile: apply its credentials as the current auth config."""
    from frago.init.profile_manager import activate_profile

    try:
        activate_profile(profile_id)

        # Refresh cache after activation
        state_manager = StateManager.get_instance()
        await state_manager.refresh_config(broadcast=True)

        return ApiResponse(status="ok", message="Profile activated")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.post("/settings/profiles/deactivate", response_model=ApiResponse)
async def deactivate_profile_endpoint() -> ApiResponse:
    """Deactivate current profile: switch back to official auth."""
    from frago.init.profile_manager import deactivate_profile

    try:
        deactivate_profile()

        # Refresh cache after deactivation
        state_manager = StateManager.get_instance()
        await state_manager.refresh_config(broadcast=True)

        return ApiResponse(status="ok", message="Switched to official authentication")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.post("/settings/profiles/from-current", response_model=ApiResponse)
async def save_current_as_profile(request: SaveCurrentAsProfileRequest) -> ApiResponse:
    """Save current ~/.claude/settings.json configuration as a new profile."""
    from frago.init.profile_manager import create_profile_from_current

    try:
        profile = create_profile_from_current(request.name)
        if not profile:
            return ApiResponse(
                status="error",
                error="No custom API configuration found in current settings",
            )
        return ApiResponse(status="ok", message=f"Profile '{request.name}' saved")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


# ============================================================
# Task Ingestion Channel Configuration
# (spec 20260422-channel-config-ui)
# ============================================================


class TaskIngestionChannelDTO(BaseModel):
    """Channel payload for GET/PUT /api/settings/task-ingestion."""
    name: str
    poll_recipe: str
    notify_recipe: str
    poll_interval_seconds: int = 120
    poll_timeout_seconds: int = 20


class TaskIngestionConfigDTO(BaseModel):
    """Top-level task-ingestion config payload."""
    enabled: bool = False
    channels: List[TaskIngestionChannelDTO] = []


class TaskIngestionGetResponse(BaseModel):
    enabled: bool
    channels: List[TaskIngestionChannelDTO]
    available_recipes: List[str]
    restart_supported: bool


class TaskIngestionPutResponse(BaseModel):
    status: str
    requires_restart: bool
    message: Optional[str] = None


@router.get(
    "/settings/task-ingestion",
    response_model=TaskIngestionGetResponse,
)
async def get_task_ingestion() -> TaskIngestionGetResponse:
    """Return current task ingestion configuration plus supporting data for the UI.

    `available_recipes` powers the poll/notify dropdowns so the client doesn't
    have to know how recipes are discovered.
    """
    from frago.init.config_manager import load_config
    from frago.recipes.lookup import list_recipe_names
    from frago.server.daemon import is_server_running

    config = load_config()
    ti = config.task_ingestion

    running, _ = is_server_running()

    return TaskIngestionGetResponse(
        enabled=ti.enabled,
        channels=[
            TaskIngestionChannelDTO(**c.model_dump()) for c in ti.channels
        ],
        available_recipes=list_recipe_names(),
        restart_supported=running,
    )


@router.put(
    "/settings/task-ingestion",
    response_model=TaskIngestionPutResponse,
)
async def put_task_ingestion(
    payload: TaskIngestionConfigDTO,
) -> TaskIngestionPutResponse:
    """Validate and persist task ingestion configuration.

    Returns `requires_restart: true` so the UI can prompt the user to restart
    the server — the IngestionScheduler only reads this config at boot.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.models import TaskIngestionChannel, TaskIngestionConfig
    from frago.recipes.lookup import validate_recipe_exists

    # Validate every referenced recipe exists up-front so partial writes don't
    # happen on first bad name.
    for ch in payload.channels:
        try:
            validate_recipe_exists(ch.poll_recipe)
            validate_recipe_exists(ch.notify_recipe)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        new_ti = TaskIngestionConfig(
            enabled=payload.enabled,
            channels=[
                TaskIngestionChannel(**ch.model_dump()) for ch in payload.channels
            ],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    config = load_config()
    config.task_ingestion = new_ti
    save_config(config)

    return TaskIngestionPutResponse(
        status="ok",
        requires_restart=True,
        message=f"Saved {len(new_ti.channels)} channel(s)",
    )


class RestartResponse(BaseModel):
    status: str
    message: str


@router.post("/server/restart", response_model=RestartResponse)
async def restart_server() -> RestartResponse:
    """Restart the frago server (daemon mode only).

    The caller's HTTP connection will be terminated as the server exits; the
    restarter daemon then brings up a fresh instance. In non-daemon mode
    (e.g. `frago server --debug`) this returns 409 so the UI can fall back
    to a textual prompt.
    """
    from frago.server.daemon import is_server_running, restart_daemon

    running, _ = is_server_running()
    if not running:
        raise HTTPException(
            status_code=409,
            detail="Server is not running in daemon mode; restart manually.",
        )

    # Fire-and-forget: restart_daemon spawns a detached restarter and then
    # stops the current process. The HTTP response may or may not make it
    # back to the client depending on timing, which is fine.
    success, message = restart_daemon(force=False)
    return RestartResponse(
        status="ok" if success else "error",
        message=message,
    )
