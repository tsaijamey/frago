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
from typing import Optional

import click

from frago.session.formatter import (
    TerminalFormatter,
    format_duration,
    format_timestamp,
    get_step_icon,
    get_step_label,
    Icons,
)
from frago.session.models import AgentType, SessionStatus, StepType
from frago.session.storage import (
    clean_old_sessions,
    delete_session,
    get_session_data,
    list_sessions,
    read_metadata,
    read_steps,
    read_summary,
)
from .agent_friendly import AgentFriendlyGroup


@click.group("session", cls=AgentFriendlyGroup)
def session_group():
    """
    Session Management Command Group

    View, monitor, and manage Agent execution sessions.
    """
    pass


@session_group.command("list")
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline", "all"]),
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


@session_group.command("show")
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
    type=click.Choice(["claude", "cursor", "cline"]),
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

    click.echo(f"\n📋 Basic Information")
    click.echo(f"  Agent type: {session.agent_type.value}")
    click.echo(f"  Project path: {session.project_path}")
    click.echo(f"  Status: {_get_status_display(session.status)}")

    click.echo(f"\n⏱️ Time Information")
    click.echo(f"  Started at: {session.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if session.ended_at:
        click.echo(f"  Ended at: {session.ended_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"  Last activity: {session.last_activity.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo(f"\n📊 Statistics")
    click.echo(f"  Total steps: {session.step_count}")
    click.echo(f"  Tool calls: {session.tool_call_count}")

    # Show summary
    summary = read_summary(session.session_id, agent)
    if summary:
        click.echo(f"\n📈 Session Summary")
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


@session_group.command("watch")
@click.argument("session_id", required=False)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output in JSON format"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline"]),
    default="claude",
    help="Agent type"
)
def watch_cmd(
    session_id: Optional[str],
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


@session_group.command("clean")
@click.option(
    "--days", "-d",
    type=int,
    default=30,
    help="Clean sessions older than N days"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline", "all"]),
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

    if not force:
        if not click.confirm(f"Confirm deletion of {len(old_sessions)} sessions?"):
            click.echo("Cancelled")
            return

    # Execute deletion
    cleaned = 0
    for s in old_sessions:
        if delete_session(s.session_id, s.agent_type):
            cleaned += 1

    click.echo(f"[OK] Cleaned {cleaned} sessions")


@session_group.command("delete")
@click.argument("session_id")
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline"]),
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


@session_group.command("sync")
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
    Sync data from Claude session files

    Syncs session files from ~/.claude/projects/ to ~/.frago/sessions/claude/.
    By default, only syncs the project corresponding to the current working directory.

    \b
    Examples:
      frago session sync           # Sync current project
      frago session sync --all     # Sync all projects
      frago session sync --force   # Force re-sync
    """
    import os

    from frago.session.sync import sync_all_projects, sync_project_sessions

    if sync_all:
        click.echo("Syncing sessions from all projects...")
        result = sync_all_projects(force=force)
    else:
        project_path = os.getcwd()
        click.echo(f"Syncing project: {project_path}")
        result = sync_project_sessions(project_path, force=force)

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
    click.echo(f"\nSync completed:")
    click.echo(f"  Newly synced: {result.synced}")
    click.echo(f"  Updated: {result.updated}")
    click.echo(f"  Skipped: {result.skipped}")

    if result.errors:
        click.echo(f"\n[!] Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            click.echo(f"  - {err}")
        if len(result.errors) > 5:
            click.echo(f"  ... and {len(result.errors) - 5} more errors")
