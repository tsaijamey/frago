#!/usr/bin/env python3
"""
Frago Session Commands - Session Management Command Group

Provides session data querying, viewing, and management functions:
- session list: List recent sessions
- session show: View session details
- session watch: Monitor sessions in real-time
- session clean: Clean up expired sessions
"""

import json
import sys
from datetime import datetime

import click

from frago.session.formatter import (
    format_duration,
    get_step_icon,
    get_step_label,
)
from frago.session.models import AgentType, SessionStatus
from frago.session.storage import (
    delete_session,
    get_session_data,
    list_sessions,
    read_metadata,
    read_steps,
    read_summary,
)

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup


@click.group("session", cls=AgentFriendlyGroup)
def session_group():
    """
    Session Management Command Group

    View, monitor, and manage Agent execution sessions.
    """
    pass


@session_group.command("self", cls=AgentFriendlyCommand)
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
def self_cmd(json_output: bool):
    """Print THIS session's id — the handle a later session comes back by.

    An agent cannot see its own session id: it lives in the environment that
    started it, not in the prompt. This resolves it, so a handover note can say
    which conversation it came out of.

    \b
    Prints the bare id on stdout (safe to capture), notes on stderr:
      frago session self
      frago todo add "..." --session "$(frago session self)"
      frago session self --json      # id + where it came from + record path

    \b
    Sources, in order: $FRAGO_SESSION_ID, $CLAUDE_CODE_SESSION_ID, then the
    freshest transcript of the current directory. That last one is a guess —
    it is marked as such and never presented as fact.
    """
    import json as json_module

    from frago.session.self_id import resolve_self

    found = resolve_self()
    if found is None:
        from .agent_friendly import BusinessError

        raise BusinessError(
            "cannot resolve this session's id — no $FRAGO_SESSION_ID / "
            "$CLAUDE_CODE_SESSION_ID, and no recent transcript for this directory",
            'export FRAGO_SESSION_ID="<id>"  # declare it, then retry',
            "frago session list --limit 5    # pick the id by hand",
        )

    if json_output:
        click.echo(json_module.dumps(found.to_dict(), ensure_ascii=False, indent=2))
        return

    click.echo(found.session_id)
    if found.note:
        click.echo(f"[!] {found.note}", err=True)


@session_group.command("list", cls=AgentFriendlyCommand)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "opencode", "cursor", "cline", "all"]),
    default="all",
    help="Filter by agent type"
)
@click.option(
    "--status", "-s",
    type=click.Choice(["running", "completed", "error", "all"]),
    default="all",
    help="Filter by session status"
)
@click.option(
    "--limit", "-n",
    type=int,
    default=10,
    help="Limit the number of results"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output in JSON format"
)
def list_cmd(
    agent_type: str,
    status: str,
    limit: int,
    json_output: bool
):
    """
    List recent sessions

    \b
    Examples:
      frago session list
      frago session list --agent-type claude
      frago session list --status running
      frago session list --limit 20 --json
    """
    # Convert parameters
    agent_type_filter = None
    if agent_type != "all":
        agent_type_filter = AgentType(agent_type)

    status_filter = None
    if status != "all":
        status_filter = SessionStatus(status)

    # Query sessions
    sessions = list_sessions(
        agent_type=agent_type_filter,
        limit=limit,
        status=status_filter,
    )

    if json_output:
        # JSON output
        data = [s.model_dump(mode="json") for s in sessions]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # Table output
    if not sessions:
        click.echo("No session records found")
        return

    click.echo(f"{'Session ID':<12} {'Type':<8} {'Status':<10} {'Steps':<6} {'Tools':<6} {'Last Activity':<20}")
    click.echo("-" * 70)

    for session in sessions:
        session_id_short = session.session_id[:8] + "..."
        agent = session.agent_type.value
        status_str = _get_status_display(session.status)
        steps = str(session.step_count)
        tools = str(session.tool_call_count)
        last_activity = session.last_activity.strftime("%Y-%m-%d %H:%M:%S")

        click.echo(f"{session_id_short:<12} {agent:<8} {status_str:<10} {steps:<6} {tools:<6} {last_activity:<20}")


def _get_status_display(status: SessionStatus) -> str:
    """Get status display text"""
    status_map = {
        SessionStatus.RUNNING: "🟢 Running",
        SessionStatus.COMPLETED: "[OK] Completed",
        SessionStatus.ERROR: "[X] Error",
        SessionStatus.CANCELLED: "⚪ Cancelled",
    }
    return status_map.get(status, status.value)


@session_group.command("search", cls=AgentFriendlyCommand)
@click.argument("query")
@click.option(
    "--terms", "-t",
    default=None,
    help="Comma-separated literal terms; skips model-driven keyword expansion",
)
@click.option(
    "--no-expand",
    is_flag=True,
    help="Skip the model entirely and tokenize the query literally (fast, dumber)",
)
@click.option("--days", "-d", type=int, default=None, help="Only search the last N days")
@click.option("--top", "-n", type=int, default=10, help="Max sessions to report")
@click.option("--model", default=None, help="Model for the keyword-expansion turn")
@click.option(
    "--agent-type",
    default=None,
    help="cli-agent to run the expansion turn on (claude / opencode / codex)",
)
@click.option(
    "--expand-timeout",
    type=int,
    default=None,
    help="Seconds allowed for the keyword-expansion turn (default 180)",
)
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
def search_cmd(
    query: str,
    terms: str | None,
    no_expand: bool,
    days: int | None,
    top: int,
    model: str | None,
    agent_type: str | None,
    expand_timeout: int | None,
    json_output: bool,
):
    """Search raw session transcripts by meaning, across claude AND opencode.

    A model first expands your sentence into literal search terms (synonyms,
    Chinese/English variants, likely command names and error strings), then
    ripgrep sweeps the frago session backup at ``~/.frago/sessions``. That
    backup is the corpus on purpose: Claude Code rolls old transcripts out of
    ``~/.claude/projects``, while the backup only ever grows. Sessions rank by
    how many DISTINCT terms they matched, then by hit density, then by recency.

    \b
    ``--days`` reads the timestamps carried inside the records themselves, not
    file mtimes — a backup file's mtime says when it was copied, not when the
    session happened.

    \b
    If the expansion turn fails or times out, the query is tokenized literally
    and the search still runs — the fallback is reported in the output.

    \b
    Examples:
      frago session search "上次把浏览器扩展桥接调通那回"
      frago session search "flaky test in the recipe runner" --days 30
      frago session search "opencode sqlite" --no-expand --top 5
      frago session search "hook rules" --terms "hook-rules,builtin-rules.json"
      frago session search "chrome anti-bot" --json
    """
    from frago.session.search import EXPAND_TIMEOUT_S, search_sessions

    explicit = [t.strip() for t in terms.split(",") if t.strip()] if terms else None

    if not json_output and explicit is None and not no_expand:
        click.echo("正在让模型把这句话摊成关键词（可用 --no-expand 跳过）…", err=True)

    result = search_sessions(
        query,
        terms=explicit,
        expand=not no_expand,
        days=days,
        top=top,
        agent_type=agent_type,
        model=model,
        expand_timeout_s=float(expand_timeout or EXPAND_TIMEOUT_S),
    )

    if json_output:
        click.echo(json.dumps(_search_as_dict(result), ensure_ascii=False, indent=2))
        return

    click.echo(_render_search(result))
    if not result.hits:
        sys.exit(1)


_SOURCE_LABEL = {"agent": "模型扩展", "explicit": "调用方指定", "literal": "原句切词"}


def _search_as_dict(result) -> dict:
    return {
        "query": result.query,
        "terms": result.plan.terms,
        "terms_source": result.plan.source,
        "terms_note": result.plan.note,
        "corpus_root": result.corpus_root,
        "scanned_sessions": result.scanned_sessions,
        "duration_ms": result.duration_ms,
        "warnings": result.warnings,
        "hits": [
            {
                "source": h.source,
                "session_id": h.session_id,
                "title": h.title,
                "cwd": h.cwd,
                "last_activity": datetime.fromtimestamp(h.last_activity).isoformat()
                if h.last_activity
                else None,
                "matched_terms": h.matched_terms,
                "hit_records": h.hit_lines,
                "capped": h.capped,
                "degraded": h.degraded,
                "location": h.location,
                "resume_command": h.resume_command,
                "snippets": [{"term": s.term, "text": s.text} for s in h.snippets],
            }
            for h in result.hits
        ],
    }


def _render_search(result) -> str:
    plan = result.plan
    lines = [
        f"检索：{result.query}",
        f"关键词（{_SOURCE_LABEL.get(plan.source, plan.source)}，{len(plan.terms)} 个）："
        + "、".join(plan.terms),
    ]
    if plan.note:
        lines.append(f"扩展思路：{plan.note}")
    lines.append(
        f"语料：{result.corpus_root}（{result.scanned_sessions} 场会话）；"
        f"耗时 {result.duration_ms / 1000:.1f}s"
    )
    for warning in result.warnings:
        lines.append(f"[!] {warning}")

    lines.append("")
    if not result.hits:
        lines.append("没有命中。换更具体的说法，或用 --terms 直接给字面量再试一次。")
        return "\n".join(lines)

    lines.append(f"{'#':<3} {'来源':<9} {'会话':<38} {'命中词':<8} {'记录':<6} {'最后活动':<12} 标题")
    lines.append("-" * 108)
    for i, hit in enumerate(result.hits, start=1):
        stamp = (
            datetime.fromtimestamp(hit.last_activity).strftime("%m-%d %H:%M")
            if hit.last_activity
            else "-"
        )
        records = f"{hit.hit_lines}+" if hit.capped else str(hit.hit_lines)
        coverage = f"{len(hit.matched_terms)}/{len(plan.terms)}"
        title = (hit.title or "-")[:36]
        lines.append(
            f"{i:<3} {hit.source:<9} {hit.session_id:<38} "
            f"{coverage:<8} {records:<6} {stamp:<12} {title}"
        )

    for i, hit in enumerate(result.hits, start=1):
        lines.append("")
        lines.append(f"[{i}] {hit.resume_command}")
        lines.append(f"    命中词：{'、'.join(hit.matched_terms)}")
        if hit.degraded:
            lines.append("    [!] 只剩早期加工副本，工具返回值等内容不在里面")
        if hit.cwd:
            lines.append(f"    工作目录：{hit.cwd}")
        lines.append(f"    原始记录：{hit.location}")
        for snippet in hit.snippets:
            lines.append(f"    · ({snippet.term}) {snippet.text}")

    return "\n".join(lines)


@session_group.command("show", cls=AgentFriendlyCommand)
@click.argument("session_id")
@click.option(
    "--steps", "-s",
    is_flag=True,
    help="Show step history"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output in JSON format"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "opencode", "cursor", "cline"]),
    default="claude",
    help="Agent type"
)
def show_cmd(
    session_id: str,
    steps: bool,
    json_output: bool,
    agent_type: str
):
    """
    View session details

    Supports full ID or prefix matching.

    \b
    Examples:
      frago session show 48c10a46
      frago session show 48c10a46 --steps
      frago session show 48c10a46 --json
    """
    agent = AgentType(agent_type)

    # Support prefix matching
    session = _find_session_by_prefix(session_id, agent)
    if not session:
        click.echo(f"Session not found: {session_id}", err=True)
        sys.exit(1)

    if json_output:
        # JSON output
        data = get_session_data(session.session_id, agent)
        if data:
            # Convert to serializable format
            output = {
                "metadata": data["metadata"].model_dump(mode="json"),
                "steps": [s.model_dump(mode="json") for s in data["steps"]],
                "summary": data["summary"].model_dump(mode="json") if data["summary"] else None,
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # Details output
    click.echo("=" * 60)
    click.echo(f"Session ID: {session.session_id}")
    click.echo("=" * 60)

    click.echo("\n[i] Basic Information")
    click.echo(f"  Agent type: {session.agent_type.value}")
    click.echo(f"  Project path: {session.project_path}")
    click.echo(f"  Status: {_get_status_display(session.status)}")

    click.echo("\n⏱️ Time Information")
    click.echo(f"  Started at: {session.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if session.ended_at:
        click.echo(f"  Ended at: {session.ended_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"  Last activity: {session.last_activity.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo("\n📊 Statistics")
    click.echo(f"  Total steps: {session.step_count}")
    click.echo(f"  Tool calls: {session.tool_call_count}")

    # Show summary
    summary = read_summary(session.session_id, agent)
    if summary:
        click.echo("\n📈 Session Summary")
        click.echo(f"  Total duration: {format_duration(summary.total_duration_ms)}")
        click.echo(f"  User messages: {summary.user_message_count}")
        click.echo(f"  Assistant messages: {summary.assistant_message_count}")
        click.echo(f"  Tool success: {summary.tool_success_count}")
        click.echo(f"  Tool errors: {summary.tool_error_count}")
        if summary.most_used_tools:
            tools = ", ".join(f"{t.tool_name}({t.count})" for t in summary.most_used_tools[:5])
            click.echo(f"  Most used tools: {tools}")
        if summary.model:
            click.echo(f"  Model used: {summary.model}")

    # Show step history
    if steps:
        step_list = read_steps(session.session_id, agent)
        if step_list:
            click.echo(f"\n📜 Step History ({len(step_list)} items)")
            click.echo("-" * 60)
            for step in step_list:
                icon = get_step_icon(step.type)
                label = get_step_label(step.type)
                ts = step.timestamp.strftime("%H:%M:%S")
                click.echo(f"  [{ts}] {icon} {label}: {step.content_summary}")


def _find_session_by_prefix(prefix: str, agent_type: AgentType):
    """Find session by prefix"""
    # Try exact match first
    session = read_metadata(prefix, agent_type)
    if session:
        return session

    # Try prefix matching
    sessions = list_sessions(agent_type=agent_type, limit=100)
    for s in sessions:
        if s.session_id.startswith(prefix):
            return s

    return None


@session_group.command("watch", cls=AgentFriendlyCommand)
@click.argument("session_id", required=False)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output in JSON format"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "opencode", "cursor", "cline"]),
    default="claude",
    help="Agent type"
)
def watch_cmd(
    session_id: str | None,
    json_output: bool,
    agent_type: str
):
    """
    Monitor sessions in real-time

    If session_id is not specified, monitors the latest active session.

    \b
    Examples:
      frago session watch              # Monitor latest active session
      frago session watch 48c10a46     # Monitor specified session
      frago session watch --json       # Output in JSON format
    """
    from frago.session.monitor import watch_latest_session, watch_session

    agent = AgentType(agent_type)

    if session_id:
        # Monitor specified session
        session = _find_session_by_prefix(session_id, agent)
        if not session:
            click.echo(f"Session not found: {session_id}", err=True)
            sys.exit(1)

        click.echo(f"Monitoring session: {session.session_id[:8]}...")
        watch_session(session.session_id, agent, json_output)
    else:
        # Monitor latest active session
        watch_latest_session(agent, json_output)


@session_group.command("clean", cls=AgentFriendlyCommand)
@click.option(
    "--days", "-d",
    type=int,
    default=30,
    help="Clean sessions older than N days"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "opencode", "cursor", "cline", "all"]),
    default="all",
    help="Filter by agent type"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Only show sessions to be deleted, don't actually delete"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Skip confirmation prompt"
)
def clean_cmd(
    days: int,
    agent_type: str,
    dry_run: bool,
    force: bool
):
    """
    Clean up expired sessions

    Delete session data older than the specified number of days.

    \b
    Examples:
      frago session clean              # Clean sessions older than 30 days
      frago session clean --days 7     # Clean sessions older than 7 days
      frago session clean --dry-run    # Preview sessions to be deleted
    """
    from datetime import timedelta

    agent_filter = None
    if agent_type != "all":
        agent_filter = AgentType(agent_type)

    # Find expired sessions
    cutoff = datetime.now() - timedelta(days=days)
    sessions = list_sessions(agent_type=agent_filter, limit=1000)
    old_sessions = [s for s in sessions if s.last_activity < cutoff]

    if not old_sessions:
        click.echo(f"No sessions found older than {days} days")
        return

    click.echo(f"Found {len(old_sessions)} expired sessions (older than {days} days)")

    if dry_run:
        click.echo("\n[Dry Run] Sessions to be deleted:")
        for s in old_sessions[:20]:  # Show at most 20
            click.echo(f"  - {s.session_id[:8]}... ({s.last_activity.strftime('%Y-%m-%d')})")
        if len(old_sessions) > 20:
            click.echo(f"  ... and {len(old_sessions) - 20} more")
        return

    if not force and not click.confirm(f"Confirm deletion of {len(old_sessions)} sessions?"):
        click.echo("Cancelled")
        return

    # Execute deletion
    cleaned = 0
    for s in old_sessions:
        if delete_session(s.session_id, s.agent_type):
            cleaned += 1

    click.echo(f"[OK] Cleaned {cleaned} sessions")


@session_group.command("delete", cls=AgentFriendlyCommand)
@click.argument("session_id")
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "opencode", "cursor", "cline"]),
    default="claude",
    help="Agent type"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Skip confirmation prompt"
)
def delete_cmd(
    session_id: str,
    agent_type: str,
    force: bool
):
    """
    Delete specified session

    \b
    Examples:
      frago session delete 48c10a46
      frago session delete 48c10a46 --force
    """
    agent = AgentType(agent_type)

    # Find session
    session = _find_session_by_prefix(session_id, agent)
    if not session:
        click.echo(f"Session not found: {session_id}", err=True)
        sys.exit(1)

    if not force:
        click.echo(f"Session ID: {session.session_id}")
        click.echo(f"Project: {session.project_path}")
        click.echo(f"Steps: {session.step_count}")
        if not click.confirm("Confirm deletion of this session?"):
            click.echo("Cancelled")
            return

    if delete_session(session.session_id, agent):
        click.echo(f"[OK] Deleted session: {session.session_id[:8]}...")
    else:
        click.echo("[X] Deletion failed", err=True)
        sys.exit(1)


@session_group.command("sync", cls=AgentFriendlyCommand)
@click.option(
    "--all", "sync_all",
    is_flag=True,
    help="Sync all projects (default: current project only)"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Force re-sync (including existing sessions)"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output in JSON format"
)
def sync_cmd(
    sync_all: bool,
    force: bool,
    json_output: bool
):
    """
    Sync data from agent session records

    Claude sessions come from ~/.claude/projects/, opencode sessions from its
    SQLite session database; both land in ~/.frago/sessions/{agent}/.
    By default, only syncs the project corresponding to the current working directory
    (opencode archives all of its sessions, its records are not project-scoped files).

    \b
    Examples:
      frago session sync           # Sync current project
      frago session sync --all     # Sync all projects
      frago session sync --force   # Force re-sync
    """
    import os

    from frago.session.opencode_sync import sync_opencode_sessions
    from frago.session.sync import sync_all_projects, sync_project_sessions

    if sync_all:
        click.echo("Syncing sessions from all projects...")
        result = sync_all_projects(force=force)
    else:
        project_path = os.getcwd()
        click.echo(f"Syncing project: {project_path}")
        result = sync_project_sessions(project_path, force=force)

    # opencode: archived from its session database. A failure here NEVER masks the
    # claude result — it lands in the same errors list instead.
    try:
        opencode_result = sync_opencode_sessions()
        result.synced += opencode_result.synced
        result.updated += opencode_result.updated
        result.skipped += opencode_result.skipped
        result.errors.extend(opencode_result.errors)
    except Exception as e:  # noqa: BLE001
        result.errors.append(f"opencode: {e}")

    if json_output:
        import json as json_module

        output = {
            "synced": result.synced,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": result.errors,
        }
        click.echo(json_module.dumps(output, ensure_ascii=False, indent=2))
        return

    # Text output
    click.echo("\nSync completed:")
    click.echo(f"  Newly synced: {result.synced}")
    click.echo(f"  Updated: {result.updated}")
    click.echo(f"  Skipped: {result.skipped}")

    if result.errors:
        click.echo(f"\n[!] Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            click.echo(f"  - {err}")
        if len(result.errors) > 5:
            click.echo(f"  ... and {len(result.errors) - 5} more errors")
