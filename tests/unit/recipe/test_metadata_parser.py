"""
单元测试：元数据解析和验证

测试 YAML frontmatter 解析、必需字段验证、AI 字段验证、
参数验证和类型检查。
"""

import tempfile
from pathlib import Path

import pytest

from frago.recipes.metadata import (
    RecipeMetadata,
    parse_metadata_file,
    validate_metadata,
    validate_params,
    check_param_type,
)
from frago.recipes.exceptions import MetadataParseError, RecipeValidationError


class TestYAMLFrontmatterParsing:
    """测试 YAML frontmatter 解析"""

    def test_parse_valid_metadata(self):
        """测试解析有效的元数据文件"""
        content = """---
name: test_recipe
type: atomic
runtime: python
version: "1.0"
description: "测试 Recipe"
use_cases:
  - "测试用例1"
  - "测试用例2"
output_targets:
  - stdout
  - file
tags:
  - test
inputs:
  param1:
    type: string
    required: true
    description: "参数1"
outputs:
  result:
    type: string
    description: "结果"
dependencies: []
---

# 测试 Recipe 文档
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            metadata = parse_metadata_file(temp_path)

            # 验证基本字段
            assert metadata.name == "test_recipe"
            assert metadata.type == "atomic"
            assert metadata.runtime == "python"
            assert metadata.version == "1.0"
            assert metadata.description == "测试 Recipe"

            # 验证 AI 字段
            assert len(metadata.use_cases) == 2
            assert "测试用例1" in metadata.use_cases
            assert len(metadata.output_targets) == 2
            assert "stdout" in metadata.output_targets
            assert len(metadata.tags) == 1

            # 验证输入输出
            assert "param1" in metadata.inputs
            assert metadata.inputs["param1"]["type"] == "string"
            assert metadata.inputs["param1"]["required"] is True
            assert "result" in metadata.outputs

        finally:
            temp_path.unlink()

    def test_parse_missing_frontmatter(self):
        """测试缺少 YAML frontmatter 的文件"""
        content = "# 没有 frontmatter 的文件"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            with pytest.raises(MetadataParseError) as exc_info:
                parse_metadata_file(temp_path)

            assert "缺少 YAML frontmatter" in str(exc_info.value)
        finally:
            temp_path.unlink()

    def test_parse_invalid_yaml(self):
        """测试无效的 YAML 格式"""
        content = """---
name: test
invalid yaml: [unclosed
---
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            with pytest.raises(MetadataParseError) as exc_info:
                parse_metadata_file(temp_path)

            assert "YAML 解析失败" in str(exc_info.value)
        finally:
            temp_path.unlink()

    def test_parse_missing_required_fields(self):
        """测试缺少必需字段"""
        content = """---
name: test_recipe
type: atomic
# 缺少 runtime, version, description 等字段
---
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            with pytest.raises(MetadataParseError) as exc_info:
                parse_metadata_file(temp_path)

            assert "缺少必需字段" in str(exc_info.value)
        finally:
            temp_path.unlink()


class TestMetadataValidation:
    """测试元数据验证"""

    def test_validate_valid_metadata(self):
        """测试验证有效的元数据"""
        metadata = RecipeMetadata(
            name="test_recipe",
            type="atomic",
            runtime="python",
            version="1.0",
            description="测试 Recipe",
            use_cases=["测试"],
            output_targets=["stdout"],
            tags=["test"],
            inputs={
                "param1": {
                    "type": "string",
                    "required": True,
                    "description": "参数1"
                }
            },
            outputs={"result": {"type": "string"}},
            dependencies=[]
        )

        # 应该不抛出异常
        validate_metadata(metadata)

    def test_validate_invalid_type(self):
        """测试无效的 type 字段"""
        metadata = RecipeMetadata(
            name="test",
            type="invalid_type",  # 无效类型
            runtime="python",
            version="1.0",
            description="测试",
            use_cases=["测试"],
            output_targets=["stdout"]
        )

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_metadata(metadata)

        assert "type 必须是" in str(exc_info.value)

    def test_validate_invalid_runtime(self):
        """测试无效的 runtime 字段"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="invalid_runtime",  # 无效运行时
            version="1.0",
            description="测试",
            use_cases=["测试"],
            output_targets=["stdout"]
        )

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_metadata(metadata)

        assert "runtime 必须是" in str(exc_info.value)

    def test_validate_invalid_version_format(self):
        """测试无效的版本号格式"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="python",
            version="invalid",  # 无效版本
            description="测试",
            use_cases=["测试"],
            output_targets=["stdout"]
        )

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_metadata(metadata)

        assert "version 格式无效" in str(exc_info.value)

    def test_validate_missing_ai_fields(self):
        """测试缺少 AI 字段"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="python",
            version="1.0",
            description="",  # 空描述
            use_cases=[],  # 空用例
            output_targets=[]  # 空输出目标
        )

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_metadata(metadata)

        errors = str(exc_info.value)
        assert "description" in errors
        assert "use_cases" in errors
        assert "output_targets" in errors

    def test_validate_invalid_output_target(self):
        """测试无效的输出目标"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="python",
            version="1.0",
            description="测试",
            use_cases=["测试"],
            output_targets=["invalid_target"]  # 无效目标
        )

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_metadata(metadata)

        assert "output_targets 包含无效值" in str(exc_info.value)


class TestParamValidation:
    """测试参数验证"""

    def test_validate_params_with_all_required(self):
        """测试所有必需参数都提供"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="python",
            version="1.0",
            description="测试",
            use_cases=["测试"],
            output_targets=["stdout"],
            inputs={
                "param1": {"type": "string", "required": True},
                "param2": {"type": "number", "required": False}
            }
        )

        params = {"param1": "value1"}

        # 应该不抛出异常
        validate_params(metadata, params)

    def test_validate_params_missing_required(self):
        """测试缺少必需参数"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="python",
            version="1.0",
            description="测试",
            use_cases=["测试"],
            output_targets=["stdout"],
            inputs={
                "param1": {"type": "string", "required": True, "description": "参数1说明"}
            }
        )

        params = {}  # 缺少 param1

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_params(metadata, params)

        error_msg = str(exc_info.value)
        assert "缺少必需参数" in error_msg
        assert "param1" in error_msg
        assert "参数1说明" in error_msg  # 包含描述

    def test_validate_params_type_checking(self):
        """测试参数类型检查"""
        metadata = RecipeMetadata(
            name="test",
            type="atomic",
            runtime="python",
            version="1.0",
            description="测试",
            use_cases=["测试"],
            output_targets=["stdout"],
            inputs={
                "param1": {"type": "string", "required": True},
                "param2": {"type": "number", "required": False}
            }
        )

        # 类型错误的参数
        params = {"param1": 123}  # 应该是 string

        with pytest.raises(RecipeValidationError) as exc_info:
            validate_params(metadata, params)

        assert "类型错误" in str(exc_info.value)


class TestParamTypeChecking:
    """测试参数类型检查"""

    def test_check_string_type(self):
        """测试字符串类型检查"""
        # 正确类型
        errors = check_param_type("param", "test", "string")
        assert len(errors) == 0

        # 错误类型
        errors = check_param_type("param", 123, "string")
        assert len(errors) == 1
        assert "类型错误" in errors[0]

    def test_check_number_type(self):
        """测试数字类型检查"""
        # 整数
        errors = check_param_type("param", 123, "number")
        assert len(errors) == 0

        # 浮点数
        errors = check_param_type("param", 12.3, "number")
        assert len(errors) == 0

        # 布尔值不是数字
        errors = check_param_type("param", True, "number")
        assert len(errors) == 1

        # 字符串不是数字
        errors = check_param_type("param", "123", "number")
        assert len(errors) == 1

    def test_check_boolean_type(self):
        """测试布尔类型检查"""
        # 正确类型
        errors = check_param_type("param", True, "boolean")
        assert len(errors) == 0

        errors = check_param_type("param", False, "boolean")
        assert len(errors) == 0

        # 错误类型
        errors = check_param_type("param", 1, "boolean")
        assert len(errors) == 1

    def test_check_array_type(self):
        """测试数组类型检查"""
        # 正确类型
        errors = check_param_type("param", [1, 2, 3], "array")
        assert len(errors) == 0

        # 错误类型
        errors = check_param_type("param", "not an array", "array")
        assert len(errors) == 1

    def test_check_object_type(self):
        """测试对象类型检查"""
        # 正确类型
        errors = check_param_type("param", {"key": "value"}, "object")
        assert len(errors) == 0

        # 错误类型
        errors = check_param_type("param", "not an object", "object")
        assert len(errors) == 1

    def test_check_unknown_type(self):
        """测试未知类型（跳过检查）"""
        # 未知类型不报错
        errors = check_param_type("param", "anything", "unknown_type")
        assert len(errors) == 0
