#!/usr/bin/env python3
"""
Frago CLI 命令实现

实现所有CDP功能的CLI子命令，保持与原有Shell脚本的兼容性。
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import click

from ..cdp.config import CDPConfig
from ..cdp.exceptions import CDPError
from ..cdp.session import CDPSession


# 全局选项默认值配置
GLOBAL_OPTIONS = {
    'debug': False,
    'timeout': 30,
    'host': '127.0.0.1',
    'port': 9222
}


def _format_ts() -> str:
    """格式化当前时间戳"""
    return datetime.now().strftime("%Y-%m-%d:%H-%M-%S")


def _get_projects_dir() -> Path:
    """
    获取 projects 目录

    优先级：
    1. 当前目录下的 projects/（如果存在 run context）
    2. ~/.frago/config.json 中的 working_directory + /projects
    3. 当前目录下的 projects/（fallback）
    """
    cwd = Path.cwd()

    # 先尝试当前目录
    try:
        from ..run.context import ContextManager
        projects_dir = cwd / "projects"
        ctx_mgr = ContextManager(cwd, projects_dir)
        ctx_mgr.get_current_run()  # 检查是否有活跃 context
        return projects_dir
    except Exception:
        pass

    # 检查全局配置中的工作目录
    try:
        from ..init.configurator import load_config
        config = load_config()
        if config.working_directory:
            return Path(config.working_directory) / "projects"
    except Exception:
        pass

    # fallback: 当前目录
    return cwd / "projects"


def _get_run_dir() -> Path:
    """
    获取当前 run 目录

    优先使用活跃的 run context，无 context 时使用 projects/.tmp/
    """
    projects_dir = _get_projects_dir()

    try:
        from ..run.context import ContextManager
        project_root = projects_dir.parent
        ctx_mgr = ContextManager(project_root, projects_dir)
        context = ctx_mgr.get_current_run()
        return projects_dir / context.run_id
    except Exception:
        # 无 run context，使用 .tmp 目录
        tmp_dir = projects_dir / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir


def _get_run_logger():
    """获取日志记录器（run context 或 .tmp）"""
    try:
        from ..run.logger import RunLogger
        run_dir = _get_run_dir()
        return RunLogger(run_dir)
    except Exception:
        return None


def _write_run_log(
    step: str,
    status: str,
    action_type: str = "other",
    data: Optional[Dict[str, Any]] = None
) -> None:
    """
    写入 run 日志（如果有活跃的 run context）

    Args:
        step: 步骤描述
        status: 状态 (success/error/warning)
        action_type: 操作类型
        data: 额外数据
    """
    logger = _get_run_logger()
    if not logger:
        return

    try:
        from ..run.models import ActionType, ExecutionMethod, LogStatus

        # 映射状态
        status_map = {
            "成功": LogStatus.SUCCESS,
            "失败": LogStatus.ERROR,
            "警告": LogStatus.WARNING,
            "调试": LogStatus.SUCCESS,
        }
        log_status = status_map.get(status, LogStatus.SUCCESS)

        # 映射操作类型
        action_map = {
            "navigation": ActionType.NAVIGATION,
            "interaction": ActionType.INTERACTION,
            "screenshot": ActionType.SCREENSHOT,
            "extraction": ActionType.EXTRACTION,
            "other": ActionType.OTHER,
        }
        log_action = action_map.get(action_type, ActionType.OTHER)

        logger.write_log(
            step=step,
            status=log_status,
            action_type=log_action,
            execution_method=ExecutionMethod.COMMAND,
            data=data or {},
        )
    except Exception:
        # 日志写入失败不应影响命令执行
        pass


def _print_msg(
    status: str,
    message: str,
    action_type: str = "other",
    log_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    打印格式化消息并自动写入 run 日志

    Args:
        status: 状态（成功/失败/警告/调试）
        message: 消息内容
        action_type: 操作类型（navigation/interaction/screenshot/extraction/other）
        log_data: 额外的日志数据
    """
    click.echo(f"{_format_ts()}, {status}, {message}")

    # 自动写入 run 日志
    _write_run_log(message, status, action_type, log_data)


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
    - --target-id: 指定目标tab的ID
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
        no_proxy=ctx.obj.get('NO_PROXY', False),
        target_id=ctx.obj.get('TARGET_ID')
    )
    return CDPSession(config)


def _get_dom_features(session: CDPSession) -> dict:
    """提取页面 DOM 特征"""
    script = """
    (function() {
        const body = document.body;
        const features = {
            title: document.title || '',
            url: window.location.href,
            body_class: body.className || '',
            body_id: body.id || '',
            forms: document.forms.length,
            buttons: document.querySelectorAll('button, input[type="button"], input[type="submit"]').length,
            links: document.querySelectorAll('a[href]').length,
            inputs: document.querySelectorAll('input, textarea, select').length,
            images: document.images.length,
            headings: document.querySelectorAll('h1, h2, h3').length
        };
        // 获取主要内容区域的文本预览
        const main = document.querySelector('main, [role="main"], article, .content, #content') || body;
        const text = (main.innerText || '').replace(/\\s+/g, ' ').trim();
        features.text_preview = text.substring(0, 120) + (text.length > 120 ? '...' : '');
        return features;
    })()
    """
    return session.evaluate(script, return_by_value=True) or {}


def _print_dom_features(features: dict) -> None:
    """打印 DOM 特征摘要"""
    if not features:
        return

    # 构建特征摘要
    body_attrs = []
    if features.get('body_class'):
        body_attrs.append(f"class=\"{features['body_class']}\"")
    if features.get('body_id'):
        body_attrs.append(f"id=\"{features['body_id']}\"")
    body_str = ', '.join(body_attrs) if body_attrs else '(无)'

    elements = f"{features.get('forms', 0)} forms, {features.get('buttons', 0)} buttons, {features.get('links', 0)} links, {features.get('inputs', 0)} inputs"

    _print_msg("成功", f"页面标题: {features.get('title', '(无)')}")
    _print_msg("成功", f"Body属性: {body_str}")
    _print_msg("成功", f"元素统计: {elements}")
    if features.get('text_preview'):
        _print_msg("成功", f"内容预览: {features['text_preview']}")


def _take_perception_screenshot(session: CDPSession, description: str = "page") -> Optional[str]:
    """
    截取感知截图

    Args:
        session: CDP会话
        description: 截图描述，用于生成文件名

    Returns:
        截图文件路径，失败时返回 None
    """
    try:
        from ..run.screenshot import get_next_screenshot_number
        from slugify import slugify
        import base64

        screenshots_dir = _get_run_screenshots_dir()
        seq = get_next_screenshot_number(screenshots_dir)
        desc_slug = slugify(description or 'page', max_length=40)
        filename = f"{seq:03d}_{desc_slug}.png"
        file_path = screenshots_dir / filename

        result = session.screenshot.capture()
        screenshot_data = base64.b64decode(result.get("data", ""))
        file_path.write_bytes(screenshot_data)

        return str(file_path)
    except Exception:
        return None


def _do_perception(session: CDPSession, action_desc: str, no_screenshot: bool = False) -> None:
    """
    执行操作后的感知：获取 DOM 特征并截图

    Args:
        session: CDP会话
        action_desc: 操作描述，用于截图文件名
        no_screenshot: 是否禁用截图
    """
    # 获取并打印 DOM 特征
    features = _get_dom_features(session)
    _print_dom_features(features)

    # 截图
    if not no_screenshot:
        screenshot_path = _take_perception_screenshot(
            session,
            features.get('title') or action_desc
        )
        if screenshot_path:
            _print_msg("成功", f"截图保存: {screenshot_path}")


def _get_run_screenshots_dir() -> Path:
    """获取截图目录（run context 或 .tmp）"""
    run_dir = _get_run_dir()
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    return screenshots_dir


@click.command('navigate')
@click.argument('url')
@click.option(
    '--wait-for',
    type=str,
    help='等待选择器出现后再返回'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.option(
    '--load-timeout',
    type=float,
    default=30,
    help='等待页面加载完成的超时时间（秒），默认30'
)
@click.pass_context
def navigate(ctx, url: str, wait_for: Optional[str] = None, no_screenshot: bool = False, load_timeout: float = 30):
    """导航到指定URL，等待加载完成后获取页面特征并截图"""
    try:
        with create_session(ctx) as session:
            # 1. 导航
            session.navigate(url)
            _print_msg("成功", f"导航到 {url}", "navigation", {"url": url})

            # 2. 等待页面加载完成
            session.wait_for_load(timeout=load_timeout)
            _print_msg("成功", "页面加载完成", "navigation")

            # 3. 如果指定了选择器，额外等待
            if wait_for:
                session.wait_for_selector(wait_for)
                _print_msg("成功", f"选择器就绪: {wait_for}", "navigation", {"selector": wait_for})

            # 4. 感知：获取 DOM 特征 + 截图
            _do_perception(session, f"navigate-{url}", no_screenshot)

    except CDPError as e:
        _print_msg("失败", f"导航失败: {e}", "navigation", {"url": url, "error": str(e)})
        sys.exit(1)


@click.command('click')
@click.argument('selector')
@click.option(
    '--wait-timeout',
    type=int,
    default=10,
    help='等待元素出现的超时时间（秒）'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def click_element(ctx, selector: str, wait_timeout: int, no_screenshot: bool = False):
    """点击指定选择器的元素，自动获取页面特征并截图"""
    try:
        with create_session(ctx) as session:
            session.click(selector, wait_timeout=wait_timeout)
            _print_msg("成功", f"点击元素: {selector}", "interaction", {"selector": selector})

            # 点击后短暂等待页面响应
            time.sleep(0.5)

            # 感知：获取 DOM 特征 + 截图
            _do_perception(session, f"click-{selector}", no_screenshot)

    except CDPError as e:
        _print_msg("失败", f"点击失败: {e}", "interaction", {"selector": selector, "error": str(e)})
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
            _print_msg("成功", f"截图保存到: {output_file}", "screenshot", {"file": output_file, "full_page": full_page})
    except CDPError as e:
        _print_msg("失败", f"截图失败: {e}", "screenshot", {"file": output_file, "error": str(e)})
        sys.exit(1)


@click.command('exec-js')
@click.argument('script')
@click.option(
    '--return-value',
    is_flag=True,
    help='返回JavaScript执行结果'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def execute_javascript(ctx, script: str, return_value: bool, no_screenshot: bool = False):
    """
    执行JavaScript代码，自动获取页面特征并截图

    SCRIPT 参数可以是直接的JavaScript代码，也可以是包含代码的文件路径。
    """
    try:
        # 检查是否为文件路径
        if os.path.exists(script) and os.path.isfile(script):
            try:
                with open(script, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                if ctx.obj['DEBUG']:
                    _print_msg("调试", f"从文件加载脚本: {script}", "interaction")
                script = script_content
            except Exception as e:
                _print_msg("失败", f"无法读取脚本文件: {e}", "interaction", {"error": str(e)})
                sys.exit(1)

        with create_session(ctx) as session:
            result = session.evaluate(script, return_by_value=return_value)
            if return_value:
                _print_msg("成功", f"执行结果: {result}", "interaction", {"result": str(result)})
            else:
                _print_msg("成功", "JavaScript执行完成", "interaction")

            # JS执行后短暂等待
            time.sleep(0.3)

            # 感知：获取 DOM 特征 + 截图
            _do_perception(session, "exec-js", no_screenshot)

    except CDPError as e:
        _print_msg("失败", f"JavaScript执行失败: {e}", "interaction", {"error": str(e)})
        sys.exit(1)


@click.command('get-title')
@click.pass_context
def get_title(ctx):
    """获取页面标题"""
    try:
        with create_session(ctx) as session:
            title = session.get_title()
            _print_msg("成功", f"页面标题: {title}", "extraction", {"title": title})
    except CDPError as e:
        _print_msg("失败", f"获取标题失败: {e}", "extraction", {"error": str(e)})
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
                _print_msg("失败", f"找不到元素: {selector}", "extraction", {"selector": selector})
                sys.exit(1)
            _print_msg("成功", f"获取内容 ({selector}):\n{content if content else ''}", "extraction", {"selector": selector})
    except CDPError as e:
        _print_msg("失败", f"获取内容失败: {e}", "extraction", {"selector": selector, "error": str(e)})
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
                _print_msg("成功", "CDP连接正常")
                _print_msg("成功", f"Browser: {chrome_status.get('Browser', 'unknown')}")
                _print_msg("成功", f"Protocol-Version: {chrome_status.get('Protocol-Version', 'unknown')}")
                _print_msg("成功", f"WebKit-Version: {chrome_status.get('WebKit-Version', 'unknown')}")
            else:
                _print_msg("失败", "CDP连接失败")
                sys.exit(1)
    except CDPError as e:
        _print_msg("失败", f"状态检查失败: {e}")
        sys.exit(1)


@click.command('scroll')
@click.argument('distance', type=int)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def scroll(ctx, distance: int, no_screenshot: bool = False):
    """滚动页面，自动获取页面特征并截图"""
    try:
        with create_session(ctx) as session:
            session.scroll.scroll(distance)
            _print_msg("成功", f"滚动 {distance} 像素", "interaction", {"distance": distance})

            # 滚动后短暂等待
            time.sleep(0.3)

            # 感知：获取 DOM 特征 + 截图
            _do_perception(session, f"scroll-{distance}px", no_screenshot)

    except CDPError as e:
        _print_msg("失败", f"滚动失败: {e}", "interaction", {"distance": distance, "error": str(e)})
        sys.exit(1)


@click.command('scroll-to')
@click.argument('selector')
@click.option(
    '--block',
    type=click.Choice(['start', 'center', 'end', 'nearest']),
    default='center',
    help='垂直对齐方式 (默认: center)'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def scroll_to(ctx, selector: str, block: str = 'center', no_screenshot: bool = False):
    """滚动到指定元素"""
    try:
        with create_session(ctx) as session:
            # 使用 scrollIntoView
            js_code = f'''
            (function() {{
                const el = document.querySelector({repr(selector)});
                if (el) {{
                    el.scrollIntoView({{behavior: 'smooth', block: '{block}'}});
                    return 'success';
                }} else {{
                    return 'element not found';
                }}
            }})()
            '''
            result = session.evaluate(js_code, return_by_value=True)

            if result == 'success':
                _print_msg("成功", f"滚动到元素: {selector}", "interaction", {"selector": selector, "block": block})
                time.sleep(0.5)  # 等待滚动动画完成
                _do_perception(session, f"scroll-to-{selector[:30]}", no_screenshot)
            else:
                _print_msg("失败", f"元素未找到: {selector}", "interaction", {"selector": selector})
                sys.exit(1)

    except CDPError as e:
        _print_msg("失败", f"滚动到元素失败: {e}", "interaction", {"selector": selector, "error": str(e)})
        sys.exit(1)


@click.command('wait')
@click.argument('seconds', type=float)
@click.pass_context
def wait(ctx, seconds: float):
    """等待指定秒数"""
    try:
        with create_session(ctx) as session:
            session.wait.wait(seconds)
            _print_msg("成功", f"等待 {seconds} 秒完成")
    except CDPError as e:
        _print_msg("失败", f"等待失败: {e}")
        sys.exit(1)


@click.command('zoom')
@click.argument('factor', type=float)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def zoom(ctx, factor: float, no_screenshot: bool = False):
    """设置页面缩放比例，自动获取页面特征并截图"""
    try:
        with create_session(ctx) as session:
            session.zoom(factor)
            _print_msg("成功", f"页面缩放设置为: {factor}", "interaction", {"zoom_factor": factor})

            # 缩放后短暂等待
            time.sleep(0.2)

            # 感知：获取 DOM 特征 + 截图
            _do_perception(session, f"zoom-{factor}x", no_screenshot)

    except CDPError as e:
        _print_msg("失败", f"缩放失败: {e}", "interaction", {"zoom_factor": factor, "error": str(e)})
        sys.exit(1)


@click.command('clear-effects')
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def clear_effects(ctx, no_screenshot: bool = False):
    """清除所有视觉效果，自动截图"""
    try:
        with create_session(ctx) as session:
            session.clear_effects()
            _print_msg("成功", "视觉效果已清除", "interaction")

            # 截图（不提取 DOM 特征）
            if not no_screenshot:
                screenshot_path = _take_perception_screenshot(session, "clear-effects")
                if screenshot_path:
                    _print_msg("成功", f"截图保存: {screenshot_path}", "screenshot", {"file": screenshot_path})

    except CDPError as e:
        _print_msg("失败", f"清除效果失败: {e}", "interaction", {"error": str(e)})
        sys.exit(1)


@click.command('highlight')
@click.argument('selector')
@click.option(
    '--color',
    type=str,
    default='magenta',
    help='高亮颜色，默认洋红'
)
@click.option(
    '--width',
    type=int,
    default=3,
    help='高亮边框宽度（像素），默认3'
)
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='效果持续时间（秒），默认5秒'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='始终显示直到手动clear'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def highlight(ctx, selector: str, color: str, width: int, life_time: int, longlife: bool, no_screenshot: bool = False):
    """高亮显示指定元素，自动截图"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.highlight(selector, color=color, border_width=width, lifetime=lifetime_ms)
            _print_msg("成功", f"高亮元素: {selector} (颜色: {color}, 宽度: {width}px, 持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector, "color": color, "width": width})

            # 截图（不提取 DOM 特征）
            if not no_screenshot:
                screenshot_path = _take_perception_screenshot(session, f"highlight-{selector}")
                if screenshot_path:
                    _print_msg("成功", f"截图保存: {screenshot_path}", "screenshot", {"file": screenshot_path})

    except CDPError as e:
        _print_msg("失败", f"高亮失败: {e}", "interaction", {"selector": selector, "error": str(e)})
        sys.exit(1)


@click.command('pointer')
@click.argument('selector')
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='效果持续时间（秒），默认5秒'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='始终显示直到手动clear'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def pointer(ctx, selector: str, life_time: int, longlife: bool, no_screenshot: bool = False):
    """在元素上显示鼠标指针，自动截图"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.pointer(selector, lifetime=lifetime_ms)
            _print_msg("成功", f"显示指针: {selector} (持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector})

            # 截图（不提取 DOM 特征）
            if not no_screenshot:
                screenshot_path = _take_perception_screenshot(session, f"pointer-{selector}")
                if screenshot_path:
                    _print_msg("成功", f"截图保存: {screenshot_path}", "screenshot", {"file": screenshot_path})

    except CDPError as e:
        _print_msg("失败", f"显示指针失败: {e}", "interaction", {"selector": selector, "error": str(e)})
        sys.exit(1)


@click.command('spotlight')
@click.argument('selector')
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='效果持续时间（秒），默认5秒'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='始终显示直到手动clear'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def spotlight(ctx, selector: str, life_time: int, longlife: bool, no_screenshot: bool = False):
    """聚光灯效果显示元素，自动截图"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.spotlight(selector, lifetime=lifetime_ms)
            _print_msg("成功", f"聚光灯显示: {selector} (持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector})

            # 截图（不提取 DOM 特征）
            if not no_screenshot:
                screenshot_path = _take_perception_screenshot(session, f"spotlight-{selector}")
                if screenshot_path:
                    _print_msg("成功", f"截图保存: {screenshot_path}", "screenshot", {"file": screenshot_path})

    except CDPError as e:
        _print_msg("失败", f"聚光灯失败: {e}", "interaction", {"selector": selector, "error": str(e)})
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
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='效果持续时间（秒），默认5秒'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='始终显示直到手动clear'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def annotate(ctx, selector: str, text: str, position: str, life_time: int, longlife: bool, no_screenshot: bool = False):
    """在元素上添加标注，自动截图"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.annotate(selector, text, position=position, lifetime=lifetime_ms)
            _print_msg("成功", f"添加标注: {text} ({selector}) (持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector, "text": text, "position": position})

            # 截图（不提取 DOM 特征）
            if not no_screenshot:
                screenshot_path = _take_perception_screenshot(session, f"annotate-{selector}")
                if screenshot_path:
                    _print_msg("成功", f"截图保存: {screenshot_path}", "screenshot", {"file": screenshot_path})

    except CDPError as e:
        _print_msg("失败", f"添加标注失败: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})
        sys.exit(1)


@click.command('underline')
@click.argument('selector')
@click.option(
    '--color',
    type=str,
    default='magenta',
    help='线条颜色，默认洋红'
)
@click.option(
    '--width',
    type=int,
    default=3,
    help='线条宽度（像素），默认3'
)
@click.option(
    '--duration',
    type=int,
    default=1000,
    help='动画总时长（毫秒），默认1000'
)
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='效果持续时间（秒），默认5秒'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='始终显示直到手动clear'
)
@click.option(
    '--no-screenshot',
    is_flag=True,
    help='不自动截图'
)
@click.pass_context
def underline(ctx, selector: str, color: str, width: int, duration: int, life_time: int, longlife: bool, no_screenshot: bool = False):
    """在元素文本底部逐行画线动画，自动截图"""
    import json
    lifetime_ms = 0 if longlife else life_time * 1000

    # 直接用 JS 实现，避免 Python f-string 转义问题
    js_code = """
(function(selector, color, width, duration, lifetime) {
    const elements = document.querySelectorAll(selector);
    elements.forEach(el => {
        const range = document.createRange();
        range.selectNodeContents(el);
        const allRects = Array.from(range.getClientRects());

        const lineMap = new Map();
        allRects.forEach(rect => {
            if (rect.width <= 0 || rect.height <= 0) return;
            const topKey = Math.round(rect.top);
            if (lineMap.has(topKey)) {
                const existing = lineMap.get(topKey);
                existing.left = Math.min(existing.left, rect.left);
                existing.right = Math.max(existing.right, rect.right);
                existing.bottom = Math.max(existing.bottom, rect.bottom);
            } else {
                lineMap.set(topKey, { left: rect.left, right: rect.right, bottom: rect.bottom });
            }
        });

        const lines = Array.from(lineMap.values())
            .map(l => ({ left: l.left, top: l.bottom, width: l.right - l.left }))
            .sort((a, b) => a.top - b.top);

        if (lines.length === 0) return;

        const createdElements = [];
        lines.forEach((line, index) => {
            const u = document.createElement('div');
            u.className = 'frago-underline';
            u.style.position = 'fixed';
            u.style.left = line.left + 'px';
            u.style.top = line.top + 'px';
            u.style.width = line.width + 'px';
            u.style.height = width + 'px';
            u.style.backgroundColor = color;
            u.style.zIndex = '999999';
            u.style.pointerEvents = 'none';
            document.body.appendChild(u);
            createdElements.push(u);
        });
        if (lifetime > 0) {
            setTimeout(() => createdElements.forEach(el => el.remove()), lifetime);
        }
    });
})(""" + json.dumps(selector) + "," + json.dumps(color) + "," + str(width) + "," + str(duration) + "," + str(lifetime_ms) + ")"

    try:
        with create_session(ctx) as session:
            session.evaluate(js_code)
            _print_msg("成功", f"划线元素: {selector} (颜色: {color}, 宽度: {width}px, 持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector, "color": color, "width": width, "duration": duration})

            # 截图（不提取 DOM 特征）
            if not no_screenshot:
                screenshot_path = _take_perception_screenshot(session, f"underline-{selector}")
                if screenshot_path:
                    _print_msg("成功", f"截图保存: {screenshot_path}", "screenshot", {"file": screenshot_path})

    except CDPError as e:
        _print_msg("失败", f"划线失败: {e}", "interaction", {"selector": selector, "error": str(e)})
        sys.exit(1)


@click.command('init')
@click.option(
    '--force',
    is_flag=True,
    help='强制重新创建已存在的目录'
)
def init(force: bool):
    """
    初始化 Frago 用户级目录结构

    创建 ~/.frago/recipes/ 目录及其子目录:
    - atomic/chrome/: Chrome CDP 操作的 Recipe
    - atomic/system/: 系统操作的 Recipe
    - workflows/: 编排多个 Recipe 的工作流
    """
    from pathlib import Path

    user_home = Path.home()
    frago_dir = user_home / '.frago'
    recipes_dir = frago_dir / 'recipes'

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
    click.echo("使用 'frago recipe copy <name>' 复制示例 Recipe 到此目录")


# ============================================================
# Chrome 浏览器管理命令
# ============================================================


@click.command('chrome')
@click.option(
    '--headless',
    is_flag=True,
    help='无头模式：无窗口运行'
)
@click.option(
    '--void',
    is_flag=True,
    help='虚空模式：窗口移到屏幕外（不影响当前桌面）'
)
@click.option(
    '--port',
    type=int,
    default=9222,
    help='CDP 调试端口，默认 9222'
)
@click.option(
    '--width',
    type=int,
    default=1280,
    help='窗口宽度，默认 1280'
)
@click.option(
    '--height',
    type=int,
    default=960,
    help='窗口高度，默认 960'
)
@click.option(
    '--profile-dir',
    type=click.Path(),
    help='Chrome 用户数据目录（默认 ~/.frago/chrome_profile）'
)
@click.option(
    '--no-kill',
    is_flag=True,
    help='不关闭已存在的 CDP Chrome 进程'
)
@click.option(
    '--keep-alive',
    is_flag=True,
    help='启动后保持运行，直到 Ctrl+C'
)
def chrome_start(headless: bool, void: bool, port: int, width: int, height: int,
                 profile_dir: str, no_kill: bool, keep_alive: bool):
    """
    启动 Chrome 浏览器（带 CDP 调试支持）

    \b
    模式说明:
      默认    - 正常窗口模式
      --headless - 无界面运行
      --void     - 窗口隐藏到屏幕外

    \b
    示例:
      frago chrome                    # 正常启动
      frago chrome --headless         # 无头模式
      frago chrome --void             # 虚空模式
      frago chrome --port 9333        # 使用其他端口
      frago chrome --keep-alive       # 启动后保持运行
    """
    from ..cdp.commands.chrome import ChromeLauncher
    from pathlib import Path

    # headless 和 void 互斥
    if headless and void:
        click.echo("警告: --headless 和 --void 不能同时使用，将使用 --headless 模式")
        void = False

    profile_path = Path(profile_dir) if profile_dir else None

    launcher = ChromeLauncher(
        headless=headless,
        void=void,
        port=port,
        width=width,
        height=height,
        profile_dir=profile_path,
    )

    # 检查 Chrome 是否存在
    if not launcher.chrome_path:
        click.echo("错误: 未找到 Chrome 浏览器", err=True)
        click.echo("请安装 Google Chrome 或 Chromium 浏览器", err=True)
        sys.exit(1)

    click.echo(f"Chrome 路径: {launcher.chrome_path}")
    click.echo(f"Profile 目录: {launcher.profile_dir}")
    click.echo(f"CDP 端口: {port}")
    click.echo(f"模式: {'headless' if headless else 'void' if void else '正常窗口'}")

    # 启动 Chrome
    if launcher.launch(kill_existing=not no_kill):
        click.echo(f"\n✓ Chrome 已启动，CDP 监听端口: {port}")

        # 获取并显示状态
        status_info = launcher.get_status()
        if status_info.get("running"):
            click.echo(f"Browser: {status_info.get('browser', 'unknown')}")

        if keep_alive:
            click.echo("\n按 Ctrl+C 停止 Chrome...")

            import signal

            def signal_handler(_signum, _frame):
                click.echo("\n正在关闭 Chrome...")
                launcher.stop()
                sys.exit(0)

            signal.signal(signal.SIGINT, signal_handler)

            try:
                while True:
                    time.sleep(30)
                    # 定期检查状态
                    st = launcher.get_status()
                    if not st.get("running"):
                        click.echo("Chrome 进程已退出")
                        break
            except KeyboardInterrupt:
                pass
            finally:
                launcher.stop()
    else:
        click.echo("✗ Chrome 启动失败", err=True)
        sys.exit(1)


@click.command('chrome-stop')
@click.option(
    '--port',
    type=int,
    default=9222,
    help='CDP 调试端口，默认 9222'
)
def chrome_stop(port: int):
    """
    停止 Chrome CDP 进程

    关闭指定端口上运行的 Chrome CDP 实例。
    """
    from ..cdp.commands.chrome import ChromeLauncher

    launcher = ChromeLauncher(port=port)
    killed = launcher.kill_existing_chrome()

    if killed > 0:
        click.echo(f"✓ 已关闭 {killed} 个 Chrome CDP 进程（端口 {port}）")
    else:
        click.echo(f"未找到运行在端口 {port} 的 Chrome CDP 进程")


@click.command('list-tabs')
@click.pass_context
def list_tabs(ctx):
    """
    列出所有打开的浏览器 tabs

    显示每个 tab 的 ID、标题和 URL，用于 switch-tab 命令。
    """
    import requests
    import json

    config = ctx.obj or {}
    host = config.get('host', GLOBAL_OPTIONS['host'])
    port = config.get('port', GLOBAL_OPTIONS['port'])

    try:
        response = requests.get(f'http://{host}:{port}/json/list', timeout=5)
        targets = response.json()

        pages = [t for t in targets if t.get('type') == 'page']

        if not pages:
            click.echo("没有找到打开的 tabs")
            return

        # 输出 JSON 格式便于程序解析
        output = []
        for i, p in enumerate(pages):
            tab_info = {
                "index": i,
                "id": p.get('id'),
                "title": p.get('title', 'No Title'),
                "url": p.get('url', '')
            }
            output.append(tab_info)
            click.echo(f"{i}. [{p.get('id')[:8]}...] {p.get('title', 'No Title')[:50]}")
            click.echo(f"   {p.get('url', '')}")

    except Exception as e:
        click.echo(f"获取 tabs 列表失败: {e}", err=True)
        sys.exit(1)


@click.command('switch-tab')
@click.argument('tab_id')
@click.pass_context
def switch_tab(ctx, tab_id: str):
    """
    切换到指定的浏览器 tab

    TAB_ID 可以是完整的 target ID 或部分匹配（如前8位）。
    使用 list-tabs 命令查看可用的 tab ID。
    """
    import requests
    import json
    import websocket

    config = ctx.obj or {}
    host = config.get('host', GLOBAL_OPTIONS['host'])
    port = config.get('port', GLOBAL_OPTIONS['port'])

    try:
        response = requests.get(f'http://{host}:{port}/json/list', timeout=5)
        targets = response.json()

        # 查找匹配的 tab
        target = None
        for t in targets:
            if t.get('type') == 'page':
                if t.get('id') == tab_id or t.get('id', '').startswith(tab_id):
                    target = t
                    break

        if not target:
            click.echo(f"未找到匹配的 tab: {tab_id}", err=True)
            click.echo("使用 list-tabs 命令查看可用的 tabs")
            sys.exit(1)

        ws_url = target.get('webSocketDebuggerUrl')
        if not ws_url:
            click.echo(f"Tab {tab_id} 没有可用的 WebSocket URL", err=True)
            sys.exit(1)

        # 发送 Page.bringToFront 命令
        ws = websocket.create_connection(ws_url)
        ws.send(json.dumps({'id': 1, 'method': 'Page.bringToFront', 'params': {}}))
        result = json.loads(ws.recv())
        ws.close()

        if 'error' in result:
            click.echo(f"切换失败: {result['error']}", err=True)
            sys.exit(1)

        _print_msg("成功", f"已切换到 tab: {target.get('title', 'Unknown')}", "tab_switch", {
            "tab_id": target.get('id'),
            "title": target.get('title'),
            "url": target.get('url')
        })

    except Exception as e:
        click.echo(f"切换 tab 失败: {e}", err=True)
        sys.exit(1)