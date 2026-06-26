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

from frago.server.services.claude_sessions import (
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
      2. The last assistant record's ``message.stop_reason`` decides ``done``;
         ``pending_tool_use`` is True when it equals ``tool_use``.
      3. Group by that record's ``requestId`` and concatenate the ``text`` blocks
         across the group — a turn's thinking/text/tool_use are split across
         records sharing one requestId.

    Trailing ``system`` meta records (stop_hook_summary / turn_duration) and
    last-prompt / ai-title / mode / permission-mode records are not turns and do
    not affect the verdict — they are simply not of ``type == "assistant"``.
    """
    assistants = [
        r
        for r in records
        if r.get("type") == "assistant" and not r.get("isSidechain", False)
    ]
    if not assistants:
        return _empty(session_id=session_id, source_path=source_path)

    terminal = assistants[-1]
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
    parts = []
    for r in group:
        text = _extract_text((r.get("message") or {}).get("content", ""))
        if text:
            parts.append(text)
    final_text = "".join(parts)

    return TurnCompletion(
        done=stop_reason in _DONE_REASONS,
        stop_reason=stop_reason,
        final_text=final_text,
        request_id=request_id,
        last_uuid=terminal.get("uuid"),
        pending_tool_use=stop_reason == "tool_use",
        session_id=session_id or terminal.get("sessionId"),
        source_path=source_path,
        last_terminal_ts=_parse_ts(terminal.get("timestamp")),
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
