"""Agent-Friendly CLI Enhancement Module

Provide AI Agent with more friendly error messages and help output:
- Show similar command suggestions and available commands list for unknown commands
- Show correct usage examples when parameters are missing
- Expand subcommand groups in help information
"""

import difflib
from typing import List, Optional, Tuple

import click
from click import Context


def get_command_examples(cmd_name: str, group_prefix: str = "") -> List[str]:
    """Get command usage examples

    Args:
        cmd_name: Command name
        group_prefix: Command group prefix (e.g. "chrome")

    Returns:
        List of examples
    """
    # Lazy import to avoid circular dependencies
    from .commands import COMMAND_EXAMPLES

    # Try multiple key name formats
    keys_to_try = [
        f"{group_prefix}/{cmd_name}" if group_prefix else cmd_name,
        cmd_name,
        cmd_name.replace("-", "_"),
    ]

    for key in keys_to_try:
        if key in COMMAND_EXAMPLES:
            return COMMAND_EXAMPLES[key]

    return []


class AgentFriendlyGroup(click.Group):
    """Agent-friendly command group

    Enhanced error handling, provides when command parsing fails:
    - Similar command suggestions (based on edit distance)
    - Correct usage examples
    - Available commands list
    """

    def resolve_command(
        self, ctx: Context, args: List[str]
    ) -> Tuple[Optional[str], Optional[click.Command], List[str]]:
        """Override command resolution to enhance error messages"""
        cmd_name = args[0] if args else None

        if cmd_name:
            cmd = self.get_command(ctx, cmd_name)

            if cmd is None and not ctx.resilient_parsing:
                # Get all available commands
                available = self.list_commands(ctx)

                # Use fuzzy matching to find similar commands
                matches = difflib.get_close_matches(
                    cmd_name, available, n=3, cutoff=0.5
                )

                # Build detailed error message
                error_lines = [f"No such command '{cmd_name}'."]

                if matches:
                    error_lines.append(f"\nDid you mean: {', '.join(matches)}?")

                    # Show usage examples for most similar command
                    group_prefix = self._get_group_prefix(ctx)
                    examples = get_command_examples(matches[0], group_prefix)
                    if examples:
                        error_lines.append(f"\nExample usage for '{matches[0]}':")
                        for ex in examples[:3]:
                            error_lines.append(f"  {ex}")

                # Always show available commands list
                error_lines.append(f"\nAvailable commands: {', '.join(sorted(available))}")

                ctx.fail("\n".join(error_lines))

        return super().resolve_command(ctx, args)

    def _get_group_prefix(self, ctx: Context) -> str:
        """Get current command group prefix (e.g. 'chrome')"""
        if ctx.info_name:
            return ctx.info_name
        return ""

    def make_context(
        self,
        info_name: Optional[str],
        args: List[str],
        parent: Optional[Context] = None,
        **extra,
    ) -> Context:
        """Override context creation to capture and enhance parameter errors"""
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.MissingParameter as e:
            # Enhance missing parameter error message
            self._enhance_missing_param_error(e, info_name, parent)
            raise
        except click.BadParameter as e:
            # Enhance bad parameter error message
            self._enhance_bad_param_error(e, info_name, parent)
            raise

    def _enhance_missing_param_error(
        self,
        error: click.MissingParameter,
        info_name: Optional[str],
        parent: Optional[Context],
    ) -> None:
        """Enhance MissingParameter error message"""
        if not info_name:
            return

        group_prefix = parent.info_name if parent else ""
        examples = get_command_examples(info_name, group_prefix)

        if examples:
            original_msg = error.format_message()
            enhanced_msg = f"{original_msg}\n\nCorrect usage:"
            for ex in examples[:3]:
                enhanced_msg += f"\n  {ex}"
            error.message = enhanced_msg

    def _enhance_bad_param_error(
        self,
        error: click.BadParameter,
        info_name: Optional[str],
        parent: Optional[Context],
    ) -> None:
        """Enhance BadParameter error message"""
        # BadParameter is usually handled well by custom ParamType
        # This serves as an additional enhancement point
        pass


class AgentFriendlyCommand(click.Command):
    """Agent-friendly command

    Provides correct usage examples when parameter parsing fails
    """

    def make_context(
        self,
        info_name: Optional[str],
        args: List[str],
        parent: Optional[Context] = None,
        **extra,
    ) -> Context:
        """Override context creation to capture and enhance parameter errors"""
        try:
            return super().make_context(info_name, args, parent, **extra)
        except click.MissingParameter as e:
            self._enhance_error_with_examples(e, info_name, parent)
            raise
        except click.BadParameter as e:
            # BadParameter usually has detailed information, no additional handling
            raise

    def _enhance_error_with_examples(
        self,
        error: click.MissingParameter,
        info_name: Optional[str],
        parent: Optional[Context],
    ) -> None:
        """Add usage examples to error"""
        if not info_name:
            return

        # Get command group prefix
        group_prefix = ""
        if parent and parent.info_name:
            group_prefix = parent.info_name

        examples = get_command_examples(info_name, group_prefix)

        if examples:
            original_msg = error.format_message()
            enhanced_msg = f"{original_msg}\n\nCorrect usage:"
            for ex in examples[:3]:
                enhanced_msg += f"\n  {ex}"
            error.message = enhanced_msg


def _get_available_options(ctx: Optional[Context]) -> List[str]:
    """Get available options list from context"""
    if not ctx or not ctx.command:
        return []

    options = []
    for param in ctx.command.params:
        if isinstance(param, click.Option):
            # Get option name (prefer long option)
            opt_names = param.opts
            if opt_names:
                # Prefer long options starting with --
                long_opts = [o for o in opt_names if o.startswith("--")]
                if long_opts:
                    options.append(long_opts[0])
                else:
                    options.append(opt_names[0])

    return sorted(options)


def install_agent_friendly_errors():
    """Install global Agent-friendly error handling

    By monkey-patching Click's UsageError.show method,
    automatically add usage examples after all error messages.
    """
    original_show = click.UsageError.show

    def enhanced_show(self, file=None):
        """Enhanced error display"""
        # Call original show method first
        original_show(self, file)

        # Try to get command info from context and add examples
        if not self.ctx:
            return

        cmd_name = self.ctx.info_name
        if not cmd_name:
            return

        # Get parent context's command group name
        group_prefix = ""
        if self.ctx.parent and self.ctx.parent.info_name:
            group_prefix = self.ctx.parent.info_name

        # Get examples
        examples = get_command_examples(cmd_name, group_prefix)
        if not examples:
            return

        # Check error type and add corresponding examples
        error_msg = self.format_message()
        import sys
        err_file = file or sys.stderr

        # Handle missing parameter errors
        if "Missing" in error_msg or "required" in error_msg.lower():
            click.echo("\nCorrect usage:", file=err_file)
            for ex in examples[:3]:
                click.echo(f"  {ex}", file=err_file)
        # Handle invalid option errors
        elif "No such option" in error_msg or "no such option" in error_msg.lower():
            # Show available options
            available_options = _get_available_options(self.ctx)
            if available_options:
                click.echo(f"\nAvailable options: {', '.join(available_options)}", file=err_file)
            # Show correct usage
            click.echo("\nCorrect usage:", file=err_file)
            for ex in examples[:3]:
                click.echo(f"  {ex}", file=err_file)

    click.UsageError.show = enhanced_show


# Automatically install enhanced error handling
install_agent_friendly_errors()
