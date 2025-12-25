"""Settings API endpoints.

Provides endpoints for main config, environment variables, and GitHub integration.
"""

import os
import platform
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


class MainConfigResponse(BaseModel):
    """Main configuration response"""
    working_directory: str
    auth_method: str
    sync_repo: Optional[str] = None
    resources_installed: bool = True
    resources_version: Optional[str] = None
    init_completed: bool = True


class MainConfigUpdateRequest(BaseModel):
    """Main configuration update request"""
    working_directory: Optional[str] = None
    auth_method: Optional[str] = None
    sync_repo: Optional[str] = None


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
    config = MainConfigService.get_config()

    return MainConfigResponse(
        working_directory=config.get("working_directory_display", "~/.frago"),
        auth_method=config.get("auth_method", "api_key"),
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
        auth_method=config.get("auth_method", "api_key"),
        sync_repo=config.get("sync_repo_url"),
    )


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
