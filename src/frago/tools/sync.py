"""
Pack 模块 - 同步用户目录资源到打包目录

同步 ~/.frago/recipes/ 目录的 Recipe 到 src/frago/resources/recipes/
同步 ~/.claude/commands/ 目录的命令到 src/frago/resources/commands/
同步 ~/.claude/skills/ 目录的 Skill 到 src/frago/resources/skills/

提供将用户目录的 Recipe 和 Claude Code 命令同步到 Python 包资源目录的功能，
使得打包分发时能够包含最新的内容。

注意: 这是用于 PyPI 打包的内部功能。
开发者直接在 ~/.claude/ 和 ~/.frago/ 编辑资源，然后用 dev pack 同步到包内。
"""

import fnmatch
import shutil
from pathlib import Path
from typing import Optional


class CommandSync:
    """Claude Code 命令同步器"""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ):
        """
        初始化同步器

        Args:
            source_dir: 源目录（~/.claude/commands/），默认用户目录
            target_dir: 目标目录（src/frago/resources/commands/），默认自动检测
        """
        # 自动检测项目根目录（用于 target_dir）
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        # 源目录改为用户目录
        self.source_dir = source_dir or (Path.home() / ".claude" / "commands")
        self.target_dir = target_dir or (
            project_root / "src" / "frago" / "resources" / "commands"
        )

    def find_commands(self, pattern: Optional[str] = None) -> list[Path]:
        """
        查找所有 frago.*.md 命令文件

        Args:
            pattern: 可选的通配符模式，用于过滤命令名称

        Returns:
            命令文件路径列表
        """
        commands = []

        if not self.source_dir.exists():
            return commands

        # 查找 frago.*.md 文件（用户目录使用正式命名）
        for cmd_file in self.source_dir.glob("frago.*.md"):
            if not cmd_file.is_file():
                continue

            cmd_name = cmd_file.name

            # 如果指定了 pattern，进行匹配
            if pattern:
                if not fnmatch.fnmatch(cmd_name, pattern):
                    continue

            commands.append(cmd_file)

        return commands

    def get_target_name(self, source_name: str) -> str:
        """
        获取目标文件名（直接使用源文件名）

        Args:
            source_name: 源文件名，如 frago.recipe.md

        Returns:
            目标文件名，与源文件名相同
        """
        # 用户目录已使用正式命名，无需转换
        return source_name

    def sync(
        self,
        pattern: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """
        执行同步操作

        Args:
            pattern: 可选的通配符模式，用于过滤命令名称
            dry_run: 如果为 True，仅显示将要执行的操作，不实际执行
            verbose: 显示详细信息

        Returns:
            同步结果列表，每个元素包含 source_name, target_name, source_file, target_file, action
        """
        results = []
        cmd_files = self.find_commands(pattern)

        if not cmd_files:
            return results

        for src_file in cmd_files:
            source_name = src_file.name
            target_name = self.get_target_name(source_name)
            target_file = self.target_dir / target_name

            # 确定操作类型
            if target_file.exists():
                # 检查是否需要更新（比较修改时间）
                if src_file.stat().st_mtime > target_file.stat().st_mtime:
                    action = "update"
                else:
                    action = "skip"
            else:
                action = "create"

            result = {
                "source_name": source_name,
                "target_name": target_name,
                "source_file": src_file,
                "target_file": target_file,
                "action": action,
            }

            if action == "skip":
                results.append(result)
                continue

            if not dry_run:
                # 确保目标目录存在
                self.target_dir.mkdir(parents=True, exist_ok=True)
                # 复制文件
                shutil.copy2(src_file, target_file)

            results.append(result)

        return results

    def list_synced(self) -> list[Path]:
        """列出已同步到 resources 的命令文件"""
        synced = []

        if not self.target_dir.exists():
            return synced

        for cmd_file in self.target_dir.glob("frago.*.md"):
            if cmd_file.is_file():
                synced.append(cmd_file)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        清理目标目录中不存在于源目录的命令文件

        Args:
            dry_run: 如果为 True，仅显示将要删除的文件，不实际执行

        Returns:
            被删除（或将要删除）的文件列表
        """
        removed = []

        for target_file in self.list_synced():
            target_name = target_file.name
            # 源文件名与目标文件名相同
            source_file = self.source_dir / target_name

            if not source_file.exists():
                if not dry_run:
                    target_file.unlink()
                removed.append(target_file)

        return removed


class RecipeSync:
    """Recipe 同步器"""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ):
        """
        初始化同步器

        Args:
            source_dir: 源目录（~/.frago/recipes/），默认用户目录
            target_dir: 目标目录（src/frago/resources/recipes/），默认自动检测
        """
        # 自动检测项目根目录（用于 target_dir）
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        # 源目录改为用户目录
        self.source_dir = source_dir or (Path.home() / ".frago" / "recipes")
        self.target_dir = target_dir or (
            project_root / "src" / "frago" / "resources" / "recipes"
        )

    def find_recipes(self, pattern: Optional[str] = None) -> list[Path]:
        """
        查找所有 Recipe 目录

        Args:
            pattern: 可选的通配符模式，用于过滤 Recipe 名称

        Returns:
            配方目录路径列表
        """
        recipes = []

        # 遍历 examples/ 下的子目录 (atomic/chrome, atomic/system, workflows)
        for subdir in ["atomic/chrome", "atomic/system", "workflows"]:
            category_path = self.source_dir / subdir
            if not category_path.exists():
                continue

            # 查找所有配方目录（包含 recipe.md 的目录）
            for recipe_dir in category_path.iterdir():
                if not recipe_dir.is_dir():
                    continue
                # 跳过 __pycache__ 目录
                if recipe_dir.name == "__pycache__":
                    continue

                # 检查是否包含 recipe.md
                metadata_path = recipe_dir / "recipe.md"
                if not metadata_path.exists():
                    continue

                # 获取 Recipe 名称（目录名）
                recipe_name = recipe_dir.name

                # 如果指定了 pattern，进行匹配
                if pattern:
                    if not fnmatch.fnmatch(recipe_name, pattern):
                        continue

                recipes.append(recipe_dir)

        return recipes

    def sync(
        self,
        pattern: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """
        执行同步操作（目录形式配方）

        Args:
            pattern: 可选的通配符模式，用于过滤 Recipe 名称
            dry_run: 如果为 True，仅显示将要执行的操作，不实际执行
            verbose: 显示详细信息

        Returns:
            同步结果列表，每个元素包含 recipe_name, source_dir, target_dir, action
        """
        results = []
        recipe_dirs = self.find_recipes(pattern)

        if not recipe_dirs:
            return results

        for recipe_dir in recipe_dirs:
            # 计算相对路径
            rel_path = recipe_dir.relative_to(self.source_dir)
            recipe_name = recipe_dir.name

            # 目标路径
            target_dir = self.target_dir / rel_path

            # 确定操作类型
            if target_dir.exists():
                # 检查是否需要更新（比较目录内所有文件的修改时间）
                needs_update = False
                for src_file in recipe_dir.rglob("*"):
                    if src_file.is_file() and "__pycache__" not in str(src_file):
                        rel_file = src_file.relative_to(recipe_dir)
                        tgt_file = target_dir / rel_file
                        if not tgt_file.exists():
                            needs_update = True
                            break
                        if src_file.stat().st_mtime > tgt_file.stat().st_mtime:
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
                results.append(result)
                continue

            if not dry_run:
                # 删除旧目录（如果存在）
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                # 复制整个目录（排除 __pycache__）
                shutil.copytree(
                    recipe_dir,
                    target_dir,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )

            results.append(result)

        return results

    def list_synced(self) -> list[Path]:
        """列出已同步到 resources 的 Recipe 目录"""
        synced = []

        # 遍历 target_dir 下的子目录
        for subdir in ["atomic/chrome", "atomic/system", "workflows"]:
            category_path = self.target_dir / subdir
            if not category_path.exists():
                continue

            for recipe_dir in category_path.iterdir():
                if recipe_dir.is_dir() and (recipe_dir / "recipe.md").exists():
                    synced.append(recipe_dir)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        清理目标目录中不存在于源目录的 Recipe

        Args:
            dry_run: 如果为 True，仅显示将要删除的目录，不实际执行

        Returns:
            被删除（或将要删除）的目录列表
        """
        removed = []

        for target_dir in self.list_synced():
            # 计算对应的源路径
            rel_path = target_dir.relative_to(self.target_dir)
            source_dir = self.source_dir / rel_path

            if not source_dir.exists():
                if not dry_run:
                    shutil.rmtree(target_dir)
                removed.append(target_dir)

        return removed


class SkillSync:
    """Skill 同步器"""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ):
        """
        初始化同步器

        Args:
            source_dir: 源目录（~/.claude/skills/），默认用户目录
            target_dir: 目标目录（src/frago/resources/skills/），默认自动检测
        """
        # 自动检测项目根目录（用于 target_dir）
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        # 源目录改为用户目录
        self.source_dir = source_dir or (Path.home() / ".claude" / "skills")
        self.target_dir = target_dir or (
            project_root / "src" / "frago" / "resources" / "skills"
        )

    def find_skills(self, pattern: Optional[str] = None) -> list[Path]:
        """
        查找所有 Skill 目录（以 frago- 开头）

        Args:
            pattern: 可选的通配符模式，用于过滤 Skill 名称

        Returns:
            Skill 目录路径列表
        """
        skills = []

        if not self.source_dir.exists():
            return skills

        for skill_dir in self.source_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            # 跳过 __pycache__ 目录
            if skill_dir.name == "__pycache__":
                continue
            # 只同步以 frago- 开头的 skill
            if not skill_dir.name.startswith("frago-"):
                continue

            # 检查是否包含 SKILL.md
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill_name = skill_dir.name

            # 如果指定了 pattern，进行匹配
            if pattern:
                if not fnmatch.fnmatch(skill_name, pattern):
                    continue

            skills.append(skill_dir)

        return skills

    def list_synced(self) -> list[Path]:
        """列出已同步到 resources 的 Skill 目录"""
        synced = []

        if not self.target_dir.exists():
            return synced

        for skill_dir in self.target_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                synced.append(skill_dir)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        清理目标目录中不存在于源目录的 Skill

        Args:
            dry_run: 如果为 True，仅显示将要删除的目录，不实际执行

        Returns:
            被删除（或将要删除）的目录列表
        """
        removed = []

        for target_dir in self.list_synced():
            skill_name = target_dir.name
            source_dir = self.source_dir / skill_name

            if not source_dir.exists():
                if not dry_run:
                    shutil.rmtree(target_dir)
                removed.append(target_dir)

        return removed
