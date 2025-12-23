"""use-git command group - Sync Frago resources via Git

Treat ~/.frago/ as a Git repository, sync resources to remote repository for multi-device sharing.
"""

import click

from .agent_friendly import AgentFriendlyGroup
from .sync_command import sync_cmd


@click.group(name="use-git", cls=AgentFriendlyGroup, hidden=True)
def usegit_group():
    """
    [Deprecated] Sync Frago resources via Git

    This command is deprecated, please use `frago sync` instead.

    \b
    New commands:
      frago sync --set-repo git@github.com:user/my-resources.git  # First time use
      frago sync              # Sync resources
      frago sync --dry-run    # Preview content to be synced

    \b
    Sync content:
      ~/.claude/commands/frago.*.md   # Command files
      ~/.claude/skills/frago-*        # Skills
      ~/.frago/recipes/               # Recipes
    """
    click.echo("[!]  'frago use-git' command is deprecated, please use 'frago sync'", err=True)


# Register subcommand
usegit_group.add_command(sync_cmd, name="sync")
