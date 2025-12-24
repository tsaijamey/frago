"""Settings API endpoints.

Provides endpoints for main config, environment variables, and GitHub integration.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from frago.server.adapter import FragoApiAdapter

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
    adapter = FragoApiAdapter.get_instance()
    status = adapter.check_gh_cli()

    return GhCliStatusResponse(
        installed=status.get("installed", False),
        authenticated=status.get("authenticated", False),
        version=status.get("version"),
        username=status.get("username"),
    )


@router.post("/settings/gh-cli/login", response_model=ApiResponse)
async def gh_auth_login() -> ApiResponse:
    """Initiate GitHub CLI authentication."""
    adapter = FragoApiAdapter.get_instance()
    result = adapter.gh_auth_login()

    if result.get("status") == "ok":
        return ApiResponse(status="ok", message=result.get("message", "Authentication initiated"))
    return ApiResponse(status="error", error=result.get("error", "Authentication failed"))


# ============================================================
# Main Config Endpoints
# ============================================================


@router.get("/settings/main-config", response_model=MainConfigResponse)
async def get_main_config() -> MainConfigResponse:
    """Get main configuration."""
    adapter = FragoApiAdapter.get_instance()
    config = adapter.get_main_config()

    return MainConfigResponse(
        working_directory=config.get("working_directory_display", "~/.frago"),
        auth_method=config.get("auth_method", "api_key"),
        sync_repo=config.get("sync_repo_url"),
    )


@router.put("/settings/main-config", response_model=MainConfigResponse)
async def update_main_config(request: MainConfigUpdateRequest) -> MainConfigResponse:
    """Update main configuration."""
    adapter = FragoApiAdapter.get_instance()

    updates = {}
    if request.working_directory is not None:
        updates["working_directory"] = request.working_directory
    if request.auth_method is not None:
        updates["auth_method"] = request.auth_method
    if request.sync_repo is not None:
        updates["sync_repo_url"] = request.sync_repo

    result = adapter.update_main_config(updates)

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # Get the config field from the result (which contains the full config)
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
    adapter = FragoApiAdapter.get_instance()
    result = adapter.get_env_vars()

    return EnvVarsResponse(
        vars=result.get("vars", {}),
        file_exists=result.get("file_exists", False),
    )


@router.put("/settings/env-vars", response_model=EnvVarsResponse)
async def update_env_vars(request: EnvVarsUpdateRequest) -> EnvVarsResponse:
    """Update environment variables."""
    adapter = FragoApiAdapter.get_instance()
    result = adapter.update_env_vars(request.updates)

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return EnvVarsResponse(
        vars=result.get("vars", {}),
        file_exists=result.get("file_exists", True),
    )


@router.get("/settings/recipe-env-requirements", response_model=List[RecipeEnvRequirement])
async def get_recipe_env_requirements() -> List[RecipeEnvRequirement]:
    """Get environment variable requirements from recipes."""
    adapter = FragoApiAdapter.get_instance()
    requirements = adapter.get_recipe_env_requirements()

    return [
        RecipeEnvRequirement(
            name=r.get("name", ""),
            description=r.get("description"),
            required=r.get("required", False),
        )
        for r in requirements
    ]
