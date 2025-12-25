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

# Default storage directory
DEFAULT_SESSION_DIR = Path.home() / ".frago" / "sessions"


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


# ============================================================
# Session Directory Management
# ============================================================


def get_session_dir(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Path:
    """Get session storage directory path

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        Session directory path
    """
    base_dir = get_session_base_dir()
    return base_dir / agent_type.value / session_id


def create_session_dir(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Path:
    """Create session storage directory

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        Created session directory path
    """
    session_dir = get_session_dir(session_id, agent_type)
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created session directory: {session_dir}")
    return session_dir


# ============================================================
# metadata.json Read/Write
# ============================================================


def write_metadata(session: MonitoredSession) -> Path:
    """Write session metadata

    Args:
        session: Monitored session object

    Returns:
        metadata.json file path
    """
    session_dir = create_session_dir(session.session_id, session.agent_type)
    metadata_path = session_dir / "metadata.json"

    data = session.model_dump(mode="json")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"Wrote metadata: {metadata_path}")
    return metadata_path


def read_metadata(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> Optional[MonitoredSession]:
    """Read session metadata

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        Monitored session object, None if does not exist
    """
    session_dir = get_session_dir(session_id, agent_type)
    metadata_path = session_dir / "metadata.json"

    if not metadata_path.exists():
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


def append_step(step: SessionStep, agent_type: AgentType = AgentType.CLAUDE) -> Path:
    """Append write step record

    Args:
        step: Session step object
        agent_type: Agent type

    Returns:
        steps.jsonl file path
    """
    session_dir = create_session_dir(step.session_id, agent_type)
    steps_path = session_dir / "steps.jsonl"

    data = step.model_dump(mode="json")
    line = json.dumps(data, ensure_ascii=False)

    with open(steps_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    logger.debug(f"Appended step {step.step_id}: {steps_path}")
    return steps_path


def read_steps(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> List[SessionStep]:
    """Read all step records

    Args:
        session_id: Session ID
        agent_type: Agent type

    Returns:
        List of step records
    """
    session_dir = get_session_dir(session_id, agent_type)
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
) -> Optional[SessionSummary]:
    """Generate session summary

    Args:
        session_id: Session ID
        agent_type: Agent type
        tool_calls: Tool call record list (optional, for statistics)

    Returns:
        Session summary object
    """
    session = read_metadata(session_id, agent_type)
    if not session:
        return None

    steps = read_steps(session_id, agent_type)

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
) -> Optional[Path]:
    """Generate and write session summary

    Args:
        session_id: Session ID
        agent_type: Agent type
        tool_calls: Tool call record list

    Returns:
        summary.json file path
    """
    summary = generate_summary(session_id, agent_type, tool_calls)
    if not summary:
        return None

    session_dir = get_session_dir(session_id, agent_type)
    summary_path = session_dir / "summary.json"

    data = summary.model_dump(mode="json")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"Wrote summary: {summary_path}")
    return summary_path


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


def read_steps_paginated(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    limit: int = 50,
    offset: int = 0,
    from_end: bool = False,
) -> Dict[str, Any]:
    """Read session steps with pagination

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

    all_steps = read_steps(session_id, agent_type)
    total = len(all_steps)

    if from_end:
        # Read from end: offset=0 gets the latest `limit` steps
        # Steps are returned in reverse order (newest first)
        start = max(0, total - offset - limit)
        end = total - offset
        steps = all_steps[start:end]
        steps.reverse()  # Newest first
        return {
            "steps": steps,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": start > 0,
        }
    else:
        # Original logic: read from beginning
        return {
            "steps": all_steps[offset : offset + limit],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
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

    sessions = []

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

    # Sort by last activity time descending (normalize to UTC timezone for comparison)
    from datetime import timezone
    def get_sortable_time(s):
        t = s.last_activity
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
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
