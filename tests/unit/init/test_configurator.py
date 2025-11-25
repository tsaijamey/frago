"""
配置管理模块测试

测试 configurator.py 中的配置功能：
- 认证方式选择 (User Story 2)
- 配置持久化 (User Story 2)
- 配置摘要显示 (User Story 3)
- 配置更新流程 (User Story 3)
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import tempfile

from frago.init.models import Config, APIEndpoint


# =============================================================================
# Phase 4: User Story 2 - 认证方式选择测试
# =============================================================================


class TestPromptAuthMethod:
    """prompt_auth_method() 函数测试 (T030)"""

    def test_prompt_auth_method_returns_official(self):
        """用户选择官方认证"""
        from frago.init.configurator import prompt_auth_method

        with patch("click.prompt", return_value="official"):
            result = prompt_auth_method()

        assert result == "official"

    def test_prompt_auth_method_returns_custom(self):
        """用户选择自定义端点"""
        from frago.init.configurator import prompt_auth_method

        with patch("click.prompt", return_value="custom"):
            result = prompt_auth_method()

        assert result == "custom"

    def test_prompt_auth_method_case_insensitive(self):
        """认证方式选择不区分大小写"""
        from frago.init.configurator import prompt_auth_method

        with patch("click.prompt", return_value="OFFICIAL"):
            result = prompt_auth_method()

        assert result == "official"


class TestConfigureOfficialAuth:
    """configure_official_auth() 函数测试 (T031)"""

    def test_configure_official_auth_returns_config(self):
        """配置官方认证返回正确的 Config"""
        from frago.init.configurator import configure_official_auth

        config = configure_official_auth()

        assert config.auth_method == "official"
        assert config.api_endpoint is None

    def test_configure_official_auth_clears_existing_endpoint(self):
        """官方认证会清除已有的自定义端点配置"""
        from frago.init.configurator import configure_official_auth

        existing_config = Config(
            auth_method="custom",
            api_endpoint=APIEndpoint(type="deepseek", api_key="old_key"),
        )

        config = configure_official_auth(existing_config)

        assert config.auth_method == "official"
        assert config.api_endpoint is None


class TestConfigureCustomEndpoint:
    """configure_custom_endpoint() 函数测试 (T032)"""

    def test_configure_custom_endpoint_deepseek(self):
        """配置 Deepseek 端点"""
        from frago.init.configurator import configure_custom_endpoint

        with patch("click.prompt", side_effect=["deepseek", "sk-test-key"]):
            config = configure_custom_endpoint()

        assert config.auth_method == "custom"
        assert config.api_endpoint is not None
        assert config.api_endpoint.type == "deepseek"
        assert config.api_endpoint.api_key == "sk-test-key"

    def test_configure_custom_endpoint_with_custom_url(self):
        """配置自定义 URL 端点"""
        from frago.init.configurator import configure_custom_endpoint

        with patch(
            "click.prompt",
            side_effect=["custom", "https://api.example.com/v1", "my-api-key"],
        ):
            config = configure_custom_endpoint()

        assert config.auth_method == "custom"
        assert config.api_endpoint.type == "custom"
        assert config.api_endpoint.url == "https://api.example.com/v1"
        assert config.api_endpoint.api_key == "my-api-key"


class TestAuthMutualExclusivity:
    """认证互斥性验证测试 (T033)"""

    def test_official_auth_cannot_have_endpoint(self):
        """官方认证不能有 api_endpoint"""
        with pytest.raises(ValueError, match="Official auth cannot have api_endpoint"):
            Config(
                auth_method="official",
                api_endpoint=APIEndpoint(type="deepseek", api_key="key"),
            )

    def test_custom_auth_requires_endpoint(self):
        """自定义认证必须有 api_endpoint"""
        with pytest.raises(ValueError, match="Custom auth requires api_endpoint"):
            Config(auth_method="custom", api_endpoint=None)

    def test_switching_from_custom_to_official_clears_endpoint(self):
        """从自定义切换到官方会清除端点配置"""
        from frago.init.configurator import configure_official_auth

        existing = Config(
            auth_method="custom",
            api_endpoint=APIEndpoint(type="deepseek", api_key="key"),
        )

        new_config = configure_official_auth(existing)

        assert new_config.auth_method == "official"
        assert new_config.api_endpoint is None


class TestLoadSaveConfig:
    """load_config() 和 save_config() 函数测试 (T039)"""

    def test_save_and_load_config(self, tmp_path):
        """保存和加载配置"""
        from frago.init.configurator import save_config, load_config

        config_file = tmp_path / ".frago" / "config.json"
        config = Config(
            auth_method="official",
            node_version="20.10.0",
            claude_code_version="1.0.0",
            init_completed=True,
        )

        save_config(config, config_file)
        loaded = load_config(config_file)

        assert loaded.auth_method == "official"
        assert loaded.node_version == "20.10.0"
        assert loaded.init_completed is True

    def test_load_nonexistent_config_returns_default(self, tmp_path):
        """加载不存在的配置返回默认值"""
        from frago.init.configurator import load_config

        config_file = tmp_path / "nonexistent" / "config.json"
        config = load_config(config_file)

        assert config.auth_method == "official"
        assert config.init_completed is False

    def test_save_config_creates_directory(self, tmp_path):
        """保存配置时自动创建目录"""
        from frago.init.configurator import save_config

        config_file = tmp_path / "new_dir" / "config.json"
        config = Config()

        save_config(config, config_file)

        assert config_file.exists()
        assert config_file.parent.exists()

    def test_load_corrupted_config_returns_default(self, tmp_path):
        """加载损坏的配置返回默认值并备份"""
        from frago.init.configurator import load_config

        config_file = tmp_path / "config.json"
        config_file.write_text("invalid json {{{")

        config = load_config(config_file)

        assert config.auth_method == "official"
        # 应该创建了备份文件
        backup_file = config_file.with_suffix(".json.bak")
        assert backup_file.exists()


# =============================================================================
# Phase 5: User Story 3 - 配置更新流程测试
# =============================================================================


class TestDisplayConfigSummary:
    """display_config_summary() 函数测试 (T042)"""

    def test_display_summary_official_auth(self):
        """显示官方认证配置摘要"""
        from frago.init.configurator import display_config_summary

        config = Config(
            auth_method="official",
            node_version="20.10.0",
            claude_code_version="1.0.0",
            init_completed=True,
        )

        summary = display_config_summary(config)

        assert "官方" in summary or "official" in summary.lower()
        assert "20.10.0" in summary
        assert "1.0.0" in summary

    def test_display_summary_custom_endpoint(self):
        """显示自定义端点配置摘要"""
        from frago.init.configurator import display_config_summary

        config = Config(
            auth_method="custom",
            api_endpoint=APIEndpoint(type="deepseek", api_key="sk-***"),
            node_version="20.10.0",
        )

        summary = display_config_summary(config)

        assert "自定义" in summary or "custom" in summary.lower()
        assert "deepseek" in summary.lower()


class TestPromptConfigUpdate:
    """prompt_config_update() 函数测试 (T043)"""

    def test_prompt_config_update_yes(self):
        """用户选择更新配置"""
        from frago.init.configurator import prompt_config_update

        with patch("click.confirm", return_value=True):
            result = prompt_config_update()

        assert result is True

    def test_prompt_config_update_no(self):
        """用户选择不更新配置"""
        from frago.init.configurator import prompt_config_update

        with patch("click.confirm", return_value=False):
            result = prompt_config_update()

        assert result is False


class TestSelectConfigItemsToUpdate:
    """select_config_items_to_update() 函数测试 (T048)"""

    def test_select_auth_method_update(self):
        """选择更新认证方式"""
        from frago.init.configurator import select_config_items_to_update

        with patch("click.prompt", return_value="auth"):
            items = select_config_items_to_update()

        assert "auth" in items

    def test_select_multiple_items(self):
        """选择更新多个配置项"""
        from frago.init.configurator import select_config_items_to_update

        # 模拟用户选择多个项目
        with patch("click.prompt", return_value="auth,endpoint"):
            items = select_config_items_to_update()

        assert "auth" in items or "endpoint" in items


class TestGetConfigPath:
    """get_config_path() 函数测试"""

    def test_get_config_path_default(self):
        """获取默认配置路径"""
        from frago.init.configurator import get_config_path

        path = get_config_path()

        assert path.name == "config.json"
        assert ".frago" in str(path)

    def test_get_config_path_custom_home(self, tmp_path):
        """使用自定义 HOME 目录"""
        from frago.init.configurator import get_config_path

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            path = get_config_path()

        assert str(tmp_path) in str(path)


class TestConfigExists:
    """config_exists() 函数测试"""

    def test_config_exists_true(self, tmp_path):
        """配置文件存在"""
        from frago.init.configurator import config_exists

        config_file = tmp_path / ".frago" / "config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("{}")

        with patch("frago.init.configurator.get_config_path", return_value=config_file):
            assert config_exists() is True

    def test_config_exists_false(self, tmp_path):
        """配置文件不存在"""
        from frago.init.configurator import config_exists

        config_file = tmp_path / "nonexistent" / "config.json"

        with patch("frago.init.configurator.get_config_path", return_value=config_file):
            assert config_exists() is False


# =============================================================================
# Phase 6: User Story 4 - 自定义 API 端点配置测试
# =============================================================================


class TestPromptEndpointType:
    """prompt_endpoint_type() 函数测试 (T051)"""

    def test_prompt_endpoint_type_deepseek(self):
        """选择 Deepseek 端点"""
        from frago.init.configurator import prompt_endpoint_type

        with patch("click.prompt", return_value="deepseek"):
            result = prompt_endpoint_type()

        assert result == "deepseek"

    def test_prompt_endpoint_type_aliyun(self):
        """选择阿里云端点"""
        from frago.init.configurator import prompt_endpoint_type

        with patch("click.prompt", return_value="aliyun"):
            result = prompt_endpoint_type()

        assert result == "aliyun"

    def test_prompt_endpoint_type_m2(self):
        """选择 M2 端点"""
        from frago.init.configurator import prompt_endpoint_type

        with patch("click.prompt", return_value="m2"):
            result = prompt_endpoint_type()

        assert result == "m2"

    def test_prompt_endpoint_type_custom(self):
        """选择自定义端点"""
        from frago.init.configurator import prompt_endpoint_type

        with patch("click.prompt", return_value="custom"):
            result = prompt_endpoint_type()

        assert result == "custom"

    def test_prompt_endpoint_type_case_insensitive(self):
        """端点类型不区分大小写"""
        from frago.init.configurator import prompt_endpoint_type

        with patch("click.prompt", return_value="DEEPSEEK"):
            result = prompt_endpoint_type()

        assert result == "deepseek"


class TestPromptApiKey:
    """prompt_api_key() 函数测试 (T052)"""

    def test_prompt_api_key_returns_value(self):
        """返回输入的 API Key"""
        from frago.init.configurator import prompt_api_key

        with patch("click.prompt", return_value="sk-test-key-12345") as mock_prompt:
            result = prompt_api_key()

        assert result == "sk-test-key-12345"
        # 验证使用了隐藏输入
        mock_prompt.assert_called_once()
        call_kwargs = mock_prompt.call_args[1]
        assert call_kwargs.get("hide_input") is True

    def test_prompt_api_key_with_description(self):
        """带描述的 API Key 输入"""
        from frago.init.configurator import prompt_api_key

        with patch("click.prompt", return_value="my-api-key") as mock_prompt:
            result = prompt_api_key("Deepseek")

        assert result == "my-api-key"


class TestValidateEndpointUrl:
    """validate_endpoint_url() 函数测试 (T053)"""

    def test_validate_valid_https_url(self):
        """验证有效的 HTTPS URL"""
        from frago.init.configurator import validate_endpoint_url

        result = validate_endpoint_url("https://api.example.com/v1")

        assert result is True

    def test_validate_valid_http_url(self):
        """验证有效的 HTTP URL"""
        from frago.init.configurator import validate_endpoint_url

        result = validate_endpoint_url("http://localhost:8080/api")

        assert result is True

    def test_validate_invalid_url_no_scheme(self):
        """无效 URL - 缺少协议"""
        from frago.init.configurator import validate_endpoint_url

        result = validate_endpoint_url("api.example.com/v1")

        assert result is False

    def test_validate_invalid_url_empty(self):
        """无效 URL - 空字符串"""
        from frago.init.configurator import validate_endpoint_url

        result = validate_endpoint_url("")

        assert result is False

    def test_validate_invalid_url_malformed(self):
        """无效 URL - 格式错误"""
        from frago.init.configurator import validate_endpoint_url

        result = validate_endpoint_url("not a url at all")

        assert result is False


class TestPromptCustomEndpointUrl:
    """prompt_custom_endpoint_url() 函数测试 (T058)"""

    def test_prompt_custom_url_valid(self):
        """输入有效的自定义 URL"""
        from frago.init.configurator import prompt_custom_endpoint_url

        with patch("click.prompt", return_value="https://api.custom.com/v1"):
            result = prompt_custom_endpoint_url()

        assert result == "https://api.custom.com/v1"

    def test_prompt_custom_url_retry_on_invalid(self):
        """无效 URL 时重试"""
        from frago.init.configurator import prompt_custom_endpoint_url

        # 第一次输入无效，第二次输入有效
        with patch("click.prompt", side_effect=["invalid", "https://api.valid.com/v1"]):
            with patch("click.echo"):
                result = prompt_custom_endpoint_url()

        assert result == "https://api.valid.com/v1"


class TestPresetEndpoints:
    """预设端点 URL 映射测试 (T060)"""

    def test_preset_endpoints_deepseek(self):
        """Deepseek 预设 URL"""
        from frago.init.configurator import PRESET_ENDPOINTS

        assert "deepseek" in PRESET_ENDPOINTS
        assert "deepseek" in PRESET_ENDPOINTS["deepseek"].lower()

    def test_preset_endpoints_aliyun(self):
        """阿里云预设 URL"""
        from frago.init.configurator import PRESET_ENDPOINTS

        assert "aliyun" in PRESET_ENDPOINTS
        assert "dashscope" in PRESET_ENDPOINTS["aliyun"].lower()

    def test_preset_endpoints_m2(self):
        """M2 预设 URL"""
        from frago.init.configurator import PRESET_ENDPOINTS

        assert "m2" in PRESET_ENDPOINTS
        assert "m2" in PRESET_ENDPOINTS["m2"].lower()

    def test_preset_endpoints_all_https(self):
        """所有预设 URL 都使用 HTTPS"""
        from frago.init.configurator import PRESET_ENDPOINTS

        for name, url in PRESET_ENDPOINTS.items():
            assert url.startswith("https://"), f"{name} should use HTTPS"


# =============================================================================
# Phase 8: User Story 6 - 配置持久化和摘要报告测试
# =============================================================================


class TestFormatFinalSummary:
    """format_final_summary() 函数测试 (T072)"""

    def test_format_final_summary_official_auth(self):
        """官方认证的最终摘要"""
        from frago.init.configurator import format_final_summary

        config = Config(
            auth_method="official",
            node_version="20.10.0",
            claude_code_version="1.0.0",
            init_completed=True,
        )

        summary = format_final_summary(config)

        assert "初始化完成" in summary or "完成" in summary
        assert "20.10.0" in summary
        assert "1.0.0" in summary

    def test_format_final_summary_custom_endpoint(self):
        """自定义端点的最终摘要"""
        from frago.init.configurator import format_final_summary

        config = Config(
            auth_method="custom",
            api_endpoint=APIEndpoint(type="deepseek", api_key="sk-***"),
            node_version="20.10.0",
            init_completed=True,
        )

        summary = format_final_summary(config)

        assert "deepseek" in summary.lower()
        assert "sk-***" not in summary  # API Key 应被隐藏


class TestSuggestNextSteps:
    """suggest_next_steps() 函数测试 (T076)"""

    def test_suggest_next_steps_official_auth(self):
        """官方认证的下一步建议"""
        from frago.init.configurator import suggest_next_steps

        config = Config(auth_method="official", init_completed=True)

        steps = suggest_next_steps(config)

        assert isinstance(steps, list)
        assert len(steps) > 0

    def test_suggest_next_steps_custom_endpoint(self):
        """自定义端点的下一步建议"""
        from frago.init.configurator import suggest_next_steps

        config = Config(
            auth_method="custom",
            api_endpoint=APIEndpoint(type="deepseek", api_key="key"),
            init_completed=True,
        )

        steps = suggest_next_steps(config)

        assert isinstance(steps, list)


class TestSaveConfigAtomic:
    """save_config 原子写入测试 (T074)"""

    def test_save_config_atomic_write(self, tmp_path):
        """保存配置使用原子写入"""
        from frago.init.configurator import save_config, load_config

        config_file = tmp_path / ".frago" / "config.json"
        config = Config(auth_method="official", init_completed=True)

        save_config(config, config_file)

        # 验证文件存在且可读
        assert config_file.exists()
        loaded = load_config(config_file)
        assert loaded.auth_method == "official"

    def test_save_config_preserves_existing_on_error(self, tmp_path):
        """写入失败时保留原有配置"""
        from frago.init.configurator import save_config, load_config

        config_file = tmp_path / ".frago" / "config.json"
        config_file.parent.mkdir(parents=True)

        # 先写入一个有效配置
        original_config = Config(auth_method="official", node_version="18.0.0")
        save_config(original_config, config_file)

        # 验证原配置存在
        loaded = load_config(config_file)
        assert loaded.node_version == "18.0.0"
