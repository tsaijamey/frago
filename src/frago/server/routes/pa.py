"""Primary Agent API endpoints.

Query endpoints for PA tasks.
"""

import dataclasses
import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)


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
