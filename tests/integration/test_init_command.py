"""
frago init 命令集成测试

测试完整的初始化流程：
- 全新安装场景
- 部分已安装场景
- 已有配置更新场景
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from click.testing import CliRunner
import json
import tempfile


@pytest.fixture
def temp_home(tmp_path):
    """创建临时 home 目录"""
    frago_dir = tmp_path / ".frago"
    frago_dir.mkdir()
    return tmp_path


@pytest.fixture
def cli_runner():
    """Click CLI 测试运行器"""
    return CliRunner()


class TestInitCommandFreshInstall:
    """全新安装场景测试 (User Story 1)"""

    def test_fresh_install_all_missing(self, cli_runner, temp_home):
        """全新系统：所有依赖缺失，需要安装"""
        from frago.cli.init_command import init

        # Mock 依赖检查结果：都未安装
        mock_check_results = {
            "node": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ node: 未安装"),
            "claude-code": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ claude-code: 未安装"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=["node", "claude-code"]):
                with patch("frago.cli.init_command.install_dependency", return_value=True):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        # y=安装依赖, official=选择官方认证
                        result = cli_runner.invoke(init, input="y\nofficial\n")

        # 验证退出码
        assert result.exit_code == 0, f"命令失败: {result.output}"

    def test_fresh_install_user_declines(self, cli_runner, temp_home):
        """全新系统：用户拒绝安装"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ node: 未安装"),
            "claude-code": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ claude-code: 未安装"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=["node", "claude-code"]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    result = cli_runner.invoke(init, input="n\n")

        # 用户取消应该返回退出码 2
        assert result.exit_code == 2

    def test_fresh_install_node_only_missing(self, cli_runner, temp_home):
        """部分已装：仅 Node.js 缺失"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ node: 未安装"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, version="1.0.0", display_status=lambda: "✅ claude-code: 1.0.0"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=["node"]):
                with patch("frago.cli.init_command.install_dependency", return_value=True):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        # y=安装依赖, official=选择官方认证
                        result = cli_runner.invoke(init, input="y\nofficial\n")

        assert result.exit_code == 0

    def test_fresh_install_claude_code_only_missing(self, cli_runner, temp_home):
        """部分已装：仅 Claude Code 缺失"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, version="20.10.0", display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ claude-code: 未安装"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=["claude-code"]):
                with patch("frago.cli.init_command.install_dependency", return_value=True):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        # y=安装依赖, official=选择官方认证
                        result = cli_runner.invoke(init, input="y\nofficial\n")

        assert result.exit_code == 0


class TestInitCommandInstallFailure:
    """安装失败场景测试"""

    def test_node_install_failure_terminates(self, cli_runner, temp_home):
        """Node.js 安装失败应立即终止"""
        from frago.cli.init_command import init
        from frago.init.exceptions import CommandError, InitErrorCode

        mock_check_results = {
            "node": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ node: 未安装"),
            "claude-code": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ claude-code: 未安装"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=["node", "claude-code"]):
                with patch(
                    "frago.cli.init_command.install_dependency",
                    side_effect=CommandError("安装失败", InitErrorCode.INSTALL_ERROR),
                ):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        result = cli_runner.invoke(init, input="y\n")

        # 安装失败应返回非零退出码
        assert result.exit_code != 0
        assert "失败" in result.output or "error" in result.output.lower()

    def test_claude_code_install_failure_terminates(self, cli_runner, temp_home):
        """Claude Code 安装失败应立即终止"""
        from frago.cli.init_command import init
        from frago.init.exceptions import CommandError, InitErrorCode

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, version="20.10.0", display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=False, needs_install=lambda: True, display_status=lambda: "❌ claude-code: 未安装"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=["claude-code"]):
                with patch(
                    "frago.cli.init_command.install_dependency",
                    side_effect=CommandError("安装失败", InitErrorCode.PERMISSION_ERROR),
                ):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        result = cli_runner.invoke(init, input="y\n")

        # 安装失败应返回非零退出码
        assert result.exit_code != 0


class TestInitCommandAllInstalled:
    """所有依赖已安装场景测试"""

    def test_all_installed_shows_summary(self, cli_runner, temp_home):
        """所有依赖已安装时显示摘要"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(
                installed=True,
                needs_install=lambda: False,
                version="20.10.0",
                display_status=lambda: "✅ node: 20.10.0",
            ),
            "claude-code": MagicMock(
                installed=True,
                needs_install=lambda: False,
                version="1.0.0",
                display_status=lambda: "✅ claude-code: 1.0.0",
            ),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    # official=选择官方认证
                    result = cli_runner.invoke(init, input="official\n")

        assert result.exit_code == 0
        # 应该显示依赖状态
        assert "✅" in result.output or "已满足" in result.output or "installed" in result.output.lower()


class TestInitCommandDependencyCheck:
    """依赖检查显示测试"""

    def test_dependency_check_shows_status(self, cli_runner, temp_home):
        """检查时显示依赖状态"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(
                installed=True,
                needs_install=lambda: False,
                version="20.10.0",
                display_status=lambda: "✅ Node.js: 20.10.0",
            ),
            "claude-code": MagicMock(
                installed=False,
                needs_install=lambda: True,
                version=None,
                display_status=lambda: "❌ Claude Code: 未安装",
            ),
        }

        with patch("frago.init.checker.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.init.installer.install_claude_code", return_value=True):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    result = cli_runner.invoke(init, input="y\n")

        # 应该显示检查结果
        assert "Node" in result.output or "node" in result.output
        assert "Claude" in result.output or "claude" in result.output


class TestInitCommandConfigPersistence:
    """配置持久化测试"""

    def test_config_saved_after_successful_init(self, cli_runner, temp_home):
        """成功初始化后配置被保存"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(
                installed=True,
                needs_install=lambda: False,
                version="20.10.0",
                path="/usr/bin/node",
                display_status=lambda: "✅ node: 20.10.0",
            ),
            "claude-code": MagicMock(
                installed=True,
                needs_install=lambda: False,
                version="1.0.0",
                path="/usr/bin/claude",
                display_status=lambda: "✅ claude-code: 1.0.0",
            ),
        }

        config_file = temp_home / ".frago" / "config.json"

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    # 选择官方认证
                    result = cli_runner.invoke(init, input="official\n")

        assert result.exit_code == 0
        assert config_file.exists()


# =============================================================================
# Phase 4: User Story 2 - 认证方式选择集成测试
# =============================================================================


class TestInitCommandOfficialAuth:
    """官方认证流程集成测试 (T034)"""

    def test_official_auth_flow(self, cli_runner, temp_home):
        """选择官方认证流程"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ claude-code: 1.0.0"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    result = cli_runner.invoke(init, input="official\n")

        assert result.exit_code == 0
        assert "官方" in result.output or "official" in result.output.lower()

        # 验证配置文件
        config_file = temp_home / ".frago" / "config.json"
        assert config_file.exists()

        config_data = json.loads(config_file.read_text())
        assert config_data["auth_method"] == "official"
        assert config_data["api_endpoint"] is None


class TestInitCommandCustomEndpoint:
    """自定义端点流程集成测试 (T035)"""

    def test_custom_endpoint_deepseek(self, cli_runner, temp_home):
        """选择 Deepseek 自定义端点"""
        from frago.cli.init_command import init

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ claude-code: 1.0.0"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    # 选择 custom -> deepseek -> api_key
                    result = cli_runner.invoke(init, input="custom\ndeepseek\nsk-test-key\n")

        assert result.exit_code == 0

        # 验证配置文件
        config_file = temp_home / ".frago" / "config.json"
        assert config_file.exists()

        config_data = json.loads(config_file.read_text())
        assert config_data["auth_method"] == "custom"
        assert config_data["api_endpoint"]["type"] == "deepseek"
        assert config_data["api_endpoint"]["api_key"] == "sk-test-key"


# =============================================================================
# Phase 5: User Story 3 - 配置更新流程集成测试
# =============================================================================


class TestInitCommandConfigUpdate:
    """配置更新流程集成测试 (T044)"""

    def test_existing_config_shows_summary(self, cli_runner, temp_home):
        """已有配置时显示摘要"""
        from frago.cli.init_command import init

        # 预先创建配置文件
        config_file = temp_home / ".frago" / "config.json"
        config_data = {
            "schema_version": "1.0",
            "auth_method": "official",
            "api_endpoint": None,
            "init_completed": True,
            "node_version": "20.10.0",
            "claude_code_version": "1.0.0",
        }
        config_file.write_text(json.dumps(config_data))

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ claude-code: 1.0.0"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    # 选择不更新配置
                    result = cli_runner.invoke(init, input="n\n")

        assert result.exit_code == 0
        # 应该显示当前配置摘要
        assert "当前配置" in result.output or "official" in result.output.lower()

    def test_update_config_from_official_to_custom(self, cli_runner, temp_home):
        """从官方认证更新到自定义端点"""
        from frago.cli.init_command import init

        # 预先创建官方认证配置
        config_file = temp_home / ".frago" / "config.json"
        config_data = {
            "schema_version": "1.0",
            "auth_method": "official",
            "api_endpoint": None,
            "init_completed": True,
        }
        config_file.write_text(json.dumps(config_data))

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ claude-code: 1.0.0"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    # 选择更新 -> custom -> deepseek -> api_key -> 确认切换
                    result = cli_runner.invoke(init, input="y\ncustom\ndeepseek\nsk-new-key\ny\n")

        assert result.exit_code == 0

        # 验证配置已更新
        updated_config = json.loads(config_file.read_text())
        assert updated_config["auth_method"] == "custom"
        assert updated_config["api_endpoint"]["type"] == "deepseek"


class TestInitCommandNoUpdateExit:
    """无需更新退出测试 (T045)"""

    def test_no_update_keeps_existing_config(self, cli_runner, temp_home):
        """选择不更新时保持现有配置"""
        from frago.cli.init_command import init

        # 预先创建配置
        config_file = temp_home / ".frago" / "config.json"
        original_config = {
            "schema_version": "1.0",
            "auth_method": "custom",
            "api_endpoint": {"type": "deepseek", "url": "https://api.deepseek.com/v1", "api_key": "original-key"},
            "init_completed": True,
        }
        config_file.write_text(json.dumps(original_config))

        mock_check_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ node: 20.10.0"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅ claude-code: 1.0.0"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_check_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch.dict("os.environ", {"HOME": str(temp_home)}):
                    # 选择不更新
                    result = cli_runner.invoke(init, input="n\n")

        assert result.exit_code == 0
        assert "保持现有配置" in result.output

        # 验证配置未变
        current_config = json.loads(config_file.read_text())
        assert current_config["api_endpoint"]["api_key"] == "original-key"


class TestInitCommandShowConfig:
    """--show-config 选项测试"""

    def test_show_config_displays_current(self, cli_runner, temp_home):
        """--show-config 显示当前配置"""
        from frago.cli.init_command import init

        # 创建配置
        config_file = temp_home / ".frago" / "config.json"
        config_data = {
            "schema_version": "1.0",
            "auth_method": "official",
            "api_endpoint": None,
            "init_completed": True,
            "node_version": "20.10.0",
        }
        config_file.write_text(json.dumps(config_data))

        with patch.dict("os.environ", {"HOME": str(temp_home)}):
            result = cli_runner.invoke(init, ["--show-config"])

        assert result.exit_code == 0
        assert "当前配置" in result.output
        assert "20.10.0" in result.output

    def test_show_config_no_config_exists(self, cli_runner, temp_home):
        """--show-config 无配置时提示"""
        from frago.cli.init_command import init

        # 确保没有配置文件
        config_file = temp_home / ".frago" / "config.json"
        if config_file.exists():
            config_file.unlink()

        with patch.dict("os.environ", {"HOME": str(temp_home)}):
            result = cli_runner.invoke(init, ["--show-config"])

        assert result.exit_code == 0
        assert "尚未初始化" in result.output


# =============================================================================
# Phase 6: User Story 4 - 自定义 API 端点配置集成测试
# =============================================================================


class TestInitCommandDeepseekEndpoint:
    """Deepseek 端点配置测试 (T054)"""

    def test_configure_deepseek_endpoint(self, cli_runner, temp_home):
        """配置 Deepseek 端点完整流程"""
        from frago.cli.init_command import init

        # Mock 所有依赖已安装
        mock_results = {
            "node": MagicMock(
                installed=True,
                needs_install=lambda: False,
                display_status=lambda: "✅ node: v20.10.0",
            ),
            "claude-code": MagicMock(
                installed=True,
                needs_install=lambda: False,
                display_status=lambda: "✅ claude-code: 1.0.0",
            ),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch("frago.cli.init_command.format_check_results", return_value="依赖检查完成"):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        # custom=选择自定义, deepseek=选择Deepseek, api_key=输入密钥
                        result = cli_runner.invoke(
                            init,
                            input="custom\ndeepseek\nsk-deepseek-test-key\n",
                        )

        assert result.exit_code == 0

        # 验证配置保存
        config_file = temp_home / ".frago" / "config.json"
        assert config_file.exists()

        config = json.loads(config_file.read_text())
        assert config["auth_method"] == "custom"
        assert config["api_endpoint"]["type"] == "deepseek"
        assert config["api_endpoint"]["api_key"] == "sk-deepseek-test-key"
        assert "deepseek" in config["api_endpoint"]["url"].lower()

    def test_configure_aliyun_endpoint(self, cli_runner, temp_home):
        """配置阿里云端点"""
        from frago.cli.init_command import init

        mock_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch("frago.cli.init_command.format_check_results", return_value=""):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        result = cli_runner.invoke(
                            init,
                            input="custom\naliyun\nsk-aliyun-key\n",
                        )

        assert result.exit_code == 0

        config = json.loads((temp_home / ".frago" / "config.json").read_text())
        assert config["api_endpoint"]["type"] == "aliyun"
        assert "dashscope" in config["api_endpoint"]["url"].lower()


class TestInitCommandCustomUrlEndpoint:
    """自定义 URL 端点配置测试 (T055)"""

    def test_configure_custom_url_endpoint(self, cli_runner, temp_home):
        """配置自定义 URL 端点"""
        from frago.cli.init_command import init

        mock_results = {
            "node": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅"),
            "claude-code": MagicMock(installed=True, needs_install=lambda: False, display_status=lambda: "✅"),
        }

        with patch("frago.cli.init_command.parallel_dependency_check", return_value=mock_results):
            with patch("frago.cli.init_command.get_missing_dependencies", return_value=[]):
                with patch("frago.cli.init_command.format_check_results", return_value=""):
                    with patch.dict("os.environ", {"HOME": str(temp_home)}):
                        # custom=自定义认证, custom=自定义URL, url, api_key
                        result = cli_runner.invoke(
                            init,
                            input="custom\ncustom\nhttps://api.mycorp.com/v1\nmy-corp-api-key\n",
                        )

        assert result.exit_code == 0

        config = json.loads((temp_home / ".frago" / "config.json").read_text())
        assert config["auth_method"] == "custom"
        assert config["api_endpoint"]["type"] == "custom"
        assert config["api_endpoint"]["url"] == "https://api.mycorp.com/v1"
        assert config["api_endpoint"]["api_key"] == "my-corp-api-key"

    def test_custom_endpoint_persists_across_sessions(self, cli_runner, temp_home):
        """自定义端点配置持久化验证"""
        from frago.cli.init_command import init

        # 先创建配置
        config_file = temp_home / ".frago" / "config.json"
        config_data = {
            "schema_version": "1.0",
            "auth_method": "custom",
            "api_endpoint": {
                "type": "custom",
                "url": "https://api.persistent.com/v1",
                "api_key": "persistent-key",
            },
            "init_completed": True,
        }
        config_file.write_text(json.dumps(config_data))

        # 使用 --show-config 验证
        with patch.dict("os.environ", {"HOME": str(temp_home)}):
            result = cli_runner.invoke(init, ["--show-config"])

        assert result.exit_code == 0
        assert "自定义" in result.output
        assert "custom" in result.output.lower()
