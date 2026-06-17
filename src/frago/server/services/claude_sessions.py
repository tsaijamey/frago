"""Claude Code session scanner service.

Reads raw Claude Code session transcripts from ``~/.claude/projects/**/*.jsonl``
and produces a lightweight, UI-friendly inventory used by the web dashboard's
session-management homepage.

This is a self-contained server service. It deliberately reimplements (rather
than imports) the heuristics proven by the ``claude_sessions_scan`` recipe so
the shipped server has no runtime dependency on a user-installed recipe.

Each session is classified as human / maybe / agent so the UI can separate
conversations a person started (worth ``claude --resume``) from ones spawned by
sub-agents, Task tool, or cron triggers.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DAYS = 7

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# First user message patterns that indicate an agent/automated session
# rather than a human typing into the CLI.
_AGENT_PATTERNS = [
    re.compile(r"^\s*-?\s*你是\s+\S"),
    re.compile(r"^\s*\[Reflection Tick\]"),
    re.compile(r"^\s*---\s*待处理消息"),
    re.compile(r"^\s*<command-name>"),
    re.compile(r"^\s*你的上一条输出格式错误"),
]

_RECAP_TRAILER = "(disable recaps in /config)"


def _extract_text(content: Any) -> str:
    """Flatten a message ``content`` (str or list of blocks) into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""


def _stringify_tool_result(content: Any) -> str:
    """Flatten a tool_result ``content`` (str or list of blocks) into text.

    Tool results may be a plain string or a list of content blocks (text and/or
    image references). Full content is preserved — never truncated.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append("[image]")
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _extract_blocks(content: Any) -> list[dict[str, Any]]:
    """Parse a message ``content`` into typed blocks for the detail view.

    Preserves every block — text, thinking, tool_use (name + full input) and
    tool_result (full output) — so the panel can show all session data, not just
    the assistant's prose.
    """
    blocks: list[dict[str, Any]] = []
    if isinstance(content, str):
        if content.strip():
            blocks.append({"type": "text", "text": content})
        return blocks
    if not isinstance(content, list):
        return blocks
    for block in content:
        if isinstance(block, str):
            if block.strip():
                blocks.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if text:
                blocks.append({"type": "text", "text": text})
        elif btype == "thinking":
            blocks.append({"type": "thinking", "text": block.get("thinking", "")})
        elif btype == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "name": block.get("name", ""),
                    "tool_input": block.get("input"),
                    "tool_id": block.get("id"),
                }
            )
        elif btype == "tool_result":
            blocks.append(
                {
                    "type": "tool_result",
                    "content": _stringify_tool_result(block.get("content")),
                    "is_error": bool(block.get("is_error", False)),
                    "tool_id": block.get("tool_use_id"),
                }
            )
        elif btype == "image":
            blocks.append({"type": "image"})
    return blocks


def _classify_human(slug: str | None, first_user_text: str | None) -> tuple[str, str]:
    """Return (classification, reason) where classification is human|maybe|agent.

    A CLI-issued interactive session always carries a ``slug``. Without one we
    fall back to matching the first user message against known agent templates.
    """
    if slug:
        return "human", "has slug (CLI-issued interactive session)"
    if first_user_text:
        for pat in _AGENT_PATTERNS:
            if pat.search(first_user_text[:200]):
                return "agent", f"first user message matches agent template: {pat.pattern}"
    if first_user_text is None:
        return "agent", "no user message at all"
    return "maybe", "no slug but message doesn't match known agent patterns"


def _strip_recap_trailer(text: str | None) -> str | None:
    if not text:
        return text
    stripped = text.rstrip()
    if stripped.endswith(_RECAP_TRAILER):
        stripped = stripped[: -len(_RECAP_TRAILER)].rstrip()
    return stripped


def _iso_local(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _scan_file(path: Path) -> dict[str, Any] | None:
    """Parse a single session JSONL, extracting the fields the dashboard needs."""
    slug = None
    custom_title = None
    ai_title = None
    recap = None
    last_prompt = None
    first_user = None
    last_assistant = None
    first_ts = None
    cwd = None
    branch = None
    n_user = 0
    n_assistant = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not slug and record.get("slug"):
                    slug = record["slug"]
                rtype = record.get("type")
                if rtype == "custom-title" and record.get("customTitle"):
                    custom_title = record["customTitle"]
                elif rtype == "ai-title" and record.get("aiTitle"):
                    ai_title = record["aiTitle"]  # last-write-wins
                elif rtype == "last-prompt" and record.get("lastPrompt"):
                    last_prompt = record["lastPrompt"]
                elif (
                    rtype == "system"
                    and record.get("subtype") == "away_summary"
                    and record.get("content")
                ):
                    # Claude-generated session recap; latest wins.
                    recap = _strip_recap_trailer(record["content"])
                if not cwd and record.get("cwd"):
                    cwd = record.get("cwd")
                if not branch and record.get("gitBranch"):
                    branch = record.get("gitBranch")
                ts = record.get("timestamp")
                if ts and first_ts is None:
                    first_ts = ts
                if rtype == "user" and not record.get("isMeta"):
                    n_user += 1
                    if first_user is None:
                        msg = record.get("message") or {}
                        txt = _extract_text(msg.get("content", ""))
                        if txt and txt.strip():
                            first_user = txt.strip()
                elif rtype == "assistant":
                    n_assistant += 1
                    msg = record.get("message") or {}
                    txt = _extract_text(msg.get("content", ""))
                    if txt and txt.strip():
                        last_assistant = txt.strip()
    except OSError:
        return None
    return {
        "slug": slug,
        "custom_title": custom_title,
        "ai_title": ai_title,
        "recap": recap,
        "last_prompt": last_prompt,
        "first_user": first_user,
        "last_assistant": last_assistant,
        "first_ts": first_ts,
        "cwd": cwd,
        "branch": branch,
        "n_user": n_user,
        "n_assistant": n_assistant,
    }


def _load_sessions_index(proj_dir: Path) -> dict[str, dict[str, Any]]:
    """Map {sessionId: entry} from ``<proj_dir>/sessions-index.json`` if present."""
    f = proj_dir / "sessions-index.json"
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    entries = data.get("entries", [])
    return {e.get("sessionId"): e for e in entries if e.get("sessionId")}


def _resolve_range(
    days: int | None,
    since: str | None,
    until: str | None,
) -> tuple[float, float]:
    until_ts = datetime.fromisoformat(until).timestamp() if until else time.time()
    if since:
        since_ts = datetime.fromisoformat(since).timestamp()
    else:
        since_ts = until_ts - (days or DEFAULT_DAYS) * 86400
    return since_ts, until_ts


def scan_sessions(
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
    projects_root: Path | None = None,
) -> dict[str, Any]:
    """Scan Claude Code sessions within a time window.

    Args:
        days: look-back window in days (default 7). Overridden by ``since``.
        since: ISO date/datetime lower bound, overrides ``days``.
        until: ISO date/datetime upper bound (default now).
        projects_root: override for ``~/.claude/projects`` (tests).

    Returns an envelope dict with ``sessions`` sorted newest-first.
    """
    root = projects_root or CLAUDE_PROJECTS_DIR
    since_ts, until_ts = _resolve_range(days, since, until)

    envelope: dict[str, Any] = {
        "scanned_at": _iso_local(time.time()),
        "range": {
            "since": _iso_local(since_ts),
            "until": _iso_local(until_ts),
            "since_ts": since_ts,
            "until_ts": until_ts,
        },
        "projects_root": str(root),
        "scanned_files": 0,
        "matched_sessions": 0,
        "sessions": [],
    }

    if not root.exists():
        return envelope

    scanned = 0
    sessions: list[dict[str, Any]] = []
    for proj_dir in sorted(root.iterdir()):
        if not proj_dir.is_dir():
            continue
        index = _load_sessions_index(proj_dir)
        for jsonl in proj_dir.glob("*.jsonl"):
            scanned += 1
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            if mtime < since_ts or mtime > until_ts:
                continue
            data = _scan_file(jsonl)
            if data is None:
                continue
            sid = jsonl.stem
            human, reason = _classify_human(data["slug"], data["first_user"])
            first_user_full = data["first_user"] or ""
            last_full = data["last_assistant"] or ""
            idx_entry = index.get(sid) or {}

            first_ts_epoch = None
            if data["first_ts"]:
                with contextlib.suppress(ValueError, AttributeError):
                    first_ts_epoch = datetime.fromisoformat(
                        data["first_ts"].replace("Z", "+00:00")
                    ).timestamp()

            # away_summary (live recap) > sessions-index summary (legacy snapshot).
            recap = data["recap"] or idx_entry.get("summary") or None

            sessions.append(
                {
                    "sid": sid,
                    "human": human,
                    "human_reason": reason,
                    "name": data["slug"],
                    "title": data["custom_title"],
                    "recap": recap,
                    "ai_title": data["ai_title"],
                    "last_prompt": data["last_prompt"] or idx_entry.get("firstPrompt") or None,
                    "first_user_preview": first_user_full[:100],
                    "first_user_full": first_user_full,
                    "last_assistant_preview": last_full[:100],
                    "first_interaction_at": _iso_local(first_ts_epoch) if first_ts_epoch else None,
                    "first_interaction_ts": first_ts_epoch,
                    "last_interaction_at": _iso_local(mtime),
                    "last_interaction_ts": mtime,
                    "cwd": data["cwd"],
                    "branch": data["branch"],
                    "project": proj_dir.name,
                    "n_user_messages": data["n_user"],
                    "n_assistant_messages": data["n_assistant"],
                    "resume_command": f"claude --resume {sid}",
                }
            )

    # Sort by session start time (first interaction), newest first.
    sessions.sort(
        key=lambda s: s["first_interaction_ts"] or s["last_interaction_ts"] or 0,
        reverse=True,
    )

    envelope["scanned_files"] = scanned
    envelope["matched_sessions"] = len(sessions)
    envelope["sessions"] = sessions
    return envelope


def _find_session_file(sid: str, projects_root: Path | None = None) -> Path | None:
    root = projects_root or CLAUDE_PROJECTS_DIR
    if not root.exists():
        return None
    for proj_dir in root.iterdir():
        if not proj_dir.is_dir():
            continue
        candidate = proj_dir / f"{sid}.jsonl"
        if candidate.exists():
            return candidate
    return None


def read_session_messages(
    sid: str,
    limit: int = 200,
    projects_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the user/assistant message stream for one session, for the detail view.

    Returns ``None`` when the session file cannot be found. Tool noise and meta
    records are skipped; each message carries role, plain text, and timestamp.
    """
    path = _find_session_file(sid, projects_root)
    if path is None:
        return None

    messages: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                rtype = record.get("type")
                if rtype not in ("user", "assistant"):
                    continue
                if record.get("isMeta"):
                    continue
                msg = record.get("message") or {}
                content = msg.get("content", "")
                blocks = _extract_blocks(content)
                if not blocks:
                    continue
                text = _extract_text(content).strip()
                messages.append(
                    {
                        "role": rtype,
                        "text": text,
                        "blocks": blocks,
                        "timestamp": record.get("timestamp"),
                    }
                )
    except OSError:
        return None

    total = len(messages)
    truncated = total > limit
    if truncated:
        # Keep the most recent ``limit`` messages — the tail is what a resume
        # decision hinges on.
        messages = messages[-limit:]

    return {
        "sid": sid,
        "path": str(path),
        "total_messages": total,
        "returned_messages": len(messages),
        "truncated": truncated,
        "messages": messages,
        "resume_command": f"claude --resume {sid}",
    }
