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

    def find_recipes(self, pattern: Optional[str] = None) -> list[tuple[Path, Path]]:
        """
        查找所有 Recipe 文件对（脚本 + 元数据）

        Args:
            pattern: 可选的通配符模式，用于过滤 Recipe 名称

        Returns:
            列表，每个元素是 (脚本路径, 元数据路径) 元组
        """
        recipes = []

        # 支持的脚本扩展名
        script_extensions = {".py", ".js", ".sh"}

        # 遍历 examples/ 目录
        for script_path in self.source_dir.rglob("*"):
            # 跳过目录和非脚本文件
            if script_path.is_dir():
                continue
            if script_path.suffix not in script_extensions:
                continue
            # 跳过 __pycache__ 目录
            if "__pycache__" in str(script_path):
                continue

            # 查找对应的元数据文件
            metadata_path = script_path.with_suffix(".md")
            if not metadata_path.exists():
                continue

            # 获取 Recipe 名称（不含扩展名）
            recipe_name = script_path.stem

            # 如果指定了 pattern，进行匹配
            if pattern:
                if not fnmatch.fnmatch(recipe_name, pattern):
                    continue

            recipes.append((script_path, metadata_path))

        return recipes

    def sync(
        self,
        pattern: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """
        执行同步操作

        Args:
            pattern: 可选的通配符模式，用于过滤 Recipe 名称
            dry_run: 如果为 True，仅显示将要执行的操作，不实际执行
            verbose: 显示详细信息

        Returns:
            同步结果列表，每个元素包含 recipe_name, source, target, action
        """
        results = []
        recipes = self.find_recipes(pattern)

        if not recipes:
            return results

        for script_path, metadata_path in recipes:
            # 计算相对路径
            rel_path = script_path.relative_to(self.source_dir)

            # 目标路径
            target_script = self.target_dir / rel_path
            target_metadata = target_script.with_suffix(".md")

            # 确定操作类型
            script_exists = target_script.exists()
            metadata_exists = target_metadata.exists()

            if script_exists and metadata_exists:
                # 检查是否需要更新
                script_modified = script_path.stat().st_mtime > target_script.stat().st_mtime
                metadata_modified = metadata_path.stat().st_mtime > target_metadata.stat().st_mtime
                if script_modified or metadata_modified:
                    action = "update"
                else:
                    action = "skip"
            else:
                action = "create"

            result = {
                "recipe_name": script_path.stem,
                "source_script": script_path,
                "source_metadata": metadata_path,
                "target_script": target_script,
                "target_metadata": target_metadata,
                "action": action,
            }

            if action == "skip":
                results.append(result)
                continue

            if not dry_run:
                # 创建目标目录
                target_script.parent.mkdir(parents=True, exist_ok=True)

                # 复制文件
                shutil.copy2(script_path, target_script)
                shutil.copy2(metadata_path, target_metadata)

            results.append(result)

        return results

    def list_synced(self) -> list[Path]:
        """列出已同步到 resources 的 Recipe 脚本"""
        synced = []
        script_extensions = {".py", ".js", ".sh"}

        for path in self.target_dir.rglob("*"):
            if path.is_file() and path.suffix in script_extensions:
                synced.append(path)

        return synced

    def clean(
        self,
        dry_run: bool = False,
    ) -> list[Path]:
        """
        清理目标目录中不存在于源目录的 Recipe

        Args:
            dry_run: 如果为 True，仅显示将要删除的文件，不实际执行

        Returns:
            被删除（或将要删除）的文件列表
        """
        removed = []

        for target_script in self.list_synced():
            # 计算对应的源路径
            rel_path = target_script.relative_to(self.target_dir)
            source_script = self.source_dir / rel_path

            if not source_script.exists():
                target_metadata = target_script.with_suffix(".md")

                if not dry_run:
                    if target_script.exists():
                        target_script.unlink()
                        removed.append(target_script)
                    if target_metadata.exists():
                        target_metadata.unlink()
                        removed.append(target_metadata)
                else:
                    if target_script.exists():
                        removed.append(target_script)
                    if target_metadata.exists():
                        removed.append(target_metadata)

        return removed
