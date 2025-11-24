"""
集成测试：Recipe 执行功能

测试三种运行时（chrome-js、python、shell）的 Recipe 执行、
参数传递、JSON 输出、错误处理。
"""

import json
import tempfile
from pathlib import Path

import pytest

from frago.recipes.runner import RecipeRunner
from frago.recipes.registry import RecipeRegistry
from frago.recipes.exceptions import RecipeExecutionError, RecipeNotFoundError


@pytest.fixture
def recipe_runner():
    """创建 RecipeRunner 实例"""
    registry = RecipeRegistry()
    registry.scan()
    return RecipeRunner(registry)


@pytest.fixture
def temp_test_file():
    """创建临时测试文件"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("test content")
        temp_path = Path(f.name)

    yield temp_path

    # 清理
    if temp_path.exists():
        temp_path.unlink()


class TestPythonRecipeExecution:
    """测试 Python Runtime Recipe 执行"""

    def test_clipboard_read_success(self, recipe_runner):
        """测试剪贴板读取 Recipe（可能因环境原因失败）"""
        try:
            result = recipe_runner.run("clipboard_read")

            # 验证返回格式
            assert isinstance(result, dict)
            assert "success" in result
            assert "data" in result or "error" in result

            if result["success"]:
                assert "content" in result["data"]
                assert "length" in result["data"]
                assert isinstance(result["data"]["length"], int)
        except RecipeNotFoundError:
            pytest.skip("clipboard_read recipe not found in registry")
        except RecipeExecutionError as e:
            # 如果是 pyperclip 未安装，跳过测试
            if "pyperclip" in str(e) or "DependencyError" in str(e):
                pytest.skip("pyperclip not installed, skipping clipboard test")
            raise

    def test_python_recipe_json_output(self, recipe_runner):
        """测试 Python Recipe 返回合法 JSON"""
        try:
            result = recipe_runner.run("clipboard_read")

            # 确保返回值可序列化为 JSON
            json_str = json.dumps(result)
            parsed = json.loads(json_str)
            assert parsed == result
        except (RecipeNotFoundError, RecipeExecutionError):
            pytest.skip("clipboard_read recipe not available")


class TestShellRecipeExecution:
    """测试 Shell Runtime Recipe 执行"""

    def test_file_copy_success(self, recipe_runner, temp_test_file):
        """测试文件复制 Recipe"""
        dest_path = temp_test_file.parent / f"{temp_test_file.stem}_copy{temp_test_file.suffix}"

        try:
            params = {
                "source_path": str(temp_test_file),
                "dest_path": str(dest_path)
            }

            result = recipe_runner.run("file_copy", params)

            # 验证返回格式
            assert result["success"] is True
            assert "data" in result
            assert result["data"]["source"] == str(temp_test_file)
            assert result["data"]["destination"] == str(dest_path)
            assert "size_bytes" in result["data"]
            assert result["data"]["operation"] == "copy"

            # 验证文件确实被复制
            assert dest_path.exists()
            assert dest_path.read_text() == "test content"

        finally:
            # 清理复制的文件
            if dest_path.exists():
                dest_path.unlink()

    def test_file_copy_missing_params(self, recipe_runner):
        """测试缺少必需参数时的错误处理"""
        from frago.recipes.exceptions import RecipeValidationError

        # 应该抛出 RecipeValidationError
        with pytest.raises(RecipeValidationError) as exc_info:
            recipe_runner.run("file_copy", {})

        # 验证错误信息
        assert "source_path" in str(exc_info.value)
        assert "dest_path" in str(exc_info.value)

    def test_file_copy_nonexistent_source(self, recipe_runner):
        """测试源文件不存在时的错误处理"""
        params = {
            "source_path": "/nonexistent/source.txt",
            "dest_path": "/tmp/dest.txt"
        }

        try:
            result = recipe_runner.run("file_copy", params)

            # 应该返回失败结果
            assert result["success"] is False
            assert "error" in result
            assert "FileNotFoundError" in result["error"]["type"]
        except RecipeExecutionError:
            # 如果抛出异常也是可接受的
            pass

    def test_shell_recipe_json_output(self, recipe_runner, temp_test_file):
        """测试 Shell Recipe 返回合法 JSON"""
        dest_path = temp_test_file.parent / f"{temp_test_file.stem}_json_test{temp_test_file.suffix}"

        try:
            params = {
                "source_path": str(temp_test_file),
                "dest_path": str(dest_path)
            }

            result = recipe_runner.run("file_copy", params)

            # 确保返回值可序列化为 JSON
            json_str = json.dumps(result)
            parsed = json.loads(json_str)
            assert parsed == result

        finally:
            if dest_path.exists():
                dest_path.unlink()


class TestRecipeNotFound:
    """测试 Recipe 不存在的情况"""

    def test_run_nonexistent_recipe(self, recipe_runner):
        """测试运行不存在的 Recipe"""
        with pytest.raises(RecipeNotFoundError):
            recipe_runner.run("nonexistent_recipe_xyz")


class TestParameterPassing:
    """测试参数传递机制"""

    def test_params_as_dict(self, recipe_runner, temp_test_file):
        """测试以字典形式传递参数"""
        dest_path = temp_test_file.parent / "params_dict_test.txt"

        try:
            params = {
                "source_path": str(temp_test_file),
                "dest_path": str(dest_path)
            }

            result = recipe_runner.run("file_copy", params)
            assert result["success"] is True

        finally:
            if dest_path.exists():
                dest_path.unlink()

    def test_empty_params(self, recipe_runner):
        """测试空参数"""
        try:
            # clipboard_read 不需要参数
            result = recipe_runner.run("clipboard_read", {})
            assert "success" in result
        except (RecipeNotFoundError, RecipeExecutionError):
            pytest.skip("clipboard_read recipe not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
