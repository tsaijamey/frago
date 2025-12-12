"""sync 命令 - 同步 ~/.frago/ 资源到您的仓库"""

import sys
from typing import Optional

import click

from frago.init.configurator import load_config, save_config
from frago.tools.sync_repo import SyncResult, sync


def _format_result(result: SyncResult, dry_run: bool) -> None:
    """格式化输出同步结果"""
    # 冲突信息
    if result.conflicts:
        click.echo()
        click.echo("⚠️  发现资源冲突:")
        for conflict in result.conflicts:
            click.echo(f"  - {conflict}")
        click.echo()
        click.echo("请在 ~/.frago/ 目录中手动解决冲突后重新同步")

    # 错误信息
    if result.errors:
        click.echo()
        for error in result.errors:
            click.echo(f"❌ {error}", err=True)

    # 总结
    click.echo()
    if dry_run:
        click.echo("(预览模式) 以上操作将在实际运行时执行")
    elif result.success:
        summary_parts = []
        if result.local_changes:
            summary_parts.append(f"保存 {len(result.local_changes)} 项本地修改")
        if result.remote_updates:
            summary_parts.append(f"获取 {len(result.remote_updates)} 个仓库更新")
        if result.pushed_to_remote:
            summary_parts.append("已推送到您的仓库")

        if summary_parts:
            click.echo(f"✅ 同步完成: {' | '.join(summary_parts)}")
        else:
            click.echo("✅ 同步完成: 本地资源已是最新")
    else:
        click.echo("❌ 同步失败", err=True)


def _get_configured_repo_url() -> Optional[str]:
    """获取配置的仓库 URL"""
    config = load_config()
    return config.sync_repo_url


@click.command(name="sync")
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅预览将要执行的操作，不实际同步",
)
@click.option(
    "--no-push",
    is_flag=True,
    help="仅保存本地修改，不推送到您的仓库",
)
@click.option(
    "--message",
    "-m",
    type=str,
    help="自定义保存说明",
)
@click.option(
    "--set-repo",
    type=str,
    help="设置仓库地址",
)
def sync_cmd(
    dry_run: bool,
    no_push: bool,
    message: Optional[str],
    set_repo: Optional[str],
):
    """
    同步本地资源到您的仓库

    将 ~/.frago/ 和 ~/.claude/ 中的 Frago 资源同步到配置的仓库，
    实现多设备之间资源共享。

    \b
    同步流程:
      1. 检查本地资源修改，确保不丢失任何内容
      2. 从您的仓库获取其他设备的更新
      3. 更新本地 Claude Code 使用的资源
      4. 将本地修改推送到您的仓库

    \b
    首次使用:
      frago sync --set-repo git@github.com:user/my-resources.git

    \b
    日常使用:
      frago sync              # 同步资源
      frago sync --dry-run    # 预览将要同步的内容
      frago sync --no-push    # 仅获取更新，不推送

    \b
    同步内容:
      ~/.claude/commands/frago.*.md   # 命令文件
      ~/.claude/skills/frago-*        # Skills
      ~/.frago/recipes/               # Recipes
    """
    try:
        # 处理 --set-repo
        if set_repo:
            config = load_config()
            config.sync_repo_url = set_repo
            save_config(config)
            click.echo(f"✅ 已保存仓库配置: {set_repo}")

            # 如果没有其他操作，直接返回
            if not dry_run and not no_push and not message:
                return

        # 获取仓库 URL
        repo_url = set_repo or _get_configured_repo_url()

        if not repo_url:
            click.echo("错误: 未配置仓库", err=True)
            click.echo("")
            click.echo("请先配置仓库:", err=True)
            click.echo("  frago sync --set-repo git@github.com:user/my-resources.git", err=True)
            sys.exit(1)

        if dry_run:
            click.echo("=== 预览模式 ===")
            click.echo()

        result = sync(
            repo_url=repo_url,
            message=message,
            dry_run=dry_run,
            no_push=no_push,
        )

        _format_result(result, dry_run)

        if not result.success:
            sys.exit(1)

    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
