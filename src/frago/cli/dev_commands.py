"""dev 命令组 - Frago 开发者命令

包含:
  - pack: 用户目录 → 打包资源
"""

import click

from .pack_command import dev_pack
from .agent_friendly import AgentFriendlyGroup


@click.group(name="dev", cls=AgentFriendlyGroup)
def dev_group():
    """
    Frago 开发者命令

    用于 Frago 项目开发和测试。

    \b
    子命令:
      pack     用户目录 → 打包资源 (src/frago/resources/)

    \b
    数据流:
      用户目录 (~/.claude/, ~/.frago/)
          ↓ pack
      打包资源 (src/frago/resources/)
          ↓ (PyPI 发布)
      用户安装 (frago init)
          ↓
      用户目录 (~/.claude/, ~/.frago/)

    \b
    示例:
      frago dev pack              # 打包用户目录资源
      frago dev pack --dry-run    # 预览将要同步的文件
      frago dev pack --all        # 忽略清单，同步所有
    """
    pass


# 注册子命令
dev_group.add_command(dev_pack, name="pack")
