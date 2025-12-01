"""
Deploy 模块 - 从远程仓库部署资源到系统目录

从用户配置的私有仓库拉取 .claude 和 examples 内容，
部署到 ~/.claude 和 ~/.frago/recipes。
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

# 本地仓库缓存目录（与 sync 共享）
SYNC_REPO_CACHE_DIR = SYSTEM_FRAGO_DIR / "sync-repo"

# 同步配置：仓库中存储开发环境格式 frago.dev.*.md
# 部署时去掉 .dev 后缀变为 frago.*.md
DEV_COMMANDS_PATTERN = "frago.dev.*.md"
RUNTIME_COMMANDS_PATTERN = "frago.*.md"
SKILLS_PREFIX = "frago-"


@dataclass
class DeployResult:
    """部署结果"""
    success: bool = False
    commands_installed: List[str] = field(default_factory=list)
    skills_installed: List[str] = field(default_factory=list)
    recipes_installed: List[str] = field(default_factory=list)
    commands_skipped: List[str] = field(default_factory=list)
    skills_skipped: List[str] = field(default_factory=list)
    recipes_skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def ensure_local_repo(repo_url: str, branch: str = DEFAULT_BRANCH) -> Path:
    """
    确保本地仓库缓存存在并更新到最新

    如果缓存目录不存在则克隆，存在则拉取最新。
    使用 ~/.frago/sync-repo 作为缓存目录，与 sync 命令共享。

    Args:
        repo_url: 仓库 URL
        branch: 分支名

    Returns:
        本地仓库路径

    Raises:
        subprocess.CalledProcessError: git 命令执行失败
    """
    if SYNC_REPO_CACHE_DIR.exists() and (SYNC_REPO_CACHE_DIR / ".git").exists():
        # 已存在，拉取最新
        cmd = ["git", "-C", str(SYNC_REPO_CACHE_DIR), "pull", "--rebase"]
        subprocess.run(cmd, capture_output=True, text=True)
        return SYNC_REPO_CACHE_DIR

    # 克隆新仓库
    SYNC_REPO_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git", "clone", "--branch", branch, repo_url, str(SYNC_REPO_CACHE_DIR)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    return SYNC_REPO_CACHE_DIR


def get_runtime_name(dev_name: str) -> str:
    """
    将开发环境文件名转换为运行时文件名

    frago.dev.recipe.md → frago.recipe.md
    """
    return re.sub(r"^frago\.dev\.", "frago.", dev_name)


def deploy_commands(
    source_dir: Path,
    target_dir: Path = SYSTEM_COMMANDS_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    部署 commands 到系统目录

    仓库中存储 frago.dev.*.md 格式，部署时去掉 .dev 后缀。
    同时同步 frago/ 子目录（规则和指南）。
    避免覆盖用户自有命令。

    Args:
        source_dir: 源目录 (仓库中的 .claude/commands/)
        target_dir: 目标目录 (~/.claude/commands/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (installed, skipped) 元组
    """
    installed = []
    skipped = []

    if not source_dir.exists():
        return installed, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 同步 frago.dev.*.md 文件
    for src_file in source_dir.glob(DEV_COMMANDS_PATTERN):
        if not src_file.is_file():
            continue

        # 仓库中 frago.dev.*.md → 系统目录 frago.*.md
        runtime_name = get_runtime_name(src_file.name)
        target_file = target_dir / runtime_name

        if target_file.exists() and not force:
            # 比较修改时间，仅更新更新的文件
            if src_file.stat().st_mtime <= target_file.stat().st_mtime:
                skipped.append(f"{src_file.name} → {runtime_name}")
                continue

        if not dry_run:
            shutil.copy2(src_file, target_file)
        installed.append(f"{src_file.name} → {runtime_name}")

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
            installed.append("frago/ (规则和指南)")
        else:
            skipped.append("frago/ (规则和指南)")

    return installed, skipped


def deploy_skills(
    source_dir: Path,
    target_dir: Path = SYSTEM_SKILLS_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    部署 skills 到系统目录

    仅部署 frago-* 前缀的 skills。

    Args:
        source_dir: 源目录 (仓库中的 .claude/skills/)
        target_dir: 目标目录 (~/.claude/skills/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (installed, skipped) 元组
    """
    installed = []
    skipped = []

    if not source_dir.exists():
        return installed, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 遍历每个 skill 目录，仅处理 frago-* 前缀
    for skill_dir in source_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith('.'):
            continue
        # 仅部署 frago-* 前缀的 skills
        if not skill_dir.name.startswith(SKILLS_PREFIX):
            continue

        target_skill_dir = target_dir / skill_dir.name

        # 检查是否需要更新
        needs_update = force or not target_skill_dir.exists()

        if not needs_update:
            # 检查源目录中的文件是否有更新
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
            # 删除旧目录并复制新的
            if target_skill_dir.exists():
                shutil.rmtree(target_skill_dir)
            shutil.copytree(
                skill_dir,
                target_skill_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        installed.append(skill_dir.name)

    return installed, skipped


def deploy_recipes(
    source_dir: Path,
    target_dir: Path = SYSTEM_RECIPES_DIR,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[List[str], List[str]]:
    """
    部署 recipes 到系统目录

    Args:
        source_dir: 源目录 (仓库中的 examples/)
        target_dir: 目标目录 (~/.frago/recipes/)
        force: 是否强制覆盖已存在文件
        dry_run: 仅预览不执行

    Returns:
        (installed, skipped) 元组
    """
    installed = []
    skipped = []

    if not source_dir.exists():
        return installed, skipped

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    # 遍历 atomic/ 和 workflows/ 子目录
    for category in ["atomic", "workflows"]:
        category_dir = source_dir / category
        if not category_dir.exists():
            continue

        # 对于 atomic，再遍历 chrome/ 和 system/
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

                    _install_or_skip, _skipped = _deploy_recipe_dir(
                        recipe_dir, target_recipe_dir, rel_path, force, dry_run
                    )
                    installed.extend(_install_or_skip)
                    skipped.extend(_skipped)
        else:
            # workflows 直接遍历
            for recipe_dir in category_dir.iterdir():
                if not recipe_dir.is_dir():
                    continue
                if not (recipe_dir / "recipe.md").exists():
                    continue

                rel_path = f"{category}/{recipe_dir.name}"
                target_recipe_dir = target_dir / category / recipe_dir.name

                _install_or_skip, _skipped = _deploy_recipe_dir(
                    recipe_dir, target_recipe_dir, rel_path, force, dry_run
                )
                installed.extend(_install_or_skip)
                skipped.extend(_skipped)

    return installed, skipped


def _deploy_recipe_dir(
    source_dir: Path,
    target_dir: Path,
    rel_path: str,
    force: bool,
    dry_run: bool,
) -> tuple[List[str], List[str]]:
    """部署单个 recipe 目录"""
    installed = []
    skipped = []

    needs_update = force or not target_dir.exists()

    if not needs_update:
        # 检查是否有更新的文件
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
        installed.append(rel_path)

    return installed, skipped


def deploy(
    repo_url: Optional[str] = None,
    branch: str = DEFAULT_BRANCH,
    force: bool = False,
    dry_run: bool = False,
    local_repo: Optional[Path] = None,
) -> DeployResult:
    """
    主部署函数

    从远程仓库拉取资源并部署到系统目录。
    使用 ~/.frago/sync-repo 作为本地缓存，与 sync 命令共享。

    Args:
        repo_url: 仓库 URL
        branch: 分支名
        force: 强制覆盖所有文件
        dry_run: 仅预览不执行
        local_repo: 使用本地仓库而非缓存（用于开发测试）

    Returns:
        DeployResult 包含部署结果
    """
    result = DeployResult()

    try:
        # 获取仓库内容
        if local_repo:
            repo_dir = local_repo
        else:
            if not repo_url:
                result.errors.append("未配置仓库 URL，请使用 frago sync --set-repo 配置")
                return result
            repo_dir = ensure_local_repo(repo_url, branch)

        # 部署 commands
        source_commands = repo_dir / ".claude" / "commands"
        installed, skipped = deploy_commands(source_commands, force=force, dry_run=dry_run)
        result.commands_installed = installed
        result.commands_skipped = skipped

        # 部署 skills
        source_skills = repo_dir / ".claude" / "skills"
        installed, skipped = deploy_skills(source_skills, force=force, dry_run=dry_run)
        result.skills_installed = installed
        result.skills_skipped = skipped

        # 部署 recipes
        source_recipes = repo_dir / "examples"
        installed, skipped = deploy_recipes(source_recipes, force=force, dry_run=dry_run)
        result.recipes_installed = installed
        result.recipes_skipped = skipped

        result.success = True

    except subprocess.CalledProcessError as e:
        result.errors.append(f"Git 操作失败: {e.stderr}")
    except PermissionError as e:
        result.errors.append(f"权限错误: {e}")
    except Exception as e:
        result.errors.append(f"部署失败: {e}")

    return result
