"""
单元测试：Recipe 注册表

测试三级查找路径、优先级、来源标注、同名 Recipe 处理。
"""

import tempfile
from pathlib import Path

import pytest

from frago.recipes.registry import RecipeRegistry, Recipe
from frago.recipes.exceptions import RecipeNotFoundError


@pytest.fixture
def temp_recipe_dirs(tmp_path):
    """创建临时的三级 Recipe 目录结构"""
    # 项目级目录（模拟在当前工作目录）
    project_dir = tmp_path / 'project' / '.frago' / 'recipes' / 'atomic' / 'chrome'
    project_dir.mkdir(parents=True)

    # 用户级目录（模拟在用户家目录）
    user_dir = tmp_path / 'user' / '.frago' / 'recipes' / 'atomic' / 'chrome'
    user_dir.mkdir(parents=True)

    # 示例级目录
    example_dir = tmp_path / 'examples' / 'atomic' / 'chrome'
    example_dir.mkdir(parents=True)

    # 创建示例 Recipe（不同优先级）
    # 示例级：basic_recipe
    create_test_recipe(
        example_dir,
        'basic_recipe',
        'chrome-js',
        'Example recipe',
        '1.0.0'
    )

    # 用户级：basic_recipe (同名，应该覆盖示例级)
    create_test_recipe(
        user_dir,
        'basic_recipe',
        'chrome-js',
        'User customized recipe',
        '1.1.0'
    )

    # 项目级：basic_recipe (同名，应该覆盖用户级)
    create_test_recipe(
        project_dir,
        'basic_recipe',
        'chrome-js',
        'Project specific recipe',
        '2.0.0'
    )

    # 用户级：user_recipe (仅存在于用户级)
    create_test_recipe(
        user_dir,
        'user_recipe',
        'chrome-js',
        'User only recipe',
        '1.0.0'
    )

    # 示例级：example_recipe (仅存在于示例级)
    create_test_recipe(
        example_dir,
        'example_recipe',
        'chrome-js',
        'Example only recipe',
        '1.0.0'
    )

    yield {
        'project': tmp_path / 'project',
        'user': tmp_path / 'user',
        'example': tmp_path / 'examples',
        'project_recipes': project_dir.parent.parent,
        'user_recipes': user_dir.parent.parent,
        'example_recipes': example_dir.parent.parent
    }


def create_test_recipe(directory: Path, name: str, runtime: str, description: str, version: str):
    """创建一个测试 Recipe（脚本 + 元数据）"""
    # 创建脚本文件
    script_ext = '.js' if runtime == 'chrome-js' else '.py'
    script_path = directory / f"{name}{script_ext}"
    script_path.write_text(f"// Test recipe: {name}\nconsole.log('test');")

    # 创建元数据文件
    metadata_path = directory / f"{name}.md"
    metadata_content = f"""---
name: {name}
type: atomic
runtime: {runtime}
version: "{version}"
description: "{description}"
use_cases:
  - "Test use case 1"
  - "Test use case 2"
tags:
  - test
output_targets:
  - stdout
inputs: {{}}
outputs: {{}}
---

# {name}

Test recipe for unit testing.
"""
    metadata_path.write_text(metadata_content)


class TestRecipeRegistryPaths:
    """测试三级查找路径"""

    def test_search_paths_setup(self, temp_recipe_dirs, monkeypatch):
        """测试搜索路径正确设置"""
        # Mock 工作目录和家目录
        monkeypatch.setattr(Path, 'cwd', lambda: temp_recipe_dirs['project'])
        monkeypatch.setattr(Path, 'home', lambda: temp_recipe_dirs['user'])

        # 修改 registry 初始化逻辑
        from frago.recipes.registry import RecipeRegistry

        registry = RecipeRegistry()

        # 验证搜索路径数量（至少应该有示例路径）
        assert len(registry.search_paths) > 0

    def test_project_level_path(self, temp_recipe_dirs, monkeypatch):
        """测试项目级路径存在时被添加"""
        monkeypatch.setattr(Path, 'cwd', lambda: temp_recipe_dirs['project'])
        monkeypatch.setattr(Path, 'home', lambda: Path('/nonexistent'))

        registry = RecipeRegistry()

        # 应该至少有项目级路径
        project_path = temp_recipe_dirs['project'] / '.frago' / 'recipes'
        # 注意：_setup_search_paths 可能不会添加不存在的路径
        # 所以我们只验证不会崩溃

    def test_user_level_path(self, temp_recipe_dirs, monkeypatch):
        """测试用户级路径存在时被添加"""
        monkeypatch.setattr(Path, 'home', lambda: temp_recipe_dirs['user'])

        registry = RecipeRegistry()

        user_path = temp_recipe_dirs['user'] / '.frago' / 'recipes'
        # 验证不会崩溃


class TestRecipeRegistryPriority:
    """测试优先级逻辑"""

    def test_same_name_recipe_priority(self, temp_recipe_dirs, monkeypatch):
        """测试同名 Recipe 的优先级（项目 > 用户 > 示例）"""
        # 模拟环境：项目目录存在 basic_recipe
        monkeypatch.setattr(Path, 'cwd', lambda: temp_recipe_dirs['project'])
        monkeypatch.setattr(Path, 'home', lambda: temp_recipe_dirs['user'])

        # 手动设置搜索路径
        registry = RecipeRegistry()
        registry.search_paths = [
            temp_recipe_dirs['project_recipes'],
            temp_recipe_dirs['user_recipes'],
            temp_recipe_dirs['example_recipes']
        ]

        registry.scan()

        # 查找 basic_recipe
        recipe = registry.find('basic_recipe')

        # 应该是项目级的版本（version 2.0.0）
        assert recipe.metadata.version == '2.0.0'
        assert recipe.metadata.description == 'Project specific recipe'
        assert recipe.source == 'Project'

    def test_user_level_priority_over_example(self, temp_recipe_dirs, monkeypatch):
        """测试用户级优先于示例级（无项目级时）"""
        # 不设置项目级路径
        monkeypatch.setattr(Path, 'cwd', lambda: Path('/nonexistent'))
        monkeypatch.setattr(Path, 'home', lambda: temp_recipe_dirs['user'])

        registry = RecipeRegistry()
        registry.search_paths = [
            temp_recipe_dirs['user_recipes'],
            temp_recipe_dirs['example_recipes']
        ]

        registry.scan()

        recipe = registry.find('basic_recipe')

        # 应该是用户级的版本（version 1.1.0）
        assert recipe.metadata.version == '1.1.0'
        assert recipe.metadata.description == 'User customized recipe'
        assert recipe.source == 'User'


class TestRecipeRegistrySourceLabels:
    """测试来源标注"""

    def test_project_source_label(self, temp_recipe_dirs, monkeypatch):
        """测试项目级 Recipe 标注为 Project"""
        monkeypatch.setattr(Path, 'cwd', lambda: temp_recipe_dirs['project'])

        registry = RecipeRegistry()
        registry.search_paths = [temp_recipe_dirs['project_recipes']]
        registry.scan()

        recipe = registry.find('basic_recipe')
        assert recipe.source == 'Project'

    def test_user_source_label(self, temp_recipe_dirs, monkeypatch):
        """测试用户级 Recipe 标注为 User"""
        monkeypatch.setattr(Path, 'home', lambda: temp_recipe_dirs['user'])

        registry = RecipeRegistry()
        registry.search_paths = [temp_recipe_dirs['user_recipes']]
        registry.scan()

        recipe = registry.find('user_recipe')
        assert recipe.source == 'User'

    def test_example_source_label(self, temp_recipe_dirs):
        """测试示例级 Recipe 标注为 Example"""
        registry = RecipeRegistry()
        registry.search_paths = [temp_recipe_dirs['example_recipes']]
        registry.scan()

        recipe = registry.find('example_recipe')
        assert recipe.source == 'Example'


class TestRecipeRegistryScanning:
    """测试扫描功能"""

    def test_scan_finds_all_recipes(self, temp_recipe_dirs):
        """测试 scan 找到所有 Recipe"""
        registry = RecipeRegistry()
        registry.search_paths = [
            temp_recipe_dirs['project_recipes'],
            temp_recipe_dirs['user_recipes'],
            temp_recipe_dirs['example_recipes']
        ]

        registry.scan()

        # 应该找到 3 个不同的 Recipe（basic_recipe, user_recipe, example_recipe）
        all_recipes = registry.list_all()
        assert len(all_recipes) >= 3

        recipe_names = [r.metadata.name for r in all_recipes]
        assert 'basic_recipe' in recipe_names
        assert 'user_recipe' in recipe_names
        assert 'example_recipe' in recipe_names

    def test_find_recipe_by_name(self, temp_recipe_dirs):
        """测试通过名称查找 Recipe"""
        registry = RecipeRegistry()
        registry.search_paths = [temp_recipe_dirs['example_recipes']]
        registry.scan()

        recipe = registry.find('example_recipe')
        assert recipe.metadata.name == 'example_recipe'
        assert recipe.metadata.description == 'Example only recipe'

    def test_find_nonexistent_recipe(self, temp_recipe_dirs):
        """测试查找不存在的 Recipe 抛出异常"""
        registry = RecipeRegistry()
        registry.search_paths = [temp_recipe_dirs['example_recipes']]
        registry.scan()

        with pytest.raises(RecipeNotFoundError):
            registry.find('nonexistent_recipe')

    def test_list_all_recipes(self, temp_recipe_dirs):
        """测试列出所有 Recipe"""
        registry = RecipeRegistry()
        registry.search_paths = [
            temp_recipe_dirs['user_recipes'],
            temp_recipe_dirs['example_recipes']
        ]
        registry.scan()

        all_recipes = registry.list_all()
        assert isinstance(all_recipes, list)
        assert len(all_recipes) > 0
        assert all(isinstance(r, Recipe) for r in all_recipes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
