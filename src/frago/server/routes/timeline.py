"""Timeline API endpoints.

Provides aggregated timeline data for the frontend live feed.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/timeline")
async def get_timeline(
    since: Optional[str] = Query(default=None, description="ISO timestamp — events after this time"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Get aggregated timeline events.

    Merges IngestedTask + PA events + Run logs into a unified event stream.
    Each event has humanized title/subtitle ready for frontend rendering.
    """
    from frago.server.services.timeline_service import get_timeline as _get_timeline

    events = _get_timeline(since=since, limit=limit)
    return {"events": events}
