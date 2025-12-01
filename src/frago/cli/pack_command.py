"""pack 命令 - 同步开发资源到打包目录（用于 PyPI 分发）"""

import sys
from typing import Optional

import click

from frago.tools.sync import CommandSync, RecipeSync


@click.command(name="pack")
@click.option(
    "--files",
    type=str,
    default=None,
    help="通配符模式过滤名称，如 *stock* 或 clipboard*",
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
    help="清理目标目录中不存在于源目录的文件",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="显示详细信息",
)
@click.option(
    "--commands-only",
    is_flag=True,
    help="仅同步 commands（不同步 recipes）",
)
@click.option(
    "--recipes-only",
    is_flag=True,
    help="仅同步 recipes（不同步 commands）",
)
def pack(
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
    commands_only: bool,
    recipes_only: bool,
):
    """
    同步开发资源到打包目录（用于 PyPI 分发）

    将 examples/ 下的 Recipe 和 .claude/commands/ 下的命令
    同步到 src/frago/resources/，用于打包分发。

    Commands 同步时会自动去掉 .dev 后缀:
      frago.dev.recipe.md → frago.recipe.md

    \b
    示例:
      frago pack                       # 同步所有资源
      frago pack --commands-only       # 仅同步 commands
      frago pack --recipes-only        # 仅同步 recipes
      frago pack --files "*stock*"     # 同步名称包含 stock 的资源
      frago pack --dry-run             # 预览将要同步的文件
      frago pack --clean               # 清理已删除的资源
    """
    try:
        # 确定同步范围
        sync_commands = not recipes_only
        sync_recipes = not commands_only

        if dry_run:
            click.echo("=== Dry Run 模式 ===\n")

        # 同步 Commands
        if sync_commands:
            _sync_commands(files, dry_run, do_clean, verbose)

        # 同步 Recipes
        if sync_recipes:
            if sync_commands:
                click.echo()  # 分隔符
            _sync_recipes(files, dry_run, do_clean, verbose)

        if dry_run:
            click.echo("\n(Dry Run 模式，未执行实际操作)")

    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


def _sync_commands(
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """同步 commands"""
    syncer = CommandSync()

    # 检查源目录是否存在
    if not syncer.source_dir.exists():
        click.echo(f"Commands 源目录不存在: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Commands 同步")

    if do_clean:
        # 清理模式
        removed = syncer.clean(dry_run=dry_run)
        if removed:
            action_word = "将要删除" if dry_run else "已删除"
            click.echo(f"  {action_word} {len(removed)} 个文件:")
            for path in removed:
                click.echo(f"    - {path.name}")
        else:
            click.echo("  没有需要清理的命令文件")
        return

    # 同步模式
    results = syncer.sync(pattern=files, dry_run=dry_run, verbose=verbose)

    if not results:
        if files:
            click.echo(f"  未找到匹配 '{files}' 的命令")
        else:
            click.echo("  未找到任何 frago.dev.*.md 命令文件")
        return

    # 统计
    created = [r for r in results if r["action"] == "create"]
    updated = [r for r in results if r["action"] == "update"]
    skipped = [r for r in results if r["action"] == "skip"]

    action_word = "将要" if dry_run else "已"

    # 显示结果
    if created:
        click.echo(f"  ✓ {action_word}创建 {len(created)} 个命令:")
        for r in created:
            click.echo(f"    + {r['source_name']} → {r['target_name']}")

    if updated:
        click.echo(f"  ✓ {action_word}更新 {len(updated)} 个命令:")
        for r in updated:
            click.echo(f"    ~ {r['source_name']} → {r['target_name']}")

    if skipped and verbose:
        click.echo(f"  - 跳过 {len(skipped)} 个未变化的命令:")
        for r in skipped:
            click.echo(f"    = {r['source_name']}")

    # 总结
    click.echo(
        f"  总计: {len(created)} 创建, {len(updated)} 更新, {len(skipped)} 跳过"
    )


def _sync_recipes(
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """同步 recipes"""
    syncer = RecipeSync()

    # 检查源目录是否存在
    if not syncer.source_dir.exists():
        click.echo(f"Recipes 源目录不存在: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Recipes 同步")

    if do_clean:
        # 清理模式
        removed = syncer.clean(dry_run=dry_run)
        if removed:
            action_word = "将要删除" if dry_run else "已删除"
            click.echo(f"  {action_word} {len(removed)} 个 Recipe:")
            for path in removed:
                click.echo(f"    - {path.name}")
        else:
            click.echo("  没有需要清理的 Recipe")
        return

    # 同步模式
    results = syncer.sync(pattern=files, dry_run=dry_run, verbose=verbose)

    if not results:
        if files:
            click.echo(f"  未找到匹配 '{files}' 的 Recipe")
        else:
            click.echo("  未找到任何 Recipe")
        return

    # 统计
    created = [r for r in results if r["action"] == "create"]
    updated = [r for r in results if r["action"] == "update"]
    skipped = [r for r in results if r["action"] == "skip"]

    action_word = "将要" if dry_run else "已"

    # 显示结果
    if created:
        click.echo(f"  ✓ {action_word}创建 {len(created)} 个 Recipe:")
        for r in created:
            click.echo(f"    + {r['recipe_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if updated:
        click.echo(f"  ✓ {action_word}更新 {len(updated)} 个 Recipe:")
        for r in updated:
            click.echo(f"    ~ {r['recipe_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if skipped and verbose:
        click.echo(f"  - 跳过 {len(skipped)} 个未变化的 Recipe:")
        for r in skipped:
            click.echo(f"    = {r['recipe_name']}")

    # 总结
    click.echo(
        f"  总计: {len(created)} 创建, {len(updated)} 更新, {len(skipped)} 跳过"
    )
