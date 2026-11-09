#!/usr/bin/env python3
"""
Frago Session Commands - Session Management Command Group

Provides session data querying, viewing, and management functions:
- session list: List sessions, newest created first
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
    find_session_by_prefix,
    get_session_data,
    is_managed_session,
    list_sessions,
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
@click.option("--agent", "agent_only", is_flag=True, help="Print THIS session's CLI agent type (e.g. claude/codex/opencode/agy/coreagent)")
@click.option("--signature", "signature_only", is_flag=True, help="Print THIS CLI agent's commit 'Generated with [...]' signature line")
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
def self_cmd(agent_only: bool, signature_only: bool, json_output: bool):
    """Print THIS session's id (or CLI agent identity / signature).

    An agent cannot see its own session id or CLI agent runtime from the prompt
    alone: it lives in the environment and process tree that started it.

    \b
    Prints the bare id on stdout (safe to capture), notes on stderr:
      frago session self
      frago session self --agent      # claude / codex / opencode / agy / coreagent
      frago session self --signature  # 🤖 Generated with [<CLI Agent>](<url>)
      frago todo add "..." --session "$(frago session self)"
      frago session self --json       # id + where it came from + record path
    """
    import json as json_module

    if agent_only or signature_only:
        from frago.session.self_id import resolve_self_agent

        found_agent = resolve_self_agent()
        if found_agent is None:
            from .agent_friendly import BusinessError

            raise BusinessError(
                "cannot resolve current CLI agent — no CLI agent process ancestor "
                "or session environment variable found",
                'export FRAGO_CLI_AGENT="claude"  # declare explicitly, then retry',
                "frago agent self --json",
            )
        if json_output:
            click.echo(json_module.dumps(found_agent.to_dict(), ensure_ascii=False, indent=2))
            return
        if signature_only:
            click.echo(found_agent.generated_with)
            return
        click.echo(found_agent.agent_type)
        return

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
    type=click.Choice(["claude", "opencode", "codex", "coreagent", "agy", "cursor", "cline", "all"]),
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
    List sessions, newest created first

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

    click.echo(f"{'Session ID':<12} {'Type':<8} {'Status':<10} {'Steps':<6} {'Tools':<6} {'Created':<20} {'Last Activity':<20}")
    click.echo("-" * 91)

    for session in sessions:
        session_id_short = session.session_id[:8] + "..."
        agent = session.agent_type.value
        status_str = _get_status_display(session.status)
        steps = str(session.step_count)
        tools = str(session.tool_call_count)
        created = session.started_at.strftime("%Y-%m-%d %H:%M:%S")
        last_activity = session.last_activity.strftime("%Y-%m-%d %H:%M:%S")

        click.echo(f"{session_id_short:<12} {agent:<8} {status_str:<10} {steps:<6} {tools:<6} {created:<20} {last_activity:<20}")


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
@click.argument("query", required=False, default="")
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
    """Search raw session transcripts by meaning, across claude, opencode AND codex.

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
    clean_query = (query or "").strip()
    if not clean_query and not explicit:
        raise click.ClickException(
            'Missing search query: provide QUERY argument or --terms "term1,term2".'
        )
    effective_query = clean_query or ", ".join(explicit or [])

    if not json_output and explicit is None and not no_expand:
        click.echo("正在让模型把这句话摊成关键词（可用 --no-expand 跳过）…", err=True)

    result = search_sessions(
        effective_query,
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
        lines.append(f'    单轮提取：frago session ask {hit.session_id[:8]} "<要提取的具体问题>"')
        for snippet in hit.snippets:
            lines.append(f"    · ({snippet.term}) {snippet.text}")

    lines.append("")
    lines.append(
        '提示：提取某场会话的具体结论或片段请用 frago session ask <会话id> "<问句>"'
        "（轻量模型单轮秒回，勿直接 Read 或用 python 读 raw.jsonl）。"
    )
    return "\n".join(lines)


@session_group.command("ask", cls=AgentFriendlyCommand)
@click.argument("session_id")
@click.argument("question")
@click.option(
    "--grep", "-g",
    default=None,
    help="Comma-separated literal terms to filter records (+2 neighbor context)",
)
@click.option(
    "--tail", "-n",
    type=int,
    default=None,
    help="Focus on the last N non-empty records of the session",
)
@click.option(
    "--range", "-r", "range_spec",
    default=None,
    help="1-based record range start:end (e.g. 450:520)",
)
@click.option(
    "--model",
    default=None,
    help="Override model for the single-turn extraction",
)
@click.option(
    "--timeout",
    type=int,
    default=None,
    help="Seconds allowed for the single-turn extraction (default 60)",
)
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
def ask_cmd(
    session_id: str,
    question: str,
    grep: str | None,
    tail: int | None,
    range_spec: str | None,
    model: str | None,
    timeout: int | None,
    json_output: bool,
):
    """Extract specific answers or conclusions from a session in a single turn.

    Cleans and redacts the session transcript (supporting full session_id or
    unique prefix across claude, opencode, codex, coreagent, and agy), windows
    onto the relevant records, and queries ``frago-core --mode chat --as-role
    lightagent`` in a single stateless turn (no tools, no tmux, no new session
    file). Use this instead of reading ``raw.jsonl`` directly with Read or
    Python scripts.

    \b
    Examples:
      frago session ask 32c0bb7a "提取最后一条结论记录并脱敏连接串" --tail 20
      frago session ask a1d5f9f8 "第 450 至 520 条记录中引用的 32c0bb7a 结论是什么" --range 450:520
      frago session ask 32c0bb7a "报错原因和最终修复命令是什么" --grep "32c0bb7a,error"
    """
    from frago.session.ask import (
        ASK_TIMEOUT_S,
        SessionAskError,
        ask_session,
    )

    from .agent_friendly import BusinessError

    try:
        result = ask_session(
            session_id,
            question,
            grep=grep,
            tail=tail,
            range_spec=range_spec,
            model=model,
            timeout_s=float(timeout or ASK_TIMEOUT_S),
        )
    except ValueError as exc:
        raise BusinessError(
            str(exc),
            'frago session ask <session_id> "<question>" --range 450:520',
        ) from exc
    except SessionAskError as exc:
        raise BusinessError(
            str(exc),
            'frago session search "<keywords>"  # locate the session id first',
        ) from exc

    if json_output:
        payload = {
            "session_id": result.session_id,
            "source": result.source,
            "question": result.question,
            "answer": result.answer,
            "answer_source": result.answer_source,
            "total_records": result.total_records,
            "selected_records": len(result.selected_seqs),
            "selected_seqs": result.selected_seqs,
            "location": result.location,
            "duration_ms": result.duration_ms,
            "note": result.note,
        }
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    header = (
        f"会话：{result.session_id}（{result.source}，共 {result.total_records} 条记录，"
        f"选取 {len(result.selected_seqs)} 条，耗时 {result.duration_ms / 1000:.1f}s）"
    )
    click.echo(header)
    if result.note:
        click.echo(f"[!] {result.note}")
    click.echo("-" * 72)
    click.echo(result.answer)


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
    type=click.Choice(["claude", "opencode", "codex", "coreagent", "agy", "cursor", "cline"]),
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

    # Support prefix matching, with multi-kernel fallback via record_reader
    session = _find_session_by_prefix(session_id, agent)
    rr_bundle = None
    if not session or (
        session.step_count == 0
        and not is_managed_session(session.session_id, session.agent_type)
    ):
        rr_bundle = _resolve_session_via_record_reader(session_id)
        if rr_bundle is not None:
            session = rr_bundle[0]

    if not session:
        click.echo(f"Session not found: {session_id}", err=True)
        sys.exit(1)

    if json_output:
        if rr_bundle is not None:
            rr_session, rr_steps, rr_summary = rr_bundle
            output = {
                "metadata": rr_session.model_dump(mode="json"),
                "steps": [s.model_dump(mode="json") for s in rr_steps],
                "summary": rr_summary.model_dump(mode="json") if rr_summary else None,
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
            return
        # JSON output
        data = get_session_data(session.session_id, session.agent_type)
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
    summary = (
        rr_bundle[2]
        if rr_bundle is not None
        else read_summary(session.session_id, session.agent_type)
    )
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
        step_list = (
            rr_bundle[1]
            if rr_bundle is not None
            else read_steps(session.session_id, session.agent_type)
        )
        if step_list:
            click.echo(f"\n📜 Step History ({len(step_list)} items)")
            click.echo("-" * 60)
            for step in step_list:
                icon = get_step_icon(step.type)
                label = get_step_label(step.type)
                ts = step.timestamp.strftime("%H:%M:%S")
                click.echo(f"  [{ts}] {icon} {label}: {step.content_summary}")

    click.echo(
        f'\n💡 单轮提取本场具体内容：frago session ask {session.session_id[:8]} "<要提取的问题>"'
    )


def _find_session_by_prefix(prefix: str, agent_type: AgentType):
    """Find session by prefix, falling back across other AgentType directories."""
    found = find_session_by_prefix(prefix, agent_type)
    if found is not None:
        return found
    for alt_agent in (
        AgentType.AGY,
        AgentType.COREAGENT,
        AgentType.CODEX,
        AgentType.OPENCODE,
        AgentType.CLAUDE,
    ):
        if alt_agent == agent_type:
            continue
        found = find_session_by_prefix(prefix, alt_agent)
        if found is not None:
            return found
    return None


def _resolve_session_via_record_reader(
    session_id_or_prefix: str,
):
    """Fallback to multi-kernel unified `record_reader` (claude-code / opencode / codex / coreagent / agy)."""
    from collections import Counter

    from frago.session import record_reader
    from frago.session.models import (
        MonitoredSession,
        SessionSource,
        SessionStep,
        SessionSummary,
        StepType,
        ToolUsageStats,
    )

    needle = (session_id_or_prefix or "").strip()
    if not needle:
        return None

    card = None
    try:
        cards = record_reader.list_sessions()
        matched = [
            c
            for c in cards
            if c.session_id == needle or c.session_id.startswith(needle)
        ]
        if matched:
            exact = [c for c in matched if c.session_id == needle]
            card = exact[0] if exact else matched[0]
    except Exception:
        card = None

    family = card.family if card is not None else None
    resolved_sid = card.session_id if card is not None else needle
    if family is None:
        try:
            family = record_reader.detect_family(resolved_sid)
        except Exception:
            return None

    try:
        unified_records = record_reader.read_records(
            resolved_sid, after=0, limit=record_reader.MAX_LIMIT
        )
    except Exception:
        unified_records = []

    if card is None and not unified_records:
        return None

    family_to_agent = {
        "claude-code": AgentType.CLAUDE,
        "opencode": AgentType.OPENCODE,
        "codex": AgentType.CODEX,
        "coreagent": AgentType.COREAGENT,
        "agy": AgentType.AGY,
    }
    mapped_agent = family_to_agent.get(str(family), AgentType.CLAUDE)

    if card is not None:
        if card.status == "running":
            mapped_status = SessionStatus.RUNNING
        elif card.status == "error":
            mapped_status = SessionStatus.ERROR
        else:
            mapped_status = SessionStatus.COMPLETED
        started_dt = (
            datetime.fromtimestamp(card.created_at / 1000.0)
            if card.created_at > 0
            else datetime.now()
        )
        last_active_dt = (
            datetime.fromtimestamp(card.last_active_at / 1000.0)
            if card.last_active_at > 0
            else started_dt
        )
        project_path = card.directory or ""
        title = card.title
    else:
        mapped_status = SessionStatus.COMPLETED
        first_ts = next((r.ts for r in unified_records if r.ts > 0), 0)
        last_ts = next((r.ts for r in reversed(unified_records) if r.ts > 0), first_ts)
        started_dt = (
            datetime.fromtimestamp(first_ts / 1000.0)
            if first_ts > 0
            else datetime.now()
        )
        last_active_dt = (
            datetime.fromtimestamp(last_ts / 1000.0) if last_ts > 0 else started_dt
        )
        project_path = ""
        title = resolved_sid

    step_list: list[SessionStep] = []
    user_count = 0
    assistant_count = 0
    tool_call_count = 0
    tool_success_count = 0
    tool_error_count = 0
    tool_counter: Counter[str] = Counter()

    for idx, rec in enumerate(unified_records, start=1):
        payload = rec.payload if isinstance(rec.payload, dict) else {}
        if rec.kind == "user.say":
            step_type = StepType.USER_MESSAGE
            user_count += 1
        elif rec.kind in ("agent.say", "agent.think"):
            step_type = StepType.ASSISTANT_MESSAGE
            if rec.kind == "agent.say":
                assistant_count += 1
        elif rec.kind in ("tool.call", "subagent.dispatch"):
            step_type = StepType.TOOL_CALL
            tool_call_count += 1
            t_name = str(
                payload.get("tool")
                or payload.get("name")
                or payload.get("tool_name")
                or rec.kind
            )
            tool_counter[t_name] += 1
        elif rec.kind == "tool.result":
            step_type = StepType.TOOL_RESULT
            if payload.get("is_error") or payload.get("status") == "error":
                tool_error_count += 1
            else:
                tool_success_count += 1
        else:
            step_type = StepType.SYSTEM_EVENT
            if rec.kind == "error":
                tool_error_count += 1

        summary_text = str(
            payload.get("text")
            or payload.get("summary")
            or payload.get("command")
            or payload.get("output")
            or payload.get("message")
            or payload.get("title")
            or rec.kind
        ).strip()
        if len(summary_text) > 200:
            summary_text = summary_text[:197] + "..."

        rec_dt = (
            datetime.fromtimestamp(rec.ts / 1000.0) if rec.ts > 0 else last_active_dt
        )
        step_list.append(
            SessionStep(
                step_id=idx,
                session_id=resolved_sid,
                type=step_type,
                timestamp=rec_dt,
                content_summary=summary_text or rec.kind,
                raw_uuid=str(rec.id or f"seq-{rec.seq}"),
                tool_name=str(payload.get("tool") or payload.get("name") or "") or None,
            )
        )

    duration_ms = max(0, int((last_active_dt - started_dt).total_seconds() * 1000))
    most_used = [
        ToolUsageStats(tool_name=name, count=count)
        for name, count in tool_counter.most_common(5)
    ]
    model_name = None
    source_file = f"record_reader:{family}/{resolved_sid}"
    if mapped_agent == AgentType.AGY:
        from frago.session import agy_store

        model_name = agy_store.session_model(resolved_sid)
        source_file = str(agy_store.transcript_path(resolved_sid))

    monitored = MonitoredSession(
        session_id=resolved_sid,
        agent_type=mapped_agent,
        project_path=project_path,
        name=title,
        source_file=source_file,
        started_at=started_dt,
        last_activity=last_active_dt,
        ended_at=last_active_dt if mapped_status != SessionStatus.RUNNING else None,
        status=mapped_status,
        step_count=len(step_list),
        tool_call_count=tool_call_count,
        source=SessionSource.UNKNOWN,
    )
    summary = SessionSummary(
        session_id=resolved_sid,
        total_duration_ms=duration_ms,
        user_message_count=user_count,
        assistant_message_count=assistant_count,
        tool_call_count=tool_call_count,
        tool_success_count=tool_success_count,
        tool_error_count=tool_error_count,
        most_used_tools=most_used,
        final_status=mapped_status,
        model=model_name,
    )
    return monitored, step_list, summary


@session_group.command("watch", cls=AgentFriendlyCommand)
@click.argument("session_id", required=False)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="Output in JSON format"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "opencode", "coreagent", "cursor", "cline"]),
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
    type=click.Choice(["claude", "opencode", "coreagent", "cursor", "cline", "all"]),
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
    # 只清 frago 自己管过的会话。清单现在也含同步进来的原文镜像，那些目录里没有
    # metadata，是各家 CLI 转录的唯一副本，不归这条命令管。
    old_sessions = [
        s
        for s in sessions
        if s.last_activity < cutoff and is_managed_session(s.session_id, s.agent_type)
    ]

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
    type=click.Choice(["claude", "opencode", "coreagent", "cursor", "cline"]),
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

    from frago.session.coreagent_sync import sync_coreagent_sessions
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

    # coreagent: its records are not project-scoped either, so every run archives
    # all of them. Same rule as opencode — a failure lands in the errors list.
    try:
        coreagent_result = sync_coreagent_sessions()
        result.synced += coreagent_result.synced
        result.updated += coreagent_result.updated
        result.skipped += coreagent_result.skipped
        result.errors.extend(coreagent_result.errors)
    except Exception as e:  # noqa: BLE001
        result.errors.append(f"coreagent: {e}")

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
