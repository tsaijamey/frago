"""Claude Code sessions API endpoints.

Powers the web dashboard's session-management homepage: list raw Claude Code
sessions from ``~/.claude/projects`` (classified human / maybe / agent) and read
a single session's message stream for the detail view.
"""


from fastapi import APIRouter, HTTPException, Query

from frago.server.services import claude_sessions as svc

router = APIRouter()


@router.get("/claude-sessions")
async def list_claude_sessions(
    days: int | None = Query(None, description="Look-back window in days (default 7)"),
    since: str | None = Query(None, description="ISO date/datetime lower bound (overrides days)"),
    until: str | None = Query(None, description="ISO date/datetime upper bound (default now)"),
) -> dict:
    """Scan and return Claude Code sessions within a time window."""
    try:
        return svc.scan_sessions(days=days, since=since, until=until)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date range: {e}") from e


@router.get("/claude-sessions/{sid}")
async def get_claude_session(
    sid: str,
    limit: int = Query(200, ge=1, le=2000, description="Max messages to return (tail kept)"),
) -> dict:
    """Return the message stream for a single Claude Code session."""
    result = svc.read_session_messages(sid, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {sid}")
    return result
