"""Primary Agent API endpoints.

Provides the notification endpoint for sub-agents to report task completion
to the PA via the message queue.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class PANotifyRequest(BaseModel):
    """Sub-agent completion notification."""
    run_id: str
    summary: str | None = None
    error: str | None = None
    outputs: list[str] | None = None


@router.post("/pa/notify")
async def pa_notify(request: PANotifyRequest) -> dict:
    """Receive sub-agent completion notification and enqueue to PA.

    Called by sub-agents (via curl or HTTP) after task completion.
    The message enters the PA message queue and will be delivered
    to PA in the next queue drain cycle.
    """
    from frago.server.services.primary_agent_service import PrimaryAgentService

    if not request.summary and not request.error:
        raise HTTPException(
            status_code=400,
            detail="Either 'summary' or 'error' must be provided",
        )

    pa = PrimaryAgentService.get_instance()

    msg = {
        "type": "agent_notify",
        "run_id": request.run_id,
    }
    if request.summary:
        msg["summary"] = request.summary
    if request.error:
        msg["error"] = request.error
    if request.outputs:
        msg["outputs"] = request.outputs

    try:
        await pa.enqueue_message(msg)
        logger.info("PA notify: run=%s enqueued", request.run_id[:8])
        return {"status": "ok", "run_id": request.run_id}
    except Exception as e:
        logger.exception("Failed to enqueue PA notify for run=%s", request.run_id[:8])
        raise HTTPException(status_code=500, detail=str(e)) from e
