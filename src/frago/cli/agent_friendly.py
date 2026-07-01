"""Agent-Friendly CLI Enhancement Module

Provide AI Agent with more friendly error messages and help output:
- Show similar command suggestions and available commands list for unknown commands
- Show correct usage examples when parameters are missing
- Expand subcommand groups in help information
"""

import difflib
from typing import List, Optional, Sequence, Tuple

import click
from click import Context

# Layer 3 of the agent-friendly mechanism (FRAGO.md): a business-level failure
# should not just say "Error: X" — it should hand the agent a copy-pasteable
# command that fixes the situation. Historically each command group hand-rolled
# this: chrome embeds "start with: uv run frago chrome start" inside its error
# strings, recipe_commands echoes `[Fix] ...` lines manually. The helpers below
# make that pattern a single shared, group-agnostic primitive so any command
# group can attach executable fixes consistently.

FIX_PREFIX = "[Fix]"


def render_fix_lines(fixes: Sequence[str]) -> List[str]:
    """Render executable fix commands as ``[Fix] <command>`` lines.

    Returns one line per fix, matching the format already emitted by
    recipe_commands (``[Fix] frago recipe plan ...``) so adopting this helper
    leaves existing on-screen output byte-identical.
    """
    return [f"{FIX_PREFIX} {fix}" for fix in fixes if fix]


def echo_business_error(message: str, *fixes: str) -> None:
    """Print a business error plus its executable fix command(s) to stderr.

    Usage in any command group::

        echo_business_error("spec.md already exists", "frago recipe plan x --force")

    Emits::

        Error: spec.md already exists
        [Fix] frago recipe plan x --force
    """
    click.echo(f"Error: {message}", err=True)
    for line in render_fix_lines(fixes):
        click.echo(line, err=True)


class BusinessError(click.ClickException):
    """A command business failure that carries optional executable fix command(s).

    Group-agnostic layer-3 primitive: raising this anywhere inside a command
    makes click exit with code 1 and render, on stderr::

        Error: <message>
        [Fix] <fix-1>
        [Fix] <fix-2>

    This replaces hand-rolled ``click.echo("[Fix] ...", err=True); sys.exit(1)``
    blocks with a single raise, while keeping the rendered output identical.
    """

    def __init__(self, message: str, *fixes: str):
        super().__init__(message)
        self.fixes: Tuple[str, ...] = tuple(f for f in fixes if f)

    def show(self, file=None) -> None:  # noqa: D401 - click hook
        click.echo(f"Error: {self.format_message()}", err=True, file=file)
        for line in render_fix_lines(self.fixes):
            click.echo(line, err=True, file=file)


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
            suffix = "\n\nCorrect usage:"
            for ex in examples[:3]:
                suffix += f"\n  {ex}"
            error.message = (error.message or "") + suffix

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
        except click.BadParameter:
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
            suffix = "\n\nCorrect usage:"
            for ex in examples[:3]:
                suffix += f"\n  {ex}"
            error.message = (error.message or "") + suffix


