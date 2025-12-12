#!/usr/bin/env python3
"""
Frago CLI 命令实现

实现所有CDP功能的CLI子命令，保持与原有Shell脚本的兼容性。
"""

import functools
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import click


# =============================================================================
# 命令用法示例（Agent 友好输出）
# =============================================================================

COMMAND_EXAMPLES = {
    # Chrome 子命令（使用完整路径，便于 agent 直接复制）
    "navigate": [
        "frago chrome navigate <url>",
        "frago chrome navigate https://example.com",
        "frago chrome navigate https://example.com --wait-for '.content-loaded'",
    ],
    "click": [
        "frago chrome click <selector>",
        "frago chrome click 'button.submit'",
        "frago chrome click '#login-btn' --wait-timeout 15",
    ],
    "screenshot": [
        "frago chrome screenshot <output_file>",
        "frago chrome screenshot page.png",
        "frago chrome screenshot full.png --full-page --quality 90",
    ],
    "exec-js": [
        "frago chrome exec-js <script>",
        "frago chrome exec-js 'document.title'",
        "frago chrome exec-js 'return window.scrollY' --return-value",
        "frago chrome exec-js ./script.js  # 从文件加载",
    ],
    "get-title": [
        "frago chrome get-title",
    ],
    "get-content": [
        "frago chrome get-content [selector]",
        "frago chrome get-content  # 默认获取 body",
        "frago chrome get-content 'article.main' --desc 'article-content'",
    ],
    "scroll": [
        "frago chrome scroll <distance>",
        "frago chrome scroll 500      # 向下滚动 500px",
        "frago chrome scroll -300     # 向上滚动 300px",
        "frago chrome scroll down     # 别名: 向下 500px",
        "frago chrome scroll up       # 别名: 向上 500px",
    ],
    "scroll-to": [
        "frago chrome scroll-to <selector>",
        "frago chrome scroll-to 'article'",
        "frago chrome scroll-to --text 'Section Title'",
        "frago chrome scroll-to '#footer' --block end",
    ],
    "wait": [
        "frago chrome wait <seconds>",
        "frago chrome wait 2",
        "frago chrome wait 0.5",
    ],
    "zoom": [
        "frago chrome zoom <factor>",
        "frago chrome zoom 1.5   # 放大到 150%",
        "frago chrome zoom 0.8   # 缩小到 80%",
        "frago chrome zoom 1     # 恢复原始大小",
    ],
    "clear-effects": [
        "frago chrome clear-effects",
    ],
    "highlight": [
        "frago chrome highlight <selector>",
        "frago chrome highlight 'button.primary'",
        "frago chrome highlight '#target' --color red --width 5",
        "frago chrome highlight '.element' --longlife  # 永久显示",
    ],
    "pointer": [
        "frago chrome pointer <selector>",
        "frago chrome pointer 'button.submit'",
        "frago chrome pointer '#element' --life-time 10",
    ],
    "spotlight": [
        "frago chrome spotlight <selector>",
        "frago chrome spotlight '.highlight-me'",
        "frago chrome spotlight '#focus' --longlife",
    ],
    "annotate": [
        "frago chrome annotate <selector> <text>",
        "frago chrome annotate 'button' 'Click here'",
        "frago chrome annotate '#form' 'Fill this' --position bottom",
    ],
    "underline": [
        "frago chrome underline <selector>",
        "frago chrome underline 'article p'",
        "frago chrome underline --text 'Important text'",
        "frago chrome underline '.content' --color blue --width 2",
    ],
    "start": [
        "frago chrome start",
        "frago chrome start --headless",
        "frago chrome start --void --keep-alive",
        "frago chrome start --port 9333 --width 1920 --height 1080",
    ],
    "stop": [
        "frago chrome stop",
        "frago chrome stop --port 9333",
    ],
    "list-tabs": [
        "frago chrome list-tabs",
    ],
    "switch-tab": [
        "frago chrome switch-tab <tab_id>",
        "frago chrome switch-tab ABC123  # 支持部分 ID 匹配",
    ],
    # 顶层命令
    "status": [
        "frago status",
        "frago chrome status  # 等效",
    ],
    "init": [
        "frago init",
        "frago init --force",
    ],
    # chrome 命令组自身（显示子命令概览）
    "chrome": [
        "frago chrome <command>",
        "frago chrome start      # 启动浏览器",
        "frago chrome navigate   # 导航到 URL",
        "frago chrome click      # 点击元素",
        "frago chrome screenshot # 截图",
    ],
    # frago 顶层命令
    "frago": [
        "frago <command>",
        "frago chrome start      # 启动浏览器",
        "frago status            # 检查 CDP 连接状态",
        "frago --gui             # 启动 GUI 应用",
    ],
}


def print_usage(func):
    """
    装饰器：在命令执行前打印用法示例

    帮助 AI Agent 在跟踪输出时直接理解命令的正确用法。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 从函数名推断命令名（下划线转连字符）
        cmd_name = func.__name__.replace('_', '-')
        # 特殊映射
        name_map = {
            "click-element": "click",
            "execute-javascript": "exec-js",
            "chrome-start": "chrome",
            "init-dirs": "init",
        }
        cmd_name = name_map.get(cmd_name, cmd_name)

        examples = COMMAND_EXAMPLES.get(cmd_name)
        if examples:
            click.echo(f"[用法] {examples[0]}")
            for ex in examples[1:]:
                click.echo(f"       {ex}")
            click.echo("")  # 空行分隔

        return func(*args, **kwargs)
    return wrapper

from ..cdp.config import CDPConfig
from ..cdp.exceptions import CDPError
from ..cdp.session import CDPSession


# =============================================================================
# 自定义参数类型（提供友好的错误提示和使用示例）
# =============================================================================


class ScrollDistanceType(click.ParamType):
    """滚动距离参数类型，支持像素值或 up/down 别名"""
    name = "distance"

    def convert(self, value, param, ctx):
        # 支持 up/down 别名
        aliases = {"up": -500, "down": 500, "page-up": -800, "page-down": 800}
        if isinstance(value, str) and value.lower() in aliases:
            return aliases[value.lower()]

        try:
            return int(value)
        except (ValueError, TypeError):
            self.fail(
                f"'{value}' 不是有效的滚动距离。\n\n"
                "正确用法:\n"
                "  frago scroll 500       # 向下滚动 500 像素\n"
                "  frago scroll -300      # 向上滚动 300 像素\n"
                "  frago scroll down      # 向下滚动 500 像素 (别名)\n"
                "  frago scroll up        # 向上滚动 500 像素 (别名)\n"
                "  frago scroll-to 'selector'  # 滚动到指定元素",
                param,
                ctx,
            )


class ZoomFactorType(click.ParamType):
    """缩放因子参数类型"""
    name = "factor"

    def convert(self, value, param, ctx):
        try:
            factor = float(value)
            if factor <= 0:
                raise ValueError("必须大于 0")
            return factor
        except (ValueError, TypeError):
            self.fail(
                f"'{value}' 不是有效的缩放因子。\n\n"
                "正确用法:\n"
                "  frago zoom 1.5    # 放大到 150%\n"
                "  frago zoom 0.8    # 缩小到 80%\n"
                "  frago zoom 1      # 恢复原始大小",
                param,
                ctx,
            )


class WaitSecondsType(click.ParamType):
    """等待秒数参数类型"""
    name = "seconds"

    def convert(self, value, param, ctx):
        try:
            seconds = float(value)
            if seconds < 0:
                raise ValueError("不能为负数")
            return seconds
        except (ValueError, TypeError):
            self.fail(
                f"'{value}' 不是有效的等待时间。\n\n"
                "正确用法:\n"
                "  frago wait 2      # 等待 2 秒\n"
                "  frago wait 0.5    # 等待 0.5 秒",
                param,
                ctx,
            )


# 实例化自定义类型
SCROLL_DISTANCE = ScrollDistanceType()
ZOOM_FACTOR = ZoomFactorType()
WAIT_SECONDS = WaitSecondsType()


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

    统一使用 ~/.frago/projects/
    """
    return Path.home() / ".frago" / "projects"


def _get_run_dir() -> Path:
    """
    获取当前 run 目录

    优先使用活跃的 run context，无 context 时使用 projects/.tmp/
    """
    frago_home = Path.home() / ".frago"
    projects_dir = _get_projects_dir()

    try:
        from ..run.context import ContextManager
        ctx_mgr = ContextManager(frago_home, projects_dir)
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
    """提取页面 DOM 特征，重点关注当前可视区域内容"""
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

        // 获取当前可视区域内的文本内容
        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;

        // 收集视口内可见元素的文本
        const visibleTexts = [];
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function(node) {
                    const parent = node.parentElement;
                    if (!parent) return NodeFilter.FILTER_REJECT;
                    const style = window.getComputedStyle(parent);
                    if (style.display === 'none' || style.visibility === 'hidden') {
                        return NodeFilter.FILTER_REJECT;
                    }
                    const rect = parent.getBoundingClientRect();
                    // 检查元素是否在视口内
                    if (rect.bottom < 0 || rect.top > viewportHeight ||
                        rect.right < 0 || rect.left > viewportWidth) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    const text = node.textContent.trim();
                    if (text.length < 2) return NodeFilter.FILTER_REJECT;
                    return NodeFilter.FILTER_ACCEPT;
                }
            }
        );

        let charCount = 0;
        const maxChars = 300;
        while (walker.nextNode() && charCount < maxChars) {
            const text = walker.currentNode.textContent.trim();
            if (text) {
                visibleTexts.push(text);
                charCount += text.length;
            }
        }

        const visibleContent = visibleTexts.join(' ').replace(/\\s+/g, ' ').trim();
        features.visible_content = visibleContent.substring(0, 300) + (visibleContent.length > 300 ? '...' : '');
        features.scroll_y = Math.round(window.scrollY);

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

    # 输出滚动位置和可视区域内容
    scroll_y = features.get('scroll_y', 0)
    _print_msg("成功", f"滚动位置: scrollY={scroll_y}px")

    if features.get('visible_content'):
        _print_msg("成功", f"可视内容: {features['visible_content']}")


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


def _do_perception(session: CDPSession, action_desc: str, delay: float = 0) -> None:
    """
    执行操作后的感知：获取 DOM 特征

    注意：不再自动截图。截图应由用户显式调用 screenshot 命令。
    理由：减少对模型的暗示，避免模型过度依赖截图而忽略结构化数据提取。

    Args:
        session: CDP会话
        action_desc: 操作描述（保留用于日志）
        delay: 获取 DOM 特征前的延迟（秒），用于等待页面加载
    """
    # 可选延迟
    if delay > 0:
        time.sleep(delay)

    # 获取并打印 DOM 特征
    features = _get_dom_features(session)
    _print_dom_features(features)


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
    '--load-timeout',
    type=float,
    default=30,
    help='等待页面加载完成的超时时间（秒），默认30'
)
@click.pass_context
@print_usage
def navigate(ctx, url: str, wait_for: Optional[str] = None, load_timeout: float = 30):
    """导航到指定URL，等待加载完成后获取页面特征"""
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

            # 4. 感知：获取 DOM 特征（延迟2秒让动态内容加载）
            _do_perception(session, f"navigate-{url}", delay=2.0)

    except CDPError as e:
        _print_msg("失败", f"导航失败: {e}", "navigation", {"url": url, "error": str(e)})


@click.command('click')
@click.argument('selector')
@click.option(
    '--wait-timeout',
    type=int,
    default=10,
    help='等待元素出现的超时时间（秒）'
)
@click.pass_context
@print_usage
def click_element(ctx, selector: str, wait_timeout: int):
    """点击指定选择器的元素，自动获取页面特征"""
    try:
        with create_session(ctx) as session:
            session.click(selector, wait_timeout=wait_timeout)
            _print_msg("成功", f"点击元素: {selector}", "interaction", {"selector": selector})

            # 点击后短暂等待页面响应
            time.sleep(0.5)

            # 感知：获取 DOM 特征
            _do_perception(session, f"click-{selector}")

    except CDPError as e:
        _print_msg("失败", f"点击失败: {e}", "interaction", {"selector": selector, "error": str(e)})


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
@print_usage
def screenshot(ctx, output_file: str, full_page: bool, quality: int):
    """
    截取页面截图

    如果存在活跃的 run context，截图将保存到 run 的 screenshots 目录，
    OUTPUT_FILE 将作为描述用于生成文件名（自动编号）。

    如果没有 run context，OUTPUT_FILE 作为完整文件路径使用。
    """
    try:
        # 检测是否有活跃的 run context
        actual_output_file = output_file
        try:
            from ..run.screenshot import get_next_screenshot_number
            from slugify import slugify

            screenshots_dir = _get_run_screenshots_dir()
            run_dir = _get_run_dir()

            # 检查是否是 .tmp 目录（无 run context）
            if run_dir.name != ".tmp":
                # 有 run context，将 output_file 作为描述生成文件名
                # 去掉可能的扩展名作为描述
                description = Path(output_file).stem
                seq = get_next_screenshot_number(screenshots_dir)
                desc_slug = slugify(description or 'screenshot', max_length=40)
                filename = f"{seq:03d}_{desc_slug}.png"
                actual_output_file = str(screenshots_dir / filename)
        except Exception:
            # 获取 run context 失败，使用原始路径
            pass

        with create_session(ctx) as session:
            session.screenshot.capture(actual_output_file, full_page=full_page, quality=quality)
            _print_msg("成功", f"截图保存到: {actual_output_file}", "screenshot", {"file": actual_output_file, "full_page": full_page})
    except CDPError as e:
        _print_msg("失败", f"截图失败: {e}", "screenshot", {"file": output_file, "error": str(e)})


@click.command('exec-js')
@click.argument('script')
@click.option(
    '--return-value',
    is_flag=True,
    help='返回JavaScript执行结果'
)
@click.pass_context
@print_usage
def execute_javascript(ctx, script: str, return_value: bool):
    """
    执行JavaScript代码，自动获取页面特征

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
                return

        with create_session(ctx) as session:
            result = session.evaluate(script, return_by_value=return_value)
            if return_value:
                _print_msg("成功", f"执行结果: {result}", "interaction", {"result": str(result)})
            else:
                _print_msg("成功", "JavaScript执行完成", "interaction")

            # JS执行后短暂等待
            time.sleep(0.3)

            # 感知：获取 DOM 特征
            _do_perception(session, "exec-js")

    except CDPError as e:
        _print_msg("失败", f"JavaScript执行失败: {e}", "interaction", {"error": str(e)})


@click.command('get-title')
@click.pass_context
@print_usage
def get_title(ctx):
    """获取页面标题"""
    try:
        with create_session(ctx) as session:
            title = session.get_title()
            _print_msg("成功", f"页面标题: {title}", "extraction", {"title": title})
    except CDPError as e:
        _print_msg("失败", f"获取标题失败: {e}", "extraction", {"error": str(e)})


def _get_run_outputs_dir() -> Path:
    """获取输出目录（run context 或 .tmp）"""
    run_dir = _get_run_dir()
    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


def _get_next_output_number(outputs_dir: Path, ext: str = ".txt") -> int:
    """获取下一个输出文件序号"""
    import re
    max_num = 0
    for file in outputs_dir.glob(f"*{ext}"):
        match = re.match(r"^(\d{3})_", file.name)
        if match:
            num = int(match.group(1))
            max_num = max(max_num, num)
    return max_num + 1


@click.command('get-content')
@click.argument('selector', default='body')
@click.option(
    '--desc',
    type=str,
    default=None,
    help='内容描述（用于生成文件名）'
)
@click.pass_context
@print_usage
def get_content(ctx, selector: str, desc: Optional[str]):
    """
    获取页面或元素的文本内容

    输出包含：
    - 来源 URL（当前页面地址）
    - 文本内容
    - 内容中包含的超链接

    如果存在活跃的 run context，内容将自动保存到 run 的 outputs 目录。
    """
    import json as json_module

    try:
        with create_session(ctx) as session:
            script = f"""
            (function() {{
                var el = document.querySelector('{selector}');
                if (!el) return JSON.stringify({{error: 'Element not found'}});

                // 获取文本内容
                var textContent = el.innerText || el.textContent || '';

                // 获取来源 URL
                var sourceUrl = window.location.href;

                // 获取元素内的所有超链接
                var links = [];
                var anchors = el.querySelectorAll('a[href]');
                anchors.forEach(function(a) {{
                    var href = a.href;
                    var text = (a.innerText || a.textContent || '').trim();
                    if (href && !href.startsWith('javascript:')) {{
                        links.push({{
                            url: href,
                            text: text.substring(0, 100)  // 限制文本长度
                        }});
                    }}
                }});

                return JSON.stringify({{
                    source_url: sourceUrl,
                    content: textContent,
                    links: links
                }});
            }})()
            """
            result_str = session.evaluate(script, return_by_value=True)

            try:
                result = json_module.loads(result_str)
            except (json_module.JSONDecodeError, TypeError):
                _print_msg("失败", f"解析结果失败: {result_str}", "extraction", {"selector": selector})
                return

            if result.get('error'):
                _print_msg("失败", f"找不到元素: {selector}", "extraction", {"selector": selector})
                return

            source_url = result.get('source_url', '')
            content = result.get('content', '')
            links = result.get('links', [])

            # 格式化输出内容
            formatted_output = f"来源: {source_url}\n\n"
            formatted_output += "--- 内容 ---\n"
            formatted_output += content
            if links:
                formatted_output += "\n\n--- 包含的链接 ---\n"
                for link in links:
                    link_text = link.get('text', '')
                    link_url = link.get('url', '')
                    if link_text:
                        formatted_output += f"- [{link_text}] {link_url}\n"
                    else:
                        formatted_output += f"- {link_url}\n"

            # 尝试保存到 run outputs 目录
            saved_file = None
            try:
                from slugify import slugify

                outputs_dir = _get_run_outputs_dir()
                run_dir = _get_run_dir()

                if run_dir.name != ".tmp":
                    seq = _get_next_output_number(outputs_dir)
                    description = desc or selector.replace(" ", "-")[:30]
                    desc_slug = slugify(description, max_length=40)
                    filename = f"{seq:03d}_{desc_slug}.txt"
                    file_path = outputs_dir / filename
                    file_path.write_text(formatted_output, encoding="utf-8")
                    saved_file = str(file_path)
            except Exception:
                pass

            # 输出结果（始终打印内容，让 agent 能看到）
            log_data = {
                "selector": selector,
                "source_url": source_url,
                "links_count": len(links)
            }
            if saved_file:
                log_data["file"] = saved_file
                _print_msg("成功", f"获取内容 ({selector}), 已保存到: {saved_file}\n{formatted_output}", "extraction", log_data)
            else:
                _print_msg("成功", f"获取内容 ({selector}):\n{formatted_output}", "extraction", log_data)
    except CDPError as e:
        _print_msg("失败", f"获取内容失败: {e}", "extraction", {"selector": selector, "error": str(e)})


@click.command('status')
@click.pass_context
@print_usage
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
                return
    except CDPError as e:
        _print_msg("失败", f"状态检查失败: {e}")


@click.command('scroll')
@click.argument('distance', type=SCROLL_DISTANCE)
@click.pass_context
@print_usage
def scroll(ctx, distance: int):
    """
    滚动页面，自动获取页面特征

    \b
    DISTANCE 可以是:
      - 像素值: 正数向下，负数向上
      - 别名: down, up, page-down, page-up
    """
    try:
        with create_session(ctx) as session:
            session.scroll.scroll(distance)
            _print_msg("成功", f"滚动 {distance} 像素", "interaction", {"distance": distance})

            # 滚动后短暂等待
            time.sleep(0.3)

            # 感知：获取 DOM 特征
            _do_perception(session, f"scroll-{distance}px")

    except CDPError as e:
        _print_msg("失败", f"滚动失败: {e}", "interaction", {"distance": distance, "error": str(e)})


@click.command('scroll-to')
@click.argument('selector', required=False)
@click.option(
    '--text',
    type=str,
    help='按文本内容查找元素（支持部分匹配）'
)
@click.option(
    '--block',
    type=click.Choice(['start', 'center', 'end', 'nearest']),
    default='center',
    help='垂直对齐方式 (默认: center)'
)
@click.pass_context
@print_usage
def scroll_to(ctx, selector: Optional[str], text: Optional[str], block: str = 'center'):
    """
    滚动到指定元素

    可以通过 CSS 选择器或文本内容查找元素：

    \b
    示例：
      frago scroll-to "article"                    # CSS 选择器
      frago scroll-to --text "Just canceled"       # 按文本查找
    """
    import json

    if not selector and not text:
        click.echo("错误: 必须提供 SELECTOR 或 --text 参数", err=True)
        return

    try:
        with create_session(ctx) as session:
            if text:
                # 按文本内容查找元素
                js_code = f'''
                (function() {{
                    const searchText = {json.dumps(text)};
                    const block = {json.dumps(block)};

                    // 使用 TreeWalker 遍历所有文本节点
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        {{
                            acceptNode: function(node) {{
                                if (node.textContent.includes(searchText)) {{
                                    return NodeFilter.FILTER_ACCEPT;
                                }}
                                return NodeFilter.FILTER_REJECT;
                            }}
                        }}
                    );

                    const textNode = walker.nextNode();
                    if (textNode && textNode.parentElement) {{
                        textNode.parentElement.scrollIntoView({{behavior: 'smooth', block: block}});
                        return 'success';
                    }}
                    return 'element not found';
                }})()
                '''
                display_target = f"文本: {text}"
            else:
                # CSS 选择器查找
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
                display_target = selector

            result = session.evaluate(js_code, return_by_value=True)

            if result == 'success':
                _print_msg("成功", f"滚动到元素: {display_target}", "interaction", {"selector": selector, "text": text, "block": block})
                time.sleep(0.5)  # 等待滚动动画完成
                _do_perception(session, f"scroll-to-{(text or selector)[:30]}")
            else:
                _print_msg("失败", f"元素未找到: {display_target}", "interaction", {"selector": selector, "text": text})
                return

    except CDPError as e:
        _print_msg("失败", f"滚动到元素失败: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('wait')
@click.argument('seconds', type=WAIT_SECONDS)
@click.pass_context
@print_usage
def wait(ctx, seconds: float):
    """等待指定秒数（支持小数，如 0.5）"""
    try:
        with create_session(ctx) as session:
            session.wait.wait(seconds)
            _print_msg("成功", f"等待 {seconds} 秒完成")
    except CDPError as e:
        _print_msg("失败", f"等待失败: {e}")


@click.command('zoom')
@click.argument('factor', type=ZOOM_FACTOR)
@click.pass_context
@print_usage
def zoom(ctx, factor: float):
    """
    设置页面缩放比例，自动获取页面特征

    \b
    FACTOR 示例: 1.5 (150%), 0.8 (80%), 1 (原始大小)
    """
    try:
        with create_session(ctx) as session:
            session.zoom(factor)
            _print_msg("成功", f"页面缩放设置为: {factor}", "interaction", {"zoom_factor": factor})

            # 缩放后短暂等待
            time.sleep(0.2)

            # 感知：获取 DOM 特征
            _do_perception(session, f"zoom-{factor}x")

    except CDPError as e:
        _print_msg("失败", f"缩放失败: {e}", "interaction", {"zoom_factor": factor, "error": str(e)})


@click.command('clear-effects')
@click.pass_context
@print_usage
def clear_effects(ctx):
    """清除所有视觉效果"""
    try:
        with create_session(ctx) as session:
            session.clear_effects()
            _print_msg("成功", "视觉效果已清除", "interaction")

    except CDPError as e:
        _print_msg("失败", f"清除效果失败: {e}", "interaction", {"error": str(e)})


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
@click.pass_context
@print_usage
def highlight(ctx, selector: str, color: str, width: int, life_time: int, longlife: bool):
    """高亮显示指定元素"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.highlight(selector, color=color, border_width=width, lifetime=lifetime_ms)
            _print_msg("成功", f"高亮元素: {selector} (颜色: {color}, 宽度: {width}px, 持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector, "color": color, "width": width})

    except CDPError as e:
        _print_msg("失败", f"高亮失败: {e}", "interaction", {"selector": selector, "error": str(e)})


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
@click.pass_context
@print_usage
def pointer(ctx, selector: str, life_time: int, longlife: bool):
    """在元素上显示鼠标指针"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.pointer(selector, lifetime=lifetime_ms)
            _print_msg("成功", f"显示指针: {selector} (持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector})

    except CDPError as e:
        _print_msg("失败", f"显示指针失败: {e}", "interaction", {"selector": selector, "error": str(e)})


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
@click.pass_context
@print_usage
def spotlight(ctx, selector: str, life_time: int, longlife: bool):
    """聚光灯效果显示元素"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.spotlight(selector, lifetime=lifetime_ms)
            _print_msg("成功", f"聚光灯显示: {selector} (持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector})

    except CDPError as e:
        _print_msg("失败", f"聚光灯失败: {e}", "interaction", {"selector": selector, "error": str(e)})


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
@click.pass_context
@print_usage
def annotate(ctx, selector: str, text: str, position: str, life_time: int, longlife: bool):
    """在元素上添加标注"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.annotate(selector, text, position=position, lifetime=lifetime_ms)
            _print_msg("成功", f"添加标注: {text} ({selector}) (持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector, "text": text, "position": position})

    except CDPError as e:
        _print_msg("失败", f"添加标注失败: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('underline')
@click.argument('selector', required=False)
@click.option(
    '--text',
    type=str,
    help='按文本内容查找元素（支持部分匹配）'
)
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
@click.pass_context
@print_usage
def underline(ctx, selector: Optional[str], text: Optional[str], color: str, width: int, duration: int, life_time: int, longlife: bool):
    """
    在元素文本底部逐行画线动画

    \b
    示例：
      frago underline "article"                    # CSS 选择器
      frago underline --text "Just canceled"       # 按文本查找
    """
    import json

    if not selector and not text:
        click.echo("错误: 必须提供 SELECTOR 或 --text 参数", err=True)
        return

    lifetime_ms = 0 if longlife else life_time * 1000
    display_target = f"文本: {text}" if text else selector

    # JS 代码：支持 selector 或 text 查找
    js_code = """
(function(selector, searchText, color, width, duration, lifetime) {
    let elements = [];

    if (searchText) {
        // 按文本查找
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function(node) {
                    if (node.textContent.includes(searchText)) {
                        return NodeFilter.FILTER_ACCEPT;
                    }
                    return NodeFilter.FILTER_REJECT;
                }
            }
        );
        const textNode = walker.nextNode();
        if (textNode && textNode.parentElement) {
            elements = [textNode.parentElement];
        }
    } else {
        elements = Array.from(document.querySelectorAll(selector));
    }

    if (elements.length === 0) return 'element not found';

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
    return 'success';
})(""" + json.dumps(selector) + "," + json.dumps(text) + "," + json.dumps(color) + "," + str(width) + "," + str(duration) + "," + str(lifetime_ms) + ")"

    try:
        with create_session(ctx) as session:
            result = session.evaluate(js_code, return_by_value=True)

            if result == 'element not found':
                _print_msg("失败", f"元素未找到: {display_target}", "interaction", {"selector": selector, "text": text})
                return

            _print_msg("成功", f"划线元素: {display_target} (颜色: {color}, 宽度: {width}px, 持续: {'永久' if longlife else f'{life_time}秒'})", "interaction", {"selector": selector, "text": text, "color": color, "width": width, "duration": duration})

    except CDPError as e:
        _print_msg("失败", f"划线失败: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('init')
@click.option(
    '--force',
    is_flag=True,
    help='强制重新创建已存在的目录'
)
@print_usage
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
            return

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
@print_usage
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

    # 检测是否显式指定了非默认端口
    use_port_suffix = (port != 9222) and (profile_dir is None)

    launcher = ChromeLauncher(
        headless=headless,
        void=void,
        port=port,
        width=width,
        height=height,
        profile_dir=profile_path,
        use_port_suffix=use_port_suffix,
    )

    # 检查 Chrome 是否存在
    if not launcher.chrome_path:
        click.echo("错误: 未找到 Chrome 浏览器", err=True)
        click.echo("请安装 Google Chrome 或 Chromium 浏览器", err=True)
        return

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


@click.command('chrome-stop')
@click.option(
    '--port',
    type=int,
    default=9222,
    help='CDP 调试端口，默认 9222'
)
@print_usage
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
@print_usage
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


@click.command('switch-tab')
@click.argument('tab_id')
@click.pass_context
@print_usage
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
            return

        ws_url = target.get('webSocketDebuggerUrl')
        if not ws_url:
            click.echo(f"Tab {tab_id} 没有可用的 WebSocket URL", err=True)
            return

        # 发送 Page.bringToFront 命令
        ws = websocket.create_connection(ws_url)
        ws.send(json.dumps({'id': 1, 'method': 'Page.bringToFront', 'params': {}}))
        result = json.loads(ws.recv())
        ws.close()

        if 'error' in result:
            click.echo(f"切换失败: {result['error']}", err=True)
            return

        _print_msg("成功", f"已切换到 tab: {target.get('title', 'Unknown')}", "tab_switch", {
            "tab_id": target.get('id'),
            "title": target.get('title'),
            "url": target.get('url')
        })

    except Exception as e:
        click.echo(f"切换 tab 失败: {e}", err=True)