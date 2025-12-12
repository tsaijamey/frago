"""Run命令系统CLI子命令组

提供run实例管理、日志记录、截图等命令
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import click

from ..run.context import ContextManager
from ..run.discovery import RunDiscovery
from ..run.exceptions import (
    ContextAlreadySetError,
    ContextNotSetError,
    FileSystemError,
    RunException,
    RunNotFoundError,
)
from ..run.logger import RunLogger
from ..run.manager import RunManager
from ..run.models import ActionType, ExecutionMethod, InsightEntry, InsightType, LogStatus, RunStatus
from .agent_friendly import AgentFriendlyGroup


# 统一使用用户目录
FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"


def get_manager() -> RunManager:
    """获取RunManager实例"""
    return RunManager(PROJECTS_DIR)


def get_context_manager() -> ContextManager:
    """获取ContextManager实例"""
    return ContextManager(FRAGO_HOME, PROJECTS_DIR)


def format_timestamp(dt: datetime) -> str:
    """格式化时间戳为ISO 8601格式（带Z后缀）"""
    return dt.isoformat().replace("+00:00", "Z")


def output_json(data: Dict[str, Any]) -> None:
    """输出JSON格式数据"""
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def get_extra_metadata(instance: Any) -> Dict[str, Any]:
    """获取额外元数据字段（排除核心字段）"""
    core_fields = {"run_id", "theme_description", "created_at", "last_accessed", "status"}

    # 获取实例的所有字段
    instance_dict = instance.model_dump()

    # 过滤出额外字段
    extra_metadata = {}
    for key, value in instance_dict.items():
        if key not in core_fields:
            extra_metadata[key] = value

    return extra_metadata


def format_extra_metadata(extra_metadata: Dict[str, Any], indent: str = "  ") -> str:
    """格式化额外元数据为可读字符串"""
    if not extra_metadata:
        return ""

    lines = [f"\nExtra Metadata:"]
    for key, value in sorted(extra_metadata.items()):
        if isinstance(value, dict):
            lines.append(f"{indent}- {key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"{indent}  {sub_key}: {json.dumps(sub_value, ensure_ascii=False)}")
        elif isinstance(value, list):
            lines.append(f"{indent}- {key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{indent}- {key}: {value}")

    return "\n".join(lines)


def handle_error(e: Exception, exit_code: int = 1) -> None:
    """统一错误处理"""
    click.echo(f"Error: {e}", err=True)
    sys.exit(exit_code)


@click.group(name="run", cls=AgentFriendlyGroup)
def run_group():
    """Run命令系统 - 管理AI主持的任务执行

    \b
    核心概念:
    - Run实例: 主题型的信息中心，持久化存储任务执行历史
    - 上下文: 当前工作的run实例（通过 set-context 设置）
    - 日志: JSONL格式的结构化执行记录

    \b
    典型工作流:
    1. 创建run: frago run init "任务描述"
    2. 设置上下文: frago run set-context <run_id>
    3. 记录日志: frago run log --step "..." --status "success" ...
    4. 查看进度: frago run info <run_id>
    5. 归档: frago run archive <run_id>
    """
    pass


@run_group.command()
@click.argument("description")
@click.option(
    "--run-id",
    help="自定义run ID（默认自动生成）",
)
def init(description: str, run_id: Optional[str]):
    """初始化新run实例

    \b
    示例:
        frago run init "在Upwork上搜索Python职位"
        frago run init "测试任务" --run-id custom-id
    """
    try:
        manager = get_manager()
        instance = manager.create_run(description, run_id)

        output_json({
            "run_id": instance.run_id,
            "created_at": format_timestamp(instance.created_at),
            "path": str(PROJECTS_DIR / instance.run_id),
        })
    except RunException as e:
        handle_error(e)


@run_group.command()
@click.argument("run_id")
def set_context(run_id: str):
    """设置当前工作run

    \b
    注意: 系统仅允许一个活跃的run上下文。如需切换，先用 release 释放。

    \b
    示例:
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


@run_group.command()
def release():
    """释放当前run上下文（互斥锁）

    \b
    用于在任务完成后或切换任务前释放当前活跃的上下文。

    \b
    示例:
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


@run_group.command()
@click.option(
    "--format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="输出格式",
)
@click.option(
    "--status",
    type=click.Choice(["all", "active", "archived"]),
    default="all",
    help="过滤状态",
)
def list(format: str, status: str):
    """列出所有run实例

    \b
    示例:
        frago run list
        frago run list --format json --status active
    """
    try:
        manager = get_manager()

        # 状态过滤
        status_filter = None
        if status == "active":
            status_filter = RunStatus.ACTIVE
        elif status == "archived":
            status_filter = RunStatus.ARCHIVED

        runs = manager.list_runs(status=status_filter)

        if format == "json":
            output_json({"runs": runs, "total": len(runs)})
        else:
            # 表格格式
            if not runs:
                click.echo("No run instances found.")
                return

            # 表头
            click.echo(
                f"{'RUN_ID':<40} {'STATUS':<10} {'CREATED_AT':<20} {'LAST_ACCESSED':<20}"
            )
            click.echo("-" * 90)

            # 数据行
            for run in runs:
                created = run["created_at"][:19].replace("T", " ")
                accessed = run["last_accessed"][:19].replace("T", " ")
                click.echo(
                    f"{run['run_id']:<40} {run['status']:<10} {created:<20} {accessed:<20}"
                )

    except RunException as e:
        handle_error(e)


@run_group.command()
@click.argument("run_id")
@click.option(
    "--format",
    type=click.Choice(["human", "json"]),
    default="human",
    help="输出格式",
)
def info(run_id: str, format: str):
    """显示run实例详情

    \b
    示例:
        frago run info find-job-on-upwork
        frago run info find-job-on-upwork --format json
    """
    try:
        manager = get_manager()
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
            # 人类可读格式
            click.echo(f"\nRun ID: {instance.run_id}")
            click.echo(f"Status: {instance.status.value}")
            click.echo(f"Theme: {instance.theme_description}")
            click.echo(
                f"Created: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            click.echo(
                f"Last Accessed: {instance.last_accessed.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            click.echo(f"\nStatistics:")
            click.echo(f"- Log Entries: {stats['log_entries']}")
            click.echo(f"- Screenshots: {stats['screenshots']}")
            click.echo(f"- Scripts: {stats['scripts']}")
            click.echo(f"- Disk Usage: {stats['disk_usage_bytes'] / 1024:.1f} KB")

            # 显示额外元数据
            extra_metadata = get_extra_metadata(instance)
            if extra_metadata:
                click.echo(format_extra_metadata(extra_metadata))

            if recent_logs:
                click.echo(f"\nRecent Logs (last 5):")
                for log in recent_logs:
                    status_icon = "✓" if log.status == LogStatus.SUCCESS else "✗"
                    timestamp = log.timestamp.strftime("%Y-%m-%d %H:%M")
                    click.echo(
                        f"  [{timestamp}] {status_icon} {log.step} "
                        f"({log.action_type.value}/{log.execution_method.value})"
                    )

    except RunException as e:
        handle_error(e)


@run_group.command()
@click.argument("run_id")
def archive(run_id: str):
    """归档run实例

    \b
    示例:
        frago run archive find-job-on-upwork
    """
    try:
        manager = get_manager()
        instance = manager.archive_run(run_id)

        # 如果是当前上下文的run，清空上下文
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


@run_group.command()
@click.option("--step", required=True, help="步骤描述")
@click.option(
    "--status",
    type=click.Choice(["success", "error", "warning"]),
    required=True,
    help="执行状态",
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
    help="操作类型",
)
@click.option(
    "--execution-method",
    type=click.Choice(["command", "recipe", "file", "manual", "analysis", "tool"]),
    required=True,
    help="执行方法",
)
@click.option("--data", required=True, help="JSON格式的详细数据")
@click.option(
    "--insight",
    multiple=True,
    help="关键发现/坑点，格式：'type:summary' 或 JSON。type可选：key_factor, pitfall, lesson, workaround",
)
def log(step: str, status: str, action_type: str, execution_method: str, data: str, insight: tuple):
    """记录结构化日志

    \b
    示例:
        frago run log \\
          --step "导航到搜索页" \\
          --status "success" \\
          --action-type "navigation" \\
          --execution-method "command" \\
          --data '{"command": "frago chrome navigate https://upwork.com"}'

    \b
    带 insight 示例:
        frago run log \\
          --step "提取职位列表" \\
          --status "error" \\
          --action-type "extraction" \\
          --execution-method "command" \\
          --data '{"error": "选择器失效"}' \\
          --insight "pitfall:动态class导致选择器失效，需用data-testid"

    \b
    JSON格式 insight:
        --insight '{"insight_type": "key_factor", "summary": "必须等待页面加载", "detail": "加载动画消失后才能提取"}'
    """
    try:
        # 获取当前上下文
        context_mgr = get_context_manager()
        context = context_mgr.get_current_run()

        # 解析data
        try:
            data_dict = json.loads(data)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON in --data: {e}", err=True)
            sys.exit(2)

        # 解析insights
        insights_list = None
        if insight:
            insights_list = []
            for i in insight:
                try:
                    # 尝试解析JSON格式
                    if i.strip().startswith("{"):
                        insight_data = json.loads(i)
                        insights_list.append(InsightEntry.from_dict(insight_data))
                    else:
                        # 简写格式: "type:summary"
                        if ":" not in i:
                            click.echo(f"Error: Invalid insight format '{i}'. Use 'type:summary' or JSON.", err=True)
                            sys.exit(2)
                        insight_type, summary = i.split(":", 1)
                        insight_type = insight_type.strip().lower()
                        if insight_type not in ["key_factor", "pitfall", "lesson", "workaround"]:
                            click.echo(f"Error: Unknown insight type '{insight_type}'. Use: key_factor, pitfall, lesson, workaround", err=True)
                            sys.exit(2)
                        insights_list.append(InsightEntry(
                            insight_type=InsightType(insight_type),
                            summary=summary.strip(),
                        ))
                except json.JSONDecodeError as e:
                    click.echo(f"Error: Invalid JSON in --insight: {e}", err=True)
                    sys.exit(2)

        # 写入日志
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


@run_group.command()
@click.argument("description")
def screenshot(description: str):
    """保存截图（自动编号）

    \b
    示例:
        frago run screenshot "搜索结果页面"
    """
    try:
        # 获取当前上下文
        context_mgr = get_context_manager()
        context = context_mgr.get_current_run()

        run_dir = PROJECTS_DIR / context.run_id
        screenshots_dir = run_dir / "screenshots"

        # 导入screenshot模块（稍后实现）
        from ..run.screenshot import capture_screenshot

        file_path, sequence_number = capture_screenshot(description, screenshots_dir)

        # 自动记录日志
        logger = RunLogger(run_dir)
        logger.write_log(
            step=f"截图: {description}",
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
