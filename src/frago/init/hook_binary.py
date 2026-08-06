"""
Hook binary deployment.

Detects the current OS/arch, locates the matching precompiled binary
shipped inside the frago package (site-packages/frago/bin/), and copies it
to ~/.frago/bin/. Also syncs hook event registration in settings.json based
on what the binary reports via --supported-events.

The binary lives in frago's own runtime dir (~/.frago/bin/) rather than
~/.claude/hooks/frago/ because frago-core is frago's runtime component, not
a Claude Code plugin. The wheel bundles all four platform binaries, so
upgrading frago-cli upgrades them automatically; deploy just syncs the
right one to the stable path settings.json points at.
"""

import contextlib
import filecmp
import json
import logging
import platform
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from frago.init.app_control import smart_app_control_warning

logger = logging.getLogger(__name__)


def get_platform_key() -> str:
    """Return the platform directory name matching the current OS and architecture.

    Returns:
        One of: linux-x86_64, darwin-arm64, darwin-x86_64, windows-x86_64

    Raises:
        RuntimeError: If the current platform is not supported.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        ("linux", "x86_64"): "linux-x86_64",
        ("linux", "amd64"): "linux-x86_64",
        ("darwin", "arm64"): "darwin-arm64",
        ("darwin", "aarch64"): "darwin-arm64",
        ("darwin", "x86_64"): "darwin-x86_64",
        ("windows", "x86_64"): "windows-x86_64",
        ("windows", "amd64"): "windows-x86_64",
    }

    key = arch_map.get((system, machine))
    if not key:
        raise RuntimeError(f"Unsupported platform: {system}-{machine}")
    return key


def get_binary_name() -> str:
    """Return the binary filename for the current OS."""
    if platform.system().lower() == "windows":
        return "frago-core.exe"
    return "frago-core"


def get_engine_argv() -> list[str]:
    """Return the argv prefix that selects the hook (engine) entry.

    frago-core runs two entries in one binary: the default (no args) is the
    agentic kernel; ``--engine`` selects the hook router that Claude Code /
    opencode invoke per event. Every hook command must carry it, or a hook
    invocation would silently launch the kernel instead.
    """
    return ["--engine"]


def get_bundled_binary_path() -> Path:
    """Return the path to the bundled binary for the current platform.

    Raises:
        FileNotFoundError: If the binary for this platform is not bundled.
    """
    pkg_bin = Path(__file__).resolve().parent.parent / "bin"
    platform_key = get_platform_key()
    binary = pkg_bin / platform_key / get_binary_name()

    if not binary.exists():
        raise FileNotFoundError(
            f"No precompiled binary for {platform_key}. "
            f"Expected at: {binary}"
        )
    return binary


def get_hook_deploy_dir() -> Path:
    """Return ~/.frago/bin/, creating it if needed."""
    deploy_dir = Path.home() / ".frago" / "bin"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    return deploy_dir


def deploy_hook_binary(force: bool = False) -> Path:
    """Copy the platform-appropriate binary to ~/.frago/bin/.

    Also removes the legacy ~/.claude/hooks/frago/ copy so an upgraded
    install never runs a stale binary (the runtime path changed once;
    leftover copies there are dead weight and a drift hazard).

    Args:
        force: Overwrite even if the target already exists and has the same size.

    Returns:
        Path to the deployed binary.

    Raises:
        FileNotFoundError: If no binary is bundled for this platform.
        RuntimeError: If the platform is not supported.
    """
    # Say this before copying anything. A blocked hook binary produces no error
    # of its own — the deploy succeeds, the file is in place, and the routing
    # just never happens. Without this line the log gives no reason to suspect
    # the platform.
    warning = smart_app_control_warning()
    if warning:
        logger.warning("Hook binary may not load:\n%s", warning)

    src = get_bundled_binary_path()
    dst_dir = get_hook_deploy_dir()
    dst = dst_dir / get_binary_name()

    # Clean the legacy copy before the idempotency early-return: the cleanup
    # must happen on every deploy, not only when the binary actually changes.
    # Otherwise a second server start with an already-current binary would
    # skip it and leftover legacy copies would survive.
    cleanup_legacy_hook_copy()

    if dst.exists() and not force and filecmp.cmp(src, dst, shallow=False):
        return dst

    shutil.copy2(src, dst)

    # Ensure executable permission (no-op on Windows)
    if platform.system().lower() != "windows":
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return dst


def get_hook_binary_path() -> str:
    """Return the absolute path string to the deployed hook binary.

    Useful for generating settings.json hook commands.
    """
    deploy_dir = get_hook_deploy_dir()
    return str(deploy_dir / get_binary_name())


def get_legacy_hook_dir() -> Path:
    """Return the historical ~/.claude/hooks/frago/ directory, if present."""
    return Path.home() / ".claude" / "hooks" / "frago"


def cleanup_legacy_hook_copy() -> None:
    """Remove stale binaries left by previous deploy layouts.

    Two generations of leftovers can exist:
    - ~/.claude/hooks/frago/frago-hook (pre-1.2.x runtime location)
    - ~/.frago/bin/frago-hook (pre-renaming runtime copy)

    The current layout is ~/.frago/bin/frago-core. Stale copies are dead
    weight and, worse, a drift hazard: if a settings.json still points at one,
    an upgraded frago would keep running the stale binary. Deleting them
    forces any stale reference to surface loudly rather than silently run an
    old hook.

    The ``.exe`` suffix is part of the name on Windows. Omitting it made this
    function a no-op there, so ``~/.claude/hooks/frago/frago-hook.exe`` survived
    every deploy — and a settings.json still pointing at it kept running the
    pre-rename binary indefinitely, which is exactly the drift this is meant to
    prevent.

    Best-effort: missing copies are normal (fresh install); the
    session-start-book.sh script in ~/.claude/hooks/frago/ is left untouched
    — it is a Claude Code integration layer, not the binary.
    """
    suffix = ".exe" if platform.system().lower() == "windows" else ""
    legacy_name = f"frago-hook{suffix}"
    candidates = [
        get_legacy_hook_dir() / legacy_name,
        get_hook_deploy_dir() / legacy_name,
    ]
    for stale in candidates:
        with contextlib.suppress(OSError):
            if stale.exists():
                stale.unlink()
                logger.info("Removed legacy hook binary: %s", stale)


# ---------------------------------------------------------------------------
# Hook event registration sync
# ---------------------------------------------------------------------------


def query_supported_events(hook_path: str) -> list[dict[str, Any]]:
    """Call frago-core --supported-events and return event descriptors.

    Returns:
        List of dicts like [{"event": "SessionStart", "matcher": ""}, ...]
        Empty list on failure (graceful fallback).
    """
    try:
        result = subprocess.run(
            [hook_path, "--supported-events"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            events = json.loads(result.stdout.strip())
            if isinstance(events, list) and all(
                isinstance(e, dict) and "event" in e and "matcher" in e
                for e in events
            ):
                return events
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to query supported events: %s", e)
    return []


def sync_hook_events(hook_path: str) -> None:
    """Ensure settings.json hook registrations match what frago-core supports.

    Only touches frago entries — other hooks are left untouched.
    Matcher values come from frago-core itself (source of truth).
    """
    from frago.init.configurator import CLAUDE_SETTINGS_PATH, load_claude_settings

    supported = query_supported_events(hook_path)
    if not supported:
        logger.warning("No supported events from frago-core, skipping sync")
        return

    # Claude Code on Windows launches hooks via Git Bash (/usr/bin/bash);
    # backslash paths get eaten as escape sequences. Forward slashes work
    # for both Windows APIs and bash, and are a no-op on POSIX.
    hook_path = hook_path.replace("\\", "/")

    supported_event_names = {desc["event"] for desc in supported}

    settings = load_claude_settings()
    hooks = settings.setdefault("hooks", {})

    # The hook command is "<binary> --engine": the default (no-arg) entry of
    # frago-core is the agentic kernel, and a bare path would launch that
    # instead of routing the event. The engine flag keeps hook invocations
    # on the hook entry no matter what the binary's default becomes.
    command = " ".join([hook_path, *get_engine_argv()])
    frago_entry = {
        "type": "command",
        "command": command,
        "timeout": 10,
    }

    changed = False

    # Ensure supported events are registered with correct matcher AND command
    for desc in supported:
        event = desc["event"]
        matcher = desc["matcher"]
        if not _has_frago_hook_with_command(hooks, event, matcher, command):
            # Stale entry (wrong matcher or wrong command path) → remove + re-add
            _remove_frago_hook(hooks, event)
            _ensure_frago_hook(hooks, event, matcher, frago_entry)
            changed = True

    # Remove frago from events it no longer supports
    for event in list(hooks.keys()):
        if event not in supported_event_names and _remove_frago_hook(hooks, event):
            changed = True
            if not hooks[event]:
                del hooks[event]

    if changed:
        CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLAUDE_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        logger.info("Hook events synced: %s", [d["event"] for d in supported])
    else:
        logger.debug("Hook events already in sync")


def _is_frago_hook(entry: dict[str, Any]) -> bool:
    """Check if a hook entry belongs to frago.

    Matches both the pre-renaming ``frago-hook`` (stale settings.json from an
    older install) and the current ``frago-core`` binary. A stale entry must
    still be recognised so the sync pass can replace it rather than leave a
    second copy of the event running.
    """
    return entry.get("type") == "command" and (
        "frago-core" in entry.get("command", "")
        or "frago-hook" in entry.get("command", "")
    )


def _has_frago_hook_with_command(
    hooks: dict[str, Any], event: str, matcher: str, command: str
) -> bool:
    """Check if an event has a frago entry with the expected matcher AND command."""
    for group in hooks.get(event, []):
        if group.get("matcher", "") != matcher:
            continue
        for hook in group.get("hooks", []):
            if _is_frago_hook(hook) and hook.get("command") == command:
                return True
    return False


def _ensure_frago_hook(
    hooks: dict[str, Any], event: str, matcher: str, entry: dict[str, Any]
) -> None:
    """Add a frago entry to an event with the specified matcher."""
    if event not in hooks:
        hooks[event] = []
    hooks[event].append({"matcher": matcher, "hooks": [entry]})


def _remove_frago_hook(hooks: dict[str, Any], event: str) -> bool:
    """Remove frago entries from an event. Returns True if anything was removed."""
    if event not in hooks:
        return False
    removed = False
    groups = hooks[event]
    for group in groups[:]:
        original_len = len(group.get("hooks", []))
        group["hooks"] = [h for h in group.get("hooks", []) if not _is_frago_hook(h)]
        if len(group["hooks"]) < original_len:
            removed = True
        if not group["hooks"]:
            groups.remove(group)
    return removed
