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
from typing import Any

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionSource,
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

#: 会话目录里那份原文副本的文件名。同步程序（``session/sync.py``、
#: ``opencode_sync.py``、``codex_sync.py``）把各家 CLI 自己的转录逐字节镜像到这里，
#: 覆盖的是「你自己跑的会话」；而 ``metadata.json`` 只有 frago 亲自监控过的会话才有。
#: 所以「这场会话存不存在」要以目录里有没有原文副本为准，不是以有没有 metadata 为准。
RAW_FILENAME = "raw.jsonl"

#: 一条 ``status=running`` 的元数据，多久没动静就不再当作还在跑。
#: 取一天，而不是像网页侧 ``session_index.derive_status`` 那样取 90 秒：worker 一轮
#: 任务不设时间上限，跑几小时是常态，判据收紧了会把真在跑的会话报成已结束——那个方向
#: 的错比漏报更难发现。
STALE_RUNNING_SECONDS = 24 * 60 * 60


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
# 目录级会话判定
# ============================================================


def _raw_jsonl_path(session_dir: Path) -> Path | None:
    """目录里的原文副本。没有、或是空文件，都返回 None。"""
    path = session_dir / RAW_FILENAME
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
    except OSError:
        return None
    return None


def _session_mtime(session_dir: Path) -> float | None:
    """这场会话「最后动过」的时刻：metadata.json 与 raw.jsonl 里新的那个。"""
    newest: float | None = None
    for name in ("metadata.json", RAW_FILENAME):
        try:
            mtime = (session_dir / name).stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def _live_status(
    status: SessionStatus, last_activity: datetime, now: datetime | None = None
) -> SessionStatus:
    """把烂在 ``running`` 上的状态按最后活动时刻归位。

    监控进程没走到收尾就退出了（网页那几千条就是这么来的），metadata 里的 status 便
    永远停在 ``running``。写侧已经收不了尾，只能在读的时候判：``last_activity`` 超过
    :data:`STALE_RUNNING_SECONDS` 的，按已结束读。
    """
    if status != SessionStatus.RUNNING:
        return status
    current = now if now is not None else datetime.now()
    activity = last_activity
    # 两侧时区未必一致（老数据不带时区），对齐后再减，免得整体偏掉几个时区。
    if activity.tzinfo is not None and current.tzinfo is None:
        current = current.astimezone(activity.tzinfo)
    elif activity.tzinfo is None and current.tzinfo is not None:
        activity = activity.replace(tzinfo=current.tzinfo)

    try:
        idle = (current - activity).total_seconds()
    except (OverflowError, OSError):
        return SessionStatus.RUNNING

    if idle <= STALE_RUNNING_SECONDS:
        return SessionStatus.RUNNING
    return SessionStatus.COMPLETED


def _derive_session_from_raw(
    session_dir: Path,
    agent_type: AgentType,
    raw_path: Path,
    now: datetime | None = None,
) -> MonitoredSession | None:
    """目录里只有原文副本、没有 ``metadata.json`` 时，就地派生一份最小元数据。

    这种目录是同步进来的「你自己跑的会话」——CLI 写了转录、镜像落在盘上，而 frago 的
    监控没参与过，所以没有 metadata。它在磁盘上明明存在，清单里不该缺席。
    """
    try:
        stamp = datetime.fromtimestamp(raw_path.stat().st_mtime)
    except OSError:
        return None
    return MonitoredSession(
        session_id=session_dir.name,
        agent_type=agent_type,
        # 原文副本里读不出工作目录，也不值得为它把整份转录解析一遍。
        project_path="",
        name=None,
        source_file=str(raw_path),
        started_at=stamp,
        last_activity=stamp,
        status=_live_status(SessionStatus.RUNNING, stamp, now),
        step_count=0,
        tool_call_count=0,
        source=SessionSource.UNKNOWN,
    )


def _load_session_from_dir(
    session_dir: Path, now: datetime | None = None
) -> MonitoredSession | None:
    """一个会话目录 → 一条 ``MonitoredSession``。metadata 优先，没有就从原文副本派生。

    两个都没有（空目录）返回 None。
    """
    metadata_path = session_dir / "metadata.json"
    if metadata_path.exists():
        try:
            with open(metadata_path, encoding="utf-8") as f:
                data = json.load(f)
            return MonitoredSession.model_validate(data)
        except Exception as e:
            # metadata 坏了，但原文副本可能还在——那就退到派生，别因此把这场会话
            # 从清单里抹掉。
            logger.warning(f"Failed to read session {session_dir.name}: {e}")

    raw_path = _raw_jsonl_path(session_dir)
    if raw_path is None:
        return None
    try:
        agent_type = AgentType(session_dir.parent.name)
    except ValueError:
        # 认不出是哪一家，派生的卡片连 agent_type 都填不出来，不猜。
        return None
    return _derive_session_from_raw(session_dir, agent_type, raw_path, now)


def is_managed_session(session_id: str, agent_type: AgentType) -> bool:
    """这场会话是不是 frago 自己管过（目录里有 metadata.json）。

    清理只对这类生效。读取侧的放宽（只认原文副本也算一场会话）不能让
    ``frago session clean`` 反过来去删同步进来的原文镜像。
    """
    return (get_session_dir(session_id, agent_type) / "metadata.json").exists()


# ============================================================
# Session Directory Management
# ============================================================


def get_session_dir(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    domain: str | None = None,
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
    domain: str | None = None,
) -> Path:
    """Create session storage directory."""
    session_dir = get_session_dir(session_id, agent_type, domain)
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created session directory: {session_dir}")
    return session_dir


def _scan_domain_session_dir(session_id: str) -> Path | None:
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
    domain: str | None = None,
) -> MonitoredSession | None:
    """Read session metadata.

    Resolution order:
    1. If ``domain`` is provided -> read directly from the domain path.
    2. Otherwise scan ``~/.frago/projects/*/{session_id}/metadata.json``
       (Phase 1 new layout).
    3. Fall back to the legacy ``~/.frago/sessions/{agent_type}/{session_id}/``
       path; 那个目录里只有 ``raw.jsonl`` 时，就地派生一份最小元数据。

    **状态按盘上原样返回，不做「还活着吗」的归位。**问那个问题的是清单那几条路
    （:func:`list_sessions` / :func:`find_session_by_prefix`）；这里返回的对象会被写
    路径拿去判断「这场会话存不存在」，把一场久未活动、正被续接的会话读成已结束，
    会被原样写回盘上。
    """
    metadata_path: Path | None = None

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
            legacy_dir = get_session_base_dir() / agent_type.value / session_id
            legacy_path = legacy_dir / "metadata.json"
            if legacy_path.exists():
                metadata_path = legacy_path
            else:
                # 只有原文副本的会话（同步进来、frago 没监控过）也要能打开。
                raw_path = _raw_jsonl_path(legacy_dir)
                if raw_path is not None:
                    return _derive_session_from_raw(legacy_dir, agent_type, raw_path)

    if metadata_path is None or not metadata_path.exists():
        return None

    try:
        with open(metadata_path, encoding="utf-8") as f:
            data = json.load(f)
        return MonitoredSession.model_validate(data)
    except Exception as e:
        logger.warning(f"Failed to read metadata: {e}")
        return None


def update_metadata(
    session_id: str,
    agent_type: AgentType = AgentType.CLAUDE,
    **updates: Any,
) -> MonitoredSession | None:
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
    domain: str | None = None,
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
    domain: str | None = None,
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
    domain: str | None = None,
) -> list[SessionStep]:
    """Read all step records."""
    session_dir = _resolve_existing_or_legacy_dir(session_id, agent_type, domain)
    steps_path = session_dir / "steps.jsonl"

    if not steps_path.exists():
        return []

    steps = []
    try:
        with open(steps_path, encoding="utf-8") as f:
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
    tool_calls: list[ToolCallRecord] | None = None,
    domain: str | None = None,
) -> SessionSummary | None:
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

    # Calculate duration (ensure non-negative, as timestamps in file may not be strictly ordered).
    # Normalize tz first: file timestamps can be a mix of naive and aware, and
    # subtracting across the two raises "can't subtract offset-naive and
    # offset-aware datetimes" — surfaced as the dashboard's recurring
    # "Failed to compute recent tasks" error every poll.
    def _naive(dt: datetime) -> datetime:
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    if session.started_at and session.ended_at:
        delta = _naive(session.ended_at) - _naive(session.started_at)
        total_duration_ms = max(0, int(delta.total_seconds() * 1000))
    elif session.started_at and session.last_activity:
        delta = _naive(session.last_activity) - _naive(session.started_at)
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
    tool_calls: list[ToolCallRecord] | None = None,
    domain: str | None = None,
) -> Path | None:
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
    summary: SessionSummary | None = None,
    domain: str | None = None,
) -> Path | None:
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
) -> SessionSummary | None:
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
        with open(summary_path, encoding="utf-8") as f:
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
        with open(file_path, encoding="utf-8") as f:
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
) -> dict[str, Any]:
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

    steps: list[SessionStep] = []
    try:
        with open(steps_path, encoding="utf-8") as f:
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
    agent_type: AgentType | None = None,
    status: SessionStatus | None = None,
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

    now = datetime.now()
    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue

        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue

            # 目录里有内容就算一场会话：metadata.json 或原文副本，二者有其一。
            if not (session_dir / "metadata.json").exists() and (
                _raw_jsonl_path(session_dir) is None
            ):
                continue

            if not status:
                count += 1
                continue

            session = _load_session_from_dir(session_dir, now)
            if session is None:
                continue
            # 状态判据必须与 list_sessions 同一套，否则同一个问题两个答案。
            session_status = _live_status(session.status, session.last_activity, now)
            if session_status != status:
                continue

            count += 1

    return count


def list_sessions(
    agent_type: AgentType | None = None,
    limit: int = 20,
    status: SessionStatus | None = None,
) -> list[MonitoredSession]:
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

    # Phase 1: Collect (session_dir, mtime) pairs. 目录里有内容就算一场会话——原文副本
    # （同步进来的、frago 没监控过的会话）或 metadata 二者有其一即可。mtime 取两份文件
    # 里新的那个，粗筛时才不会漏掉刚写过原文的会话。
    candidates: list[tuple[float, Path]] = []
    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue

        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue

            if not (session_dir / "metadata.json").exists() and (
                _raw_jsonl_path(session_dir) is None
            ):
                continue

            mtime = _session_mtime(session_dir)
            if mtime is None:
                continue
            candidates.append((mtime, session_dir))

    # Phase 2: Sort by mtime descending and only load the top N.
    # With 1000+ sessions, this avoids reading all metadata.json files.
    # Read more than `limit` to compensate for status filtering losses.
    candidates.sort(key=lambda x: x[0], reverse=True)
    read_budget = limit * 5  # read at most 5x limit to find enough matches

    now = datetime.now()
    sessions = []
    for _mtime, session_dir in candidates[:read_budget]:
        session = _load_session_from_dir(session_dir, now)
        if session is None:
            continue

        # 烂在 running 上的状态按最后活动时刻归位，再过滤。
        session.status = _live_status(session.status, session.last_activity, now)

        # Status filtering
        if status and session.status != status:
            continue

        sessions.append(session)

    # Sort by actual last_activity (more accurate than mtime)
    def get_sortable_time(s):
        t = s.last_activity
        if t.tzinfo is not None:
            t = t.replace(tzinfo=None)
        return t
    sessions.sort(key=get_sortable_time, reverse=True)

    return sessions[:limit]


def find_session_by_prefix(
    prefix: str, agent_type: AgentType = AgentType.CLAUDE
) -> MonitoredSession | None:
    """按会话 id 前缀找一场会话。

    先当完整 id 直接开；开不到就按目录名前缀扫那一家的目录。**不走
    :func:`list_sessions` 再筛**——那条路只加载最近的一批，一场很久没动过的会话
    明明在盘上，却会因为没有排进窗口而报「找不到」。
    """
    now = datetime.now()
    session = read_metadata(prefix, agent_type)
    if session is not None:
        session.status = _live_status(session.status, session.last_activity, now)
        return session

    if not prefix:
        return None

    agent_dir = get_session_base_dir() / agent_type.value
    if not agent_dir.is_dir():
        return None

    for session_dir in sorted(agent_dir.iterdir()):
        if not session_dir.is_dir() or not session_dir.name.startswith(prefix):
            continue
        session = _load_session_from_dir(session_dir, now)
        if session is None:
            continue
        session.status = _live_status(session.status, session.last_activity, now)
        return session

    return None


def get_session_data(
    session_id: str, agent_type: AgentType = AgentType.CLAUDE
) -> dict[str, Any] | None:
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
    agent_type: AgentType | None = None,
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
        # 只清 frago 自己管过的会话。读取侧的放宽（只有原文副本也算一场会话）不能反过来
        # 让清理去删那些同步进来的镜像——它们目录里没有 metadata，删了就只剩 CLI 自己
        # 那一份了。
        if not is_managed_session(session.session_id, session.agent_type):
            continue
        if session.last_activity < cutoff and delete_session(
            session.session_id, session.agent_type
        ):
            cleaned += 1

    logger.info(f"Cleaned {cleaned} expired sessions")
    return cleaned
