"""
Hook binary deployment for Claude Code.

Detects the current OS/arch, locates the matching precompiled binary
shipped inside the frago package, and copies it to ~/.claude/hooks/frago/.
Also syncs hook event registration in settings.json based on what
the binary reports via --supported-events.
"""

import json
import logging
import platform
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

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
        return "frago-hook.exe"
    return "frago-hook"


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
    """Return ~/.claude/hooks/frago/, creating it if needed."""
    deploy_dir = Path.home() / ".claude" / "hooks" / "frago"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    return deploy_dir


def deploy_hook_binary(force: bool = False) -> Path:
    """Copy the platform-appropriate binary to ~/.claude/hooks/frago/.

    Args:
        force: Overwrite even if the target already exists and has the same size.

    Returns:
        Path to the deployed binary.

    Raises:
        FileNotFoundError: If no binary is bundled for this platform.
        RuntimeError: If the platform is not supported.
    """
    src = get_bundled_binary_path()
    dst_dir = get_hook_deploy_dir()
    dst = dst_dir / get_binary_name()

    if dst.exists() and not force and dst.stat().st_size == src.stat().st_size:
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


# ---------------------------------------------------------------------------
# Hook event registration sync
# ---------------------------------------------------------------------------


def query_supported_events(hook_path: str) -> list[dict[str, Any]]:
    """Call frago-hook --supported-events and return event descriptors.

    Returns:
        List of dicts like [{"event": "SessionStart", "matcher": ""}, ...]
        Empty list on failure (graceful fallback).
    """
    try:
        result = subprocess.run(
            [hook_path, "--supported-events"],
            capture_output=True,
            text=True,
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
    """Ensure settings.json hook registrations match what frago-hook supports.

    Only touches frago-hook entries — other hooks are left untouched.
    Matcher values come from frago-hook itself (source of truth).
    """
    from frago.init.configurator import CLAUDE_SETTINGS_PATH, load_claude_settings

    supported = query_supported_events(hook_path)
    if not supported:
        logger.warning("No supported events from frago-hook, skipping sync")
        return

    # Claude Code on Windows launches hooks via Git Bash (/usr/bin/bash);
    # backslash paths get eaten as escape sequences. Forward slashes work
    # for both Windows APIs and bash, and are a no-op on POSIX.
    hook_path = hook_path.replace("\\", "/")

    supported_event_names = {desc["event"] for desc in supported}

    settings = load_claude_settings()
    hooks = settings.setdefault("hooks", {})

    frago_entry = {
        "type": "command",
        "command": hook_path,
        "timeout": 10,
    }

    changed = False

    # Ensure supported events are registered with correct matcher AND command
    for desc in supported:
        event = desc["event"]
        matcher = desc["matcher"]
        if not _has_frago_hook_with_command(hooks, event, matcher, hook_path):
            # Stale entry (wrong matcher or wrong command path) → remove + re-add
            _remove_frago_hook(hooks, event)
            _ensure_frago_hook(hooks, event, matcher, frago_entry)
            changed = True

    # Remove frago-hook from events it no longer supports
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
    """Check if a hook entry belongs to frago-hook."""
    return entry.get("type") == "command" and "frago-hook" in entry.get("command", "")


def _has_frago_hook_with_command(
    hooks: dict[str, Any], event: str, matcher: str, command: str
) -> bool:
    """Check if an event has a frago-hook entry with the expected matcher AND command."""
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
    """Add a frago-hook entry to an event with the specified matcher."""
    if event not in hooks:
        hooks[event] = []
    hooks[event].append({"matcher": matcher, "hooks": [entry]})


def _remove_frago_hook(hooks: dict[str, Any], event: str) -> bool:
    """Remove frago-hook entries from an event. Returns True if anything was removed."""
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
