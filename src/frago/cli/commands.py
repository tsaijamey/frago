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

from .agent_friendly import AgentFriendlyCommand

# =============================================================================
# Command usage examples (Agent-friendly output)
# =============================================================================

COMMAND_EXAMPLES = {
    # Chrome subcommands — all tab-operating commands require --group (or FRAGO_CURRENT_RUN env)
    "navigate": [
        "frago chrome navigate <url> --group <name>",
        "frago chrome navigate https://example.com --group research",
        "frago chrome navigate https://example.com --group research --wait-for '.content-loaded'",
    ],
    "click": [
        "frago chrome click --group <name> <selector>",
        "frago chrome click --group research 'button.submit'",
        "frago chrome click --group research '#login-btn' --wait-timeout 15",
    ],
    "screenshot": [
        "frago chrome screenshot --group <name> <output_file>",
        "frago chrome screenshot --group research page.png",
        "frago chrome screenshot --group research full.png --full-page --quality 90",
    ],
    "exec-js": [
        "frago chrome exec-js --group <name> <script>",
        "frago chrome exec-js --group research 'document.title'",
        "frago chrome exec-js --group research 'return window.scrollY' --return-value",
        "frago chrome exec-js --group research ./script.js  # Load from file",
    ],
    "get-title": [
        "frago chrome get-title --group <name>",
        "frago chrome get-title --group research",
    ],
    "get-content": [
        "frago chrome get-content --group <name> [selector]",
        "frago chrome get-content --group research",
        "frago chrome get-content --group research 'article.main' --desc 'article-content'",
    ],
    "scroll": [
        "frago chrome scroll --group <name> <distance>",
        "frago chrome scroll --group research 500",
        "frago chrome scroll --group research down",
        "frago chrome scroll --group research up",
    ],
    "scroll-to": [
        "frago chrome scroll-to --group <name> <selector>",
        "frago chrome scroll-to --group research 'article'",
        "frago chrome scroll-to --group research --text 'Section Title'",
    ],
    "wait": [
        "frago chrome wait --group <name> <seconds>",
        "frago chrome wait --group research 2",
    ],
    "zoom": [
        "frago chrome zoom --group <name> <factor>",
        "frago chrome zoom --group research 1.5",
        "frago chrome zoom --group research 1     # Reset to original size",
    ],
    "clear-effects": [
        "frago chrome clear-effects --group <name>",
        "frago chrome clear-effects --group research",
    ],
    "highlight": [
        "frago chrome highlight --group <name> <selector>",
        "frago chrome highlight --group research 'button.primary'",
        "frago chrome highlight --group research '#target' --color red --width 5",
    ],
    "pointer": [
        "frago chrome pointer --group <name> <selector>",
        "frago chrome pointer --group research 'button.submit'",
    ],
    "spotlight": [
        "frago chrome spotlight --group <name> <selector>",
        "frago chrome spotlight --group research '.highlight-me'",
    ],
    "annotate": [
        "frago chrome annotate --group <name> <selector> <text>",
        "frago chrome annotate --group research 'button' 'Click here'",
        "frago chrome annotate --group research '#form' 'Fill this' --position bottom",
    ],
    "underline": [
        "frago chrome underline --group <name> <selector>",
        "frago chrome underline --group research 'article p'",
        "frago chrome underline --group research --text 'Important text'",
    ],
    "groups": [
        "frago chrome groups",
        "frago chrome groups --json",
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
        "frago chrome groups     # List tab groups",
        "frago chrome click      # Click element",
        "frago chrome screenshot # Take screenshot",
    ],
    # Frago top-level commands
    "frago": [
        "frago <command>",
        "frago chrome start      # Start browser",
        "frago status            # Check CDP connection status",
        "frago server            # Start web server",
    ],
    # Chrome additional
    "close-tab": [
        "frago chrome close-tab <tab_id>",
    ],
    "detect": [
        "frago chrome detect",
    ],
    "group-info": [
        "frago chrome group-info <group_name>",
    ],
    "group-close": [
        "frago chrome group-close <group_name>",
    ],
    "group-cleanup": [
        "frago chrome group-cleanup",
    ],
    "reset": [
        "frago chrome reset",
    ],
    # Server
    "server": [
        "frago server",
        "frago server start",
        "frago server --debug",
    ],
    "server/start": [
        "frago server start",
        "frago server start --debug",
    ],
    "server/stop": [
        "frago server stop",
        "frago server stop --force",
    ],
    "server/restart": [
        "frago server restart",
        "frago server restart --force",
    ],
    "server/status": [
        "frago server status",
    ],
    # Recipe
    "recipe": [
        "frago recipe <command>",
        "frago recipe list",
        "frago recipe run <name> --params '{...}'",
        "frago recipe plan <name> --prompt '...'",
        "frago recipe create <name>",
    ],
    "recipe/list": [
        "frago recipe list",
        "frago recipe list --source user --format json",
    ],
    "recipe/info": [
        "frago recipe info <name>",
    ],
    "recipe/run": [
        "frago recipe run <name> --params '{\"key\": \"value\"}'",
        "frago recipe run <name> --params '{...}' --async",
    ],
    "recipe/validate": [
        "frago recipe validate <path>",
        "frago recipe validate ./my-recipe.yaml --strict",
    ],
    "recipe/plan": [
        "frago recipe plan <name> --prompt '<requirement>'",
        "frago recipe plan <name> --prompt-file requirements.txt",
        "frago recipe plan <name> --prompt '...' --type atomic --runtime python",
    ],
    "recipe/create": [
        "frago recipe create <name>",
        "frago recipe create <name> --prompt '<requirement>'",
        "frago recipe create <name> --spec /path/to/spec.md",
    ],
    "recipe/install": [
        "frago recipe install <url>",
    ],
    "recipe/uninstall": [
        "frago recipe uninstall <name>",
        "frago recipe uninstall <name> --source user",
    ],
    "recipe/search": [
        "frago recipe search <query>",
    ],
    "recipe/schedule": [
        "frago recipe schedule <name> --every 1h",
        "frago recipe schedule <name> --cron '0 9 * * *'",
    ],
    "recipe/executions": [
        "frago recipe executions <name>",
    ],
    "recipe/execution": [
        "frago recipe execution <execution_id>",
    ],
    "recipe/cancel": [
        "frago recipe cancel <execution_id>",
    ],
    "recipe/update": [
        "frago recipe update <name>",
    ],
    "recipe/share": [
        "frago recipe share <name>",
    ],
    # Run
    "run": [
        "frago run <command>",
        "frago run list",
        "frago run init '<description>'",
    ],
    "run/init": [
        "frago run init '<description>'",
        "frago run init 'research web scraping'",
    ],
    "run/set-context": [
        "frago run set-context <run_id>",
    ],
    "run/release": [
        "frago run release",
    ],
    "run/list": [
        "frago run list",
        "frago run list --status active --format json",
    ],
    "run/info": [
        "frago run info <run_id>",
    ],
    "run/log": [
        "frago run log --step 'step description' --status success",
    ],
    "run/export": [
        "frago run export <run_id> --format markdown --output report.md",
    ],
    "run/archive": [
        "frago run archive <run_id>",
    ],
    "run/delete": [
        "frago run delete <run_id> --force",
    ],
    "run/discover": [
        "frago run discover",
    ],
    # Session
    "session": [
        "frago session <command>",
        "frago session list",
        "frago session show <id>",
    ],
    "session/list": [
        "frago session list",
        "frago session list --status running --limit 10",
    ],
    "session/show": [
        "frago session show <session_id>",
        "frago session show <id> --format timeline",
    ],
    "session/watch": [
        "frago session watch <session_id> --follow",
    ],
    "session/clean": [
        "frago session clean --before 7d --dry-run",
    ],
    "session/delete": [
        "frago session delete <session_id> --force",
    ],
    "session/sync": [
        "frago session sync",
    ],
    # Agent
    "agent": [
        "frago agent '<prompt>'",
        "frago agent 'fix the login bug' --model sonnet",
    ],
    "agent-status": [
        "frago agent-status",
    ],
    # Schedule
    "schedule": [
        "frago schedule <command>",
        "frago schedule list",
    ],
    "schedule/add": [
        "frago schedule add <recipe> --every 1h",
        "frago schedule add --cron '0 9 * * *' --prompt 'daily check'",
    ],
    "schedule/list": [
        "frago schedule list",
    ],
    "schedule/remove": [
        "frago schedule remove <schedule_id>",
    ],
    "schedule/toggle": [
        "frago schedule toggle <schedule_id>",
    ],
    "schedule/history": [
        "frago schedule history <schedule_id>",
    ],
    "schedule/run": [
        "frago schedule run <schedule_id>",
    ],
    # Client
    "client": [
        "frago client <command>",
        "frago client start",
    ],
    "client/start": [
        "frago client start",
        "frago client start --no-download",
    ],
    "client/status": [
        "frago client status",
    ],
    "client/update": [
        "frago client update",
    ],
    "client/uninstall": [
        "frago client uninstall",
    ],
    # Autostart
    "autostart": [
        "frago autostart <command>",
    ],
    "autostart/enable": [
        "frago autostart enable",
    ],
    "autostart/disable": [
        "frago autostart disable",
    ],
    "autostart/status": [
        "frago autostart status",
    ],
    # Workspace
    "workspace": [
        "frago workspace <command>",
    ],
    "workspace/list": [
        "frago workspace list",
    ],
    "workspace/set-scan-roots": [
        "frago workspace set-scan-roots ~/repos ~/projects",
    ],
    "workspace/collect": [
        "frago workspace collect",
        "frago workspace collect --dry-run",
    ],
    "workspace/pending": [
        "frago workspace pending",
    ],
    # Other top-level
    "sync": [
        "frago sync",
        "frago sync --dry-run",
        "frago sync --no-push",
    ],
    "update": [
        "frago update",
        "frago update --check",
    ],
    "view": [
        "frago view <file>",
        "frago view report.md --theme dark",
    ],
    "book": [
        "frago book",
        "frago book <topic>",
        "frago book chrome-usage --brief",
    ],
    "reply": [
        "frago reply --channel email --params '{...}'",
    ],
    # Channel (task ingestion channel CRUD)
    "channel": [
        "frago channel <command>",
        "frago channel list",
    ],
    "channel/list": [
        "frago channel list",
    ],
    "channel/add": [
        "frago channel add <name> --poll <recipe> --notify <recipe>",
        "frago channel add feishu --poll feishu_poll --notify feishu_notify --interval 300",
    ],
    "channel/rm": [
        "frago channel rm <name>",
    ],
    "channel/edit": [
        "frago channel edit <name> --interval 300",
        "frago channel edit <name> --notify new_notify_recipe",
    ],
    "channel/enable": [
        "frago channel enable",
    ],
    "channel/disable": [
        "frago channel disable",
    ],
    "channel/recipes": [
        "frago channel recipes  # list installed recipes usable for channels",
    ],
    "serve": [
        "frago serve  # deprecated, use 'frago server'",
    ],
    # Cloud
    "login": [
        "frago login",
    ],
    "logout": [
        "frago logout",
    ],
    "whoami": [
        "frago whoami",
        "frago whoami --refresh",
    ],
    "config": [
        "frago config <command>",
    ],
    "config/get": [
        "frago config get <key>",
    ],
    "config/set": [
        "frago config set <key> <value>",
    ],
    "config/list": [
        "frago config list",
    ],
    "market": [
        "frago market <command>",
    ],
    "market/search": [
        "frago market search <query>",
    ],
    "market/info": [
        "frago market info <name>",
    ],
    "market/install": [
        "frago market install <name>",
    ],
    "market/list": [
        "frago market list",
    ],
    "market/uninstall": [
        "frago market uninstall <name>",
    ],
    "install": [
        "frago install <command>",
    ],
    "install/claude-code": [
        "frago install claude-code",
    ],
    "install/check-update": [
        "frago install check-update",
    ],
    # Def
    "def": [
        "frago def <command>",
        "frago def list",
    ],
    "def/add": [
        "frago def add <name> --purpose '...' --schema '{...}'",
    ],
    "def/list": [
        "frago def list",
    ],
    "def/remove": [
        "frago def remove <name>",
    ],
    # Hook-rules — frago-hook routing rules engine (spec 20260419-hook-rules-engine)
    "hook-rules": [
        "frago hook-rules <command>",
        "frago hook-rules list",
        "frago hook-rules list --source=agent",
    ],
    "hook-rules/list": [
        "frago hook-rules list",
        "frago hook-rules list --source=agent --show-disabled",
        "frago hook-rules list --event=PreToolUse",
    ],
    "hook-rules/add": [
        "frago hook-rules add --rule='{\"id\":\"agent-<name>\",\"event\":\"UserPromptSubmit\",\"match\":{\"type\":\"prompt_contains\",\"value\":\"<kw>\"},\"action\":{\"type\":\"inject_book_topic\",\"topic\":\"<topic>\"}}'",
        "See `frago book hook-rules-authoring` for schema and examples.",
    ],
    "hook-rules/show": [
        "frago hook-rules show <rule_id>",
    ],
    "hook-rules/remove": [
        "frago hook-rules remove <rule_id>",
    ],
    "hook-rules/disable": [
        "frago hook-rules disable <rule_id>",
    ],
    "hook-rules/enable": [
        "frago hook-rules enable <rule_id>",
    ],
    "hook-rules/validate": [
        "frago hook-rules validate",
    ],
    # Skill
    "skill": [
        "frago skill <command>",
    ],
    "skill/list": [
        "frago skill list",
    ],
    # Thread — timeline thread organization (spec 20260418-thread-organization)
    "thread": [
        "frago thread <command>",
        "frago thread list",
        "frago thread info <thread_id>",
    ],
    "thread/list": [
        "frago thread list",
        "frago thread list --status active --limit 10",
        "frago thread list --origin internal --subkind reflection",
    ],
    "thread/search": [
        "frago thread search <query>",
        "frago thread search 报销",
        "frago thread search \"\" --task-id t_123",
    ],
    "thread/info": [
        "frago thread info <thread_id>",
        "frago thread info 01HW001 --json",
    ],
    "thread/peek": [
        "frago thread peek <thread_id>",
        "frago thread peek 01HW001",
    ],
    "thread/close": [
        "frago thread close <thread_id>",
    ],
    "thread/open": [
        "frago thread open <thread_id>",
    ],
    "thread/bind-run": [
        "frago thread bind-run <thread_id> <run_instance_id>",
    ],
    "thread/tag": [
        "frago thread tag <thread_id> <tag>",
    ],
    "thread/set-summary": [
        "frago thread set-summary <thread_id> <summary>",
    ],
    # Timeline — unified event timeline (spec 20260418-timeline-event-coverage)
    "timeline": [
        "frago timeline <command>",
        "frago timeline tail --thread <thread_id>",
        "frago timeline view --recent 24h",
    ],
    "timeline/tail": [
        "frago timeline tail --thread <thread_id> --limit 20",
        "frago timeline tail --data-type task_state --task-id <id>",
        "frago timeline tail --origin internal",
    ],
    "timeline/trace": [
        "frago timeline trace <entry_id>",
    ],
    "timeline/search": [
        "frago timeline search --task-id <id>",
        "frago timeline search --data-type thought --subkind reflection",
    ],
    "timeline/view": [
        "frago timeline view --recent 24h",
        "frago timeline view --recent 1h --full",
    ],
    "timeline/task-status": [
        "frago timeline task-status <task_id>",
    ],
    "timeline/append": [
        "frago timeline append --origin internal --subkind pa --data-type thought --thread <id> --event \"...\"",
        "frago timeline append --origin internal --subkind observation --data-type os_event --data '{\"kind\":\"state_change\"}'",
    ],
    # Task — hand-adjust task state via timeline-aware override
    "task": [
        "frago task <command>",
        "frago task mark <task_id> <status>",
    ],
    "task/mark": [
        "frago task mark <task_id> completed --reason \"manual cleanup\"",
        "frago task mark <task_id> failed --error \"zombie killed\"",
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
from ..cdp.tab_group_manager import CHROME_ERRORS, ChromeCommandError

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


def group_option(fn):
    """Shared --group/-g option for all tab-operating commands."""
    return click.option(
        '--group', '-g',
        type=str,
        default=None,
        help='Tab group name (also reads FRAGO_CURRENT_RUN env)',
    )(fn)


def create_session(ctx, *, group: str | None = None, require_group: bool = True) -> CDPSession:
    """
    Create CDP session.

    When require_group=True (default), resolves target from the group's
    current_target_id.  Raises ChromeCommandError("NO_GROUP") if no
    group context is available.

    Management commands (status, reset, group-close) pass require_group=False
    to skip group enforcement — they don't operate on a specific tab.
    """
    target_id = ctx.obj.get('TARGET_ID')

    # Auto-resolve target from tab group when no explicit target_id
    if not target_id and require_group:
        from ..cdp.tab_group_manager import ChromeCommandError, TabGroupManager
        group_name = TabGroupManager.resolve_group_name(group)
        if not group_name:
            raise ChromeCommandError("NO_GROUP", CHROME_ERRORS["NO_GROUP"])
        tgm = TabGroupManager(
            host=ctx.obj['HOST'],
            port=ctx.obj['PORT'],
        )
        target_id = tgm.get_current_target(group_name)
        # Store resolved group in ctx for downstream use
        ctx.obj['_RESOLVED_GROUP'] = group_name

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
        target_id=target_id,
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
        import base64

        from slugify import slugify

        from ..run.screenshot import get_next_screenshot_number

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


# =============================================================================
# Tab management helpers
# =============================================================================

def _get_current_target_id(session: CDPSession) -> Optional[str]:
    """Extract target ID from the current WebSocket connection URL."""
    ws_url = getattr(session, '_ws_url', None)
    if ws_url:
        # ws URL format: ws://host:port/devtools/page/TARGET_ID
        parts = ws_url.rstrip('/').split('/')
        if parts:
            return parts[-1]
    return None


def _lookup_tab_group(tab_id: str, host: str = "127.0.0.1", port: int = 9222) -> Optional[str]:
    """Find which group a tab belongs to. Returns group name or None."""
    try:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=host, port=port)
        for name, group in tgm.list_groups().items():
            if tab_id in group.tabs:
                return name
    except Exception:
        pass
    return None


def _build_group_index(host: str = "127.0.0.1", port: int = 9222) -> dict[str, str]:
    """Build tab_id → group_name mapping for all groups. Returns empty dict on failure."""
    try:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=host, port=port)
        index: dict[str, str] = {}
        for name, group in tgm.list_groups().items():
            for tid in group.tabs:
                index[tid] = name
        return index
    except Exception:
        return {}


def _route_tab_for_navigate(
    ctx, session: CDPSession, url: str, group: Optional[str] = None
) -> tuple[Optional[str], str]:
    """Route to the correct tab for a URL within a group.

    Group context is mandatory — resolved from explicit --group or
    FRAGO_CURRENT_RUN env var.  Raises ChromeCommandError if missing.

    Returns (target_id, resolved_group_name) tuple.
    """
    from ..cdp.tab_group_manager import ChromeCommandError, TabGroupManager

    group_name = TabGroupManager.resolve_group_name(group)
    if not group_name:
        raise ChromeCommandError("NO_GROUP", CHROME_ERRORS["NO_GROUP"])

    tgm = TabGroupManager(
        host=ctx.obj['HOST'],
        port=ctx.obj['PORT'],
    )
    tgm.reconcile()
    tid = tgm.get_or_create_tab(url, group_name, session) or None
    return tid, group_name


def _handle_chrome_command_error(e: ChromeCommandError) -> None:
    """Format and print a ChromeCommandError, then exit."""
    _print_msg("error", f"{e.code}: {e.message}", "chrome", e.context)
    sys.exit(1)


def _check_landing_page_protection(session: CDPSession, ctx=None) -> None:
    """Block operations on the landing page tab and trigger lazy group cleanup.

    Compares the session's current target_id against the landing page.
    Raises ChromeCommandError with LANDING_PAGE_PROTECTED if matched.
    Also runs expired group cleanup as a side effect (lazy scan).
    """
    # Lazy cleanup — runs on every protected command
    if ctx:
        _lazy_cleanup_expired_groups(session, ctx.obj['HOST'], ctx.obj['PORT'])

    try:
        current_id = _get_current_target_id(session)
        if not current_id:
            return
        landing_id = session.get_landing_page_target_id()
        if landing_id and current_id == landing_id:
            raise ChromeCommandError(
                code="LANDING_PAGE_PROTECTED",
                message="landing page is protected and cannot be operated on",
            )
    except ChromeCommandError:
        raise
    except Exception:
        pass  # Best-effort — don't block if detection fails


def _lazy_cleanup_expired_groups(session: CDPSession, host: str, port: int) -> None:
    """Lazily clean up groups that have been inactive for >30 minutes.
    Also ensures the landing page tab exists (auto-restore if missing).
    """
    try:
        from ..cdp.tab_group_manager import TabGroupManager
        tgm = TabGroupManager(host=host, port=port)
        tgm.cleanup_expired_groups(session)
        tgm.ensure_landing_page()
    except Exception:
        pass


def _touch_active_tab(session: CDPSession, host: str, port: int) -> None:
    """Update last_activity timestamp for the currently connected tab.

    Also triggers lazy cleanup of expired groups.
    """
    _lazy_cleanup_expired_groups(session, host, port)
    try:
        from ..cdp.tab_manager import TabManager
        tab_id = _get_current_target_id(session)
        if tab_id:
            tab_mgr = TabManager(host=host, port=port)
            tab_mgr.touch_tab(tab_id)
            tab_mgr._save_state()
    except Exception:
        pass


@click.command('navigate', cls=AgentFriendlyCommand)
@click.argument('url')
@click.option(
    '--group', '-g',
    type=str,
    default=None,
    help='Tab group name for agent isolation (also reads FRAGO_CURRENT_RUN env)'
)
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
@click.option(
    '--no-border',
    is_flag=True,
    default=False,
    help='Disable viewport border indicator (for interactive UIs)'
)
@click.pass_context
@print_usage
def navigate(ctx, url: str, group: Optional[str] = None, wait_for: Optional[str] = None, load_timeout: float = 30, no_border: bool = False):
    """Navigate to URL and get page features after loading"""
    try:
        # navigate does its own tab routing, so skip group enforcement here
        with create_session(ctx, require_group=False) as session:
            # Lazy cleanup of expired groups
            _lazy_cleanup_expired_groups(session, ctx.obj['HOST'], ctx.obj['PORT'])

            # Disable viewport border if requested
            if no_border:
                session.auto_viewport_border = False

            # Tab routing: reuse tab by origin or create new (group enforced here)
            resolved_group = None
            if not ctx.obj.get('TARGET_ID'):
                target_id, resolved_group = _route_tab_for_navigate(ctx, session, url, group=group)
                if target_id:
                    current_id = _get_current_target_id(session)
                    if target_id != current_id:
                        session.disconnect()
                        session.config.target_id = target_id
                        session.connect()

            # 1. Navigate
            session.navigate(url)
            _print_msg("success", f"Navigated to {url}", "navigation", {"url": url})

            # Persist current target_id for non-navigate commands
            if resolved_group:
                try:
                    from ..cdp.tab_group_manager import TabGroupManager
                    tgm = TabGroupManager(host=ctx.obj['HOST'], port=ctx.obj['PORT'])
                    actual_target = _get_current_target_id(session)
                    if actual_target:
                        tgm.set_current_target(resolved_group, actual_target)
                except Exception:
                    pass

            # Print group context (always present — enforced by _route_tab_for_navigate)
            _print_msg("success", f"Tab group: {resolved_group}", "navigation", {"group": resolved_group})

            # 2. Wait for page load
            session.wait_for_load(timeout=load_timeout)
            _print_msg("success", "Page load complete", "navigation")

            # 3. If selector specified, wait for it
            if wait_for:
                session.wait_for_selector(wait_for)
                _print_msg("success", f"Selector ready: {wait_for}", "navigation", {"selector": wait_for})

            # 4. Perception: get DOM features (delay 2s for dynamic content)
            _do_perception(session, f"navigate-{url}", delay=2.0)

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Navigation failed: {e}", "navigation", {"url": url, "error": str(e)})
        sys.exit(1)


@click.command('click', cls=AgentFriendlyCommand)
@click.argument('selector')
@click.option(
    '--wait-timeout',
    type=int,
    default=10,
    help='Wait timeout for element to appear (seconds)'
)
@click.option(
    '--precise',
    is_flag=True,
    default=False,
    help='Use coordinate-based click (dispatchMouseEvent) instead of JS click'
)
@group_option
@click.pass_context
@print_usage
def click_element(ctx, selector: str, wait_timeout: int, precise: bool, group: Optional[str] = None):
    """Click element by selector and get page features"""
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            _touch_active_tab(session, ctx.obj['HOST'], ctx.obj['PORT'])
            if precise:
                session.click_precise(selector, wait_timeout=wait_timeout)
            else:
                session.click(selector, wait_timeout=wait_timeout)
            _print_msg("success", f"Clicked element: {selector}", "interaction", {"selector": selector})

            # Brief wait for page response after click
            time.sleep(0.5)

            # Perception: get DOM features
            _do_perception(session, f"click-{selector}")

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Click failed: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('screenshot', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def screenshot(ctx, output_file: str, full_page: bool, quality: int, group: Optional[str] = None):
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
            from slugify import slugify

            from ..run.screenshot import get_next_screenshot_number

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

        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            _touch_active_tab(session, ctx.obj['HOST'], ctx.obj['PORT'])
            session.screenshot.capture(actual_output_file, full_page=full_page, quality=quality)
            _print_msg("success", f"Screenshot saved to: {actual_output_file}", "screenshot", {"file": actual_output_file, "full_page": full_page})
    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Screenshot failed: {e}", "screenshot", {"file": output_file, "error": str(e)})


@click.command('exec-js', cls=AgentFriendlyCommand)
@click.argument('script')
@click.option(
    '--return-value',
    is_flag=True,
    help='Return JavaScript execution result'
)
@group_option
@click.pass_context
@print_usage
def execute_javascript(ctx, script: str, return_value: bool, group: Optional[str] = None):
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

        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            _touch_active_tab(session, ctx.obj['HOST'], ctx.obj['PORT'])
            result = session.evaluate(script, return_by_value=return_value)
            if return_value:
                _print_msg("success", f"Execution result: {result}", "interaction", {"result": str(result)})
            else:
                _print_msg("success", "JavaScript execution completed", "interaction")

            # Brief wait after JS execution
            time.sleep(0.3)

            # Perception: capture DOM features
            _do_perception(session, "exec-js")

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"JavaScript execution failed: {e}", "interaction", {"error": str(e)})


@click.command('get-title', cls=AgentFriendlyCommand)
@group_option
@click.pass_context
@print_usage
def get_title(ctx, group: Optional[str] = None):
    """Get page title"""
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            title = session.get_title()
            _print_msg("success", f"Page title: {title}", "extraction", {"title": title})
    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
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


@click.command('get-content', cls=AgentFriendlyCommand)
@click.argument('selector', default='body')
@click.option(
    '--desc',
    type=str,
    default=None,
    help='Content description (used for filename generation)'
)
@group_option
@click.pass_context
@print_usage
def get_content(ctx, selector: str, desc: Optional[str], group: Optional[str] = None):
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
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            _touch_active_tab(session, ctx.obj['HOST'], ctx.obj['PORT'])
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
    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Failed to get content: {e}", "extraction", {"selector": selector, "error": str(e)})


@click.command('status', cls=AgentFriendlyCommand)
@click.pass_context
@print_usage
def status(ctx):
    """Check CDP connection status"""
    try:
        with create_session(ctx, require_group=False) as session:
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
                sys.exit(1)
    except CDPError as e:
        _print_msg("error", f"Status check failed: {e}")
        sys.exit(1)


@click.command('scroll', cls=AgentFriendlyCommand)
@click.argument('distance', type=SCROLL_DISTANCE)
@group_option
@click.pass_context
@print_usage
def scroll(ctx, distance: int, group: Optional[str] = None):
    """
    Scroll page and automatically capture page features

    \b
    DISTANCE can be:
      - Pixel value: positive for down, negative for up
      - Alias: down, up, page-down, page-up
    """
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            _touch_active_tab(session, ctx.obj['HOST'], ctx.obj['PORT'])
            session.scroll.scroll(distance)
            _print_msg("success", f"Scrolled {distance} pixels", "interaction", {"distance": distance})

            # Brief wait after scroll
            time.sleep(0.3)

            # Perception: capture DOM features
            _do_perception(session, f"scroll-{distance}px")

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Scroll failed: {e}", "interaction", {"distance": distance, "error": str(e)})


@click.command('scroll-to', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def scroll_to(ctx, selector: Optional[str], text: Optional[str], block: str, group: Optional[str] = None):
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
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
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
                _do_perception(session, f"scroll-to-{(text or selector)}")
            else:
                _print_msg("error", f"Element not found: {display_target}", "interaction", {"selector": selector, "text": text})
                return

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Failed to scroll to element: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('wait', cls=AgentFriendlyCommand)
@click.argument('seconds', type=WAIT_SECONDS)
@group_option
@click.pass_context
@print_usage
def wait(ctx, seconds: float, group: Optional[str] = None):
    """Wait for specified seconds (supports decimals, e.g., 0.5)"""
    try:
        with create_session(ctx, group=group) as session:
            session.wait.wait(seconds)
            _print_msg("success", f"Waited {seconds} seconds")
    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Wait failed: {e}")


@click.command('zoom', cls=AgentFriendlyCommand)
@click.argument('factor', type=ZOOM_FACTOR)
@group_option
@click.pass_context
@print_usage
def zoom(ctx, factor: float, group: Optional[str] = None):
    """
    Set page zoom level and automatically capture page features

    \b
    FACTOR examples: 1.5 (150%), 0.8 (80%), 1 (original size)
    """
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            session.zoom(factor)
            _print_msg("success", f"Page zoom set to: {factor}", "interaction", {"zoom_factor": factor})

            # Brief wait after zoom
            time.sleep(0.2)

            # Perception: capture DOM features
            _do_perception(session, f"zoom-{factor}x")

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Zoom failed: {e}", "interaction", {"zoom_factor": factor, "error": str(e)})


@click.command('clear-effects', cls=AgentFriendlyCommand)
@group_option
@click.pass_context
@print_usage
def clear_effects(ctx, group: Optional[str] = None):
    """Clear all visual effects"""
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            session.clear_effects()
            _print_msg("success", "Visual effects cleared", "interaction")

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Failed to clear effects: {e}", "interaction", {"error": str(e)})


@click.command('highlight', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def highlight(ctx, selector: str, color: str, width: int, life_time: int, longlife: bool, group: Optional[str] = None):
    """Highlight specified element"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            session.highlight(selector, color=color, border_width=width, lifetime=lifetime_ms)
            _print_msg("success", f"Highlighted element: {selector} (color: {color}, width: {width}px, duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector, "color": color, "width": width})

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Highlight failed: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('pointer', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def pointer(ctx, selector: str, life_time: int, longlife: bool, group: Optional[str] = None):
    """Show mouse pointer on element"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            session.pointer(selector, lifetime=lifetime_ms)
            _print_msg("success", f"Pointer shown: {selector} (duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector})

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Failed to show pointer: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('spotlight', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def spotlight(ctx, selector: str, life_time: int, longlife: bool, group: Optional[str] = None):
    """Show element with spotlight effect"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            session.spotlight(selector, lifetime=lifetime_ms)
            _print_msg("success", f"Spotlight shown: {selector} (duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector})

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Spotlight failed: {e}", "interaction", {"selector": selector, "error": str(e)})


@click.command('annotate', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def annotate(ctx, selector: str, text: str, position: str, life_time: int, longlife: bool, group: Optional[str] = None):
    """Add annotation on element"""
    lifetime_ms = 0 if longlife else life_time * 1000
    try:
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            session.annotate(selector, text, position=position, lifetime=lifetime_ms)
            _print_msg("success", f"Annotation added: {text} ({selector}) (duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector, "text": text, "position": position})

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Failed to add annotation: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('underline', cls=AgentFriendlyCommand)
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
@group_option
@click.pass_context
@print_usage
def underline(ctx, selector: Optional[str], text: Optional[str], color: str, width: int, duration: int, life_time: int, longlife: bool, group: Optional[str] = None):
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
        with create_session(ctx, group=group) as session:
            _check_landing_page_protection(session, ctx)
            result = session.evaluate(js_code, return_by_value=True)

            if result == 'element not found':
                _print_msg("error", f"Element not found: {display_target}", "interaction", {"selector": selector, "text": text})
                return

            _print_msg("success", f"Underlined element: {display_target} (color: {color}, width: {width}px, duration: {'permanent' if longlife else f'{life_time}s'})", "interaction", {"selector": selector, "text": text, "color": color, "width": width, "duration": duration})

    except ChromeCommandError as e:
        _handle_chrome_command_error(e)
    except CDPError as e:
        _print_msg("error", f"Underline failed: {e}", "interaction", {"selector": selector, "text": text, "error": str(e)})


@click.command('init', cls=AgentFriendlyCommand)
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


@click.command('chrome', cls=AgentFriendlyCommand)
@click.option(
    '--browser', '-b',
    type=click.Choice(['chrome', 'edge', 'chromium'], case_sensitive=False),
    help='Browser to use (auto-detect if not specified)'
)
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
    '--app',
    'app_mode',
    is_flag=True,
    help='App mode: borderless window (requires --app-url)'
)
@click.option(
    '--app-url',
    type=str,
    help='Initial URL for app mode'
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
    '--window-x',
    type=int,
    help='Window X position (app mode only)'
)
@click.option(
    '--window-y',
    type=int,
    help='Window Y position (app mode only)'
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
def chrome_start(browser: str, headless: bool, void: bool, app_mode: bool, app_url: str,
                 port: int, width: int, height: int, window_x: int, window_y: int,
                 profile_dir: str, no_kill: bool, keep_alive: bool):
    """
    Launch browser with CDP debugging support (Chrome, Edge, or Chromium)

    \b
    Browser selection (--browser/-b):
      chrome   - Google Chrome (default if available)
      edge     - Microsoft Edge
      chromium - Chromium browser
      (auto)   - Auto-detect: Chrome > Edge > Chromium

    \b
    Mode descriptions:
      default    - Normal window mode
      --headless - Run without UI
      --void     - Window hidden off-screen
      --app      - App mode: borderless window (requires --app-url)

    \b
    Examples:
      frago chrome                              # Auto-detect browser
      frago chrome --browser edge               # Use Edge browser
      frago chrome -b chromium                  # Use Chromium
      frago chrome --headless                   # Headless mode
      frago chrome --void                       # Void mode
      frago chrome --app --app-url https://...  # App mode
      frago chrome --port 9333                  # Use different port
      frago chrome --keep-alive                 # Keep running after launch
    """
    from pathlib import Path

    from ..cdp.commands.chrome import ChromeLauncher

    # Mode exclusivity check
    mode_count = sum([headless, void, app_mode])
    if mode_count > 1:
        click.echo("Error: --headless, --void, and --app are mutually exclusive", err=True)
        return

    # App mode requires URL
    if app_mode and not app_url:
        click.echo("Error: --app mode requires --app-url to be specified", err=True)
        click.echo("Example: frago chrome start --app --app-url http://localhost:8093/viewer/...", err=True)
        return

    # Window position only used for app mode
    if (window_x is not None or window_y is not None) and not app_mode:
        click.echo("Warning: --window-x and --window-y are only used in --app mode", err=True)

    profile_path = Path(profile_dir) if profile_dir else None

    # Detect if a non-default port was explicitly specified
    use_port_suffix = (port != 9222) and (profile_dir is None)

    launcher = ChromeLauncher(
        headless=headless,
        void=void,
        app_mode=app_mode,
        app_url=app_url,
        port=port,
        width=width,
        height=height,
        window_x=window_x,
        window_y=window_y,
        profile_dir=profile_path,
        use_port_suffix=use_port_suffix,
        browser=browser,
    )

    # Check if browser exists
    if not launcher.browser_path:
        if browser:
            click.echo(f"Error: {browser.title()} browser not found", err=True)
        else:
            click.echo("Error: No supported browser found (Chrome, Edge, or Chromium)", err=True)
        click.echo("Please install Google Chrome, Microsoft Edge, or Chromium browser", err=True)
        return

    click.echo(f"Browser: {launcher.browser_type.value.title()} ({launcher.browser_path})")
    click.echo(f"Profile directory: {launcher.profile_dir}")
    click.echo(f"CDP port: {port}")

    mode_str = 'app' if app_mode else 'headless' if headless else 'void' if void else 'normal window'
    click.echo(f"Mode: {mode_str}")

    if app_mode:
        click.echo(f"App URL: {app_url}")
        if window_x is not None and window_y is not None:
            click.echo(f"Window position: ({window_x}, {window_y})")

    # Launch browser
    if launcher.launch(kill_existing=not no_kill):
        click.echo(f"\n[OK] Browser launched, CDP listening on port: {port}")

        # Get and display status
        status_info = launcher.get_status()
        if status_info.get("running"):
            click.echo(f"Version: {status_info.get('browser', 'unknown')}")

        if keep_alive:
            click.echo("\nPress Ctrl+C to stop browser...")

            import signal

            def signal_handler(_signum, _frame):
                click.echo("\nClosing browser...")
                launcher.stop()
                sys.exit(0)

            signal.signal(signal.SIGINT, signal_handler)

            try:
                while True:
                    time.sleep(30)
                    # Periodically check status
                    st = launcher.get_status()
                    if not st.get("running"):
                        click.echo("Browser process has exited")
                        break
            except KeyboardInterrupt:
                pass
            finally:
                launcher.stop()
    else:
        click.echo("[X] Failed to launch browser", err=True)


@click.command('chrome-stop', cls=AgentFriendlyCommand)
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


# =============================================================================
# Tab group commands
# =============================================================================

@click.command('groups', cls=AgentFriendlyCommand)
@click.option('--json', 'as_json', is_flag=True, default=False, help='Output as JSON')
@click.pass_context
@print_usage
def tab_groups(ctx, as_json: bool):
    """List all tab groups and their tab counts"""
    import json as _json

    from ..cdp.tab_group_manager import TabGroupManager

    host = ctx.obj.get('HOST', '127.0.0.1')
    port = ctx.obj.get('PORT', 9222)
    tgm = TabGroupManager(host=host, port=port)
    tgm.reconcile()

    groups = tgm.list_groups()
    if as_json:
        out = {
            name: {
                "tabs": len(g.tabs),
                "created_at": g.created_at,
                "agent_session": g.agent_session,
            }
            for name, g in groups.items()
        }
        click.echo(_json.dumps(out, indent=2))
        return

    if not groups:
        click.echo("No active tab groups")
        return

    for name, g in groups.items():
        click.echo(f"  {name}  ({len(g.tabs)} tabs)")


@click.command('group-info', cls=AgentFriendlyCommand)
@click.argument('group_name')
@click.pass_context
@print_usage
def tab_group_info(ctx, group_name: str):
    """Show details of a tab group"""
    from datetime import datetime

    from ..cdp.tab_group_manager import TabGroupManager

    host = ctx.obj.get('HOST', '127.0.0.1')
    port = ctx.obj.get('PORT', 9222)
    tgm = TabGroupManager(host=host, port=port)
    tgm.reconcile()

    group = tgm.get_group(group_name)
    if not group:
        click.echo(f"Group '{group_name}' not found", err=True)
        sys.exit(1)

    created = datetime.fromtimestamp(group.created_at).strftime("%Y-%m-%d %H:%M:%S")
    click.echo(f"Group: {group_name}")
    click.echo(f"Agent session: {group.agent_session}")
    click.echo(f"Created: {created}")
    click.echo(f"Tabs ({len(group.tabs)}/{group.max_tabs}):")

    for tab in sorted(group.tabs.values(), key=lambda t: t.last_activity, reverse=True):
        title = tab.title or tab.url
        click.echo(f"  [{tab.target_id[:8]}] {title}  ({tab.origin})")


@click.command('group-close', cls=AgentFriendlyCommand)
@click.argument('group_name')
@click.pass_context
@print_usage
def tab_group_close(ctx, group_name: str):
    """Close a tab group and all its tabs"""
    from ..cdp.tab_group_manager import TabGroupManager

    host = ctx.obj.get('HOST', '127.0.0.1')
    port = ctx.obj.get('PORT', 9222)
    tgm = TabGroupManager(host=host, port=port)

    with create_session(ctx, require_group=False) as session:
        if tgm.close_group(group_name, session):
            click.echo(f"Closed group '{group_name}'")
        else:
            click.echo(f"Group '{group_name}' not found", err=True)
            sys.exit(1)


@click.command('group-cleanup', cls=AgentFriendlyCommand)
@click.pass_context
@print_usage
def tab_group_cleanup(ctx):
    """Remove stale groups whose tabs no longer exist"""
    from ..cdp.tab_group_manager import TabGroupManager

    host = ctx.obj.get('HOST', '127.0.0.1')
    port = ctx.obj.get('PORT', 9222)
    tgm = TabGroupManager(host=host, port=port)
    count = tgm.cleanup_stale_groups()
    click.echo(f"Cleaned up {count} stale group(s)")


@click.command('reset', cls=AgentFriendlyCommand)
@click.pass_context
@print_usage
def chrome_reset(ctx):
    """Close all tabs except the landing page

    With FRAGO_CURRENT_RUN set: only closes that agent's group.
    Without: closes all groups and ungrouped non-landing tabs.
    """
    import os as _os

    import requests as _requests

    from ..cdp.tab_group_manager import TabGroupManager

    host = ctx.obj.get('HOST', '127.0.0.1')
    port = ctx.obj.get('PORT', 9222)
    tgm = TabGroupManager(host=host, port=port)

    agent_run = _os.environ.get("FRAGO_CURRENT_RUN")
    click.echo(f"Group context: {agent_run or '(none — global reset)'}")

    with create_session(ctx, require_group=False) as session:
        if agent_run:
            # Only close the current agent's group
            if tgm.close_group(agent_run, session):
                click.echo(f"Reset: closed group '{agent_run}'")
            else:
                click.echo(f"No group '{agent_run}' to reset")
        else:
            # Close all groups
            groups = list(tgm.list_groups().keys())
            for name in groups:
                tgm.close_group(name, session)
                click.echo(f"  Closed group: {name}")

            # Close ungrouped non-landing tabs
            ungrouped_closed = 0
            try:
                resp = _requests.get(f"http://{host}:{port}/json/list", timeout=5)
                for t in resp.json():
                    if t.get("type") != "page":
                        continue
                    url = t.get("url", "")
                    title = t.get("title", "")
                    if "/chrome/dashboard" in url or url.startswith("data:text/html") or title == "frago":
                        continue
                    try:
                        session.target.close_target(t["id"])
                        ungrouped_closed += 1
                    except Exception:
                        pass
            except Exception:
                pass

            click.echo(f"Reset: closed {len(groups)} group(s) and {ungrouped_closed} ungrouped tab(s)")


@click.command('list-tabs', cls=AgentFriendlyCommand)
@click.option('--tracked', is_flag=True, default=False, help='Show tab tracking info (origin, last activity)')
@click.option('--json', 'as_json', is_flag=True, default=False, help='Output as JSON for programmatic use')
@click.pass_context
@print_usage
def list_tabs(ctx, tracked: bool, as_json: bool):
    """
    List all open browser tabs

    Shows each tab's ID, title and URL, for use with switch-tab and close-tab commands.
    Use --tracked to see origin routing and activity information.
    Use --json for machine-readable output.
    """
    import json

    import requests

    config = ctx.obj or {}
    host = config.get('host', GLOBAL_OPTIONS['host'])
    port = config.get('port', GLOBAL_OPTIONS['port'])

    try:
        response = requests.get(f'http://{host}:{port}/json/list', timeout=5)
        targets = response.json()

        pages = [t for t in targets if t.get('type') == 'page']

        if not pages:
            if as_json:
                click.echo(json.dumps([]))
            else:
                click.echo("No open tabs found")
            return

        # Load tracking info if requested
        tracking = {}
        if tracked:
            try:
                from ..cdp.tab_manager import TabManager
                tab_mgr = TabManager(host=host, port=port)
                tab_mgr.reconcile()
                tracking = {e.tab_id: e for e in tab_mgr.get_tracked_tabs()}
            except Exception:
                pass

        # Load group membership
        group_index = _build_group_index(host=host, port=port)

        output = []
        for i, p in enumerate(pages):
            tab_id = p.get('id', '')
            title = p.get('title', 'No Title')
            url = p.get('url', '')

            tab_info = {
                "index": i,
                "id": tab_id,
                "title": title,
                "url": url,
            }

            if tab_id in group_index:
                tab_info["group"] = group_index[tab_id]

            if tracked and tab_id in tracking:
                entry = tracking[tab_id]
                tab_info["origin"] = entry.origin
                tab_info["last_activity"] = entry.last_activity

            output.append(tab_info)

        if as_json:
            click.echo(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            for item in output:
                tab_id = item["id"]
                display_title = item["title"][:50]

                suffix = ""
                group_part = ""
                if "group" in item:
                    group_part = f" group:{item['group']}"
                if "origin" in item:
                    origin_part = f" [{item['origin']}]" if item["origin"] else ""
                    age = time.time() - item["last_activity"]
                    if age < 60:
                        age_part = f" (active {int(age)}s ago)"
                    elif age < 3600:
                        age_part = f" (active {int(age / 60)}m ago)"
                    else:
                        age_part = f" (active {int(age / 3600)}h ago)"
                    suffix = f"{origin_part}{age_part}"

                click.echo(f"{item['index']}. [{tab_id[:8]}...]{group_part}{suffix} {display_title}")
                click.echo(f"   {item['url']}")

    except Exception as e:
        click.echo(f"Failed to get tabs list: {e}", err=True)


@click.command('switch-tab', cls=AgentFriendlyCommand)
@click.argument('tab_id')
@click.pass_context
@print_usage
def switch_tab(ctx, tab_id: str):
    """
    Switch to specified browser tab

    TAB_ID can be the complete target ID or partial match (e.g., first 8 characters).
    Use list-tabs command to view available tab IDs.
    """
    import json

    import requests
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

        # Update tab activity tracking
        full_id = target.get('id')
        try:
            from ..cdp.tab_manager import TabManager
            tab_mgr = TabManager(host=host, port=port)
            tab_mgr.touch_tab(full_id)
            tab_mgr._save_state()
        except Exception:
            pass

        tab_group = _lookup_tab_group(full_id, host=host, port=port)
        # Update group's current_target_id so subsequent commands follow
        if tab_group:
            try:
                from ..cdp.tab_group_manager import TabGroupManager
                tgm = TabGroupManager(host=host, port=port)
                tgm.set_current_target(tab_group, full_id)
            except Exception:
                pass
        group_info = f" (group: {tab_group})" if tab_group else ""
        _print_msg("success", f"Switched to tab: {target.get('title', 'Unknown')}{group_info}", "tab_switch", {
            "tab_id": full_id,
            "title": target.get('title'),
            "url": target.get('url'),
            "group": tab_group,
        })

    except Exception as e:
        click.echo(f"Failed to switch tab: {e}", err=True)


@click.command('close-tab', cls=AgentFriendlyCommand)
@click.argument('tab_id')
@click.pass_context
@print_usage
def close_tab(ctx, tab_id: str):
    """
    Close a browser tab by ID

    TAB_ID can be the complete target ID or partial match (e.g., first 8 characters).
    Use list-tabs command to view available tab IDs.
    """
    import requests

    config = ctx.obj or {}
    host = config.get('host', GLOBAL_OPTIONS['host'])
    port = config.get('port', GLOBAL_OPTIONS['port'])

    try:
        # Find matching tab via HTTP (no session needed for listing)
        response = requests.get(f'http://{host}:{port}/json/list', timeout=5)
        targets = response.json()

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

        full_id = target.get('id')

        # Check group membership before closing
        tab_group = _lookup_tab_group(full_id, host=host, port=port)

        # Close via TargetCommands CDP command
        with create_session(ctx, require_group=False) as session:
            success = session.target.close_target(full_id)

        if success:
            # Remove from TabManager state (best-effort)
            try:
                from ..cdp.tab_manager import TabManager
                tab_mgr = TabManager(host=host, port=port)
                tab_mgr.untrack_tab(full_id)
                tab_mgr._save_state()
            except Exception:
                pass

            # Remove from TabGroupManager if it was grouped
            if tab_group:
                try:
                    from ..cdp.tab_group_manager import TabGroupManager
                    tgm = TabGroupManager(host=host, port=port)
                    grp = tgm.get_group(tab_group)
                    if grp and full_id in grp.tabs:
                        del grp.tabs[full_id]
                        tgm._save_state()
                except Exception:
                    pass

            group_info = f" (removed from group: {tab_group})" if tab_group else ""
            _print_msg("success", f"Closed tab: {target.get('title', 'Unknown')}{group_info}", "tab_close", {
                "tab_id": full_id,
                "title": target.get('title'),
                "url": target.get('url'),
                "group": tab_group,
            })
        else:
            click.echo(f"Failed to close tab: {full_id}", err=True)

    except CDPError as e:
        click.echo(f"Failed to close tab: {e}", err=True)
    except Exception as e:
        click.echo(f"Failed to close tab: {e}", err=True)
