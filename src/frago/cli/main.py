#!/usr/bin/env python3
"""
Frago CLI - Chrome DevTools Protocol command-line interface

Provides backward-compatible CLI interface supporting all original shell script features.
"""

import sys
import click
from typing import Optional, List, Tuple
from collections import OrderedDict

from frago import __version__
from .commands import (
    status,
    init as init_dirs,  # Legacy directory init command, kept as init-dirs
)
from .init_command import init  # New environment init command
from .recipe_commands import recipe_group
from .skill_commands import skill_group
from .run_commands import run_group
from .dev_commands import dev_group
from .usegit_commands import usegit_group
from .sync_command import sync_cmd  # Sync command
from .chrome_commands import chrome_group
from .update_command import update
from .agent_command import agent, agent_status
from .gui_command import gui_deps
from .session_commands import session_group
from .view_command import view
from .serve_command import serve
from .agent_friendly import AgentFriendlyGroup


# Command group definitions (by user role)
COMMAND_GROUPS = OrderedDict([
    ("Daily Use", ["chrome", "recipe", "skill", "run", "view", "serve"]),
    ("Session & Intelligence", ["session", "agent", "agent-status"]),
    ("Environment", ["init", "status", "sync", "update"]),
    ("Developer", ["dev", "init-dirs", "gui-deps"]),
])

# Command groups to expand subcommands
EXPAND_SUBCOMMANDS = ["chrome", "recipe", "run", "dev", "session"]

# Chrome subcommand groups
CHROME_SUBGROUPS = OrderedDict([
    ("Lifecycle", ["start", "stop", "status"]),
    ("Tab Management", ["list-tabs", "switch-tab"]),
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
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter):
        """Format command list by groups, expanding subcommand groups"""
        commands: List[Tuple[str, click.Command]] = []
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
    ) -> List[Tuple[str, str]]:
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
    help='Launch GUI (pywebview desktop window)'
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
        proxy_host: Optional[str], proxy_port: Optional[int],
        proxy_username: Optional[str], proxy_password: Optional[str],
        no_proxy: bool, target_id: Optional[str]):
    """
    Frago - AI Agent Multi-Runtime Automation Infrastructure

    \b
    Three Core Systems:
      - Run System    Persistent task context, records complete exploration process
      - Recipe System Metadata-driven reusable automation scripts
      - Chrome CDP    Browser automation low-level capabilities

    \b
    GUI Mode:
      frago --gui    Launch desktop GUI application
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

    # Handle --gui option (launches pywebview desktop window)
    if gui:
        from frago.gui.app import start_gui
        start_gui(debug=debug)
        return

    # Handle --gui-background option (internal, for legacy subprocess calls)
    if gui_background:
        from frago.gui.app import start_gui
        # gui_background means this is a background process started by subprocess, run GUI directly
        start_gui(debug=debug, _background=gui_background)
        return

    # If no subcommand is invoked, show help
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return

    if debug:
        click.echo(f"Debug mode enabled - Host: {host}:{port}, Timeout: {timeout}s")
        if no_proxy:
            click.echo("Proxy disabled (--no-proxy)")
        elif proxy_host and proxy_port:
            click.echo(f"Proxy config: {proxy_host}:{proxy_port}")


# Register top-level commands
cli.add_command(init)  # New environment init command
cli.add_command(init_dirs, name="init-dirs")  # Legacy directory init command
cli.add_command(status)  # CDP connection status (kept at top level for quick checks)
cli.add_command(sync_cmd, name="sync")  # Resource sync command
cli.add_command(update)  # Self-update command
cli.add_command(gui_deps)  # GUI dependency check command

# Command groups
cli.add_command(dev_group)  # Developer command group: dev pack
cli.add_command(usegit_group)  # Git sync command group: use-git sync (deprecated, use sync)
cli.add_command(chrome_group)  # Chrome CDP command group

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

# Serve command - web service GUI
cli.add_command(serve)


def main():
    """CLI entry point"""
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