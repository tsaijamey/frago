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
    prompt_working_directory,
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
from frago.init.ui import (
    spinner_context,
    print_section,
    print_summary,
    ProgressReporter,
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
    print_section("Frago Environment Initialization")

    # 加载现有配置
    existing_config = load_config() if config_exists() else None

    # 1. 依赖检查
    deps_satisfied = True
    if not skip_deps:
        deps_satisfied = _check_and_install_dependencies(non_interactive)
    else:
        click.secho("Skipped dependency check", dim=True)
        click.echo()

    # 2. 安装资源文件（Claude Code 命令和示例 recipe）
    resources_success = False
    if deps_satisfied and not skip_resources:
        resources_success = _install_resources(force_update=update_resources)
    elif skip_resources:
        click.secho("Skipped resource installation", dim=True)
        click.echo()

    # 3. 配置流程
    if deps_satisfied:
        if not non_interactive:
            click.echo()  # 空行分隔
        config = _handle_configuration(existing_config, non_interactive)

        # 4. 更新资源安装状态并保存配置
        config.init_completed = True
        if resources_success:
            from datetime import datetime
            from frago import __version__
            config.resources_installed = True
            config.resources_version = __version__
            config.last_resource_update = datetime.now()

        with spinner_context("Saving configuration", "Configuration saved"):
            save_config(config)

        # 5. 显示完成摘要
        _print_completion_summary(config)

    sys.exit(InitErrorCode.SUCCESS)


def _print_completion_summary(config: Config) -> None:
    """
    打印初始化完成摘要（uv 风格）

    Args:
        config: 配置对象
    """
    print_section("Initialization Complete")

    items = []

    # 依赖信息
    if config.node_version:
        items.append(("Node.js", config.node_version))
    if config.claude_code_version:
        items.append(("Claude Code", config.claude_code_version))

    # 认证方式
    if config.auth_method == "official":
        items.append(("Authentication", "User configured"))
    else:
        endpoint_type = config.api_endpoint.type if config.api_endpoint else "custom"
        items.append(("Authentication", f"Frago managed ({endpoint_type})"))

    # 工作目录
    workdir = config.working_directory or "current directory"
    items.append(("Working Directory", workdir))

    print_summary(items, "Configuration")

    click.secho("Run 'frago --help' to get started", fg="cyan")
    click.echo()


def _show_current_config() -> None:
    """显示当前配置和资源状态"""
    if not config_exists():
        print_section("Frago Configuration")
        click.secho("Not initialized. Run 'frago init' to configure.", dim=True)
        click.echo()
        return

    config = load_config()
    print_section("Frago Configuration")
    click.echo(display_config_summary(config))
    click.echo()


def _handle_reset() -> None:
    """
    处理配置重置

    删除现有配置，允许重新初始化
    """
    if not config_exists():
        click.secho("No configuration to reset", dim=True)
        click.echo()
        return

    config = load_config()
    print_section("Reset Configuration")
    click.secho("The following configuration will be removed:", fg="yellow")
    click.echo()
    click.echo(display_config_summary(config))
    click.echo()

    if not click.confirm("Confirm reset?", default=False):
        click.secho("Reset cancelled", dim=True)
        sys.exit(InitErrorCode.USER_CANCELLED)

    # 删除配置文件
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
        click.secho("Configuration reset successfully", fg="green")
        click.echo()


def _check_and_install_dependencies(non_interactive: bool = False) -> bool:
    """
    检查并安装依赖

    Args:
        non_interactive: 非交互模式

    Returns:
        True 如果所有依赖已满足或用户选择跳过安装
    """
    with spinner_context("Checking dependencies", "Resolved dependencies") as reporter:
        results = parallel_dependency_check()

    # 显示检查结果
    reporter = ProgressReporter()
    for name, result in results.items():
        if result.installed:
            version = result.version or "unknown"
            reporter.item_added(name, version)
        else:
            reporter.item_error(name, "not found")

    click.echo()

    # 获取缺失的依赖
    missing = get_missing_dependencies(results)

    if missing:
        _handle_missing_dependencies(results, missing, non_interactive)

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
        click.secho("Using default configuration", dim=True)
        if existing_config:
            return existing_config
        return Config(auth_method="official")

    if existing_config and existing_config.init_completed:
        # 已有完整配置，显示摘要并询问是否更新
        print_section("Current Configuration")
        click.echo(display_config_summary(existing_config))

        if not prompt_config_update():
            return existing_config

        # 用户选择更新，警告认证方式切换
        current_method = existing_config.auth_method
        config = run_auth_configuration(existing_config)

        if config.auth_method != current_method:
            if not warn_auth_switch(current_method, config.auth_method):
                click.secho("Configuration update cancelled", dim=True)
                return existing_config

        return config
    else:
        # 新配置或未完成的配置
        print_section("Configuration")
        config = run_auth_configuration(existing_config)

        # 配置工作目录
        working_dir = prompt_working_directory()
        config.working_directory = working_dir

        return config


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
        click.secho("Skipped dependency installation", dim=True)
        click.echo()
        return

    # 按顺序安装
    node_needed = "node" in missing
    claude_code_needed = "claude-code" in missing
    install_order = get_installation_order(node_needed, claude_code_needed)

    click.echo()

    # 追踪是否刚安装了 Node.js 且 npm 不在 PATH 中
    node_installed_needs_activation = False

    for name in install_order:
        # 对于 claude-code：如果刚安装了 node 且 npm 不可用，使用 nvm fallback
        use_nvm = node_installed_needs_activation and name == "claude-code"

        requires_restart = _install_with_progress(
            name,
            use_nvm_fallback=use_nvm,
            node_just_installed=node_installed_needs_activation,
        )

        if name == "node" and requires_restart:
            # Node.js 安装成功但 npm 不在 PATH 中
            node_installed_needs_activation = True

            # 检查是否还有后续依赖
            remaining = install_order[install_order.index(name) + 1:]
            if remaining:
                # 尝试用 nvm fallback 安装后续依赖，而不是直接要求重启
                click.echo()
                click.secho(
                    "ℹ️  npm 尚未在当前终端生效，尝试通过 nvm 环境继续安装...",
                    fg="cyan",
                )
                continue

        # 如果不是 node，但需要重启（理论上不应该发生）
        if requires_restart and name != "node":
            _show_restart_required_message([])
            sys.exit(0)


def _show_restart_required_message(remaining_deps: list) -> None:
    """
    显示需要重启终端的提示

    Args:
        remaining_deps: 剩余需要安装的依赖
    """
    from frago.init.installer import _get_shell_config_file

    click.echo()
    click.secho("⚠️  Node.js 已安装，但需要激活才能继续", fg="yellow")
    click.echo()

    shell_config = _get_shell_config_file()
    if shell_config:
        click.echo("请执行以下操作之一：")
        click.echo()
        click.echo(f"  1. 激活当前终端（推荐）:")
        click.echo(f"     source {shell_config}")
        click.echo()
        click.echo("  2. 重启终端")
        click.echo()
    else:
        click.echo("请重启终端或执行:")
        click.echo("    source ~/.nvm/nvm.sh")
        click.echo()

    click.echo("然后重新运行:")
    click.secho("    frago init", fg="cyan")
    click.echo()

    remaining_names = ", ".join(
        "Claude Code" if d == "claude-code" else d for d in remaining_deps
    )
    click.echo(f"（剩余依赖: {remaining_names}）")


def _install_with_progress(
    name: str,
    use_nvm_fallback: bool = False,
    node_just_installed: bool = False,
) -> bool:
    """
    带进度提示的安装

    Args:
        name: 依赖名称
        use_nvm_fallback: 对于 claude-code，是否在 npm 不可用时使用 nvm 环境
        node_just_installed: 是否刚安装了 Node.js（用于错误提示）

    Returns:
        requires_restart: 是否需要重启终端后继续
    """
    display_name = "Node.js" if name == "node" else "Claude Code"

    click.echo(f"📦 正在安装 {display_name}...")

    try:
        success, warning, requires_restart = install_dependency(
            name,
            use_nvm_fallback=use_nvm_fallback,
        )
        click.echo(f"✅ {display_name} 安装成功")

        # 显示 Windows PATH 警告（如有）
        if warning:
            click.secho(warning, fg="yellow")

        click.echo()
        return requires_restart

    except CommandError as e:
        click.echo(f"\n❌ {display_name} 安装失败")
        click.echo(str(e))

        # 如果是因为刚安装 Node.js 导致 npm 不可用，给出更友好的提示
        if name == "claude-code" and node_just_installed:
            click.echo()
            _show_restart_required_message(["claude-code"])

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
    try:
        with spinner_context("Installing resources", "Installed resources") as reporter:
            status = install_all_resources(force_update=force_update)

        # 显示安装详情（uv 风格）
        reporter = ProgressReporter()

        # Commands
        if status.commands:
            for name in status.commands.installed:
                reporter.item_added(name)
            for error in status.commands.errors:
                click.secho(f" ✗ {error}", fg="red")

        # Skills
        if status.skills:
            for name in status.skills.installed:
                reporter.item_added(f"skill/{name}")
            for name in status.skills.skipped:
                reporter.item_skipped(f"skill/{name}")

        # Recipes
        if status.recipes:
            for name in status.recipes.installed:
                reporter.item_added(f"recipe/{name}")
            for name in status.recipes.skipped:
                reporter.item_skipped(f"recipe/{name}")

        click.echo()

        # 检查是否有错误
        if not status.all_success:
            click.secho("Warning: Some resources failed to install", fg="yellow")
            return False

        return True

    except Exception as e:
        click.secho(f"Error: Resource installation failed - {e}", fg="red", err=True)
        click.secho("  Ensure write permissions for ~/.claude/ and ~/.frago/", dim=True, err=True)
        return False
