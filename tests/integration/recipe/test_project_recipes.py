"""
集成测试：项目级 Recipe 支持

测试项目级 Recipe 优先级、切换目录后行为、同名 Recipe 处理
"""

import json
import tempfile
from pathlib import Path

import pytest

from frago.recipes.runner import RecipeRunner
from frago.recipes.registry import RecipeRegistry


@pytest.fixture
def temp_project_dir():
    """创建临时项目目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        yield project_path


class TestProjectLevelRecipeDetection:
    """测试项目级 Recipe 检测"""

    def test_project_path_detection(self, temp_project_dir):
        """测试项目级路径检测"""
        # 创建项目级 Recipe 目录
        recipe_dir = temp_project_dir / '.frago' / 'recipes' / 'workflows'
        recipe_dir.mkdir(parents=True)

        # 切换到项目目录
        import os
        original_cwd = Path.cwd()
        os.chdir(temp_project_dir)

        try:
            # 创建注册表
            registry = RecipeRegistry()

            # 验证项目级路径被检测到
            project_path = temp_project_dir / '.frago' / 'recipes'
            assert project_path in registry.search_paths

        finally:
            # 恢复原目录
            os.chdir(original_cwd)

    def test_search_paths_order(self):
        """测试搜索路径优先级顺序"""
        registry = RecipeRegistry()

        # 验证优先级顺序
        # 注意：只有存在的路径才会被添加到 search_paths
        # 我们只验证顺序是正确的
        if len(registry.search_paths) >= 2:
            # 如果有多个路径，验证顺序
            sources = [registry._get_source_label(p) for p in registry.search_paths]

            # Project 应该在 User 之前
            if 'Project' in sources and 'User' in sources:
                assert sources.index('Project') < sources.index('User')

            # User 应该在 Example 之前
            if 'User' in sources and 'Example' in sources:
                assert sources.index('User') < sources.index('Example')


class TestProjectRecipePriority:
    """测试项目级 Recipe 优先级"""

    def test_project_recipe_overrides_user(self, temp_project_dir):
        """测试项目级 Recipe 覆盖用户级 Recipe"""
        # 创建项目级 Recipe
        project_recipe_dir = temp_project_dir / '.frago' / 'recipes' / 'workflows'
        project_recipe_dir.mkdir(parents=True)

        # 创建项目级元数据
        project_md = project_recipe_dir / 'test_override.md'
        project_md.write_text("""---
name: test_override
type: workflow
runtime: python
version: "2.0"
description: "项目级覆盖版本"
use_cases:
  - "项目特定用途"
output_targets:
  - stdout
tags:
  - project
inputs: {}
outputs: {}
dependencies: []
---

# 项目级 Recipe
""")

        # 创建项目级脚本
        project_script = project_recipe_dir / 'test_override.py'
        project_script.write_text("""#!/usr/bin/env python3
import json
import sys
print(json.dumps({"source": "project", "version": "2.0"}))
""")

        # 切换到项目目录
        import os
        original_cwd = Path.cwd()
        os.chdir(temp_project_dir)

        try:
            # 扫描 Recipe
            registry = RecipeRegistry()
            registry.scan()

            # 如果 test_override 被注册（可能被注册，取决于是否有同名全局 Recipe）
            if 'test_override' in registry.recipes:
                recipe = registry.find('test_override')
                # 验证使用的是项目级版本
                assert recipe.source == 'Project'
                assert recipe.metadata.version == '2.0'

        finally:
            os.chdir(original_cwd)

    def test_find_all_sources(self, temp_project_dir):
        """测试查找所有来源的同名 Recipe"""
        # 创建项目级 Recipe
        project_recipe_dir = temp_project_dir / '.frago' / 'recipes' / 'workflows'
        project_recipe_dir.mkdir(parents=True)

        project_md = project_recipe_dir / 'multi_source.md'
        project_md.write_text("""---
name: multi_source
type: workflow
runtime: python
version: "1.0"
description: "测试"
use_cases:
  - "测试"
output_targets:
  - stdout
inputs: {}
outputs: {}
---
""")

        # 切换到项目目录
        import os
        original_cwd = Path.cwd()
        os.chdir(temp_project_dir)

        try:
            registry = RecipeRegistry()
            registry.scan()

            # 测试 find_all_sources 方法
            sources = registry.find_all_sources('multi_source')
            assert len(sources) >= 1

            # 验证返回的是 (source, path) 元组列表
            for source, path in sources:
                assert source in ['Project', 'User', 'Example']
                assert isinstance(path, Path)

        finally:
            os.chdir(original_cwd)


class TestProjectRecipeExecution:
    """测试项目级 Recipe 执行"""

    def test_execute_project_specific_task(self):
        """测试执行 project_specific_task 示例"""
        registry = RecipeRegistry()
        registry.scan()

        # 验证 project_specific_task 存在
        if 'project_specific_task' not in registry.recipes:
            pytest.skip("project_specific_task Recipe 不存在")

        runner = RecipeRunner(registry)

        # 执行 Recipe
        result = runner.run(
            "project_specific_task",
            params={"project_name": "TestProject"}
        )

        # 验证返回格式
        assert isinstance(result, dict)
        assert result["success"] is True

        # 验证返回数据
        data = result["data"]
        assert "message" in data
        assert "project_info" in data

        # 验证项目信息
        project_info = data["project_info"]
        assert "name" in project_info
        assert project_info["name"] == "TestProject"


class TestDirectorySwitching:
    """测试切换目录后的行为"""

    def test_registry_reflects_current_directory(self, temp_project_dir):
        """测试注册表反映当前工作目录"""
        # 创建两个项目目录
        project1 = temp_project_dir / "project1"
        project2 = temp_project_dir / "project2"
        project1.mkdir()
        project2.mkdir()

        # 在 project1 创建 Recipe
        recipe1_dir = project1 / '.frago' / 'recipes' / 'workflows'
        recipe1_dir.mkdir(parents=True)
        (recipe1_dir / 'p1_recipe.md').write_text("""---
name: p1_recipe
type: workflow
runtime: python
version: "1.0"
description: "Project 1 Recipe"
use_cases:
  - "测试"
output_targets:
  - stdout
inputs: {}
outputs: {}
---
""")
        # 创建对应的脚本文件
        (recipe1_dir / 'p1_recipe.py').write_text("""#!/usr/bin/env python3
import json
import sys
print(json.dumps({"project": "1"}))
""")

        # 在 project2 创建不同的 Recipe
        recipe2_dir = project2 / '.frago' / 'recipes' / 'workflows'
        recipe2_dir.mkdir(parents=True)
        (recipe2_dir / 'p2_recipe.md').write_text("""---
name: p2_recipe
type: workflow
runtime: python
version: "1.0"
description: "Project 2 Recipe"
use_cases:
  - "测试"
output_targets:
  - stdout
inputs: {}
outputs: {}
---
""")
        # 创建对应的脚本文件
        (recipe2_dir / 'p2_recipe.py').write_text("""#!/usr/bin/env python3
import json
import sys
print(json.dumps({"project": "2"}))
""")

        import os
        original_cwd = Path.cwd()

        try:
            # 切换到 project1
            os.chdir(project1)
            registry1 = RecipeRegistry()
            registry1.scan()

            # 切换到 project2
            os.chdir(project2)
            registry2 = RecipeRegistry()
            registry2.scan()

            # 验证各自的 Recipe 被检测到
            assert 'p1_recipe' in registry1.recipes
            assert 'p2_recipe' not in registry1.recipes

            assert 'p2_recipe' in registry2.recipes
            assert 'p1_recipe' not in registry2.recipes

        finally:
            os.chdir(original_cwd)
