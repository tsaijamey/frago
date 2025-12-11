#!/usr/bin/env python3
"""
Frago Session Commands - 会话管理命令组

提供会话数据的查询、查看和管理功能：
- session list: 列出最近的会话
- session show: 查看会话详情
- session watch: 实时监控会话
- session clean: 清理过期会话
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
    会话管理命令组

    查看、监控和管理 Agent 执行会话。
    """
    pass


@session_group.command("list")
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline", "all"]),
    default="all",
    help="筛选 Agent 类型"
)
@click.option(
    "--status", "-s",
    type=click.Choice(["running", "completed", "error", "all"]),
    default="all",
    help="筛选会话状态"
)
@click.option(
    "--limit", "-n",
    type=int,
    default=10,
    help="显示数量限制"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="以 JSON 格式输出"
)
def list_cmd(
    agent_type: str,
    status: str,
    limit: int,
    json_output: bool
):
    """
    列出最近的会话

    \b
    示例:
      frago session list
      frago session list --agent-type claude
      frago session list --status running
      frago session list --limit 20 --json
    """
    # 转换参数
    agent_type_filter = None
    if agent_type != "all":
        agent_type_filter = AgentType(agent_type)

    status_filter = None
    if status != "all":
        status_filter = SessionStatus(status)

    # 查询会话
    sessions = list_sessions(
        agent_type=agent_type_filter,
        limit=limit,
        status=status_filter,
    )

    if json_output:
        # JSON 输出
        data = [s.model_dump(mode="json") for s in sessions]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # 表格输出
    if not sessions:
        click.echo("没有找到会话记录")
        return

    click.echo(f"{'会话 ID':<12} {'类型':<8} {'状态':<10} {'步骤':<6} {'工具':<6} {'最后活动':<20}")
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
    """获取状态的显示文本"""
    status_map = {
        SessionStatus.RUNNING: "🟢 运行中",
        SessionStatus.COMPLETED: "✅ 完成",
        SessionStatus.ERROR: "❌ 错误",
        SessionStatus.CANCELLED: "⚪ 取消",
    }
    return status_map.get(status, status.value)


@session_group.command("show")
@click.argument("session_id")
@click.option(
    "--steps", "-s",
    is_flag=True,
    help="显示步骤历史"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="以 JSON 格式输出"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline"]),
    default="claude",
    help="Agent 类型"
)
def show_cmd(
    session_id: str,
    steps: bool,
    json_output: bool,
    agent_type: str
):
    """
    查看会话详情

    支持使用完整 ID 或前缀匹配。

    \b
    示例:
      frago session show 48c10a46
      frago session show 48c10a46 --steps
      frago session show 48c10a46 --json
    """
    agent = AgentType(agent_type)

    # 支持前缀匹配
    session = _find_session_by_prefix(session_id, agent)
    if not session:
        click.echo(f"未找到会话: {session_id}", err=True)
        sys.exit(1)

    if json_output:
        # JSON 输出
        data = get_session_data(session.session_id, agent)
        if data:
            # 转换为可序列化格式
            output = {
                "metadata": data["metadata"].model_dump(mode="json"),
                "steps": [s.model_dump(mode="json") for s in data["steps"]],
                "summary": data["summary"].model_dump(mode="json") if data["summary"] else None,
            }
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 详情输出
    click.echo("=" * 60)
    click.echo(f"会话 ID: {session.session_id}")
    click.echo("=" * 60)

    click.echo(f"\n📋 基本信息")
    click.echo(f"  Agent 类型: {session.agent_type.value}")
    click.echo(f"  项目路径: {session.project_path}")
    click.echo(f"  状态: {_get_status_display(session.status)}")

    click.echo(f"\n⏱️ 时间信息")
    click.echo(f"  开始时间: {session.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if session.ended_at:
        click.echo(f"  结束时间: {session.ended_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"  最后活动: {session.last_activity.strftime('%Y-%m-%d %H:%M:%S')}")

    click.echo(f"\n📊 统计信息")
    click.echo(f"  总步骤数: {session.step_count}")
    click.echo(f"  工具调用: {session.tool_call_count}")

    # 显示摘要
    summary = read_summary(session.session_id, agent)
    if summary:
        click.echo(f"\n📈 会话摘要")
        click.echo(f"  总耗时: {format_duration(summary.total_duration_ms)}")
        click.echo(f"  用户消息: {summary.user_message_count}")
        click.echo(f"  助手消息: {summary.assistant_message_count}")
        click.echo(f"  工具成功: {summary.tool_success_count}")
        click.echo(f"  工具失败: {summary.tool_error_count}")
        if summary.most_used_tools:
            tools = ", ".join(f"{t.tool_name}({t.count})" for t in summary.most_used_tools[:5])
            click.echo(f"  常用工具: {tools}")
        if summary.model:
            click.echo(f"  使用模型: {summary.model}")

    # 显示步骤历史
    if steps:
        step_list = read_steps(session.session_id, agent)
        if step_list:
            click.echo(f"\n📜 步骤历史 ({len(step_list)} 条)")
            click.echo("-" * 60)
            for step in step_list:
                icon = get_step_icon(step.type)
                label = get_step_label(step.type)
                ts = step.timestamp.strftime("%H:%M:%S")
                click.echo(f"  [{ts}] {icon} {label}: {step.content_summary}")


def _find_session_by_prefix(prefix: str, agent_type: AgentType):
    """通过前缀查找会话"""
    # 先尝试精确匹配
    session = read_metadata(prefix, agent_type)
    if session:
        return session

    # 尝试前缀匹配
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
    help="以 JSON 格式输出"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline"]),
    default="claude",
    help="Agent 类型"
)
def watch_cmd(
    session_id: Optional[str],
    json_output: bool,
    agent_type: str
):
    """
    实时监控会话

    如果不指定 session_id，则监控最新的活跃会话。

    \b
    示例:
      frago session watch              # 监控最新活跃会话
      frago session watch 48c10a46     # 监控指定会话
      frago session watch --json       # JSON 格式输出
    """
    from frago.session.monitor import watch_latest_session, watch_session

    agent = AgentType(agent_type)

    if session_id:
        # 监控指定会话
        session = _find_session_by_prefix(session_id, agent)
        if not session:
            click.echo(f"未找到会话: {session_id}", err=True)
            sys.exit(1)

        click.echo(f"监控会话: {session.session_id[:8]}...")
        watch_session(session.session_id, agent, json_output)
    else:
        # 监控最新活跃会话
        watch_latest_session(agent, json_output)


@session_group.command("clean")
@click.option(
    "--days", "-d",
    type=int,
    default=30,
    help="清理多少天前的会话"
)
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline", "all"]),
    default="all",
    help="筛选 Agent 类型"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅显示将要删除的会话，不实际删除"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="跳过确认提示"
)
def clean_cmd(
    days: int,
    agent_type: str,
    dry_run: bool,
    force: bool
):
    """
    清理过期会话

    删除指定天数之前的会话数据。

    \b
    示例:
      frago session clean              # 清理 30 天前的会话
      frago session clean --days 7     # 清理 7 天前的会话
      frago session clean --dry-run    # 预览将要删除的会话
    """
    from datetime import timedelta

    agent_filter = None
    if agent_type != "all":
        agent_filter = AgentType(agent_type)

    # 查找过期会话
    cutoff = datetime.now() - timedelta(days=days)
    sessions = list_sessions(agent_type=agent_filter, limit=1000)
    old_sessions = [s for s in sessions if s.last_activity < cutoff]

    if not old_sessions:
        click.echo(f"没有找到 {days} 天前的会话")
        return

    click.echo(f"找到 {len(old_sessions)} 个过期会话（{days} 天前）")

    if dry_run:
        click.echo("\n[Dry Run] 将要删除的会话:")
        for s in old_sessions[:20]:  # 最多显示 20 个
            click.echo(f"  - {s.session_id[:8]}... ({s.last_activity.strftime('%Y-%m-%d')})")
        if len(old_sessions) > 20:
            click.echo(f"  ... 还有 {len(old_sessions) - 20} 个")
        return

    if not force:
        if not click.confirm(f"确认删除 {len(old_sessions)} 个会话？"):
            click.echo("已取消")
            return

    # 执行删除
    cleaned = 0
    for s in old_sessions:
        if delete_session(s.session_id, s.agent_type):
            cleaned += 1

    click.echo(f"✓ 已清理 {cleaned} 个会话")


@session_group.command("delete")
@click.argument("session_id")
@click.option(
    "--agent-type", "-a",
    type=click.Choice(["claude", "cursor", "cline"]),
    default="claude",
    help="Agent 类型"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="跳过确认提示"
)
def delete_cmd(
    session_id: str,
    agent_type: str,
    force: bool
):
    """
    删除指定会话

    \b
    示例:
      frago session delete 48c10a46
      frago session delete 48c10a46 --force
    """
    agent = AgentType(agent_type)

    # 查找会话
    session = _find_session_by_prefix(session_id, agent)
    if not session:
        click.echo(f"未找到会话: {session_id}", err=True)
        sys.exit(1)

    if not force:
        click.echo(f"会话 ID: {session.session_id}")
        click.echo(f"项目: {session.project_path}")
        click.echo(f"步骤数: {session.step_count}")
        if not click.confirm("确认删除此会话？"):
            click.echo("已取消")
            return

    if delete_session(session.session_id, agent):
        click.echo(f"✓ 已删除会话: {session.session_id[:8]}...")
    else:
        click.echo("✗ 删除失败", err=True)
        sys.exit(1)


@session_group.command("sync")
@click.option(
    "--all", "sync_all",
    is_flag=True,
    help="同步所有项目（默认仅当前项目）"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="强制重新同步（包括已存在的会话）"
)
@click.option(
    "--json", "json_output",
    is_flag=True,
    help="以 JSON 格式输出"
)
def sync_cmd(
    sync_all: bool,
    force: bool,
    json_output: bool
):
    """
    从 Claude 会话文件同步数据

    将 ~/.claude/projects/ 下的会话文件同步到 ~/.frago/sessions/claude/。
    默认仅同步当前工作目录对应的项目。

    \b
    示例:
      frago session sync           # 同步当前项目
      frago session sync --all     # 同步所有项目
      frago session sync --force   # 强制重新同步
    """
    import os

    from frago.session.sync import sync_all_projects, sync_project_sessions

    if sync_all:
        click.echo("同步所有项目的会话...")
        result = sync_all_projects(force=force)
    else:
        project_path = os.getcwd()
        click.echo(f"同步项目: {project_path}")
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

    # 文本输出
    click.echo(f"\n同步完成:")
    click.echo(f"  新同步: {result.synced}")
    click.echo(f"  已更新: {result.updated}")
    click.echo(f"  已跳过: {result.skipped}")

    if result.errors:
        click.echo(f"\n⚠️ 错误 ({len(result.errors)}):")
        for err in result.errors[:5]:
            click.echo(f"  - {err}")
        if len(result.errors) > 5:
            click.echo(f"  ... 还有 {len(result.errors) - 5} 个错误")
