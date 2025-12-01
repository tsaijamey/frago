"""deploy 命令 - 从远程仓库部署资源到系统目录"""

import sys
from typing import Optional

import click

from frago.tools.deploy import (
    DEFAULT_BRANCH,
    deploy,
    DeployResult,
)
from frago.init.configurator import load_config


def _format_result(result: DeployResult, dry_run: bool) -> None:
    """格式化输出部署结果"""
    action_word = "将要" if dry_run else "已"

    # Commands
    if result.commands_installed or result.commands_skipped:
        click.echo("\n📦 Commands")
        for name in result.commands_installed:
            click.echo(f"  ✓ {action_word}安装: {name}")
        for name in result.commands_skipped:
            click.echo(f"  - 跳过: {name}")

    # Skills
    if result.skills_installed or result.skills_skipped:
        click.echo("\n📦 Skills")
        for name in result.skills_installed:
            click.echo(f"  ✓ {action_word}安装: {name}")
        for name in result.skills_skipped:
            click.echo(f"  - 跳过: {name}")

    # Recipes
    if result.recipes_installed or result.recipes_skipped:
        click.echo("\n📦 Recipes")
        for name in result.recipes_installed:
            click.echo(f"  ✓ {action_word}安装: {name}")
        for name in result.recipes_skipped:
            click.echo(f"  - 跳过: {name}")

    # 错误
    if result.errors:
        click.echo("\n❌ 错误:")
        for error in result.errors:
            click.echo(f"  {error}", err=True)

    # 总计
    total_installed = (
        len(result.commands_installed)
        + len(result.skills_installed)
        + len(result.recipes_installed)
    )
    total_skipped = (
        len(result.commands_skipped)
        + len(result.skills_skipped)
        + len(result.recipes_skipped)
    )

    click.echo()
    if dry_run:
        click.echo(f"(Dry Run) 将要安装 {total_installed} 项，跳过 {total_skipped} 项")
    elif result.success:
        click.echo(f"✅ 部署完成: {total_installed} 项安装，{total_skipped} 项跳过")
    else:
        click.echo("❌ 部署失败", err=True)


def _get_repo_url() -> Optional[str]:
    """获取仓库 URL（从配置读取）"""
    config = load_config()
    return config.sync_repo_url


@click.command(name="deploy")
@click.option(
    "--repo",
    type=str,
    default=None,
    help="远程仓库 URL（默认使用配置或内置默认值）",
)
@click.option(
    "--branch",
    type=str,
    default=DEFAULT_BRANCH,
    help=f"分支名，默认: {DEFAULT_BRANCH}",
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
    help="仅显示将要执行的操作，不实际部署",
)
@click.option(
    "--local",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="使用本地仓库目录（用于开发测试）",
)
def deploy_cmd(
    repo: str,
    branch: str,
    force: bool,
    dry_run: bool,
    local: Optional[str],
):
    """
    从远程仓库部署资源到系统目录

    从用户配置的私有仓库拉取 .claude 和 examples 内容，
    部署到 ~/.claude 和 ~/.frago/recipes。

    \b
    部署内容:
      .claude/commands/frago.dev.*.md  →  ~/.claude/commands/frago.*.md
      .claude/skills/*                 →  ~/.claude/skills/
      examples/                        →  ~/.frago/recipes/

    \b
    首次使用需要配置仓库:
      frago sync --set-repo git@github.com:user/my-recipes.git

    \b
    示例:
      frago deploy                          # 从配置的仓库部署
      frago deploy --repo <url>             # 指定仓库 URL
      frago deploy --force                  # 强制覆盖所有文件
      frago deploy --dry-run                # 预览将要部署的内容
      frago deploy --local ~/my-recipes     # 使用本地仓库目录
    """
    try:
        # 确定仓库 URL
        repo_url = repo or _get_repo_url()

        if not repo_url and not local:
            click.echo("错误: 未配置同步仓库", err=True)
            click.echo("")
            click.echo("请先配置仓库:", err=True)
            click.echo("  frago sync --set-repo git@github.com:user/my-recipes.git", err=True)
            click.echo("")
            click.echo("或使用 --repo 指定仓库 URL:", err=True)
            click.echo("  frago deploy --repo <repo-url>", err=True)
            sys.exit(1)

        if dry_run:
            click.echo("=== Dry Run 模式 ===")

        if local:
            click.echo(f"使用本地仓库: {local}")
        else:
            click.echo(f"从仓库同步: {repo_url} ({branch})")
            click.echo(f"本地缓存: ~/.frago/sync-repo")

        from pathlib import Path
        local_path = Path(local) if local else None

        result = deploy(
            repo_url=repo_url,
            branch=branch,
            force=force,
            dry_run=dry_run,
            local_repo=local_path,
        )

        _format_result(result, dry_run)

        if not result.success:
            sys.exit(1)

    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
