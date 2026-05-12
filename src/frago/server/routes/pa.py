"""Primary Agent API endpoints.

Query endpoints for PA tasks + CLI chat ingestion.
"""

import dataclasses
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    prompt: str
    cli_session_id: str


@router.post("/pa/chat")
async def pa_chat(request: ChatRequest) -> dict:
    """Accept a CLI chat message and enqueue for PA."""
    from frago.server.services.primary_agent_service import PrimaryAgentService

    pa = PrimaryAgentService.get_instance()
    if pa._pa_session is None:
        raise HTTPException(503, "PA is not running")

    msg_id = f"cli_{uuid4().hex[:8]}"
    msg = {
        "type": "user_message",
        "msg_id": msg_id,
        "channel": "cli",
        "channel_message_id": msg_id,
        "prompt": request.prompt,
        "reply_context": {"cli_session_id": request.cli_session_id},
    }
    await pa.enqueue_message(msg)
    return {"status": "ok", "msg_id": msg_id}


@router.get("/pa/tasks")
async def list_pa_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    status: str = Query(default="all"),
) -> dict:
    """Return recent IngestedTask list for Timeline initial load."""
    from frago.server.services.taskboard.legacy_store import TaskStore
    from frago.server.services.taskboard.models import TaskStatus

    store = TaskStore()
    if status == "all":
        tasks = store.get_recent(limit=limit)
    else:
        try:
            tasks = store.get_by_status(TaskStatus(status))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from e
    return {
        "tasks": [
            {k: v.value if hasattr(v, "value") else v for k, v in dataclasses.asdict(t).items()}
            for t in tasks[:limit]
        ],
    }
