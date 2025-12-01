"""
Sync 模块 - 将系统目录的资源同步到远程仓库

从 ~/.claude 和 ~/.frago/recipes 中的特定内容
同步到用户配置的私有仓库，用于多设备间共享。

仅同步 frago.* 开头的命令，避免将用户私有命令推送到仓库。
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


# 默认分支
DEFAULT_BRANCH = "main"

# 系统级目录
SYSTEM_CLAUDE_DIR = Path.home() / ".claude"
SYSTEM_FRAGO_DIR = Path.home() / ".frago"
SYSTEM_COMMANDS_DIR = SYSTEM_CLAUDE_DIR / "commands"
SYSTEM_SKILLS_DIR = SYSTEM_CLAUDE_DIR / "skills"
SYSTEM_RECIPES_DIR = SYSTEM_FRAGO_DIR / "recipes"

# 同步配置：仅同步 frago.* 开头的命令
COMMANDS_PATTERN = "frago.*.md"


@dataclass
class SyncResult:
    """同步结果"""
    success: bool = False
    commands_synced: List[str] = field(default_factory=list)
    skills_synced: List[str] = field(default_factory=list)
    recipes_synced: List[str] = field(default_factory=list)
    commands_skipped: List[str] = field(default_factory=list)
    skills_skipped: List[str] = field(default_factory=list)
    recipes_skipped: List[str] = field(default_factory=list)
    git_status: str = ""
    errors: List[str] = field(default_factory=list)


def get_dev_name(runtime_name: str) -> str:
    """
    将运行时文件名转换为开发环境文件名

    系统目录中是 frago.*.md，同步到仓库需要转为 frago.dev.*.md。

    Args:
        runtime_name: 系统目录文件名，如 frago.recipe.md

    Returns:
        仓库中的文件名，如 frago.dev.recipe.md
    """
    # frago.xxx.md → frago.dev.xxx.md
    return re.sub(r"^frago\.", "frago.dev.", runtime_name)


def sync_commands_to_repo(
    source_dir: Path,
    target_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    同步 commands 到仓库目录

    系统目录中是 frago.*.md，同步到仓库转换为 frago.dev.*.md。
    同时同步 frago/ 子目录（规则和指南）。

    Args:
        source_dir: 源目录 (~/.claude/commands/)
        target_dir: 目标目录 (仓库中的 .claude/commands/)
        force: 是否强制覆盖
        dry_run: 仅预览不执行

    Returns:
        (synced, skipped) 元组
    """
    synced = []
    skipped = []

    if not source_dir.exists():
        return synced, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 同步 frago.*.md 文件
    for src_file in source_dir.glob(COMMANDS_PATTERN):
        if not src_file.is_file():
            continue

        # 系统目录 frago.*.md → 仓库 frago.dev.*.md
        dev_name = get_dev_name(src_file.name)
        target_file = target_dir / dev_name

        if target_file.exists() and not force:
            if src_file.stat().st_mtime <= target_file.stat().st_mtime:
                skipped.append(f"{src_file.name} → {dev_name}")
                continue

        if not dry_run:
            shutil.copy2(src_file, target_file)
        synced.append(f"{src_file.name} → {dev_name}")

    # 同步 frago/ 子目录（规则和指南）
    frago_source = source_dir / "frago"
    frago_target = target_dir / "frago"

    if frago_source.exists() and frago_source.is_dir():
        needs_update = force or not frago_target.exists()

        if not needs_update:
            # 检查是否有更新的文件
            for src_file in frago_source.rglob("*"):
                if src_file.is_file():
                    rel_path = src_file.relative_to(frago_source)
                    target_file = frago_target / rel_path
                    if not target_file.exists() or src_file.stat().st_mtime > target_file.stat().st_mtime:
                        needs_update = True
                        break

        if needs_update:
            if not dry_run:
                if frago_target.exists():
                    shutil.rmtree(frago_target)
                shutil.copytree(
                    frago_source,
                    frago_target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            synced.append("frago/ (规则和指南)")
        else:
            skipped.append("frago/ (规则和指南)")

    return synced, skipped


def sync_skills_to_repo(
    source_dir: Path,
    target_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    同步 skills 到仓库目录

    Args:
        source_dir: 源目录 (~/.claude/skills/)
        target_dir: 目标目录 (仓库中的 .claude/skills/)
        force: 是否强制覆盖
        dry_run: 仅预览不执行

    Returns:
        (synced, skipped) 元组
    """
    synced = []
    skipped = []

    if not source_dir.exists():
        return synced, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in source_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith('.'):
            continue

        target_skill_dir = target_dir / skill_dir.name

        needs_update = force or not target_skill_dir.exists()

        if not needs_update:
            for src_file in skill_dir.rglob("*"):
                if src_file.is_file():
                    rel_path = src_file.relative_to(skill_dir)
                    target_file = target_skill_dir / rel_path
                    if not target_file.exists() or src_file.stat().st_mtime > target_file.stat().st_mtime:
                        needs_update = True
                        break

        if not needs_update:
            skipped.append(skill_dir.name)
            continue

        if not dry_run:
            if target_skill_dir.exists():
                shutil.rmtree(target_skill_dir)
            shutil.copytree(
                skill_dir,
                target_skill_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        synced.append(skill_dir.name)

    return synced, skipped


def sync_recipes_to_repo(
    source_dir: Path,
    target_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    同步 recipes 到仓库目录

    Args:
        source_dir: 源目录 (~/.frago/recipes/)
        target_dir: 目标目录 (仓库中的 examples/)
        force: 是否强制覆盖
        dry_run: 仅预览不执行

    Returns:
        (synced, skipped) 元组
    """
    synced = []
    skipped = []

    if not source_dir.exists():
        return synced, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 遍历 atomic/ 和 workflows/
    for category in ["atomic", "workflows"]:
        category_dir = source_dir / category
        if not category_dir.exists():
            continue

        if category == "atomic":
            for subcategory in ["chrome", "system"]:
                subcat_dir = category_dir / subcategory
                if not subcat_dir.exists():
                    continue

                for recipe_dir in subcat_dir.iterdir():
                    if not recipe_dir.is_dir():
                        continue
                    if not (recipe_dir / "recipe.md").exists():
                        continue

                    rel_path = f"{category}/{subcategory}/{recipe_dir.name}"
                    target_recipe_dir = target_dir / category / subcategory / recipe_dir.name

                    _sync, _skip = _sync_recipe_dir(
                        recipe_dir, target_recipe_dir, rel_path, force, dry_run
                    )
                    synced.extend(_sync)
                    skipped.extend(_skip)
        else:
            for recipe_dir in category_dir.iterdir():
                if not recipe_dir.is_dir():
                    continue
                if not (recipe_dir / "recipe.md").exists():
                    continue

                rel_path = f"{category}/{recipe_dir.name}"
                target_recipe_dir = target_dir / category / recipe_dir.name

                _sync, _skip = _sync_recipe_dir(
                    recipe_dir, target_recipe_dir, rel_path, force, dry_run
                )
                synced.extend(_sync)
                skipped.extend(_skip)

    return synced, skipped


def _sync_recipe_dir(
    source_dir: Path,
    target_dir: Path,
    rel_path: str,
    force: bool,
    dry_run: bool,
) -> tuple[List[str], List[str]]:
    """同步单个 recipe 目录"""
    synced = []
    skipped = []

    needs_update = force or not target_dir.exists()

    if not needs_update:
        for src_file in source_dir.rglob("*"):
            if src_file.is_file() and "__pycache__" not in str(src_file):
                file_rel = src_file.relative_to(source_dir)
                target_file = target_dir / file_rel
                if not target_file.exists() or src_file.stat().st_mtime > target_file.stat().st_mtime:
                    needs_update = True
                    break

    if not needs_update:
        skipped.append(rel_path)
    else:
        if not dry_run:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                source_dir,
                target_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        synced.append(rel_path)

    return synced, skipped


def get_git_status(repo_dir: Path) -> str:
    """获取 git 仓库状态"""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def git_add_commit_push(
    repo_dir: Path,
    message: str,
    push: bool = True,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    执行 git add, commit, push

    Args:
        repo_dir: 仓库目录
        message: 提交信息
        push: 是否推送
        dry_run: 仅预览不执行

    Returns:
        (success, output) 元组
    """
    try:
        if dry_run:
            status = get_git_status(repo_dir)
            return True, f"[Dry Run] 将要提交的更改:\n{status}"

        # git add
        subprocess.run(
            ["git", "-C", str(repo_dir), "add", "."],
            check=True,
            capture_output=True,
        )

        # 检查是否有更改
        status = get_git_status(repo_dir)
        if not status:
            return True, "没有需要提交的更改"

        # git commit
        subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-m", message],
            check=True,
            capture_output=True,
        )

        output = f"已提交: {message}"

        # git push
        if push:
            subprocess.run(
                ["git", "-C", str(repo_dir), "push"],
                check=True,
                capture_output=True,
            )
            output += "\n已推送到远程仓库"

        return True, output

    except subprocess.CalledProcessError as e:
        return False, f"Git 操作失败: {e.stderr.decode() if e.stderr else str(e)}"


def sync_to_repo(
    repo_dir: Path,
    force: bool = False,
    dry_run: bool = False,
    push: bool = True,
    message: Optional[str] = None,
    commands_only: bool = False,
    recipes_only: bool = False,
    skills_only: bool = False,
) -> SyncResult:
    """
    主同步函数

    将系统目录的资源同步到本地仓库目录。

    Args:
        repo_dir: 本地仓库目录
        force: 强制覆盖所有文件
        dry_run: 仅预览不执行
        push: 是否推送到远程
        message: 提交信息
        commands_only: 仅同步 commands
        recipes_only: 仅同步 recipes
        skills_only: 仅同步 skills

    Returns:
        SyncResult 包含同步结果
    """
    result = SyncResult()

    try:
        # 确定同步范围
        do_commands = not (recipes_only or skills_only)
        do_skills = not (commands_only or recipes_only)
        do_recipes = not (commands_only or skills_only)

        # 同步 commands
        if do_commands:
            target_commands = repo_dir / ".claude" / "commands"
            synced, skipped = sync_commands_to_repo(
                SYSTEM_COMMANDS_DIR, target_commands, force=force, dry_run=dry_run
            )
            result.commands_synced = synced
            result.commands_skipped = skipped

        # 同步 skills
        if do_skills:
            target_skills = repo_dir / ".claude" / "skills"
            synced, skipped = sync_skills_to_repo(
                SYSTEM_SKILLS_DIR, target_skills, force=force, dry_run=dry_run
            )
            result.skills_synced = synced
            result.skills_skipped = skipped

        # 同步 recipes
        if do_recipes:
            target_recipes = repo_dir / "examples"
            synced, skipped = sync_recipes_to_repo(
                SYSTEM_RECIPES_DIR, target_recipes, force=force, dry_run=dry_run
            )
            result.recipes_synced = synced
            result.recipes_skipped = skipped

        # Git 操作
        total_synced = (
            len(result.commands_synced)
            + len(result.skills_synced)
            + len(result.recipes_synced)
        )

        if total_synced > 0 or dry_run:
            if message is None:
                message = f"sync: update {total_synced} resources from system"

            success, git_output = git_add_commit_push(
                repo_dir, message, push=push, dry_run=dry_run
            )

            result.git_status = git_output

            if not success:
                result.errors.append(git_output)
                return result

        result.success = True

    except PermissionError as e:
        result.errors.append(f"权限错误: {e}")
    except Exception as e:
        result.errors.append(f"同步失败: {e}")

    return result
