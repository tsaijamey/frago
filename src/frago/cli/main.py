#!/usr/bin/env python3
"""
Frago CLI - Chrome DevTools Protocol command-line interface

Provides backward-compatible CLI interface supporting all original shell script features.
"""

import sys
from collections import OrderedDict

import click

from frago import __version__

from .agent_command import agent, agent_status
from .agent_friendly import AgentFriendlyGroup
from .autostart_command import autostart_group
from .book_commands import book_command
from .channel_commands import channel_group
from .chrome_commands import chrome_group
from .extension_commands import extension_group
from .client_commands import client_group
from .cloud_commands import (
    config_group,
    install_group,
    login_cmd,
    logout_cmd,
    market_group,
    whoami_cmd,
)
from .commands import (
    init as init_dirs,  # Legacy directory init command, kept as init-dirs
)
from .commands import (
    status,
)
from .def_commands import def_group
from .hook_rules_commands import hook_rules_group
from .init_command import init  # New environment init command
from .recipe_commands import recipe_group
from .reply_command import reply_cmd
from .run_commands import run_group
from .schedule_commands import schedule_group
from .task_commands import task_group
from .thread_commands import thread_group
from .timeline_commands import timeline_group
from .serve_command import serve
from .server_command import server_group
from .session_commands import session_group
from .skill_commands import skill_group
from .start_command import start
from .sync_command import sync_cmd  # Sync command
from .update_command import update
from .usegit_commands import usegit_group
from .view_command import view
from .workspace_commands import workspace_group

# Command group definitions (by user role)
COMMAND_GROUPS = OrderedDict([
    ("Daily Use", ["start", "client", "chrome", "recipe", "skill", "run", "book", "def", "view", "server", "serve"]),
    ("Session & Intelligence", ["session", "agent", "agent-status", "reply", "channel"]),
    ("Cloud", ["login", "logout", "whoami", "config", "market", "install"]),
    ("Environment", ["init", "status", "sync", "workspace", "update", "autostart"]),
    ("Developer", ["dev", "init-dirs"]),
])

# Command groups to expand subcommands
EXPAND_SUBCOMMANDS = ["chrome", "recipe", "run", "dev", "session"]

# Chrome subcommand groups
CHROME_SUBGROUPS = OrderedDict([
    ("Lifecycle", ["start", "stop", "status"]),
    ("Tab Management", ["list-tabs", "switch-tab", "close-tab"]),
    ("Tab Groups", ["groups", "group-info", "group-close", "group-cleanup", "reset"]),
    ("Page Control", ["navigate", "scroll", "scroll-to", "zoom", "wait"]),
    ("Element Interaction", ["click", "exec-js", "get-title", "get-content"]),
    ("Visual Effects", ["screenshot", "highlight", "pointer", "spotlight", "annotate", "underline", "clear-effects"]),
])


class AgentFriendlyGroupedGroup(AgentFriendlyGroup):
    """Agent-friendly grouped command group

    Combines:
    - AgentFriendlyGroup: Enhanced error messages
    - Grouped display: Organize commands by category
    - Subcommand expansion: Show subcommands of command groups in help
    - Dynamic domain commands: registered def domains become top-level commands
    """

    def list_commands(self, ctx: click.Context) -> list[str]:
        builtin = super().list_commands(ctx)
        try:
            from frago.def_.registry import load_registry
            registered = sorted(load_registry().keys())
            # Exclude names that collide with built-in commands
            builtin_set = set(builtin)
            dynamic = [n for n in registered if n not in builtin_set]
            return builtin + dynamic
        except Exception:
            return builtin

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        # Check if it's a registered domain
        try:
            from frago.def_.registry import load_registry
            registry = load_registry()
            if cmd_name in registry:
                from frago.cli.def_commands import build_command_group
                return build_command_group(cmd_name, registry[cmd_name])
        except Exception:
            pass
        return None

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter):
        """Format command list by groups, expanding subcommand groups"""
        commands: list[tuple[str, click.Command]] = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands.append((subcommand, cmd))

        if not commands:
            return

        # Organize commands by groups
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

        # Output grouped commands in COMMAND_GROUPS order
        for group_name in COMMAND_GROUPS:
            if group_name not in grouped:
                continue
            group_cmds = grouped[group_name]
            with formatter.section(group_name):
                rows = []
                for name, cmd in sorted(
                    group_cmds,
                    key=lambda x: COMMAND_GROUPS[group_name].index(x[0])
                ):
                    # Check if subcommands need to be expanded
                    if name in EXPAND_SUBCOMMANDS and isinstance(cmd, click.Group):
                        # Add group itself first
                        rows.append((name, cmd.get_short_help_str(limit=formatter.width)))
                        # Expand subcommands
                        subcommand_rows = self._get_subcommand_rows(ctx, name, cmd)
                        rows.extend(subcommand_rows)
                    else:
                        rows.append((name, cmd.get_short_help_str(limit=formatter.width)))
                formatter.write_dl(rows)

        # Output ungrouped commands
        if ungrouped:
            with formatter.section("Other"):
                formatter.write_dl([
                    (name, cmd.get_short_help_str(limit=formatter.width))
                    for name, cmd in ungrouped
                ])

    def _get_subcommand_rows(
        self,
        ctx: click.Context,
        group_name: str,
        group_cmd: click.Group
    ) -> list[tuple[str, str]]:
        """Get subcommand rows for a command group (with indent prefix)"""
        rows = []

        # Create sub-context to get subcommand list
        with ctx.scope() as sub_ctx:
            sub_ctx.info_name = group_name

            # Get all subcommands
            subcmds = {}
            for subcmd_name in group_cmd.list_commands(sub_ctx):
                subcmd = group_cmd.get_command(sub_ctx, subcmd_name)
                if subcmd is None or subcmd.hidden:
                    continue
                subcmds[subcmd_name] = subcmd

            # Chrome command group uses grouped display
            if group_name == "chrome" and CHROME_SUBGROUPS:
                for subgroup_name, subgroup_cmds in CHROME_SUBGROUPS.items():
                    # Add group label
                    rows.append((f"  [{subgroup_name}]", ""))
                    for subcmd_name in subgroup_cmds:
                        if subcmd_name in subcmds:
                            subcmd = subcmds[subcmd_name]
                            full_name = f"    {group_name} {subcmd_name}"
                            help_str = subcmd.get_short_help_str(limit=55)
                            rows.append((full_name, help_str))
            else:
                # Other command groups use flat display
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
    help='[DEPRECATED] Use "frago server start" instead'
)
@click.option(
    '--gui-background',
    is_flag=True,
    hidden=True,
    help='Internal option: Launch GUI in background mode (for subprocess calls)'
)
@click.option(
    '--debug',
    is_flag=True,
    help='Enable debug mode with verbose logging'
)
@click.option(
    '--timeout',
    type=int,
    default=30,
    help='Set operation timeout in seconds, default 30'
)
@click.option(
    '--host',
    type=str,
    default='127.0.0.1',
    help='Chrome DevTools Protocol host address, default 127.0.0.1'
)
@click.option(
    '--port',
    type=int,
    default=9222,
    help='Chrome DevTools Protocol port, default 9222'
)
@click.option(
    '--proxy-host',
    type=str,
    help='Proxy server host (supports HTTP_PROXY/HTTPS_PROXY env vars)'
)
@click.option(
    '--proxy-port',
    type=int,
    help='Proxy server port'
)
@click.option(
    '--proxy-username',
    type=str,
    help='Proxy authentication username'
)
@click.option(
    '--proxy-password',
    type=str,
    help='Proxy authentication password'
)
@click.option(
    '--no-proxy',
    is_flag=True,
    help='Bypass proxy (ignore env vars and proxy config)'
)
@click.option(
    '--target-id',
    type=str,
    help='Specify target tab ID for precise control in multi-tab environments'
)
@click.pass_context
def cli(ctx, gui: bool, gui_background: bool, debug: bool, timeout: int, host: str, port: int,
        proxy_host: str | None, proxy_port: int | None,
        proxy_username: str | None, proxy_password: str | None,
        no_proxy: bool, target_id: str | None):
    """
    Frago - AI Agent Multi-Runtime Automation Infrastructure

    \b
    Three Core Systems:
      - Run System    Persistent task context, records complete exploration process
      - Recipe System Metadata-driven reusable automation scripts
      - Chrome CDP    Browser automation low-level capabilities

    \b
    GUI Mode (deprecated):
      frago --gui    Use 'frago server start' instead
    """
    # Ensure Windows console can emit CJK / symbols in every subcommand,
    # including when invoked via `frago.exe` (whose entry point is `cli`,
    # not `main`, so the wrapper in main() is bypassed).
    _force_utf8_stdio_on_windows()

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

    # Handle --gui option (deprecated, show migration notice)
    if gui:
        click.echo("⚠️  The --gui option is deprecated.")
        click.echo("")
        click.echo("Please use the web-based interface instead:")
        click.echo("  frago server            # Start the web server")
        click.echo("  frago server stop       # Stop the web server")
        click.echo("  frago server status     # Check server status")
        click.echo("")
        click.echo("Then open http://127.0.0.1:8093 in your browser.")
        return

    # Handle --gui-background option (deprecated)
    if gui_background:
        click.echo("⚠️  The --gui-background option is deprecated.")
        click.echo("Please use 'frago server start' instead.")
        return

    # If no subcommand is invoked, enter chat mode
    if ctx.invoked_subcommand is None:
        from frago.cli.chat import start_chat
        start_chat()
        return

    if debug:
        click.echo(f"Debug mode enabled - Host: {host}:{port}, Timeout: {timeout}s")
        if no_proxy:
            click.echo("Proxy disabled (--no-proxy)")
        elif proxy_host and proxy_port:
            click.echo(f"Proxy config: {proxy_host}:{proxy_port}")


# Register top-level commands
cli.add_command(start)  # User-friendly entry point: starts server + opens browser
cli.add_command(init)  # New environment init command
cli.add_command(init_dirs, name="init-dirs")  # Legacy directory init command
cli.add_command(status)  # CDP connection status (kept at top level for quick checks)
cli.add_command(sync_cmd, name="sync")  # Resource sync command
cli.add_command(update)  # Self-update command

# Command groups
cli.add_command(usegit_group)  # Git sync command group: use-git sync (deprecated, use sync)
cli.add_command(chrome_group)  # Chrome CDP command group
cli.add_command(extension_group, name="extension")  # Browser extension bridge (P1 MVP)

# Recipe management command group
cli.add_command(recipe_group)

# Skill management command group
cli.add_command(skill_group)

# Run command system
cli.add_command(run_group)

# Agent commands
cli.add_command(agent)
cli.add_command(agent_status)

# Session management command group
cli.add_command(session_group)

# View command - universal content viewer
cli.add_command(view)

# Serve command - web service GUI (deprecated, use 'server' instead)
cli.add_command(serve)

# Server command group - background web service management
cli.add_command(server_group)

# Client command group - desktop client management
cli.add_command(client_group)

# Autostart command group - manage server autostart on boot
cli.add_command(autostart_group)

# Workspace command group - agent resource management
cli.add_command(workspace_group)

# Reply command - send replies through ingestion channels
cli.add_command(reply_cmd, name="reply")

# Channel command group - manage task ingestion channels
cli.add_command(channel_group, name="channel")

# Book command - built-in knowledge query
cli.add_command(book_command)

# Def command group - structured knowledge domain management
cli.add_command(def_group)

# Hook-rules command group - manage frago-hook's data-driven routing rules
cli.add_command(hook_rules_group)

# Schedule command group - manage scheduled tasks
cli.add_command(schedule_group, name="schedule")

# Thread command group - timeline thread organization (spec 20260418-thread-organization)
cli.add_command(thread_group, name="thread")

# Timeline command group - unified timeline queries (spec 20260418-timeline-event-coverage)
cli.add_command(timeline_group, name="timeline")

# Task command group - hand-adjust task state via timeline-aware override
cli.add_command(task_group, name="task")

# Cloud commands - frago Cloud authentication, config, and market
cli.add_command(login_cmd, name="login")
cli.add_command(logout_cmd, name="logout")
cli.add_command(whoami_cmd, name="whoami")
cli.add_command(config_group, name="config")
cli.add_command(market_group, name="market")
cli.add_command(install_group, name="install")



def _force_utf8_stdio_on_windows() -> None:
    """Replace sys.stdout/stderr with explicit UTF-8 TextIOWrapper on Windows.

    Japanese/Chinese/Korean Windows editions default console codepage to
    cp932/cp936/cp949, which can't encode the CJK text and box-drawing
    characters frago CLI emits (recipe list tables, def find output, book
    content). English Windows uses cp1252, equally CJK-unfriendly.

    The simpler `sys.stdout.reconfigure(encoding='utf-8')` silently fails
    when stdout is a pipe captured by a parent process (Claude Code →
    Git Bash → frago.exe), leaving Python encoding at locale default.
    Replacing the stream object with a fresh TextIOWrapper on top of the
    raw buffer is the robust path: no hidden wrapper intercepts it, and
    every subsequent write() goes through UTF-8 regardless of TTY state.
    """
    import contextlib
    import io
    import platform
    if platform.system() != "Windows":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            setattr(sys, name, io.TextIOWrapper(
                buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
                write_through=True,
            ))


def main():
    """CLI entry point"""
    _force_utf8_stdio_on_windows()
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\nOperation cancelled", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
