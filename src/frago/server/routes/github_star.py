"""GitHub star endpoints.

Standalone routes for starring/unstarring the frago repository. Split from
the legacy multi-device-sync route file so this community-interaction
feature survives independently.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from frago.server.services.github_service import GitHubService

router = APIRouter()


class StarredStatusResponse(BaseModel):
    """Response for checking starred status"""
    status: str
    is_starred: Optional[bool] = None
    gh_configured: bool = False
    error: Optional[str] = None


class StarRequest(BaseModel):
    """Request to star/unstar the repository"""
    star: bool


class StarResponse(BaseModel):
    """Response for star/unstar operation"""
    status: str
    is_starred: Optional[bool] = None
    error: Optional[str] = None


@router.get("/github/starred", response_model=StarredStatusResponse)
async def check_github_starred() -> StarredStatusResponse:
    """Check if user has starred the frago repository."""
    result = GitHubService.check_starred()

    return StarredStatusResponse(
        status=result.get("status", "error"),
        is_starred=result.get("is_starred"),
        gh_configured=result.get("gh_configured", False),
        error=result.get("error"),
    )


@router.post("/github/star", response_model=StarResponse)
async def toggle_github_star(request: StarRequest) -> StarResponse:
    """Star or unstar the frago repository."""
    result = GitHubService.toggle_star(request.star)

    return StarResponse(
        status=result.get("status", "error"),
        is_starred=result.get("is_starred"),
        error=result.get("error"),
    )
