"""Session backup.

Claude Code deletes old session transcripts. This module keeps a copy of them,
and that is the whole job: every line of ``~/.claude/projects/**/<sid>.jsonl`` is
copied byte for byte into ``~/.frago/sessions/claude/<sid>/raw.jsonl``. Nothing is
parsed into a private shape, nothing is summarised, nothing is dropped — the copy
is only useful if it is what the original was.

The backup file is its own ledger. How far a session got is its size on disk; no
offset or checksum is written down anywhere, so there is nothing that can drift
out of step with the bytes. Each cycle compares the two files and picks one of:

  nothing to do   backup already as long as the source, tail still matches
  append          source grew, and the shared prefix still matches
  full copy       no backup yet, or the source no longer matches what we hold
                  (a rewritten transcript — compaction, or a reused session id)

Source files are located by session id every cycle rather than by a remembered
path: a session resumed from another directory moves to a different Claude Code
project folder, and a remembered path would read as "the source is gone".
"""

import logging
import os
import uuid as uuid_module
from dataclasses import dataclass, field
from pathlib import Path

from frago.session.models import AgentType
from frago.session.storage import get_session_base_dir

logger = logging.getLogger(__name__)

# Claude Code session directory
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Inactivity timeout (used to determine if session has ended)
INACTIVITY_TIMEOUT_MINUTES = 1

# How many trailing bytes of the backup are checked against the source before
# appending. Enough to catch a rewritten transcript, small enough to be free.
_TAIL_CHECK_BYTES = 4096

RAW_FILENAME = "raw.jsonl"


@dataclass
class SyncResult:
    """Synchronization result"""

    synced: int = 0  # Number of newly synced sessions
    updated: int = 0  # Number of updated sessions
    skipped: int = 0  # Number of skipped sessions (already exists with no changes)
    errors: list[str] = field(default_factory=list)  # Error messages


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


def raw_backup_path(session_id: str) -> Path:
    """Where this session's copy lives.

    Always the plain ``~/.frago/sessions/claude/<sid>/`` path: a backup has one
    home, so it can always be found without asking anything else first.
    """
    return get_session_base_dir() / AgentType.CLAUDE.value / session_id / RAW_FILENAME


def _prefix_still_matches(source: Path, backup: Path, backed_up: int) -> bool:
    """Is the source still the file we copied ``backed_up`` bytes of?

    Compares the last stretch of the backup against the same stretch of the
    source. A transcript that was appended to still matches there; one that was
    rewritten does not, and must be copied again from the start.
    """
    window = min(_TAIL_CHECK_BYTES, backed_up)
    start = backed_up - window
    with open(source, "rb") as src, open(backup, "rb") as bak:
        src.seek(start)
        bak.seek(start)
        return src.read(window) == bak.read(window)


def _copy_raw(source: Path, backup: Path, force: bool = False) -> tuple[bool, str]:
    """Bring the backup in line with the source.

    Returns (changed, action) where action is one of ``created`` / ``appended``
    / ``rewritten`` / ``unchanged``.
    """
    source_size = source.stat().st_size
    backed_up = backup.stat().st_size if backup.exists() else 0

    if force or backed_up == 0:
        action = "created" if backed_up == 0 else "rewritten"
    elif backed_up > source_size or not _prefix_still_matches(source, backup, backed_up):
        # The source is shorter than what we hold, or no longer matches it:
        # it was rewritten, so the copy we have is of a file that no longer exists.
        action = "rewritten"
    elif backed_up == source_size:
        return False, "unchanged"
    else:
        action = "appended"

    backup.parent.mkdir(parents=True, exist_ok=True)
    offset = backed_up if action == "appended" else 0
    mode = "ab" if action == "appended" else "wb"
    with open(source, "rb") as src, open(backup, mode) as bak:
        src.seek(offset)
        while chunk := src.read(1 << 20):
            bak.write(chunk)
    return True, action


def sync_session(jsonl_path: Path, force: bool = False) -> str | None:
    """Back up a single session transcript.

    Args:
        jsonl_path: JSONL file path
        force: Copy the whole transcript again even if the backup looks current

    Returns:
        session_id when the backup changed, None when there was nothing to do
    """
    # Skip empty files (e.g., placeholder files created by Claude CLI resume)
    if jsonl_path.stat().st_size == 0:
        logger.debug(f"Skipping empty file: {jsonl_path}")
        return None

    session_id = jsonl_path.stem
    backup = raw_backup_path(session_id)

    changed, action = _copy_raw(jsonl_path, backup, force=force)
    if not changed:
        logger.debug(f"No changes for session: {session_id}")
        return None

    # Sidechain transcripts (agent-*.jsonl) are excluded by is_main_session_file
    # before we get here; nothing else about the content needs inspecting.

    logger.info(f"Backed up session: {session_id} ({action})")
    return session_id


def sync_project_sessions(
    project_path: str,
    force: bool = False,
    mtime_cache: dict[str, float] | None = None,
) -> SyncResult:
    """Back up the Claude sessions belonging to one project

    Args:
        project_path: Project absolute path
        force: Whether to copy transcripts again from the start
        mtime_cache: Optional dict mapping session_id to last-seen mtime (float).
            When provided, sessions whose mtime hasn't changed are skipped before
            any disk read.

    Returns:
        Synchronization result
    """
    claude_dir = CLAUDE_PROJECTS_DIR / encode_project_path(os.path.abspath(project_path))
    if not claude_dir.exists():
        logger.debug(f"Claude session directory does not exist: {claude_dir}")
        return SyncResult()
    return _sync_dir(claude_dir, force, mtime_cache)


def _sync_dir(
    claude_dir: Path,
    force: bool = False,
    mtime_cache: dict[str, float] | None = None,
) -> SyncResult:
    """Back up every main session transcript sitting in one Claude Code folder."""
    result = SyncResult()

    # Scan all JSONL files
    for jsonl_file in claude_dir.glob("*.jsonl"):
        if not is_main_session_file(jsonl_file.name):
            continue

        try:
            session_id = jsonl_file.stem
            current_mtime = jsonl_file.stat().st_mtime

            # Fast path: skip if mtime unchanged since last cycle (no disk read needed)
            if not force and mtime_cache is not None and session_id in mtime_cache and current_mtime <= mtime_cache[session_id]:
                result.skipped += 1
                continue

            # 备份文件在不在，就是"这场以前备过没有"的唯一依据。
            existed = raw_backup_path(session_id).exists()

            synced_id = sync_session(jsonl_file, force)
            if mtime_cache is not None:
                mtime_cache[session_id] = current_mtime
            if synced_id:
                if existed:
                    result.updated += 1
                else:
                    result.synced += 1
            else:
                result.skipped += 1

        except Exception as e:
            error_msg = f"Sync failed {jsonl_file.name}: {e}"
            logger.warning(error_msg)
            result.errors.append(error_msg)

    # Only log if there are actual changes or errors
    if result.synced > 0 or result.updated > 0 or result.errors:
        logger.info(
            f"Sync complete: synced={result.synced}, updated={result.updated}, "
            f"skipped={result.skipped}, errors={len(result.errors)}"
        )
    return result


def sync_all_projects(
    force: bool = False,
    mtime_cache: dict[str, float] | None = None,
) -> SyncResult:
    """Back up Claude sessions across all projects

    Args:
        force: Whether to copy transcripts again from the start
        mtime_cache: Optional shared mtime cache passed through to sync_project_sessions.

    Returns:
        Synchronization result
    """
    result = SyncResult()

    if not CLAUDE_PROJECTS_DIR.exists():
        # When installing Claude Code for the first time, directory not existing is normal
        logger.debug(f"Claude project directory does not exist: {CLAUDE_PROJECTS_DIR}")
        return result

    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        project_result = _sync_dir(project_dir, force, mtime_cache)

        result.synced += project_result.synced
        result.updated += project_result.updated
        result.skipped += project_result.skipped
        result.errors.extend(project_result.errors)

    return result
