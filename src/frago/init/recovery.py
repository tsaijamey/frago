"""
中断恢复模块

提供 Ctrl+C 优雅中断处理和状态恢复功能：
- GracefulInterruptHandler: 信号处理器
- 临时状态保存/加载/删除
- 恢复提示
"""

import json
import os
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import click

from frago.init.models import TemporaryState


# 临时状态过期时间（天）
TEMP_STATE_EXPIRY_DAYS = 7


def get_temp_state_path() -> Path:
    """
    获取临时状态文件路径

    Returns:
        临时状态文件路径 (~/.frago/.init_state.json)
    """
    return Path.home() / ".frago" / ".init_state.json"


def load_temp_state() -> Optional[TemporaryState]:
    """
    加载临时状态

    Returns:
        TemporaryState 对象，如果不存在或已过期则返回 None
    """
    state_file = get_temp_state_path()

    if not state_file.exists():
        return None

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 处理 datetime
        if "interrupted_at" in data and isinstance(data["interrupted_at"], str):
            data["interrupted_at"] = datetime.fromisoformat(data["interrupted_at"])

        state = TemporaryState(**data)

        # 检查是否过期
        if state.is_expired(days=TEMP_STATE_EXPIRY_DAYS):
            delete_temp_state()
            return None

        return state

    except (json.JSONDecodeError, TypeError, ValueError):
        # 状态文件损坏，删除
        delete_temp_state()
        return None


def save_temp_state(state: TemporaryState) -> None:
    """
    保存临时状态

    Args:
        state: TemporaryState 对象
    """
    state_file = get_temp_state_path()

    # 确保目录存在
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # 序列化
    data = {
        "completed_steps": state.completed_steps,
        "current_step": state.current_step,
        "interrupted_at": state.interrupted_at.isoformat(),
        "recoverable": state.recoverable,
    }

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def delete_temp_state() -> bool:
    """
    删除临时状态文件

    Returns:
        True 如果成功删除或文件不存在
    """
    state_file = get_temp_state_path()

    try:
        if state_file.exists():
            state_file.unlink()
        return True
    except OSError:
        return False


def prompt_resume(state: TemporaryState) -> bool:
    """
    询问用户是否恢复上次中断的安装

    Args:
        state: TemporaryState 对象

    Returns:
        True 如果用户选择恢复
    """
    click.echo("\n⚠️  检测到上次安装被中断")
    click.echo(f"   中断时间: {state.interrupted_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if state.current_step:
        click.echo(f"   中断步骤: {state.current_step}")

    # 显示已完成的步骤
    if state.completed_steps:
        click.echo("\n   已完成的步骤:")
        for step in state.completed_steps:
            click.echo(f"     ✅ {step}")

    click.echo()
    return click.confirm("是否从上次中断处继续?", default=True)


def format_resume_summary(state: TemporaryState) -> str:
    """
    格式化恢复摘要

    Args:
        state: TemporaryState 对象

    Returns:
        格式化的摘要字符串
    """
    lines = ["恢复信息:"]

    completed = len(state.completed_steps)
    if completed:
        lines.append(f"  已完成: {completed} 步")
    if state.current_step:
        lines.append(f"  当前步骤: {state.current_step}")

    return "\n".join(lines)


class GracefulInterruptHandler:
    """
    优雅中断处理器

    用于捕获 Ctrl+C 信号并执行清理操作

    Usage:
        with GracefulInterruptHandler() as handler:
            # 长时间运行的操作
            if handler.interrupted:
                break
    """

    def __init__(self, on_interrupt: Optional[Callable[[], None]] = None):
        """
        初始化中断处理器

        Args:
            on_interrupt: 中断时执行的回调函数
        """
        self.interrupted = False
        self.on_interrupt = on_interrupt
        self._original_handler = None

    def __enter__(self):
        self._original_handler = signal.signal(signal.SIGINT, self._handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.signal(signal.SIGINT, self._original_handler)
        return False

    def _handler(self, signum, frame):
        """信号处理函数"""
        self.interrupted = True
        if self.on_interrupt:
            self.on_interrupt()

        click.echo("\n\n⚠️  收到中断信号，正在保存状态...")


def create_initial_state() -> TemporaryState:
    """
    创建初始临时状态

    Returns:
        TemporaryState 对象
    """
    return TemporaryState(
        completed_steps=[],
        current_step=None,
        interrupted_at=datetime.now(),
        recoverable=True,
    )


def mark_step_completed(state: TemporaryState, step_name: str) -> None:
    """
    标记步骤为已完成

    Args:
        state: TemporaryState 对象
        step_name: 步骤名称
    """
    state.add_step(step_name)


def set_current_step(state: TemporaryState, step_name: str) -> None:
    """
    设置当前步骤

    Args:
        state: TemporaryState 对象
        step_name: 步骤名称
    """
    state.set_current_step(step_name)
