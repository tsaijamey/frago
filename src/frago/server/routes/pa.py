"""Primary Agent API endpoints.

Query endpoints for PA tasks + CLI chat ingestion.
"""

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
    """Return recent task list for Timeline initial load.

    Single source: board.timeline.jsonl. We walk the board.view_for_pa()
    snapshot, flatten msg → task pairs, and serialise into the JSON shape
    the frontend expects (id, channel, status, prompt, ...).
    """
    from frago.server.services.taskboard import get_board

    valid_status = {
        "all", "queued", "executing", "completed", "failed",
        "resume_failed", "replied",
    }
    if status not in valid_status:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    board = get_board()
    view = board.view_for_pa()
    out: list[dict] = []
    for t in view.get("threads", []):
        for m in t.get("msgs", []):
            channel = m.get("channel") or t.get("subkind") or "unknown"
            msg_id = m.get("id", "")
            channel_msg_id = msg_id.split(":", 1)[1] if ":" in msg_id else msg_id
            for tk in m.get("tasks", []):
                if status != "all" and tk.get("status") != status:
                    continue
                out.append({
                    "id": tk.get("id"),
                    "channel": channel,
                    "channel_message_id": channel_msg_id,
                    "status": tk.get("status"),
                    "type": tk.get("type"),
                    "thread_id": t.get("id"),
                    "reply_context": m.get("reply_context") or {},
                })
    out.sort(key=lambda d: d.get("id", ""), reverse=True)
    return {"tasks": out[:limit]}
