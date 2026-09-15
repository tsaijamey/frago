"""Schedule management commands."""

import json

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup
from frago.server.services.scheduler_service import (
    SchedulerService,
    _parse_interval,
)


@click.group(name="schedule", cls=AgentFriendlyGroup)
def schedule_group():
    """Manage scheduled tasks."""
    pass


@schedule_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("recipe_name", required=False, default=None)
@click.option(
    "--every",
    default=None,
    help="Run interval: e.g. 30s, 10m, 2h (mutually exclusive with --cron)",
)
@click.option(
    "--cron",
    default=None,
    help="Cron expression: e.g. '0 8 * * *' (mutually exclusive with --every)",
)
@click.option("--name", default=None, help="Human-readable schedule name")
@click.option("--prompt", default=None, help="自然语言任务，交给 CoreAgent 理解并执行")
@click.option(
    "--instructions",
    default=None,
    help="--prompt 用：CoreAgent 读的说明书，~/.frago/coreagent/ 下的文件名（如 todo-triage.md）",
)
@click.option(
    "--allowed-tools",
    "allowed_tools",
    multiple=True,
    help="--prompt 用：只允许这些工具调用，写法同 Claude Code 权限规则（可重复，如 Read、'Bash(git log:*)'）；不给就不限制",
)
@click.option(
    "--disallowed-tools",
    "disallowed_tools",
    multiple=True,
    help="--prompt 用：禁止这些工具调用，命中即拒，优先于允许（可重复，如 'Bash(rm:*)'）",
)
@click.option("--command", default=None, help="一条 shell 命令，frago 直接执行（不经 PA）")
@click.option("--cwd", default=None, help="工作目录，默认家目录：--command 在这里执行，--prompt 的 CoreAgent 在这里干活")
@click.option("--params", default=None, help="JSON params for the recipe")
@click.option(
    "--notify-on",
    type=click.Choice(["change", "always", "failure", "never"]),
    default="change",
    help="什么时候通知：change（默认，有新鲜事才说）/ always / failure / never",
)
@click.option(
    "--notify-to",
    default=None,
    help="通知推到哪：已配置的 channel 名（见 frago channel list）、desktop、或 pa",
)
@click.option(
    "--notify-context",
    default=None,
    help="通知落点需要的定位信息 JSON，如飞书的 '{\"chat_id\":\"oc_xxx\"}'",
)
@click.option("--start", default=None, help="Start time (ISO 8601), default: now")
@click.option("--end", default=None, help="End time (ISO 8601), default: never")
@click.option(
    "--overlap",
    type=click.Choice(["skip", "queue"]),
    default="skip",
    help="Overlap control: skip (default) or queue",
)
@click.option("--timeout", type=int, default=300, help="Execution timeout in seconds (default: 300)")
def schedule_add(
    recipe_name: str | None,
    every: str | None,
    cron: str | None,
    name: str | None,
    prompt: str | None,
    instructions: str | None,
    allowed_tools: tuple[str, ...],
    disallowed_tools: tuple[str, ...],
    command: str | None,
    cwd: str | None,
    params: str | None,
    notify_on: str,
    notify_to: str | None,
    notify_context: str | None,
    start: str | None,
    end: str | None,
    overlap: str,
    timeout: int,
):
    """Add a scheduled task.

    三种任务形态，选一种：

      配方      frago schedule add my-recipe --every 10m
      命令      frago schedule add --command "df -h /" --cron "0 9 * * *"
      自然语言  frago schedule add --prompt "汇总昨天飞书消息" --cron "0 8 * * *"

    配方和命令由 frago 自己执行；自然语言任务交给 CoreAgent（设置页里绑定的连接），
    可以用 --cwd 指定它在哪个目录干活、--instructions 给它说明书、
    --allowed-tools / --disallowed-tools 限定它能做什么：

      frago schedule add --prompt "拉 Jira 最新状态，分析我的卡，发到飞书群" \\
        --cron "0 14 * * 1-5" --cwd ~/Repos/my-project --instructions jira-report.md \\
        --allowed-tools Read --allowed-tools Grep \\
        --allowed-tools 'Bash(git log:*)' --allowed-tools 'Bash(frago recipe run jira_fetch:*)' \\
        --notify-on never

    通知：默认 --notify-on change，也就是任务自己说有新鲜事才推送。
    推到哪用 --notify-to，可以是已配置的 channel、desktop、或 pa：

      frago schedule add github_star_watch --cron "0 9,21 * * *" \\
        --params '{"action":"update","no_open":true}' \\
        --notify-on change --notify-to feishu \\
        --notify-context '{"chat_id":"oc_xxx"}'
    """
    # Validate: --every and --cron are mutually exclusive, one is required
    if every and cron:
        click.echo("Error: --every and --cron are mutually exclusive. Use one or the other.")
        raise SystemExit(1)
    if not every and not cron:
        click.echo("Error: either --every or --cron is required.")
        raise SystemExit(1)

    # 三选一：形态必须明确，否则「到底谁来执行」是猜出来的
    given = [x for x in (recipe_name, command, prompt) if x]
    if not given:
        click.echo("Error: 三种任务形态选一种——RECIPE_NAME、--command、或 --prompt。")
        raise SystemExit(1)
    if len(given) > 1:
        click.echo(
            "Error: RECIPE_NAME / --command / --prompt 只能给一个。\n"
            "  配方和命令由 frago 直接执行，自然语言任务交给 CoreAgent，三者执行者不同，混着给无法判定。"
        )
        raise SystemExit(1)

    if (instructions or allowed_tools or disallowed_tools) and not prompt:
        click.echo(
            "Error: --instructions / --allowed-tools / --disallowed-tools 只对 --prompt 型任务有意义。"
        )
        raise SystemExit(1)

    if cwd:
        # 到点才发现目录不存在，任务就只会在执行记录里失败一次又一次。建的时候就拦。
        from pathlib import Path

        cwd = str(Path(cwd).expanduser())
        if not Path(cwd).is_dir():
            click.echo(f"Error: --cwd 不是一个存在的目录：{cwd}")
            raise SystemExit(1)

    parsed_notify_context = {}
    if notify_context:
        try:
            parsed_notify_context = json.loads(notify_context)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid --notify-context JSON: {e}")
            raise SystemExit(1) from e

    if notify_on != "never" and not notify_to:
        click.echo(
            "Error: --notify-on 不是 never 时必须给 --notify-to，否则通知无处可去。\n"
            "  可选：已配置的 channel（frago channel list）、desktop（本机系统通知）、pa（投给常驻 agent）。\n"
            "  确实不想要通知就写 --notify-on never。"
        )
        raise SystemExit(1)

    if notify_to and notify_to not in ("desktop", "pa"):
        from frago.server.services.schedule_executor import _resolve_channel_names

        known = _resolve_channel_names()
        if notify_to not in known:
            click.echo(
                f"Error: 通知落点 '{notify_to}' 不认识。\n"
                f"  已配置的 channel：{', '.join(known) or '（一个都没有，用 frago channel add 加）'}\n"
                f"  或者用 desktop / pa。"
            )
            raise SystemExit(1)

    interval = None
    if every:
        try:
            interval = _parse_interval(every)
        except (ValueError, IndexError) as e:
            click.echo(f"Invalid interval: {every}. Use format like 30s, 10m, 2h")
            raise SystemExit(1) from e

    if cron:
        try:
            from croniter import croniter
            croniter(cron)  # validate expression
        except (ValueError, KeyError) as e:
            click.echo(f"Invalid cron expression: {e}")
            raise SystemExit(1) from e

    parsed_params = None
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid params JSON: {e}")
            raise SystemExit(1) from e

    # Verify recipe exists (if provided)
    if recipe_name:
        from frago.recipes.exceptions import RecipeError
        from frago.recipes.registry import get_registry

        registry = get_registry()
        try:
            registry.find(recipe_name)
        except RecipeError as e:
            click.echo(f"Recipe not found: {recipe_name}")
            raise SystemExit(1) from e

    service = SchedulerService.get_instance()
    schedule = service.add_schedule(
        recipe_name=recipe_name,
        interval_seconds=interval,
        params=parsed_params,
        start_at=start,
        end_at=end,
        name=name,
        prompt=prompt,
        cron=cron,
        overlap=overlap,
        timeout=timeout,
        command=command,
        cwd=cwd,
        notify={"on": notify_on, "to": notify_to, "context": parsed_notify_context},
        instructions=instructions,
        allowed_tools=list(allowed_tools),
        disallowed_tools=list(disallowed_tools),
    )

    executor = {
        "recipe": "frago 直接执行",
        "command": "frago 直接执行",
        "prompt": "交给 CoreAgent",
    }[schedule["kind"]]

    click.echo(f"Schedule created: {schedule['id']}")
    click.echo(f"  Name: {schedule['name']}")
    click.echo(f"  Kind: {schedule['kind']}（{executor}）")
    if recipe_name:
        click.echo(f"  Recipe: {recipe_name}")
    if command:
        click.echo(f"  Command: {command}")
    if prompt:
        click.echo(f"  Prompt: {prompt}")
    if instructions:
        click.echo(f"  Instructions: ~/.frago/coreagent/{instructions}")
    if cwd:
        click.echo(f"  Cwd: {cwd}")
    if allowed_tools:
        click.echo(f"  Allowed tools: {', '.join(allowed_tools)}")
    if disallowed_tools:
        click.echo(f"  Disallowed tools: {', '.join(disallowed_tools)}")
    if notify_on == "never":
        click.echo("  Notify: 关闭")
    else:
        click.echo(f"  Notify: {notify_on} → {notify_to}")
    if every:
        click.echo(f"  Interval: {every} ({interval}s)")
    if cron:
        click.echo(f"  Cron: {cron}")
    click.echo(f"  Overlap: {overlap}")
    if start:
        click.echo(f"  Start: {start}")
    if end:
        click.echo(f"  End: {end}")
    click.echo("\nSchedule will be active when the frago server is running.")


@schedule_group.command(name="list", cls=AgentFriendlyCommand)
def schedule_list():
    """List all scheduled tasks."""
    service = SchedulerService.get_instance()
    schedules = service.list_schedules()

    if not schedules:
        click.echo("No schedules configured.")
        return

    # Header
    click.echo(
        f"{'ID':<16} {'Enabled':<8} {'Kind':<9} {'Name':<22} {'Schedule':<15} "
        f"{'Runs':<6} {'Last Status':<12} {'Notify':<16} {'Next Run'}"
    )
    click.echo("-" * 140)

    for s in schedules:
        # Schedule expression
        cron_expr = s.get("cron")
        interval = s.get("interval_seconds")
        if cron_expr:
            schedule_str = cron_expr
        elif interval:
            if interval >= 3600:
                schedule_str = f"every {interval // 3600}h"
            elif interval >= 60:
                schedule_str = f"every {interval // 60}m"
            else:
                schedule_str = f"every {interval}s"
        else:
            schedule_str = "—"

        enabled = "✓" if s.get("enabled", True) else "✗"
        schedule_name = s.get("name", s.get("recipe_name", "—"))
        last_status = s.get("last_status", "—") or "—"
        run_count = s.get("run_count", 0)

        # Calculate next run
        next_run_dt = service._next_run_at(s)
        next_run = next_run_dt.strftime("%Y-%m-%d %H:%M:%S") if next_run_dt else "—"
        if not s.get("enabled", True):
            next_run = "(disabled)"

        kind = s.get("kind") or ("recipe" if s.get("recipe") else "prompt")
        nf = s.get("notify") or {}
        notify_str = "—" if nf.get("on") in (None, "never") else f"{nf.get('on')}→{nf.get('to')}"

        click.echo(
            f"{s['id']:<16} {enabled:<8} {kind:<9} {schedule_name:<22} {schedule_str:<15} "
            f"{run_count:<6} {last_status:<12} {notify_str:<16} {next_run}"
        )


@schedule_group.command(name="remove", cls=AgentFriendlyCommand)
@click.argument("schedule_id")
def schedule_remove(schedule_id: str):
    """Remove a schedule by ID."""
    service = SchedulerService.get_instance()
    if service.remove_schedule(schedule_id):
        click.echo(f"Schedule {schedule_id} removed.")
    else:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)


@schedule_group.command(name="toggle", cls=AgentFriendlyCommand)
@click.argument("schedule_id")
def schedule_toggle(schedule_id: str):
    """Enable or disable a schedule."""
    service = SchedulerService.get_instance()
    result = service.toggle_schedule(schedule_id)
    if result is None:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)
    state = "enabled" if result else "disabled"
    click.echo(f"Schedule {schedule_id} is now {state}.")


@schedule_group.command(name="history", cls=AgentFriendlyCommand)
@click.argument("schedule_id")
def schedule_history(schedule_id: str):
    """Show execution history for a schedule."""
    service = SchedulerService.get_instance()
    schedules = service.list_schedules()

    target = None
    for s in schedules:
        if s["id"] == schedule_id:
            target = s
            break

    if not target:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)

    history = target.get("history", [])
    if not history:
        click.echo(f"No execution history for {schedule_id}.")
        return

    click.echo(f"Execution history for {schedule_id} ({target.get('name', '')}):")
    click.echo(f"{'#':<4} {'Triggered At':<22} {'Status':<14} {'Task ID'}")
    click.echo("-" * 70)

    for i, entry in enumerate(reversed(history), 1):
        # `or`, not a `get` default: a manually triggered run records the key
        # with a null value rather than leaving it out, and a default only fires
        # on a missing key. The whole listing died formatting that None — so the
        # one place that answers "did this check actually run" was unreadable
        # exactly for the runs somebody had gone and triggered by hand.
        triggered = entry.get("triggered_at") or "—"
        if triggered != "—":
            triggered = triggered[:19]
        status = entry.get("status") or "—"
        task_id = entry.get("task_id") or "—"
        click.echo(f"{i:<4} {triggered:<22} {status:<14} {task_id}")


@schedule_group.command(name="run", cls=AgentFriendlyCommand)
@click.argument("schedule_id")
def schedule_run(schedule_id: str):
    """Manually trigger a schedule once (does not affect regular schedule cycle)."""
    import asyncio

    service = SchedulerService.get_instance()
    schedules = service.list_schedules()

    target = None
    for s in schedules:
        if s["id"] == schedule_id:
            target = s
            break

    if not target:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)

    kind = target.get("kind") or ("recipe" if target.get("recipe") else "prompt")

    click.echo(f"Triggering schedule {schedule_id} ({target.get('name', '')}) — {kind}...")
    asyncio.run(service._execute_native(target))

    # 重新读盘拿这一轮的结果，别拿内存里那份旧的报给人看
    for s in service.list_schedules():
        if s["id"] != schedule_id:
            continue
        last = (s.get("history") or [])[-1] if s.get("history") else {}
        click.echo(f"  Status: {last.get('status', '?')}  ({last.get('duration_ms', 0)}ms)")
        if last.get("error"):
            click.echo(f"  Error: {last['error']}")
        if last.get("notified"):
            click.echo(f"  Notified: {last.get('notify_status')}（{last.get('notify_reason')}）")
        else:
            click.echo(f"  未通知：{last.get('notify_reason', '—')}")
        break
