"""Multi-device sync API endpoints.

Provides endpoints for syncing Frago resources across multiple devices
using a GitHub repository.
"""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from frago.server.services.multidevice_sync_service import MultiDeviceSyncService

router = APIRouter()


# ============================================================
# Request/Response Models
# ============================================================


class CreateRepoRequest(BaseModel):
    """Create repository request"""
    repo_name: str
    private: bool = True


class CreateRepoResponse(BaseModel):
    """Create repository response"""
    status: str
    repo_url: Optional[str] = None
    error: Optional[str] = None


class SelectRepoRequest(BaseModel):
    """Select existing repository request"""
    repo_url: str


class SelectRepoResponse(BaseModel):
    """Select repository response"""
    status: str
    repo_url: Optional[str] = None
    error: Optional[str] = None


class GithubRepo(BaseModel):
    """GitHub repository info"""
    name: str
    full_name: str
    description: Optional[str] = None
    private: bool
    ssh_url: str
    url: str


class ListReposResponse(BaseModel):
    """List repositories response"""
    status: str
    repos: Optional[List[GithubRepo]] = None
    error: Optional[str] = None


class RepoVisibilityResponse(BaseModel):
    """Repository visibility response"""
    status: str
    is_public: Optional[bool] = None
    error: Optional[str] = None


class SyncResponse(BaseModel):
    """Sync operation response"""
    status: str  # "ok", "error", "running", "idle"
    success: Optional[bool] = None
    output: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    local_changes: Optional[int] = None
    remote_updates: Optional[int] = None
    pushed_to_remote: Optional[bool] = None
    conflicts: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    is_public_repo: Optional[bool] = None


# ============================================================
# Sync Endpoints
# ============================================================


@router.post("/sync/create-repo", response_model=CreateRepoResponse)
async def create_sync_repo(request: CreateRepoRequest) -> CreateRepoResponse:
    """Create a new GitHub repository for syncing.

    Creates a private repository by default and saves the URL to config.
    """
    result = MultiDeviceSyncService.create_sync_repo(
        repo_name=request.repo_name,
        private=request.private,
    )

    return CreateRepoResponse(
        status=result.get("status", "error"),
        repo_url=result.get("repo_url"),
        error=result.get("error"),
    )


@router.get("/sync/repos", response_model=ListReposResponse)
async def list_user_repos(limit: int = 100) -> ListReposResponse:
    """List user's GitHub repositories.

    Returns a list of repositories that can be selected for syncing.
    """
    result = MultiDeviceSyncService.list_user_repos(limit=limit)

    repos = None
    if result.get("status") == "ok" and result.get("repos"):
        repos = [
            GithubRepo(
                name=r.get("name", ""),
                full_name=r.get("full_name", r.get("name", "")),
                description=r.get("description"),
                private=r.get("private", True),
                ssh_url=r.get("ssh_url", ""),
                url=r.get("url", ""),
            )
            for r in result["repos"]
        ]

    return ListReposResponse(
        status=result.get("status", "error"),
        repos=repos,
        error=result.get("error"),
    )


@router.post("/sync/select-repo", response_model=SelectRepoResponse)
async def select_existing_repo(request: SelectRepoRequest) -> SelectRepoResponse:
    """Select an existing repository for syncing.

    Saves the repository URL to config for future sync operations.
    """
    result = MultiDeviceSyncService.select_existing_repo(request.repo_url)

    return SelectRepoResponse(
        status=result.get("status", "error"),
        repo_url=result.get("repo_url"),
        error=result.get("error"),
    )


@router.get("/sync/repo-visibility", response_model=RepoVisibilityResponse)
async def check_repo_visibility() -> RepoVisibilityResponse:
    """Check if the configured sync repository is public or private.

    Returns whether the repository is public (visible to anyone).
    """
    result = MultiDeviceSyncService.check_repo_visibility()

    return RepoVisibilityResponse(
        status=result.get("status", "error"),
        is_public=result.get("is_public"),
        error=result.get("error"),
    )


@router.post("/sync/run", response_model=SyncResponse)
async def run_sync() -> SyncResponse:
    """Start a sync operation.

    Initiates sync in the background and returns immediately.
    Use GET /sync/status to poll for completion.
    """
    result = MultiDeviceSyncService.start_sync()

    return SyncResponse(
        status=result.get("status", "error"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.get("/sync/status", response_model=SyncResponse)
async def get_sync_status() -> SyncResponse:
    """Get the status of the current or last sync operation.

    Returns "running" if sync is in progress, or the final result.
    """
    result = MultiDeviceSyncService.get_sync_result()

    return SyncResponse(
        status=result.get("status", "idle"),
        success=result.get("success"),
        output=result.get("output"),
        error=result.get("error"),
        message=result.get("message"),
        local_changes=result.get("local_changes"),
        remote_updates=result.get("remote_updates"),
        pushed_to_remote=result.get("pushed_to_remote"),
        conflicts=result.get("conflicts"),
        warnings=result.get("warnings"),
        is_public_repo=result.get("is_public_repo"),
    )
