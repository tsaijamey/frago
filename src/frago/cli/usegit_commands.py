"""use-git 命令组 - 从 Git 仓库同步资源

包含:
  - deploy: 从远程仓库部署资源到用户目录
  - sync: 配置和同步远程仓库
"""

import click

from .deploy_command import deploy_cmd
from .sync_command import sync
from .agent_friendly import AgentFriendlyGroup


@click.group(name="use-git", cls=AgentFriendlyGroup)
def usegit_group():
    """
    从 Git 仓库同步资源

    用于从私有 Git 仓库同步 commands、skills 和 recipes 到本地。

    \b
    子命令:
      deploy   从远程仓库部署资源到用户目录
      sync     配置和管理同步仓库

    \b
    使用流程:
      1. 配置仓库: frago use-git sync --set-repo <url>
      2. 部署资源: frago use-git deploy
      3. 更新资源: frago use-git deploy --force

    \b
    示例:
      frago use-git sync --set-repo git@github.com:user/my-recipes.git
      frago use-git deploy
      frago use-git deploy --dry-run
    """
    pass


# 注册子命令
usegit_group.add_command(deploy_cmd, name="deploy")
usegit_group.add_command(sync, name="sync")
