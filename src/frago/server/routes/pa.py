"""Primary Agent API endpoints.

CLI chat ingestion endpoint.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
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
    if pa._queue_consumer_task is None or pa._queue_consumer_task.done():
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
