"""Runtime state management for ~/.frago/runtime.json.

Unlike config.json (user intent), runtime.json stores observations about the
running server process: how it was launched, etc. It is device-local and
never synced.

The primary consumer is the Rust frago-hook binary, which reads
launcher.command to know how to invoke `frago book` without any heuristic
probing. See spec 20260413-launcher-runtime-detection.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

RUNTIME_STATE_PATH = Path.home() / ".frago" / "runtime.json"


class LauncherInfo(BaseModel):
    """How the currently-running frago server was launched.

    command: Full argv prefix to invoke frago from any cwd, e.g.
        ["frago"]
        ["uv", "run", "--project", "/abs/path/to/frago", "frago"]
    mode: Semantic label for debugging; Rust side ignores it.
    detected_at: Detection timestamp (naive local time).
    source: Raw detection signals, for troubleshooting.
    """

    command: list[str] = Field(..., min_length=1)
    mode: Literal["global", "uv_run"]
    detected_at: datetime = Field(default_factory=datetime.now)
    source: dict[str, str | None] = Field(default_factory=dict)


class RuntimeState(BaseModel):
    """~/.frago/runtime.json top-level schema."""

    schema_version: str = "1.0"
    launcher: LauncherInfo | None = None


def load_runtime_state() -> RuntimeState:
    """Load runtime state. Missing or corrupt file → empty state.

    Corrupt files are backed up to runtime.json.bak.<timestamp> before
    being replaced. Never raises.
    """
    if not RUNTIME_STATE_PATH.exists():
        return RuntimeState()
    try:
        data = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
        return RuntimeState(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning("runtime.json corrupt, resetting: %s", e)
        _backup_corrupted()
        return RuntimeState()
    except Exception as e:
        logger.warning("runtime.json unreadable: %s", e)
        return RuntimeState()


def save_runtime_state(state: RuntimeState) -> None:
    """Persist runtime state to disk. Creates parent dir if missing."""
    RUNTIME_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE_PATH.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def update_launcher(launcher: LauncherInfo) -> RuntimeState:
    """Load → replace launcher field → save. Returns the new state.

    Windows backslash paths in `launcher.command` get eaten by Git Bash as
    escape sequences when an agent pastes the injected command (e.g.
    `C:\\Users\\x\\frago.exe` → `C:Usersxfrago.exe` → not found). Both
    Windows APIs and bash accept forward slashes, so normalize at the
    source. frago-hook's format_launcher_for_shell also normalizes as a
    belt-and-suspenders, but fixing here keeps runtime.json itself clean
    for other downstream consumers.
    """
    launcher.command = [arg.replace("\\", "/") for arg in launcher.command]
    state = load_runtime_state()
    state.launcher = launcher
    save_runtime_state(state)
    os.environ["FRAGO_LAUNCHER"] = json.dumps(launcher.command)
    return state


def _backup_corrupted() -> None:
    if not RUNTIME_STATE_PATH.exists():
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = RUNTIME_STATE_PATH.with_suffix(f".json.bak.{ts}")
    with contextlib.suppress(Exception):
        shutil.copy(RUNTIME_STATE_PATH, backup)
