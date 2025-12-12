"""use-git 命令组 - 通过 Git 同步 Frago 资源

将 ~/.frago/ 作为 Git 仓库，同步资源到远程仓库，实现多设备共享。
"""

import click

from .agent_friendly import AgentFriendlyGroup
from .sync_command import sync_cmd


@click.group(name="use-git", cls=AgentFriendlyGroup)
def usegit_group():
    """
    [已废弃] 通过 Git 同步 Frago 资源

    此命令已废弃，请使用 `frago sync` 代替。

    \b
    新命令:
      frago sync --set-repo git@github.com:user/my-resources.git  # 首次使用
      frago sync              # 同步资源
      frago sync --dry-run    # 预览将要同步的内容

    \b
    同步内容:
      ~/.claude/commands/frago.*.md   # 命令文件
      ~/.claude/skills/frago-*        # Skills
      ~/.frago/recipes/               # Recipes
    """
    click.echo("⚠️  'frago use-git' 命令已废弃，请使用 'frago sync'", err=True)


# 注册子命令
usegit_group.add_command(sync_cmd, name="sync")
