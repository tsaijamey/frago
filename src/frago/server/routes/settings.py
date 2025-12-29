"""Settings API endpoints.

Provides endpoints for main config, environment variables, and GitHub integration.
"""

import os
import platform
import shutil
import subprocess
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from frago.server.services.env_service import EnvService
from frago.server.services.github_service import GitHubService
from frago.server.services.main_config_service import MainConfigService

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
    api_key: str
    url: Optional[str] = None  # Only for custom type
    default_model: Optional[str] = None  # Override for ANTHROPIC_MODEL
    sonnet_model: Optional[str] = None   # Override for ANTHROPIC_DEFAULT_SONNET_MODEL
    haiku_model: Optional[str] = None    # Override for ANTHROPIC_DEFAULT_HAIKU_MODEL


class AuthUpdateRequest(BaseModel):
    """Authentication update request"""
    auth_method: str  # official or custom
    api_endpoint: Optional[APIEndpointRequest] = None


class EnvVarsResponse(BaseModel):
    """Environment variables response"""
    vars: Dict[str, str]
    file_exists: bool


class EnvVarsUpdateRequest(BaseModel):
    """Environment variables update request"""
    updates: Dict[str, Optional[str]]  # None value means delete


class RecipeEnvRequirement(BaseModel):
    """Recipe environment variable requirement"""
    name: str
    description: Optional[str] = None
    required: bool = False
    configured: bool = False
    recipe_name: Optional[str] = None


class ApiResponse(BaseModel):
    """Generic API response"""
    status: str
    message: Optional[str] = None
    error: Optional[str] = None


class VSCodeStatusResponse(BaseModel):
    """VSCode installation status response"""
    available: bool  # True only if VSCode installed AND settings.json exists


# ============================================================
# GitHub CLI Endpoints
# ============================================================


@router.get("/settings/gh-cli", response_model=GhCliStatusResponse)
async def check_gh_cli() -> GhCliStatusResponse:
    """Check GitHub CLI installation and authentication status."""
    status = GitHubService.check_gh_cli()

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
    """Get main configuration."""
    from frago.init.configurator import PRESET_ENDPOINTS

    config = MainConfigService.get_config()

    # Build api_endpoint response if exists
    api_endpoint = None
    if config.get("api_endpoint"):
        ep = config["api_endpoint"]
        ep_type = ep.get("type", "custom")

        # Get preset defaults if available
        preset = PRESET_ENDPOINTS.get(ep_type, {})
        default_model = ep.get("default_model") or preset.get("ANTHROPIC_MODEL")
        sonnet_model = ep.get("sonnet_model") or preset.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        haiku_model = ep.get("haiku_model") or preset.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")

        api_endpoint = APIEndpointResponse(
            type=ep_type,
            url=ep.get("url"),
            api_key=ep.get("api_key", ""),
            default_model=default_model,
            sonnet_model=sonnet_model,
            haiku_model=haiku_model,
        )

    return MainConfigResponse(
        working_directory=config.get("working_directory_display", "~/.frago"),
        auth_method=config.get("auth_method", "official"),
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

    # Get the config field from the result
    config = result.get("config", result)

    return MainConfigResponse(
        working_directory=config.get("working_directory_display", "~/.frago"),
        auth_method=config.get("auth_method", "official"),
        sync_repo=config.get("sync_repo_url"),
    )


@router.post("/settings/update-auth", response_model=ApiResponse)
async def update_auth(request: AuthUpdateRequest) -> ApiResponse:
    """Update authentication method and API endpoint.

    When auth_method is 'custom', creates ~/.claude/settings.json with the API config.
    When auth_method is 'official', deletes ~/.claude/settings.json.
    """
    from frago.init.config_manager import load_config, save_config
    from frago.init.configurator import (
        build_claude_env_config,
        save_claude_settings,
        delete_claude_settings,
        ensure_claude_json_for_custom_auth,
    )
    from frago.init.models import APIEndpoint

    try:
        # Load existing config
        config = load_config()

        if request.auth_method == "custom":
            if not request.api_endpoint:
                return ApiResponse(status="error", error="API endpoint required for custom auth")

            endpoint = request.api_endpoint

            # Build env config for Claude Code
            env_config = build_claude_env_config(
                endpoint_type=endpoint.type,
                api_key=endpoint.api_key,
                custom_url=endpoint.url if endpoint.type == "custom" else None,
                default_model=endpoint.default_model,
                sonnet_model=endpoint.sonnet_model,
                haiku_model=endpoint.haiku_model,
            )

            # Ensure ~/.claude.json exists (to skip official login)
            ensure_claude_json_for_custom_auth()

            # Save to ~/.claude/settings.json
            save_claude_settings({"env": env_config})

            # Update frago config
            config.auth_method = "custom"
            config.api_endpoint = APIEndpoint(
                type=endpoint.type,
                api_key=endpoint.api_key,
                url=endpoint.url,
                default_model=endpoint.default_model,
                sonnet_model=endpoint.sonnet_model,
                haiku_model=endpoint.haiku_model,
            )

        else:  # official
            # Delete ~/.claude/settings.json
            delete_claude_settings()

            # Update frago config
            config.auth_method = "official"
            config.api_endpoint = None

        # Save frago config
        save_config(config)

        return ApiResponse(status="ok", message="Authentication updated")

    except Exception as e:
        return ApiResponse(status="error", error=str(e))


# ============================================================
# Environment Variables Endpoints
# ============================================================


@router.get("/settings/env-vars", response_model=EnvVarsResponse)
async def get_env_vars() -> EnvVarsResponse:
    """Get environment variables from .env file."""
    result = EnvService.get_env_vars()

    return EnvVarsResponse(
        vars=result.get("vars", {}),
        file_exists=result.get("file_exists", False),
    )


@router.put("/settings/env-vars", response_model=EnvVarsResponse)
async def update_env_vars(request: EnvVarsUpdateRequest) -> EnvVarsResponse:
    """Update environment variables."""
    result = EnvService.update_env_vars(request.updates)

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return EnvVarsResponse(
        vars=result.get("vars", {}),
        file_exists=result.get("file_exists", True),
    )


@router.get("/settings/recipe-env-requirements", response_model=List[RecipeEnvRequirement])
async def get_recipe_env_requirements() -> List[RecipeEnvRequirement]:
    """Get environment variable requirements from recipes."""
    requirements = EnvService.get_recipe_env_requirements()

    return [
        RecipeEnvRequirement(
            name=r.get("var_name", ""),
            description=r.get("description"),
            required=r.get("required", False),
            configured=r.get("configured", False),
            recipe_name=r.get("recipe_name"),
        )
        for r in requirements
    ]


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
                subprocess.run(["explorer", "/select,", path], check=True)
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
            subprocess.Popen([vscode_path, settings_path])

        return ApiResponse(status="ok", message="Opened in VSCode")
    except Exception as e:
        return ApiResponse(status="error", error=str(e))
