"""Agent API endpoints.

Provides endpoints for starting and continuing agent tasks.
Supports both detached (fire-and-forget) and attached (streaming) modes.
"""

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from frago.server.models import (
    AgentAttachedStartRequest,
    AgentAttachedStartResponse,
    AgentContinueRequest,
    AgentStartRequest,
    TaskItemResponse,
)
from frago.server.services.agent_service import AgentService

router = APIRouter()


async def _delayed_refresh() -> None:
    """Trigger state refresh after a short delay.

    Gives Claude Code time to create the session file before refreshing.
    """
    await asyncio.sleep(1.0)
    try:
        from frago.server.services.sync_service import SyncService
        from frago.server.state import StateManager

        SyncService.sync_now()
        state_manager = StateManager.get_instance()
        if state_manager.is_initialized():
            await state_manager.refresh_tasks(broadcast=True)
    except Exception:
        pass  # Best effort, don't fail the request


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
    from datetime import datetime

    result = AgentService.start_task(
        prompt=request.prompt,
        project_path=request.project_path,
    )

    # Check for error
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Parse started_at
    started_at = result.get("started_at")
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    elif started_at is None:
        started_at = datetime.now()

    # Schedule delayed refresh to update task list
    asyncio.create_task(_delayed_refresh())

    return TaskItemResponse(
        id=result.get("id", ""),
        title=result.get("title", request.prompt),
        status="running",
        project_path=result.get("project_path") or request.project_path,
        agent_type=result.get("agent_type", "claude"),
        started_at=started_at,
        completed_at=None,
        duration_ms=None,
    )


@router.post("/agent/{session_id}/continue")
async def continue_agent(session_id: str, request: AgentContinueRequest) -> Dict[str, Any]:
    """Continue conversation in an existing session.

    Uses the Claude session_id (from task list) to resume the conversation.
    This is the correct ID that maps to ~/.frago/sessions/claude/{session_id}/.

    Args:
        session_id: Claude session ID (NOT the web task_id)
        request: Continuation request with new prompt

    Returns:
        Status and message

    Raises:
        HTTPException: 400 if session_id is empty, 500 if continue fails
    """
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id cannot be empty")

    result = AgentService.continue_task(session_id, request.prompt)

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Schedule delayed refresh to update task list
    asyncio.create_task(_delayed_refresh())

    return result


# ============================================================
# Attached mode endpoints
# ============================================================


@router.post("/agent/attached", response_model=AgentAttachedStartResponse)
async def start_agent_attached(
    request: AgentAttachedStartRequest,
) -> AgentAttachedStartResponse:
    """Start an agent task in attached mode with real-time streaming.

    The session streams events via WebSocket (agent_* event types).
    The real Claude session ID is sent via agent_session_resolved event.

    Args:
        request: Agent task request with prompt and optional project path

    Returns:
        Attached session info with internal_id for tracking

    Raises:
        HTTPException: 500 if agent fails to start
    """
    result = await AgentService.start_task_attached(
        prompt=request.prompt,
        project_path=request.project_path,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))

    # Schedule delayed refresh to update task list
    asyncio.create_task(_delayed_refresh())

    return AgentAttachedStartResponse(
        session_id=result.get("session_id"),
        internal_id=result["internal_id"],
        status="starting",
        project_path=result["project_path"],
    )


@router.post("/agent/attached/{internal_id}/message")
async def send_message_attached(internal_id: str, request: AgentContinueRequest) -> Dict[str, Any]:
    """Send a continuation message to an attached session.

    Args:
        internal_id: Internal session ID (from start_agent_attached response)
        request: Request with continuation prompt

    Returns:
        Status dictionary

    Raises:
        HTTPException: 404 if session not found, 500 on failure
    """
    result = await AgentService.send_message_attached(internal_id, request.prompt)

    if result.get("status") == "error":
        error = result.get("error", "")
        if "not found" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=500, detail=error)

    # Schedule delayed refresh
    asyncio.create_task(_delayed_refresh())

    return result


@router.post("/agent/attached/{internal_id}/stop")
async def stop_agent_attached(internal_id: str) -> Dict[str, Any]:
    """Stop an attached session.

    Args:
        internal_id: Internal session ID

    Returns:
        Status dictionary

    Raises:
        HTTPException: 404 if session not found
    """
    result = await AgentService.stop_attached(internal_id)

    if result.get("status") == "error":
        error = result.get("error", "")
        if "not found" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=500, detail=error)

    return result


@router.get("/agent/attached/{internal_id}/info")
async def get_attached_info(internal_id: str) -> Dict[str, Any]:
    """Get info about an attached session.

    Args:
        internal_id: Internal session ID

    Returns:
        Session info

    Raises:
        HTTPException: 404 if session not found
    """
    info = AgentService.get_attached_session_info(internal_id)

    if info is None:
        raise HTTPException(status_code=404, detail=f"Attached session {internal_id} not found")

    return info
