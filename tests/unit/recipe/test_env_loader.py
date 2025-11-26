"""测试环境变量加载器"""
import os
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from frago.recipes.env_loader import EnvLoader, WorkflowContext


class TestEnvLoader:
    """EnvLoader 测试"""

    def test_load_env_file_basic(self, tmp_path):
        """测试基本的 .env 文件解析"""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")

        loader = EnvLoader()
        result = loader.load_env_file(env_file)

        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_load_env_file_with_quotes(self, tmp_path):
        """测试带引号的值"""
        env_file = tmp_path / ".env"
        env_file.write_text('KEY1="value with spaces"\nKEY2=\'single quotes\'\n')

        loader = EnvLoader()
        result = loader.load_env_file(env_file)

        assert result == {"KEY1": "value with spaces", "KEY2": "single quotes"}

    def test_load_env_file_with_comments(self, tmp_path):
        """测试带注释的文件"""
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nKEY1=value1\n# Another comment\n\nKEY2=value2\n")

        loader = EnvLoader()
        result = loader.load_env_file(env_file)

        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_load_env_file_not_exists(self, tmp_path):
        """测试文件不存在的情况"""
        env_file = tmp_path / "nonexistent.env"

        loader = EnvLoader()
        result = loader.load_env_file(env_file)

        assert result == {}

    def test_load_all_merges_correctly(self, tmp_path, monkeypatch):
        """测试多级配置合并"""
        # 设置系统环境变量
        monkeypatch.setenv("SYS_VAR", "from_system")
        monkeypatch.setenv("OVERRIDE_VAR", "system_value")

        # 创建用户级配置
        user_env_dir = tmp_path / "user" / ".frago"
        user_env_dir.mkdir(parents=True)
        user_env_file = user_env_dir / ".env"
        user_env_file.write_text("USER_VAR=from_user\nOVERRIDE_VAR=user_value\n")

        # 创建项目级配置
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_env_dir = project_dir / ".frago"
        project_env_dir.mkdir()
        project_env_file = project_env_dir / ".env"
        project_env_file.write_text("PROJECT_VAR=from_project\nOVERRIDE_VAR=project_value\n")

        # Patch 路径
        monkeypatch.setattr(EnvLoader, "USER_ENV_PATH", user_env_file)

        loader = EnvLoader(project_root=project_dir)
        result = loader.load_all()

        # 验证合并结果
        assert result["SYS_VAR"] == "from_system"
        assert result["USER_VAR"] == "from_user"
        assert result["PROJECT_VAR"] == "from_project"
        # 项目级覆盖用户级和系统级
        assert result["OVERRIDE_VAR"] == "project_value"

    def test_resolve_for_recipe_applies_defaults(self, monkeypatch):
        """测试默认值应用"""
        # 清除可能干扰的环境变量
        monkeypatch.delenv("MY_API_KEY", raising=False)
        monkeypatch.delenv("MY_MODEL", raising=False)

        loader = EnvLoader()

        env_definitions = {
            "MY_API_KEY": {"required": False, "default": "default_key"},
            "MY_MODEL": {"required": False, "default": "gpt-4"},
        }

        result = loader.resolve_for_recipe(env_definitions)

        assert result["MY_API_KEY"] == "default_key"
        assert result["MY_MODEL"] == "gpt-4"

    def test_resolve_for_recipe_missing_required(self, monkeypatch):
        """测试缺少必需变量时抛出异常"""
        monkeypatch.delenv("REQUIRED_VAR", raising=False)

        loader = EnvLoader()

        env_definitions = {
            "REQUIRED_VAR": {"required": True, "description": "必需的API密钥"},
        }

        with pytest.raises(ValueError) as exc_info:
            loader.resolve_for_recipe(env_definitions)

        assert "REQUIRED_VAR" in str(exc_info.value)

    def test_resolve_for_recipe_cli_overrides(self, monkeypatch):
        """测试 CLI 覆盖"""
        monkeypatch.setenv("MY_VAR", "from_system")

        loader = EnvLoader()

        env_definitions = {
            "MY_VAR": {"required": False},
        }

        result = loader.resolve_for_recipe(
            env_definitions,
            cli_overrides={"MY_VAR": "from_cli"}
        )

        assert result["MY_VAR"] == "from_cli"

    def test_resolve_for_recipe_workflow_context(self, monkeypatch):
        """测试 Workflow 上下文共享"""
        monkeypatch.setenv("MY_VAR", "from_system")

        loader = EnvLoader()
        context = WorkflowContext()
        context.set("MY_VAR", "from_workflow")

        env_definitions = {
            "MY_VAR": {"required": False},
        }

        result = loader.resolve_for_recipe(
            env_definitions,
            workflow_context=context
        )

        assert result["MY_VAR"] == "from_workflow"

    def test_resolve_inherits_system_env(self, monkeypatch):
        """测试完整继承系统环境变量"""
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/test")

        loader = EnvLoader()
        result = loader.resolve_for_recipe({})

        # 应该继承系统环境变量
        assert "PATH" in result
        assert "HOME" in result


class TestWorkflowContext:
    """WorkflowContext 测试"""

    def test_set_and_get(self):
        """测试设置和获取变量"""
        ctx = WorkflowContext()
        ctx.set("KEY1", "value1")

        assert ctx.get("KEY1") == "value1"
        assert ctx.get("NONEXISTENT") is None
        assert ctx.get("NONEXISTENT", "default") == "default"

    def test_update(self):
        """测试批量更新"""
        ctx = WorkflowContext()
        ctx.update({"KEY1": "value1", "KEY2": "value2"})

        assert ctx.get("KEY1") == "value1"
        assert ctx.get("KEY2") == "value2"

    def test_as_dict(self):
        """测试导出为字典"""
        ctx = WorkflowContext()
        ctx.set("KEY1", "value1")
        ctx.set("KEY2", "value2")

        result = ctx.as_dict()

        assert result == {"KEY1": "value1", "KEY2": "value2"}
        # 确保返回的是副本
        result["KEY3"] = "value3"
        assert ctx.get("KEY3") is None
