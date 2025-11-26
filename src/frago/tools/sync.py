"""
同步 examples/ 目录的 Recipe 到 src/frago/resources/recipes/

提供将示例 Recipe 同步到 Python 包资源目录的功能，
使得打包分发时能够包含最新的示例。
"""

import fnmatch
import shutil
from pathlib import Path
from typing import Optional


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
            source_dir: 源目录（examples/），默认自动检测
            target_dir: 目标目录（src/frago/resources/recipes/），默认自动检测
        """
        # 自动检测项目根目录
        current_file = Path(__file__).resolve()
        # src/frago/tools/sync.py -> project_root
        project_root = current_file.parent.parent.parent.parent

        self.source_dir = source_dir or (project_root / "examples")
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
