"""Resume inbox: append-only file queue for PA → sub-agent hot injection.

PA decides to resume a running sub-agent → write a JSON file into the
inbox keyed by claude_session_id. The agent's next PreToolUse hook (in
frago-core, Rust) drains the inbox and injects the prompts via
``additionalContext`` so the agent sees them before its next tool call.

This module is the Python writer half. The Rust reader lives in
``frago-core/src/resume_inbox.rs`` and shares the on-disk schema below.

File layout
-----------
``~/.frago/projects/<run_id>/<claude_session_id>/resume_inbox/<ts>__<uuid>.json``

The reader moves consumed files into a sibling ``.consumed/`` directory
via atomic rename so concurrent hook triggers cannot double-consume the
same injection.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PENDING_DIR_NAME = "resume_inbox"
SCHEMA_VERSION = 1
PROJECTS_DIR = Path.home() / ".frago" / "projects"


@dataclass
class ResumeInjection:
    """One pending PA-resume prompt waiting to be picked up by PreToolUse."""

    injection_id: str
    claude_session_id: str
    task_id: str
    prompt: str
    created_at: str  # naive local time, ISO8601
    pa_thread_id: str | None = None
    schema_version: int = SCHEMA_VERSION


class ResumeInbox:
    """File-backed inbox keyed by claude_session_id."""

    @staticmethod
    def _inbox_dir(run_id: str, claude_session_id: str) -> Path:
        return PROJECTS_DIR / run_id / claude_session_id / PENDING_DIR_NAME

    @classmethod
    def append(
        cls,
        run_id: str,
        claude_session_id: str,
        task_id: str,
        prompt: str,
        pa_thread_id: str | None = None,
    ) -> ResumeInjection:
        """Persist a new pending injection. Returns the record."""
        injection = ResumeInjection(
            injection_id=str(uuid.uuid4()),
            claude_session_id=claude_session_id,
            task_id=task_id,
            prompt=prompt,
            created_at=datetime.now().isoformat(timespec="microseconds"),
            pa_thread_id=pa_thread_id,
        )
        inbox = cls._inbox_dir(run_id, claude_session_id)
        inbox.mkdir(parents=True, exist_ok=True)

        # File name format: "<ts>__<uuid>.json".
        # Use ":"-free timestamp so listing on filesystems that dislike ":"
        # (Windows) sorts cleanly; lexicographic order == arrival order.
        ts_compact = injection.created_at.replace(":", "-")
        target = inbox / f"{ts_compact}__{injection.injection_id}.json"
        tmp = inbox / f".{target.name}.tmp"

        payload = json.dumps(asdict(injection), ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)

        logger.info(
            "ResumeInbox: appended injection %s for csid=%s (run=%s, task=%s)",
            injection.injection_id[:8],
            claude_session_id[:8],
            run_id,
            task_id[:8],
        )
        return injection

    @classmethod
    def list_pending(
        cls, run_id: str, claude_session_id: str,
    ) -> list[ResumeInjection]:
        """Best-effort read; primarily for tests/diagnostics. Does not consume."""
        inbox = cls._inbox_dir(run_id, claude_session_id)
        if not inbox.is_dir():
            return []
        out: list[ResumeInjection] = []
        for f in sorted(inbox.iterdir()):
            if not f.is_file() or not f.name.endswith(".json"):
                continue
            if f.name.startswith("."):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(ResumeInjection(**data))
            except Exception:
                logger.warning("ResumeInbox: corrupt file %s — skipped", f)
        return out
