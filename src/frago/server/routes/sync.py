"""Multi-device sync API endpoints.

Provides endpoints for syncing Frago resources across multiple devices
using a GitHub repository.
"""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from frago.server.state import StateManager
from frago.server.services.github_service import DEFAULT_SYNC_REPO_NAME, GitHubService
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
    Triggers cache refresh for recipes and skills after successful sync.
    """
    result = MultiDeviceSyncService.get_sync_result()

    # Refresh recipes and skills cache after successful sync
    if result.get("needs_refresh"):
        state_manager = StateManager.get_instance()
        await state_manager.refresh_recipes(broadcast=True)
        await state_manager.refresh_skills(broadcast=True)
        MultiDeviceSyncService.clear_refresh_flag()

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


# ============================================================
# GitHub Star Endpoints
# ============================================================


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


@router.get("/sync/github/starred", response_model=StarredStatusResponse)
async def check_github_starred() -> StarredStatusResponse:
    """Check if user has starred the frago repository.

    Returns the current star status and whether gh CLI is configured.
    """
    result = GitHubService.check_starred()

    return StarredStatusResponse(
        status=result.get("status", "error"),
        is_starred=result.get("is_starred"),
        gh_configured=result.get("gh_configured", False),
        error=result.get("error"),
    )


@router.post("/sync/github/star", response_model=StarResponse)
async def toggle_github_star(request: StarRequest) -> StarResponse:
    """Star or unstar the frago repository.

    Set star=true to star, star=false to unstar.
    """
    result = GitHubService.toggle_star(request.star)

    return StarResponse(
        status=result.get("status", "error"),
        is_starred=result.get("is_starred"),
        error=result.get("error"),
    )


# ============================================================
# Web Login Endpoints (New Wizard Flow)
# ============================================================


class WebLoginResponse(BaseModel):
    """Web login response with device code"""
    status: str
    code: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None


class AuthStatusResponse(BaseModel):
    """Authentication status response"""
    status: str
    completed: bool = False
    authenticated: bool = False
    username: Optional[str] = None
    error: Optional[str] = None


class SetupRepoResponse(BaseModel):
    """Setup repository response"""
    status: str
    repo_url: Optional[str] = None
    username: Optional[str] = None
    created: Optional[bool] = None
    sync_success: Optional[bool] = None
    local_changes: Optional[int] = None
    remote_updates: Optional[int] = None
    pushed_to_remote: Optional[bool] = None
    message: Optional[str] = None
    error: Optional[str] = None
    warnings: Optional[List[str]] = None
    needs_refresh: Optional[bool] = None


class CheckRepoResponse(BaseModel):
    """Check repository existence response"""
    status: str
    exists: Optional[bool] = None
    repo_url: Optional[str] = None
    is_private: Optional[bool] = None
    username: Optional[str] = None
    default_repo_name: str = DEFAULT_SYNC_REPO_NAME
    error: Optional[str] = None


@router.post("/sync/auth-login-web", response_model=WebLoginResponse)
async def start_web_login() -> WebLoginResponse:
    """Start web-based GitHub authentication.

    Initiates `gh auth login --web` and returns the device code
    for display in the web UI. The browser will be opened automatically.
    """
    result = GitHubService.auth_login_web()

    return WebLoginResponse(
        status=result.get("status", "error"),
        code=result.get("code"),
        url=result.get("url"),
        error=result.get("error"),
    )


@router.get("/sync/auth-status", response_model=AuthStatusResponse)
async def check_auth_status() -> AuthStatusResponse:
    """Check if the web login process has completed.

    Poll this endpoint to detect when user completes GitHub authorization.
    """
    result = GitHubService.check_auth_login_complete()

    return AuthStatusResponse(
        status=result.get("status", "error"),
        completed=result.get("completed", False),
        authenticated=result.get("authenticated", False),
        username=result.get("username"),
        error=result.get("error"),
    )


@router.post("/sync/auth-cancel")
async def cancel_web_login() -> dict:
    """Cancel any ongoing web login process."""
    result = GitHubService.cancel_auth_login()
    return result


@router.get("/sync/check-repo", response_model=CheckRepoResponse)
async def check_sync_repo() -> CheckRepoResponse:
    """Check if the default sync repository exists.

    Returns whether frago-working-dir repository exists for the current user.
    """
    result = MultiDeviceSyncService.check_repo_exists()

    return CheckRepoResponse(
        status=result.get("status", "error"),
        exists=result.get("exists"),
        repo_url=result.get("repo_url"),
        is_private=result.get("is_private"),
        username=result.get("username"),
        default_repo_name=DEFAULT_SYNC_REPO_NAME,
        error=result.get("error"),
    )


@router.post("/sync/setup-repo", response_model=SetupRepoResponse)
async def setup_sync_repo() -> SetupRepoResponse:
    """Start automatic repository setup.

    This will:
    1. Check if frago-working-dir exists
    2. Create it as private if not
    3. Run first sync
    """
    result = MultiDeviceSyncService.setup_sync_repo()

    return SetupRepoResponse(
        status=result.get("status", "error"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.get("/sync/setup-status", response_model=SetupRepoResponse)
async def get_setup_status() -> SetupRepoResponse:
    """Get the status of the repository setup operation.

    Poll this endpoint to track setup progress.
    Triggers cache refresh for recipes and skills after successful setup.
    """
    result = MultiDeviceSyncService.get_setup_result()

    # Refresh recipes and skills cache after successful setup
    if result.get("needs_refresh"):
        state_manager = StateManager.get_instance()
        await state_manager.refresh_recipes(broadcast=True)
        await state_manager.refresh_skills(broadcast=True)
        MultiDeviceSyncService.clear_refresh_flag()

    return SetupRepoResponse(
        status=result.get("status", "idle"),
        repo_url=result.get("repo_url"),
        username=result.get("username"),
        created=result.get("created"),
        sync_success=result.get("sync_success"),
        local_changes=result.get("local_changes"),
        remote_updates=result.get("remote_updates"),
        pushed_to_remote=result.get("pushed_to_remote"),
        message=result.get("message"),
        error=result.get("error"),
        warnings=result.get("warnings"),
        needs_refresh=result.get("needs_refresh"),
    )
