"""dev-load 命令 - 从系统目录加载 frago 资源到当前项目目录（开发者工具）"""

import sys
from pathlib import Path
from typing import Optional

import click

from frago.tools.load import (
    load,
    LoadResult,
)


def _format_result(result: LoadResult, dry_run: bool) -> None:
    """格式化输出加载结果"""
    action_word = "将要加载" if dry_run else "已加载"

    # Commands
    if result.commands_loaded or result.commands_skipped:
        click.echo("\n📦 Commands")
        for name in result.commands_loaded:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.commands_skipped:
            click.echo(f"  - 跳过: {name}")

    # Skills
    if result.skills_loaded or result.skills_skipped:
        click.echo("\n📦 Skills")
        for name in result.skills_loaded:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.skills_skipped:
            click.echo(f"  - 跳过: {name}")

    # Recipes
    if result.recipes_loaded or result.recipes_skipped:
        click.echo("\n📦 Recipes")
        for name in result.recipes_loaded:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.recipes_skipped:
            click.echo(f"  - 跳过: {name}")

    # 错误
    if result.errors:
        click.echo("\n❌ 错误:")
        for error in result.errors:
            click.echo(f"  {error}", err=True)

    # 总计
    total_loaded = (
        len(result.commands_loaded)
        + len(result.skills_loaded)
        + len(result.recipes_loaded)
    )
    total_skipped = (
        len(result.commands_skipped)
        + len(result.skills_skipped)
        + len(result.recipes_skipped)
    )

    click.echo()
    if dry_run:
        click.echo(f"(Dry Run) 将要加载 {total_loaded} 项，跳过 {total_skipped} 项")
    elif result.success:
        click.echo(f"✅ 加载完成: {total_loaded} 项加载，{total_skipped} 项跳过")
    else:
        click.echo("❌ 加载失败", err=True)


@click.command(name="dev-load")
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    required=False,
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="强制覆盖所有已存在文件",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅显示将要执行的操作，不实际加载",
)
@click.option(
    "--commands-only",
    is_flag=True,
    help="仅加载 commands",
)
@click.option(
    "--skills-only",
    is_flag=True,
    help="仅加载 skills",
)
@click.option(
    "--recipes-only",
    is_flag=True,
    help="仅加载 recipes",
)
def dev_load_cmd(
    project_dir: Optional[str],
    force: bool,
    dry_run: bool,
    commands_only: bool,
    skills_only: bool,
    recipes_only: bool,
):
    """
    从系统目录加载 frago 资源到当前项目目录（开发者工具）

    从 ~/.claude 和 ~/.frago/recipes 加载 frago 相关内容，
    安装到项目的 .claude/ 和 examples/ 目录。

    \b
    加载内容:
      ~/.claude/commands/frago.*.md  →  .claude/commands/
      ~/.claude/commands/frago/      →  .claude/commands/frago/
      ~/.claude/skills/frago-*       →  .claude/skills/
      ~/.frago/recipes/              →  examples/

    \b
    PROJECT_DIR: 项目目录（可选，默认为当前目录）

    \b
    示例:
      frago dev-load                    # 加载到当前目录
      frago dev-load ~/my-project       # 加载到指定项目目录
      frago dev-load --force            # 强制覆盖所有文件
      frago dev-load --dry-run          # 预览将要加载的内容
      frago dev-load --commands-only    # 仅加载 commands
      frago dev-load --recipes-only     # 仅加载 recipes
    """
    try:
        # 确定项目目录
        if project_dir:
            project_path = Path(project_dir)
        else:
            project_path = Path.cwd()

        if dry_run:
            click.echo("=== Dry Run 模式 ===")

        click.echo(f"加载到项目目录: {project_path}")

        result = load(
            project_dir=project_path,
            force=force,
            dry_run=dry_run,
            commands_only=commands_only,
            skills_only=skills_only,
            recipes_only=recipes_only,
        )

        _format_result(result, dry_run)

        if not result.success:
            sys.exit(1)

    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
