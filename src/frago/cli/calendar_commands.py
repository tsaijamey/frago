"""frago calendar — 每日完成事务（Completed Affairs）管理命令。

  frago calendar add            # 登记单条完成事务（同日同标题自动幂等合并更新）
  frago calendar write          # 批量结构化写入/覆写指定日期事务（支持文件、JSON字符串与标准输入）
  frago calendar list           # 查询并按日分组展示已完成事务列表
  frago calendar update <id>    # 修改单条事务详情
  frago calendar remove <id>    # 删除单条事务（支持别名 delete）

存储默认落在 ``~/.frago/data/calendar/`` 下，带原子写与文件锁保护，
并与 WebUI 顶栏「日历 · 时间轴」实现深度双向联动。
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from frago.calendar import store

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup


@click.group(name="calendar", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.pass_context
def calendar_group(ctx: click.Context) -> None:
    """Manage completed daily affairs in the calendar."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(calendar_list)


@calendar_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("title_arg", required=False, metavar="[TITLE]")
@click.option("--title", "-t", "title_opt", help="Affair title (or pass as positional argument)")
@click.option("--summary", "-s", default="", help="Business conclusion and result summary")
@click.option("--date", "-d", default=None, help="Belonging date (YYYY-MM-DD, defaults to today)")
@click.option("--category", "-c", default="未分类", help="Category name (e.g. 系统研发, 投研分析, 演示宣发)")
@click.option("--tag", "--tags", "tags", multiple=True, help="Tag(s), can pass multiple or comma-separated")
@click.option("--employee", "-e", default=None, help="Employee post ID (e.g. frago-developer, stock)")
@click.option("--session", "--sessions", "sessions", multiple=True, help="Associated session ID(s)")
@click.option("--artifact", "--artifacts", "artifacts", multiple=True, help="Associated artifact path(s)")
@click.option("--completed-at", default=None, help="Completion time (HH:MM or ISO timestamp)")
@click.option("--id", "affair_id", default=None, help="Explicit unique affair ID (optional)")
@click.option("--json", "json_out", is_flag=True, help="Output result as JSON")
def calendar_add(
    title_arg: str | None,
    title_opt: str | None,
    summary: str,
    date: str | None,
    category: str,
    tags: tuple[str, ...],
    employee: str | None,
    sessions: tuple[str, ...],
    artifacts: tuple[str, ...],
    completed_at: str | None,
    affair_id: str | None,
    json_out: bool,
) -> None:
    """Record a completed affair into the calendar (idempotent on same-date same-title)."""
    title = (title_opt or title_arg or "").strip()
    if not title:
        raise click.ClickException("Missing required option '--title' or positional title argument.")

    # 展平逗号分隔项
    flat_tags: list[str] = []
    for item in tags:
        flat_tags.extend([t.strip() for t in item.split(",") if t.strip()])

    flat_sessions: list[str] = []
    for item in sessions:
        flat_sessions.extend([s.strip() for s in item.split(",") if s.strip()])

    flat_artifacts: list[str] = []
    for item in artifacts:
        flat_artifacts.extend([a.strip() for a in item.split(",") if a.strip()])

    item = store.add_affair(
        title=title,
        date=date,
        summary=summary,
        category=category,
        tags=flat_tags,
        employee=employee,
        sessions=flat_sessions,
        artifacts=flat_artifacts,
        completed_at=completed_at,
        affair_id=affair_id,
    )

    if json_out:
        click.echo(json.dumps(item.to_dict(), ensure_ascii=False, indent=2))
        return

    click.echo(f"✓ 已记录事务 [{item.id}]")
    click.echo(f"  日期: {item.date} | 时间: {item.completed_at}")
    click.echo(f"  分类: {item.category}" + (f" | 员工: {item.employee}" if item.employee else ""))
    click.echo(f"  标题: {item.title}")
    if item.summary:
        click.echo(f"  结论: {item.summary}")
    if item.sessions:
        click.echo(f"  会话: {', '.join(item.sessions)}")
    if item.artifacts:
        click.echo(f"  归档: {', '.join(item.artifacts)}")


@calendar_group.command(name="write", cls=AgentFriendlyCommand)
@click.option("--file", "-f", "file_path", type=click.Path(exists=True), help="Path to JSON file containing affairs")
@click.option("--json", "json_str", help="JSON string of affairs array or {date, items}")
@click.option("--stdin", "from_stdin", is_flag=True, help="Read JSON from standard input")
@click.option("--date", "-d", default=None, help="Default date (YYYY-MM-DD) for items missing date")
@click.option("--mode", type=click.Choice(["upsert", "replace"]), default="upsert",
              help="Write mode: upsert (merge by id/title, default) or replace (overwrite target date)")
@click.option("--json-out", is_flag=True, help="Output results as JSON")
def calendar_write(
    file_path: str | None,
    json_str: str | None,
    from_stdin: bool,
    date: str | None,
    mode: str,
    json_out: bool,
) -> None:
    """Batch write structured affairs into the calendar (from file, string or stdin)."""
    raw_content = ""
    if file_path:
        with open(file_path, encoding="utf-8") as f:
            raw_content = f.read()
    elif json_str:
        raw_content = json_str
    elif from_stdin or not sys.stdin.isatty():
        raw_content = sys.stdin.read()
    else:
        raise click.ClickException("Provide affairs input via '--file', '--json', or '--stdin'.")

    try:
        data = json.loads(raw_content)
    except Exception as e:
        raise click.ClickException(f"Invalid JSON content: {e}") from e

    items_to_write: list[dict[str, Any]] = []
    specified_date = date

    if isinstance(data, list):
        items_to_write = data
    elif isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            items_to_write = data["items"]
            if not specified_date and "date" in data:
                specified_date = str(data["date"])
        else:
            # 单个对象包装为列表
            items_to_write = [data]
    else:
        raise click.ClickException("Expected JSON array or object with 'items' key.")

    saved = store.write_affairs(items_to_write, default_date=specified_date, mode=mode)

    if json_out:
        click.echo(json.dumps([it.to_dict() for it in saved], ensure_ascii=False, indent=2))
        return

    click.echo(f"✓ 成功写入 {len(saved)} 项事务（模式: {mode}）")
    # 按日期统计
    dates: dict[str, int] = {}
    for it in saved:
        dates[it.date] = dates.get(it.date, 0) + 1
    for d, cnt in sorted(dates.items()):
        click.echo(f"  - {d}: {cnt} 项事务")


@calendar_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--date", "-d", default=None, help="Filter by exact date (YYYY-MM-DD)")
@click.option("--month", "-m", default=None, help="Filter by month (YYYY-MM)")
@click.option("--days", "-n", type=int, default=None, help="Filter by recent N days")
@click.option("--employee", "-e", default=None, help="Filter by employee post ID")
@click.option("--category", "-c", default=None, help="Filter by category")
@click.option("--query", "-q", default=None, help="Search keyword across titles, summaries and tags")
@click.option("--json", "json_out", is_flag=True, help="Output results as JSON")
def calendar_list(
    date: str | None,
    month: str | None,
    days: int | None,
    employee: str | None,
    category: str | None,
    query: str | None,
    json_out: bool,
) -> None:
    """List completed affairs grouped by date with clear formatting."""
    items = store.list_affairs(
        date=date,
        month=month,
        days=days,
        employee=employee,
        category=category,
        query=query,
    )

    if json_out:
        click.echo(json.dumps([it.to_dict() for it in items], ensure_ascii=False, indent=2))
        return

    if not items:
        click.echo("（当前条件下无事务记录）")
        return

    # 按日期分组展示
    grouped: dict[str, list[store.CompletedAffair]] = {}
    for it in items:
        grouped.setdefault(it.date, []).append(it)

    total_count = len(items)
    days_count = len(grouped)
    click.echo(f"=== 每日完成事务清单（共 {total_count} 项 · 跨 {days_count} 天）===")

    for d, day_items in grouped.items():
        click.echo(f"\n📅 【{d}】（共 {len(day_items)} 项事务）")
        click.echo("-" * 72)
        for idx, it in enumerate(day_items, 1):
            emp_tag = f"[{it.employee}] " if it.employee else ""
            cat_tag = f"<{it.category}> " if it.category else ""
            time_str = f"({it.completed_at[-8:]}) " if len(it.completed_at) >= 8 else ""
            click.echo(f"  {idx}. {time_str}{cat_tag}{emp_tag}{it.title}")
            if it.summary:
                click.echo(f"     结论: {it.summary}")
            extra_bits = []
            if it.sessions:
                extra_bits.append(f"会话: {', '.join(it.sessions)}")
            if it.artifacts:
                extra_bits.append(f"归档: {', '.join(it.artifacts)}")
            if it.tags:
                extra_bits.append(f"标签: {', '.join(it.tags)}")
            if extra_bits:
                click.echo(f"     {' | '.join(extra_bits)}")


@calendar_group.command(name="update", cls=AgentFriendlyCommand)
@click.argument("affair_id")
@click.option("--title", "-t", default=None, help="New title")
@click.option("--summary", "-s", default=None, help="New summary")
@click.option("--date", "-d", default=None, help="Move to new date (YYYY-MM-DD)")
@click.option("--category", "-c", default=None, help="New category")
@click.option("--tag", "--tags", "tags", multiple=True, help="New tag(s)")
@click.option("--employee", "-e", default=None, help="New employee ID")
@click.option("--session", "--sessions", "sessions", multiple=True, help="New session ID(s)")
@click.option("--artifact", "--artifacts", "artifacts", multiple=True, help="New artifact path(s)")
@click.option("--completed-at", default=None, help="New completion timestamp")
@click.option("--json", "json_out", is_flag=True, help="Output result as JSON")
def calendar_update(
    affair_id: str,
    title: str | None,
    summary: str | None,
    date: str | None,
    category: str | None,
    tags: tuple[str, ...],
    employee: str | None,
    sessions: tuple[str, ...],
    artifacts: tuple[str, ...],
    completed_at: str | None,
    json_out: bool,
) -> None:
    """Update a completed affair record by ID."""
    kwargs: dict[str, Any] = {}
    if title is not None:
        kwargs["title"] = title
    if summary is not None:
        kwargs["summary"] = summary
    if date is not None:
        kwargs["date"] = date
    if category is not None:
        kwargs["category"] = category
    if tags:
        flat_tags = []
        for t in tags:
            flat_tags.extend([x.strip() for x in t.split(",") if x.strip()])
        kwargs["tags"] = flat_tags
    if employee is not None:
        kwargs["employee"] = employee
    if sessions:
        flat_sessions = []
        for s in sessions:
            flat_sessions.extend([x.strip() for x in s.split(",") if x.strip()])
        kwargs["sessions"] = flat_sessions
    if artifacts:
        flat_artifacts = []
        for a in artifacts:
            flat_artifacts.extend([x.strip() for x in a.split(",") if x.strip()])
        kwargs["artifacts"] = flat_artifacts
    if completed_at is not None:
        kwargs["completed_at"] = completed_at

    updated = store.update_affair(affair_id, **kwargs)
    if not updated:
        raise click.ClickException(f"Affair record not found: {affair_id}")

    if json_out:
        click.echo(json.dumps(updated.to_dict(), ensure_ascii=False, indent=2))
        return

    click.echo(f"✓ 已更新事务 [{updated.id}] - {updated.title}")


@calendar_group.command(name="remove", cls=AgentFriendlyCommand)
@click.argument("affair_id")
@click.option("--date", "-d", default=None, help="Date hint (YYYY-MM-DD) for faster lookup")
@click.option("--json", "json_out", is_flag=True, help="Output result as JSON")
def calendar_remove(affair_id: str, date: str | None, json_out: bool) -> None:
    """Remove a completed affair record by ID."""
    ok = store.remove_affair(affair_id, date=date)
    if not ok:
        raise click.ClickException(f"Affair record not found: {affair_id}")

    if json_out:
        click.echo(json.dumps({"ok": True, "id": affair_id}, ensure_ascii=False))
        return

    click.echo(f"✓ 已删除事务 [{affair_id}]")


# 注册别名 delete
calendar_group.add_command(calendar_remove, name="delete")
