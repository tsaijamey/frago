"""Detect how the current frago server process was launched.

Called at server startup to derive the complete launcher command and persist
it into ~/.frago/runtime.json. The Rust frago-hook binary then reads that
file to invoke `frago book` without any heuristic probing.

See spec 20260413-launcher-runtime-detection.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from frago.init.runtime_state import LauncherInfo

logger = logging.getLogger(__name__)


def detect_launcher() -> LauncherInfo | None:
    """Inspect current process state and derive the launcher command.

    Returns None when we cannot confidently determine how to call frago.
    Callers MUST NOT write runtime.json with a None launcher — Rust hook
    would then see no launcher and stay silent, which is the desired
    failure mode.
    """
    argv0 = sys.argv[0] if sys.argv else ""
    argv0_resolved = _safe_resolve(argv0)
    virtual_env = os.environ.get("VIRTUAL_ENV")
    uv_project = os.environ.get("UV_PROJECT")
    which_frago = shutil.which("frago")
    which_frago_resolved = _safe_resolve(which_frago) if which_frago else None

    source: dict[str, str | None] = {
        "argv0": argv0 or None,
        "virtual_env": virtual_env,
        "which_frago": which_frago,
        "uv_project": uv_project,
    }

    # Branch 1: uv_run mode — user invoked via `uv run frago ...`
    # VIRTUAL_ENV is set and argv[0] lives inside that venv. This is a strong
    # signal that we're in a uv-managed project and the Rust hook should
    # invoke `uv run --project <root> frago` for freshness/isolation.
    if virtual_env and argv0_resolved:
        try:
            venv_path = Path(virtual_env).resolve()
        except Exception:
            venv_path = None
        if venv_path:
            try:
                argv0_resolved.relative_to(venv_path)
                inside_venv = True
            except ValueError:
                inside_venv = False
            if inside_venv:
                project_root = _derive_project_root(venv_path, uv_project, argv0_resolved)
                if project_root:
                    return LauncherInfo(
                        command=["uv", "run", "--project", str(project_root), "frago"],
                        mode="uv_run",
                        source=source,
                    )

    # Branch 2: absolute path from shutil.which("frago")
    # Works for pipx install, uv tool install, systemd daemon (PATH-resolved),
    # or any shebang-based launch — even when the binary lives inside a venv,
    # calling it directly via absolute path is fine because shebang handles
    # Python resolution.
    if which_frago_resolved:
        return LauncherInfo(
            command=[str(which_frago_resolved)],
            mode="global",
            source=source,
        )

    logger.warning(
        "Cannot determine frago launcher; argv0=%s venv=%s which_frago=%s",
        argv0,
        virtual_env,
        which_frago,
    )
    return None


def _safe_resolve(path: str | None) -> Path | None:
    if not path:
        return None
    try:
        return Path(path).resolve()
    except Exception:
        return None


def _derive_project_root(
    venv_path: Path,
    uv_project: str | None,
    argv0_resolved: Path,
) -> Path | None:
    """Derive the project root for `uv run --project <root>`.

    Preference order:
      1. UV_PROJECT env var (uv 0.5+ sets this)
      2. VIRTUAL_ENV parent (standard <project>/.venv layout) with pyproject.toml
      3. Walk up from argv[0] to find the nearest pyproject.toml
      4. Last resort: VIRTUAL_ENV parent even without pyproject.toml (log warning)
    """
    if uv_project:
        try:
            p = Path(uv_project).resolve()
        except Exception:
            p = None
        if p and (p / "pyproject.toml").exists():
            return p

    candidate = venv_path.parent
    if (candidate / "pyproject.toml").exists():
        return candidate

    for ancestor in argv0_resolved.parents:
        if (ancestor / "pyproject.toml").exists():
            return ancestor

    logger.warning(
        "Could not find pyproject.toml; falling back to VIRTUAL_ENV parent %s",
        candidate,
    )
    return candidate
