"""
Dev-Load 模块 - 从系统目录加载 frago 资源到当前项目目录

从 ~/.claude 和 ~/.frago/recipes 加载 frago 相关内容，
安装到当前项目的 .claude/ 和 examples/ 目录。

这是开发者工具，用于在 Frago 开发环境中初始化项目资源。
"""

import shutil
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field


# 系统级目录
SYSTEM_CLAUDE_DIR = Path.home() / ".claude"
SYSTEM_FRAGO_DIR = Path.home() / ".frago"
SYSTEM_COMMANDS_DIR = SYSTEM_CLAUDE_DIR / "commands"
SYSTEM_SKILLS_DIR = SYSTEM_CLAUDE_DIR / "skills"
SYSTEM_RECIPES_DIR = SYSTEM_FRAGO_DIR / "recipes"

# 同步配置：仅同步 frago 相关资源
COMMANDS_PATTERN = "frago.*.md"
SKILLS_PREFIX = "frago-"


@dataclass
class LoadResult:
    """加载结果"""
    success: bool = False
    commands_loaded: List[str] = field(default_factory=list)
    skills_loaded: List[str] = field(default_factory=list)
    recipes_loaded: List[str] = field(default_factory=list)
    commands_skipped: List[str] = field(default_factory=list)
    skills_skipped: List[str] = field(default_factory=list)
    recipes_skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def load_commands(
    project_dir: Path,
    source_dir: Path = SYSTEM_COMMANDS_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    从系统目录加载 commands 到项目目录

    加载 ~/.claude/commands/frago.*.md 和 ~/.claude/commands/frago/ 目录
    到项目的 .claude/commands/

    Args:
        project_dir: 项目根目录
        source_dir: 源目录 (~/.claude/commands/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (loaded, skipped) 元组
    """
    loaded = []
    skipped = []

    if not source_dir.exists():
        return loaded, skipped

    target_dir = project_dir / ".claude" / "commands"
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 加载 frago.*.md 文件
    for src_file in source_dir.glob(COMMANDS_PATTERN):
        if not src_file.is_file():
            continue

        target_file = target_dir / src_file.name

        if target_file.exists() and not force:
            if src_file.stat().st_mtime <= target_file.stat().st_mtime:
                skipped.append(src_file.name)
                continue

        if not dry_run:
            shutil.copy2(src_file, target_file)
        loaded.append(src_file.name)

    # 加载 frago/ 子目录
    frago_source = source_dir / "frago"
    frago_target = target_dir / "frago"

    if frago_source.exists() and frago_source.is_dir():
        needs_update = force or not frago_target.exists()

        if not needs_update:
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
            loaded.append("frago/ (规则和指南)")
        else:
            skipped.append("frago/ (规则和指南)")

    return loaded, skipped


def load_skills(
    project_dir: Path,
    source_dir: Path = SYSTEM_SKILLS_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    从系统目录加载 skills 到项目目录

    仅加载 frago-* 前缀的 skills。

    Args:
        project_dir: 项目根目录
        source_dir: 源目录 (~/.claude/skills/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (loaded, skipped) 元组
    """
    loaded = []
    skipped = []

    if not source_dir.exists():
        return loaded, skipped

    target_dir = project_dir / ".claude" / "skills"
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in source_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith('.'):
            continue
        # 仅加载 frago-* 前缀的 skills
        if not skill_dir.name.startswith(SKILLS_PREFIX):
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
        loaded.append(skill_dir.name)

    return loaded, skipped


def load_recipes(
    project_dir: Path,
    source_dir: Path = SYSTEM_RECIPES_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    从系统目录加载 recipes 到项目目录

    Args:
        project_dir: 项目根目录
        source_dir: 源目录 (~/.frago/recipes/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (loaded, skipped) 元组
    """
    loaded = []
    skipped = []

    if not source_dir.exists():
        return loaded, skipped

    target_dir = project_dir / "examples"
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

                    _loaded, _skipped = _load_recipe_dir(
                        recipe_dir, target_recipe_dir, rel_path, force, dry_run
                    )
                    loaded.extend(_loaded)
                    skipped.extend(_skipped)
        else:
            for recipe_dir in category_dir.iterdir():
                if not recipe_dir.is_dir():
                    continue
                if not (recipe_dir / "recipe.md").exists():
                    continue

                rel_path = f"{category}/{recipe_dir.name}"
                target_recipe_dir = target_dir / category / recipe_dir.name

                _loaded, _skipped = _load_recipe_dir(
                    recipe_dir, target_recipe_dir, rel_path, force, dry_run
                )
                loaded.extend(_loaded)
                skipped.extend(_skipped)

    return loaded, skipped


def _load_recipe_dir(
    source_dir: Path,
    target_dir: Path,
    rel_path: str,
    force: bool,
    dry_run: bool,
) -> tuple[List[str], List[str]]:
    """加载单个 recipe 目录"""
    loaded = []
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
        loaded.append(rel_path)

    return loaded, skipped


def load(
    project_dir: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
    commands_only: bool = False,
    skills_only: bool = False,
    recipes_only: bool = False,
) -> LoadResult:
    """
    主加载函数

    从系统目录加载 frago 资源到项目目录。

    Args:
        project_dir: 项目目录，默认为当前目录
        force: 强制覆盖所有文件
        dry_run: 仅预览不执行
        commands_only: 仅加载 commands
        skills_only: 仅加载 skills
        recipes_only: 仅加载 recipes

    Returns:
        LoadResult 包含加载结果
    """
    result = LoadResult()

    if project_dir is None:
        project_dir = Path.cwd()

    try:
        # 确定加载范围
        do_commands = not (skills_only or recipes_only)
        do_skills = not (commands_only or recipes_only)
        do_recipes = not (commands_only or skills_only)

        # 加载 commands
        if do_commands:
            loaded, skipped = load_commands(project_dir, force=force, dry_run=dry_run)
            result.commands_loaded = loaded
            result.commands_skipped = skipped

        # 加载 skills
        if do_skills:
            loaded, skipped = load_skills(project_dir, force=force, dry_run=dry_run)
            result.skills_loaded = loaded
            result.skills_skipped = skipped

        # 加载 recipes
        if do_recipes:
            loaded, skipped = load_recipes(project_dir, force=force, dry_run=dry_run)
            result.recipes_loaded = loaded
            result.recipes_skipped = skipped

        result.success = True

    except PermissionError as e:
        result.errors.append(f"权限错误: {e}")
    except Exception as e:
        result.errors.append(f"加载失败: {e}")

    return result
