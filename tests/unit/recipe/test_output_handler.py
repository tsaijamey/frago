"""
单元测试：OutputHandler（输出处理器）

测试输出到 stdout、file、clipboard 的功能和错误处理
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.recipes.output_handler import OutputHandler


class TestOutputHandlerStdout:
    """测试 stdout 输出"""

    def test_to_stdout(self, capsys):
        """测试基本的 stdout 输出"""
        data = {"success": True, "message": "Hello"}

        OutputHandler.handle(data, "stdout")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == data

    def test_to_stdout_with_chinese(self, capsys):
        """测试包含中文的 stdout 输出"""
        data = {"message": "你好世界", "value": 42}

        OutputHandler.handle(data, "stdout")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["message"] == "你好世界"
        assert output["value"] == 42

    def test_to_stdout_pretty_print(self, capsys):
        """测试 stdout 输出格式化（缩进）"""
        data = {"nested": {"key": "value"}}

        OutputHandler.handle(data, "stdout")

        captured = capsys.readouterr()
        # 验证输出包含缩进（pretty print）
        assert "  " in captured.out


class TestOutputHandlerFile:
    """测试 file 输出"""

    def test_to_file_basic(self):
        """测试基本的文件输出"""
        data = {"result": "test"}

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "output.json"

            OutputHandler.handle(data, "file", {"path": str(file_path)})

            # 验证文件存在
            assert file_path.exists()

            # 验证文件内容
            saved_data = json.loads(file_path.read_text())
            assert saved_data == data

    def test_to_file_creates_parent_directory(self):
        """测试文件输出自动创建父目录"""
        data = {"test": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "subdir" / "nested" / "output.json"

            OutputHandler.handle(data, "file", {"path": str(file_path)})

            # 验证父目录被创建
            assert file_path.parent.exists()
            # 验证文件存在
            assert file_path.exists()

    def test_to_file_missing_path_option(self):
        """测试文件输出缺少 path 选项"""
        data = {"test": True}

        with pytest.raises(ValueError, match="file 输出目标需要 'path' 选项"):
            OutputHandler.handle(data, "file", {})

    def test_to_file_write_error(self):
        """测试文件写入失败"""
        data = {"test": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.json"

            # 创建一个只读目录来触发写入错误
            file_path.parent.chmod(0o444)

            try:
                with pytest.raises(RuntimeError, match="写入文件失败"):
                    OutputHandler.handle(data, "file", {"path": str(file_path)})
            finally:
                # 恢复权限以便清理
                file_path.parent.chmod(0o755)

    def test_to_file_with_chinese(self):
        """测试包含中文的文件输出"""
        data = {"message": "测试中文", "value": 123}

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "chinese.json"

            OutputHandler.handle(data, "file", {"path": str(file_path)})

            # 验证中文正确保存（UTF-8编码）
            saved_data = json.loads(file_path.read_text(encoding='utf-8'))
            assert saved_data["message"] == "测试中文"


class TestOutputHandlerClipboard:
    """测试 clipboard 输出"""

    def test_to_clipboard(self):
        """测试剪贴板输出"""
        data = {"copied": "content"}

        # 模拟 pyperclip 模块
        with patch('builtins.__import__') as mock_import:
            mock_pyperclip = MagicMock()

            def import_side_effect(name, *args, **kwargs):
                if name == 'pyperclip':
                    return mock_pyperclip
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = import_side_effect

            OutputHandler.handle(data, "clipboard")

            # 验证调用了 pyperclip.copy
            mock_pyperclip.copy.assert_called_once()

            # 验证复制的内容是 JSON 字符串
            copied_content = mock_pyperclip.copy.call_args[0][0]
            assert json.loads(copied_content) == data

    def test_to_clipboard_pyperclip_not_installed(self):
        """测试 pyperclip 未安装时的错误"""
        data = {"test": True}

        # 模拟 pyperclip 未安装
        def import_side_effect(name, *args, **kwargs):
            if name == 'pyperclip':
                raise ImportError("No module named 'pyperclip'")
            return __import__(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_side_effect):
            with pytest.raises(RuntimeError, match="clipboard 输出需要安装可选依赖 pyperclip"):
                OutputHandler.handle(data, "clipboard")

    def test_to_clipboard_copy_fails(self):
        """测试剪贴板复制失败"""
        data = {"test": True}

        # 模拟 pyperclip 模块但 copy 失败
        with patch('builtins.__import__') as mock_import:
            mock_pyperclip = MagicMock()
            mock_pyperclip.copy.side_effect = Exception("Clipboard error")

            def import_side_effect(name, *args, **kwargs):
                if name == 'pyperclip':
                    return mock_pyperclip
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = import_side_effect

            with pytest.raises(RuntimeError, match="复制到剪贴板失败"):
                OutputHandler.handle(data, "clipboard")


class TestOutputHandlerErrors:
    """测试错误处理"""

    def test_invalid_target(self):
        """测试无效的输出目标"""
        data = {"test": True}

        with pytest.raises(ValueError, match="无效的输出目标: 'invalid'"):
            OutputHandler.handle(data, "invalid")

    def test_invalid_target_case_sensitive(self):
        """测试输出目标大小写敏感"""
        data = {"test": True}

        # 大写的 STDOUT 应该被视为无效
        with pytest.raises(ValueError, match="无效的输出目标"):
            OutputHandler.handle(data, "STDOUT")

    def test_none_options(self):
        """测试 options 为 None 时不报错"""
        data = {"test": True}

        # stdout 不需要 options，应该正常工作
        OutputHandler.handle(data, "stdout", None)
        # 如果没有抛出异常，测试通过
