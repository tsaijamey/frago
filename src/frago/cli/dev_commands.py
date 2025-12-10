"""dev 命令组 - Frago 开发者命令

包含:
  - pack: 开发环境 → 打包资源
  - load: 打包资源 → 开发环境
  - publish: 开发环境 → 用户目录（跳过打包，直接测试）
"""

import click

from .pack_command import dev_pack
from .load_command import dev_load_cmd
from .publish_command import publish_cmd
from .agent_friendly import AgentFriendlyGroup


@click.group(name="dev", cls=AgentFriendlyGroup)
def dev_group():
    """
    Frago 开发者命令

    用于 Frago 项目开发和测试。

    \b
    子命令:
      pack     开发环境 → 打包资源 (src/frago/resources/)
      load     打包资源 → 开发环境（反向恢复）
      publish  开发环境 → 用户目录（跳过打包，直接测试）

    \b
    数据流:
      开发环境 (.claude/, examples/)
          ↓ pack
      打包资源 (src/frago/resources/)
          ↓ (PyPI 发布)
      用户安装 (frago init)
          ↓
      用户目录 (~/.claude/, ~/.frago/)

    \b
    示例:
      frago dev pack              # 打包开发资源
      frago dev publish --force   # 直接发布到用户目录测试
      frago dev load              # 从打包资源恢复开发环境
    """
    pass


# 注册子命令（去掉 dev- 前缀）
dev_group.add_command(dev_pack, name="pack")
dev_group.add_command(dev_load_cmd, name="load")
dev_group.add_command(publish_cmd, name="publish")
