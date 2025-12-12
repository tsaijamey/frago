#!/usr/bin/env python3
"""
Frago CLI - Chrome DevTools Protocol 命令行接口

提供向后兼容的CLI接口，支持所有原Shell脚本功能。
"""

import sys
import click
from typing import Optional, List, Tuple
from collections import OrderedDict

from frago import __version__
from .commands import (
    status,
    init as init_dirs,  # 旧的目录初始化命令，保留为 init-dirs
)
from .init_command import init  # 新的环境初始化命令
from .recipe_commands import recipe_group
from .run_commands import run_group
from .dev_commands import dev_group
from .usegit_commands import usegit_group
from .sync_command import sync_cmd  # Sync 命令
from .chrome_commands import chrome_group
from .update_command import update
from .agent_command import agent, agent_status
from .gui_command import gui_deps
from .session_commands import session_group
from .agent_friendly import AgentFriendlyGroup


# 命令分组定义（按用户角色）
COMMAND_GROUPS = OrderedDict([
    ("日常使用", ["chrome", "recipe", "run"]),
    ("会话与智能", ["session", "agent", "agent-status"]),
    ("环境管理", ["init", "status", "sync", "update"]),
    ("开发者", ["dev", "use-git", "init-dirs", "gui-deps"]),
])

# 需要展开子命令的命令组
EXPAND_SUBCOMMANDS = ["chrome", "recipe", "run", "dev", "use-git", "session"]

# chrome 子命令分组
CHROME_SUBGROUPS = OrderedDict([
    ("生命周期", ["start", "stop", "status"]),
    ("Tab 管理", ["list-tabs", "switch-tab"]),
    ("页面控制", ["navigate", "scroll", "scroll-to", "zoom", "wait"]),
    ("元素交互", ["click", "exec-js", "get-title", "get-content"]),
    ("视觉效果", ["screenshot", "highlight", "pointer", "spotlight", "annotate", "underline", "clear-effects"]),
])


class AgentFriendlyGroupedGroup(AgentFriendlyGroup):
    """Agent 友好的分组命令组

    结合：
    - AgentFriendlyGroup: 增强错误信息
    - 分组显示: 按类别组织命令
    - 子命令展开: 在帮助中显示命令组的子命令
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter):
        """按分组格式化命令列表，展开子命令组"""
        commands: List[Tuple[str, click.Command]] = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands.append((subcommand, cmd))

        if not commands:
            return

        # 按分组组织命令
        grouped = OrderedDict()
        ungrouped = []

        for name, cmd in commands:
            found = False
            for group_name, group_cmds in COMMAND_GROUPS.items():
                if name in group_cmds:
                    if group_name not in grouped:
                        grouped[group_name] = []
                    grouped[group_name].append((name, cmd))
                    found = True
                    break
            if not found:
                ungrouped.append((name, cmd))

        # 按 COMMAND_GROUPS 定义的顺序输出分组命令
        for group_name in COMMAND_GROUPS.keys():
            if group_name not in grouped:
                continue
            group_cmds = grouped[group_name]
            with formatter.section(group_name):
                rows = []
                for name, cmd in sorted(
                    group_cmds,
                    key=lambda x: COMMAND_GROUPS[group_name].index(x[0])
                ):
                    # 检查是否需要展开子命令
                    if name in EXPAND_SUBCOMMANDS and isinstance(cmd, click.Group):
                        # 先添加组本身
                        rows.append((name, cmd.get_short_help_str(limit=formatter.width)))
                        # 展开子命令
                        subcommand_rows = self._get_subcommand_rows(ctx, name, cmd)
                        rows.extend(subcommand_rows)
                    else:
                        rows.append((name, cmd.get_short_help_str(limit=formatter.width)))
                formatter.write_dl(rows)

        # 输出未分组命令
        if ungrouped:
            with formatter.section("其他"):
                formatter.write_dl([
                    (name, cmd.get_short_help_str(limit=formatter.width))
                    for name, cmd in ungrouped
                ])

    def _get_subcommand_rows(
        self,
        ctx: click.Context,
        group_name: str,
        group_cmd: click.Group
    ) -> List[Tuple[str, str]]:
        """获取命令组的子命令行（带缩进前缀）"""
        rows = []

        # 创建子上下文以获取子命令列表
        with ctx.scope() as sub_ctx:
            sub_ctx.info_name = group_name

            # 获取所有子命令
            subcmds = {}
            for subcmd_name in group_cmd.list_commands(sub_ctx):
                subcmd = group_cmd.get_command(sub_ctx, subcmd_name)
                if subcmd is None or subcmd.hidden:
                    continue
                subcmds[subcmd_name] = subcmd

            # chrome 命令组使用分组显示
            if group_name == "chrome" and CHROME_SUBGROUPS:
                for subgroup_name, subgroup_cmds in CHROME_SUBGROUPS.items():
                    # 添加分组标签
                    rows.append((f"  [{subgroup_name}]", ""))
                    for subcmd_name in subgroup_cmds:
                        if subcmd_name in subcmds:
                            subcmd = subcmds[subcmd_name]
                            full_name = f"    {group_name} {subcmd_name}"
                            help_str = subcmd.get_short_help_str(limit=55)
                            rows.append((full_name, help_str))
            else:
                # 其他命令组扁平显示
                for subcmd_name, subcmd in subcmds.items():
                    full_name = f"  {group_name} {subcmd_name}"
                    help_str = subcmd.get_short_help_str(limit=60)
                    rows.append((full_name, help_str))

        return rows


@click.group(cls=AgentFriendlyGroupedGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="frago")
@click.option(
    '--gui',
    is_flag=True,
    help='启动 GUI 应用模式'
)
@click.option(
    '--debug',
    is_flag=True,
    help='启用调试模式，输出详细日志'
)
@click.option(
    '--timeout',
    type=int,
    default=30,
    help='设置操作超时时间（秒），默认30秒'
)
@click.option(
    '--host',
    type=str,
    default='127.0.0.1',
    help='Chrome DevTools Protocol 主机地址，默认127.0.0.1'
)
@click.option(
    '--port',
    type=int,
    default=9222,
    help='Chrome DevTools Protocol 端口，默认9222'
)
@click.option(
    '--proxy-host',
    type=str,
    help='代理服务器主机地址（支持环境变量HTTP_PROXY/HTTPS_PROXY）'
)
@click.option(
    '--proxy-port',
    type=int,
    help='代理服务器端口'
)
@click.option(
    '--proxy-username',
    type=str,
    help='代理认证用户名'
)
@click.option(
    '--proxy-password',
    type=str,
    help='代理认证密码'
)
@click.option(
    '--no-proxy',
    is_flag=True,
    help='绕过代理连接（忽略环境变量和代理配置）'
)
@click.option(
    '--target-id',
    type=str,
    help='指定目标tab的ID，用于在多tab环境下精确控制操作哪个页面'
)
@click.pass_context
def cli(ctx, gui: bool, debug: bool, timeout: int, host: str, port: int,
        proxy_host: Optional[str], proxy_port: Optional[int],
        proxy_username: Optional[str], proxy_password: Optional[str],
        no_proxy: bool, target_id: Optional[str]):
    """
    Frago - AI Agent 多运行时自动化基础设施

    \b
    三大核心系统:
      • Run System   持久化任务上下文，记录完整探索过程
      • Recipe System 元数据驱动的可复用自动化脚本
      • Chrome CDP    浏览器自动化底层能力

    \b
    GUI 模式:
      frago --gui    启动桌面 GUI 应用界面
    """
    ctx.ensure_object(dict)
    ctx.obj['DEBUG'] = debug
    ctx.obj['TIMEOUT'] = timeout
    ctx.obj['HOST'] = host
    ctx.obj['PORT'] = port
    ctx.obj['PROXY_HOST'] = proxy_host
    ctx.obj['PROXY_PORT'] = proxy_port
    ctx.obj['PROXY_USERNAME'] = proxy_username
    ctx.obj['PROXY_PASSWORD'] = proxy_password
    ctx.obj['NO_PROXY'] = no_proxy
    ctx.obj['TARGET_ID'] = target_id

    # Handle --gui option
    if gui:
        from frago.gui.app import start_gui
        start_gui(debug=debug)
        return

    # If no subcommand is invoked, show help
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return

    if debug:
        click.echo(f"调试模式已启用 - 主机: {host}:{port}, 超时: {timeout}s")
        if no_proxy:
            click.echo("代理已禁用 (--no-proxy)")
        elif proxy_host and proxy_port:
            click.echo(f"代理配置: {proxy_host}:{proxy_port}")


# 注册顶层命令
cli.add_command(init)  # 新的环境初始化命令
cli.add_command(init_dirs, name="init-dirs")  # 旧的目录初始化命令
cli.add_command(status)  # CDP 连接状态（保留在顶层便于快速检查）
cli.add_command(sync_cmd, name="sync")  # 资源同步命令
cli.add_command(update)  # 自我更新命令
cli.add_command(gui_deps)  # GUI 依赖检查命令

# 命令组
cli.add_command(dev_group)  # 开发者命令组: dev pack
cli.add_command(usegit_group)  # Git 同步命令组: use-git sync（已废弃，请使用 sync）
cli.add_command(chrome_group)  # Chrome CDP 命令组

# Recipe 管理命令组
cli.add_command(recipe_group)

# Run 命令系统
cli.add_command(run_group)

# Agent 命令
cli.add_command(agent)
cli.add_command(agent_status)

# Session 管理命令组
cli.add_command(session_group)


def main():
    """CLI入口点"""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n操作已取消", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()