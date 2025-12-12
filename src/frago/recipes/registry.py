"""Recipe 注册表"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .exceptions import RecipeNotFoundError
from .metadata import RecipeMetadata, parse_metadata_file, validate_metadata


@dataclass
class Recipe:
    """Recipe 实体"""
    metadata: RecipeMetadata
    script_path: Path
    metadata_path: Path
    source: str  # Project | User | Example
    base_dir: Optional[Path] = None  # 配方根目录（目录形式配方）

    @property
    def examples_dir(self) -> Optional[Path]:
        """返回示例目录路径（如果存在）"""
        if self.base_dir:
            examples = self.base_dir / 'examples'
            if examples.exists():
                return examples
        return None

    def list_examples(self) -> list[Path]:
        """列出所有示例文件"""
        if self.examples_dir:
            return list(self.examples_dir.glob('*'))
        return []


class RecipeRegistry:
    """Recipe 注册表，管理所有可用 Recipe 的索引"""

    def __init__(self):
        self.search_paths: list[Path] = []
        # 嵌套字典：{recipe_name: {source: Recipe}}
        self.recipes: dict[str, dict[str, Recipe]] = {}
        self._setup_search_paths()

    def _setup_search_paths(self) -> None:
        """设置查找路径 - 统一使用 ~/.frago/recipes/"""
        # 只使用用户目录
        user_path = Path.home() / '.frago' / 'recipes'
        if user_path.exists():
            self.search_paths.append(user_path)
    
    def scan(self) -> None:
        """扫描所有 search_paths，解析元数据并构建索引"""
        self.recipes.clear()

        for search_path in self.search_paths:
            source = self._get_source_label(search_path)
            self._scan_directory(search_path, source)

        # 验证 Workflow 的依赖
        self._validate_dependencies()
    
    def _get_source_label(self, path: Path) -> str:
        """根据路径返回来源标签"""
        # 统一使用用户目录
        return 'User'
    
    def _scan_directory(self, base_path: Path, source: str) -> None:
        """递归扫描目录，查找 Recipe（目录形式）"""
        # 扫描子目录: atomic/chrome/, atomic/system/, workflows/
        for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
            dir_path = base_path / subdir
            if not dir_path.exists():
                continue

            # 查找所有配方目录（包含 recipe.md 的目录）
            for recipe_dir in dir_path.iterdir():
                if recipe_dir.is_dir():
                    metadata_path = recipe_dir / 'recipe.md'
                    if metadata_path.exists():
                        self._register_recipe(metadata_path, source, recipe_dir)
    
    def _register_recipe(self, metadata_path: Path, source: str, base_dir: Path) -> None:
        """注册单个 Recipe（目录形式）"""
        try:
            # 解析元数据
            metadata = parse_metadata_file(metadata_path)

            # 验证元数据
            validate_metadata(metadata)

            # 查找对应的脚本文件（在配方目录内查找 recipe.py/js/sh）
            script_path = self._find_script_file(base_dir, metadata.runtime)
            if not script_path:
                # 脚本文件不存在，跳过
                return

            # 创建 Recipe 对象
            recipe = Recipe(
                metadata=metadata,
                script_path=script_path,
                metadata_path=metadata_path,
                source=source,
                base_dir=base_dir
            )

            # 初始化配方名称的字典（如果不存在）
            if metadata.name not in self.recipes:
                self.recipes[metadata.name] = {}

            # 按来源存储（同一来源下同名配方仍然覆盖）
            self.recipes[metadata.name][source] = recipe

        except Exception:
            # 解析或验证失败，跳过该 Recipe（静默）
            pass
    
    def _find_script_file(self, recipe_dir: Path, runtime: str) -> Optional[Path]:
        """根据运行时类型在配方目录内查找脚本文件"""
        # 根据 runtime 确定扩展名
        extensions = {
            'chrome-js': ['.js'],
            'python': ['.py'],
            'shell': ['.sh']
        }

        for ext in extensions.get(runtime, []):
            script_path = recipe_dir / f"recipe{ext}"
            if script_path.exists():
                return script_path

        return None
    
    def find(self, name: str, source: Optional[str] = None) -> Recipe:
        """
        查找指定名称的 Recipe

        Args:
            name: Recipe 名称
            source: 指定来源 ('project' | 'user' | 'example')，为 None 时按优先级返回

        Returns:
            Recipe 对象

        Raises:
            RecipeNotFoundError: Recipe 不存在时抛出
        """
        searched_paths = [str(p) for p in self.search_paths]

        if name not in self.recipes:
            raise RecipeNotFoundError(name, searched_paths)

        sources_dict = self.recipes[name]

        if source:
            # 指定来源查找
            source_label = source.capitalize()
            if source_label not in sources_dict:
                raise RecipeNotFoundError(f"{name} (source: {source})", searched_paths)
            return sources_dict[source_label]

        # 未指定来源：返回 User 来源
        if 'User' in sources_dict:
            return sources_dict['User']

        # 理论上不应该到达这里，因为 sources_dict 不为空
        raise RecipeNotFoundError(name, searched_paths)
    
    def list_all(self, include_all_sources: bool = False) -> list[Recipe]:
        """
        列出所有 Recipe

        Args:
            include_all_sources: 是否包含所有来源的配方（默认只返回最高优先级的）

        Returns:
            Recipe 列表（按名称排序）
        """
        result = []
        for name, sources_dict in self.recipes.items():
            if include_all_sources:
                # 返回所有来源的配方
                result.extend(sources_dict.values())
            else:
                # 返回 User 来源
                if 'User' in sources_dict:
                    result.append(sources_dict['User'])
        return sorted(result, key=lambda r: r.metadata.name)
    
    def get_by_source(self, source: str) -> list[Recipe]:
        """
        按来源过滤 Recipe

        Args:
            source: 来源标签 (Project | User | Example)

        Returns:
            匹配来源的 Recipe 列表（按名称排序）
        """
        source_label = source.capitalize()
        result = []
        for sources_dict in self.recipes.values():
            if source_label in sources_dict:
                result.append(sources_dict[source_label])
        return sorted(result, key=lambda r: r.metadata.name)

    def _validate_dependencies(self) -> None:
        """
        验证所有 Workflow Recipe 的依赖是否存在

        如果 Workflow 声明了 dependencies，检查这些依赖 Recipe 是否已注册。
        依赖缺失的 Recipe 会被从注册表中移除，并在日志中记录警告。
        """
        # 收集需要移除的配方：[(recipe_name, source), ...]
        invalid_recipes = []

        for name, sources_dict in self.recipes.items():
            for source, recipe in sources_dict.items():
                # 只检查 Workflow 类型的 Recipe
                if recipe.metadata.type != 'workflow':
                    continue

                # 检查依赖列表
                dependencies = recipe.metadata.dependencies or []
                missing_deps = []

                for dep_name in dependencies:
                    # 依赖存在只要在任意来源有即可
                    if dep_name not in self.recipes:
                        missing_deps.append(dep_name)

                if missing_deps:
                    # 记录缺失依赖的 Recipe
                    invalid_recipes.append((name, source, missing_deps))

        # 移除依赖缺失的 Recipe
        for recipe_name, source, missing_deps in invalid_recipes:
            del self.recipes[recipe_name][source]
            # 如果该配方名下没有任何来源了，删除整个条目
            if not self.recipes[recipe_name]:
                del self.recipes[recipe_name]
            # 可以在这里添加日志记录，但为了保持简单，我们只静默移除
            # print(f"警告: Recipe '{recipe_name}' ({source}) 的依赖缺失: {', '.join(missing_deps)}", file=sys.stderr)

    def find_all_sources(self, name: str) -> list[tuple[str, Path]]:
        """
        查找所有来源中是否存在同名 Recipe

        Args:
            name: Recipe 名称

        Returns:
            [(source, recipe_dir), ...] 列表，按优先级排序
        """
        if name not in self.recipes:
            return []

        # 返回 User 来源
        result = []
        if 'User' in self.recipes[name]:
            recipe = self.recipes[name]['User']
            result.append(('User', recipe.base_dir))
        return result
