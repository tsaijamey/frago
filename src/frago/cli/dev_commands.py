"""dev command group - Frago developer commands

Contains:
  - pack: User directory → Package resources
"""

import click

from .pack_command import dev_pack
from .agent_friendly import AgentFriendlyGroup


@click.group(name="dev", cls=AgentFriendlyGroup)
def dev_group():
    """
    Frago developer commands

    For Frago project development and testing.

    \b
    Subcommands:
      pack     User directory → Package resources (src/frago/resources/)

    \b
    Data flow:
      User directory (~/.claude/, ~/.frago/)
          ↓ pack
      Package resources (src/frago/resources/)
          ↓ (PyPI release)
      User installation (frago init)
          ↓
      User directory (~/.claude/, ~/.frago/)

    \b
    Examples:
      frago dev pack              # Package user directory resources
      frago dev pack --dry-run    # Preview files to be synced
      frago dev pack --all        # Ignore manifest, sync all
    """
    pass


# Register subcommand
dev_group.add_command(dev_pack, name="pack")
