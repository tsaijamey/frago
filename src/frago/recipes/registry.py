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


class RecipeRegistry:
    """Recipe 注册表，管理所有可用 Recipe 的索引"""
    
    def __init__(self):
        self.search_paths: list[Path] = []
        self.recipes: dict[str, Recipe] = {}
        self._setup_search_paths()
    
    def _setup_search_paths(self) -> None:
        """设置三级查找路径（按优先级排序）"""
        # 1. 项目级: .frago/recipes/ (当前工作目录)
        project_path = Path.cwd() / '.frago' / 'recipes'
        if project_path.exists():
            self.search_paths.append(project_path)
        
        # 2. 用户级: ~/.frago/recipes/ (用户家目录)
        user_path = Path.home() / '.frago' / 'recipes'
        if user_path.exists():
            self.search_paths.append(user_path)
        
        # 3. 示例级: examples/ (仓库根目录或安装位置)
        # 查找 src/frago/recipes/registry.py 的位置，推导出仓库根目录
        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent.parent
        example_path = repo_root / 'examples'
        if example_path.exists():
            self.search_paths.append(example_path)
    
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
        # 项目级：当前工作目录下的 .frago/recipes/
        project_path = Path.cwd() / '.frago' / 'recipes'
        if path == project_path or project_path in path.parents:
            return 'Project'

        # 用户级：用户家目录下的 .frago/recipes/
        user_path = Path.home() / '.frago' / 'recipes'
        if path == user_path or user_path in path.parents:
            return 'User'

        # 示例级：其他路径（通常是 examples/）
        return 'Example'
    
    def _scan_directory(self, base_path: Path, source: str) -> None:
        """递归扫描目录，查找 Recipe 元数据文件"""
        # 扫描子目录: atomic/chrome/, atomic/system/, workflows/
        for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
            dir_path = base_path / subdir
            if not dir_path.exists():
                continue
            
            # 查找所有 .md 文件
            for metadata_path in dir_path.glob('*.md'):
                self._register_recipe(metadata_path, source)
    
    def _register_recipe(self, metadata_path: Path, source: str) -> None:
        """注册单个 Recipe"""
        try:
            # 解析元数据
            metadata = parse_metadata_file(metadata_path)
            
            # 验证元数据
            validate_metadata(metadata)
            
            # 查找对应的脚本文件
            script_path = self._find_script_file(metadata_path, metadata.runtime)
            if not script_path:
                # 脚本文件不存在，跳过
                return
            
            # 检查是否已存在同名 Recipe（优先级高的覆盖低的）
            if metadata.name in self.recipes:
                # 已存在，跳过（因为高优先级路径先扫描）
                return
            
            # 注册 Recipe
            recipe = Recipe(
                metadata=metadata,
                script_path=script_path,
                metadata_path=metadata_path,
                source=source
            )
            self.recipes[metadata.name] = recipe
        
        except Exception:
            # 解析或验证失败，跳过该 Recipe（静默）
            pass
    
    def _find_script_file(self, metadata_path: Path, runtime: str) -> Optional[Path]:
        """根据运行时类型查找脚本文件"""
        base_name = metadata_path.stem
        dir_path = metadata_path.parent
        
        # 根据 runtime 确定扩展名
        extensions = {
            'chrome-js': ['.js'],
            'python': ['.py'],
            'shell': ['.sh']
        }
        
        for ext in extensions.get(runtime, []):
            script_path = dir_path / f"{base_name}{ext}"
            if script_path.exists():
                return script_path
        
        return None
    
    def find(self, name: str) -> Recipe:
        """
        查找指定名称的 Recipe
        
        Args:
            name: Recipe 名称
        
        Returns:
            Recipe 对象
        
        Raises:
            RecipeNotFoundError: Recipe 不存在时抛出
        """
        if name not in self.recipes:
            searched_paths = [str(p) for p in self.search_paths]
            raise RecipeNotFoundError(name, searched_paths)
        
        return self.recipes[name]
    
    def list_all(self) -> list[Recipe]:
        """
        列出所有 Recipe
        
        Returns:
            Recipe 列表（按名称排序）
        """
        return sorted(self.recipes.values(), key=lambda r: r.metadata.name)
    
    def get_by_source(self, source: str) -> list[Recipe]:
        """
        按来源过滤 Recipe

        Args:
            source: 来源标签 (Project | User | Example)

        Returns:
            匹配来源的 Recipe 列表
        """
        return [r for r in self.recipes.values() if r.source == source]

    def _validate_dependencies(self) -> None:
        """
        验证所有 Workflow Recipe 的依赖是否存在

        如果 Workflow 声明了 dependencies，检查这些依赖 Recipe 是否已注册。
        依赖缺失的 Recipe 会被从注册表中移除，并在日志中记录警告。
        """
        invalid_recipes = []

        for name, recipe in self.recipes.items():
            # 只检查 Workflow 类型的 Recipe
            if recipe.metadata.type != 'workflow':
                continue

            # 检查依赖列表
            dependencies = recipe.metadata.dependencies or []
            missing_deps = []

            for dep_name in dependencies:
                if dep_name not in self.recipes:
                    missing_deps.append(dep_name)

            if missing_deps:
                # 记录缺失依赖的 Recipe
                invalid_recipes.append((name, missing_deps))

        # 移除依赖缺失的 Recipe
        for recipe_name, missing_deps in invalid_recipes:
            del self.recipes[recipe_name]
            # 可以在这里添加日志记录，但为了保持简单，我们只静默移除
            # print(f"警告: Recipe '{recipe_name}' 的依赖缺失: {', '.join(missing_deps)}", file=sys.stderr)

    def find_all_sources(self, name: str) -> list[tuple[str, Path]]:
        """
        查找所有来源中是否存在同名 Recipe

        Args:
            name: Recipe 名称

        Returns:
            [(source, path), ...] 列表，按优先级排序
        """
        sources = []

        for search_path in self.search_paths:
            source = self._get_source_label(search_path)

            # 扫描子目录查找同名 Recipe
            for subdir in ['atomic/chrome', 'atomic/system', 'workflows']:
                dir_path = search_path / subdir
                if not dir_path.exists():
                    continue

                # 查找元数据文件
                metadata_path = dir_path / f"{name}.md"
                if metadata_path.exists():
                    sources.append((source, metadata_path))

        return sources
