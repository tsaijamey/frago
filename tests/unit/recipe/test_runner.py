"""
单元测试：RecipeRunner（Recipe 执行器）

测试 Recipe 执行、参数验证、超时和输出大小限制
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.recipes.exceptions import RecipeExecutionError, RecipeValidationError
from frago.recipes.metadata import RecipeMetadata
from frago.recipes.registry import Recipe
from frago.recipes.runner import RecipeRunner


@pytest.fixture
def mock_registry():
    """创建模拟的 RecipeRegistry"""
    registry = MagicMock()
    return registry


@pytest.fixture
def runner_with_mock_registry(mock_registry):
    """创建带有模拟注册表的 RecipeRunner"""
    return RecipeRunner(registry=mock_registry)


class TestRecipeRunnerParameterValidation:
    """测试参数验证"""

    def test_validates_required_params(self, runner_with_mock_registry, mock_registry):
        """测试必需参数验证"""
        # 创建需要参数的元数据
        metadata = RecipeMetadata(
            name="test_recipe",
            type="atomic",
            runtime="python",
            description="Test",
            use_cases=["test"],
            output_targets=["stdout"],
            inputs={
                "url": {"type": "string", "required": True, "description": "URL"}
            },
            outputs={},
            dependencies=[],
            version="1.0.0"
        )

        recipe = Recipe(
            metadata=metadata,
            script_path=Path("/tmp/test.py"),
            metadata_path=Path("/tmp/test.md"),
            source="User"
        )

        mock_registry.find.return_value = recipe

        # 不提供必需参数应该抛出验证错误
        with pytest.raises(RecipeValidationError) as exc_info:
            runner_with_mock_registry.run("test_recipe", params={})

        assert "缺少必需参数: 'url'" in str(exc_info.value)

    def test_validates_param_types(self, runner_with_mock_registry, mock_registry):
        """测试参数类型验证"""
        metadata = RecipeMetadata(
            name="test_recipe",
            type="atomic",
            runtime="python",
            description="Test",
            use_cases=["test"],
            output_targets=["stdout"],
            inputs={
                "count": {"type": "number", "required": True}
            },
            outputs={},
            dependencies=[],
            version="1.0.0"
        )

        recipe = Recipe(
            metadata=metadata,
            script_path=Path("/tmp/test.py"),
            metadata_path=Path("/tmp/test.md"),
            source="User"
        )

        mock_registry.find.return_value = recipe

        # 提供错误类型的参数
        with pytest.raises(RecipeValidationError) as exc_info:
            runner_with_mock_registry.run("test_recipe", params={"count": "not_a_number"})

        assert "count" in str(exc_info.value)


class TestRecipeRunnerPythonExecution:
    """测试 Python Recipe 执行"""

    def test_run_python_success(self, runner_with_mock_registry, mock_registry):
        """测试成功执行 Python Recipe"""
        # 创建临时 Python 脚本
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""#!/usr/bin/env python3
import json
import sys
params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
print(json.dumps({"result": "success", "input": params}))
""")
            script_path = Path(f.name)

        try:
            metadata = RecipeMetadata(
                name="test_python",
                type="atomic",
                runtime="python",
                description="Test",
                use_cases=["test"],
                output_targets=["stdout"],
                inputs={},
                outputs={},
                dependencies=[],
                version="1.0.0"
            )

            recipe = Recipe(
                
                metadata=metadata,
                script_path=script_path,
                metadata_path=Path("/tmp/test.md"),
                source="User"
            )

            mock_registry.find.return_value = recipe

            # 执行 Recipe
            result = runner_with_mock_registry.run("test_python", params={"test": "value"})

            # 验证结果
            assert result["success"] is True
            assert result["data"]["result"] == "success"
            assert result["data"]["input"]["test"] == "value"
            assert result["recipe_name"] == "test_python"
            assert result["runtime"] == "python"
            assert "execution_time" in result

        finally:
            script_path.unlink()

    def test_run_python_with_error_exit_code(self, runner_with_mock_registry, mock_registry):
        """测试 Python Recipe 执行失败（非零退出码）"""
        # 创建会失败的 Python 脚本
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""#!/usr/bin/env python3
import sys
sys.exit(1)
""")
            script_path = Path(f.name)

        try:
            metadata = RecipeMetadata(
                name="test_python_fail",
                type="atomic",
                runtime="python",
                description="Test",
                use_cases=["test"],
                output_targets=["stdout"],
                inputs={},
                outputs={},
                dependencies=[],
                version="1.0.0"
            )

            recipe = Recipe(
                
                metadata=metadata,
                script_path=script_path,
                metadata_path=Path("/tmp/test.md"),
                source="User"
            )

            mock_registry.find.return_value = recipe

            # 执行应该抛出 RecipeExecutionError
            with pytest.raises(RecipeExecutionError) as exc_info:
                runner_with_mock_registry.run("test_python_fail")

            assert exc_info.value.exit_code == 1
            assert exc_info.value.runtime == "python"

        finally:
            script_path.unlink()

    def test_run_python_with_invalid_json_output(self, runner_with_mock_registry, mock_registry):
        """测试 Python Recipe 输出无效 JSON"""
        # 创建输出无效 JSON 的脚本
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""#!/usr/bin/env python3
print("This is not valid JSON")
""")
            script_path = Path(f.name)

        try:
            metadata = RecipeMetadata(
                name="test_invalid_json",
                type="atomic",
                runtime="python",
                description="Test",
                use_cases=["test"],
                output_targets=["stdout"],
                inputs={},
                outputs={},
                dependencies=[],
                version="1.0.0"
            )

            recipe = Recipe(
                
                metadata=metadata,
                script_path=script_path,
                metadata_path=Path("/tmp/test.md"),
                source="User"
            )

            mock_registry.find.return_value = recipe

            # 执行应该抛出 RecipeExecutionError
            with pytest.raises(RecipeExecutionError) as exc_info:
                runner_with_mock_registry.run("test_invalid_json")

            assert "JSON 解析失败" in exc_info.value.stderr

        finally:
            script_path.unlink()


class TestRecipeRunnerShellExecution:
    """测试 Shell Recipe 执行"""

    def test_run_shell_success(self, runner_with_mock_registry, mock_registry):
        """测试成功执行 Shell Recipe"""
        # 创建临时 Shell 脚本
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("""#!/bin/bash
echo '{"result": "success"}'
""")
            script_path = Path(f.name)

        # 添加执行权限
        script_path.chmod(0o755)

        try:
            metadata = RecipeMetadata(
                name="test_shell",
                type="atomic",
                runtime="shell",
                description="Test",
                use_cases=["test"],
                output_targets=["stdout"],
                inputs={},
                outputs={},
                dependencies=[],
                version="1.0.0"
            )

            recipe = Recipe(
                
                metadata=metadata,
                script_path=script_path,
                metadata_path=Path("/tmp/test.md"),
                source="User"
            )

            mock_registry.find.return_value = recipe

            # 执行 Recipe
            result = runner_with_mock_registry.run("test_shell")

            # 验证结果
            assert result["success"] is True
            assert result["data"]["result"] == "success"
            assert result["runtime"] == "shell"

        finally:
            script_path.unlink()

    def test_run_shell_without_execute_permission(self, runner_with_mock_registry, mock_registry):
        """测试执行没有执行权限的 Shell 脚本"""
        # 创建没有执行权限的脚本
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("""#!/bin/bash
echo '{"result": "success"}'
""")
            script_path = Path(f.name)

        # 移除执行权限
        script_path.chmod(0o644)

        try:
            metadata = RecipeMetadata(
                name="test_shell_no_exec",
                type="atomic",
                runtime="shell",
                description="Test",
                use_cases=["test"],
                output_targets=["stdout"],
                inputs={},
                outputs={},
                dependencies=[],
                version="1.0.0"
            )

            recipe = Recipe(
                
                metadata=metadata,
                script_path=script_path,
                metadata_path=Path("/tmp/test.md"),
                source="User"
            )

            mock_registry.find.return_value = recipe

            # 执行应该抛出错误
            with pytest.raises(RecipeExecutionError) as exc_info:
                runner_with_mock_registry.run("test_shell_no_exec")

            assert "脚本没有执行权限" in exc_info.value.stderr

        finally:
            script_path.unlink()


class TestRecipeRunnerOutputSizeLimit:
    """测试输出大小限制"""

    @patch('subprocess.run')
    def test_output_size_limit_python(self, mock_run, runner_with_mock_registry, mock_registry):
        """测试 Python Recipe 输出大小限制（10MB）"""
        # 创建超过10MB的输出
        large_output = "x" * (11 * 1024 * 1024)  # 11MB

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = large_output
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        metadata = RecipeMetadata(
            name="test_large_output",
            type="atomic",
            runtime="python",
            description="Test",
            use_cases=["test"],
            output_targets=["stdout"],
            inputs={},
            outputs={},
            dependencies=[],
            version="1.0.0"
        )

        recipe = Recipe(
            
            metadata=metadata,
            script_path=Path("/tmp/test.py"),
            metadata_path=Path("/tmp/test.md"),
            source="User"
        )

        mock_registry.find.return_value = recipe

        # 执行应该抛出错误
        with pytest.raises(RecipeExecutionError) as exc_info:
            runner_with_mock_registry.run("test_large_output")

        assert "Recipe 输出过大" in exc_info.value.stderr
        assert "限制: 10MB" in exc_info.value.stderr


class TestRecipeRunnerTimeout:
    """测试超时机制"""

    @patch('subprocess.run')
    def test_timeout_python(self, mock_run, runner_with_mock_registry, mock_registry):
        """测试 Python Recipe 超时（5分钟）"""
        # 模拟超时
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=300)

        metadata = RecipeMetadata(
            name="test_timeout",
            type="atomic",
            runtime="python",
            description="Test",
            use_cases=["test"],
            output_targets=["stdout"],
            inputs={},
            outputs={},
            dependencies=[],
            version="1.0.0"
        )

        recipe = Recipe(
            
            metadata=metadata,
            script_path=Path("/tmp/test.py"),
            metadata_path=Path("/tmp/test.md"),
            source="User"
        )

        mock_registry.find.return_value = recipe

        # 执行应该抛出错误
        with pytest.raises(RecipeExecutionError) as exc_info:
            runner_with_mock_registry.run("test_timeout")

        assert "执行超时（5分钟）" in exc_info.value.stderr


class TestRecipeRunnerUnsupportedRuntime:
    """测试不支持的运行时"""

    def test_unsupported_runtime(self, runner_with_mock_registry, mock_registry):
        """测试不支持的运行时类型"""
        metadata = RecipeMetadata(
            name="test_unsupported",
            type="atomic",
            runtime="ruby",  # 不支持的运行时
            description="Test",
            use_cases=["test"],
            output_targets=["stdout"],
            inputs={},
            outputs={},
            dependencies=[],
            version="1.0.0"
        )

        recipe = Recipe(
            
            metadata=metadata,
            script_path=Path("/tmp/test.rb"),
            metadata_path=Path("/tmp/test.md"),
            source="User"
        )

        mock_registry.find.return_value = recipe

        # 执行应该抛出错误
        with pytest.raises(RecipeExecutionError) as exc_info:
            runner_with_mock_registry.run("test_unsupported")

        assert "不支持的运行时类型: ruby" in exc_info.value.stderr
