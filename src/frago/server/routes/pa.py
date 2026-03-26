"""Primary Agent API endpoints.

Provides the notification endpoint for sub-agents to report task completion
to the PA via the message queue, and query endpoints for PA tasks.
"""

import dataclasses
import logging

from fastapi import APIRouter, HTTPException, Query
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
    from frago.server.services.message_journal import MessageJournal
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
        # Resolve task_id from run_id so journal entries can be filtered on recovery
        resolved_task_id = None
        try:
            from frago.server.services.task_lifecycle import TaskLifecycle
            lifecycle = TaskLifecycle()
            task = lifecycle.find_task_for_run(request.run_id)
            if task:
                resolved_task_id = task.id
        except Exception:
            pass

        # Persist to journal first (survives server restart)
        journal = MessageJournal()
        journal.append(msg_type="agent_notify", task_id=resolved_task_id, payload=msg)

        await pa.enqueue_message(msg)
        logger.info("PA notify: run=%s enqueued", request.run_id[:8])
        return {"status": "ok", "run_id": request.run_id}
    except Exception as e:
        logger.exception("Failed to enqueue PA notify for run=%s", request.run_id[:8])
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/pa/tasks")
async def list_pa_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    status: str = Query(default="all"),
) -> dict:
    """Return recent IngestedTask list for Timeline initial load."""
    from frago.server.services.ingestion.models import TaskStatus
    from frago.server.services.ingestion.store import TaskStore

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
