"""
Publish 模块 - 从开发环境发布资源到系统目录

将 Frago 开发环境中的 .claude/commands/ 和 examples/ 内容
发布到 ~/.claude 和 ~/.frago/recipes。

发布时 frago.dev.*.md 会去掉 .dev 后缀变为 frago.*.md。
"""

import re
import shutil
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


# 系统级目录
SYSTEM_CLAUDE_DIR = Path.home() / ".claude"
SYSTEM_FRAGO_DIR = Path.home() / ".frago"
SYSTEM_COMMANDS_DIR = SYSTEM_CLAUDE_DIR / "commands"
SYSTEM_SKILLS_DIR = SYSTEM_CLAUDE_DIR / "skills"
SYSTEM_RECIPES_DIR = SYSTEM_FRAGO_DIR / "recipes"

# 开发环境命令模式
DEV_COMMANDS_PATTERN = "frago.dev.*.md"


@dataclass
class PublishResult:
    """发布结果"""
    success: bool = False
    commands_published: List[str] = field(default_factory=list)
    skills_published: List[str] = field(default_factory=list)
    recipes_published: List[str] = field(default_factory=list)
    commands_skipped: List[str] = field(default_factory=list)
    skills_skipped: List[str] = field(default_factory=list)
    recipes_skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def get_project_root() -> Optional[Path]:
    """
    获取 Frago 项目根目录

    通过查找 pyproject.toml 来定位项目根目录。

    Returns:
        项目根目录路径，未找到返回 None
    """
    current = Path.cwd()

    # 向上查找 pyproject.toml
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            # 确认是 Frago 项目
            pyproject = parent / "pyproject.toml"
            content = pyproject.read_text()
            if "frago" in content.lower():
                return parent
        if (parent / ".git").exists():
            # 到达 git 根目录，检查是否是 Frago 项目
            if (parent / "src" / "frago").exists():
                return parent

    return None


def get_target_name(source_name: str) -> str:
    """
    获取目标文件名（去掉 .dev 后缀）

    Args:
        source_name: 源文件名，如 frago.dev.recipe.md

    Returns:
        目标文件名，如 frago.recipe.md
    """
    return re.sub(r"^frago\.dev\.", "frago.", source_name)


def publish_commands(
    source_dir: Path,
    target_dir: Path = SYSTEM_COMMANDS_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    发布 commands 到系统目录

    将 frago.dev.*.md 发布为 frago.*.md，同时同步 frago/ 子目录。

    Args:
        source_dir: 源目录 (开发环境的 .claude/commands/)
        target_dir: 目标目录 (~/.claude/commands/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (published, skipped) 元组
    """
    published = []
    skipped = []

    if not source_dir.exists():
        return published, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 1. 发布 frago.dev.*.md 文件（重命名为 frago.*.md）
    for src_file in source_dir.glob(DEV_COMMANDS_PATTERN):
        if not src_file.is_file():
            continue

        target_name = get_target_name(src_file.name)
        target_file = target_dir / target_name

        if target_file.exists() and not force:
            # 比较修改时间
            if src_file.stat().st_mtime <= target_file.stat().st_mtime:
                skipped.append(f"{src_file.name} → {target_name}")
                continue

        if not dry_run:
            shutil.copy2(src_file, target_file)
        published.append(f"{src_file.name} → {target_name}")

    # 2. 同步 frago/ 子目录（包含规则、指南、脚本等）
    frago_subdir = source_dir / "frago"
    if frago_subdir.exists() and frago_subdir.is_dir():
        target_frago_subdir = target_dir / "frago"
        _pub, _skip = _sync_directory(
            frago_subdir, target_frago_subdir, "frago/", force, dry_run
        )
        published.extend(_pub)
        skipped.extend(_skip)

    return published, skipped


def _sync_directory(
    source_dir: Path,
    target_dir: Path,
    prefix: str,
    force: bool,
    dry_run: bool,
) -> tuple[List[str], List[str]]:
    """
    同步目录内容

    Args:
        source_dir: 源目录
        target_dir: 目标目录
        prefix: 显示前缀（用于日志）
        force: 是否强制覆盖
        dry_run: 仅预览不执行

    Returns:
        (published, skipped) 元组
    """
    published = []
    skipped = []

    if not source_dir.exists():
        return published, skipped

    # 遍历源目录中的所有文件
    for src_file in source_dir.rglob("*"):
        if not src_file.is_file():
            continue
        if "__pycache__" in str(src_file) or src_file.suffix == ".pyc":
            continue

        rel_path = src_file.relative_to(source_dir)
        target_file = target_dir / rel_path
        display_path = f"{prefix}{rel_path}"

        needs_update = force or not target_file.exists()

        if not needs_update:
            if src_file.stat().st_mtime > target_file.stat().st_mtime:
                needs_update = True

        if not needs_update:
            skipped.append(display_path)
            continue

        if not dry_run:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target_file)
        published.append(display_path)

    return published, skipped


def publish_skills(
    source_dir: Path,
    target_dir: Path = SYSTEM_SKILLS_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    发布 skills 到系统目录

    Args:
        source_dir: 源目录 (开发环境的 .claude/skills/)
        target_dir: 目标目录 (~/.claude/skills/)
        force: 是否强制覆盖
        dry_run: 仅预览不执行

    Returns:
        (published, skipped) 元组
    """
    published = []
    skipped = []

    if not source_dir.exists():
        return published, skipped

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
        published.append(skill_dir.name)

    return published, skipped


def publish_recipes(
    source_dir: Path,
    target_dir: Path = SYSTEM_RECIPES_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    发布 recipes 到系统目录

    Args:
        source_dir: 源目录 (开发环境的 examples/)
        target_dir: 目标目录 (~/.frago/recipes/)
        force: 是否强制覆盖
        dry_run: 仅预览不执行

    Returns:
        (published, skipped) 元组
    """
    published = []
    skipped = []

    if not source_dir.exists():
        return published, skipped

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

                    _pub, _skip = _publish_recipe_dir(
                        recipe_dir, target_recipe_dir, rel_path, force, dry_run
                    )
                    published.extend(_pub)
                    skipped.extend(_skip)
        else:
            for recipe_dir in category_dir.iterdir():
                if not recipe_dir.is_dir():
                    continue
                if not (recipe_dir / "recipe.md").exists():
                    continue

                rel_path = f"{category}/{recipe_dir.name}"
                target_recipe_dir = target_dir / category / recipe_dir.name

                _pub, _skip = _publish_recipe_dir(
                    recipe_dir, target_recipe_dir, rel_path, force, dry_run
                )
                published.extend(_pub)
                skipped.extend(_skip)

    return published, skipped


def _publish_recipe_dir(
    source_dir: Path,
    target_dir: Path,
    rel_path: str,
    force: bool,
    dry_run: bool,
) -> tuple[List[str], List[str]]:
    """发布单个 recipe 目录"""
    published = []
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
        published.append(rel_path)

    return published, skipped


def publish(
    project_root: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
    commands_only: bool = False,
    recipes_only: bool = False,
    skills_only: bool = False,
) -> PublishResult:
    """
    主发布函数

    从开发环境发布资源到系统目录。

    Args:
        project_root: 项目根目录，默认自动检测
        force: 强制覆盖所有文件
        dry_run: 仅预览不执行
        commands_only: 仅发布 commands
        recipes_only: 仅发布 recipes
        skills_only: 仅发布 skills

    Returns:
        PublishResult 包含发布结果
    """
    result = PublishResult()

    try:
        if project_root is None:
            project_root = get_project_root()

        if project_root is None:
            result.errors.append("未找到 Frago 项目根目录，请在 Frago 项目目录下运行此命令")
            return result

        # 确定发布范围
        do_commands = not (recipes_only or skills_only)
        do_skills = not (commands_only or recipes_only)
        do_recipes = not (commands_only or skills_only)

        # 发布 commands
        if do_commands:
            source_commands = project_root / ".claude" / "commands"
            published, skipped = publish_commands(source_commands, force=force, dry_run=dry_run)
            result.commands_published = published
            result.commands_skipped = skipped

        # 发布 skills
        if do_skills:
            source_skills = project_root / ".claude" / "skills"
            published, skipped = publish_skills(source_skills, force=force, dry_run=dry_run)
            result.skills_published = published
            result.skills_skipped = skipped

        # 发布 recipes
        if do_recipes:
            source_recipes = project_root / "examples"
            published, skipped = publish_recipes(source_recipes, force=force, dry_run=dry_run)
            result.recipes_published = published
            result.recipes_skipped = skipped

        result.success = True

    except PermissionError as e:
        result.errors.append(f"权限错误: {e}")
    except Exception as e:
        result.errors.append(f"发布失败: {e}")

    return result
