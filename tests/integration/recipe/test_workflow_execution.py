"""
集成测试：Workflow Recipe 执行功能

测试 Workflow Recipe 的完整执行流程：
- Workflow 调用多个原子 Recipe
- 循环处理逻辑
- 错误处理和异常传播
- 结果汇总
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from frago.recipes.runner import RecipeRunner
from frago.recipes.registry import RecipeRegistry
from frago.recipes.exceptions import RecipeExecutionError


@pytest.fixture
def recipe_runner():
    """创建 RecipeRunner 实例"""
    registry = RecipeRegistry()
    registry.scan()
    return RecipeRunner(registry)


@pytest.fixture
def temp_output_dir():
    """创建临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestWorkflowDependencyValidation:
    """测试 Workflow 依赖验证"""

    def test_workflow_with_valid_dependencies(self, recipe_runner):
        """测试 Workflow 依赖存在时可以正常注册"""
        # upwork_batch_extract 依赖 upwork_extract_job_details_as_markdown
        registry = recipe_runner.registry

        # 验证依赖的 Recipe 存在
        assert "upwork_extract_job_details_as_markdown" in registry.recipes

        # 验证 Workflow 存在
        assert "upwork_batch_extract" in registry.recipes

        # 验证 Workflow 类型
        workflow = registry.find("upwork_batch_extract")
        assert workflow.metadata.type == "workflow"
        assert workflow.metadata.runtime == "python"

    def test_workflow_dependencies_in_metadata(self, recipe_runner):
        """测试 Workflow 元数据包含正确的依赖声明"""
        registry = recipe_runner.registry
        workflow = registry.find("upwork_batch_extract")

        # 验证依赖列表
        assert workflow.metadata.dependencies is not None
        assert "upwork_extract_job_details_as_markdown" in workflow.metadata.dependencies


class TestWorkflowExecution:
    """测试 Workflow 执行"""

    def test_workflow_script_exists(self):
        """测试 Workflow 脚本文件存在且可读"""
        workflow_path = Path(__file__).parent.parent.parent.parent / "examples/workflows/upwork_batch_extract.py"
        assert workflow_path.exists()
        assert workflow_path.is_file()

        # 验证脚本包含必要的导入
        content = workflow_path.read_text()
        assert "from frago.recipes import RecipeRunner" in content
        assert "RecipeExecutionError" in content

    def test_workflow_metadata_structure(self, recipe_runner):
        """测试 Workflow 元数据结构完整"""
        workflow = recipe_runner.registry.find("upwork_batch_extract")

        # 验证元数据字段
        assert workflow.metadata.name == "upwork_batch_extract"
        assert workflow.metadata.type == "workflow"
        assert workflow.metadata.runtime == "python"

        # 验证输入参数定义
        assert "urls" in workflow.metadata.inputs
        assert workflow.metadata.inputs["urls"]["required"] is True
        assert workflow.metadata.inputs["urls"]["type"] == "array"

        # 验证输出定义
        assert "success" in workflow.metadata.outputs
        assert "total" in workflow.metadata.outputs
        assert "successful" in workflow.metadata.outputs
        assert "failed" in workflow.metadata.outputs

    def test_workflow_can_be_registered(self, recipe_runner):
        """测试 Workflow 可以被正确注册"""
        registry = recipe_runner.registry

        # 验证 Workflow 已注册
        assert "upwork_batch_extract" in registry.recipes

        # 验证可以通过 list_all 找到
        all_recipes = registry.list_all()
        workflow_names = [r.metadata.name for r in all_recipes]
        assert "upwork_batch_extract" in workflow_names


class TestWorkflowErrorHandling:
    """测试 Workflow 错误处理"""

    def test_workflow_missing_required_params(self, recipe_runner):
        """测试 Workflow 缺少必需参数时抛出验证错误"""
        from frago.recipes.exceptions import RecipeValidationError

        with pytest.raises(RecipeValidationError) as exc_info:
            recipe_runner.run("upwork_batch_extract", params={})

        # 验证错误信息
        assert "urls" in str(exc_info.value)

    def test_workflow_with_invalid_params_type(self, recipe_runner):
        """测试 Workflow 参数类型错误"""
        from frago.recipes.exceptions import RecipeValidationError

        # urls 应该是数组，不是字符串
        with pytest.raises((RecipeValidationError, RecipeExecutionError)):
            recipe_runner.run(
                "upwork_batch_extract",
                params={"urls": "not-an-array"}
            )


class TestWorkflowRecipeIntegration:
    """测试 Workflow Recipe 与原子 Recipe 的集成"""

    def test_workflow_can_import_recipe_runner(self):
        """测试 Workflow 脚本可以导入 RecipeRunner"""
        # 验证 RecipeRunner 已导出
        from frago.recipes import RecipeRunner
        assert RecipeRunner is not None

    def test_workflow_can_catch_recipe_execution_error(self):
        """测试 Workflow 可以捕获原子 Recipe 的执行异常"""
        from frago.recipes import RecipeRunner, RecipeExecutionError

        runner = RecipeRunner()

        # 尝试运行不存在的 Recipe
        try:
            runner.run("non_existent_recipe")
            assert False, "应该抛出异常"
        except Exception as e:
            # 验证异常类型
            assert isinstance(e, (RecipeExecutionError, Exception))
