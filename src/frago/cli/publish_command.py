"""publish 命令 - 从开发环境发布资源到系统目录"""

import sys
from typing import Optional
from pathlib import Path

import click

from frago.tools.publish import publish, PublishResult, get_project_root


def _format_result(result: PublishResult, dry_run: bool) -> None:
    """格式化输出发布结果"""
    action_word = "将要发布" if dry_run else "已发布"

    # Commands
    if result.commands_published or result.commands_skipped:
        click.echo("\n📦 Commands")
        for name in result.commands_published:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.commands_skipped:
            click.echo(f"  - 跳过: {name}")

    # Skills
    if result.skills_published or result.skills_skipped:
        click.echo("\n📦 Skills")
        for name in result.skills_published:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.skills_skipped:
            click.echo(f"  - 跳过: {name}")

    # Recipes
    if result.recipes_published or result.recipes_skipped:
        click.echo("\n📦 Recipes")
        for name in result.recipes_published:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.recipes_skipped:
            click.echo(f"  - 跳过: {name}")

    # 错误
    if result.errors:
        click.echo("\n❌ 错误:")
        for error in result.errors:
            click.echo(f"  {error}", err=True)

    # 总计
    total_published = (
        len(result.commands_published)
        + len(result.skills_published)
        + len(result.recipes_published)
    )
    total_skipped = (
        len(result.commands_skipped)
        + len(result.skills_skipped)
        + len(result.recipes_skipped)
    )

    click.echo()
    if dry_run:
        click.echo(f"(Dry Run) 将要发布 {total_published} 项，跳过 {total_skipped} 项")
    elif result.success:
        click.echo(f"✅ 发布完成: {total_published} 项发布，{total_skipped} 项跳过")
    else:
        click.echo("❌ 发布失败", err=True)


@click.command(name="publish")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="强制覆盖所有已存在文件",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅显示将要执行的操作，不实际发布",
)
@click.option(
    "--commands-only",
    is_flag=True,
    help="仅发布 commands",
)
@click.option(
    "--recipes-only",
    is_flag=True,
    help="仅发布 recipes",
)
@click.option(
    "--skills-only",
    is_flag=True,
    help="仅发布 skills",
)
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="指定项目根目录（默认自动检测）",
)
def publish_cmd(
    force: bool,
    dry_run: bool,
    commands_only: bool,
    recipes_only: bool,
    skills_only: bool,
    project: Optional[str],
):
    """
    从开发环境发布资源到系统目录

    将 Frago 开发环境中的 .claude 和 examples 内容发布到系统目录。
    发布时 frago.dev.*.md 会自动去掉 .dev 后缀。

    \b
    发布内容:
      .claude/commands/frago.dev.*.md  →  ~/.claude/commands/frago.*.md
      .claude/commands/frago/          →  ~/.claude/commands/frago/
      .claude/skills/*                 →  ~/.claude/skills/
      examples/                        →  ~/.frago/recipes/

    \b
    示例:
      frago publish                    # 发布所有资源
      frago publish --force            # 强制覆盖所有文件
      frago publish --dry-run          # 预览将要发布的内容
      frago publish --commands-only    # 仅发布 commands
    """
    try:
        project_root = Path(project) if project else get_project_root()

        if project_root is None:
            click.echo("错误: 未找到 Frago 项目根目录", err=True)
            click.echo("请在 Frago 项目目录下运行此命令，或使用 --project 指定路径", err=True)
            sys.exit(1)

        if dry_run:
            click.echo("=== Dry Run 模式 ===")

        click.echo(f"项目目录: {project_root}")

        result = publish(
            project_root=project_root,
            force=force,
            dry_run=dry_run,
            commands_only=commands_only,
            recipes_only=recipes_only,
            skills_only=skills_only,
        )

        _format_result(result, dry_run)

        if not result.success:
            sys.exit(1)

    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
