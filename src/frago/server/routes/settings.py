"""Settings API endpoints.

Provides endpoints for main config, environment variables, and GitHub integration.
"""

import os
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from frago.server.state import StateManager
from frago.server.services.gh_install_service import GhInstallService, detect_install_plan
from frago.server.services.github_service import GitHubService
from frago.server.services.main_config_service import MainConfigService
from frago.server.services.recipe_secrets_service import RecipeSecretsService
from frago.server.services.system_service import SystemService
from frago.server.services.update_service import UpdateService
from frago.server.services.version_service import VersionCheckService

router = APIRouter()


# ============================================================
# Request/Response Models
# ============================================================


class GhRateLimitResponse(BaseModel):
    """How much of GitHub's hourly request budget is left."""
    limit: int
    remaining: int
    used: int
    reset_in_seconds: int
    authenticated: bool


class GhCliStatusResponse(BaseModel):
    """GitHub CLI status response"""
    installed: bool
    authenticated: bool
    version: Optional[str] = None
    username: Optional[str] = None
    # Whether GitHub confirmed the credential just now. False with
    # authenticated=True means a token is stored but github.com could not be
    # reached to check it — a network problem, not a logged-out user.
    verified: bool = False
    verify_error: Optional[str] = None
    # Filled in only when nobody is logged in — that is when the number
    # matters, and it is the one case where 60 requests an hour runs out.
    rate_limit: GhRateLimitResponse | None = None


class GhInstallPlanResponse(BaseModel):
    """How this machine would install gh, decided before anything runs."""
    method: str  # brew | winget | binary
    command: str
    needs_path_hint: bool
    manual_url: str


class GhInstallStartResponse(BaseModel):
    """Acknowledgement that a background install is under way."""
    status: str
    already_running: bool
    method: Optional[str] = None


class GhInstallStatusResponse(BaseModel):
    """Progress of the running (or last) gh install."""
    status: str  # idle | running | success | error
    method: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    log: List[str] = []
    # Set only for the archive install, whose target sits outside the shell
    # PATH; it is the line the user adds so their own terminal finds gh too.
    path_hint: Optional[str] = None


class GhDeviceLoginResponse(BaseModel):
    """The one-time code GitHub wants typed into github.com/login/device."""
    status: str
    code: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


class GhDeviceLoginStatusResponse(BaseModel):
    """Whether the device login finished, and who it logged in as."""
    status: str
    completed: bool
    authenticated: bool
    username: Optional[str] = None
    error: Optional[str] = None


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
    resources_installed: bool = True
    resources_version: Optional[str] = None
    init_completed: bool = True


class MainConfigUpdateRequest(BaseModel):
    """Main configuration update request"""
    working_directory: Optional[str] = None
    auth_method: Optional[str] = None


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
    import asyncio

    state_manager = StateManager.get_instance()
    # Always refresh to get current status (user may have logged in/out externally)
    await state_manager.refresh_gh_status(broadcast=False)
    status = state_manager.get_gh_status()

    # Nobody logged in means every GitHub call frago makes runs on the
    # anonymous 60-per-hour budget, shared across this whole IP. Tell the
    # caller how much of it is left instead of leaving them to guess why
    # community recipes went quiet. Off the event loop: it is a network call.
    rate_limit = None
    if not status.get("authenticated", False):
        rate_limit = await asyncio.get_running_loop().run_in_executor(
            None, GitHubService.get_rate_limit
        )

    return GhCliStatusResponse(
        installed=status.get("installed", False),
        authenticated=status.get("authenticated", False),
        version=status.get("version"),
        username=status.get("username"),
        verified=status.get("verified", False),
        verify_error=status.get("verify_error"),
        rate_limit=GhRateLimitResponse(**rate_limit) if rate_limit else None,
    )


@router.post("/settings/gh-cli/login", response_model=ApiResponse)
async def gh_auth_login() -> ApiResponse:
    """Initiate GitHub CLI authentication."""
    result = GitHubService.auth_login()

    if result.get("status") == "ok":
        return ApiResponse(status="ok", message=result.get("message", "Authentication initiated"))
    return ApiResponse(status="error", error=result.get("error", "Authentication failed"))


@router.get("/settings/gh-cli/install-plan", response_model=GhInstallPlanResponse)
async def gh_install_plan() -> GhInstallPlanResponse:
    """Report how this machine would install gh, without installing anything.

    The web UI shows the user what is about to happen — which package manager,
    or that frago will download the official release itself — before they
    commit to it.
    """
    import asyncio

    plan = await asyncio.get_running_loop().run_in_executor(None, detect_install_plan)
    return GhInstallPlanResponse(**plan)


@router.post("/settings/gh-cli/install", response_model=GhInstallStartResponse)
async def gh_install_start() -> GhInstallStartResponse:
    """Start installing gh in the background.

    Installs run for minutes; holding the request open that long would time
    out in every browser. The caller polls /settings/gh-cli/install/status.
    """
    result = GhInstallService.start()
    return GhInstallStartResponse(
        status=result.get("status", "ok"),
        already_running=result.get("already_running", False),
        method=result.get("method"),
    )


@router.get("/settings/gh-cli/install/status", response_model=GhInstallStatusResponse)
async def gh_install_status() -> GhInstallStatusResponse:
    """How the running (or last) gh install is going."""
    return GhInstallStatusResponse(**GhInstallService.get_status())


@router.post("/settings/gh-cli/login/web", response_model=GhDeviceLoginResponse)
async def gh_auth_login_web() -> GhDeviceLoginResponse:
    """Start GitHub's device-code login and hand the code back to the browser.

    Unlike the terminal flow, nothing about this requires the user to be
    sitting at the machine running frago — they read an eight-character code
    off the page and type it into github.com. That matters because the 8093
    page is routinely open on a different device than the server.

    Reading gh's first lines of output can take a few seconds, so it runs off
    the event loop.
    """
    import asyncio

    result = await asyncio.get_running_loop().run_in_executor(
        None, GitHubService.auth_login_web
    )
    return GhDeviceLoginResponse(
        status=result.get("status", "error"),
        code=result.get("code"),
        url=result.get("url"),
        error=result.get("error"),
    )


@router.get("/settings/gh-cli/login/web/status", response_model=GhDeviceLoginStatusResponse)
async def gh_auth_login_web_status() -> GhDeviceLoginStatusResponse:
    """Has the user finished the device login yet?"""
    result = GitHubService.check_auth_login_complete()
    return GhDeviceLoginStatusResponse(
        status=result.get("status", "ok"),
        completed=result.get("completed", False),
        authenticated=result.get("authenticated", False),
        username=result.get("username"),
        error=result.get("error"),
    )


@router.post("/settings/gh-cli/login/web/cancel", response_model=ApiResponse)
async def gh_auth_login_web_cancel() -> ApiResponse:
    """Abandon a device login the user walked away from.

    Left alone, `gh auth login --web` polls GitHub until the code expires and
    holds a subprocess the whole time.
    """
    GitHubService.cancel_auth_login()
    return ApiResponse(status="ok", message="Login cancelled")


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
    )


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

            await MainConfigService.apply_custom_auth(
                endpoint_type=endpoint.type,
                api_key=api_key,
                url=endpoint.url,
                default_model=endpoint.default_model,
                sonnet_model=endpoint.sonnet_model,
                haiku_model=endpoint.haiku_model,
            )
        else:  # official
            await MainConfigService.apply_official_auth()

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

        SystemService.reveal_or_open(path, request.reveal)

        return ApiResponse(status="ok", message="Path opened")
    except subprocess.CalledProcessError as e:
        return ApiResponse(status="error", error=f"Failed to open path: {e}")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


# ============================================================
# VSCode Integration Endpoints
# ============================================================


@router.get("/settings/vscode-status", response_model=VSCodeStatusResponse)
async def check_vscode() -> VSCodeStatusResponse:
    """Check if VSCode is installed AND ~/.claude/settings.json exists.

    The Edit button should only show when both conditions are met.
    ~/.claude/settings.json is created when user configures custom API endpoint.
    """
    vscode_path = SystemService.find_vscode()
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

        vscode_path = SystemService.find_vscode()
        if not vscode_path:
            return ApiResponse(status="error", error="VSCode not found")

        # Use Popen to avoid blocking the server
        SystemService.open_in_vscode(vscode_path, settings_path)

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
# Prompting Capability Endpoints (static rules + LightAgent)
# ============================================================


class StaticRulesResponse(BaseModel):
    """Static routing rules layer status.

    ``count`` is None when the rule set could not be counted; the UI then says
    "in effect" without a number rather than showing a fabricated one.
    """
    available: bool = True
    count: Optional[int] = None


class LightAgentResponse(BaseModel):
    """LightAgent layer status.

    ``status`` is one of ``enabled`` / ``disabled`` / ``not_configured`` /
    ``no_key`` — see HookReviewService for how the four are told apart.
    """
    status: str
    profile_name: Optional[str] = None
    model: Optional[str] = None
    detail: Optional[str] = None


class HookReviewStatusResponse(BaseModel):
    """Both prompting layers, plus the LightAgent switch."""
    enabled: bool
    env_off: bool = False
    static_rules: StaticRulesResponse
    lightagent: LightAgentResponse


class HookReviewEnableRequest(BaseModel):
    """Flip the LightAgent switch."""
    enabled: bool


@router.get("/settings/hook-review", response_model=HookReviewStatusResponse)
async def get_hook_review_status() -> HookReviewStatusResponse:
    """Status of frago's two prompting layers.

    Read-only. The switch itself lives in ~/.frago/config.json -> hook_review.
    """
    from frago.server.services.hook_review_service import HookReviewService

    return HookReviewStatusResponse(**HookReviewService.get_status())


@router.put("/settings/hook-review", response_model=HookReviewStatusResponse)
async def set_hook_review_enabled(
    request: HookReviewEnableRequest,
) -> HookReviewStatusResponse:
    """Turn the LightAgent layer on or off.

    Persists to ~/.frago/config.json so the engine picks it up on the next hook
    event — no environment variable, no restart. Returns the recomputed status
    so the caller never has to guess what the flip resolved to.
    """
    from frago.server.services.hook_review_service import HookReviewService

    try:
        status = HookReviewService.set_enabled(request.enabled)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # config.json changed under the server's cache; refresh so every other
    # reader sees the same file the engine will read.
    state_manager = StateManager.get_instance()
    await state_manager.refresh_config(broadcast=True)

    return HookReviewStatusResponse(**status)


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


class EndpointPresetResponse(BaseModel):
    """One built-in endpoint the UI can offer, with the models it defaults to."""
    id: str
    display_name: str
    base_url: str
    default_model: str
    sonnet_model: str
    haiku_model: str


class EndpointPresetListResponse(BaseModel):
    """All built-in endpoints. 'custom' is not in here — it is not a preset."""
    presets: List[EndpointPresetResponse]


@router.get("/settings/endpoint-presets", response_model=EndpointPresetListResponse)
async def get_endpoint_presets() -> EndpointPresetListResponse:
    """The built-in endpoint table that profile forms are built from.

    Read-only, and the reason the UI no longer carries its own copy.
    """
    from frago.init.configurator import list_endpoint_presets

    return EndpointPresetListResponse(
        presets=[EndpointPresetResponse(**preset) for preset in list_endpoint_presets()]
    )


class ProfileResponse(BaseModel):
    """Single connection (API key is always masked)"""
    id: str
    name: str
    # endpoint / official / vendor_cli — what supplies the credential. The form
    # and the card both branch on it: a vendor CLI has no endpoint or key to
    # show, and printing blank ones reads as a half-filled profile.
    kind: str = "endpoint"
    endpoint_type: str
    api_key_masked: str
    url: Optional[str] = None
    # vendor_cli only: which core this connection runs.
    agent_type: Optional[str] = None
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
    # The agent CLIs the active profile was written into. Empty when nothing is
    # active — the card that shows "active" needs to be able to say where.
    active_targets: List[str] = []
    # What the worker role is bound to. None means the plain subscription.
    worker_profile_id: Optional[str] = None


class ActivationTargetResponse(BaseModel):
    """One agent CLI's standing as a place to activate a profile."""
    agent_type: str
    display_name: str
    supported: bool
    installed: bool
    selectable: bool
    path: Optional[str] = None
    # Why this CLI can never take a frago profile. Shown next to the disabled
    # checkbox: a missing option reads as a bug, an explained one does not.
    unsupported_reason: Optional[str] = None


class ActivationTargetListResponse(BaseModel):
    """Every known agent CLI, offerable or not, in display order."""
    targets: List[ActivationTargetResponse]
    # What gets used when the caller names no targets.
    default_targets: List[str] = []


class ActivateProfileRequest(BaseModel):
    """Which agent CLIs to activate this profile on.

    Omitted entirely means the historical behavior — Claude Code only — so an
    older client that posts no body keeps working unchanged.
    """
    targets: Optional[List[str]] = None


class CreateProfileRequest(BaseModel):
    """Create profile request"""
    name: str
    # Defaulted so that a client written before kinds existed still creates the
    # endpoint profiles it always did.
    kind: str = "endpoint"
    endpoint_type: str
    # Empty for a vendor CLI connection: its credential is that CLI's own login.
    api_key: str = ""
    url: Optional[str] = None
    agent_type: Optional[str] = None
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    """Update profile request"""
    name: Optional[str] = None
    kind: Optional[str] = None
    endpoint_type: Optional[str] = None
    api_key: Optional[str] = None  # None = keep existing
    url: Optional[str] = None
    agent_type: Optional[str] = None
    default_model: Optional[str] = None
    sonnet_model: Optional[str] = None
    haiku_model: Optional[str] = None


class SaveCurrentAsProfileRequest(BaseModel):
    """Save current config as profile request"""
    name: str


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    """Treat a whitespace-only field as absent.

    Optional profile fields are either a real value or nothing; a form that
    submits "" for an untouched input should not create a model override named
    the empty string.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _profile_to_response(
    profile: "APIProfile", active_id: Optional[str]
) -> ProfileResponse:
    """Convert APIProfile to ProfileResponse with masked API key."""
    from frago.init.configurator import _mask_api_key

    return ProfileResponse(
        id=profile.id,
        name=profile.name,
        kind=profile.kind,
        endpoint_type=profile.endpoint_type,
        agent_type=profile.agent_type,
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
        active_targets=list(store.active_targets),
        worker_profile_id=store.worker_profile_id,
    )


@router.post("/settings/profiles", response_model=ApiResponse)
async def create_profile(request: CreateProfileRequest) -> ApiResponse:
    """Create a new API profile."""
    from frago.init.profile_manager import APIProfile, add_profile

    try:
        profile = APIProfile(
            name=request.name,
            kind=request.kind,
            endpoint_type=request.endpoint_type,
            api_key=request.api_key,
            agent_type=_blank_to_none(request.agent_type),
            url=_blank_to_none(request.url),
            default_model=_blank_to_none(request.default_model),
            sonnet_model=_blank_to_none(request.sonnet_model),
            haiku_model=_blank_to_none(request.haiku_model),
        )
        add_profile(profile)
        return ApiResponse(status="ok", message=f"Profile '{request.name}' created")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))


@router.put("/settings/profiles/{profile_id}", response_model=ApiResponse)
async def update_profile_endpoint(profile_id: str, request: UpdateProfileRequest) -> ApiResponse:
    """Update an existing API profile.

    Only the fields the caller actually sent are touched, and an empty string
    means "clear this one". The previous rule — drop everything that is None —
    made emptying a field impossible: a user who deleted the model override in
    the form saw it saved and reappear, because the blank never reached here
    and the stale value was never overwritten. The one field that keeps its
    "empty means unchanged" meaning is api_key, which the form never prefills.
    """
    from frago.init.profile_manager import update_profile

    try:
        sent = request.model_dump(exclude_unset=True)
        updates = {
            key: value if key == "api_key" else _blank_to_none(value)
            for key, value in sent.items()
        }
        update_profile(profile_id, updates)
        return ApiResponse(status="ok", message="Profile updated")
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        return ApiResponse(status="error", error=str(e))
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


@router.get(
    "/settings/profiles/targets", response_model=ActivationTargetListResponse
)
async def get_activation_targets() -> ActivationTargetListResponse:
    """The agent CLIs a profile can be activated on, and why the others can't."""
    from frago.init.profile_targets import DEFAULT_TARGETS, list_targets

    return ActivationTargetListResponse(
        targets=[
            ActivationTargetResponse(
                agent_type=status.agent_type,
                display_name=status.display_name,
                supported=status.supported,
                installed=status.installed,
                selectable=status.selectable,
                path=status.path,
                unsupported_reason=status.unsupported_reason,
            )
            for status in list_targets()
        ],
        default_targets=list(DEFAULT_TARGETS),
    )


@router.post("/settings/profiles/{profile_id}/activate", response_model=ApiResponse)
async def activate_profile_endpoint(
    profile_id: str, request: Optional[ActivateProfileRequest] = None
) -> ApiResponse:
    """Activate a profile on the chosen agent CLIs (Claude Code if none named)."""
    from frago.init.profile_manager import activate_profile

    try:
        activated = activate_profile(profile_id, request.targets if request else None)

        # Refresh cache after activation
        state_manager = StateManager.get_instance()
        await state_manager.refresh_config(broadcast=True)

        return ApiResponse(
            status="ok", message=f"Profile activated on: {', '.join(activated)}"
        )
    except ValueError as e:
        # "Profile not found" is the only 404 here; a refused target is the
        # request being wrong about this machine, not a missing resource, and
        # its message is written to be shown to the person as-is.
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        return ApiResponse(status="error", error=str(e))
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


# ============================================================
# Role bindings — which connection main and worker each run on
# ============================================================


class VendorCoreResponse(BaseModel):
    """An agent CLI that runs on its own account rather than on a frago key.

    These are the cores a vendor_cli connection can name. They are exactly the
    ones frago cannot hand a key to, which is why they show up here instead of
    in the activation target list.
    """
    agent_type: str
    display_name: str
    installed: bool
    path: Optional[str] = None
    # Model names this CLI's own service offers. Candidates for the form, not a
    # whitelist — a name typed by hand is passed through unchanged.
    known_models: List[str] = []
    # Why it takes no frago profile, in the driver's own words.
    reason: Optional[str] = None


class RoleBindingResponse(BaseModel):
    """One role and the connection it currently runs on."""
    role: str
    # None means nothing is bound: the plain subscription for main and worker,
    # the fallback for the light agent, not running for the observer.
    profile_id: Optional[str] = None
    # None only for an unbound observer — there is nothing it runs on.
    connection: ProfileResponse | None = None
    # main only: the agent CLIs this connection was written into.
    targets: List[str] = []


class ConnectionsResponse(BaseModel):
    """Everything the two role pickers need, in one round trip."""
    connections: List[ProfileResponse]
    bindings: List[RoleBindingResponse]
    vendor_cores: List[VendorCoreResponse]


class BindRoleRequest(BaseModel):
    """Point a role at a connection. ``official`` is the built-in subscription."""
    profile_id: str
    # main only: which agent CLIs to write it into. Omitted keeps frago's
    # historical default (Claude Code).
    targets: Optional[List[str]] = None


def _vendor_cores() -> List[VendorCoreResponse]:
    """The cores that come with their own account.

    Derived from the driver registry rather than a list kept here: a CLI that
    takes no frago profile is exactly a CLI whose credential is its own, and
    that fact already lives next to its other quirks. A second list here would
    fall behind the first time someone adds a driver.
    """
    from frago.agent_driver.driver import registered_drivers

    cores: List[VendorCoreResponse] = []
    for agent_type, driver in sorted(registered_drivers().items()):
        if driver.profile_apply is not None:
            continue
        path = driver.locate() if driver.locate else None
        cores.append(
            VendorCoreResponse(
                agent_type=agent_type,
                display_name=driver.display_name or agent_type,
                installed=path is not None,
                path=path,
                known_models=list(driver.known_models),
                reason=driver.profile_unsupported_reason,
            )
        )
    return cores


@router.get("/settings/connections", response_model=ConnectionsResponse)
async def get_connections() -> ConnectionsResponse:
    """Every connection a role can be bound to, plus what each role is on now.

    The subscription leads the list and is not a saved row — see
    ``profile_manager.official_connection`` for why it is built each time.
    """
    from frago.init.profile_manager import (
        MAIN_ROLE,
        ROLES,
        list_connections,
        load_profiles,
        role_binding_id,
        role_view,
    )

    store = load_profiles()
    connections = [
        _profile_to_response(c, store.active_profile_id) for c in list_connections()
    ]

    bindings = [
        RoleBindingResponse(
            role=role,
            profile_id=role_binding_id(role),
            connection=(
                _profile_to_response(view, store.active_profile_id)
                if (view := role_view(role)) is not None
                else None
            ),
            targets=list(store.active_targets) if role == MAIN_ROLE else [],
        )
        for role in ROLES
    ]

    return ConnectionsResponse(
        connections=connections, bindings=bindings, vendor_cores=_vendor_cores()
    )


@router.put("/settings/connections/bindings/{role}", response_model=ApiResponse)
async def bind_role_endpoint(role: str, request: BindRoleRequest) -> ApiResponse:
    """Point one role at one connection.

    Binding main writes the connection into the agent CLIs' own configuration
    and so has to refresh the cached config the status card reads; binding
    worker writes nothing anywhere and changes nothing about the running
    process, so there is nothing to refresh.
    """
    from frago.init.profile_manager import MAIN_ROLE, bind_role

    try:
        bound = bind_role(role, request.profile_id, request.targets)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        # A refused binding (a vendor CLI on main, an unknown role) is the
        # request being wrong, and its message is written to be shown as-is.
        return ApiResponse(status="error", error=str(e))
    except Exception as e:
        return ApiResponse(status="error", error=str(e))

    if role == MAIN_ROLE:
        state_manager = StateManager.get_instance()
        await state_manager.refresh_config(broadcast=True)

    return ApiResponse(status="ok", message=f"{role} → {bound.name if bound else 'unbound'}")


class WorkBuddyModelResponse(BaseModel):
    """One model as the last probe found it."""
    id: str
    name: str = ""
    # On the catalog WorkBuddy hands out. Not being there does not mean unusable.
    listed: bool = False
    ok: bool
    # openai / anthropic — which of the gateway's two doors this model answers at.
    wire: str | None = None
    first_ms: int | None = None
    thinks: bool = False
    error: str | None = None


class WorkBuddyModelsResponse(BaseModel):
    """What a WorkBuddy connection can be pointed at."""
    # Whether the WorkBuddy client is logged in on this machine. Without it every
    # call fails, so the form says so before anyone picks a model.
    logged_in: bool
    probed_at: str | None = None
    models: list[WorkBuddyModelResponse] = []


@router.get("/settings/workbuddy-models", response_model=WorkBuddyModelsResponse)
async def get_workbuddy_models() -> WorkBuddyModelsResponse:
    """The last probe's findings. Re-probing is `frago-core models probe-workbuddy`."""
    import json as _json
    from datetime import datetime

    from frago.init.profile_manager import WORKBUDDY_MODELS_PATH, workbuddy_login_path

    logged_in = workbuddy_login_path().is_file()
    try:
        data = _json.loads(WORKBUDDY_MODELS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return WorkBuddyModelsResponse(logged_in=logged_in)
    models = [
        WorkBuddyModelResponse(**{k: v for k, v in m.items() if k in WorkBuddyModelResponse.model_fields})
        for m in data.get("models", [])
        if isinstance(m, dict) and isinstance(m.get("id"), str) and "ok" in m
    ]
    # frago-core stamps the probe in UTC while every other time on the page is
    # local, so 13:30 read as 05:30. The file is written the moment the probe
    # finishes; its modification time is that moment, and it reads as local time.
    probed_at = datetime.fromtimestamp(WORKBUDDY_MODELS_PATH.stat().st_mtime).isoformat(
        timespec="seconds"
    )
    return WorkBuddyModelsResponse(logged_in=logged_in, probed_at=probed_at, models=models)


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


# ============================================================
# Agent Core Preference
# (spec 20260725-opencode-core-support Phase 5)
# ============================================================


class AgentCoreResponse(BaseModel):
    """当前内核偏好 + 各内核在本机是否可用，供向导据实置灰卡片。"""
    agent_core: str
    available: dict[str, bool]


class AgentCoreUpdateRequest(BaseModel):
    agent_core: str


def _agent_core_availability() -> dict[str, bool]:
    """本机装了哪些内核。探测复用既有出口，NEVER 新写一份。"""
    from frago.compat import find_agent_cli
    from frago.init.opencode_plugin import is_opencode_present

    return {
        "claude": find_agent_cli("claude") is not None,
        "opencode": is_opencode_present(),
    }


@router.get("/settings/agent-core", response_model=AgentCoreResponse)
async def get_agent_core_setting() -> AgentCoreResponse:
    """Read the global cli-agent core preference."""
    from frago.init.config_manager import get_agent_core

    return AgentCoreResponse(
        agent_core=get_agent_core(),
        available=_agent_core_availability(),
    )


@router.put("/settings/agent-core", response_model=AgentCoreResponse)
async def put_agent_core_setting(payload: AgentCoreUpdateRequest) -> AgentCoreResponse:
    """Persist the global cli-agent core preference.

    Rejects unknown values, and rejects picking a core that is not installed
    on this machine — silently accepting it would leave every later
    `frago agent` run failing at launch with no clue why.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.models import known_agent_cores

    # 取值合法性走与 AgentType 对齐的那一份白名单（唯一判定处）。
    allowed = known_agent_cores()
    if payload.agent_core not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown agent core {payload.agent_core!r}; "
                f"expected one of {sorted(allowed)}"
            ),
        )

    available = _agent_core_availability()
    if not available.get(payload.agent_core, False):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{payload.agent_core} is not installed on this machine; "
                "install it before making it the default core"
            ),
        )

    config = load_config()
    config.agent_core = payload.agent_core
    save_config(config)

    return AgentCoreResponse(agent_core=config.agent_core, available=available)


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
