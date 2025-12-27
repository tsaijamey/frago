"""Console API endpoints.

Provides endpoints for interactive Claude Code console sessions.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from frago.server.models import (
    ConsoleHistoryResponse,
    ConsoleMessageResponse,
    ConsoleSendMessageRequest,
    ConsoleSessionInfoResponse,
    ConsoleStartRequest,
    ConsoleStartResponse,
)
from frago.server.services.console_service import console_service

router = APIRouter()


@router.post("/console/start", response_model=ConsoleStartResponse)
async def start_console(request: ConsoleStartRequest) -> ConsoleStartResponse:
    """Start a new console session.

    Args:
        request: Console start request with initial prompt

    Returns:
        Console session information

    Raises:
        HTTPException: 500 if session fails to start
    """
    try:
        result = await console_service.create_session(
            initial_prompt=request.prompt,
            project_path=request.project_path,
            auto_approve=request.auto_approve,
        )

        return ConsoleStartResponse(
            session_id=result["session_id"],
            status=result["status"],
            project_path=result["project_path"],
            auto_approve=result["auto_approve"],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/console/{session_id}/message")
async def send_message(
    session_id: str, request: ConsoleSendMessageRequest
) -> Dict[str, Any]:
    """Send a message to an existing console session.

    Args:
        session_id: Target console session ID
        request: Message request

    Returns:
        Status dictionary

    Raises:
        HTTPException: 404 if session not found, 500 if send fails
    """
    try:
        result = await console_service.send_message(session_id, request.message)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/console/{session_id}/stop")
async def stop_console(session_id: str) -> Dict[str, Any]:
    """Stop a running console session.

    Args:
        session_id: Target console session ID

    Returns:
        Status dictionary

    Raises:
        HTTPException: 404 if session not found, 500 if stop fails
    """
    try:
        result = await console_service.stop_session(session_id)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/console/{session_id}/history", response_model=ConsoleHistoryResponse)
async def get_history(
    session_id: str, limit: int = 100, offset: int = 0
) -> ConsoleHistoryResponse:
    """Get message history for a console session.

    Args:
        session_id: Target console session ID
        limit: Maximum messages to return (default: 100)
        offset: Number of messages to skip (default: 0)

    Returns:
        Console history response

    Raises:
        HTTPException: 404 if session not found
    """
    try:
        result = console_service.get_history(session_id, limit, offset)

        return ConsoleHistoryResponse(
            messages=[
                ConsoleMessageResponse(
                    type=msg["type"],
                    content=msg["content"],
                    timestamp=msg["timestamp"],
                    tool_name=msg.get("tool_name"),
                    tool_call_id=msg.get("tool_call_id"),
                    metadata=msg.get("metadata", {}),
                )
                for msg in result["messages"]
            ],
            total=result["total"],
            has_more=result["has_more"],
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/console/{session_id}/info", response_model=ConsoleSessionInfoResponse)
async def get_session_info(session_id: str) -> ConsoleSessionInfoResponse:
    """Get console session information.

    Args:
        session_id: Target console session ID

    Returns:
        Session info response

    Raises:
        HTTPException: 404 if session not found
    """
    try:
        result = console_service.get_session_info(session_id)

        return ConsoleSessionInfoResponse(
            session_id=result["session_id"],
            project_path=result["project_path"],
            auto_approve=result["auto_approve"],
            running=result["running"],
            message_count=result["message_count"],
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
