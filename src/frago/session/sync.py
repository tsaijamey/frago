"""
Session Synchronization Module

Synchronizes session data from ~/.claude/projects/ to ~/.frago/sessions/claude/
Supports idempotent operations, does not modify source files.
"""

import json
import logging
import os
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    StepType,
)
from frago.session.parser import IncrementalParser, record_to_step
from frago.session.storage import (
    append_step,
    get_session_dir,
    read_metadata,
    write_metadata,
    write_summary,
)

logger = logging.getLogger(__name__)

# Claude Code session directory
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Inactivity timeout (used to determine if session has ended)
INACTIVITY_TIMEOUT_MINUTES = 1


@dataclass
class SyncResult:
    """Synchronization result"""

    synced: int = 0  # Number of newly synced sessions
    updated: int = 0  # Number of updated sessions
    skipped: int = 0  # Number of skipped sessions (already exists with no changes)
    errors: List[str] = field(default_factory=list)  # Error messages


def encode_project_path(project_path: str) -> str:
    """Encode project path as Claude Code directory name

    Args:
        project_path: Absolute project path

    Returns:
        Encoded directory name
    """
    # 1. Normalize path separators (Windows \ -> /)
    normalized = project_path.replace("\\", "/")

    # 2. Handle Windows drive letter (C: -> C-)
    # Claude replaces : with - too, so C:/Users -> C-/Users
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[0] + "-" + normalized[2:]

    # 3. Claude Code uses hyphens to encode paths
    # Replace both / and . with -
    # /home/yammi/.frago -> -home-yammi--frago
    return normalized.replace("/", "-").replace(".", "-")


def decode_project_path(encoded: str) -> str:
    """Decode Claude Code directory name to project path

    Args:
        encoded: Encoded directory name (e.g. C--Users-yammi)

    Returns:
        Absolute project path (e.g. C:/Users/yammi)
    """
    # Detect Windows path: starts with single letter followed by two hyphens
    # C--Users-yammi -> C:/Users/yammi
    if len(encoded) >= 3 and encoded[0].isalpha() and encoded[1:3] == "--":
        # Windows path: C--Users -> C:/Users
        drive = encoded[0]
        rest = encoded[3:].replace("-", "/")
        return f"{drive}:/{rest}"
    else:
        # Unix path: -home-user -> /home/user
        return encoded.replace("-", "/")


def is_main_session_file(filename: str) -> bool:
    """Determine if this is a main session file (not a sidechain)

    Main session file format: {uuid}.jsonl
    Sidechain file format: agent-{short_id}.jsonl

    Args:
        filename: File name

    Returns:
        Whether this is a main session file
    """
    if not filename.endswith(".jsonl"):
        return False

    # Exclude sidechain files
    if filename.startswith("agent-"):
        return False

    # Try to parse as UUID
    name = filename.replace(".jsonl", "")
    try:
        uuid_module.UUID(name)
        return True
    except ValueError:
        return False


def infer_session_status(
    records: List[Dict[str, Any]], last_activity: datetime
) -> SessionStatus:
    """Infer session status from records

    Args:
        records: Raw record list
        last_activity: Last activity time

    Returns:
        Inferred session status
    """
    if not records:
        return SessionStatus.RUNNING

    # Check for termination markers (such as summary type)
    for record in reversed(records[-10:]):  # Only check last few records
        record_type = record.get("type")
        if record_type == "summary":
            return SessionStatus.COMPLETED

    # Check last activity time
    now = datetime.now(timezone.utc)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    delta = now - last_activity
    if delta > timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES):
        # No activity for more than 5 minutes, consider completed
        return SessionStatus.COMPLETED

    return SessionStatus.RUNNING


def parse_session_file(jsonl_path: Path) -> Dict[str, Any]:
    """Parse session JSONL file

    Args:
        jsonl_path: JSONL file path

    Returns:
        Dictionary containing session_id, records, steps, metadata
    """
    result = {
        "session_id": None,
        "records": [],
        "first_timestamp": None,
        "last_timestamp": None,
        "step_count": 0,
        "tool_call_count": 0,
        "is_sidechain": False,
        "first_user_message": None,
    }

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                    result["records"].append(record)

                    # Extract session_id
                    if not result["session_id"]:
                        result["session_id"] = record.get("sessionId")

                    # Check if this is a sidechain
                    if record.get("isSidechain"):
                        result["is_sidechain"] = True

                    # Record timestamp
                    timestamp_str = record.get("timestamp")
                    if timestamp_str:
                        try:
                            ts = datetime.fromisoformat(
                                timestamp_str.replace("Z", "+00:00")
                            )
                            if not result["first_timestamp"]:
                                result["first_timestamp"] = ts
                            result["last_timestamp"] = ts
                        except ValueError:
                            pass

                    # Count tool calls
                    message = record.get("message", {})
                    if isinstance(message, dict):
                        content = message.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "tool_use":
                                        result["tool_call_count"] += 1

                    # Extract first real user message for session name
                    if result["first_user_message"] is None:
                        if (
                            record.get("type") == "user"
                            and not record.get("isMeta")
                        ):
                            msg_content = message.get("content", "") if isinstance(message, dict) else ""
                            # Handle array content (e.g., with images)
                            if isinstance(msg_content, list):
                                for block in msg_content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        msg_content = block.get("text", "")
                                        break
                                else:
                                    msg_content = ""
                            # Skip command messages
                            if isinstance(msg_content, str) and msg_content.strip():
                                if not msg_content.strip().startswith("<"):
                                    result["first_user_message"] = msg_content.strip()

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        logger.warning(f"Failed to parse file {jsonl_path}: {e}")

    return result


def sync_session(
    jsonl_path: Path,
    project_path: str,
    force: bool = False,
) -> Optional[str]:
    """Synchronize a single session file

    Args:
        jsonl_path: JSONL file path
        project_path: Project path
        force: Whether to force re-synchronization

    Returns:
        Synced session_id, None on failure
    """
    # Skip empty files (e.g., placeholder files created by Claude CLI resume)
    if jsonl_path.stat().st_size == 0:
        logger.debug(f"Skipping empty file: {jsonl_path}")
        return None

    # Parse session file
    parsed = parse_session_file(jsonl_path)

    session_id = parsed["session_id"]
    if not session_id:
        logger.debug(f"File missing session_id: {jsonl_path}")
        return None

    # Skip sessions with no valid records
    if not parsed["records"]:
        logger.debug(f"Skipping session with no records: {jsonl_path}")
        return None

    # Skip sidechain sessions
    if parsed["is_sidechain"]:
        logger.debug(f"Skipping sidechain session: {session_id}")
        return None

    # Check if already exists
    existing = read_metadata(session_id, AgentType.CLAUDE)
    if existing and not force:
        # Check if source file has updates (supports resumed conversation scenario)
        file_mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc)
        existing_last_activity = existing.last_activity
        if existing_last_activity.tzinfo is None:
            existing_last_activity = existing_last_activity.replace(tzinfo=timezone.utc)

        # If file modification time is earlier than recorded last activity time, skip
        if file_mtime <= existing_last_activity:
            if existing.status != SessionStatus.RUNNING:
                logger.debug(f"Session already exists and no updates: {session_id}")
                return None

    # Infer status
    last_activity = parsed["last_timestamp"] or datetime.now(timezone.utc)
    status = infer_session_status(parsed["records"], last_activity)

    # Extract session name from first user message (truncate to 100 chars)
    session_name = None
    first_msg = parsed.get("first_user_message")
    if first_msg:
        # Take first line and truncate
        first_line = first_msg.split("\n")[0].strip()
        session_name = first_line[:100] if len(first_line) > 100 else first_line

    # Create or update session metadata
    session = MonitoredSession(
        session_id=session_id,
        agent_type=AgentType.CLAUDE,
        project_path=project_path,
        name=session_name,
        source_file=str(jsonl_path),
        started_at=parsed["first_timestamp"] or datetime.now(timezone.utc),
        ended_at=last_activity if status != SessionStatus.RUNNING else None,
        status=status,
        step_count=0,  # Updated later
        tool_call_count=parsed["tool_call_count"],
        last_activity=last_activity,
    )

    # Get existing step count (for incremental sync)
    existing_step_count = existing.step_count if existing else 0

    # If forcing sync, clear existing steps file
    if force and existing_step_count > 0:
        from frago.session.storage import get_session_dir
        steps_file = get_session_dir(session_id, AgentType.CLAUDE) / "steps.jsonl"
        if steps_file.exists():
            steps_file.unlink()
        existing_step_count = 0

    # Use incremental parser to parse steps
    parser = IncrementalParser(str(jsonl_path))
    records = parser.parse_new_records()

    # Convert to steps (skip already synced)
    step_id = 0
    new_steps = 0
    for record in records:
        step_id += 1
        # Skip already synced steps
        if step_id <= existing_step_count:
            continue
        step, _ = record_to_step(record, step_id)
        if step:
            step.session_id = session_id
            append_step(step, AgentType.CLAUDE)
            new_steps += 1

    session.step_count = step_id

    # Write metadata
    write_metadata(session)

    # If completed, generate summary
    if status == SessionStatus.COMPLETED:
        write_summary(session_id, AgentType.CLAUDE)

    logger.info(f"Synced session: {session_id} (steps={step_id}, status={status.value})")
    return session_id


def sync_project_sessions(
    project_path: str,
    force: bool = False,
) -> SyncResult:
    """Synchronize Claude sessions for a specified project

    Args:
        project_path: Project absolute path
        force: Whether to force re-synchronization

    Returns:
        Synchronization result
    """
    result = SyncResult()

    # Encode project path
    project_path = os.path.abspath(project_path)
    encoded_path = encode_project_path(project_path)
    claude_dir = CLAUDE_PROJECTS_DIR / encoded_path

    if not claude_dir.exists():
        logger.debug(f"Claude session directory does not exist: {claude_dir}")
        return result

    # Scan all JSONL files
    for jsonl_file in claude_dir.glob("*.jsonl"):
        if not is_main_session_file(jsonl_file.name):
            continue

        try:
            # Check if already synced (for statistics only, actual check is done by sync_session)
            session_id = jsonl_file.stem
            existing = read_metadata(session_id, AgentType.CLAUDE)

            # Sync session (sync_session will check file modification time to decide if update is needed)
            synced_id = sync_session(jsonl_file, project_path, force)
            if synced_id:
                if existing:
                    result.updated += 1
                else:
                    result.synced += 1
            else:
                result.skipped += 1

        except Exception as e:
            error_msg = f"Sync failed {jsonl_file.name}: {e}"
            logger.warning(error_msg)
            result.errors.append(error_msg)

    logger.info(
        f"Sync complete: synced={result.synced}, updated={result.updated}, "
        f"skipped={result.skipped}, errors={len(result.errors)}"
    )
    return result


def sync_all_projects(force: bool = False) -> SyncResult:
    """Synchronize Claude sessions for all projects

    Args:
        force: Whether to force re-synchronization

    Returns:
        Synchronization result
    """
    result = SyncResult()

    if not CLAUDE_PROJECTS_DIR.exists():
        # When installing Claude Code for the first time, directory not existing is normal, use debug level
        logger.debug(f"Claude project directory does not exist: {CLAUDE_PROJECTS_DIR}")
        return result

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        # Decode project path (supports Windows and Unix)
        project_path = decode_project_path(project_dir.name)

        # Sync this project
        project_result = sync_project_sessions(project_path, force)

        result.synced += project_result.synced
        result.updated += project_result.updated
        result.skipped += project_result.skipped
        result.errors.extend(project_result.errors)

    return result
