"""
frago init 命令实现

提供交互式环境初始化功能：
- 并行检查依赖（Node.js, Claude Code）
- 智能安装缺失组件
- 认证方式配置（官方 vs 自定义端点）
- 配置持久化和更新
"""

import sys
from typing import Dict, Optional

import click

# ASCII Art Banner - 使用块字符创建填充效果
FRAGO_BANNER = """\
███████╗██████╗  █████╗  ██████╗  ██████╗
██╔════╝██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗
█████╗  ██████╔╝███████║██║  ███╗██║   ██║
██╔══╝  ██╔══██╗██╔══██║██║   ██║██║   ██║
██║     ██║  ██║██║  ██║╚██████╔╝╚██████╔╝
╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝
"""

# 渐变色配置：从青色过渡到蓝色再到紫色
GRADIENT_COLORS = [
    (0, 255, 255),    # cyan
    (0, 191, 255),    # deep sky blue
    (65, 105, 225),   # royal blue
    (138, 43, 226),   # blue violet
    (148, 0, 211),    # dark violet
    (186, 85, 211),   # medium orchid
]


def _rgb_to_ansi(r: int, g: int, b: int) -> str:
    """将 RGB 转换为 ANSI 256 色转义序列"""
    return f"\033[38;2;{r};{g};{b}m"


def _interpolate_color(color1: tuple, color2: tuple, t: float) -> tuple:
    """在两个颜色之间线性插值"""
    return tuple(int(c1 + (c2 - c1) * t) for c1, c2 in zip(color1, color2))


def _get_gradient_color(position: float) -> tuple:
    """根据位置 (0-1) 获取渐变色"""
    if position >= 1.0:
        return GRADIENT_COLORS[-1]

    n = len(GRADIENT_COLORS) - 1
    idx = position * n
    lower_idx = int(idx)
    t = idx - lower_idx

    return _interpolate_color(GRADIENT_COLORS[lower_idx], GRADIENT_COLORS[lower_idx + 1], t)


def print_banner() -> None:
    """打印渐变色 ASCII art banner"""
    lines = FRAGO_BANNER.rstrip().split("\n")
    total_lines = len(lines)
    use_color = sys.stdout.isatty()

    click.echo()
    for i, line in enumerate(lines):
        if use_color:
            position = i / max(total_lines - 1, 1)
            r, g, b = _get_gradient_color(position)
            color_code = _rgb_to_ansi(r, g, b)
            reset_code = "\033[0m"
            click.echo(f"{color_code}{line}{reset_code}")
        else:
            click.echo(line)
    click.echo()

from frago.init.checker import (
    parallel_dependency_check,
    get_missing_dependencies,
    format_check_results,
)
from frago.init.installer import (
    get_installation_order,
    install_dependency,
)
from frago.init.configurator import (
    config_exists,
    display_config_summary,
    get_config_path,
    load_config,
    prompt_config_update,
    run_auth_configuration,
    save_config,
    warn_auth_switch,
)
from frago.init.models import Config, DependencyCheckResult
from frago.init.exceptions import CommandError, InitErrorCode
from frago.init.resources import (
    install_all_resources,
    format_install_summary,
    format_resources_status,
)


@click.command("init")
@click.option(
    "--skip-deps",
    is_flag=True,
    help="跳过依赖检查（仅更新配置）",
)
@click.option(
    "--show-config",
    is_flag=True,
    help="显示当前配置并退出",
)
@click.option(
    "--reset",
    is_flag=True,
    help="重置配置（删除现有配置后重新初始化）",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="非交互模式（使用默认值，适合 CI/CD）",
)
@click.option(
    "--skip-resources",
    is_flag=True,
    help="跳过资源安装（Claude Code 命令和示例 recipe）",
)
@click.option(
    "--update-resources",
    is_flag=True,
    help="强制更新所有资源（包括覆盖已存在的 recipe）",
)
def init(
    skip_deps: bool = False,
    show_config: bool = False,
    reset: bool = False,
    non_interactive: bool = False,
    skip_resources: bool = False,
    update_resources: bool = False,
) -> None:
    """
    初始化 Frago 开发环境

    检查并安装必要的依赖项（Node.js、Claude Code），
    配置认证方式和相关设置。
    """
    # 仅显示配置
    if show_config:
        _show_current_config()
        sys.exit(InitErrorCode.SUCCESS)

    # 重置模式
    if reset:
        _handle_reset()

    # 打印彩色 banner
    print_banner()
    click.echo("🚀 Frago 环境初始化\n")

    # 加载现有配置
    existing_config = load_config() if config_exists() else None

    # 1. 依赖检查
    deps_satisfied = True
    if not skip_deps:
        deps_satisfied = _check_and_install_dependencies(non_interactive)
    else:
        click.echo("⏭️  跳过依赖检查\n")

    # 2. 安装资源文件（Claude Code 命令和示例 recipe）
    resources_success = False
    if deps_satisfied and not skip_resources:
        resources_success = _install_resources(force_update=update_resources)
    elif skip_resources:
        click.echo("⏭️  跳过资源安装\n")

    # 3. 配置流程
    if deps_satisfied:
        config = _handle_configuration(existing_config, non_interactive)

        # 4. 更新资源安装状态并保存配置
        config.init_completed = True
        if resources_success:
            from datetime import datetime
            from frago import __version__
            config.resources_installed = True
            config.resources_version = __version__
            config.last_resource_update = datetime.now()
        save_config(config)

        # 5. 显示完成摘要
        click.echo("\n" + display_config_summary(config))
        click.echo("\n✅ 初始化完成\n")

    sys.exit(InitErrorCode.SUCCESS)


def _show_current_config() -> None:
    """显示当前配置和资源状态"""
    if not config_exists():
        click.echo("\n⚠️  尚未初始化，运行 'frago init' 开始配置\n")
        # 即使未初始化，也显示资源状态
        click.echo(format_resources_status() + "\n")
        return

    config = load_config()
    click.echo("\n" + display_config_summary(config))
    click.echo()
    click.echo(format_resources_status() + "\n")


def _handle_reset() -> None:
    """
    处理配置重置

    删除现有配置，允许重新初始化
    """
    if not config_exists():
        click.echo("ℹ️  没有现有配置需要重置\n")
        return

    config = load_config()
    click.echo("\n⚠️  即将重置以下配置:")
    click.echo(display_config_summary(config))

    if not click.confirm("\n确认重置?", default=False):
        click.echo("\n已取消重置")
        sys.exit(InitErrorCode.USER_CANCELLED)

    # 删除配置文件
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
        click.echo("\n✅ 配置已重置\n")


def _check_and_install_dependencies(non_interactive: bool = False) -> bool:
    """
    检查并安装依赖

    Args:
        non_interactive: 非交互模式

    Returns:
        True 如果所有依赖已满足
    """
    click.echo("正在检查依赖...")
    results = parallel_dependency_check()

    # 显示检查结果
    click.echo(format_check_results(results))
    click.echo()

    # 获取缺失的依赖
    missing = get_missing_dependencies(results)

    if missing:
        _handle_missing_dependencies(results, missing, non_interactive)

    click.echo("✅ 所有依赖已满足\n")
    return True


def _handle_configuration(
    existing_config: Optional[Config],
    non_interactive: bool = False,
) -> Config:
    """
    处理配置流程

    Args:
        existing_config: 现有配置（如果存在）
        non_interactive: 非交互模式

    Returns:
        配置后的 Config 对象
    """
    # 非交互模式：使用默认配置（官方认证）
    if non_interactive:
        click.echo("📝 使用默认配置（非交互模式）\n")
        if existing_config:
            return existing_config
        return Config(auth_method="official")

    if existing_config and existing_config.init_completed:
        # 已有完整配置，询问是否更新
        click.echo(display_config_summary(existing_config))

        if not prompt_config_update():
            click.echo("\n保持现有配置")
            return existing_config

        # 用户选择更新，警告认证方式切换
        current_method = existing_config.auth_method
        config = run_auth_configuration(existing_config)

        if config.auth_method != current_method:
            if not warn_auth_switch(current_method, config.auth_method):
                click.echo("\n已取消更新")
                return existing_config

        return config
    else:
        # 新配置或未完成的配置
        click.echo("📝 配置认证方式\n")
        return run_auth_configuration(existing_config)


def _handle_missing_dependencies(
    results: Dict[str, DependencyCheckResult],
    missing: list[str],
    non_interactive: bool = False,
) -> None:
    """
    处理缺失的依赖

    Args:
        results: 依赖检查结果
        missing: 缺失的依赖列表
        non_interactive: 非交互模式
    """
    # 显示缺失信息
    click.echo("⚠️  以下依赖需要安装:")
    for name in missing:
        result = results.get(name)
        if result:
            click.echo(f"  - {result.display_status()}")
    click.echo()

    # 非交互模式：自动安装
    if non_interactive:
        click.echo("📦 自动安装依赖（非交互模式）\n")
    elif not click.confirm("是否安装缺失的依赖?", default=True):
        click.echo("\n已取消安装")
        sys.exit(InitErrorCode.USER_CANCELLED)

    # 按顺序安装
    node_needed = "node" in missing
    claude_code_needed = "claude-code" in missing
    install_order = get_installation_order(node_needed, claude_code_needed)

    click.echo()
    for name in install_order:
        _install_with_progress(name)


def _install_with_progress(name: str) -> None:
    """
    带进度提示的安装

    Args:
        name: 依赖名称
    """
    display_name = "Node.js" if name == "node" else "Claude Code"

    click.echo(f"📦 正在安装 {display_name}...")

    try:
        install_dependency(name)
        click.echo(f"✅ {display_name} 安装成功\n")
    except CommandError as e:
        click.echo(f"\n❌ {display_name} 安装失败")
        click.echo(str(e))
        sys.exit(e.code)


def _install_resources(force_update: bool = False) -> bool:
    """
    安装资源文件（Claude Code 命令和示例 recipe）

    Args:
        force_update: 强制更新所有资源（覆盖已存在的 recipe）

    Returns:
        True 如果资源安装成功（无错误）

    在依赖检查后、配置前调用
    """
    click.echo("📦 安装 Frago 资源文件...\n")

    try:
        status = install_all_resources(force_update=force_update)

        # 显示安装摘要
        summary = format_install_summary(status)
        if summary:
            click.echo(summary)
            click.echo()

        # 检查是否有错误
        if not status.all_success:
            click.echo("⚠️  部分资源安装失败，请检查错误信息\n")
            return False

        return True

    except Exception as e:
        click.echo(f"❌ 资源安装失败: {e}")
        click.echo("💡 提示: 请确保您有 ~/.claude/ 和 ~/.frago/ 目录的写入权限")
        click.echo("   可尝试: mkdir -p ~/.claude/commands ~/.frago/recipes\n")
        return False
