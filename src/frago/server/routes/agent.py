"""Agent API endpoints.

Provides endpoints for starting agent tasks.
"""

from fastapi import APIRouter, HTTPException

from frago.server.adapter import FragoApiAdapter
from frago.server.models import AgentStartRequest, TaskItemResponse

router = APIRouter()


@router.post("/agent", response_model=TaskItemResponse)
async def start_agent(request: AgentStartRequest) -> TaskItemResponse:
    """Start an agent task.

    Args:
        request: Agent task request with prompt and optional project path

    Returns:
        Started task information

    Raises:
        HTTPException: 500 if agent fails to start
    """
    from datetime import datetime, timezone

    adapter = FragoApiAdapter.get_instance()

    result = adapter.start_agent(
        prompt=request.prompt,
        project_path=request.project_path,
    )

    # Check for error
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Parse started_at
    started_at = result.get("started_at")
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    elif started_at is None:
        started_at = datetime.now(timezone.utc)

    return TaskItemResponse(
        id=result.get("id", ""),
        title=result.get("title", request.prompt[:50] + "..." if len(request.prompt) > 50 else request.prompt),
        status=result.get("status", "running"),
        project_path=result.get("project_path") or request.project_path,
        agent_type=result.get("agent_type", "claude"),
        started_at=started_at,
        completed_at=None,
        duration_ms=None,
    )
