"""
格式化模块

提供标准化的消息格式化功能：
- 错误消息格式化
- 成功消息格式化
- 依赖状态格式化
- 进度提示
"""

from typing import Dict, Optional

import click

from frago.init.models import DependencyCheckResult


# 颜色常量
class Colors:
    """ANSI 颜色"""
    SUCCESS = "green"
    ERROR = "red"
    WARNING = "yellow"
    INFO = "blue"
    MUTED = "bright_black"


def format_error_message(
    title: str,
    details: Optional[str] = None,
    suggestion: Optional[str] = None,
) -> str:
    """
    格式化错误消息

    Args:
        title: 错误标题
        details: 错误详情（可选）
        suggestion: 解决建议（可选）

    Returns:
        格式化的错误消息字符串
    """
    lines = [f"❌ {title}"]

    if details:
        lines.append("")
        for line in details.split("\n"):
            lines.append(f"   {line}")

    if suggestion:
        lines.append("")
        lines.append(f"💡 建议: {suggestion}")

    return "\n".join(lines)


def format_success_message(
    title: str,
    details: Optional[str] = None,
) -> str:
    """
    格式化成功消息

    Args:
        title: 成功标题
        details: 详情（可选）

    Returns:
        格式化的成功消息字符串
    """
    lines = [f"✅ {title}"]

    if details:
        lines.append(f"   {details}")

    return "\n".join(lines)


def format_warning_message(
    title: str,
    details: Optional[str] = None,
) -> str:
    """
    格式化警告消息

    Args:
        title: 警告标题
        details: 详情（可选）

    Returns:
        格式化的警告消息字符串
    """
    lines = [f"⚠️  {title}"]

    if details:
        lines.append(f"   {details}")

    return "\n".join(lines)


def format_info_message(title: str) -> str:
    """
    格式化信息消息

    Args:
        title: 信息标题

    Returns:
        格式化的信息消息字符串
    """
    return f"ℹ️  {title}"


def format_dependency_status(results: Dict[str, DependencyCheckResult]) -> str:
    """
    格式化依赖检查状态

    Args:
        results: 依赖检查结果字典

    Returns:
        格式化的状态字符串
    """
    lines = ["依赖检查结果:", ""]

    for name, result in results.items():
        if result.installed:
            status = "✅"
            version_info = f"v{result.version}" if result.version else "已安装"
        else:
            status = "❌"
            version_info = "未安装"

        display_name = format_dependency_name(name)
        lines.append(f"  {status} {display_name}: {version_info}")

        # 显示版本不满足要求警告
        if result.installed and not result.version_sufficient:
            lines.append(f"     ⚠️  版本不满足要求: 需要 >= {result.required_version}")

    return "\n".join(lines)


def format_dependency_name(name: str) -> str:
    """
    格式化依赖名称显示

    Args:
        name: 依赖内部名称

    Returns:
        用户友好的显示名称
    """
    name_map = {
        "node": "Node.js",
        "claude-code": "Claude Code",
        "ccr": "Claude Code Router",
    }
    return name_map.get(name, name)


def format_progress(current: int, total: int, message: str) -> str:
    """
    格式化进度信息

    Args:
        current: 当前步骤
        total: 总步骤数
        message: 进度消息

    Returns:
        格式化的进度字符串
    """
    return f"[{current}/{total}] {message}"


def format_step_start(step_name: str) -> str:
    """
    格式化步骤开始消息

    Args:
        step_name: 步骤名称

    Returns:
        格式化的消息
    """
    return f"📦 正在{step_name}..."


def format_step_complete(step_name: str) -> str:
    """
    格式化步骤完成消息

    Args:
        step_name: 步骤名称

    Returns:
        格式化的消息
    """
    return f"✅ {step_name}完成"


def format_step_failed(step_name: str, error: Optional[str] = None) -> str:
    """
    格式化步骤失败消息

    Args:
        step_name: 步骤名称
        error: 错误信息（可选）

    Returns:
        格式化的消息
    """
    msg = f"❌ {step_name}失败"
    if error:
        msg += f"\n   {error}"
    return msg


def echo_error(title: str, details: Optional[str] = None, suggestion: Optional[str] = None) -> None:
    """
    输出错误消息（带颜色）

    Args:
        title: 错误标题
        details: 错误详情
        suggestion: 解决建议
    """
    click.secho(format_error_message(title, details, suggestion), fg=Colors.ERROR)


def echo_success(title: str, details: Optional[str] = None) -> None:
    """
    输出成功消息（带颜色）

    Args:
        title: 成功标题
        details: 详情
    """
    click.secho(format_success_message(title, details), fg=Colors.SUCCESS)


def echo_warning(title: str, details: Optional[str] = None) -> None:
    """
    输出警告消息（带颜色）

    Args:
        title: 警告标题
        details: 详情
    """
    click.secho(format_warning_message(title, details), fg=Colors.WARNING)


def echo_info(title: str) -> None:
    """
    输出信息消息（带颜色）

    Args:
        title: 信息标题
    """
    click.secho(format_info_message(title), fg=Colors.INFO)
