#!/usr/bin/env python3
"""
Frago CLI command implementations

Implements all CDP functionality CLI subcommands, maintaining compatibility with original shell scripts.
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
# Command usage examples (Agent-friendly output)
# =============================================================================

COMMAND_EXAMPLES = {
    # Chrome subcommands (using full paths for easy agent copy-paste)
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
        "frago chrome exec-js ./script.js  # Load from file",
    ],
    "get-title": [
        "frago chrome get-title",
    ],
    "get-content": [
        "frago chrome get-content [selector]",
        "frago chrome get-content  # Default: get body",
        "frago chrome get-content 'article.main' --desc 'article-content'",
    ],
    "scroll": [
        "frago chrome scroll <distance>",
        "frago chrome scroll 500      # Scroll down 500px",
        "frago chrome scroll -300     # Scroll up 300px",
        "frago chrome scroll down     # Alias: scroll down 500px",
        "frago chrome scroll up       # Alias: scroll up 500px",
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
        "frago chrome zoom 1.5   # Zoom to 150%",
        "frago chrome zoom 0.8   # Zoom to 80%",
        "frago chrome zoom 1     # Reset to original size",
    ],
    "clear-effects": [
        "frago chrome clear-effects",
    ],
    "highlight": [
        "frago chrome highlight <selector>",
        "frago chrome highlight 'button.primary'",
        "frago chrome highlight '#target' --color red --width 5",
        "frago chrome highlight '.element' --longlife  # Permanent display",
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
        "frago chrome switch-tab ABC123  # Supports partial ID matching",
    ],
    # Top-level commands
    "status": [
        "frago status",
        "frago chrome status  # Equivalent",
    ],
    "init": [
        "frago init",
        "frago init --force",
    ],
    # Chrome command group itself (showing subcommand overview)
    "chrome": [
        "frago chrome <command>",
        "frago chrome start      # Start browser",
        "frago chrome navigate   # Navigate to URL",
        "frago chrome click      # Click element",
        "frago chrome screenshot # Take screenshot",
    ],
    # Frago top-level commands
    "frago": [
        "frago <command>",
        "frago chrome start      # Start browser",
        "frago status            # Check CDP connection status",
        "frago --gui             # Launch GUI app",
    ],
}


def print_usage(func):
    """
    Decorator: Print usage examples before command execution

    Helps AI Agents understand correct command usage when tracking output.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Infer command name from function name (underscore to hyphen)
        cmd_name = func.__name__.replace('_', '-')
        # Special mappings
        name_map = {
            "click-element": "click",
            "execute-javascript": "exec-js",
            "chrome-start": "chrome",
            "init-dirs": "init",
        }
        cmd_name = name_map.get(cmd_name, cmd_name)

        examples = COMMAND_EXAMPLES.get(cmd_name)
        if examples:
            click.echo(f"[Usage] {examples[0]}")
            for ex in examples[1:]:
                click.echo(f"        {ex}")
            click.echo("")  # Empty line separator

        return func(*args, **kwargs)
    return wrapper

from ..cdp.config import CDPConfig
from ..cdp.exceptions import CDPError
from ..cdp.session import CDPSession


# =============================================================================
# Custom parameter types (with friendly error messages and usage examples)
# =============================================================================


class ScrollDistanceType(click.ParamType):
    """Scroll distance parameter type, supports pixel values or up/down aliases"""
    name = "distance"

    def convert(self, value, param, ctx):
        # Support up/down aliases
        aliases = {"up": -500, "down": 500, "page-up": -800, "page-down": 800}
        if isinstance(value, str) and value.lower() in aliases:
            return aliases[value.lower()]

        try:
            return int(value)
        except (ValueError, TypeError):
            self.fail(
                f"'{value}' is not a valid scroll distance.\n\n"
                "Correct usage:\n"
                "  frago scroll 500       # Scroll down 500 pixels\n"
                "  frago scroll -300      # Scroll up 300 pixels\n"
                "  frago scroll down      # Scroll down 500 pixels (alias)\n"
                "  frago scroll up        # Scroll up 500 pixels (alias)\n"
                "  frago scroll-to 'selector'  # Scroll to element",
                param,
                ctx,
            )


class ZoomFactorType(click.ParamType):
    """Zoom factor parameter type"""
    name = "factor"

    def convert(self, value, param, ctx):
        try:
            factor = float(value)
            if factor <= 0:
                raise ValueError("Must be greater than 0")
            return factor
        except (ValueError, TypeError):
            self.fail(
                f"'{value}' is not a valid zoom factor.\n\n"
                "Correct usage:\n"
                "  frago zoom 1.5    # Zoom to 150%\n"
                "  frago zoom 0.8    # Zoom to 80%\n"
                "  frago zoom 1      # Reset to original size",
                param,
                ctx,
            )


class WaitSecondsType(click.ParamType):
    """Wait seconds parameter type"""
    name = "seconds"

    def convert(self, value, param, ctx):
        try:
            seconds = float(value)
            if seconds < 0:
                raise ValueError("Cannot be negative")
            return seconds
        except (ValueError, TypeError):
            self.fail(
                f"'{value}' is not a valid wait time.\n\n"
                "Correct usage:\n"
                "  frago wait 2      # Wait 2 seconds\n"
                "  frago wait 0.5    # Wait 0.5 seconds",
                param,
                ctx,
            )


# Instantiate custom types
SCROLL_DISTANCE = ScrollDistanceType()
ZOOM_FACTOR = ZoomFactorType()
WAIT_SECONDS = WaitSecondsType()


# Global options default configuration
GLOBAL_OPTIONS = {
    'debug': False,
    'timeout': 30,
    'host': '127.0.0.1',
    'port': 9222
}


def _format_ts() -> str:
    """Format current timestamp"""
    return datetime.now().strftime("%Y-%m-%d:%H-%M-%S")


def _get_projects_dir() -> Path:
    """
    Get projects directory

    Uses ~/.frago/projects/
    """
    return Path.home() / ".frago" / "projects"


def _get_run_dir() -> Path:
    """
    Get current run directory

    Uses active run context if available, otherwise uses projects/.tmp/
    """
    frago_home = Path.home() / ".frago"
    projects_dir = _get_projects_dir()

    try:
        from ..run.context import ContextManager
        ctx_mgr = ContextManager(frago_home, projects_dir)
        context = ctx_mgr.get_current_run()
        return projects_dir / context.run_id
    except Exception:
        # No run context, use .tmp directory
        tmp_dir = projects_dir / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir


def _get_run_logger():
    """Get logger (run context or .tmp)"""
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
    Write to run log (if there's an active run context)

    Args:
        step: Step description
        status: Status (success/error/warning)
        action_type: Action type
        data: Additional data
    """
    logger = _get_run_logger()
    if not logger:
        return

    try:
        from ..run.models import ActionType, ExecutionMethod, LogStatus

        # Map status
        status_map = {
            "success": LogStatus.SUCCESS,
            "error": LogStatus.ERROR,
            "warning": LogStatus.WARNING,
            "debug": LogStatus.SUCCESS,
        }
        log_status = status_map.get(status, LogStatus.SUCCESS)

        # Map action type
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
        # Log write failure should not affect command execution
        pass


def _print_msg(
    status: str,
    message: str,
    action_type: str = "other",
    log_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Print formatted message and automatically write to run log

    Args:
        status: Status (success/error/warning/debug)
        message: Message content
        action_type: Action type (navigation/interaction/screenshot/extraction/other)
        log_data: Additional log data
    """
    click.echo(f"{_format_ts()}, {status}, {message}")

    # Auto write to run log
    _write_run_log(message, status, action_type, log_data)


def create_session(ctx) -> CDPSession:
    """
    Create CDP session

    Uses global options:
    - --debug: Enable debug mode
    - --timeout: Set operation timeout
    - --host: CDP service host address
    - --port: CDP service port
    - --proxy-host: Proxy server host address
    - --proxy-port: Proxy server port
    - --proxy-username: Proxy auth username
    - --proxy-password: Proxy auth password
    - --no-proxy: Bypass proxy connection
    - --target-id: Specify target tab ID
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
    """Extract page DOM features, focusing on current visible area content"""
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

        // Get text content within current viewport
        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;

        // Collect text from visible elements in viewport
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
                    // Check if element is within viewport
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
    """Print DOM features summary"""
    if not features:
        return

    # Build feature summary
    body_attrs = []
    if features.get('body_class'):
        body_attrs.append(f"class=\"{features['body_class']}\"")
    if features.get('body_id'):
        body_attrs.append(f"id=\"{features['body_id']}\"")
    body_str = ', '.join(body_attrs) if body_attrs else '(none)'

    elements = f"{features.get('forms', 0)} forms, {features.get('buttons', 0)} buttons, {features.get('links', 0)} links, {features.get('inputs', 0)} inputs"

    _print_msg("success", f"Page title: {features.get('title', '(none)')}")
    _print_msg("success", f"Body attrs: {body_str}")
    _print_msg("success", f"Element stats: {elements}")

    # Output scroll position and visible content
    scroll_y = features.get('scroll_y', 0)
    _print_msg("success", f"Scroll position: scrollY={scroll_y}px")

    if features.get('visible_content'):
        _print_msg("success", f"Visible content: {features['visible_content']}")


def _take_perception_screenshot(session: CDPSession, description: str = "page") -> Optional[str]:
    """
    Take perception screenshot

    Args:
        session: CDP session
        description: Screenshot description for filename generation

    Returns:
        Screenshot file path, None on failure
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
    Post-action perception: get DOM features

    Note: No longer auto-screenshots. Screenshots should be explicitly called via screenshot command.
    Reason: Reduce hints to model, avoid over-reliance on screenshots over structured data extraction.

    Args:
        session: CDP session
        action_desc: Action description (kept for logging)
        delay: Delay before getting DOM features (seconds), for waiting page load
    """
    # Optional delay
    if delay > 0:
        time.sleep(delay)

    # Get and print DOM features
    features = _get_dom_features(session)
    _print_dom_features(features)


def _get_run_screenshots_dir() -> Path:
    """Get screenshots directory (run context or .tmp)"""
    run_dir = _get_run_dir()
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    return screenshots_dir


@click.command('navigate')
@click.argument('url')
@click.option(
    '--wait-for',
    type=str,
    help='Wait for selector to appear before returning'
)
@click.option(
    '--load-timeout',
    type=float,
    default=30,
    help='Page load timeout in seconds, default 30'
)
@click.pass_context
@print_usage
def navigate(ctx, url: str, wait_for: Optional[str] = None, load_timeout: float = 30):
    """Navigate to URL and get page features after loading"""
    try:
        with create_session(ctx) as session:
            # 1. Navigate
            session.navigate(url)
            _print_msg("success", f"Navigated to {url}", "navigation", {"url": url})

            # 2. Wait for page load
            session.wait_for_load(timeout=load_timeout)
            _print_msg("success", "Page load complete", "navigation")

            # 3. If selector specified, wait for it
            if wait_for:
                session.wait_for_selector(wait_for)
                _print_msg("success", f"Selector ready: {wait_for}", "navigation", {"selector": wait_for})

            # 4. Perception: get DOM features (delay 2s for dynamic content)
            _do_perception(session, f"navigate-{url}", delay=2.0)

    except CDPError as e:
        _print_msg("error", f"Navigation failed: {e}", "navigation", {"url": url, "error": str(e)})


@click.command('click')
@click.argument('selector')
@click.option(
    '--wait-timeout',
    type=int,
    default=10,
    help='Wait timeout for element to appear (seconds)'
)
@click.pass_context
@print_usage
def click_element(ctx, selector: str, wait_timeout: int):
    """Click element by selector and get page features"""
    try:
        with create_session(ctx) as session:
            session.click(selector, wait_timeout=wait_timeout)
            _print_msg("success", f"Clicked element: {selector}", "interaction", {"selector": selector})

            # Brief wait for page response after click
            time.sleep(0.5)

            # Perception: get DOM features
            _do_perception(session, f"click-{selector}")

    except CDPError as e:
        _print_msg("error", f"Click failed: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('screenshot')
@click.argument('output_file')
@click.option(
    '--full-page',
    is_flag=True,
    help='Capture full page (including scroll area)'
)
@click.option(
    '--quality',
    type=int,
    default=80,
    help='Image quality (1-100), default 80'
)
@click.pass_context
@print_usage
def screenshot(ctx, output_file: str, full_page: bool, quality: int):
    """
    Capture page screenshot

    If there's an active run context, screenshot will be saved to run's screenshots directory,
    OUTPUT_FILE will be used as description for filename generation (auto-numbered).

    If no run context, OUTPUT_FILE is used as complete file path.
    """
    try:
        # Check for active run context
        actual_output_file = output_file
        try:
            from ..run.screenshot import get_next_screenshot_number
            from slugify import slugify

            screenshots_dir = _get_run_screenshots_dir()
            run_dir = _get_run_dir()

            # Check if .tmp directory (no run context)
            if run_dir.name != ".tmp":
                # Has run context, use output_file as description for filename
                # Remove possible extension as description
                description = Path(output_file).stem
                seq = get_next_screenshot_number(screenshots_dir)
                desc_slug = slugify(description or 'screenshot', max_length=40)
                filename = f"{seq:03d}_{desc_slug}.png"
                actual_output_file = str(screenshots_dir / filename)
        except Exception:
            # Get run context failed, use original path
            pass

        with create_session(ctx) as session:
            session.screenshot.capture(actual_output_file, full_page=full_page, quality=quality)
            _print_msg("success", f"Screenshot saved to: {actual_output_file}", "screenshot", {"file": actual_output_file, "full_page": full_page})
    except CDPError as e:
        _print_msg("error", f"Screenshot failed: {e}", "screenshot", {"file": output_file, "error": str(e)})


@click.command('exec-js')
@click.argument('script')
@click.option(
    '--return-value',
    is_flag=True,
    help='Return JavaScript execution result'
)
@click.pass_context
@print_usage
def execute_javascript(ctx, script: str, return_value: bool):
    """
    Execute JavaScript code and automatically capture page features

    The SCRIPT argument can be either direct JavaScript code or a file path containing the code.
    """
    try:
        # Check if it's a file path
        if os.path.exists(script) and os.path.isfile(script):
            try:
                with open(script, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                if ctx.obj['DEBUG']:
                    _print_msg("debug", f"Loaded script from file: {script}", "interaction")
                script = script_content
            except Exception as e:
                _print_msg("error", f"Failed to read script file: {e}", "interaction", {"error": str(e)})
                return

        with create_session(ctx) as session:
            result = session.evaluate(script, return_by_value=return_value)
            if return_value:
                _print_msg("success", f"Execution result: {result}", "interaction", {"result": str(result)})
            else:
                _print_msg("success", "JavaScript execution completed", "interaction")

            # Brief wait after JS execution
            time.sleep(0.3)

            # Perception: capture DOM features
            _do_perception(session, "exec-js")

    except CDPError as e:
        _print_msg("error", f"JavaScript execution failed: {e}", "interaction", {"error": str(e)})


@click.command('get-title')
@click.pass_context
@print_usage
def get_title(ctx):
    """Get page title"""
    try:
        with create_session(ctx) as session:
            title = session.get_title()
            _print_msg("success", f"Page title: {title}", "extraction", {"title": title})
    except CDPError as e:
        _print_msg("error", f"Failed to get title: {e}", "extraction", {"error": str(e)})


def _get_run_outputs_dir() -> Path:
    """Get outputs directory (run context or .tmp)"""
    run_dir = _get_run_dir()
    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


def _get_next_output_number(outputs_dir: Path, ext: str = ".txt") -> int:
    """Get next output file sequence number"""
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
    help='Content description (used for filename generation)'
)
@click.pass_context
@print_usage
def get_content(ctx, selector: str, desc: Optional[str]):
    """
    Get text content from page or element

    Output includes:
    - Source URL (current page address)
    - Text content
    - Hyperlinks contained in the content

    If an active run context exists, the content will be automatically saved to the run's outputs directory.
    """
    import json as json_module

    try:
        with create_session(ctx) as session:
            script = f"""
            (function() {{
                var el = document.querySelector('{selector}');
                if (!el) return JSON.stringify({{error: 'Element not found'}});

                // Get text content
                var textContent = el.innerText || el.textContent || '';

                // Get source URL
                var sourceUrl = window.location.href;

                // Get all hyperlinks within the element
                var links = [];
                var anchors = el.querySelectorAll('a[href]');
                anchors.forEach(function(a) {{
                    var href = a.href;
                    var text = (a.innerText || a.textContent || '').trim();
                    if (href && !href.startsWith('javascript:')) {{
                        links.push({{
                            url: href,
                            text: text.substring(0, 100)  // Limit text length
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
                _print_msg("error", f"Failed to parse result: {result_str}", "extraction", {"selector": selector})
                return

            if result.get('error'):
                _print_msg("error", f"Element not found: {selector}", "extraction", {"selector": selector})
                return

            source_url = result.get('source_url', '')
            content = result.get('content', '')
            links = result.get('links', [])

            # Format output content
            formatted_output = f"Source: {source_url}\n\n"
            formatted_output += "--- Content ---\n"
            formatted_output += content
            if links:
                formatted_output += "\n\n--- Included Links ---\n"
                for link in links:
                    link_text = link.get('text', '')
                    link_url = link.get('url', '')
                    if link_text:
                        formatted_output += f"- [{link_text}] {link_url}\n"
                    else:
                        formatted_output += f"- {link_url}\n"

            # Try to save to run outputs directory
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

            # Output results (always print content so agent can see it)
            log_data = {
                "selector": selector,
                "source_url": source_url,
                "links_count": len(links)
            }
            if saved_file:
                log_data["file"] = saved_file
                _print_msg("success", f"Content retrieved ({selector}), saved to: {saved_file}\n{formatted_output}", "extraction", log_data)
            else:
                _print_msg("success", f"Content retrieved ({selector}):\n{formatted_output}", "extraction", log_data)
    except CDPError as e:
        _print_msg("error", f"Failed to get content: {e}", "extraction", {"selector": selector, "error": str(e)})


@click.command('status')
@click.pass_context
@print_usage
def status(ctx):
    """Check CDP connection status"""
    try:
        with create_session(ctx) as session:
            # Perform health check
            is_healthy = session.status.health_check()
            if is_healthy:
                # Get Chrome status information
                chrome_status = session.status.check_chrome_status()
                _print_msg("success", "CDP connection OK")
                _print_msg("success", f"Browser: {chrome_status.get('Browser', 'unknown')}")
                _print_msg("success", f"Protocol-Version: {chrome_status.get('Protocol-Version', 'unknown')}")
                _print_msg("success", f"WebKit-Version: {chrome_status.get('WebKit-Version', 'unknown')}")
            else:
                _print_msg("error", "CDP connection failed")
                return
    except CDPError as e:
        _print_msg("error", f"Status check failed: {e}")


@click.command('scroll')
@click.argument('distance', type=SCROLL_DISTANCE)
@click.pass_context
@print_usage
def scroll(ctx, distance: int):
    """
    Scroll page and automatically capture page features

    \b
    DISTANCE can be:
      - Pixel value: positive for down, negative for up
      - Alias: down, up, page-down, page-up
    """
    try:
        with create_session(ctx) as session:
            session.scroll.scroll(distance)
            _print_msg("success", f"Scrolled {distance} pixels", "interaction", {"distance": distance})

            # Brief wait after scroll
            time.sleep(0.3)

            # Perception: capture DOM features
            _do_perception(session, f"scroll-{distance}px")

    except CDPError as e:
        _print_msg("error", f"Scroll failed: {e}", "interaction", {"distance": distance, "error": str(e)})


@click.command('scroll-to')
@click.argument('selector', required=False)
@click.option(
    '--text',
    type=str,
    help='Find element by text content (supports partial matching)'
)
@click.option(
    '--block',
    type=click.Choice(['start', 'center', 'end', 'nearest']),
    default='center',
    help='Vertical alignment (default: center)'
)
@click.pass_context
@print_usage
def scroll_to(ctx, selector: Optional[str], text: Optional[str], block: str = 'center'):
    """
    Scroll to specified element

    You can find elements by CSS selector or text content:

    \b
    Examples:
      frago scroll-to "article"                    # CSS selector
      frago scroll-to --text "Just canceled"       # Find by text
    """
    import json

    if not selector and not text:
        click.echo("Error: must provide SELECTOR or --text parameter", err=True)
        return

    try:
        with create_session(ctx) as session:
            if text:
                # Find element by text content
                js_code = f'''
                (function() {{
                    const searchText = {json.dumps(text)};
                    const block = {json.dumps(block)};

                    // Use TreeWalker to traverse all text nodes
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
                display_target = f"text: {text}"
            else:
                # CSS selector lookup
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
                _print_msg("success", f"Scrolled to element: {display_target}", "interaction", {"selector": selector, "text": text, "block": block})
                time.sleep(0.5)  # Wait for scroll animation to complete
                _do_perception(session, f"scroll-to-{(text or selector)[:30]}")
            else:
                _print_msg("error", f"Element not found: {display_target}", "interaction", {"selector": selector, "text": text})
                return

    except CDPError as e:
        _print_msg("error", f"Failed to scroll to element: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('wait')
@click.argument('seconds', type=WAIT_SECONDS)
@click.pass_context
@print_usage
def wait(ctx, seconds: float):
    """Wait for specified seconds (supports decimals, e.g., 0.5)"""
    try:
        with create_session(ctx) as session:
            session.wait.wait(seconds)
            _print_msg("success", f"Waited {seconds} seconds")
    except CDPError as e:
        _print_msg("error", f"Wait failed: {e}")


@click.command('zoom')
@click.argument('factor', type=ZOOM_FACTOR)
@click.pass_context
@print_usage
def zoom(ctx, factor: float):
    """
    Set page zoom level and automatically capture page features

    \b
    FACTOR examples: 1.5 (150%), 0.8 (80%), 1 (original size)
    """
    try:
        with create_session(ctx) as session:
            session.zoom(factor)
            _print_msg("success", f"Page zoom set to: {factor}", "interaction", {"zoom_factor": factor})

            # Brief wait after zoom
            time.sleep(0.2)

            # Perception: capture DOM features
            _do_perception(session, f"zoom-{factor}x")

    except CDPError as e:
        _print_msg("error", f"Zoom failed: {e}", "interaction", {"zoom_factor": factor, "error": str(e)})


@click.command('clear-effects')
@click.pass_context
@print_usage
def clear_effects(ctx):
    """Clear all visual effects"""
    try:
        with create_session(ctx) as session:
            session.clear_effects()
            _print_msg("success", "Visual effects cleared", "interaction")

    except CDPError as e:
        _print_msg("error", f"Failed to clear effects: {e}", "interaction", {"error": str(e)})


@click.command('highlight')
@click.argument('selector')
@click.option(
    '--color',
    type=str,
    default='magenta',
    help='Highlight color, default magenta'
)
@click.option(
    '--width',
    type=int,
    default=3,
    help='Highlight border width (pixels), default 3'
)
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='Effect duration (seconds), default 5 seconds'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='Show permanently until manually cleared'
)
@click.pass_context
@print_usage
def highlight(ctx, selector: str, color: str, width: int, life_time: int, longlife: bool):
    """Highlight specified element"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.highlight(selector, color=color, border_width=width, lifetime=lifetime_ms)
            _print_msg("success", f"Highlighted element: {selector} (color: {color}, width: {width}px, duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector, "color": color, "width": width})

    except CDPError as e:
        _print_msg("error", f"Highlight failed: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('pointer')
@click.argument('selector')
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='Effect duration (seconds), default 5 seconds'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='Show permanently until manually cleared'
)
@click.pass_context
@print_usage
def pointer(ctx, selector: str, life_time: int, longlife: bool):
    """Show mouse pointer on element"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.pointer(selector, lifetime=lifetime_ms)
            _print_msg("success", f"Pointer shown: {selector} (duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector})

    except CDPError as e:
        _print_msg("error", f"Failed to show pointer: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('spotlight')
@click.argument('selector')
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='Effect duration (seconds), default 5 seconds'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='Show permanently until manually cleared'
)
@click.pass_context
@print_usage
def spotlight(ctx, selector: str, life_time: int, longlife: bool):
    """Show element with spotlight effect"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.spotlight(selector, lifetime=lifetime_ms)
            _print_msg("success", f"Spotlight shown: {selector} (duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector})

    except CDPError as e:
        _print_msg("error", f"Spotlight failed: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('annotate')
@click.argument('selector')
@click.argument('text')
@click.option(
    '--position',
    type=click.Choice(['top', 'bottom', 'left', 'right']),
    default='top',
    help='Annotation position'
)
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='Effect duration (seconds), default 5 seconds'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='Show permanently until manually cleared'
)
@click.pass_context
@print_usage
def annotate(ctx, selector: str, text: str, position: str, life_time: int, longlife: bool):
    """Add annotation on element"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx) as session:
            session.annotate(selector, text, position=position, lifetime=lifetime_ms)
            _print_msg("success", f"Annotation added: {text} ({selector}) (duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector, "text": text, "position": position})

    except CDPError as e:
        _print_msg("error", f"Failed to add annotation: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('underline')
@click.argument('selector', required=False)
@click.option(
    '--text',
    type=str,
    help='Find element by text content (supports partial matching)'
)
@click.option(
    '--color',
    type=str,
    default='magenta',
    help='Line color, default magenta'
)
@click.option(
    '--width',
    type=int,
    default=3,
    help='Line width (pixels), default 3'
)
@click.option(
    '--duration',
    type=int,
    default=1000,
    help='Total animation duration (milliseconds), default 1000'
)
@click.option(
    '--life-time',
    type=int,
    default=5,
    help='Effect duration (seconds), default 5 seconds'
)
@click.option(
    '--longlife',
    is_flag=True,
    help='Show permanently until manually cleared'
)
@click.pass_context
@print_usage
def underline(ctx, selector: Optional[str], text: Optional[str], color: str, width: int, duration: int, life_time: int, longlife: bool):
    """
    Draw line animation under element text line by line

    \b
    Examples:
      frago underline "article"                    # CSS selector
      frago underline --text "Just canceled"       # Find by text
    """
    import json

    if not selector and not text:
        click.echo("Error: must provide SELECTOR or --text parameter", err=True)
        return

    lifetime_ms = 0 if longlife else life_time * 1000
    display_target = f"text: {text}" if text else selector

    # JS code: supports selector or text lookup
    js_code = """
(function(selector, searchText, color, width, duration, lifetime) {
    let elements = [];

    if (searchText) {
        // Find by text
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
                _print_msg("error", f"Element not found: {display_target}", "interaction", {"selector": selector, "text": text})
                return

            _print_msg("success", f"Underlined element: {display_target} (color: {color}, width: {width}px, duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector, "text": text, "color": color, "width": width, "duration": duration})

    except CDPError as e:
        _print_msg("error", f"Underline failed: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('init')
@click.option(
    '--force',
    is_flag=True,
    help='Force recreate existing directories'
)
@print_usage
def init(force: bool):
    """
    Initialize Frago user-level directory structure

    Creates ~/.frago/recipes/ directory and subdirectories:
    - atomic/chrome/: Recipes for Chrome CDP operations
    - atomic/system/: Recipes for system operations
    - workflows/: Workflows that orchestrate multiple Recipes
    """
    from pathlib import Path

    user_home = Path.home()
    frago_dir = user_home / '.frago'
    recipes_dir = frago_dir / 'recipes'

    # List of directories to create
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
            click.echo(f"Failed to create directory {directory}: {e}", err=True)
            return

    # Output results
    if created:
        click.echo("Created the following directories:")
        for dir_path in created:
            click.echo(f"  [OK] {dir_path}")

    if skipped:
        click.echo("\nThe following directories already exist (use --force to recreate):")
        for dir_path in skipped:
            click.echo(f"  - {dir_path}")

    if not created and not skipped:
        click.echo("All directories already exist")

    click.echo(f"\nUser-level Recipe directory: {recipes_dir}")
    click.echo("Use 'frago recipe copy <name>' to copy sample Recipes to this directory")


# ============================================================
# Chrome Browser Management Commands
# ============================================================


@click.command('chrome')
@click.option(
    '--headless',
    is_flag=True,
    help='Headless mode: run without window'
)
@click.option(
    '--void',
    is_flag=True,
    help='Void mode: window moved off-screen (does not affect current desktop)'
)
@click.option(
    '--port',
    type=int,
    default=9222,
    help='CDP debug port, default 9222'
)
@click.option(
    '--width',
    type=int,
    default=1280,
    help='Window width, default 1280'
)
@click.option(
    '--height',
    type=int,
    default=960,
    help='Window height, default 960'
)
@click.option(
    '--profile-dir',
    type=click.Path(),
    help='Chrome user data directory (default ~/.frago/chrome_profile)'
)
@click.option(
    '--no-kill',
    is_flag=True,
    help='Do not kill existing CDP Chrome processes'
)
@click.option(
    '--keep-alive',
    is_flag=True,
    help='Keep running after launch until Ctrl+C'
)
@print_usage
def chrome_start(headless: bool, void: bool, port: int, width: int, height: int,
                 profile_dir: str, no_kill: bool, keep_alive: bool):
    """
    Launch Chrome browser (with CDP debugging support)

    \b
    Mode descriptions:
      default    - Normal window mode
      --headless - Run without UI
      --void     - Window hidden off-screen

    \b
    Examples:
      frago chrome                    # Normal launch
      frago chrome --headless         # Headless mode
      frago chrome --void             # Void mode
      frago chrome --port 9333        # Use different port
      frago chrome --keep-alive       # Keep running after launch
    """
    from ..cdp.commands.chrome import ChromeLauncher
    from pathlib import Path

    # headless and void are mutually exclusive
    if headless and void:
        click.echo("Warning: --headless and --void cannot be used together, will use --headless mode")
        void = False

    profile_path = Path(profile_dir) if profile_dir else None

    # Detect if a non-default port was explicitly specified
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

    # Check if Chrome exists
    if not launcher.chrome_path:
        click.echo("Error: Chrome browser not found", err=True)
        click.echo("Please install Google Chrome or Chromium browser", err=True)
        return

    click.echo(f"Chrome path: {launcher.chrome_path}")
    click.echo(f"Profile directory: {launcher.profile_dir}")
    click.echo(f"CDP port: {port}")
    click.echo(f"Mode: {'headless' if headless else 'void' if void else 'normal window'}")

    # Launch Chrome
    if launcher.launch(kill_existing=not no_kill):
        click.echo(f"\n[OK] Chrome launched, CDP listening on port: {port}")

        # Get and display status
        status_info = launcher.get_status()
        if status_info.get("running"):
            click.echo(f"Browser: {status_info.get('browser', 'unknown')}")

        if keep_alive:
            click.echo("\nPress Ctrl+C to stop Chrome...")

            import signal

            def signal_handler(_signum, _frame):
                click.echo("\nClosing Chrome...")
                launcher.stop()
                sys.exit(0)

            signal.signal(signal.SIGINT, signal_handler)

            try:
                while True:
                    time.sleep(30)
                    # Periodically check status
                    st = launcher.get_status()
                    if not st.get("running"):
                        click.echo("Chrome process has exited")
                        break
            except KeyboardInterrupt:
                pass
            finally:
                launcher.stop()
    else:
        click.echo("[X] Failed to launch Chrome", err=True)


@click.command('chrome-stop')
@click.option(
    '--port',
    type=int,
    default=9222,
    help='CDP debug port, default 9222'
)
@print_usage
def chrome_stop(port: int):
    """
    Stop Chrome CDP process

    Closes the Chrome CDP instance running on the specified port.
    """
    from ..cdp.commands.chrome import ChromeLauncher

    launcher = ChromeLauncher(port=port)
    killed = launcher.kill_existing_chrome()

    if killed > 0:
        click.echo(f"[OK] Closed {killed} Chrome CDP process(es) (port {port})")
    else:
        click.echo(f"No Chrome CDP process found running on port {port}")


@click.command('list-tabs')
@click.pass_context
@print_usage
def list_tabs(ctx):
    """
    List all open browser tabs

    Shows each tab's ID, title and URL, for use with switch-tab command.
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
            click.echo("No open tabs found")
            return

        # Output JSON format for easy program parsing
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
        click.echo(f"Failed to get tabs list: {e}", err=True)


@click.command('switch-tab')
@click.argument('tab_id')
@click.pass_context
@print_usage
def switch_tab(ctx, tab_id: str):
    """
    Switch to specified browser tab

    TAB_ID can be the complete target ID or partial match (e.g., first 8 characters).
    Use list-tabs command to view available tab IDs.
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

        # Find matching tab
        target = None
        for t in targets:
            if t.get('type') == 'page':
                if t.get('id') == tab_id or t.get('id', '').startswith(tab_id):
                    target = t
                    break

        if not target:
            click.echo(f"No matching tab found: {tab_id}", err=True)
            click.echo("Use list-tabs command to view available tabs")
            return

        ws_url = target.get('webSocketDebuggerUrl')
        if not ws_url:
            click.echo(f"Tab {tab_id} has no available WebSocket URL", err=True)
            return

        # Send Page.bringToFront command
        ws = websocket.create_connection(ws_url)
        ws.send(json.dumps({'id': 1, 'method': 'Page.bringToFront', 'params': {}}))
        result = json.loads(ws.recv())
        ws.close()

        if 'error' in result:
            click.echo(f"Switch failed: {result['error']}", err=True)
            return

        _print_msg("success", f"Switched to tab: {target.get('title', 'Unknown')}", "tab_switch", {
            "tab_id": target.get('id'),
            "title": target.get('title'),
            "url": target.get('url')
        })

    except Exception as e:
        click.echo(f"Failed to switch tab: {e}", err=True)