"""sync 命令 - 将系统目录的资源同步到远程仓库"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

import click

from frago.tools.sync_repo import (
    sync_to_repo,
    SyncResult,
)
from frago.init.configurator import load_config, save_config


# 本地仓库缓存目录
SYNC_REPO_CACHE_DIR = Path.home() / ".frago" / "sync-repo"


def _format_result(result: SyncResult, dry_run: bool) -> None:
    """格式化输出同步结果"""
    action_word = "将要同步" if dry_run else "已同步"

    # Commands
    if result.commands_synced or result.commands_skipped:
        click.echo("\n📦 Commands")
        for name in result.commands_synced:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.commands_skipped:
            click.echo(f"  - 跳过: {name}")

    # Skills
    if result.skills_synced or result.skills_skipped:
        click.echo("\n📦 Skills")
        for name in result.skills_synced:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.skills_skipped:
            click.echo(f"  - 跳过: {name}")

    # Recipes
    if result.recipes_synced or result.recipes_skipped:
        click.echo("\n📦 Recipes")
        for name in result.recipes_synced:
            click.echo(f"  ✓ {action_word}: {name}")
        for name in result.recipes_skipped:
            click.echo(f"  - 跳过: {name}")

    # Git 状态
    if result.git_status:
        click.echo(f"\n📝 Git: {result.git_status}")

    # 错误
    if result.errors:
        click.echo("\n❌ 错误:")
        for error in result.errors:
            click.echo(f"  {error}", err=True)

    # 总计
    total_synced = (
        len(result.commands_synced)
        + len(result.skills_synced)
        + len(result.recipes_synced)
    )
    total_skipped = (
        len(result.commands_skipped)
        + len(result.skills_skipped)
        + len(result.recipes_skipped)
    )

    click.echo()
    if dry_run:
        click.echo(f"(Dry Run) 将要同步 {total_synced} 项，跳过 {total_skipped} 项")
    elif result.success:
        click.echo(f"✅ 同步完成: {total_synced} 项同步，{total_skipped} 项跳过")
    else:
        click.echo("❌ 同步失败", err=True)


def _get_configured_repo_url() -> Optional[str]:
    """获取配置的仓库 URL"""
    config = load_config()
    return config.sync_repo_url


def _ensure_local_repo(repo_url: str) -> Path:
    """
    确保本地仓库存在（如果不存在则克隆）

    Returns:
        本地仓库路径
    """
    if SYNC_REPO_CACHE_DIR.exists() and (SYNC_REPO_CACHE_DIR / ".git").exists():
        # 已存在，拉取最新
        click.echo(f"更新本地仓库缓存...")
        subprocess.run(
            ["git", "-C", str(SYNC_REPO_CACHE_DIR), "pull", "--rebase"],
            capture_output=True,
        )
        return SYNC_REPO_CACHE_DIR

    # 克隆新仓库
    click.echo(f"克隆仓库到本地缓存...")
    SYNC_REPO_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["git", "clone", repo_url, str(SYNC_REPO_CACHE_DIR)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"克隆仓库失败: {result.stderr}")

    return SYNC_REPO_CACHE_DIR


def _find_local_repo() -> Optional[Path]:
    """查找本地仓库缓存目录"""
    # 仅使用缓存目录
    if SYNC_REPO_CACHE_DIR.exists() and (SYNC_REPO_CACHE_DIR / ".git").exists():
        return SYNC_REPO_CACHE_DIR

    return None


@click.command(name="sync")
@click.argument(
    "repo_dir",
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
    help="仅显示将要执行的操作，不实际同步",
)
@click.option(
    "--no-push",
    is_flag=True,
    help="仅提交不推送",
)
@click.option(
    "--message",
    "-m",
    type=str,
    help="Git 提交信息",
)
@click.option(
    "--commands-only",
    is_flag=True,
    help="仅同步 commands",
)
@click.option(
    "--recipes-only",
    is_flag=True,
    help="仅同步 recipes",
)
@click.option(
    "--skills-only",
    is_flag=True,
    help="仅同步 skills",
)
@click.option(
    "--set-repo",
    type=str,
    help="设置并保存远程仓库 URL 到配置",
)
def sync(
    repo_dir: Optional[str],
    force: bool,
    dry_run: bool,
    no_push: bool,
    message: Optional[str],
    commands_only: bool,
    recipes_only: bool,
    skills_only: bool,
    set_repo: Optional[str],
):
    """
    将系统目录的资源同步到远程仓库

    从 ~/.claude 和 ~/.frago/recipes 中的 frago 相关内容
    同步到配置的仓库，用于多设备间共享。

    \b
    同步内容:
      ~/.claude/commands/frago.*.md  →  仓库/.claude/commands/
      ~/.claude/skills/*             →  仓库/.claude/skills/
      ~/.frago/recipes/              →  仓库/examples/

    \b
    仓库配置:
      首次使用需要配置仓库: frago sync --set-repo <your-repo-url>
      配置后可直接使用: frago sync

    \b
    REPO_DIR: 本地仓库目录（可选，优先级高于配置）

    \b
    示例:
      frago sync --set-repo git@github.com:user/my-recipes.git  # 配置仓库
      frago sync                                  # 同步到配置的仓库
      frago sync ~/my-recipes                     # 指定本地仓库目录
      frago sync --force                          # 强制覆盖
      frago sync --dry-run                        # 预览将要同步的内容
      frago sync --no-push                        # 仅提交不推送
      frago sync -m "update recipes"              # 自定义提交信息
    """
    try:
        # 处理 --set-repo
        if set_repo:
            config = load_config()
            config.sync_repo_url = set_repo
            save_config(config)
            click.echo(f"✅ 已保存仓库配置: {set_repo}")

            # 如果没有其他操作，直接返回
            if not repo_dir and not force and not dry_run:
                return

        # 确定仓库目录
        if repo_dir:
            repo_path = Path(repo_dir)
        else:
            # 检查配置的仓库 URL
            configured_url = _get_configured_repo_url()

            if configured_url:
                # 使用配置的仓库，确保本地缓存存在
                repo_path = _ensure_local_repo(configured_url)
            else:
                # 尝试查找本地仓库
                repo_path = _find_local_repo()

                if repo_path is None:
                    click.echo("错误: 未配置同步仓库", err=True)
                    click.echo("")
                    click.echo("请先配置仓库:", err=True)
                    click.echo("  frago sync --set-repo git@github.com:user/my-recipes.git", err=True)
                    click.echo("")
                    click.echo("或指定本地仓库目录:", err=True)
                    click.echo("  frago sync ~/my-recipes", err=True)
                    sys.exit(1)

        # 验证是 git 仓库
        if not (repo_path / ".git").exists():
            click.echo(f"错误: {repo_path} 不是 git 仓库", err=True)
            sys.exit(1)

        if dry_run:
            click.echo("=== Dry Run 模式 ===")

        click.echo(f"同步到仓库: {repo_path}")

        result = sync_to_repo(
            repo_dir=repo_path,
            force=force,
            dry_run=dry_run,
            push=not no_push,
            message=message,
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
