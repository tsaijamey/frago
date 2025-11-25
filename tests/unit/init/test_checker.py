"""
依赖检查模块测试

测试 checker.py 中的依赖检测功能：
- check_node(): 检测 Node.js 安装状态
- check_claude_code(): 检测 Claude Code 安装状态
- parallel_dependency_check(): 并行检查所有依赖
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from frago.init.models import DependencyCheckResult


class TestCheckNode:
    """check_node() 函数测试"""

    def test_node_installed_and_sufficient(self):
        """Node.js 已安装且版本满足要求"""
        from frago.init.checker import check_node

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v20.10.0\n"

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/node"):
                result = check_node()

        assert result.installed is True
        assert result.version == "20.10.0"
        assert result.version_sufficient is True
        assert result.path == "/usr/bin/node"
        assert result.error is None

    def test_node_installed_but_version_insufficient(self):
        """Node.js 已安装但版本不足"""
        from frago.init.checker import check_node

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v18.0.0\n"

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/node"):
                result = check_node(min_version="20.0.0")

        assert result.installed is True
        assert result.version == "18.0.0"
        assert result.version_sufficient is False
        assert result.needs_install() is True

    def test_node_not_installed(self):
        """Node.js 未安装"""
        from frago.init.checker import check_node

        with patch("shutil.which", return_value=None):
            result = check_node()

        assert result.installed is False
        assert result.version is None
        assert result.path is None
        assert result.needs_install() is True

    def test_node_command_error(self):
        """Node.js 命令执行错误"""
        from frago.init.checker import check_node

        with patch("shutil.which", return_value="/usr/bin/node"):
            with patch(
                "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=5)
            ):
                result = check_node()

        assert result.installed is False
        assert result.error is not None
        assert "timeout" in result.error.lower() or "超时" in result.error


class TestCheckClaudeCode:
    """check_claude_code() 函数测试"""

    def test_claude_code_installed(self):
        """Claude Code 已安装"""
        from frago.init.checker import check_claude_code

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1.0.0\n"

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/claude"):
                result = check_claude_code()

        assert result.installed is True
        assert result.version == "1.0.0"
        assert result.version_sufficient is True

    def test_claude_code_not_installed(self):
        """Claude Code 未安装"""
        from frago.init.checker import check_claude_code

        with patch("shutil.which", return_value=None):
            result = check_claude_code()

        assert result.installed is False
        assert result.version is None
        assert result.needs_install() is True

    def test_claude_code_command_not_found(self):
        """Claude Code 命令不存在（FileNotFoundError）"""
        from frago.init.checker import check_claude_code

        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", side_effect=FileNotFoundError()):
                result = check_claude_code()

        assert result.installed is False
        assert result.error is not None


class TestParallelDependencyCheck:
    """parallel_dependency_check() 函数测试"""

    def test_all_dependencies_installed(self):
        """所有依赖都已安装"""
        from frago.init.checker import parallel_dependency_check

        node_result = DependencyCheckResult(
            name="node",
            installed=True,
            version="20.10.0",
            version_sufficient=True,
            required_version="20.0.0",
        )
        claude_result = DependencyCheckResult(
            name="claude-code",
            installed=True,
            version="1.0.0",
            version_sufficient=True,
            required_version="1.0.0",
        )

        with patch("frago.init.checker.check_node", return_value=node_result):
            with patch("frago.init.checker.check_claude_code", return_value=claude_result):
                results = parallel_dependency_check()

        assert len(results) == 2
        assert results["node"].installed is True
        assert results["claude-code"].installed is True

    def test_some_dependencies_missing(self):
        """部分依赖缺失"""
        from frago.init.checker import parallel_dependency_check

        node_result = DependencyCheckResult(
            name="node",
            installed=True,
            version="20.10.0",
            version_sufficient=True,
            required_version="20.0.0",
        )
        claude_result = DependencyCheckResult(
            name="claude-code",
            installed=False,
            version=None,
            version_sufficient=False,
            required_version="1.0.0",
        )

        with patch("frago.init.checker.check_node", return_value=node_result):
            with patch("frago.init.checker.check_claude_code", return_value=claude_result):
                results = parallel_dependency_check()

        assert results["node"].installed is True
        assert results["claude-code"].installed is False
        assert results["claude-code"].needs_install() is True

    def test_all_dependencies_missing(self):
        """所有依赖都缺失"""
        from frago.init.checker import parallel_dependency_check

        node_result = DependencyCheckResult(
            name="node",
            installed=False,
            version=None,
            version_sufficient=False,
            required_version="20.0.0",
        )
        claude_result = DependencyCheckResult(
            name="claude-code",
            installed=False,
            version=None,
            version_sufficient=False,
            required_version="1.0.0",
        )

        with patch("frago.init.checker.check_node", return_value=node_result):
            with patch("frago.init.checker.check_claude_code", return_value=claude_result):
                results = parallel_dependency_check()

        assert results["node"].needs_install() is True
        assert results["claude-code"].needs_install() is True

    def test_parallel_execution_performance(self):
        """验证并行执行（不应串行等待）"""
        from frago.init.checker import parallel_dependency_check
        import time

        def slow_check_node():
            time.sleep(0.1)
            return DependencyCheckResult(
                name="node",
                installed=True,
                version="20.0.0",
                version_sufficient=True,
                required_version="20.0.0",
            )

        def slow_check_claude():
            time.sleep(0.1)
            return DependencyCheckResult(
                name="claude-code",
                installed=True,
                version="1.0.0",
                version_sufficient=True,
                required_version="1.0.0",
            )

        with patch("frago.init.checker.check_node", side_effect=slow_check_node):
            with patch("frago.init.checker.check_claude_code", side_effect=slow_check_claude):
                start = time.time()
                results = parallel_dependency_check()
                elapsed = time.time() - start

        # 并行执行应该小于 0.2 秒（串行需要 0.2+ 秒）
        assert elapsed < 0.2, f"并行执行耗时过长: {elapsed:.3f}s"
        assert len(results) == 2


class TestVersionComparison:
    """版本比较逻辑测试"""

    def test_compare_versions_equal(self):
        """版本相等"""
        from frago.init.checker import compare_versions

        assert compare_versions("20.0.0", "20.0.0") == 0

    def test_compare_versions_greater(self):
        """当前版本高于要求"""
        from frago.init.checker import compare_versions

        assert compare_versions("20.10.0", "20.0.0") > 0
        assert compare_versions("21.0.0", "20.10.0") > 0

    def test_compare_versions_less(self):
        """当前版本低于要求"""
        from frago.init.checker import compare_versions

        assert compare_versions("18.0.0", "20.0.0") < 0
        assert compare_versions("20.0.0", "20.10.0") < 0

    def test_compare_versions_with_v_prefix(self):
        """版本号带 v 前缀"""
        from frago.init.checker import compare_versions

        assert compare_versions("v20.0.0", "20.0.0") == 0
        assert compare_versions("20.0.0", "v20.0.0") == 0
