"""frago hook-rules — manage the rules engine's user-editable rule set.

Storage: ``~/.frago/hook-rules.json``. On first write, the file is seeded by
invoking ``frago-hook --dump-builtin-rules`` so the user's copy starts with
the shipped builtin rules. Subsequent writes mutate this file directly.

See spec ``.claude/docs/spec-driven-plan/20260419-hook-rules-engine.md``.
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

logger = logging.getLogger(__name__)

RULES_PATH = Path.home() / ".frago" / "hook-rules.json"
HITS_LOG_PATH = Path.home() / ".frago" / "hook-rules-hits.log"
ARCHIVE_PATH = Path.home() / ".frago" / "hook-rules-archive.json"
SCHEMA_VERSION = 1
DEFAULT_AGENT_TTL_DAYS = 30


# ── helpers ──────────────────────────────────────────────────────────────


def _dump_builtin() -> dict:
    """Invoke ``frago-hook --dump-builtin-rules`` and return the parsed JSON.

    The engine's single source of truth for builtin rules is the Rust binary.
    Python shells out instead of carrying its own copy to avoid drift.
    """
    from frago.init.hook_binary import get_bundled_binary_path

    binary = get_bundled_binary_path()
    result = subprocess.run(
        [str(binary), "--dump-builtin-rules"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _load_user_file() -> dict:
    """Load the user rules file. Returns empty skeleton if absent."""
    if not RULES_PATH.exists():
        return {"version": SCHEMA_VERSION, "rules": []}
    try:
        return json.loads(RULES_PATH.read_text())
    except json.JSONDecodeError as e:
        raise click.ClickException(
            f"{RULES_PATH} is not valid JSON: {e}. Fix or delete to reset."
        )


def _load_merged() -> dict:
    """Return the engine's effective rule set: builtin overlaid with user file.

    Matches the merge semantics the Rust engine applies at load time. Used
    for listing — writes still go to the user file alone.
    """
    merged = _dump_builtin()
    user = _load_user_file()
    user_ids = {r.get("id") for r in user.get("rules", [])}
    merged["rules"] = [r for r in merged.get("rules", []) if r.get("id") not in user_ids]
    merged["rules"].extend(user.get("rules", []))
    return merged


def _save_user_file(data: dict) -> None:
    """Atomically write user rules file."""
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RULES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(RULES_PATH)


def _find_user_index(data: dict, rule_id: str) -> int | None:
    for i, r in enumerate(data.get("rules", [])):
        if r.get("id") == rule_id:
            return i
    return None


def _find_builtin(rule_id: str) -> dict | None:
    for r in _dump_builtin().get("rules", []):
        if r.get("id") == rule_id:
            return r
    return None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── command group ────────────────────────────────────────────────────────


@click.group(name="hook-rules", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.pass_context
def hook_rules_group(ctx):
    """Manage data-driven routing rules for the frago-hook engine."""
    if ctx.invoked_subcommand is not None:
        return
    # Bare invocation → list
    ctx.invoke(hook_rules_list)


@hook_rules_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--source", type=click.Choice(["builtin", "user", "agent"]), default=None)
@click.option("--event", default=None, help="Filter by event name (e.g. PreToolUse)")
@click.option("--show-disabled", is_flag=True, help="Include disabled rules")
def hook_rules_list(source: str | None, event: str | None, show_disabled: bool):
    """List routing rules (merged builtin + user)."""
    data = _load_merged()
    rules = data.get("rules", [])

    filtered = [
        r
        for r in rules
        if (source is None or r.get("source") == source)
        and (event is None or r.get("event") == event)
        and (show_disabled or not r.get("disabled", False))
    ]

    if not filtered:
        click.echo("(no rules match filters)")
        return

    click.echo(
        f"\n  {'ID':<40s} {'SOURCE':<8s} {'EVENT':<17s} {'MATCH':<26s} ACTION"
    )
    click.echo("  " + "─" * 118)
    for r in filtered:
        match = r.get("match", {})
        action = r.get("action", {})
        match_repr = _fmt_match(match)
        action_repr = _fmt_action(action)
        prefix = "✗ " if r.get("disabled") else "  "
        click.echo(
            f"{prefix}{r.get('id', ''):<40s} "
            f"{r.get('source', ''):<8s} "
            f"{r.get('event', ''):<17s} "
            f"{match_repr:<26s} "
            f"{action_repr}"
        )
    click.echo(f"\n({len(filtered)} rules shown)")


def _fmt_match(m: dict) -> str:
    t = m.get("type", "?")
    if "value" in m:
        return f"{t}={m['value'][:18]!r}"
    if "values" in m:
        return f"{t}={m['values']}"
    if "pattern" in m:
        return f"{t}={m['pattern'][:18]!r}"
    if "name" in m:
        return f"{t}={m['name']}"
    return t


def _fmt_action(a: dict) -> str:
    t = a.get("type", "?")
    for k in ("topic", "recipe"):
        if k in a:
            return f"{t}({a[k]})"
    if "command" in a:
        return f"{t}({' '.join(a['command'])[:40]})"
    if "text" in a:
        return f"{t}({a['text'][:30]!r}...)"
    return t


@hook_rules_group.command(name="show", cls=AgentFriendlyCommand)
@click.argument("rule_id")
def hook_rules_show(rule_id: str):
    """Show a single rule's full JSON (merged view)."""
    data = _load_merged()
    for r in data.get("rules", []):
        if r.get("id") == rule_id:
            click.echo(json.dumps(r, indent=2, ensure_ascii=False))
            return
    raise click.ClickException(
        f"No rule with id '{rule_id}'. Run `frago hook-rules list` to see available ids."
    )


@hook_rules_group.command(name="add", cls=AgentFriendlyCommand)
@click.option(
    "--rule",
    "rule_json",
    required=True,
    help="Full rule object as JSON string. See hook-rules.schema.json for shape.",
)
@click.option(
    "--source",
    type=click.Choice(["user", "agent"]),
    default="agent",
    show_default=True,
    help="Defaults to 'agent'; pass --source=user for curated rules (no TTL).",
)
def hook_rules_add(rule_json: str, source: str):
    """Append a new rule to the user rules file.

    Example:

      \b
      frago hook-rules add --source=agent --rule='{
        "id":"agent-video-tutorial",
        "event":"UserPromptSubmit",
        "match":{"type":"prompt_contains","value":"视频教程"},
        "action":{"type":"run_command_and_inject_stdout",
                  "command":["frago-promotion","find","--","--name=bilibili-tutorial-video-methodology"]}
      }'
    """
    try:
        new_rule = json.loads(rule_json)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"--rule is not valid JSON: {e}")

    if not isinstance(new_rule, dict) or "id" not in new_rule:
        raise click.ClickException("--rule must be a JSON object with an 'id' field.")

    new_rule.setdefault("source", source)
    new_rule.setdefault("created_at", _now_iso())
    new_rule.setdefault("hit_count", 0)
    new_rule.setdefault("last_hit_at", None)
    if new_rule["source"] == "agent" and "ttl_days" not in new_rule:
        new_rule["ttl_days"] = DEFAULT_AGENT_TTL_DAYS

    # Conflict check against merged view (user overrides allowed; but conflict
    # against another user rule with same id is not).
    data = _load_user_file()
    if _find_user_index(data, new_rule["id"]) is not None:
        raise click.ClickException(
            f"Rule id '{new_rule['id']}' already exists in user file. "
            f"Use `remove` first or pick another id."
        )
    # Also warn (not error) if id collides with a builtin — that's an override.
    if _find_builtin(new_rule["id"]) is not None:
        click.echo(
            f"Note: '{new_rule['id']}' collides with a builtin rule — your entry will override it."
        )

    data.setdefault("rules", []).append(new_rule)
    _save_user_file(data)
    click.echo(f"Added rule '{new_rule['id']}' (source={new_rule['source']}).")


@hook_rules_group.command(name="remove", cls=AgentFriendlyCommand)
@click.argument("rule_id")
def hook_rules_remove(rule_id: str):
    """Delete a rule from the user file.

    Builtin rules cannot be removed (they live in the binary). To suppress
    one, use ``disable`` instead — that writes an override to the user file.
    """
    data = _load_user_file()
    idx = _find_user_index(data, rule_id)
    if idx is None:
        if _find_builtin(rule_id) is not None:
            raise click.ClickException(
                f"'{rule_id}' is a builtin rule and cannot be removed. "
                f"Use `frago hook-rules disable {rule_id}` to suppress it."
            )
        raise click.ClickException(f"No rule with id '{rule_id}' in user file.")
    removed = data["rules"].pop(idx)
    _save_user_file(data)
    click.echo(f"Removed rule '{rule_id}' (source={removed.get('source', '?')}).")


@hook_rules_group.command(name="disable", cls=AgentFriendlyCommand)
@click.argument("rule_id")
def hook_rules_disable(rule_id: str):
    """Mark a rule as disabled without deleting it."""
    _set_disabled(rule_id, True)
    click.echo(f"Disabled rule '{rule_id}'.")


@hook_rules_group.command(name="enable", cls=AgentFriendlyCommand)
@click.argument("rule_id")
def hook_rules_enable(rule_id: str):
    """Re-enable a previously disabled rule."""
    _set_disabled(rule_id, False)
    click.echo(f"Enabled rule '{rule_id}'.")


def _set_disabled(rule_id: str, disabled: bool) -> None:
    """Flip disabled on an existing user rule, or materialize a disabled
    builtin override into the user file when the id is builtin-only."""
    data = _load_user_file()
    idx = _find_user_index(data, rule_id)
    if idx is not None:
        data["rules"][idx]["disabled"] = disabled
        _save_user_file(data)
        return

    builtin = _find_builtin(rule_id)
    if builtin is None:
        raise click.ClickException(
            f"No rule with id '{rule_id}' (neither user nor builtin)."
        )
    override = dict(builtin)
    override["source"] = "user"
    override["disabled"] = disabled
    data.setdefault("rules", []).append(override)
    _save_user_file(data)


@hook_rules_group.command(name="validate", cls=AgentFriendlyCommand)
def hook_rules_validate():
    """Structural validation of ~/.frago/hook-rules.json.

    Checks version, required fields, known match/action types. Does not run
    the engine or exercise matchers.
    """
    if not RULES_PATH.exists():
        click.echo(f"{RULES_PATH} does not exist (engine falls back to embedded builtin).")
        sys.exit(0)

    try:
        data = json.loads(RULES_PATH.read_text())
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON: {e}")

    errors: list[str] = []

    version = data.get("version")
    if version != SCHEMA_VERSION:
        errors.append(f"unsupported version: {version} (expected {SCHEMA_VERSION})")

    KNOWN_MATCH = {
        "tool_name_eq",
        "bash_contains",
        "bash_contains_all",
        "path_contains",
        "path_contains_all",
        "path_regex",
        "prompt_contains",
        "prompt_regex",
        "env_exists",
        "always",
    }
    KNOWN_ACTION = {
        "inject_book_topic",
        "inject_literal",
        "run_command_and_inject_stdout",
        "spawn_recipe_async",
    }
    KNOWN_EVENT = {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Notification",
        "Stop",
        "SubagentStop",
        "PreCompact",
        "SessionEnd",
    }

    seen_ids: set[str] = set()
    for i, r in enumerate(data.get("rules", [])):
        prefix = f"rules[{i}]"
        for field in ("id", "event", "match", "action"):
            if field not in r:
                errors.append(f"{prefix}: missing '{field}'")
        rid = r.get("id")
        if rid and rid in seen_ids:
            errors.append(f"{prefix}: duplicate id '{rid}'")
        if rid:
            seen_ids.add(rid)
        if r.get("event") not in KNOWN_EVENT:
            errors.append(f"{prefix}: unknown event '{r.get('event')}'")
        m_type = r.get("match", {}).get("type")
        if m_type not in KNOWN_MATCH:
            errors.append(f"{prefix}.match: unknown type '{m_type}'")
        a_type = r.get("action", {}).get("type")
        if a_type not in KNOWN_ACTION:
            errors.append(f"{prefix}.action: unknown type '{a_type}'")

    if errors:
        click.echo(f"Validation failed ({len(errors)} error(s)):", err=True)
        for e in errors:
            click.echo(f"  {e}", err=True)
        sys.exit(1)

    click.echo(f"OK: {len(data.get('rules', []))} rules, schema v{version}.")


# ── stats ────────────────────────────────────────────────────────────────


def _read_hits() -> dict[str, dict]:
    """Aggregate ~/.frago/hook-rules-hits.log into {rule_id: {count, last_ts}}."""
    stats: dict[str, dict] = {}
    if not HITS_LOG_PATH.exists():
        return stats
    for line in HITS_LOG_PATH.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            ts = int(parts[0])
        except ValueError:
            continue
        rule_id = parts[2]
        entry = stats.setdefault(rule_id, {"count": 0, "last_ts": 0})
        entry["count"] += 1
        if ts > entry["last_ts"]:
            entry["last_ts"] = ts
    return stats


@hook_rules_group.command(name="stats", cls=AgentFriendlyCommand)
@click.option("--source", type=click.Choice(["builtin", "user", "agent"]), default=None)
def hook_rules_stats(source: str | None):
    """Show hit counts and last-hit timestamps per rule."""
    merged = _load_merged()
    rules_by_id = {r["id"]: r for r in merged.get("rules", []) if r.get("id")}
    stats = _read_hits()

    rows = []
    for rid, info in rules_by_id.items():
        if source and info.get("source") != source:
            continue
        s = stats.get(rid, {"count": 0, "last_ts": 0})
        rows.append((rid, info.get("source", "?"), s["count"], s["last_ts"]))
    rows.sort(key=lambda r: (-r[2], r[0]))

    click.echo(f"\n  {'ID':<42s} {'SOURCE':<8s} {'HITS':>6s}   LAST HIT")
    click.echo("  " + "─" * 80)
    for rid, src, count, ts in rows:
        last = datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else "—"
        click.echo(f"  {rid:<42s} {src:<8s} {count:>6d}   {last}")

    zero = sum(1 for r in rows if r[2] == 0)
    click.echo(f"\n({len(rows)} rules; {zero} with zero hits)")


# ── prune ────────────────────────────────────────────────────────────────


@hook_rules_group.command(name="prune", cls=AgentFriendlyCommand)
@click.option("--dry-run", is_flag=True, help="Report what would be pruned without moving.")
def hook_rules_prune(dry_run: bool):
    """Archive stale agent rules past their TTL with zero recent hits.

    Moves qualifying rules from ~/.frago/hook-rules.json to
    ~/.frago/hook-rules-archive.json so the decision can be reviewed or
    reversed later.
    """
    data = _load_user_file()
    stats = _read_hits()
    now = datetime.now()

    to_prune: list[dict] = []
    keep: list[dict] = []
    for r in data.get("rules", []):
        if r.get("source") != "agent":
            keep.append(r)
            continue
        ttl = r.get("ttl_days")
        if ttl is None:
            keep.append(r)
            continue

        # Anchor: last hit from log, else created_at, else now (defensive).
        last_ts = stats.get(r["id"], {}).get("last_ts", 0)
        if last_ts:
            last_seen = datetime.fromtimestamp(last_ts)
        else:
            created = r.get("created_at")
            try:
                last_seen = datetime.fromisoformat(created) if created else now
            except (TypeError, ValueError):
                last_seen = now

        age_days = (now - last_seen).days
        if age_days > ttl:
            to_prune.append({**r, "pruned_at": now.isoformat(timespec="seconds")})
        else:
            keep.append(r)

    if not to_prune:
        click.echo("Nothing to prune.")
        return

    click.echo(f"{'DRY-RUN: ' if dry_run else ''}Pruning {len(to_prune)} stale agent rule(s):")
    for r in to_prune:
        click.echo(f"  - {r['id']}")

    if dry_run:
        return

    # Archive (append)
    archive = {"version": SCHEMA_VERSION, "rules": []}
    if ARCHIVE_PATH.exists():
        try:
            archive = json.loads(ARCHIVE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    archive.setdefault("rules", []).extend(to_prune)
    ARCHIVE_PATH.write_text(json.dumps(archive, indent=2, ensure_ascii=False) + "\n")

    # Rewrite user file without pruned entries
    data["rules"] = keep
    _save_user_file(data)
    click.echo(f"Archived to {ARCHIVE_PATH}")
