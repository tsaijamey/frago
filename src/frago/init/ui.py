"""
UI 输出模块

提供优雅的终端输出工具,受 uv 输出风格启发:
- 实时进度更新
- 精确时间显示
- 清晰的状态指示
- 对齐的输出格式
"""

import sys
import time
from contextlib import contextmanager
from typing import Optional

import click


class Spinner:
    """简单的 spinner 动画"""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = ""):
        self.message = message
        self.frame = 0
        self.is_tty = sys.stdout.isatty()

    def step(self) -> str:
        """获取下一帧"""
        if not self.is_tty:
            return ""
        frame = self.FRAMES[self.frame % len(self.FRAMES)]
        self.frame += 1
        return frame

    def clear(self):
        """清除当前行"""
        if self.is_tty:
            click.echo("\r" + " " * 80 + "\r", nl=False)


class ProgressReporter:
    """进度报告器 - uv 风格的输出"""

    def __init__(self):
        self.start_time = time.time()
        self.is_tty = sys.stdout.isatty()

    def _elapsed_time(self) -> str:
        """获取经过的时间（毫秒）"""
        elapsed = (time.time() - self.start_time) * 1000
        if elapsed < 1000:
            return f"{int(elapsed)}ms"
        else:
            return f"{elapsed / 1000:.1f}s"

    def step(self, message: str, spinner: Optional[Spinner] = None):
        """显示进行中的步骤（会被覆盖）"""
        if not self.is_tty:
            return

        frame = spinner.step() if spinner else ""
        output = f"\r{frame} {message}" if frame else f"\r{message}"
        click.echo(output + " " * 20, nl=False)

    def success(self, message: str, detail: Optional[str] = None):
        """显示成功消息（持久化）"""
        elapsed = self._elapsed_time()
        if detail:
            click.echo(f"\r{message} in {elapsed}")
            click.secho(f"  {detail}", dim=True)
        else:
            click.echo(f"\r{message} in {elapsed}")

    def info(self, message: str):
        """显示信息（持久化）"""
        click.echo(f"\r{message}")

    def item_added(self, name: str, version: Optional[str] = None):
        """显示添加的项目（uv 风格）"""
        if version:
            click.secho(f" + {name}=={version}", fg="green")
        else:
            click.secho(f" + {name}", fg="green")

    def item_skipped(self, name: str, reason: str = "already exists"):
        """显示跳过的项目"""
        click.secho(f" ~ {name}", fg="yellow", dim=True, nl=False)
        click.secho(f" ({reason})", dim=True)

    def item_error(self, name: str, error: str):
        """显示错误的项目"""
        click.secho(f" ✗ {name}", fg="red", nl=False)
        click.secho(f" - {error}", dim=True)


@contextmanager
def spinner_context(message: str, success_message: Optional[str] = None):
    """
    Spinner 上下文管理器

    用法:
        with spinner_context("Checking dependencies", "Dependencies satisfied"):
            # 执行耗时操作
            pass
    """
    spinner = Spinner(message)
    reporter = ProgressReporter()
    start_time = time.time()

    if sys.stdout.isatty():
        # TTY 模式：显示 spinner
        reporter.step(message, spinner)
        try:
            yield reporter
            # 成功：显示最终消息
            spinner.clear()
            elapsed = int((time.time() - start_time) * 1000)
            final_msg = success_message or message
            click.echo(f"{final_msg} in {elapsed}ms")
        except Exception as e:
            # 失败：清除并重新抛出
            spinner.clear()
            raise e
    else:
        # 非 TTY 模式：直接输出
        click.echo(message)
        try:
            yield reporter
            if success_message:
                click.echo(success_message)
        except Exception:
            raise


def print_header(text: str):
    """打印段落标题"""
    click.echo()
    click.secho(text, bold=True)


def print_section(title: str):
    """打印章节标题"""
    click.echo()
    click.secho(f"━━━ {title} ━━━", fg="cyan", bold=True)
    click.echo()


def print_summary(items: list[tuple[str, str]], title: str = "Summary"):
    """
    打印摘要信息（键值对）

    Args:
        items: [(key, value), ...] 列表
        title: 摘要标题
    """
    click.echo()
    click.secho(title, bold=True)
    click.echo()

    max_key_len = max(len(k) for k, _ in items) if items else 0

    for key, value in items:
        # 对齐键值对
        padded_key = key.ljust(max_key_len)
        click.echo(f"  {padded_key}  {value}")

    click.echo()


def print_error(message: str, detail: Optional[str] = None):
    """打印错误消息"""
    click.secho(f"Error: {message}", fg="red", err=True)
    if detail:
        click.secho(f"  {detail}", dim=True, err=True)


def print_warning(message: str):
    """打印警告消息"""
    click.secho(f"Warning: {message}", fg="yellow")


def confirm(message: str, default: bool = True) -> bool:
    """
    简洁的确认提示

    Args:
        message: 提示消息
        default: 默认值

    Returns:
        用户选择
    """
    default_hint = "Y/n" if default else "y/N"
    return click.confirm(f"{message} [{default_hint}]", default=default, show_default=False)


def ask_question(
    question: str,
    header: str,
    options: list[dict],
    default_index: int = 0,
    multi_select: bool = False
) -> str:
    """
    交互式菜单（支持方向键导航）

    Args:
        question: 问题描述
        header: 菜单标题
        options: 选项列表，每个选项包含 label 和 description
        default_index: 默认选项索引
        multi_select: 是否允许多选（暂不支持）

    Returns:
        用户选择的选项 label

    示例:
        answer = ask_question(
            question="Which authentication method?",
            header="Auth",
            options=[
                {"label": "Default", "description": "Use current config"},
                {"label": "Custom", "description": "Configure API endpoint"}
            ]
        )
    """
    import questionary
    from questionary import Style

    # 如果不在交互式终端，使用默认值
    if not sys.stdout.isatty():
        return options[default_index]["label"]

    # 自定义样式（简洁风格，类似 uv）
    custom_style = Style([
        ('qmark', 'fg:cyan bold'),           # 问号标记
        ('question', 'bold'),                 # 问题文字
        ('answer', 'fg:cyan bold'),           # 用户答案
        ('pointer', 'fg:cyan bold'),          # 当前选项指针 >
        ('highlighted', 'fg:cyan bold'),      # 当前高亮选项
        ('selected', 'fg:green'),             # 已选择项（多选）
        ('instruction', 'fg:#858585'),        # 说明文字（灰色）
    ])

    # 显示标题
    click.echo()
    click.secho(f"━━━ {header} ━━━", fg="cyan", bold=True)
    click.echo()

    # 构建 questionary 选项（带描述）
    choices = []
    for i, opt in enumerate(options):
        # 格式: "Label - Description"（单行显示）
        display_text = f"{opt['label']} - {opt['description']}"
        choices.append(
            questionary.Choice(
                title=display_text,
                value=opt['label'],  # 返回值只用 label
            )
        )

    # 使用 questionary.select
    try:
        answer = questionary.select(
            question,
            choices=choices,
            default=choices[default_index],  # 使用 Choice 对象作为默认值
            style=custom_style,
            use_shortcuts=True,
            use_indicator=True,
            instruction="(Use arrow keys, j/k, or number keys)"
        ).ask()
    except KeyboardInterrupt:
        # Ctrl+C 时使用默认值
        click.echo()
        click.secho("Using default option", dim=True)
        return options[default_index]["label"]

    return answer if answer else options[default_index]["label"]
