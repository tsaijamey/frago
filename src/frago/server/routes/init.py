"""Init API routes for web-based frago initialization.

Provides endpoints for:
- GET /api/init/status - Get overall init status
- POST /api/init/check-deps - Trigger fresh dependency check
- POST /api/init/install-dep/{name} - Install specific dependency
- POST /api/init/install-resources - Install/update resources
- POST /api/init/complete - Mark initialization complete
- POST /api/init/reset - Reset init status for re-running wizard
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException

from frago.server.models import (
    DependencyCheckResponse,
    DependencyInstallResponse,
    DependencyStatusResponse,
    InitCompleteResponse,
    InitStatusResponse,
    InstallResultSummary,
    ResourceInstallRequest,
    ResourceInstallResponse,
)
from frago.server.services.init_service import InitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/init", tags=["init"])


@router.get("/status", response_model=InitStatusResponse)
async def get_init_status():
    """Get comprehensive initialization status.

    Returns status of:
    - Dependencies (Node.js, Claude Code)
    - Resources (commands, skills, recipes)
    - Authentication configuration
    - Overall init completion
    """
    try:
        result = InitService.get_init_status()

        # Convert to response model
        return InitStatusResponse(
            init_completed=result["init_completed"],
            node=DependencyStatusResponse(**result["node"]),
            claude_code=DependencyStatusResponse(**result["claude_code"]),
            resources_installed=result["resources_installed"],
            resources_version=result["resources_version"],
            resources_update_available=result["resources_update_available"],
            current_frago_version=result["current_frago_version"],
            auth_configured=result["auth_configured"],
            auth_method=result["auth_method"],
            resources_info=result["resources_info"],
        )
    except Exception as e:
        logger.exception("Failed to get init status")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-deps", response_model=DependencyCheckResponse)
async def check_dependencies():
    """Trigger fresh dependency check.

    Checks Node.js and Claude Code installation status.
    Returns whether all dependencies are satisfied.
    """
    try:
        result = InitService.check_dependencies()

        return DependencyCheckResponse(
            node=DependencyStatusResponse(**result["node"]),
            claude_code=DependencyStatusResponse(**result["claude_code"]),
            all_satisfied=result["all_satisfied"],
        )
    except Exception as e:
        logger.exception("Failed to check dependencies")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/install-dep/{name}", response_model=DependencyInstallResponse)
async def install_dependency(name: Literal["node", "claude-code"]):
    """Install a specific dependency.

    Args:
        name: Dependency name ("node" or "claude-code")

    Note: Node.js installation on Windows is not supported.
    The response will include installation guide for manual install.
    """
    try:
        result = InitService.install_dependency(name)

        return DependencyInstallResponse(
            status=result["status"],
            message=result["message"],
            requires_restart=result.get("requires_restart", False),
            warning=result.get("warning"),
            install_guide=result.get("install_guide"),
            error_code=result.get("error_code"),
            details=result.get("details"),
        )
    except Exception as e:
        logger.exception(f"Failed to install dependency: {name}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/install-resources", response_model=ResourceInstallResponse)
async def install_resources(request: ResourceInstallRequest = None):
    """Install or update resources (commands, skills, recipes).

    Args:
        force_update: If True, overwrite existing resources

    Resources include:
    - Claude Code commands (~/.claude/commands/)
    - Claude Code skills (~/.claude/skills/)
    - Example recipes (~/.frago/recipes/)
    """
    try:
        force_update = request.force_update if request else False
        result = InitService.install_resources(force_update=force_update)

        return ResourceInstallResponse(
            status=result["status"],
            commands=InstallResultSummary(**result["commands"]),
            skills=InstallResultSummary(**result["skills"]),
            recipes=InstallResultSummary(**result["recipes"]),
            total_installed=result["total_installed"],
            total_skipped=result["total_skipped"],
            errors=result["errors"],
            frago_version=result.get("frago_version"),
            message=result.get("message"),
        )
    except Exception as e:
        logger.exception("Failed to install resources")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete", response_model=InitCompleteResponse)
async def mark_init_complete():
    """Mark initialization as complete.

    Call this after all init steps are done.
    The init wizard will not show again once complete.
    """
    try:
        result = InitService.mark_init_complete()

        return InitCompleteResponse(
            status=result["status"],
            message=result["message"],
            init_completed=result.get("init_completed", False),
        )
    except Exception as e:
        logger.exception("Failed to mark init complete")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset", response_model=InitCompleteResponse)
async def reset_init_status():
    """Reset initialization status.

    Use this to re-run the init wizard.
    Does not remove installed resources.
    """
    try:
        result = InitService.reset_init_status()

        return InitCompleteResponse(
            status=result["status"],
            message=result["message"],
            init_completed=False,
        )
    except Exception as e:
        logger.exception("Failed to reset init status")
        raise HTTPException(status_code=500, detail=str(e))
