#!/usr/bin/env python3
"""
AuViMa CLI 命令实现

实现所有CDP功能的CLI子命令，保持与原有Shell脚本的兼容性。
"""

import os
import sys
import click
from typing import Optional

from ..cdp.session import CDPSession
from ..cdp.exceptions import CDPError
from ..cdp.config import CDPConfig


# 全局选项默认值配置
GLOBAL_OPTIONS = {
    'debug': False,
    'timeout': 30,
    'host': '127.0.0.1', 
    'port': 9222
}


def create_session(ctx) -> CDPSession:
    """
    创建CDP会话

    使用全局选项：
    - --debug: 启用调试模式
    - --timeout: 设置操作超时时间
    - --host: CDP服务主机地址
    - --port: CDP服务端口
    - --proxy-host: 代理服务器主机地址
    - --proxy-port: 代理服务器端口
    - --proxy-username: 代理认证用户名
    - --proxy-password: 代理认证密码
    - --no-proxy: 绕过代理连接
    """
    config = CDPConfig(
        host=ctx.obj['HOST'],
        port=ctx.obj['PORT'],
        timeout=ctx.obj['TIMEOUT'],
        debug=ctx.obj['DEBUG'],
        proxy_host=ctx.obj.get('PROXY_HOST'),
        proxy_port=ctx.obj.get('PROXY_PORT'),
        proxy_username=ctx.obj.get('PROXY_USERNAME'),
        proxy_password=ctx.obj.get('PROXY_PASSWORD'),
        no_proxy=ctx.obj.get('NO_PROXY', False)
    )
    return CDPSession(config)


@click.command('navigate')
@click.argument('url')
@click.option(
    '--wait-for',
    type=str,
    help='等待选择器出现后再返回'
)
@click.pass_context
def navigate(ctx, url: str, wait_for: Optional[str] = None):
    """导航到指定URL"""
    try:
        with create_session(ctx) as session:
            session.navigate(url)
            if wait_for:
                session.wait_for_selector(wait_for)
            click.echo(f"成功导航到: {url}")
    except CDPError as e:
        click.echo(f"导航失败: {e}", err=True)
        sys.exit(1)


@click.command('click')
@click.argument('selector')
@click.option(
    '--wait-timeout',
    type=int,
    default=10,
    help='等待元素出现的超时时间（秒）'
)
@click.pass_context
def click_element(ctx, selector: str, wait_timeout: int):
    """点击指定选择器的元素"""
    try:
        with create_session(ctx) as session:
            session.click(selector, wait_timeout=wait_timeout)
            click.echo(f"成功点击元素: {selector}")
    except CDPError as e:
        click.echo(f"点击失败: {e}", err=True)
        sys.exit(1)


@click.command('screenshot')
@click.argument('output_file')
@click.option(
    '--full-page',
    is_flag=True,
    help='截取整个页面（包括滚动区域）'
)
@click.option(
    '--quality',
    type=int,
    default=80,
    help='图片质量（1-100），默认80'
)
@click.pass_context
def screenshot(ctx, output_file: str, full_page: bool, quality: int):
    """截取页面截图"""
    try:
        with create_session(ctx) as session:
            session.screenshot.capture(output_file, full_page=full_page, quality=quality)
            click.echo(f"截图已保存到: {output_file}")
    except CDPError as e:
        click.echo(f"截图失败: {e}", err=True)
        sys.exit(1)


@click.command('exec-js')
@click.argument('script')
@click.option(
    '--return-value',
    is_flag=True,
    help='返回JavaScript执行结果'
)
@click.pass_context
def execute_javascript(ctx, script: str, return_value: bool):
    """
    执行JavaScript代码
    
    SCRIPT 参数可以是直接的JavaScript代码，也可以是包含代码的文件路径。
    """
    try:
        # 检查是否为文件路径
        if os.path.exists(script) and os.path.isfile(script):
            try:
                with open(script, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                if ctx.obj['DEBUG']:
                    click.echo(f"从文件加载脚本: {script}")
                script = script_content
            except Exception as e:
                click.echo(f"无法读取脚本文件: {e}", err=True)
                sys.exit(1)

        with create_session(ctx) as session:
            result = session.evaluate(script, return_by_value=return_value)
            if return_value:
                click.echo(f"执行结果: {result}")
            else:
                click.echo("JavaScript执行完成")
    except CDPError as e:
        click.echo(f"JavaScript执行失败: {e}", err=True)
        sys.exit(1)


@click.command('get-title')
@click.pass_context
def get_title(ctx):
    """获取页面标题"""
    try:
        with create_session(ctx) as session:
            title = session.get_title()
            click.echo(title)
    except CDPError as e:
        click.echo(f"获取标题失败: {e}", err=True)
        sys.exit(1)


@click.command('get-content')
@click.argument('selector', default='body')
@click.pass_context
def get_content(ctx, selector: str):
    """获取页面或元素的文本内容"""
    try:
        with create_session(ctx) as session:
            script = f"""
            (function() {{
                var el = document.querySelector('{selector}');
                if (!el) return 'Error: Element not found';
                return el.innerText || el.textContent || '';
            }})()
            """
            # session.evaluate() 已经提取了值，直接返回结果
            content = session.evaluate(script, return_by_value=True)
            if content == 'Error: Element not found':
                click.echo(f"找不到元素: {selector}", err=True)
                sys.exit(1)
            click.echo(content if content else '')
    except CDPError as e:
        click.echo(f"获取内容失败: {e}", err=True)
        sys.exit(1)


@click.command('status')
@click.pass_context
def status(ctx):
    """检查CDP连接状态"""
    try:
        with create_session(ctx) as session:
            # 执行健康检查
            is_healthy = session.status.health_check()
            if is_healthy:
                # 获取Chrome状态信息
                chrome_status = session.status.check_chrome_status()
                click.echo(f"✓ CDP连接正常")
                click.echo(f"Browser: {chrome_status.get('Browser', 'unknown')}")
                click.echo(f"Protocol-Version: {chrome_status.get('Protocol-Version', 'unknown')}")
                click.echo(f"WebKit-Version: {chrome_status.get('WebKit-Version', 'unknown')}")
            else:
                click.echo("✗ CDP连接失败", err=True)
                sys.exit(1)
    except CDPError as e:
        click.echo(f"状态检查失败: {e}", err=True)
        sys.exit(1)


@click.command('scroll')
@click.argument('distance', type=int)
@click.pass_context
def scroll(ctx, distance: int):
    """滚动页面"""
    try:
        with create_session(ctx) as session:
            session.scroll(distance)
            click.echo(f"已滚动 {distance} 像素")
    except CDPError as e:
        click.echo(f"滚动失败: {e}", err=True)
        sys.exit(1)


@click.command('wait')
@click.argument('seconds', type=float)
@click.pass_context
def wait(ctx, seconds: float):
    """等待指定秒数"""
    try:
        with create_session(ctx) as session:
            session.wait.wait(seconds)
            click.echo(f"等待 {seconds} 秒完成")
    except CDPError as e:
        click.echo(f"等待失败: {e}", err=True)
        sys.exit(1)


@click.command('zoom')
@click.argument('factor', type=float)
@click.pass_context
def zoom(ctx, factor: float):
    """设置页面缩放比例"""
    try:
        with create_session(ctx) as session:
            session.zoom(factor)
            click.echo(f"页面缩放设置为: {factor}")
    except CDPError as e:
        click.echo(f"缩放失败: {e}", err=True)
        sys.exit(1)


@click.command('clear-effects')
@click.pass_context
def clear_effects(ctx):
    """清除所有视觉效果"""
    try:
        with create_session(ctx) as session:
            session.clear_effects()
            click.echo("视觉效果已清除")
    except CDPError as e:
        click.echo(f"清除效果失败: {e}", err=True)
        sys.exit(1)


@click.command('highlight')
@click.argument('selector')
@click.option(
    '--color',
    type=str,
    default='yellow',
    help='高亮颜色，默认黄色'
)
@click.option(
    '--width',
    type=int,
    default=3,
    help='高亮边框宽度（像素），默认3'
)
@click.pass_context
def highlight(ctx, selector: str, color: str, width: int):
    """高亮显示指定元素"""
    try:
        with create_session(ctx) as session:
            session.highlight(selector, color=color, border_width=width)
            click.echo(f"已高亮元素: {selector} (颜色: {color}, 宽度: {width}px)")
    except CDPError as e:
        click.echo(f"高亮失败: {e}", err=True)
        sys.exit(1)


@click.command('pointer')
@click.argument('selector')
@click.pass_context
def pointer(ctx, selector: str):
    """在元素上显示鼠标指针"""
    try:
        with create_session(ctx) as session:
            session.pointer(selector)
            click.echo(f"已在元素上显示指针: {selector}")
    except CDPError as e:
        click.echo(f"显示指针失败: {e}", err=True)
        sys.exit(1)


@click.command('spotlight')
@click.argument('selector')
@click.pass_context
def spotlight(ctx, selector: str):
    """聚光灯效果显示元素"""
    try:
        with create_session(ctx) as session:
            session.spotlight(selector)
            click.echo(f"已聚光灯显示元素: {selector}")
    except CDPError as e:
        click.echo(f"聚光灯失败: {e}", err=True)
        sys.exit(1)


@click.command('annotate')
@click.argument('selector')
@click.argument('text')
@click.option(
    '--position',
    type=click.Choice(['top', 'bottom', 'left', 'right']),
    default='top',
    help='标注位置'
)
@click.pass_context
def annotate(ctx, selector: str, text: str, position: str):
    """在元素上添加标注"""
    try:
        with create_session(ctx) as session:
            session.annotate(selector, text, position=position)
            click.echo(f"已在元素上添加标注: {text}")
    except CDPError as e:
        click.echo(f"添加标注失败: {e}", err=True)
        sys.exit(1)


@click.command('init')
@click.option(
    '--force',
    is_flag=True,
    help='强制重新创建已存在的目录'
)
def init(force: bool):
    """
    初始化 AuViMa 用户级目录结构

    创建 ~/.auvima/recipes/ 目录及其子目录:
    - atomic/chrome/: Chrome CDP 操作的 Recipe
    - atomic/system/: 系统操作的 Recipe
    - workflows/: 编排多个 Recipe 的工作流
    """
    from pathlib import Path

    user_home = Path.home()
    auvima_dir = user_home / '.auvima'
    recipes_dir = auvima_dir / 'recipes'

    # 需要创建的目录列表
    directories = [
        recipes_dir / 'atomic' / 'chrome',
        recipes_dir / 'atomic' / 'system',
        recipes_dir / 'workflows'
    ]

    created = []
    skipped = []

    for directory in directories:
        if directory.exists() and not force:
            skipped.append(str(directory))
            continue

        try:
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory))
        except Exception as e:
            click.echo(f"创建目录失败 {directory}: {e}", err=True)
            sys.exit(1)

    # 输出结果
    if created:
        click.echo("已创建以下目录:")
        for dir_path in created:
            click.echo(f"  ✓ {dir_path}")

    if skipped:
        click.echo("\n以下目录已存在（使用 --force 强制重新创建）:")
        for dir_path in skipped:
            click.echo(f"  - {dir_path}")

    if not created and not skipped:
        click.echo("所有目录已存在")

    click.echo(f"\n用户级 Recipe 目录: {recipes_dir}")
    click.echo("使用 'auvima recipe copy <name>' 复制示例 Recipe 到此目录")