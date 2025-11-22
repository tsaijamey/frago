#!/usr/bin/env python3
"""
AuViMa CLI - Chrome DevTools Protocol 命令行接口

提供向后兼容的CLI接口，支持所有原Shell脚本功能。
"""

import sys
import click
from typing import Optional

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
    init
)
from .recipe_commands import recipe_group
from .run_commands import run_group


@click.group()
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
    AuViMa - Chrome DevTools Protocol 命令行工具

    提供与Chrome浏览器交互的命令行接口，支持页面导航、
    元素操作、截图、JavaScript执行等功能。

    代理配置优先级:
    1. 命令行参数 (--proxy-host, --proxy-port等)
    2. 环境变量 (HTTP_PROXY, HTTPS_PROXY, NO_PROXY)
    3. 无代理
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
cli.add_command(init)

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