"""
资源安装模块

提供 frago init 命令所需的资源安装功能：
- 安装 Claude Code slash 命令到 ~/.claude/commands/
- 安装示例 recipe 到 ~/.frago/recipes/
"""

import shutil
from pathlib import Path
from typing import Optional

from frago.init.models import InstallResult, ResourceStatus, ResourceType


# 资源安装目标路径
INSTALL_TARGETS = {
    "commands": Path.home() / ".claude" / "commands",
    "skills": Path.home() / ".claude" / "skills",
    "recipes": Path.home() / ".frago" / "recipes",
}


def get_package_resources_path(resource_type: str) -> Path:
    """
    获取包内资源目录路径

    Args:
        resource_type: 资源类型 ("commands", "skills", "recipes")

    Returns:
        资源目录的 Path 对象

    Raises:
        ValueError: 无效的资源类型
        FileNotFoundError: 资源目录不存在
    """
    valid_types = ("commands", "skills", "recipes")
    if resource_type not in valid_types:
        raise ValueError(f"无效的资源类型: {resource_type}, 有效值: {valid_types}")

    # 使用 importlib.resources 获取包内资源路径
    try:
        from importlib.resources import files
        package_files = files("frago.resources")
        resource_path = package_files.joinpath(resource_type)
        # 转换为 Path（兼容开发环境和已安装环境）
        return Path(str(resource_path))
    except (ImportError, FileNotFoundError, AttributeError):
        # 降级：开发环境使用相对路径
        import frago.resources
        base_path = Path(frago.resources.__file__).parent
        resource_path = base_path / resource_type
        if not resource_path.exists():
            raise FileNotFoundError(f"资源目录不存在: {resource_path}")
        return resource_path


def get_target_path(resource_type: str) -> Path:
    """
    获取资源安装目标目录

    Args:
        resource_type: 资源类型 ("commands", "skills", "recipes")

    Returns:
        目标目录的 Path 对象

    Raises:
        ValueError: 无效的资源类型
    """
    if resource_type not in INSTALL_TARGETS:
        raise ValueError(f"无效的资源类型: {resource_type}")
    return INSTALL_TARGETS[resource_type]


def install_commands(source_dir: Optional[Path] = None, target_dir: Optional[Path] = None) -> InstallResult:
    """
    安装 Claude Code slash 命令（始终覆盖）

    Args:
        source_dir: 源目录，默认从包内资源获取
        target_dir: 目标目录，默认为 ~/.claude/commands/

    Returns:
        InstallResult 包含安装结果
    """
    result = InstallResult(resource_type=ResourceType.COMMAND)

    try:
        if source_dir is None:
            source_dir = get_package_resources_path("commands")
        if target_dir is None:
            target_dir = get_target_path("commands")

        # 检查源目录是否存在且有内容
        if not source_dir.exists():
            result.errors.append(f"源资源目录不存在: {source_dir}")
            return result

        command_files = list(source_dir.glob("frago.*.md"))
        if not command_files:
            result.errors.append(f"源资源目录为空或损坏: {source_dir} 中没有 frago.*.md 文件")
            return result

        # 确保目标目录存在
        target_dir.mkdir(parents=True, exist_ok=True)

        # 复制所有 frago.*.md 文件（始终覆盖）
        for src_file in command_files:
            target_file = target_dir / src_file.name
            shutil.copy2(src_file, target_file)
            result.installed.append(src_file.name)

        # 复制 frago/ 子目录（如果存在）
        frago_subdir = source_dir / "frago"
        if frago_subdir.exists() and frago_subdir.is_dir():
            target_frago_dir = target_dir / "frago"
            if target_frago_dir.exists():
                shutil.rmtree(target_frago_dir)
            shutil.copytree(
                frago_subdir,
                target_frago_dir,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            result.installed.append("frago/ (子目录)")

    except FileNotFoundError as e:
        result.errors.append(f"资源目录不存在: {e}")
    except PermissionError as e:
        result.errors.append(f"权限错误: 无法写入 {target_dir}, 请检查目录权限")
    except Exception as e:
        result.errors.append(f"安装命令时出错: {e}")

    return result


def install_skills(
    source_dir: Optional[Path] = None,
    target_dir: Optional[Path] = None,
    force_update: bool = False,
) -> InstallResult:
    """
    安装 Claude Code skills（默认仅首次安装，不覆盖已存在目录）

    Args:
        source_dir: 源目录，默认从包内资源获取
        target_dir: 目标目录，默认为 ~/.claude/skills/
        force_update: 是否强制更新（覆盖已存在目录）

    Returns:
        InstallResult 包含安装、跳过的 skill 列表
    """
    result = InstallResult(resource_type=ResourceType.SKILL)

    try:
        if source_dir is None:
            source_dir = get_package_resources_path("skills")
        if target_dir is None:
            target_dir = get_target_path("skills")

        # 检查源目录是否存在
        if not source_dir.exists():
            result.errors.append(f"源资源目录不存在: {source_dir}")
            return result

        # 查找所有 skill 目录（包含 SKILL.md 的目录）
        skill_dirs = []
        for skill_dir in source_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skill_dirs.append(skill_dir)

        if not skill_dirs:
            result.errors.append(f"源资源目录为空或损坏: {source_dir} 中没有有效的 skill")
            return result

        # 确保目标目录存在
        target_dir.mkdir(parents=True, exist_ok=True)

        # 复制 skill 目录
        for src_skill_dir in skill_dirs:
            skill_name = src_skill_dir.name
            target_skill_dir = target_dir / skill_name

            if target_skill_dir.exists() and not force_update:
                # 目录已存在且非强制更新模式，跳过
                result.skipped.append(skill_name)
            elif target_skill_dir.exists() and force_update:
                # 强制更新模式，先删除再复制
                shutil.rmtree(target_skill_dir)
                shutil.copytree(
                    src_skill_dir,
                    target_skill_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                result.installed.append(skill_name)
            else:
                # 新目录，直接复制
                shutil.copytree(
                    src_skill_dir,
                    target_skill_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                result.installed.append(skill_name)

    except FileNotFoundError as e:
        result.errors.append(f"资源目录不存在: {e}")
    except PermissionError as e:
        result.errors.append(f"权限错误: 无法写入 {target_dir}, 请检查目录权限")
    except Exception as e:
        result.errors.append(f"安装 skill 时出错: {e}")

    return result


def install_recipes(
    source_dir: Optional[Path] = None,
    target_dir: Optional[Path] = None,
    force_update: bool = False,
) -> InstallResult:
    """
    安装示例 recipe（默认仅首次安装，不覆盖已存在文件）

    Args:
        source_dir: 源目录，默认从包内资源获取
        target_dir: 目标目录，默认为 ~/.frago/recipes/
        force_update: 是否强制更新（覆盖已存在文件，会先备份）

    Returns:
        InstallResult 包含安装、跳过和备份的文件列表
    """
    result = InstallResult(resource_type=ResourceType.RECIPE)

    try:
        if source_dir is None:
            source_dir = get_package_resources_path("recipes")
        if target_dir is None:
            target_dir = get_target_path("recipes")

        # 检查源目录是否存在
        if not source_dir.exists():
            result.errors.append(f"源资源目录不存在: {source_dir}")
            return result

        # 检查源目录是否有内容
        recipe_files = list(source_dir.rglob("*"))
        if not any(f.is_file() for f in recipe_files):
            result.errors.append(f"源资源目录为空或损坏: {source_dir} 中没有文件")
            return result

        # 确保目标目录存在
        target_dir.mkdir(parents=True, exist_ok=True)

        # 遍历源目录中的所有文件
        for src_file in source_dir.rglob("*"):
            if src_file.is_file():
                # 计算相对路径
                rel_path = src_file.relative_to(source_dir)
                target_file = target_dir / rel_path

                if target_file.exists() and not force_update:
                    # 文件已存在且非强制更新模式，跳过
                    result.skipped.append(str(rel_path))
                elif target_file.exists() and force_update:
                    # 强制更新模式，先备份再覆盖
                    backup_file = target_file.with_suffix(target_file.suffix + ".bak")
                    shutil.copy2(target_file, backup_file)
                    result.backed_up.append(str(rel_path))
                    shutil.copy2(src_file, target_file)
                    result.installed.append(str(rel_path))
                else:
                    # 新文件，直接安装
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, target_file)
                    result.installed.append(str(rel_path))

    except FileNotFoundError as e:
        result.errors.append(f"资源目录不存在: {e}")
    except PermissionError as e:
        result.errors.append(f"权限错误: 无法写入 {target_dir}, 请检查目录权限")
    except Exception as e:
        result.errors.append(f"安装 recipe 时出错: {e}")

    return result


def install_all_resources(skip_recipes: bool = False, force_update: bool = False) -> ResourceStatus:
    """
    安装所有资源（主入口）

    Args:
        skip_recipes: 是否跳过 recipe 安装
        force_update: 是否强制更新所有资源

    Returns:
        ResourceStatus 包含所有资源的安装状态
    """
    from datetime import datetime
    from frago import __version__

    status = ResourceStatus(
        frago_version=__version__,
        install_time=datetime.now(),
    )

    # 安装 slash 命令（始终覆盖）
    status.commands = install_commands()

    # 安装 skills
    status.skills = install_skills(force_update=force_update)

    # 安装示例 recipe（可选）
    if not skip_recipes:
        status.recipes = install_recipes(force_update=force_update)

    return status


def format_install_summary(status: ResourceStatus) -> str:
    """
    格式化安装摘要输出

    Args:
        status: 资源安装状态

    Returns:
        格式化的摘要字符串
    """
    lines = []

    # Commands 摘要
    if status.commands:
        cmd = status.commands
        if cmd.installed:
            lines.append("📦 安装 Claude Code 命令...")
            for name in cmd.installed:
                lines.append(f"  ✅ {name}")
        if cmd.errors:
            for error in cmd.errors:
                lines.append(f"  ❌ {error}")

    # Skills 摘要
    if status.skills:
        skill = status.skills
        if skill.installed or skill.skipped:
            lines.append("\n📦 安装 Claude Code Skills...")
            for name in skill.installed:
                lines.append(f"  ✅ {name}")
            for name in skill.skipped:
                lines.append(f"  ⏭️  {name} (已存在)")
        if skill.errors:
            for error in skill.errors:
                lines.append(f"  ❌ {error}")

    # Recipes 摘要
    if status.recipes:
        rec = status.recipes
        if rec.installed or rec.skipped or rec.backed_up:
            lines.append("\n📦 安装示例 Recipe...")
            for name in rec.installed:
                if name in rec.backed_up:
                    lines.append(f"  🔄 {name} (已更新，旧文件备份为 .bak)")
                else:
                    lines.append(f"  ✅ {name}")
            for name in rec.skipped:
                lines.append(f"  ⏭️  {name} (已存在)")
        if rec.errors:
            for error in rec.errors:
                lines.append(f"  ❌ {error}")

    # 总计
    total_installed = 0
    total_skipped = 0
    total_backed_up = 0
    if status.commands:
        total_installed += len(status.commands.installed)
    if status.skills:
        total_installed += len(status.skills.installed)
        total_skipped += len(status.skills.skipped)
    if status.recipes:
        total_installed += len(status.recipes.installed)
        total_skipped += len(status.recipes.skipped)
        total_backed_up += len(status.recipes.backed_up)

    if total_installed > 0 or total_skipped > 0:
        summary_parts = [f"{total_installed} 个文件安装"]
        if total_backed_up > 0:
            summary_parts.append(f"{total_backed_up} 个备份")
        if total_skipped > 0:
            summary_parts.append(f"{total_skipped} 个跳过")
        lines.append(f"\n✅ 资源安装完成 ({', '.join(summary_parts)})")

    return "\n".join(lines)


def count_installed_commands(target_dir: Optional[Path] = None) -> int:
    """
    统计已安装的 frago 命令数量

    Args:
        target_dir: 目标目录，默认为 ~/.claude/commands/

    Returns:
        已安装的 frago.*.md 文件数量
    """
    if target_dir is None:
        target_dir = get_target_path("commands")

    if not target_dir.exists():
        return 0

    return len(list(target_dir.glob("frago.*.md")))


def count_installed_recipes(target_dir: Optional[Path] = None) -> int:
    """
    统计已安装的 recipe 数量

    Args:
        target_dir: 目标目录，默认为 ~/.frago/recipes/

    Returns:
        已安装的 recipe 文件数量（.md 元数据文件）
    """
    if target_dir is None:
        target_dir = get_target_path("recipes")

    if not target_dir.exists():
        return 0

    # 统计 .md 文件作为 recipe 数量（每个 recipe 有一个 .md 元数据文件）
    return len(list(target_dir.rglob("*.md")))


def get_resources_status() -> dict:
    """
    获取已安装资源的状态信息

    Returns:
        包含资源状态的字典:
        {
            "commands": {"installed": int, "path": str, "files": list},
            "recipes": {"installed": int, "path": str},
            "frago_version": str,
        }
    """
    from frago import __version__

    commands_path = get_target_path("commands")
    recipes_path = get_target_path("recipes")

    # 获取已安装的命令文件列表
    command_files = []
    if commands_path.exists():
        command_files = [f.name for f in commands_path.glob("frago.*.md")]

    return {
        "commands": {
            "installed": len(command_files),
            "path": str(commands_path),
            "files": command_files,
        },
        "recipes": {
            "installed": count_installed_recipes(),
            "path": str(recipes_path),
        },
        "frago_version": __version__,
    }


def format_resources_status() -> str:
    """
    格式化资源状态输出（用于 --show-config）

    Returns:
        格式化的状态字符串
    """
    status = get_resources_status()
    lines = []

    lines.append("📦 已安装资源:")
    lines.append("")

    # Commands 状态
    cmd = status["commands"]
    lines.append(f"  Claude Code 命令: {cmd['installed']} 个")
    lines.append(f"  位置: {cmd['path']}")
    if cmd["files"]:
        for f in cmd["files"]:
            lines.append(f"    - {f}")
    lines.append("")

    # Recipes 状态
    rec = status["recipes"]
    lines.append(f"  示例 Recipe: {rec['installed']} 个")
    lines.append(f"  位置: {rec['path']}")
    lines.append("")

    lines.append(f"  Frago 版本: {status['frago_version']}")

    return "\n".join(lines)
