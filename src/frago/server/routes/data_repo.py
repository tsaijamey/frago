"""Data repository API endpoints.

Backs the 数据仓库 page: what is pending in ``~/.frago``, what will and will
not be backed up, and starting the agent that does the grouping, committing
and pushing.

Everything here is token-zone by default, like the rest of ``/api``. That is
the right call and not an oversight: these endpoints read the owner's entire
working directory and can start an agent on their machine.
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from frago.server.services.data_repo_service import (
    DEFAULT_FILE_LIMIT,
    MAX_FILE_LIMIT,
    DataRepoSync,
    build_sync_prompt,
    get_policy,
    get_status,
)

router = APIRouter()


# ============================================================
# Models
# ============================================================


class PendingFile(BaseModel):
    """One path waiting to be backed up."""
    path: str
    status: str  # modified | added | deleted | renamed | untracked | conflicted


class AreaCount(BaseModel):
    """How much is pending under one top-level area of the repository."""
    area: str
    count: int


class LastCommit(BaseModel):
    sha: str
    subject: str
    committed_at: str


class DataRepoStatusResponse(BaseModel):
    """What is waiting to be backed up."""
    # False when ~/.frago is not a git repository yet — a setup state the page
    # explains, not an error.
    configured: bool
    repo_path: str
    remote_url: Optional[str] = None
    branch: Optional[str] = None
    # Commits made locally but not yet pushed, and the reverse.
    ahead: int = 0
    behind: int = 0
    pending_total: int = 0
    counts: Dict[str, int] = {}
    # Pending counts per top-level directory. This is what makes five figures
    # of changed files legible; the flat list never could.
    rollup: List[AreaCount] = []
    # A capped sample, not the whole set — see `truncated`.
    files: List[PendingFile] = []
    truncated: bool = False
    last_commit: Optional[LastCommit] = None
    error: Optional[str] = None


class ExcludedCategory(BaseModel):
    key: str
    title: str
    examples: List[str]
    why: str


class IncludedArea(BaseModel):
    path: str
    note: str


class DataRepoPolicyResponse(BaseModel):
    """What the confirmation dialog tells the user before anything runs."""
    excluded: List[ExcludedCategory]
    included: List[IncludedArea]


class SyncStartRequest(BaseModel):
    mode: str = Field("all", pattern="^(all|selective)$")
    # Only read for selective mode: the user's own words for what to back up.
    instruction: Optional[str] = Field(None, max_length=4000)


class SyncTask(BaseModel):
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    pid: Optional[int] = None
    mode: Optional[str] = None
    instruction: Optional[str] = None
    started_at: Optional[str] = None


class SyncStartResponse(BaseModel):
    status: str
    already_running: bool = False
    task: Optional[SyncTask] = None
    error: Optional[str] = None


class SyncStatusResponse(BaseModel):
    running: bool
    task: Optional[SyncTask] = None


class SyncPromptResponse(BaseModel):
    """The brief that would be handed to the agent, for the curious.

    Someone about to let an agent commit their entire working directory is
    entitled to read the instructions it will be following first.
    """
    prompt: str


# ============================================================
# Endpoints
# ============================================================


@router.get("/data-repo/status", response_model=DataRepoStatusResponse)
async def data_repo_status(
    limit: int = Query(DEFAULT_FILE_LIMIT, ge=0, le=MAX_FILE_LIMIT),
) -> DataRepoStatusResponse:
    """What is pending in the data repository.

    Runs off the event loop: on a working directory in daily use this shells
    out over tens of thousands of paths.
    """
    status = await asyncio.get_running_loop().run_in_executor(None, get_status, limit)
    return DataRepoStatusResponse(**status)


@router.get("/data-repo/policy", response_model=DataRepoPolicyResponse)
async def data_repo_policy() -> DataRepoPolicyResponse:
    """What is backed up and what is deliberately left behind."""
    return DataRepoPolicyResponse(**get_policy())


@router.get("/data-repo/sync/prompt", response_model=SyncPromptResponse)
async def data_repo_sync_prompt(
    mode: str = Query("all", pattern="^(all|selective)$"),
    instruction: Optional[str] = Query(None, max_length=4000),
) -> SyncPromptResponse:
    """Preview the brief without starting anything."""
    return SyncPromptResponse(prompt=build_sync_prompt(mode, instruction))


@router.post("/data-repo/sync", response_model=SyncStartResponse)
async def data_repo_sync_start(request: SyncStartRequest) -> SyncStartResponse:
    """Hand the backup to an agent.

    Returns as soon as the agent is launched. Grouping tens of thousands of
    files into coherent commits takes minutes; the page follows along by
    polling, and the work shows up in the session workbench like any other
    agent task.
    """
    result: dict[str, Any] = await asyncio.get_running_loop().run_in_executor(
        None, DataRepoSync.start, request.mode, request.instruction
    )
    task = result.get("task")
    return SyncStartResponse(
        status=result.get("status", "error"),
        already_running=result.get("already_running", False),
        task=SyncTask(**task) if task else None,
        error=result.get("error"),
    )


@router.get("/data-repo/sync/status", response_model=SyncStatusResponse)
async def data_repo_sync_status() -> SyncStatusResponse:
    """Is a sync still running, and which one."""
    state = DataRepoSync.get()
    task = state.get("task")
    return SyncStatusResponse(
        running=state.get("running", False),
        task=SyncTask(**task) if task else None,
    )
