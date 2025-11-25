"""
格式化模块测试

测试 formatter.py 中的功能：
- 错误消息格式化 (T098)
- 成功消息格式化 (T099)
- 依赖状态格式化 (T100)
"""

import pytest
from unittest.mock import patch, MagicMock

from frago.init.models import DependencyCheckResult


# =============================================================================
# Phase 11: 格式化和用户体验测试
# =============================================================================


class TestFormatErrorMessage:
    """format_error_message() 函数测试 (T098)"""

    def test_format_error_message_title_only(self):
        """仅标题的错误消息"""
        from frago.init.formatter import format_error_message

        result = format_error_message("安装失败")

        assert "❌" in result
        assert "安装失败" in result

    def test_format_error_message_with_details(self):
        """带详情的错误消息"""
        from frago.init.formatter import format_error_message

        result = format_error_message(
            "Node.js 安装失败",
            details="命令执行超时",
        )

        assert "Node.js 安装失败" in result
        assert "命令执行超时" in result

    def test_format_error_message_with_suggestion(self):
        """带建议的错误消息"""
        from frago.init.formatter import format_error_message

        result = format_error_message(
            "网络错误",
            suggestion="请检查网络连接",
        )

        assert "网络错误" in result
        assert "💡" in result
        assert "请检查网络连接" in result

    def test_format_error_message_full(self):
        """完整的错误消息"""
        from frago.init.formatter import format_error_message

        result = format_error_message(
            "安装失败",
            details="权限不足",
            suggestion="使用 sudo 运行",
        )

        assert "安装失败" in result
        assert "权限不足" in result
        assert "使用 sudo 运行" in result


class TestFormatSuccessMessage:
    """format_success_message() 函数测试 (T099)"""

    def test_format_success_message_title_only(self):
        """仅标题的成功消息"""
        from frago.init.formatter import format_success_message

        result = format_success_message("安装完成")

        assert "✅" in result
        assert "安装完成" in result

    def test_format_success_message_with_details(self):
        """带详情的成功消息"""
        from frago.init.formatter import format_success_message

        result = format_success_message(
            "Node.js 安装完成",
            details="版本 20.10.0",
        )

        assert "Node.js 安装完成" in result
        assert "20.10.0" in result


class TestFormatWarningMessage:
    """format_warning_message() 函数测试"""

    def test_format_warning_message_title_only(self):
        """仅标题的警告消息"""
        from frago.init.formatter import format_warning_message

        result = format_warning_message("版本过低")

        assert "⚠️" in result
        assert "版本过低" in result

    def test_format_warning_message_with_details(self):
        """带详情的警告消息"""
        from frago.init.formatter import format_warning_message

        result = format_warning_message(
            "版本不匹配",
            details="当前 18.0.0，需要 >= 20.0.0",
        )

        assert "版本不匹配" in result
        assert "18.0.0" in result


class TestFormatDependencyStatus:
    """format_dependency_status() 函数测试 (T100)"""

    def test_format_dependency_status_all_installed(self):
        """所有依赖已安装"""
        from frago.init.formatter import format_dependency_status

        results = {
            "node": DependencyCheckResult(
                name="node",
                installed=True,
                version="20.10.0",
                version_sufficient=True,
                required_version="20.0.0",
            ),
            "claude-code": DependencyCheckResult(
                name="claude-code",
                installed=True,
                version="1.0.0",
                version_sufficient=True,
                required_version="1.0.0",
            ),
        }

        output = format_dependency_status(results)

        assert "✅" in output
        assert "Node.js" in output
        assert "20.10.0" in output
        assert "Claude Code" in output
        assert "1.0.0" in output

    def test_format_dependency_status_missing(self):
        """有缺失的依赖"""
        from frago.init.formatter import format_dependency_status

        results = {
            "node": DependencyCheckResult(
                name="node",
                installed=False,
                required_version="20.0.0",
            ),
        }

        output = format_dependency_status(results)

        assert "❌" in output
        assert "未安装" in output

    def test_format_dependency_status_version_insufficient(self):
        """版本不满足要求"""
        from frago.init.formatter import format_dependency_status

        results = {
            "node": DependencyCheckResult(
                name="node",
                installed=True,
                version="18.0.0",
                version_sufficient=False,
                required_version="20.0.0",
            ),
        }

        output = format_dependency_status(results)

        assert "✅" in output  # 已安装
        assert "⚠️" in output  # 版本警告
        assert "20.0.0" in output


class TestFormatDependencyName:
    """format_dependency_name() 函数测试"""

    def test_format_known_names(self):
        """格式化已知名称"""
        from frago.init.formatter import format_dependency_name

        assert format_dependency_name("node") == "Node.js"
        assert format_dependency_name("claude-code") == "Claude Code"
        assert format_dependency_name("ccr") == "Claude Code Router"

    def test_format_unknown_name(self):
        """格式化未知名称"""
        from frago.init.formatter import format_dependency_name

        assert format_dependency_name("unknown") == "unknown"


class TestFormatProgress:
    """format_progress() 函数测试"""

    def test_format_progress(self):
        """格式化进度"""
        from frago.init.formatter import format_progress

        result = format_progress(2, 5, "正在安装")

        assert "[2/5]" in result
        assert "正在安装" in result


class TestFormatStepMessages:
    """步骤消息格式化测试"""

    def test_format_step_start(self):
        """格式化步骤开始"""
        from frago.init.formatter import format_step_start

        result = format_step_start("安装 Node.js")

        assert "📦" in result
        assert "安装 Node.js" in result

    def test_format_step_complete(self):
        """格式化步骤完成"""
        from frago.init.formatter import format_step_complete

        result = format_step_complete("安装")

        assert "✅" in result
        assert "安装" in result
        assert "完成" in result

    def test_format_step_failed(self):
        """格式化步骤失败"""
        from frago.init.formatter import format_step_failed

        result = format_step_failed("安装", "权限不足")

        assert "❌" in result
        assert "安装" in result
        assert "失败" in result
        assert "权限不足" in result


class TestEchoFunctions:
    """echo_* 函数测试"""

    def test_echo_error(self):
        """echo_error 输出"""
        from frago.init.formatter import echo_error

        with patch("click.secho") as mock_secho:
            echo_error("测试错误")

        mock_secho.assert_called_once()
        call_args = mock_secho.call_args
        assert "测试错误" in call_args[0][0]
        assert call_args[1]["fg"] == "red"

    def test_echo_success(self):
        """echo_success 输出"""
        from frago.init.formatter import echo_success

        with patch("click.secho") as mock_secho:
            echo_success("测试成功")

        mock_secho.assert_called_once()
        call_args = mock_secho.call_args
        assert "测试成功" in call_args[0][0]
        assert call_args[1]["fg"] == "green"

    def test_echo_warning(self):
        """echo_warning 输出"""
        from frago.init.formatter import echo_warning

        with patch("click.secho") as mock_secho:
            echo_warning("测试警告")

        mock_secho.assert_called_once()
        call_args = mock_secho.call_args
        assert call_args[1]["fg"] == "yellow"
