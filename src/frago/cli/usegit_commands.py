"""use-git 命令组 - 通过 Git 同步 Frago 资源

将 ~/.frago/ 作为 Git 仓库，同步资源到远程仓库，实现多设备共享。
"""

import click

from .agent_friendly import AgentFriendlyGroup
from .sync_command import sync_cmd


@click.group(name="use-git", cls=AgentFriendlyGroup)
def usegit_group():
    """
    通过 Git 同步 Frago 资源

    将本地的命令、Skills 和 Recipes 同步到远程 Git 仓库，
    实现多设备之间的资源共享。

    \b
    首次使用:
      frago use-git sync --set-repo git@github.com:user/my-resources.git

    \b
    日常使用:
      frago use-git sync              # 同步资源
      frago use-git sync --dry-run    # 预览将要同步的内容

    \b
    同步内容:
      ~/.claude/commands/frago.*.md   # 命令文件
      ~/.claude/skills/frago-*        # Skills
      ~/.frago/recipes/               # Recipes
    """
    pass


# 注册子命令
usegit_group.add_command(sync_cmd, name="sync")
