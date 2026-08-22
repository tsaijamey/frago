"""Collecting what older frago versions left inside ~/.claude/.

frago stopped shipping a file does not mean the file stopped existing. Every
machine that installed frago before the retirement still has it — still
registered, still listed in the slash-command menu, still telling every agent
that starts a session whatever was true the day it was written. That is
information debt frago created, and nothing on the user's machine will collect
it unless frago does.

The sweep runs from the server's startup path (``server/app.py``), which is the
only part of frago that runs on every machine without being asked, and it is the
same place hook registration is already kept in sync. Everything here is
home-directory relative, so Windows, Linux and macOS are swept by the same code;
what differs per platform is only which leftovers a given machine happens to
have.

Retiring something is one entry in the tables below. The tables list exact
names, never globs: a name frago shipped is frago's to remove, and a name the
user invented is not.
"""

import contextlib
import json
import logging
import shutil
import stat
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_claude_dir() -> Path:
    """Return ~/.claude/ — Claude Code's per-user directory on every platform."""
    return Path.home() / ".claude"


# Registered in settings.json and copied into ~/.claude/hooks/frago/.
#
# session-start-book.sh (shipped 2026-03-30 → 2026-04-01) opened every session
# with "先运行 `uv run frago book`". Both halves are wrong today: the builtin
# SessionStart rule already injects `book --brief` unasked, and must-system-frago
# made bare `frago` the only correct form outside the packaging entry. Left in
# place it taught the `uv run frago …` habit before the agent had read a single
# user request. Its very first generation registered the copy inside
# site-packages rather than ~/.claude/, so on those machines the registration has
# been pointing at a file the wheel upgrade deleted back in April — a hook that
# fails on every session start. Matching by filename covers both.
RETIRED_HOOK_SCRIPTS: tuple[str, ...] = ("session-start-book.sh",)

# Copied into ~/.claude/commands/ on every install until 2026-04-06, when
# `frago book` became the sole knowledge channel. They are still in the slash
# menu of every machine installed before that, and what they teach — tool
# priority, execution principles, navigation rules — predates both the book and
# the hook rule engine that replaced them.
RETIRED_SLASH_COMMANDS: tuple[str, ...] = (
    "frago.agent.md",
    "frago.do.md",
    "frago.exec.md",
    "frago.recipe.md",
    "frago.run.md",
    "frago.skill.md",
    "frago.test.md",
)

# The support tree those commands read from (~/.claude/commands/frago/:
# COMMON.md, rules/, guides/, scripts/). frago always treated this directory as
# exclusively its own — the old installer deleted and re-copied the whole tree on
# every run — so removing it now is the same claim it always made.
RETIRED_COMMAND_TREE = "frago"

# Copied into ~/.claude/skills/ until 2026-04-23. Unlike the commands these were
# only written when absent, so a machine can hold a copy from any version in
# between. A directory only counts as one of frago's if it still holds the
# SKILL.md the installer put there.
RETIRED_SKILLS: tuple[str, ...] = (
    "frago-previewable-content",
    "frago-view-content-generate-tips-code",
    "frago-view-content-generate-tips-html",
    "frago-view-content-generate-tips-json",
    "frago-view-content-generate-tips-markdown",
    "frago-view-content-generate-tips-pdf",
    "frago-x-extract-tweet-with-comments",
)


def retire_superseded_install_artifacts() -> list[str]:
    """Remove everything in the tables above from this machine.

    Order matters for the hook script: the registration goes first, the file
    second. A settings.json pointing at a script that is no longer on disk makes
    Claude Code fail the hook on every session start, which is louder than the
    stale advice it replaced. Doing it this way leaves a working machine either
    way if the sweep is interrupted, and the next server start finishes the job.

    Best-effort throughout — a machine with none of this is the normal case for a
    recent install, and neither an unreadable settings.json nor a file frago is
    not allowed to delete is worth failing a server start over.

    Returns:
        Human-readable descriptions of what was actually removed, for the log.
        Empty when there was nothing to collect, which is the steady state.
    """
    removed: list[str] = []
    removed.extend(_unregister_retired_hooks())
    removed.extend(_delete_retired_hook_scripts())
    removed.extend(_delete_retired_slash_commands())
    removed.extend(_delete_retired_skills())
    return removed


def _unregister_retired_hooks() -> list[str]:
    """Drop settings.json entries that invoke a retired script."""
    from frago.init.configurator import CLAUDE_SETTINGS_PATH, load_claude_settings

    settings = load_claude_settings()
    hooks = settings.get("hooks") or {}
    if not _prune_retired_registrations(hooks):
        return []

    try:
        CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLAUDE_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.warning("Could not rewrite %s: %s", CLAUDE_SETTINGS_PATH, e)
        return []
    return [f"unregistered hook: {CLAUDE_SETTINGS_PATH}"]


def _prune_retired_registrations(hooks: dict[str, Any]) -> bool:
    """Remove retired entries from a settings.json ``hooks`` mapping in place.

    Returns True if anything was removed.
    """
    removed = False
    for event in list(hooks.keys()):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        for group in groups[:]:
            entries = group.get("hooks", [])
            kept = [h for h in entries if not _is_retired_hook(h)]
            if len(kept) != len(entries):
                removed = True
                group["hooks"] = kept
            if not group.get("hooks"):
                groups.remove(group)
        # An event left with an empty list is not neutral — it is a puzzle for
        # whoever reads the file next.
        if not groups:
            del hooks[event]
    return removed


def _is_retired_hook(entry: Any) -> bool:
    """Does this hook entry invoke one of the retired scripts?

    Matches on the bare filename. The command is a shell line whose quoting,
    path separators and install prefix all differ per machine — a Windows entry
    reads ``bash "C:\\Users\\me\\.claude\\hooks\\frago\\session-start-book.sh"``
    and the oldest generation points into site-packages — and the filename is the
    one part of it frago chose.
    """
    if not isinstance(entry, dict):
        return False
    command = entry.get("command", "")
    return isinstance(command, str) and any(
        name in command for name in RETIRED_HOOK_SCRIPTS
    )


def _delete_retired_hook_scripts() -> list[str]:
    removed = []
    hooks_dir = get_claude_dir() / "hooks" / "frago"
    for name in RETIRED_HOOK_SCRIPTS:
        removed.extend(_unlink(hooks_dir / name))

    # An empty ~/.claude/hooks/frago/ is a leftover of a layout frago moved away
    # from. rmdir refuses a non-empty directory, so anything else living there
    # keeps it — including a frago-hook binary that has not been swept yet.
    with contextlib.suppress(OSError):
        hooks_dir.rmdir()
    return removed


def _delete_retired_slash_commands() -> list[str]:
    removed = []
    commands_dir = get_claude_dir() / "commands"
    for name in RETIRED_SLASH_COMMANDS:
        removed.extend(_unlink(commands_dir / name))
    removed.extend(_rmtree(commands_dir / RETIRED_COMMAND_TREE))
    # ~/.claude/commands/ itself is shared with the user — never removed, even
    # when frago's departure leaves it empty.
    return removed


def _delete_retired_skills() -> list[str]:
    removed = []
    skills_dir = get_claude_dir() / "skills"
    for name in RETIRED_SKILLS:
        skill = skills_dir / name
        if (skill / "SKILL.md").exists():
            removed.extend(_rmtree(skill))
    return removed


def _unlink(path: Path) -> list[str]:
    """Delete one file, reporting it. Missing is the normal case."""
    try:
        if path.is_file():
            path.unlink()
            logger.info("Retired install artifact: %s", path)
            return [str(path)]
    except PermissionError:
        return _retry_after_clearing_read_only(path, path.unlink)
    except OSError as e:
        logger.warning("Could not remove %s: %s", path, e)
    return []


def _rmtree(path: Path) -> list[str]:
    """Delete one directory frago owns, reporting it."""
    try:
        if path.is_dir():
            shutil.rmtree(path, onexc=_clear_read_only)
            logger.info("Retired install artifact: %s", path)
            return [str(path)]
    except OSError as e:
        logger.warning("Could not remove %s: %s", path, e)
    return []


def _clear_read_only(func: Any, path: Any, exc: BaseException) -> None:
    """rmtree recovery hook: drop the read-only bit and retry once.

    Windows refuses to delete a read-only file, and the old installer copied
    these artifacts with ``copy2`` — mode and all — from wherever the wheel had
    unpacked them. One read-only file inside a retired skill would otherwise
    abort the whole directory and leave the machine half-swept. Harmless on
    POSIX, where the permission that matters belongs to the parent directory.
    """
    if not isinstance(exc, PermissionError):
        raise exc
    with contextlib.suppress(OSError):
        Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
        func(path)


def _retry_after_clearing_read_only(path: Path, remove: Any) -> list[str]:
    """Same recovery for a single file."""
    try:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
        remove()
    except OSError as e:
        logger.warning("Could not remove %s: %s", path, e)
        return []
    logger.info("Retired install artifact: %s", path)
    return [str(path)]
