"""Claude session transcript completion probe.

Reads a Claude Code session JSONL (``~/.claude/projects/<encode(cwd)>/<sid>.jsonl``)
and answers one authoritative question: *did the latest turn truly finish, and
what was the assistant's final text?*

The authority comes from Claude Code's own ``message.stop_reason`` field, not
from scraping the TUI screen. A turn's thinking / text / tool_use blocks each
land as separate JSONL records that share one ``requestId`` and one
``stop_reason``; the final assistant text is the concatenation of the ``text``
blocks across that requestId group.

This module is the pure parsing core of the ``transcript_completion`` recipe
(spec ``20260624-transcript-completion-recipe``). It deliberately reuses the
existing JSONL parsing helpers rather than reimplementing them:
- ``claude_sessions._extract_text`` — flatten a message content into text
- ``claude_sessions._find_session_file`` — locate ``<sid>.jsonl`` by scanning
- ``monitor.encode_project_path`` — cwd → project-encoded directory name
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.session.claude_sessions import (
    CLAUDE_PROJECTS_DIR,
    _extract_text,
    _find_session_file,
)
from frago.session.monitor import encode_project_path

logger = logging.getLogger(__name__)

# stop_reason semantics (validated against 40 real transcripts; distribution
# tool_use 3920 / end_turn 565 / stop_sequence 10 / None 4):
#   end_turn / stop_sequence -> the turn was handed back to the human: done.
#   tool_use                 -> a tool call is pending/running: NOT done.
#   None / missing           -> streaming in progress or interrupted: NOT done.
#
# WARNING re max_tokens: it is grouped into the "done" bucket here, but it can
# mean the assistant was cut off by the token ceiling and should actually be
# continued, not treated as finished. It did not appear in the sampled corpus.
# If a real max_tokens turn shows up, review whether it should trigger a
# continuation instead of being reported done.
_DONE_REASONS = frozenset({"end_turn", "stop_sequence", "max_tokens"})


@dataclass
class TurnCompletion:
    """Verdict for the latest turn at a transcript's tail."""

    done: bool                       # latest turn truly finished (handed to human)
    stop_reason: str | None          # terminal record's stop_reason (the evidence)
    final_text: str                  # assistant final text (incl. JSON decision verbatim)
    request_id: str | None           # requestId terminating the turn (text grouping key)
    last_uuid: str | None            # terminal record uuid (incremental/dedup anchor)
    pending_tool_use: bool           # tail still has a pending tool_use (stop_reason==tool_use)
    session_id: str | None
    source_path: str | None
    last_terminal_ts: datetime | None = None  # terminal record's timestamp; idle clock anchor
    is_error: bool = False           # True when isApiErrorMessage / error field / empty-answer anomaly
    error_message: str | None = None # human-readable error message (never leaked into final_text)
    empty_answer: bool = False       # True when a done turn produced no assistant text


def _parse_ts(raw: Any) -> datetime | None:
    """Parse a record's ISO8601 ``timestamp`` (e.g. ``2026-06-14T09:24:32.220Z``).

    Returns a timezone-aware UTC datetime, or None when absent/unparseable —
    the idle clock simply treats "no timestamp" as "no anchor".
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _empty(session_id: str | None = None, source_path: str | None = None) -> TurnCompletion:
    """No assistant turn yet — treated as not-done."""
    return TurnCompletion(
        done=False,
        stop_reason=None,
        final_text="",
        request_id=None,
        last_uuid=None,
        pending_tool_use=False,
        session_id=session_id,
        source_path=source_path,
    )


def _is_trailing_new_turn_signal(record: dict[str, Any]) -> bool:
    """Return True if a record after the last assistant turn starts a new pending turn.

    Recognizes:
    - A substantive non-meta, non-sidechain ``user`` message (excluding pure
      ``tool_result`` responses, which continue a tool round rather than opening a
      new user prompt).
    - A ``UserPromptSubmit`` hook injection (either ``attachment`` or
      ``system/hook_response``), which fires as a new turn begins before the first
      assistant streaming token arrives.

    Explicitly ignores trailing meta/lifecycle records (``stop_hook_summary``,
    ``turn_duration``, ``informational`` stop notices, ``last-prompt``, ``ai-title``).
    """
    if record.get("isSidechain", False):
        return False

    rec_type = record.get("type")
    if rec_type == "user":
        if record.get("isMeta", False):
            return False
        msg = record.get("message") or {}
        if msg.get("role") not in (None, "user"):
            return False
        content = msg.get("content")
        if isinstance(content, str):
            stripped = content.strip()
            if not stripped:
                return False
            return not stripped.startswith("<local-command-")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        continue
                    if block.get("type") == "text":
                        if str(block.get("text") or "").strip():
                            return True
                    else:
                        return True
                elif isinstance(block, str) and block.strip():
                    return True
            return False
        return False

    if rec_type == "attachment":
        att = record.get("attachment")
        if isinstance(att, dict):
            hook_event = str(att.get("hookEvent") or "")
            hook_name = str(att.get("hookName") or "")
            if hook_event == "UserPromptSubmit" or hook_name.startswith("UserPromptSubmit"):
                return True
        return False

    return (
        rec_type == "system"
        and record.get("subtype") == "hook_response"
        and str(record.get("hook_event") or "") == "UserPromptSubmit"
    )


def _coerce_error_text(raw: Any) -> str:
    """Flatten a record/message ``error`` field into a concise non-empty string."""
    if raw is None or raw is False:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("message", "error", "detail", "type", "code"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        try:
            return json.dumps(raw, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(raw).strip()
    return str(raw).strip()


def _extract_group_error(group: list[dict[str, Any]]) -> str | None:
    """Return an error description if any record in the turn group is an API/engine error."""
    has_error = False
    text_parts: list[str] = []
    meta_parts: list[str] = []

    for rec in group:
        msg = rec.get("message")
        msg_dict = msg if isinstance(msg, dict) else {}
        is_api_err = rec.get("isApiErrorMessage") is True
        rec_err = _coerce_error_text(rec.get("error"))
        msg_err = _coerce_error_text(msg_dict.get("error"))
        stop_is_err = msg_dict.get("stop_reason") == "error"
        api_status = rec.get("apiErrorStatus")

        if not (is_api_err or rec_err or msg_err or stop_is_err):
            continue

        has_error = True
        content_text = _extract_text(msg_dict.get("content", "")).strip()
        if content_text and content_text not in text_parts:
            text_parts.append(content_text)
        for candidate in (msg_err, rec_err):
            if candidate and candidate not in meta_parts:
                meta_parts.append(candidate)
        if api_status not in (None, "", False) and str(api_status) not in meta_parts:
            meta_parts.append(f"HTTP {api_status}")

    if not has_error:
        return None
    if text_parts:
        joined = "\n".join(text_parts)
        return joined
    if meta_parts:
        return "; ".join(meta_parts)
    return "Claude API error"


def _has_substantive_non_text_blocks(group: list[dict[str, Any]]) -> bool:
    """Return True when the turn group carries thinking or tool_use blocks (not an empty envelope)."""
    for rec in group:
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "thinking" and str(block.get("thinking") or "").strip():
                return True
            if btype == "tool_use":
                return True
    return False


def evaluate_records(
    records: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    source_path: str | None = None,
) -> TurnCompletion:
    """Judge whether the latest turn finished and extract its final text.

    Algorithm (validated against real transcripts):
      1. Keep ``type == "assistant"`` records in order, dropping sidechain
         (sub-agent) records — only the main conversation is judged.
      2. If any trailing record after that last assistant record opens a new
         turn (a substantive ``user`` prompt or ``UserPromptSubmit`` hook
         injection), report ``done=False, stop_reason=None`` so idle probes do
         not mistake an awaiting-first-token turn for finished.
      3. Otherwise, the last assistant record's ``message.stop_reason`` decides
         ``done``; ``pending_tool_use`` is True when it equals ``tool_use``.
      4. Group by that record's ``requestId`` and concatenate the ``text`` blocks
         across the group — a turn's thinking/text/tool_use are split across
         records sharing one requestId.

    Trailing ``system`` meta records (stop_hook_summary / turn_duration /
    informational notices) and last-prompt / ai-title / mode / permission-mode
    records are not new turns and do not flip a finished turn back to running.
    """
    last_assistant_idx = -1
    assistants: list[dict[str, Any]] = []
    for idx, r in enumerate(records):
        if r.get("type") == "assistant" and not r.get("isSidechain", False):
            last_assistant_idx = idx
            assistants.append(r)

    if not assistants:
        return _empty(session_id=session_id, source_path=source_path)

    terminal = assistants[-1]

    trailing = records[last_assistant_idx + 1 :]
    if any(_is_trailing_new_turn_signal(r) for r in trailing):
        return TurnCompletion(
            done=False,
            stop_reason=None,
            final_text="",
            request_id=None,
            last_uuid=terminal.get("uuid"),
            pending_tool_use=False,
            session_id=session_id or terminal.get("sessionId"),
            source_path=source_path,
            last_terminal_ts=None,
        )
    msg = terminal.get("message") or {}
    stop_reason = msg.get("stop_reason")
    request_id = terminal.get("requestId")

    if stop_reason == "max_tokens":
        logger.warning(
            "transcript turn ended with stop_reason=max_tokens (session=%s); "
            "treated as done but may be a truncated turn needing continuation",
            session_id,
        )

    # Concatenate text blocks across the terminal turn's requestId group. When
    # requestId is absent, fall back to the terminal record alone.
    if request_id is not None:
        group = [r for r in assistants if r.get("requestId") == request_id]
    else:
        group = [terminal]

    group_error = _extract_group_error(group)
    if group_error is not None:
        # API/engine error bubbles carry ``type="assistant"`` and often a text block
        # like "API Error: ..."; never leak error text as normal ``final_text``.
        return TurnCompletion(
            done=True,
            stop_reason=stop_reason,
            final_text="",
            request_id=request_id,
            last_uuid=terminal.get("uuid"),
            pending_tool_use=False,
            session_id=session_id or terminal.get("sessionId"),
            source_path=source_path,
            last_terminal_ts=_parse_ts(terminal.get("timestamp")),
            is_error=True,
            error_message=group_error,
            empty_answer=False,
        )

    parts = []
    for r in group:
        text = _extract_text((r.get("message") or {}).get("content", ""))
        if text:
            parts.append(text)
    final_text = "".join(parts)
    done = stop_reason in _DONE_REASONS
    empty_answer = bool(done and not final_text.strip())
    empty_is_error = bool(empty_answer and not _has_substantive_non_text_blocks(group))

    return TurnCompletion(
        done=done,
        stop_reason=stop_reason,
        final_text=final_text,
        request_id=request_id,
        last_uuid=terminal.get("uuid"),
        pending_tool_use=stop_reason == "tool_use",
        session_id=session_id or terminal.get("sessionId"),
        source_path=source_path,
        last_terminal_ts=_parse_ts(terminal.get("timestamp")),
        is_error=empty_is_error,
        error_message="Claude turn ended with empty response" if empty_is_error else None,
        empty_answer=empty_answer,
    )


def _read_records(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL transcript into records, tolerating bad lines.

    Mirrors ``claude_sessions`` IO discipline: utf-8 with ``errors='replace'``
    and a per-line ``json.loads`` guard so a single corrupt line never aborts
    the read. Full content is preserved — never truncated.
    """
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return records


def evaluate_file(path: str | Path) -> TurnCompletion:
    """One-shot query: read a transcript and judge its tail.

    Returns a not-done verdict when the file is missing or empty, so callers can
    simply retry on the next frame.
    """
    p = Path(path)
    if not p.exists():
        return _empty(source_path=str(p))
    try:
        records = _read_records(p)
    except OSError:
        return _empty(source_path=str(p))
    return evaluate_records(records, source_path=str(p))


def locate_transcript(
    session_id: str,
    cwd: str | None = None,
    projects_root: Path | None = None,
) -> Path | None:
    """Deterministically locate ``<sid>.jsonl``.

    Prefers ``<projects_root>/<encode(cwd)>/<sid>.jsonl`` when ``cwd`` is known
    (the path is fixed the moment ``claude --session-id`` starts), falling back
    to scanning every project dir via ``_find_session_file``.
    """
    root = projects_root or CLAUDE_PROJECTS_DIR
    if cwd:
        candidate = root / encode_project_path(cwd) / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return _find_session_file(session_id, projects_root=root)
