"""Run command system CLI subcommand group

Provides run instance management, logging, screenshot and other commands
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from ..run.context import ContextManager
from ..run.discovery import RunDiscovery
from ..run.domain_dict import lookup_domain
from ..run.exceptions import (
    ContextAlreadySetError,
    ContextNotSetError,
    RunException,
    RunNotFoundError,
)
from ..run.insights import (
    VALID_TYPES as DOMAIN_INSIGHT_TYPES,
)
from ..run.insights import (
    list_insights as list_domain_insights,
)
from ..run.insights import (
    query_insights as query_domain_insights,
)
from ..run.insights import (
    search_insights_across_domains,
)
from ..run.logger import RunLogger
from ..run.manager import RunManager
from ..run.models import (
    ActionType,
    ExecutionMethod,
    LogStatus,
    RunStatus,
)
from ..run.utils import normalize_domain_name
from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

# Use user directory consistently
FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"


def get_manager() -> RunManager:
    """Get RunManager instance"""
    return RunManager(PROJECTS_DIR)


def get_context_manager() -> ContextManager:
    """Get ContextManager instance"""
    return ContextManager(FRAGO_HOME, PROJECTS_DIR)


def format_timestamp(dt: datetime) -> str:
    """Format timestamp to ISO 8601 format (with Z suffix)"""
    return dt.isoformat()


def output_json(data: dict[str, Any]) -> None:
    """Output data in JSON format"""
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def get_extra_metadata(instance: Any) -> dict[str, Any]:
    """Get extra metadata fields (excluding core fields)"""
    core_fields = {"run_id", "theme_description", "created_at", "last_accessed", "status"}

    # Get all fields of the instance
    instance_dict = instance.model_dump()

    # Filter out extra fields
    extra_metadata = {}
    for key, value in instance_dict.items():
        if key not in core_fields:
            extra_metadata[key] = value

    return extra_metadata


def format_extra_metadata(extra_metadata: dict[str, Any], indent: str = "  ") -> str:
    """Format extra metadata into a readable string"""
    if not extra_metadata:
        return ""

    lines = ["\nExtra Metadata:"]
    for key, value in sorted(extra_metadata.items()):
        # Use type name check to avoid Pydantic special type issues
        type_name = type(value).__name__
        if type_name == "dict" or isinstance(value, dict):
            lines.append(f"{indent}- {key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"{indent}  {sub_key}: {json.dumps(sub_value, ensure_ascii=False)}")
        elif type_name == "list" or hasattr(value, "__iter__") and not isinstance(value, (str, dict)):
            lines.append(f"{indent}- {key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{indent}- {key}: {value}")

    return "\n".join(lines)


def handle_error(e: Exception, exit_code: int = 1) -> None:
    """Unified error handling"""
    click.echo(f"Error: {e}", err=True)
    sys.exit(exit_code)


@click.group(name="run", cls=AgentFriendlyGroup)
def run_group():
    """Run command system - Manage AI-driven task execution

    \b
    Core concepts:
    - Run instance: Theme-based information center that persistently stores task execution history
    - Context: Currently active run instance (set via set-context)
    - Logs: Structured execution records in JSONL format

    \b
    Typical workflow:
    1. Create run: frago run init "task description"
    2. Set context: frago run set-context <run_id>
    3. Log entry: frago run log --step "..." --status "success" ...
    4. Check progress: frago run info <run_id>
    5. Archive: frago run archive <run_id>
    """
    pass


@run_group.command(cls=AgentFriendlyCommand)
@click.argument("description")
@click.option(
    "--run-id",
    help="Custom run ID / domain name (auto-derived from description by default)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Resolve candidate domain without creating any directory",
)
def init(description: str, run_id: str | None, dry_run: bool):
    """Initialize / ensure a domain (Phase 2: dictionary-aware ensure_domain)

    \b
    Phase 2 simplification: domain is derived from --run-id or the description
    (slugified). The def-dictionary lookup lands in Phase 3.

    \b
    Examples:
        frago run init "twitter"
        frago run init "twitter find X" --dry-run
        frago run init "Test task" --run-id custom-id
    """
    try:
        manager = get_manager()
        # Phase 3: when no explicit run_id, run the def domain_dict lookup
        # so dry-run preview matches what create_run would actually produce.
        if run_id:
            candidate = normalize_domain_name(run_id)
            dict_hit = None
        else:
            dict_hit = manager.resolve_domain_from_description(description)
            candidate = normalize_domain_name(dict_hit or description)
        existing = (PROJECTS_DIR / candidate).exists() if candidate else False

        if dry_run:
            output_json({
                "domain": candidate,
                "status": "existing" if existing else "new",
                "path": str(PROJECTS_DIR / candidate),
                "dict_hit": dict_hit,
                "dry_run": True,
            })
            return

        instance = manager.create_run(description, run_id)
        output_json({
            "run_id": instance.run_id,
            "domain": instance.domain or instance.run_id,
            "status": "existing" if existing else "new",
            "created_at": format_timestamp(instance.created_at),
            "path": str(PROJECTS_DIR / instance.run_id),
        })
    except RunException as e:
        handle_error(e)


@run_group.command(cls=AgentFriendlyCommand)
@click.argument("run_id")
def set_context(run_id: str):
    """Set the current working run

    \b
    Note: The system allows only one active run context. To switch, first release with the release command.

    \b
    Examples:
        frago run set-context find-job-on-upwork
    """
    try:
        manager = get_manager()
        instance = manager.find_run(run_id)

        context_mgr = get_context_manager()
        context = context_mgr.set_current_run(run_id, instance.theme_description)

        output_json({
            "run_id": context.run_id,
            "theme_description": context.theme_description,
            "set_at": format_timestamp(context.last_accessed),
        })
    except ContextAlreadySetError as e:
        handle_error(e, exit_code=2)
    except RunException as e:
        handle_error(e)


@run_group.command(cls=AgentFriendlyCommand)
def release():
    """Release the current run context (mutual exclusion lock)

    \b
    Used to release the currently active context after task completion or before switching tasks.

    \b
    Examples:
        frago run release
    """
    try:
        context_mgr = get_context_manager()
        released_run_id = context_mgr.release_context()

        if released_run_id:
            output_json({
                "released_run_id": released_run_id,
                "released_at": format_timestamp(datetime.now()),
            })
        else:
            click.echo("No active context to release.")
    except Exception as e:
        handle_error(e)


@run_group.command(cls=AgentFriendlyCommand)
@click.option(
    "--format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.option(
    "--status",
    type=click.Choice(["all", "active", "inactive"]),
    default="all",
    help="Filter by status (active / inactive; legacy 'archived' is now 'inactive')",
)
@click.option(
    "--flat",
    is_flag=True,
    default=False,
    help="Legacy flat run-id list (default: domain-centric view)",
)
def list(format: str, status: str, flat: bool):
    """List all run instances / domains

    \b
    Default: domain-centric view (one row per domain with session/insight counts).
    --flat: legacy flat run_id table.

    \b
    Examples:
        frago run list
        frago run list --status active
        frago run list --flat
        frago run list --format json
    """
    try:
        manager = get_manager()

        status_filter = None
        if status == "active":
            status_filter = RunStatus.ACTIVE
        elif status == "inactive":
            status_filter = RunStatus.INACTIVE

        runs = manager.list_runs(status=status_filter)

        if format == "json":
            output_json({"runs": runs, "total": len(runs), "flat": flat})
            return

        if not runs:
            click.echo("No run instances found.")
            return

        if flat:
            click.echo(
                f"{'RUN_ID':<40} {'STATUS':<10} {'CREATED_AT':<20} {'LAST_ACCESSED':<20}"
            )
            click.echo("-" * 90)
            for run in runs:
                created = run["created_at"][:19].replace("T", " ")
                accessed = run["last_accessed"][:19].replace("T", " ")
                click.echo(
                    f"{run['run_id']:<40} {run['status']:<10} {created:<20} {accessed:<20}"
                )
            return

        # Domain-centric view
        click.echo(
            f"{'DOMAIN':<32} {'STATUS':<10} {'SESS':>5} {'INSI':>5} {'X':>2} {'LAST_ACTIVE':<19}"
        )
        click.echo("-" * 80)
        for run in runs:
            domain = run.get("domain") or run["run_id"]
            cross = "Y" if run.get("is_cross_domain") else "-"
            accessed = run["last_accessed"][:19].replace("T", " ")
            click.echo(
                f"{domain:<32} {run['status']:<10} "
                f"{run.get('session_count', 0):>5} "
                f"{run.get('insight_count', 0):>5} "
                f"{cross:>2} "
                f"{accessed:<19}"
            )

    except RunException as e:
        handle_error(e)


@run_group.command(cls=AgentFriendlyCommand)
@click.argument("run_id")
@click.option(
    "--format",
    type=click.Choice(["human", "json"]),
    default="human",
    help="Output format",
)
@click.option(
    "--peek",
    is_flag=True,
    default=False,
    help="Compact prior-knowledge summary (recent sessions + top insights)",
)
@click.option(
    "--n-sessions",
    type=int,
    default=3,
    show_default=True,
    help="(--peek only) max recent sessions to include",
)
@click.option(
    "--n-insights",
    type=int,
    default=5,
    show_default=True,
    help="(--peek only) max top insights to include",
)
def info(run_id: str, format: str, peek: bool, n_sessions: int, n_insights: int):
    """Show run instance / domain details

    \b
    Examples:
        frago run info twitter
        frago run info twitter --format json
        frago run info twitter --peek
        frago run info twitter --peek --n-sessions 5 --n-insights 10
    """
    try:
        manager = get_manager()

        if peek:
            try:
                summary = manager.peek_domain(
                    run_id, n_sessions=n_sessions, n_insights=n_insights
                )
            except RunNotFoundError:
                handle_error(
                    RunNotFoundError(
                        f"{run_id}\n  Hint: try `frago run init '{run_id}'` to create it first."
                    )
                )
                return
            output_json(summary)
            return

        instance = manager.find_run(run_id)
        stats = manager.get_run_statistics(run_id)

        run_dir = PROJECTS_DIR / run_id
        logger = RunLogger(run_dir)
        recent_logs = logger.get_recent_logs(count=5)

        if format == "json":
            output_json({
                "run_id": instance.run_id,
                "status": instance.status.value,
                "theme_description": instance.theme_description,
                "created_at": format_timestamp(instance.created_at),
                "last_accessed": format_timestamp(instance.last_accessed),
                "extra_metadata": get_extra_metadata(instance),
                "statistics": stats,
                "recent_logs": [
                    {
                        "timestamp": format_timestamp(log.timestamp),
                        "step": log.step,
                        "status": log.status.value,
                        "action_type": log.action_type.value,
                        "execution_method": log.execution_method.value,
                    }
                    for log in recent_logs
                ],
            })
        else:
            # Human-readable format
            click.echo(f"\nRun ID: {instance.run_id}")
            click.echo(f"Status: {instance.status.value}")
            click.echo(f"Theme: {instance.theme_description}")
            click.echo(
                f"Created: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            click.echo(
                f"Last Accessed: {instance.last_accessed.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            click.echo("\nStatistics:")
            click.echo(f"- Log Entries: {stats['log_entries']}")
            click.echo(f"- Screenshots: {stats['screenshots']}")
            click.echo(f"- Scripts: {stats['scripts']}")
            click.echo(f"- Disk Usage: {stats['disk_usage_bytes'] / 1024:.1f} KB")

            # Display extra metadata
            extra_metadata = get_extra_metadata(instance)
            if extra_metadata:
                click.echo(format_extra_metadata(extra_metadata))

            if recent_logs:
                click.echo("\nRecent Logs (last 5):")
                for log in recent_logs:
                    status_icon = "[OK]" if log.status == LogStatus.SUCCESS else "[X]"
                    timestamp = log.timestamp.strftime("%Y-%m-%d %H:%M")
                    click.echo(
                        f"  [{timestamp}] {status_icon} {log.step} "
                        f"({log.action_type.value}/{log.execution_method.value})"
                    )

    except RunException as e:
        handle_error(e)


@run_group.command(cls=AgentFriendlyCommand)
@click.argument("run_id")
def archive(run_id: str):
    """Archive a run instance

    \b
    Examples:
        frago run archive find-job-on-upwork
    """
    try:
        manager = get_manager()
        instance = manager.archive_run(run_id)

        # If it's the current context's run, clear the context
        context_mgr = get_context_manager()
        current_run_id = context_mgr.get_current_run_id()
        if current_run_id == run_id:
            context_mgr._clear_context()

        output_json({
            "run_id": instance.run_id,
            "archived_at": format_timestamp(datetime.now()),
            "previous_status": "active",
        })
    except RunException as e:
        handle_error(e)


@run_group.command(cls=AgentFriendlyCommand)
@click.option("--step", required=True, help="Step description")
@click.option(
    "--status",
    type=click.Choice(["success", "error", "warning"]),
    required=True,
    help="Execution status",
)
@click.option(
    "--action-type",
    type=click.Choice(
        [
            "navigation",
            "extraction",
            "interaction",
            "screenshot",
            "recipe_execution",
            "data_processing",
            "analysis",
            "user_interaction",
            "other",
        ]
    ),
    required=True,
    help="Action type",
)
@click.option(
    "--execution-method",
    type=click.Choice(["command", "recipe", "file", "manual", "analysis", "tool"]),
    required=True,
    help="Execution method",
)
@click.option("--data", required=True, help="Detailed data in JSON format")
@click.option(
    "--insight",
    multiple=True,
    hidden=True,  # Retired 2026-07-26: rejected at runtime, points to `frago <域> save`.
    help="(retired)",
)
def log(step: str, status: str, action_type: str, execution_method: str, data: str, insight: tuple):
    """Record structured log entry

    \b
    Examples:
        frago run log \\
          --step "Navigate to search page" \\
          --status "success" \\
          --action-type "navigation" \\
          --execution-method "command" \\
          --data '{"command": "frago browser navigate https://upwork.com"}'

    \b
    Domain-level knowledge no longer lives here. insight 形态已退役，沉淀改用:
        frago <域名> save --name=<文档名> --data='{...}'
    See `frago def list` / `frago <域名> find`.
    """
    try:
        # Get current context
        context_mgr = get_context_manager()
        context = context_mgr.get_current_run()

        # Parse data
        try:
            data_dict = json.loads(data)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON in --data: {e}", err=True)
            sys.exit(2)

        # insight 形态已退役，这条 log 附带 insight 的老路一并封死。
        insights_list = None
        if insight:
            raise click.UsageError(_INSIGHT_WRITE_RETIRED_MSG)

        # Write log
        run_dir = PROJECTS_DIR / context.run_id
        logger = RunLogger(run_dir)
        entry = logger.write_log(
            step=step,
            status=LogStatus(status),
            action_type=ActionType(action_type),
            execution_method=ExecutionMethod(execution_method),
            data=data_dict,
            insights=insights_list,
        )

        result = {
            "logged_at": format_timestamp(entry.timestamp),
            "run_id": context.run_id,
            "log_file": str(run_dir / "logs" / "execution.jsonl"),
        }
        if insights_list:
            result["insights_count"] = len(insights_list)
        output_json(result)
    except ContextNotSetError as e:
        handle_error(e)
    except RunException as e:
        handle_error(e, exit_code=3)


@run_group.command(cls=AgentFriendlyCommand)
@click.argument("description")
def screenshot(description: str):
    """Save screenshot (auto-numbered)

    \b
    Examples:
        frago run screenshot "Search results page"
    """
    try:
        # Get current context
        context_mgr = get_context_manager()
        context = context_mgr.get_current_run()

        run_dir = PROJECTS_DIR / context.run_id
        screenshots_dir = run_dir / "screenshots"

        # Import screenshot module (to be implemented)
        from ..run.screenshot import capture_screenshot

        file_path, sequence_number = capture_screenshot(description, screenshots_dir)

        # Automatically record log
        logger = RunLogger(run_dir)
        logger.write_log(
            step=f"Screenshot: {description}",
            status=LogStatus.SUCCESS,
            action_type=ActionType.SCREENSHOT,
            execution_method=ExecutionMethod.COMMAND,
            data={
                "file_path": str(file_path),
                "sequence_number": sequence_number,
                "description": description,
            },
        )

        output_json({
            "file_path": str(file_path),
            "sequence_number": sequence_number,
            "saved_at": format_timestamp(datetime.now()),
        })
    except ContextNotSetError as e:
        handle_error(e)
    except RunException as e:
        handle_error(e, exit_code=2)


@run_group.command(cls=AgentFriendlyCommand)
@click.argument("keyword")
@click.option("--limit", default=10, help="Maximum number of results")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def find(keyword: str, limit: int, fmt: str):
    """Search run instances by keyword

    \b
    Two-layer search: fuzzy match on run ID/theme + grep log step fields.

    \b
    Examples:
        frago run find twitter
        frago run find etf --limit 3
        frago run find twitter --format json
    """
    try:
        manager = get_manager()
        discovery = RunDiscovery(manager)
        results = discovery.search_runs(keyword, max_results=limit)

        # Phase 2: also search insight payloads across domains.
        insight_hits = search_insights_across_domains(
            PROJECTS_DIR, keyword, limit=limit
        )

        if not results and not insight_hits:
            click.echo("No matching runs or insights found.")
            return

        if fmt == "json":
            click.echo(json.dumps(
                {"runs": results, "insights": insight_hits},
                ensure_ascii=False,
                indent=2,
            ))
            return

        if results:
            click.echo(f"\nFound {len(results)} matching runs:\n")
            click.echo(
                f"  {'RUN_ID':<55} {'MATCH':>5}  {'PURPOSE':<35} {'DATE':<10}"
            )
            click.echo("  " + "-" * 110)
            for r in results:
                date = r.get("created_at", r.get("last_accessed", ""))[:10]
                similarity = r.get("similarity", 0)
                purpose = r.get("purpose") or "-"
                if len(purpose) > 33:
                    purpose = purpose[:31] + ".."
                click.echo(
                    f"  {r['run_id']:<55} {similarity:>4}%  {purpose:<35} {date:<10}"
                )

        if insight_hits:
            click.echo(f"\nFound {len(insight_hits)} matching insights:\n")
            click.echo(f"  {'DOMAIN':<24} {'TYPE':<12} {'PAYLOAD':<70}")
            click.echo("  " + "-" * 110)
            for hit in insight_hits:
                ins = hit["insight"]
                payload = ins["payload"]
                if len(payload) > 68:
                    payload = payload[:66] + ".."
                click.echo(
                    f"  {hit['domain']:<24} {ins['type']:<12} {payload:<70}"
                )

        click.echo(
            "\nTip: frago run insights --domain <name> --query <kw> for deep search"
        )
    except RunException as e:
        handle_error(e)


_INSIGHT_WRITE_RETIRED_MSG = (
    "insight 写入已退役，本命令不再接受 --save / --update。\n"
    "  唯一的知识沉淀形态是 def 领域文档：\n"
    "    frago <域名> save --name=<文档名> --data='{...}'\n"
    "  先看有哪些域：frago def list；看某域已有内容：frago <域名> find\n"
    "  历史 insight 已于 2026-07-26 全量迁入 ~/.frago/books，原件存档在 "
    "~/.frago/_archive/insight-migration-20260726-003044/。\n"
    "  只读查询仍可用：frago run insights [--domain <域>] [--query <关键词>]"
)


def _resolve_insight_domain(explicit: str | None) -> str:
    """Resolve which domain insight CRUD applies to.

    Order: --domain > current_run context > error.
    """
    if explicit:
        # Route explicit --domain through the canonical dict, exactly like
        # `run init` does: an alias such as "etf-research" snaps to its
        # canonical "quant-trading" instead of forking a near-duplicate domain.
        hit = lookup_domain(explicit)
        normalized = normalize_domain_name(hit or explicit)
        if not normalized:
            raise click.UsageError("--domain cannot be empty after normalization")
        if hit and hit != normalize_domain_name(explicit):
            click.echo(
                f"[domain] '--domain {explicit}' 命中 canonical 域 '{hit}'，"
                f"知识将并入该域；如需独立域请先 `frago domain_dict save --name=<name> --data='{{\"aliases\":[...]}}'` 注册",
                err=True,
            )
        return normalized
    ctx_mgr = get_context_manager()
    try:
        ctx = ctx_mgr.get_current_run()
    except ContextNotSetError:
        ctx = None
    if ctx and ctx.run_id:
        return ctx.run_id
    raise click.UsageError(
        "No domain context. Pass --domain <name> or run "
        "`frago run set-context <domain>` first."
    )


@run_group.command(cls=AgentFriendlyCommand)
@click.option("--run-id", default=None, help="(legacy) full experience card for a run_id")
@click.option("--domain", default=None, help="Domain name (default: current run context)")
@click.option(
    "--save",
    "save_mode",
    is_flag=True,
    default=False,
    hidden=True,
    help="(retired) insight 写入已退役，改用 frago <域> save",
)
@click.option(
    "--update",
    "update_id",
    default=None,
    hidden=True,
    help="(retired) insight 写入已退役，改用 frago <域> save",
)
@click.option("--query", "query_text", default=None, help="Substring search insight payloads")
@click.option(
    "--type",
    "insight_type",
    default=None,
    help="Insight type (new schema: fact|decision|foreshadow|state|lesson; legacy aggregation: pitfall|lesson|key_factor|workaround)",
)
@click.option("--payload", default=None, help="(--save / --update) insight payload text")
@click.option(
    "--confidence",
    type=float,
    default=None,
    help="(--save / --update) confidence in [0.0, 1.0]",
)
@click.option(
    "--related-sessions",
    "related_sessions",
    default=None,
    help="(--save / --update) comma-separated session ids",
)
@click.option("--limit", default=20, help="Maximum number of results (0 for all)")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def insights(
    run_id: str | None,
    domain: str | None,
    save_mode: bool,
    update_id: str | None,
    query_text: str | None,
    insight_type: str | None,
    payload: str | None,
    confidence: float | None,
    related_sessions: str | None,
    limit: int,
    fmt: str,
):
    """Domain-level insights — READ-ONLY archive view (write path retired).

    \b
    insight 形态已于 2026-07-26 退役。沉淀请用 def 领域文档：
        frago def list                       # 有哪些知识域
        frago <域名> find                     # 该域已有什么
        frago <域名> save --name=... --data=... # 沉淀新知识

    \b
    READ (default — current domain):
        frago run insights
        frago run insights --query "API rate limit"
        frago run insights --type fact --limit 5
        frago run insights --domain twitter

    \b
    RETIRED (rejected with guidance):
        --save / --update

    \b
    LEGACY (run-scoped experience card; deprecated):
        frago run insights --run-id <legacy_run_id>
    """
    try:
        manager = get_manager()
        discovery = RunDiscovery(manager)

        # WRITE modes are retired ------------------------------------------
        # insight 形态已于 2026-07-26 退役：全部历史知识已迁入 books，唯一的
        # 沉淀形态是 `frago <域> save`。写入口保留会继续制造第二套散落知识，
        # 故在 CLI 层封死；读取保留，旧数据不成孤儿。
        # 任何带写意图的调用形态（含只给 payload/confidence/related-sessions
        # 而漏了 --save 的）都在这里拦下，避免"看着成功其实没落盘"的错觉。
        if (
            save_mode
            or update_id
            or payload
            or confidence is not None
            or related_sessions
        ):
            raise click.UsageError(_INSIGHT_WRITE_RETIRED_MSG)

        # Legacy --run-id experience card --------------------------------
        if run_id:
            exp = discovery.get_run_experience(run_id)

            if fmt == "json":
                click.echo(json.dumps(exp, ensure_ascii=False, indent=2))
                return

            click.echo(f"\n== {exp['run_id']} ==\n")

            if exp["purpose"]:
                click.echo(f"  Purpose:  {exp['purpose']}")
            if exp["method"]:
                method = exp["method"]
                if isinstance(method, str):
                    click.echo(f"  Method:   {method}")
                else:
                    click.echo(f"  Method:   {json.dumps(method, ensure_ascii=False)}")
            if exp["reuse_guidance"]:
                guidance = exp["reuse_guidance"]
                if isinstance(guidance, str):
                    click.echo(f"  Reuse:    {guidance}")
                elif isinstance(guidance, dict):
                    for k, v in guidance.items():
                        click.echo(f"  Reuse ({k}): {v}")
            if exp["recipe_potential"]:
                rp = exp["recipe_potential"]
                if isinstance(rp, dict):
                    ready = rp.get("ready", False)
                    note = rp.get("reason") or rp.get("note", "")
                    click.echo(f"  Recipe:   {'ready' if ready else 'not ready'}{' — ' + note if note else ''}")

            insight_list = exp["insights"]
            if insight_type:
                insight_list = [i for i in insight_list if i["type"] == insight_type]

            if insight_list:
                click.echo(f"\n  Insights ({len(insight_list)}):")
                for i in insight_list:
                    click.echo(f"    {i['type']:<14} {i['summary']}")

            if not exp["purpose"] and not exp["method"] and not insight_list:
                click.echo("  No experience data found for this run.")

            return

        # Default READ mode: list / query insights of the resolved domain.
        target_domain = _resolve_insight_domain(domain)
        if insight_type and insight_type not in DOMAIN_INSIGHT_TYPES:
            raise click.UsageError(
                f"Invalid --type {insight_type!r}. Use one of: "
                f"{sorted(DOMAIN_INSIGHT_TYPES)}."
            )
        effective_limit = limit if limit > 0 else None
        if query_text:
            entries = query_domain_insights(
                PROJECTS_DIR,
                target_domain,
                keyword=query_text,
                type=insight_type,
                limit=effective_limit,
            )
        else:
            entries = list_domain_insights(
                PROJECTS_DIR,
                target_domain,
                type=insight_type,
                limit=effective_limit,
            )

        if not entries:
            if fmt == "json":
                output_json({"domain": target_domain, "insights": []})
            else:
                click.echo(f"No insights found for domain {target_domain}.")
            return

        if fmt == "json":
            output_json({
                "domain": target_domain,
                "count": len(entries),
                "insights": [e.to_dict() for e in entries],
            })
            return

        click.echo(f"\nDomain: {target_domain}  ({len(entries)} insights)\n")
        click.echo(f"  {'ID':<28} {'TYPE':<12} {'CONF':>5}  {'PAYLOAD':<60}")
        click.echo("  " + "-" * 110)
        for e in entries:
            payload_preview = e.payload if len(e.payload) <= 58 else e.payload[:56] + ".."
            click.echo(
                f"  {e.id:<28} {e.type.value:<12} {e.confidence:>5.2f}  {payload_preview:<60}"
            )
    except click.UsageError:
        raise
    except RunException as e:
        handle_error(e)
