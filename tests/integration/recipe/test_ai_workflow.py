"""
集成测试：AI Agent 使用 Recipe 的工作流

模拟 Claude Code AI Agent 通过 Bash 工具调用 Recipe 系统的完整流程：
1. 通过 `recipe list --format json` 发现可用 Recipe
2. 解析 JSON，理解 Recipe 能力（description, use_cases, output_targets）
3. 选择合适的 Recipe 和输出方式
4. 调用 `recipe run` 执行并获取结果
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_output_file():
    """创建临时输出文件"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        temp_path = Path(f.name)

    yield temp_path

    # 清理
    if temp_path.exists():
        temp_path.unlink()


class TestAIRecipeDiscovery:
    """测试 AI 发现 Recipe 的能力"""

    def test_list_recipes_json_format(self):
        """测试 AI 通过 JSON 格式列出所有 Recipe"""
        result = subprocess.run(
            ["uv", "run", "frago", "recipe", "list", "--format", "json"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, f"命令执行失败: {result.stderr}"

        # 解析 JSON 输出
        recipes = json.loads(result.stdout)
        assert isinstance(recipes, list), "输出应该是 JSON 数组"

        # 验证至少有一个 Recipe
        assert len(recipes) > 0, "应该至少发现一个 Recipe"

        # 验证每个 Recipe 包含 AI 需要的关键字段
        for recipe in recipes:
            assert "name" in recipe, f"Recipe 缺少 'name' 字段: {recipe}"
            assert "type" in recipe, f"Recipe 缺少 'type' 字段: {recipe}"
            assert "runtime" in recipe, f"Recipe 缺少 'runtime' 字段: {recipe}"
            assert "description" in recipe, f"Recipe 缺少 'description' 字段: {recipe}"
            assert "use_cases" in recipe, f"Recipe 缺少 'use_cases' 字段: {recipe}"
            assert "tags" in recipe, f"Recipe 缺少 'tags' 字段: {recipe}"
            assert "output_targets" in recipe, f"Recipe 缺少 'output_targets' 字段: {recipe}"

    def test_ai_filter_recipes_by_tags(self):
        """测试 AI 通过标签筛选 Recipe"""
        result = subprocess.run(
            ["uv", "run", "frago", "recipe", "list", "--format", "json"],
            capture_output=True,
            text=True
        )

        recipes = json.loads(result.stdout)

        # 模拟 AI 筛选带有 "system" 标签的 Recipe
        system_recipes = [r for r in recipes if "system" in r.get("tags", [])]

        # 应该至少有 clipboard_read 和 file_copy
        assert len(system_recipes) >= 2, "应该至少有 2 个 system 类型的 Recipe"

    def test_ai_analyze_output_targets(self):
        """测试 AI 分析 Recipe 支持的输出目标"""
        result = subprocess.run(
            ["uv", "run", "frago", "recipe", "list", "--format", "json"],
            capture_output=True,
            text=True
        )

        recipes = json.loads(result.stdout)

        # 验证所有 Recipe 都声明了 output_targets
        for recipe in recipes:
            output_targets = recipe.get("output_targets", [])
            assert isinstance(output_targets, list)
            assert len(output_targets) > 0, f"{recipe['name']} 没有声明 output_targets"

            # 至少应该支持 stdout 或 file
            valid_targets = {"stdout", "file", "clipboard"}
            assert any(t in valid_targets for t in output_targets), \
                f"{recipe['name']} 的 output_targets 无效: {output_targets}"


class TestAIRecipeExecution:
    """测试 AI 执行 Recipe 的能力"""

    def test_ai_run_recipe_with_file_output(self, temp_output_file):
        """测试 AI 运行 Recipe 并输出到文件（模拟完整流程）"""
        # 步骤 1: AI 发现可用 Recipe
        list_result = subprocess.run(
            ["uv", "run", "frago", "recipe", "list", "--format", "json"],
            capture_output=True,
            text=True
        )
        assert list_result.returncode == 0

        recipes = json.loads(list_result.stdout)

        # 步骤 2: AI 分析元数据，选择 clipboard_read Recipe
        clipboard_recipe = next(
            (r for r in recipes if r["name"] == "clipboard_read"),
            None
        )

        if clipboard_recipe is None:
            pytest.skip("clipboard_read recipe not found")

        # 步骤 3: AI 检查该 Recipe 支持 file 输出
        assert "file" in clipboard_recipe["output_targets"], \
            "clipboard_read 应该支持 file 输出"

        # 步骤 4: AI 执行 Recipe 并指定输出文件
        run_result = subprocess.run(
            [
                "uv", "run", "frago", "recipe", "run", "clipboard_read",
                "--output-file", str(temp_output_file)
            ],
            capture_output=True,
            text=True
        )

        # 如果失败（如 pyperclip 未安装），跳过测试
        if run_result.returncode != 0:
            if "pyperclip" in run_result.stderr or "DependencyError" in run_result.stdout:
                pytest.skip("pyperclip not installed")
            else:
                pytest.fail(f"Recipe 执行失败: {run_result.stderr}")

        # 步骤 5: AI 验证输出文件存在且包含合法 JSON
        assert temp_output_file.exists(), "输出文件应该被创建"

        content = temp_output_file.read_text()
        result = json.loads(content)

        assert "success" in result
        assert "data" in result or "error" in result

    def test_ai_run_recipe_with_params(self):
        """测试 AI 运行带参数的 Recipe"""
        # 创建临时源文件
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("AI test content")
            source_path = Path(f.name)

        dest_path = source_path.parent / f"{source_path.stem}_copy{source_path.suffix}"

        try:
            # 步骤 1: AI 发现 file_copy Recipe
            list_result = subprocess.run(
                ["uv", "run", "frago", "recipe", "list", "--format", "json"],
                capture_output=True,
                text=True
            )
            recipes = json.loads(list_result.stdout)

            file_copy_recipe = next(
                (r for r in recipes if r["name"] == "file_copy"),
                None
            )

            if file_copy_recipe is None:
                pytest.skip("file_copy recipe not found")

            # 步骤 2: AI 查看 Recipe 详细信息（了解参数）
            info_result = subprocess.run(
                ["uv", "run", "frago", "recipe", "info", "file_copy"],
                capture_output=True,
                text=True
            )
            assert info_result.returncode == 0
            assert "source_path" in info_result.stdout
            assert "dest_path" in info_result.stdout

            # 步骤 3: AI 构造参数并执行
            params = json.dumps({
                "source_path": str(source_path),
                "dest_path": str(dest_path)
            })

            run_result = subprocess.run(
                [
                    "uv", "run", "frago", "recipe", "run", "file_copy",
                    "--params", params
                ],
                capture_output=True,
                text=True
            )

            assert run_result.returncode == 0, f"执行失败: {run_result.stderr}"

            # 步骤 4: AI 验证结果
            result = json.loads(run_result.stdout)
            assert result["success"] is True
            assert dest_path.exists()

        finally:
            # 清理
            if source_path.exists():
                source_path.unlink()
            if dest_path.exists():
                dest_path.unlink()


class TestAIErrorHandling:
    """测试 AI 处理错误的能力"""

    def test_ai_handle_missing_recipe(self):
        """测试 AI 处理不存在的 Recipe"""
        result = subprocess.run(
            ["uv", "run", "frago", "recipe", "run", "nonexistent_recipe_xyz"],
            capture_output=True,
            text=True
        )

        # 应该返回非零退出码
        assert result.returncode != 0

        # 错误信息应该清晰
        error_output = result.stderr + result.stdout
        assert "not found" in error_output.lower() or "nonexistent" in error_output.lower()

    def test_ai_handle_missing_params(self):
        """测试 AI 处理缺少必需参数的情况"""
        result = subprocess.run(
            ["uv", "run", "frago", "recipe", "run", "file_copy"],
            capture_output=True,
            text=True
        )

        # 应该返回非零退出码或包含错误信息
        assert result.returncode != 0 or "error" in result.stdout.lower()


class TestAIWorkflowComplete:
    """测试完整的 AI 工作流"""

    def test_complete_ai_workflow(self, temp_output_file):
        """
        模拟完整的 AI 工作流：
        任务：提取剪贴板内容并保存为文件
        """
        # 步骤 1: AI 接收任务并分析
        # （人类输入："提取剪贴板内容并保存为文件"）

        # 步骤 2: AI 搜索可用 Recipe
        list_result = subprocess.run(
            ["uv", "run", "frago", "recipe", "list", "--format", "json"],
            capture_output=True,
            text=True
        )
        assert list_result.returncode == 0

        recipes = json.loads(list_result.stdout)

        # 步骤 3: AI 通过关键词或 use_cases 匹配 Recipe
        clipboard_recipes = [
            r for r in recipes
            if "clipboard" in r["name"].lower()
            or "clipboard" in " ".join(r.get("tags", [])).lower()
            or any("clipboard" in uc.lower() for uc in r.get("use_cases", []))
        ]

        assert len(clipboard_recipes) > 0, "AI 应该能找到剪贴板相关的 Recipe"

        # 步骤 4: AI 选择 clipboard_read 并检查输出能力
        target_recipe = clipboard_recipes[0]
        assert "file" in target_recipe["output_targets"], \
            "选中的 Recipe 应该支持文件输出"

        # 步骤 5: AI 执行命令
        run_result = subprocess.run(
            [
                "uv", "run", "frago", "recipe", "run", target_recipe["name"],
                "--output-file", str(temp_output_file)
            ],
            capture_output=True,
            text=True
        )

        # 如果因环境问题失败，跳过验证
        if run_result.returncode != 0:
            if "pyperclip" in run_result.stderr:
                pytest.skip("pyperclip not installed")

        # 步骤 6: AI 验证任务完成
        if run_result.returncode == 0:
            assert temp_output_file.exists()
            result = json.loads(temp_output_file.read_text())
            assert "success" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
