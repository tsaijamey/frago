"""
Session Data Persistence Storage

Provides local storage capabilities for session data, including:
- Session directory creation and management
- metadata.json read/write
- steps.jsonl append write
- summary.json generation
- Session list queries
"""

import json
import logging
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    SessionSummary,
    StepType,
    ToolCallRecord,
    ToolCallStatus,
    ToolUsageStats,
)

logger = logging.getLogger(__name__)

# Default storage directory (legacy path; Phase 1 introduces ~/.frago/projects/{domain}/...)
DEFAULT_SESSION_DIR = Path.home() / ".frago" / "sessions"
DEFAULT_PROJECTS_DIR = Path.home() / ".frago" / "projects"


def get_session_base_dir() -> Path:
    """Get session storage base directory

    Supports customization via environment variable FRAGO_SESSION_DIR.

    Returns:
        Session storage base directory path
    """
    custom_dir = os.environ.get("FRAGO_SESSION_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    return DEFAULT_SESSION_DIR


def get_projects_base_dir() -> Path:
    """Get the ~/.frago/projects base directory (Phase 1 domain layout).

    Honors ``FRAGO_PROJECTS_DIR`` env var for tests / overrides.
    """
    custom_dir = os.environ.get("FRAGO_PROJECTS_DIR")
    if custom_dir:
        return Path(custom_dir).expanduser()
    return DEFAULT_PROJECTS_DIR


def _domain_session_dir(domain: str, session_id: str) -> Path:
    """Compute the new domain-scoped session directory."""
    return get_projects_base_dir() / domain / session_id


# ============================================================
# Session Directory Management
# ============================================================


def get_session_dir(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: Optional[str] = None,
) -> Path:
    """Get session storage directory path.

    Phase 1 (run-as-domain-knowledge-base):
    - If ``domain`` is provided -> ``~/.frago/projects/{domain}/{session_id}/``
    - Otherwise -> legacy ``~/.frago/sessions/{agent_type}/{session_id}/`` (fallback)
    """
    if domain:
        return _domain_session_dir(domain, session_id)
    base_dir = get_session_base_dir()
    return base_dir / agent_type.value / session_id


def create_session_dir(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: Optional[str] = None,
) -> Path:
    """Create session storage directory."""
    session_dir = get_session_dir(session_id, agent_type, domain)
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created session directory: {session_dir}")
    return session_dir


def _scan_domain_session_dir(session_id: str) -> Optional[Path]:
    """Scan ~/.frago/projects/*/{session_id}/ to find a domain-scoped session.

    Returns the path of the first match, or None.
    """
    projects_dir = get_projects_base_dir()
    if not projects_dir.exists():
        return None
    for domain_dir in projects_dir.iterdir():
        if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
            continue
        candidate = domain_dir / session_id
        if candidate.is_dir() and (candidate / "metadata.json").exists():
            return candidate
    return None


# ============================================================
# metadata.json Read/Write
# ============================================================


def write_metadata(session: MonitoredSession) -> Path:
    """Write session metadata.

    Phase 1: when ``session.domain`` is set, write under
    ``~/.frago/projects/{domain}/{session_id}/``; otherwise fall back to the
    legacy ``~/.frago/sessions/{agent_type}/{session_id}/`` path.
    """
    session_dir = create_session_dir(
        session.session_id, session.agent_type, domain=session.domain
    )
    metadata_path = session_dir / "metadata.json"

    data = session.model_dump(mode="json")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"Wrote metadata: {metadata_path}")
    return metadata_path


def read_metadata(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: Optional[str] = None,
) -> Optional[MonitoredSession]:
    """Read session metadata.

    Resolution order:
    1. If ``domain`` is provided -> read directly from the domain path.
    2. Otherwise scan ``~/.frago/projects/*/{session_id}/metadata.json``
       (Phase 1 new layout).
    3. Fall back to the legacy ``~/.frago/sessions/{agent_type}/{session_id}/``
       path.
    """
    metadata_path: Optional[Path] = None

    if domain:
        metadata_path = _domain_session_dir(domain, session_id) / "metadata.json"
        if not metadata_path.exists():
            return None
    else:
        # Try new domain-scoped layout first.
        candidate = _scan_domain_session_dir(session_id)
        if candidate is not None:
            metadata_path = candidate / "metadata.json"
        else:
            # Fall back to legacy path.
            legacy_path = (
                get_session_base_dir() / agent_type.value / session_id / "metadata.json"
            )
            if legacy_path.exists():
                metadata_path = legacy_path

    if metadata_path is None or not metadata_path.exists():
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MonitoredSession.model_validate(data)
    except Exception as e:
        logger.warning(f"Failed to read metadata: {e}")
        return None


def update_metadata(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    **updates: Any,
) -> Optional[MonitoredSession]:
    """Update session metadata

    Args:
        session_id: Session ID
        agent_type: Agent type
        **updates: Fields to update

    Returns:
        Updated monitored session object
    """
    session = read_metadata(session_id, agent_type)
    if not session:
        return None

    # Update fields
    for key, value in updates.items():
        if hasattr(session, key):
            setattr(session, key, value)

    write_metadata(session)
    return session


# ============================================================
# steps.jsonl Append Write
# ============================================================


def append_step(
    step: SessionStep,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: Optional[str] = None,
) -> Path:
    """Append write step record.

    When ``domain`` is provided, writes under the new domain-scoped layout.
    Otherwise falls back to the legacy session path (or auto-detects an
    existing domain-scoped session).
    """
    session_dir = _resolve_existing_or_legacy_dir(step.session_id, agent_type, domain)
    session_dir.mkdir(parents=True, exist_ok=True)
    steps_path = session_dir / "steps.jsonl"

    data = step.model_dump(mode="json")
    line = json.dumps(data, ensure_ascii=False)

    with open(steps_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    logger.debug(f"Appended step {step.step_id}: {steps_path}")
    return steps_path


def _resolve_existing_or_legacy_dir(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: Optional[str] = None,
) -> Path:
    """Resolve a session directory, preferring the new domain layout.

    1. If ``domain`` is given -> ``~/.frago/projects/{domain}/{session_id}/``.
    2. Otherwise scan for an existing domain-scoped dir.
    3. Fall back to the legacy ``~/.frago/sessions/{agent_type}/{session_id}/``.
    """
    if domain:
        return _domain_session_dir(domain, session_id)
    candidate = _scan_domain_session_dir(session_id)
    if candidate is not None:
        return candidate
    return get_session_base_dir() / agent_type.value / session_id


def read_steps(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: Optional[str] = None,
) -> List[SessionStep]:
    """Read all step records."""
    session_dir = _resolve_existing_or_legacy_dir(session_id, agent_type, domain)
    steps_path = session_dir / "steps.jsonl"

    if not steps_path.exists():
        return []

    steps = []
    try:
        with open(steps_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    steps.append(SessionStep.model_validate(data))
    except Exception as e:
        logger.warning(f"Failed to read step records: {e}")

    return steps


# ============================================================
# summary.json Generation
# ============================================================


def generate_summary(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    tool_calls: Optional[List[ToolCallRecord]] = None,
    domain: Optional[str] = None,
) -> Optional[SessionSummary]:
    """Generate session summary

    Args:
        session_id: Session ID
        agent_type: Agent type
        tool_calls: Tool call record list (optional, for statistics)

    Returns:
        Session summary object
    """
    session = read_metadata(session_id, agent_type, domain=domain)
    if not session:
        return None
    effective_domain = domain or session.domain

    steps = read_steps(session_id, agent_type, domain=effective_domain)

    # Count messages
    user_count = sum(1 for s in steps if s.type == StepType.USER_MESSAGE)
    assistant_count = sum(1 for s in steps if s.type == StepType.ASSISTANT_MESSAGE)

    # Count tool calls
    tool_call_count = 0
    tool_success_count = 0
    tool_error_count = 0
    tool_usage: Counter = Counter()

    if tool_calls:
        for tc in tool_calls:
            tool_call_count += 1
            tool_usage[tc.tool_name] += 1
            if tc.status == ToolCallStatus.SUCCESS:
                tool_success_count += 1
            elif tc.status == ToolCallStatus.ERROR:
                tool_error_count += 1
    else:
        # Estimate from steps
        tool_call_count = sum(1 for s in steps if s.type == StepType.TOOL_CALL)

    # Calculate most used tools
    most_used = [
        ToolUsageStats(tool_name=name, count=count)
        for name, count in tool_usage.most_common(5)
    ]

    # Calculate duration (ensure non-negative, as timestamps in file may not be strictly ordered)
    if session.started_at and session.ended_at:
        delta = session.ended_at - session.started_at
        total_duration_ms = max(0, int(delta.total_seconds() * 1000))
    elif session.started_at and session.last_activity:
        delta = session.last_activity - session.started_at
        total_duration_ms = max(0, int(delta.total_seconds() * 1000))
    else:
        total_duration_ms = 0

    summary = SessionSummary(
        session_id=session_id,
        total_duration_ms=total_duration_ms,
        user_message_count=user_count,
        assistant_message_count=assistant_count,
        tool_call_count=tool_call_count,
        tool_success_count=tool_success_count,
        tool_error_count=tool_error_count,
        most_used_tools=most_used,
        final_status=session.status,
    )

    return summary


def write_summary(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    tool_calls: Optional[List[ToolCallRecord]] = None,
    domain: Optional[str] = None,
) -> Optional[Path]:
    """Generate and write session summary.

    Phase 1: also produces a sibling ``summary.md`` (human-readable) when
    ``summary.json`` is written.
    """
    summary = generate_summary(session_id, agent_type, tool_calls, domain=domain)
    if not summary:
        return None

    # Resolve domain (explicit arg > metadata.domain) for storage path.
    if domain is None:
        existing = read_metadata(session_id, agent_type)
        domain = existing.domain if existing else None

    session_dir = _resolve_existing_or_legacy_dir(session_id, agent_type, domain)
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = session_dir / "summary.json"

    data = summary.model_dump(mode="json")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"Wrote summary: {summary_path}")

    # Best-effort: also produce summary.md.
    try:
        write_summary_md(session_id, agent_type, summary=summary, domain=domain)
    except Exception as e:
        logger.warning(f"Failed to write summary.md: {e}")

    return summary_path


def write_summary_md(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    summary: Optional[SessionSummary] = None,
    domain: Optional[str] = None,
) -> Optional[Path]:
    """Render the session summary as human-readable markdown.

    Args:
        session_id: session identifier
        agent_type: agent type
        summary: pre-computed summary (skips a re-read when supplied)
        domain: explicit domain (overrides metadata)

    Returns:
        Path to the written ``summary.md`` (None on failure / missing data).
    """
    if summary is None:
        summary = generate_summary(session_id, agent_type, domain=domain)
    if summary is None:
        return None

    if domain is None:
        existing = read_metadata(session_id, agent_type)
        domain = existing.domain if existing else None

    session_dir = _resolve_existing_or_legacy_dir(session_id, agent_type, domain)
    session_dir.mkdir(parents=True, exist_ok=True)
    md_path = session_dir / "summary.md"

    most_used_str = (
        ", ".join(f"{t.tool_name}×{t.count}" for t in summary.most_used_tools)
        if summary.most_used_tools
        else "(none)"
    )

    lines = [
        f"# Session {session_id}",
        f"- Status: {summary.final_status.value if hasattr(summary.final_status, 'value') else summary.final_status}",
        f"- Duration: {summary.total_duration_ms} ms",
        f"- Messages: user={summary.user_message_count}, assistant={summary.assistant_message_count}",
        f"- Tool calls: {summary.tool_call_count} (success={summary.tool_success_count}, error={summary.tool_error_count})",
        f"- Most used tools: {most_used_str}",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug(f"Wrote summary.md: {md_path}")
    return md_path


def read_summary(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Optional[SessionSummary]:
    """Read session summary

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        Session summary object
    """
    session_dir = get_session_dir(session_id, agent_type)
    summary_path = session_dir / "summary.json"

    if not summary_path.exists():
        return None

    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SessionSummary.model_validate(data)
    except Exception as e:
        logger.warning(f"Failed to read summary: {e}")
        return None


# ============================================================
# Session List Queries
# ============================================================

# Threshold for switching to streaming pagination (100KB)
_STREAMING_THRESHOLD_BYTES = 100 * 1024


def _count_jsonl_lines(file_path: Path) -> int:
    """Count non-empty lines in JSONL file without loading into memory.

    Args:
        file_path: Path to JSONL file

    Returns:
        Number of non-empty lines
    """
    count = 0
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
    except Exception:
        pass
    return count


def read_steps_paginated(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    limit: int = 50,
    offset: int = 0,
    from_end: bool = False,
) -> Dict[str, Any]:
    """Read session steps with pagination.

    For small files (<100KB), loads entire file (fast enough).
    For large files, uses streaming to avoid O(file_size) memory usage.

    Args:
        session_id: Session ID
        agent_type: Agent type
        limit: Page size (default 50, max 10000)
        offset: Offset
        from_end: If True, read from end (newest first). offset=0 means latest N steps.

    Returns:
        Dictionary containing steps, total, offset, limit, has_more
    """
    # Parameter validation
    limit = max(1, min(10000, limit))
    offset = max(0, offset)

    session_dir = get_session_dir(session_id, agent_type)
    steps_path = session_dir / "steps.jsonl"

    if not steps_path.exists():
        return {
            "steps": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "has_more": False,
        }

    # Check file size to decide strategy
    try:
        file_size = steps_path.stat().st_size
    except OSError:
        file_size = 0

    # Small files: use in-memory loading (fast enough, simpler)
    if file_size < _STREAMING_THRESHOLD_BYTES:
        all_steps = read_steps(session_id, agent_type)
        total = len(all_steps)

        if from_end:
            start = max(0, total - offset - limit)
            end = total - offset
            steps = all_steps[start:end]
            steps.reverse()
            return {
                "steps": steps,
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": start > 0,
            }
        else:
            return {
                "steps": all_steps[offset : offset + limit],
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": offset + limit < total,
            }

    # Large files: streaming pagination
    total = _count_jsonl_lines(steps_path)

    if from_end:
        # Calculate range from end
        start_line = max(0, total - offset - limit)
        end_line = total - offset
    else:
        start_line = offset
        end_line = min(offset + limit, total)

    steps: List[SessionStep] = []
    try:
        with open(steps_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= end_line:
                    break
                if i >= start_line:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        steps.append(SessionStep.model_validate(data))
    except Exception as e:
        logger.warning(f"Failed to read steps with streaming pagination: {e}")

    if from_end:
        steps.reverse()
        has_more = start_line > 0
    else:
        has_more = end_line < total

    return {
        "steps": steps,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
    }


def count_sessions(
    agent_type: Optional[AgentType] = None,
    status: Optional[SessionStatus] = None,
) -> int:
    """Count sessions

    Args:
        agent_type: Filter by specific Agent type, None for all
        status: Filter by specific status

    Returns:
        Session count
    """
    base_dir = get_session_base_dir()

    if not base_dir.exists():
        return 0

    count = 0

    # Determine agent directories to search
    if agent_type:
        agent_dirs = [base_dir / agent_type.value]
    else:
        agent_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue

        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue

            metadata_path = session_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            # If status filtering needed, read metadata
            if status:
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    session_status = SessionStatus(data.get("status", "running"))
                    if session_status != status:
                        continue
                except Exception:
                    continue

            count += 1

    return count


def list_sessions(
    agent_type: Optional[AgentType] = None,
    limit: int = 20,
    status: Optional[SessionStatus] = None,
) -> List[MonitoredSession]:
    """List sessions

    Args:
        agent_type: Filter by specific Agent type, None for all
        limit: Return count limit
        status: Filter by specific status

    Returns:
        Session list, sorted by last activity time descending
    """
    base_dir = get_session_base_dir()

    if not base_dir.exists():
        return []

    # Determine agent directories to search
    if agent_type:
        agent_dirs = [base_dir / agent_type.value]
    else:
        agent_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    # Phase 1: Collect (session_dir, mtime) pairs using metadata file mtime.
    # This avoids reading and parsing every metadata.json upfront.
    candidates: list[tuple[float, Path]] = []
    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue

        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue

            metadata_path = session_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                mtime = metadata_path.stat().st_mtime
                candidates.append((mtime, session_dir))
            except OSError:
                continue

    # Phase 2: Sort by mtime descending and only parse the top N metadata files.
    # With 1000+ sessions, this avoids reading all metadata.json files.
    # Read more than `limit` to compensate for status filtering losses.
    candidates.sort(key=lambda x: x[0], reverse=True)
    read_budget = limit * 5  # read at most 5x limit to find enough matches

    sessions = []
    for _mtime, session_dir in candidates[:read_budget]:
        metadata_path = session_dir / "metadata.json"
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = MonitoredSession.model_validate(data)

            # Status filtering
            if status and session.status != status:
                continue

            sessions.append(session)
        except Exception as e:
            logger.warning(f"Failed to read session {session_dir.name}: {e}")

    # Sort by actual last_activity (more accurate than mtime)
    def get_sortable_time(s):
        t = s.last_activity
        if t.tzinfo is not None:
            t = t.replace(tzinfo=None)
        return t
    sessions.sort(key=get_sortable_time, reverse=True)

    return sessions[:limit]


def get_session_data(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Optional[Dict[str, Any]]:
    """Get complete session data

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        Dictionary containing metadata, steps, summary
    """
    session = read_metadata(session_id, agent_type)
    if not session:
        return None

    return {
        "metadata": session,
        "steps": read_steps(session_id, agent_type),
        "summary": read_summary(session_id, agent_type),
    }


def delete_session(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> bool:
    """Delete session data

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        Whether deletion was successful
    """
    import shutil

    session_dir = get_session_dir(session_id, agent_type)

    if not session_dir.exists():
        return False

    try:
        shutil.rmtree(session_dir)
        logger.info(f"Deleted session: {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        return False


def clean_old_sessions(
    max_age_days: int = 30,
    agent_type: Optional[AgentType] = None,
) -> int:
    """Clean expired sessions

    Args:
        max_age_days: Maximum retention days
        agent_type: Filter by specific Agent type

    Returns:
        Number of cleaned sessions
    """
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=max_age_days)
    sessions = list_sessions(agent_type=agent_type, limit=1000)

    cleaned = 0
    for session in sessions:
        if session.last_activity < cutoff:
            if delete_session(session.session_id, session.agent_type):
                cleaned += 1

    logger.info(f"Cleaned {cleaned} expired sessions")
    return cleaned
