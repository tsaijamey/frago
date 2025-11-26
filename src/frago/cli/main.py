#!/usr/bin/env python3
"""
Frago CLI - Chrome DevTools Protocol 命令行接口

提供向后兼容的CLI接口，支持所有原Shell脚本功能。
"""

import sys
import click
from typing import Optional
from collections import OrderedDict

from .commands import (
    navigate,
    click_element,
    screenshot,
    execute_javascript,
    get_title,
    get_content,
    status,
    scroll,
    wait,
    zoom,
    clear_effects,
    highlight,
    pointer,
    spotlight,
    annotate,
    init as init_dirs,  # 旧的目录初始化命令，保留为 init-dirs
)
from .init_command import init  # 新的环境初始化命令
from .recipe_commands import recipe_group
from .run_commands import run_group
from .sync_command import sync


# 命令分组定义
COMMAND_GROUPS = OrderedDict([
    ("环境配置", ["init", "init-dirs", "status", "sync"]),
    ("页面操作", ["navigate", "scroll", "zoom", "wait"]),
    ("元素交互", ["click", "exec-js", "get-title", "get-content"]),
    ("视觉效果", ["screenshot", "highlight", "pointer", "spotlight", "annotate", "clear-effects"]),
    ("自动化", ["recipe", "run"]),
])


class GroupedGroup(click.Group):
    """支持命令分组显示的 Click Group"""

    def format_commands(self, ctx, formatter):
        """按分组格式化命令列表"""
        commands = []
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

        # 计算最大命令名长度
        max_len = max(len(name) for name, _ in commands)

        # 按 COMMAND_GROUPS 定义的顺序输出分组命令
        for group_name in COMMAND_GROUPS.keys():
            if group_name not in grouped:
                continue
            group_cmds = grouped[group_name]
            with formatter.section(group_name):
                formatter.write_dl([
                    (name, cmd.get_short_help_str(limit=formatter.width))
                    for name, cmd in sorted(group_cmds, key=lambda x: COMMAND_GROUPS[group_name].index(x[0]))
                ])

        # 输出未分组命令
        if ungrouped:
            with formatter.section("其他"):
                formatter.write_dl([
                    (name, cmd.get_short_help_str(limit=formatter.width))
                    for name, cmd in ungrouped
                ])


@click.group(cls=GroupedGroup)
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
@click.pass_context
def cli(ctx, debug: bool, timeout: int, host: str, port: int,
        proxy_host: Optional[str], proxy_port: Optional[int],
        proxy_username: Optional[str], proxy_password: Optional[str],
        no_proxy: bool):
    """
    Frago - AI Agent 多运行时自动化基础设施

    \b
    三大核心系统:
      • Run System   持久化任务上下文，记录完整探索过程
      • Recipe System 元数据驱动的可复用自动化脚本
      • Chrome CDP    浏览器自动化底层能力
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

    if debug:
        click.echo(f"调试模式已启用 - 主机: {host}:{port}, 超时: {timeout}s")
        if no_proxy:
            click.echo("代理已禁用 (--no-proxy)")
        elif proxy_host and proxy_port:
            click.echo(f"代理配置: {proxy_host}:{proxy_port}")


# 注册所有子命令
cli.add_command(navigate)
cli.add_command(click_element)
cli.add_command(screenshot)
cli.add_command(execute_javascript)
cli.add_command(get_title)
cli.add_command(get_content)
cli.add_command(status)
cli.add_command(scroll)
cli.add_command(wait)
cli.add_command(zoom)
cli.add_command(clear_effects)
cli.add_command(highlight)
cli.add_command(pointer)
cli.add_command(spotlight)
cli.add_command(annotate)
cli.add_command(init)  # 新的环境初始化命令
cli.add_command(init_dirs, name="init-dirs")  # 旧的目录初始化命令
cli.add_command(sync)  # Recipe 同步命令

# Recipe 管理命令组
cli.add_command(recipe_group)

# Run 命令系统
cli.add_command(run_group)


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