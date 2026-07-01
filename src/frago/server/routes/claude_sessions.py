"""Claude Code sessions API endpoints.

Powers the web dashboard's session-management homepage: list raw Claude Code
sessions from ``~/.claude/projects`` (classified human / maybe / agent) and read
a single session's message stream for the detail view.

spec 20260625-webui-session-lifecycle-mediator / Phase 1 also adds a ``send``
endpoint: page input is forwarded into a resident tmux claude (context-preserving,
via the UI-only ``UiSessionRunner``), and the detail view carries a ``done`` flag
(from the transcript_completion probe) so the front-end can drive its progress bar.
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from frago.session import claude_sessions as svc
from frago.session import transcript_completion as tc
from frago.server.services.ui_session_runner import UiSessionRunner

router = APIRouter()

# UI 专用 runner（持有独立 WarmSessionPool，NEVER 复用 PA 的 pool）。懒加载单例：
# server 进程内常驻一份，跨请求复用会话池。
_ui_runner: UiSessionRunner | None = None


def _get_runner() -> UiSessionRunner:
    global _ui_runner
    if _ui_runner is None:
        _ui_runner = UiSessionRunner()
    return _ui_runner


class SendRequest(BaseModel):
    """Request body for POST /api/claude-sessions/{sid}/send."""

    text: str


def _session_cwd(sid: str) -> str | None:
    """从该会话的 jsonl 里读出 cwd，供 resume 重建时落在正确的 project 目录。

    读不到时返回 None（runner 退回默认 cwd）。只读首批记录里的 cwd 字段。
    """
    path = tc.locate_transcript(sid)
    if path is None:
        return None
    with contextlib.suppress(OSError), open(
        path, encoding="utf-8", errors="replace"
    ) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            cwd = record.get("cwd")
            if cwd:
                return cwd
    return None


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
    """Return the message stream for a single Claude Code session.

    Carries a ``done`` flag from the transcript_completion probe so the front-end
    can decide whether the latest turn finished (collapse the progress bar) or is
    still streaming / tool-using (keep it spinning). ``last_terminal_ts`` is Phase 2.
    """
    result = svc.read_session_messages(sid, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {sid}")

    path = tc.locate_transcript(sid)
    verdict = tc.evaluate_file(path) if path is not None else None
    result["done"] = bool(verdict.done) if verdict is not None else False
    result["stop_reason"] = verdict.stop_reason if verdict is not None else None
    # 终结记录 uuid 作 marker：前端发消息前记下它作基线，轮询到「done 且 marker
    # 变了」才算本轮新回复落地——否则会撞上上一轮的陈旧 done 提前收进度条。
    result["last_uuid"] = verdict.last_uuid if verdict is not None else None
    return result


@router.post("/claude-sessions/{sid}/send")
async def send_to_claude_session(sid: str, request: SendRequest) -> dict:
    """Forward page input into the resident tmux claude for this session.

    Reuses a warm session when present (context preserved); cold/evicted sessions
    are resumed and rebuilt by the pool. Returns the activation state so the
    front-end can show an "activating" progress bar on cold start.
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    runner = _get_runner()
    cwd = _session_cwd(sid)
    try:
        activation = await asyncio.to_thread(runner.send, sid, request.text, cwd=cwd)
    except Exception as e:  # noqa: BLE001 — surface drive failures as 500 with cause
        raise HTTPException(status_code=500, detail=f"send failed: {e}") from e

    return {
        "sid": activation.session_id,
        "status": activation.status,
        "text": activation.text,
    }
