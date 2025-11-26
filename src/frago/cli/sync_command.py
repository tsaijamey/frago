"""sync 命令 - 同步 examples/ 到 resources/recipes/"""

import sys
from typing import Optional

import click

from frago.tools.sync import RecipeSync


@click.command(name="sync")
@click.option(
    "--files",
    type=str,
    default=None,
    help="通配符模式过滤 Recipe 名称，如 *stock* 或 clipboard*",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅显示将要执行的操作，不实际同步",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    help="清理目标目录中不存在于源目录的 Recipe",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细信息",
)
def sync(
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """
    同步 examples/ 目录的 Recipe 到包资源目录

    将 examples/ 下的 Recipe（脚本 + 元数据）同步到
    src/frago/resources/recipes/，用于打包分发。

    \b
    示例:
      uv run frago sync                    # 同步所有 Recipe
      uv run frago sync --files "*stock*"  # 同步名称包含 stock 的 Recipe
      uv run frago sync --dry-run          # 预览将要同步的文件
      uv run frago sync --clean            # 清理已删除的 Recipe
    """
    try:
        syncer = RecipeSync()

        # 检查源目录是否存在
        if not syncer.source_dir.exists():
            click.echo(f"错误: 源目录不存在: {syncer.source_dir}", err=True)
            sys.exit(1)

        if do_clean:
            # 清理模式
            removed = syncer.clean(dry_run=dry_run)
            if removed:
                action_word = "将要删除" if dry_run else "已删除"
                click.echo(f"{action_word} {len(removed)} 个文件:")
                for path in removed:
                    click.echo(f"  - {path}")
            else:
                click.echo("没有需要清理的文件")
            return

        # 同步模式
        results = syncer.sync(pattern=files, dry_run=dry_run, verbose=verbose)

        if not results:
            if files:
                click.echo(f"未找到匹配 '{files}' 的 Recipe")
            else:
                click.echo("未找到任何 Recipe")
            return

        # 统计
        created = [r for r in results if r["action"] == "create"]
        updated = [r for r in results if r["action"] == "update"]
        skipped = [r for r in results if r["action"] == "skip"]

        action_word = "将要" if dry_run else "已"

        if dry_run:
            click.echo("=== Dry Run 模式 ===\n")

        # 显示结果
        if created:
            click.echo(f"✓ {action_word}创建 {len(created)} 个 Recipe:")
            for r in created:
                click.echo(f"  + {r['recipe_name']}")
                if verbose:
                    click.echo(f"    → {r['target_dir']}")

        if updated:
            click.echo(f"✓ {action_word}更新 {len(updated)} 个 Recipe:")
            for r in updated:
                click.echo(f"  ~ {r['recipe_name']}")
                if verbose:
                    click.echo(f"    → {r['target_dir']}")

        if skipped and verbose:
            click.echo(f"- 跳过 {len(skipped)} 个未变化的 Recipe:")
            for r in skipped:
                click.echo(f"  = {r['recipe_name']}")

        # 总结
        click.echo()
        click.echo(
            f"总计: {len(created)} 创建, {len(updated)} 更新, {len(skipped)} 跳过"
        )

        if dry_run:
            click.echo("\n(Dry Run 模式，未执行实际操作)")

    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
