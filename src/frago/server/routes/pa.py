"""Primary Agent API endpoints.

CLI chat ingestion endpoint + PA resident-session listing/send for the WebUI
claude-sessions page's "PA" tab (spec: jump straight into whichever conversation
PA is already holding open, instead of re-deriving it from Feishu).
"""

import logging
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

_GROUP_NAME_RE = re.compile(r"<group_name>([^<]*)</group_name>")


def _group_name_from_transcript(sid: str) -> str | None:
    """Best-effort recovery of a conv's display name from its own transcript.

    The in-memory reply_context cache (keyed by conv_key) is empty right after
    a server restart until that conv gets a new message. But bootstrap embeds
    ``<group_name>...</group_name>`` in the prompt text whenever the triggering
    message's reply_context happened to carry ``chat_name`` — which lands in
    the same jsonl transcript this conv's resident session uses, so it can
    survive restarts. That injection is NOT guaranteed on every turn (only
    when the inbound reply_context included it), so this scans the whole file
    rather than assuming it recurs near the tail, and returns the *last*
    occurrence (freshest name PA has ever seen for this conv — but note it can
    still be stale if the Feishu group was renamed since).
    """
    from pathlib import Path

    from frago.session.transcript_completion import locate_transcript

    path = locate_transcript(sid, cwd=str(Path.home()))
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return None
    matches = _GROUP_NAME_RE.findall(content)
    return matches[-1] if matches else None


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


class PaSendRequest(BaseModel):
    conv_key: str
    text: str


@router.get("/pa/sessions")
async def list_pa_sessions() -> dict:
    """List PA's resident conversations (``primary_agent.warm_convs``, most recent first).

    Each entry's ``sid`` is the same uuid5-derived claude session id the resident
    tmux session and transcript watcher already key off of (``_claude_session_uuid``),
    so it lines up 1:1 with ``/api/claude-sessions/{sid}`` and ``claude --resume``.
    ``group_name`` prefers the channel's cached reply_context (freshest, but
    empty until this conv gets a message after a server restart), then falls
    back to reading the last ``<group_name>`` the bootstrap ever embedded in
    this conv's own transcript (survives restarts), then the raw conv native id.
    """
    from frago.agent_driver.drivers.claude import _claude_session_uuid
    from frago.server.services.primary.lifecycle import load_warm_convs
    from frago.server.services.primary_agent_service import CONFIG_FILE, PrimaryAgentService

    pa = PrimaryAgentService.get_instance()
    sessions = []
    for conv_key in load_warm_convs(CONFIG_FILE):
        channel, _, native_id = conv_key.partition(":")
        sid = _claude_session_uuid(conv_key)
        reply_ctx = pa._reply_context_cache.get(f"conv:{conv_key}") or {}
        group_name = (
            reply_ctx.get("chat_name")
            or _group_name_from_transcript(sid)
            or native_id
            or conv_key
        )
        sessions.append({
            "conv_key": conv_key,
            "channel": channel,
            "group_name": group_name,
            "sid": sid,
            "resume_command": f"claude --resume {sid}",
        })
    return {"sessions": sessions}


@router.post("/pa/sessions/send")
async def send_pa_session_message(request: PaSendRequest) -> dict:
    """Forward WebUI PA-tab input into PA's own resident session for ``conv_key``.

    Deliberately reuses PA's own pool/session (keyed by conv_key), not the
    UI-only ``UiSessionRunner`` pool: routing through ``enqueue_message`` lands
    this on the same per-conv serial worker Feishu messages for this conv use,
    so it can never race a live Feishu turn into the same tmux pane, and it
    reuses the existing resident tmux session when warm (only cold-starts one
    when none exists yet).
    """
    from frago.server.services.primary_agent_service import PrimaryAgentService

    if not request.text.strip():
        raise HTTPException(400, "text must not be empty")

    pa = PrimaryAgentService.get_instance()
    if pa._queue_consumer_task is None or pa._queue_consumer_task.done():
        raise HTTPException(503, "PA is not running")

    was_warm = pa._get_pa_tmux_runner().session(request.conv_key) is not None

    msg_id = f"webui_{uuid4().hex[:8]}"
    msg = {
        "type": "user_message",
        "msg_id": msg_id,
        "channel": "cli",
        "channel_message_id": msg_id,
        "prompt": request.text,
        "conv_key": request.conv_key,
    }
    await pa.enqueue_message(msg)

    from frago.agent_driver.drivers.claude import _claude_session_uuid

    return {
        "sid": _claude_session_uuid(request.conv_key),
        "status": "ready" if was_warm else "activating",
        "msg_id": msg_id,
    }
