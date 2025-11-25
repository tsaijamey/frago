"""
安装模块测试

测试 installer.py 中的安装功能：
- run_external_command(): 外部命令执行包装器
- install_node(): 安装 Node.js（通过 nvm）
- install_claude_code(): 安装 Claude Code（npm install）
"""

import pytest
from unittest.mock import patch, MagicMock, call
import subprocess

from frago.init.exceptions import CommandError, InitErrorCode


class TestRunExternalCommand:
    """run_external_command() 函数测试"""

    def test_successful_command(self):
        """命令执行成功"""
        from frago.init.installer import run_external_command

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "success output"
        mock_result.stderr = ""

        with patch("shutil.which", return_value="/usr/bin/echo"):
            with patch("subprocess.run", return_value=mock_result):
                result = run_external_command(["echo", "hello"])

        assert result.returncode == 0
        assert result.stdout == "success output"

    def test_command_not_found(self):
        """命令不存在"""
        from frago.init.installer import run_external_command

        with patch("shutil.which", return_value=None):
            with pytest.raises(CommandError) as exc_info:
                run_external_command(["nonexistent_command"])

        assert exc_info.value.code == InitErrorCode.COMMAND_NOT_FOUND

    def test_command_permission_denied(self):
        """命令权限不足"""
        from frago.init.installer import run_external_command

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Permission denied: EACCES"

        with patch("shutil.which", return_value="/usr/bin/test"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(CommandError) as exc_info:
                    run_external_command(["test", "command"])

        assert exc_info.value.code == InitErrorCode.PERMISSION_ERROR

    def test_command_network_timeout(self):
        """网络超时"""
        from frago.init.installer import run_external_command

        with patch("shutil.which", return_value="/usr/bin/npm"):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="npm", timeout=120),
            ):
                with pytest.raises(CommandError) as exc_info:
                    run_external_command(["npm", "install"])

        assert exc_info.value.code == InitErrorCode.NETWORK_ERROR

    def test_command_generic_error(self):
        """通用执行错误"""
        from frago.init.installer import run_external_command

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Some error occurred"

        with patch("shutil.which", return_value="/usr/bin/test"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(CommandError) as exc_info:
                    run_external_command(["test", "command"])

        assert exc_info.value.code == InitErrorCode.INSTALL_ERROR

    def test_command_with_custom_timeout(self):
        """自定义超时时间"""
        from frago.init.installer import run_external_command

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/echo"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                run_external_command(["echo", "test"], timeout=300)

        # 验证超时参数被传递
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 300

    def test_command_check_disabled(self):
        """禁用返回码检查"""
        from frago.init.installer import run_external_command

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"

        with patch("shutil.which", return_value="/usr/bin/test"):
            with patch("subprocess.run", return_value=mock_result):
                # check=False 时不应抛出异常
                result = run_external_command(["test"], check=False)

        assert result.returncode == 1


class TestInstallNode:
    """install_node() 函数测试"""

    def test_install_node_via_nvm_success(self):
        """通过 nvm 安装 Node.js 成功"""
        from frago.init.installer import install_node

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Downloading and installing node v20.10.0..."

        with patch("shutil.which", return_value="/home/user/.nvm/nvm.sh"):
            with patch("subprocess.run", return_value=mock_result):
                result = install_node(version="20")

        assert result is True

    def test_install_node_nvm_not_found(self):
        """nvm 未安装"""
        from frago.init.installer import install_node

        with patch("shutil.which", return_value=None):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(CommandError) as exc_info:
                    install_node()

        assert exc_info.value.code == InitErrorCode.COMMAND_NOT_FOUND
        assert "nvm" in exc_info.value.message.lower()

    def test_install_node_installation_failed(self):
        """Node.js 安装失败"""
        from frago.init.installer import install_node

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Installation failed"

        with patch("shutil.which", return_value="/home/user/.nvm/nvm.sh"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(CommandError) as exc_info:
                    install_node()

        assert exc_info.value.code == InitErrorCode.INSTALL_ERROR


class TestInstallClaudeCode:
    """install_claude_code() 函数测试"""

    def test_install_claude_code_success(self):
        """安装 Claude Code 成功"""
        from frago.init.installer import install_claude_code

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "added 1 package"

        with patch("shutil.which", return_value="/usr/bin/npm"):
            with patch("subprocess.run", return_value=mock_result):
                result = install_claude_code()

        assert result is True

    def test_install_claude_code_npm_not_found(self):
        """npm 未安装"""
        from frago.init.installer import install_claude_code

        with patch("shutil.which", return_value=None):
            with pytest.raises(CommandError) as exc_info:
                install_claude_code()

        assert exc_info.value.code == InitErrorCode.COMMAND_NOT_FOUND
        assert "npm" in exc_info.value.message.lower()

    def test_install_claude_code_permission_error(self):
        """npm 全局安装权限不足"""
        from frago.init.installer import install_claude_code

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "EACCES: permission denied"

        with patch("shutil.which", return_value="/usr/bin/npm"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(CommandError) as exc_info:
                    install_claude_code()

        assert exc_info.value.code == InitErrorCode.PERMISSION_ERROR

    def test_install_claude_code_network_error(self):
        """npm 安装网络错误"""
        from frago.init.installer import install_claude_code

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ETIMEDOUT: network timeout"

        with patch("shutil.which", return_value="/usr/bin/npm"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(CommandError) as exc_info:
                    install_claude_code()

        assert exc_info.value.code == InitErrorCode.NETWORK_ERROR


class TestInstallationOrder:
    """安装顺序测试"""

    def test_node_must_be_installed_before_claude_code(self):
        """Node.js 必须在 Claude Code 之前安装"""
        from frago.init.installer import get_installation_order

        order = get_installation_order(node_needed=True, claude_code_needed=True)

        assert order == ["node", "claude-code"]
        assert order.index("node") < order.index("claude-code")

    def test_only_claude_code_needed(self):
        """只需要安装 Claude Code"""
        from frago.init.installer import get_installation_order

        order = get_installation_order(node_needed=False, claude_code_needed=True)

        assert order == ["claude-code"]

    def test_only_node_needed(self):
        """只需要安装 Node.js"""
        from frago.init.installer import get_installation_order

        order = get_installation_order(node_needed=True, claude_code_needed=False)

        assert order == ["node"]

    def test_nothing_needed(self):
        """不需要安装任何东西"""
        from frago.init.installer import get_installation_order

        order = get_installation_order(node_needed=False, claude_code_needed=False)

        assert order == []
