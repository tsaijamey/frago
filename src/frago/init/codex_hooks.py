"""codex hook registration.

Registers the same frago-core binary that Claude Code runs from
``~/.claude/settings.json`` into codex's own hook system, so a codex session
receives the identical knowledge injections and routing rules.

codex needs no bridge process. Its hook wire protocol is deliberately
Claude-Code-shaped: the event names are the same strings (``SessionStart``,
``UserPromptSubmit``, ``PreToolUse``), the payload arrives as one JSON object
on stdin carrying ``session_id`` / ``cwd`` / ``hook_event_name`` / ``prompt`` /
``tool_name`` / ``tool_input``, and the reply is read back off stdout as
``hookSpecificOutput.additionalContext``. frago-core therefore talks to codex
directly — unlike opencode, which needs ``resources/opencode/frago-hook.js`` to
translate an event model that shares nothing with Claude Code's.

## What routes and what does not

The three events frago-core supports all exist in codex with a compatible
payload, but the rules that match on *what the tool is doing* only partly reach
across, because codex names some tools differently:

- ``SessionStart`` and ``UserPromptSubmit`` carry no tool vocabulary at all, so
  every rule on them fires exactly as it does under Claude Code. That is where
  the bulk of frago's routing lives.
- ``PreToolUse`` rules that read the shell command fire too: codex reports shell
  calls as ``tool_name: "Bash"`` with the command in ``tool_input.command`` — a
  string, verified against codex 0.147 — which is Claude Code's exact shape.
- ``PreToolUse`` rules keyed on ``Edit`` / ``Write``, or on a file path, do
  **not** fire. codex performs file edits through ``apply_patch``: the tool name
  is ``apply_patch`` and there is no ``file_path`` field, so ``tool_name_eq``
  and the path clauses find nothing to match.

Closing that last gap means teaching the routing engine to read
``apply_patch``'s vocabulary, which lives in frago-core (Rust) rather than here.
Until then the gap is real and stated rather than papered over — a rule that
silently stops firing on one harness is worse than one known not to.

Two things about codex are not like Claude Code and are handled here:

- The registration file is ``$CODEX_HOME/hooks.json`` (``~/.codex/hooks.json``),
  a file of its own rather than a section inside the agent's settings. codex
  also accepts inline ``[hooks]`` tables in ``config.toml`` and warns when one
  layer carries both, so frago writes only the JSON form and never touches
  ``config.toml``.
- A command hook does not run until the user has reviewed and trusted its exact
  definition. Deploying the file is therefore only half the install; see
  ``TRUST_HINT``.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HOOKS_FILENAME = "hooks.json"

# How long codex may wait for one frago-core invocation, in seconds. Same
# budget as the Claude Code registration and for the same reason: the rule
# matching answers in milliseconds, but the prompt-time review pass calls a
# model and its slow tail reaches ten seconds. codex's own default is 600s,
# which is far too patient — a hung hook would stall the turn for ten minutes.
HOOK_TIMEOUT_SECONDS = 20

# How much injected context codex forwards to the model before it spills the
# rest to a file and shows the model a preview instead. The default is roughly
# 2500 tokens; frago's session-start injection (the knowledge index plus any
# always-on rules) runs past that, and spilling would turn a knowledge index
# into a path the model has to go read. Raising this costs context window, so
# it stays a bounded number rather than 0 ("send everything"), which the codex
# docs warn can let one hook eat the whole window.
ADDITIONAL_CONTEXT_LIMIT = 8000

# Shown in the codex UI while the hook runs.
STATUS_MESSAGE = "frago"

TRUST_HINT = (
    "codex 不会直接运行新装的钩子：它要求你先过目并信任钩子的确切定义。"
    "下次进 codex 会看到 “Hooks need review”，选 Trust all；"
    "或在会话里敲 /hooks 逐条查看再信任。"
    "frago 自己驱动 codex 时走 --dangerously-bypass-hook-trust，不受这道门影响。"
)


def get_codex_home() -> Path:
    """Return codex's home directory.

    ``CODEX_HOME`` wins when set — codex reads it for every path it owns
    (config, sessions, hooks), so a machine that relocated its codex home must
    get its hooks registered in the relocated tree and not in a ``~/.codex``
    that codex never opens.
    """
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex"


def is_codex_present() -> bool:
    """Report whether codex looks installed on this machine.

    Registration is skipped otherwise: creating a codex home for a user who
    does not run codex would be an unrequested side effect, exactly as it would
    be for opencode.
    """
    return get_codex_home().is_dir() or shutil.which("codex") is not None


def get_hooks_path() -> Path:
    """Return the path of codex's user-layer hook registration file."""
    return get_codex_home() / HOOKS_FILENAME


def _is_frago_hook(entry: Any) -> bool:
    """Is this handler frago's?

    Matches the pre-renaming ``frago-hook`` as well as the current
    ``frago-core``, so an older registration is replaced rather than left
    running alongside the new one.
    """
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    if not isinstance(command, str):
        return False
    return "frago-core" in command or "frago-hook" in command


def _strip_frago_from_event(groups: Any) -> tuple[list, bool]:
    """Drop frago handlers out of one event's matcher groups.

    Returns the surviving groups and whether anything was removed. A group left
    with no handlers is dropped too — codex would read it as an event with an
    empty matcher group, and it carries no meaning once frago's handler is gone.
    """
    if not isinstance(groups, list):
        return [], True
    survivors = []
    removed = False
    for group in groups:
        if not isinstance(group, dict):
            survivors.append(group)
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            survivors.append(group)
            continue
        kept = [h for h in handlers if not _is_frago_hook(h)]
        if len(kept) != len(handlers):
            removed = True
        if not kept:
            continue
        survivors.append({**group, "hooks": kept})
    return survivors, removed


def build_hook_entry(hook_path: str, event: str) -> dict[str, Any]:
    """Build the handler frago registers for one codex event.

    ``additionalContextLimit`` is only set on the events that can actually
    return context to the model. codex reports a configuration warning for the
    events that cannot, and a warning frago prints on every startup is a
    warning people learn to ignore.
    """
    entry: dict[str, Any] = {
        "type": "command",
        "command": hook_path,
        "timeout": HOOK_TIMEOUT_SECONDS,
        "statusMessage": STATUS_MESSAGE,
    }
    if event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
        entry["additionalContextLimit"] = ADDITIONAL_CONTEXT_LIMIT
    return entry


def sync_codex_hook_events(hook_path: str) -> Path | None:
    """Make ``$CODEX_HOME/hooks.json`` match what frago-core supports.

    Only frago's own handlers are touched; a hook someone else registered in
    the same file survives untouched, including inside an event frago also
    registers.

    Args:
        hook_path: Full command frago-core is invoked with, engine flag
            included (e.g. ``/Users/x/.frago/bin/frago-core --engine``).

    Returns:
        The path written, ``None`` when codex is absent or frago-core reported
        no events (in which case nothing is written — an empty event list means
        the query failed, not that frago wants zero hooks).
    """
    if not is_codex_present():
        logger.debug("codex not detected, skipping hook registration")
        return None

    from frago.init.hook_binary import query_supported_events

    supported = query_supported_events(hook_path.split()[0])
    if not supported:
        logger.warning("No supported events from frago-core, skipping codex sync")
        return None

    path = get_hooks_path()
    document: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                document = loaded
        except (OSError, json.JSONDecodeError) as exc:
            # Refuse to overwrite a file frago cannot read. Rewriting it from
            # scratch would silently delete hooks the user wrote by hand, and
            # the only evidence would be that they stopped firing.
            logger.warning("Cannot read %s (%s); leaving it alone", path, exc)
            return None

    raw_hooks = document.get("hooks")
    hooks: dict[str, Any] = dict(raw_hooks) if isinstance(raw_hooks, dict) else {}

    supported_names = {desc["event"] for desc in supported}
    changed = False

    for desc in supported:
        event = desc["event"]
        matcher = desc["matcher"]
        entry = build_hook_entry(hook_path, event)
        groups, removed = _strip_frago_from_event(hooks.get(event, []))
        # Rebuild rather than patch in place: matcher, command and timeout all
        # come from frago, and comparing them field by field is how a changed
        # timeout stops reaching machines that already had the hook.
        group: dict[str, Any] = {"hooks": [entry]}
        if matcher:
            group["matcher"] = matcher
        new_groups = [*groups, group]
        if new_groups != hooks.get(event) or removed:
            changed = True
        hooks[event] = new_groups

    for event in list(hooks):
        if event in supported_names:
            continue
        survivors, removed = _strip_frago_from_event(hooks[event])
        if not removed:
            continue
        changed = True
        if survivors:
            hooks[event] = survivors
        else:
            del hooks[event]

    if not changed:
        logger.debug("codex hook events already in sync")
        return path

    document["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    logger.info(
        "codex hook events synced into %s: %s",
        path,
        [d["event"] for d in supported],
    )
    return path
