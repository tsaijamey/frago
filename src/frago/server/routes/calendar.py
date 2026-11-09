"""Calendar affairs API endpoints.

Provides read and write operations for daily completed affairs (~/.frago/data/calendar/),
powering both the WebUI calendar modal and external tools/agents.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from frago.calendar import store

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("/calendar/affairs")
async def list_calendar_affairs(
    month: str | None = Query(None, description="Target month (YYYY-MM)"),
    date: str | None = Query(None, description="Target date (YYYY-MM-DD)"),
    employee: str | None = Query(None, description="Filter by employee post ID"),
    category: str | None = Query(None, description="Filter by category"),
    q: str | None = Query(None, description="Search keyword across titles and summaries"),
) -> dict[str, Any]:
    """Query affairs and aggregated statistics for calendar view."""
    if month and not _MONTH_RE.match(month):
        raise HTTPException(status_code=400, detail=f"Invalid month format (want YYYY-MM): {month}")
    if date and not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail=f"Invalid date format (want YYYY-MM-DD): {date}")

    return store.get_calendar_summary(
        month=month,
        date=date,
        employee=employee,
        category=category,
        query=q,
    )


@router.post("/calendar/affairs")
async def create_or_write_affairs(request: Request) -> dict[str, Any]:
    """Create a single affair or batch write affairs (supports upsert and replace modes)."""
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON request body: {e}") from e

    if isinstance(body, list):
        items = store.write_affairs(body, mode="upsert")
        return {"ok": True, "count": len(items), "items": [it.to_dict() for it in items]}

    if isinstance(body, dict):
        if "items" in body and isinstance(body["items"], list):
            mode = str(body.get("mode") or "upsert").strip()
            default_date = body.get("default_date") or body.get("date")
            items = store.write_affairs(body["items"], default_date=default_date, mode=mode)
            return {"ok": True, "count": len(items), "items": [it.to_dict() for it in items]}

        # 单条创建
        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Missing required field 'title'")

        item = store.add_affair(
            title=title,
            date=body.get("date"),
            summary=str(body.get("summary") or ""),
            category=str(body.get("category") or "未分类"),
            tags=body.get("tags"),
            employee=body.get("employee"),
            sessions=body.get("sessions"),
            artifacts=body.get("artifacts"),
            completed_at=body.get("completed_at"),
            affair_id=body.get("id"),
        )
        return {"ok": True, "item": item.to_dict()}

    raise HTTPException(status_code=400, detail="Request body must be a JSON object or array")


@router.patch("/calendar/affairs/{item_id}")
async def update_affair_endpoint(item_id: str, request: Request) -> dict[str, Any]:
    """Update an existing affair record."""
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}") from e

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    updated = store.update_affair(item_id, **payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Affair record not found: {item_id}")

    return {"ok": True, "item": updated.to_dict()}


@router.delete("/calendar/affairs/{item_id}")
async def delete_affair_endpoint(
    item_id: str,
    date: str | None = Query(None, description="Date hint YYYY-MM-DD"),
) -> dict[str, Any]:
    """Delete an affair record."""
    ok = store.remove_affair(item_id, date=date)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Affair record not found: {item_id}")

    return {"ok": True, "id": item_id}
