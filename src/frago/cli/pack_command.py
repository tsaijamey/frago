"""dev-pack 命令 - 同步用户目录资源到打包目录（用于 PyPI 分发）"""

import fnmatch
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

import click
import yaml

from frago.tools.sync import CommandSync, RecipeSync, SkillSync


# 清单文件路径（与本文件同级）
MANIFEST_FILE = Path(__file__).parent / "pack-manifest.yaml"


def load_manifest() -> Dict[str, Any]:
    """加载打包清单配置"""
    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(f"清单文件不存在: {MANIFEST_FILE}")

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    return manifest or {}


def match_pattern(name: str, patterns: List[str]) -> bool:
    """检查名称是否匹配任意一个模式"""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


@click.command(name="dev-pack")
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
    help="清理目标目录中不存在于清单的文件",
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
    help="仅同步 recipes（不同步 commands 和 skills）",
)
@click.option(
    "--skills-only",
    is_flag=True,
    help="仅同步 skills（不同步 commands 和 recipes）",
)
@click.option(
    "--all",
    "sync_all",
    is_flag=True,
    help="忽略清单，同步所有资源（用于调试）",
)
def dev_pack(
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
    commands_only: bool,
    recipes_only: bool,
    skills_only: bool,
    sync_all: bool,
):
    """
    同步用户目录资源到打包目录（用于 PyPI 分发）

    根据 pack-manifest.yaml 白名单配置，将允许的资源
    从用户目录同步到 src/frago/resources/，用于打包分发。

    源目录:
      ~/.claude/commands/frago.*.md  → src/frago/resources/commands/
      ~/.claude/skills/frago-*       → src/frago/resources/skills/
      ~/.frago/recipes/              → src/frago/resources/recipes/

    \b
    示例:
      frago dev-pack                    # 按清单同步资源
      frago dev-pack --all              # 忽略清单，同步所有
      frago dev-pack --commands-only    # 仅同步 commands
      frago dev-pack --recipes-only     # 仅同步 recipes
      frago dev-pack --skills-only      # 仅同步 skills
      frago dev-pack --files "*stock*"  # 额外过滤
      frago dev-pack --dry-run          # 预览将要同步的文件
      frago dev-pack --clean            # 清理不在清单中的资源
    """
    try:
        # 加载清单
        if sync_all:
            manifest = {"commands": ["*"], "skills": ["*"], "recipes": ["*"]}
            click.echo("⚠️  忽略清单，同步所有资源\n")
        else:
            manifest = load_manifest()
            click.echo(f"📋 清单文件: {MANIFEST_FILE.name}\n")

        # 确定同步范围
        sync_commands = not recipes_only and not skills_only
        sync_skills = not commands_only and not recipes_only
        sync_recipes = not commands_only and not skills_only

        if dry_run:
            click.echo("=== Dry Run 模式 ===\n")

        # 同步 Commands
        if sync_commands:
            _sync_commands(manifest, files, dry_run, do_clean, verbose)

        # 同步 Skills
        if sync_skills:
            if sync_commands:
                click.echo()  # 分隔符
            _sync_skills(manifest, files, dry_run, do_clean, verbose)

        # 同步 Recipes
        if sync_recipes:
            if sync_commands or sync_skills:
                click.echo()  # 分隔符
            _sync_recipes(manifest, files, dry_run, do_clean, verbose)

        if dry_run:
            click.echo("\n(Dry Run 模式，未执行实际操作)")

    except FileNotFoundError as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


def _sync_commands(
    manifest: Dict[str, Any],
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """同步 commands"""
    syncer = CommandSync()
    allowed_patterns = manifest.get("commands", [])

    # 检查源目录是否存在
    if not syncer.source_dir.exists():
        click.echo(f"Commands 源目录不存在: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Commands 同步")

    if not allowed_patterns:
        click.echo("  清单中未配置任何 commands，跳过")
        return

    if do_clean:
        # 清理模式：删除不在清单中的文件
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
            click.echo("  未找到任何 frago.*.md 命令文件")
        return

    # 按清单过滤
    filtered_results = []
    excluded = []
    for r in results:
        source_name = r["source_name"]
        if match_pattern(source_name, allowed_patterns):
            filtered_results.append(r)
        else:
            excluded.append(r)

    # 统计
    created = [r for r in filtered_results if r["action"] == "create"]
    updated = [r for r in filtered_results if r["action"] == "update"]
    skipped = [r for r in filtered_results if r["action"] == "skip"]

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

    if excluded and verbose:
        click.echo(f"  ⊘ 清单排除 {len(excluded)} 个命令:")
        for r in excluded:
            click.echo(f"    ⊘ {r['source_name']}")

    # 总结
    click.echo(
        f"  总计: {len(created)} 创建, {len(updated)} 更新, {len(skipped)} 跳过"
        + (f", {len(excluded)} 排除" if excluded else "")
    )

    # 同步 frago/ 子目录
    _sync_frago_subdir(syncer, manifest, dry_run, verbose)


def _sync_frago_subdir(
    syncer: CommandSync,
    manifest: Dict[str, Any],
    dry_run: bool,
    verbose: bool,
):
    """同步 frago/ 子目录"""
    import shutil

    allowed_patterns = manifest.get("commands", [])

    # 检查是否允许 frago/* 或 frago/
    frago_allowed = any(
        p.startswith("frago/") or p == "frago/*"
        for p in allowed_patterns
    )

    if not frago_allowed:
        if verbose:
            click.echo("  ⊘ frago/ 子目录未在清单中")
        return

    frago_source = syncer.source_dir / "frago"
    frago_target = syncer.target_dir / "frago"

    if not frago_source.exists():
        return

    # 检查是否需要更新
    needs_update = not frago_target.exists()

    if not needs_update:
        for src_file in frago_source.rglob("*"):
            if src_file.is_file():
                rel_path = src_file.relative_to(frago_source)
                target_file = frago_target / rel_path
                if not target_file.exists() or src_file.stat().st_mtime > target_file.stat().st_mtime:
                    needs_update = True
                    break

    action_word = "将要" if dry_run else "已"

    if needs_update:
        if not dry_run:
            if frago_target.exists():
                shutil.rmtree(frago_target)
            shutil.copytree(
                frago_source,
                frago_target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        click.echo(f"  ✓ {action_word}同步 frago/ 子目录")
    else:
        if verbose:
            click.echo("  - frago/ 子目录无变化")


def _sync_skills(
    manifest: Dict[str, Any],
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """同步 skills"""
    import shutil

    syncer = SkillSync()
    allowed_patterns = manifest.get("skills", [])

    # 检查源目录是否存在
    if not syncer.source_dir.exists():
        click.echo(f"Skills 源目录不存在: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Skills 同步")

    if not allowed_patterns:
        click.echo("  清单中未配置任何 skills，跳过")
        return

    if do_clean:
        # 清理模式
        removed = syncer.clean(dry_run=dry_run)
        if removed:
            action_word = "将要删除" if dry_run else "已删除"
            click.echo(f"  {action_word} {len(removed)} 个 Skill:")
            for path in removed:
                click.echo(f"    - {path.name}")
        else:
            click.echo("  没有需要清理的 Skill")
        return

    # 获取所有 skills（不执行复制）
    skill_dirs = syncer.find_skills(pattern=files)

    if not skill_dirs:
        if files:
            click.echo(f"  未找到匹配 '{files}' 的 Skill")
        else:
            click.echo("  未找到任何 Skill")
        return

    # 先按清单过滤，再决定是否同步
    filtered_dirs = []
    excluded = []
    for skill_dir in skill_dirs:
        skill_name = skill_dir.name

        if match_pattern(skill_name, allowed_patterns):
            filtered_dirs.append(skill_dir)
        else:
            excluded.append(skill_name)

    # 对过滤后的 skills 执行同步
    created = []
    updated = []
    skipped = []

    for skill_dir in filtered_dirs:
        skill_name = skill_dir.name
        target_dir = syncer.target_dir / skill_name

        # 确定操作类型
        if target_dir.exists():
            needs_update = False
            for src_file in skill_dir.rglob("*"):
                if src_file.is_file() and "__pycache__" not in str(src_file):
                    rel_file = src_file.relative_to(skill_dir)
                    tgt_file = target_dir / rel_file
                    if not tgt_file.exists() or src_file.stat().st_mtime > tgt_file.stat().st_mtime:
                        needs_update = True
                        break
            action = "update" if needs_update else "skip"
        else:
            action = "create"

        result = {
            "skill_name": skill_name,
            "source_dir": skill_dir,
            "target_dir": target_dir,
            "action": action,
        }

        if action == "skip":
            skipped.append(result)
            continue

        # 执行复制
        if not dry_run:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                skill_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

        if action == "create":
            created.append(result)
        else:
            updated.append(result)

    action_word = "将要" if dry_run else "已"

    # 显示结果
    if created:
        click.echo(f"  ✓ {action_word}创建 {len(created)} 个 Skill:")
        for r in created:
            click.echo(f"    + {r['skill_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if updated:
        click.echo(f"  ✓ {action_word}更新 {len(updated)} 个 Skill:")
        for r in updated:
            click.echo(f"    ~ {r['skill_name']}")
            if verbose:
                click.echo(f"      → {r['target_dir']}")

    if skipped and verbose:
        click.echo(f"  - 跳过 {len(skipped)} 个未变化的 Skill:")
        for r in skipped:
            click.echo(f"    = {r['skill_name']}")

    if excluded and verbose:
        click.echo(f"  ⊘ 清单排除 {len(excluded)} 个 Skill:")
        for name in excluded:
            click.echo(f"    ⊘ {name}")

    # 总结
    click.echo(
        f"  总计: {len(created)} 创建, {len(updated)} 更新, {len(skipped)} 跳过"
        + (f", {len(excluded)} 排除" if excluded else "")
    )


def _sync_recipes(
    manifest: Dict[str, Any],
    files: Optional[str],
    dry_run: bool,
    do_clean: bool,
    verbose: bool,
):
    """同步 recipes"""
    import shutil

    syncer = RecipeSync()
    allowed_patterns = manifest.get("recipes", [])

    # 检查源目录是否存在
    if not syncer.source_dir.exists():
        click.echo(f"Recipes 源目录不存在: {syncer.source_dir}", err=True)
        return

    click.echo("📦 Recipes 同步")

    if not allowed_patterns:
        click.echo("  清单中未配置任何 recipes，跳过")
        return

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

    # 获取所有 recipes（不执行复制）
    recipe_dirs = syncer.find_recipes(pattern=files)

    if not recipe_dirs:
        if files:
            click.echo(f"  未找到匹配 '{files}' 的 Recipe")
        else:
            click.echo("  未找到任何 Recipe")
        return

    # 先按清单过滤，再决定是否同步
    filtered_dirs = []
    excluded = []
    for recipe_dir in recipe_dirs:
        rel_path = recipe_dir.relative_to(syncer.source_dir)
        rel_path_str = str(rel_path)

        if match_pattern(rel_path_str, allowed_patterns):
            filtered_dirs.append(recipe_dir)
        else:
            excluded.append(rel_path_str)

    # 对过滤后的 recipes 执行同步
    created = []
    updated = []
    skipped = []

    for recipe_dir in filtered_dirs:
        rel_path = recipe_dir.relative_to(syncer.source_dir)
        recipe_name = recipe_dir.name
        target_dir = syncer.target_dir / rel_path

        # 确定操作类型
        if target_dir.exists():
            needs_update = False
            for src_file in recipe_dir.rglob("*"):
                if src_file.is_file() and "__pycache__" not in str(src_file):
                    rel_file = src_file.relative_to(recipe_dir)
                    tgt_file = target_dir / rel_file
                    if not tgt_file.exists() or src_file.stat().st_mtime > tgt_file.stat().st_mtime:
                        needs_update = True
                        break
            action = "update" if needs_update else "skip"
        else:
            action = "create"

        result = {
            "recipe_name": recipe_name,
            "source_dir": recipe_dir,
            "target_dir": target_dir,
            "action": action,
        }

        if action == "skip":
            skipped.append(result)
            continue

        # 执行复制
        if not dry_run:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                recipe_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

        if action == "create":
            created.append(result)
        else:
            updated.append(result)

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

    if excluded and verbose:
        click.echo(f"  ⊘ 清单排除 {len(excluded)} 个 Recipe:")
        for name in excluded:
            click.echo(f"    ⊘ {name}")

    # 总结
    click.echo(
        f"  总计: {len(created)} 创建, {len(updated)} 更新, {len(skipped)} 跳过"
        + (f", {len(excluded)} 排除" if excluded else "")
    )
