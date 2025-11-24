"""单元测试 - screenshot

测试截图自动编号和原子性写入
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from frago.run.screenshot import get_next_screenshot_number, capture_screenshot


class TestGetNextScreenshotNumber:
    """测试get_next_screenshot_number函数"""

    def test_empty_directory(self, tmp_path):
        """测试空目录返回1"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        seq = get_next_screenshot_number(screenshots_dir)
        assert seq == 1

    def test_sequential_numbering(self, tmp_path):
        """测试顺序编号"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # 创建已存在的截图
        (screenshots_dir / "001_test.png").touch()
        (screenshots_dir / "002_another.png").touch()
        (screenshots_dir / "003_third.png").touch()

        seq = get_next_screenshot_number(screenshots_dir)
        assert seq == 4

    def test_gap_in_numbers(self, tmp_path):
        """测试编号有间隙时返回最大值+1"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # 创建不连续的编号
        (screenshots_dir / "001_test.png").touch()
        (screenshots_dir / "005_test.png").touch()
        (screenshots_dir / "003_test.png").touch()

        seq = get_next_screenshot_number(screenshots_dir)
        assert seq == 6  # max(1,5,3) + 1

    def test_ignores_invalid_filenames(self, tmp_path):
        """测试忽略无效的文件名"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # 创建有效和无效的文件
        (screenshots_dir / "001_valid.png").touch()
        (screenshots_dir / "invalid.png").touch()  # 无序号前缀
        (screenshots_dir / "abc_test.png").touch()  # 非数字前缀

        seq = get_next_screenshot_number(screenshots_dir)
        assert seq == 2

    def test_nonexistent_directory_creates(self, tmp_path):
        """测试不存在的目录会被创建"""
        screenshots_dir = tmp_path / "nonexistent"
        assert not screenshots_dir.exists()

        seq = get_next_screenshot_number(screenshots_dir)
        assert screenshots_dir.exists()
        assert seq == 1


class TestCaptureScreenshot:
    """测试capture_screenshot函数"""

    @patch("frago.run.screenshot.CDPSession")
    @patch("frago.run.screenshot.CDPClient")
    def test_capture_screenshot_success(self, mock_client_class, mock_session_class, tmp_path):
        """测试成功捕获截图"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # Mock CDP
        mock_session = Mock()
        mock_session.capture_screenshot.return_value = b"fake image data"
        mock_session_class.return_value = mock_session

        # 捕获截图
        file_path, seq_num = capture_screenshot("测试页面", screenshots_dir)

        # 验证
        assert seq_num == 1
        assert file_path.name.startswith("001_")
        assert file_path.suffix == ".png"
        assert file_path.exists()
        assert file_path.read_bytes() == b"fake image data"

    @patch("frago.run.screenshot.CDPSession")
    @patch("frago.run.screenshot.CDPClient")
    def test_capture_screenshot_slug_description(
        self, mock_client_class, mock_session_class, tmp_path
    ):
        """测试描述被slug化"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        mock_session = Mock()
        mock_session.capture_screenshot.return_value = b"data"
        mock_session_class.return_value = mock_session

        file_path, _ = capture_screenshot("搜索页面!@#", screenshots_dir)

        # 文件名应该不包含特殊字符
        assert "!" not in file_path.name
        assert "@" not in file_path.name
        assert "#" not in file_path.name
        assert "sou-suo-ye-mian" in file_path.name or "search-page" in file_path.name.lower()

    @patch("frago.run.screenshot.CDPSession")
    @patch("frago.run.screenshot.CDPClient")
    def test_capture_screenshot_sequential(
        self, mock_client_class, mock_session_class, tmp_path
    ):
        """测试连续截图自动递增"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        mock_session = Mock()
        mock_session.capture_screenshot.return_value = b"data"
        mock_session_class.return_value = mock_session

        # 第一个截图
        _, seq1 = capture_screenshot("页面1", screenshots_dir)
        assert seq1 == 1

        # 第二个截图
        _, seq2 = capture_screenshot("页面2", screenshots_dir)
        assert seq2 == 2

        # 第三个截图
        _, seq3 = capture_screenshot("页面3", screenshots_dir)
        assert seq3 == 3

    @patch("frago.run.screenshot.CDPSession")
    @patch("frago.run.screenshot.CDPClient")
    def test_capture_screenshot_atomic_write(
        self, mock_client_class, mock_session_class, tmp_path
    ):
        """测试原子性写入(临时文件 -> 重命名)"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        mock_session = Mock()
        mock_session.capture_screenshot.return_value = b"test data"
        mock_session_class.return_value = mock_session

        file_path, _ = capture_screenshot("test", screenshots_dir)

        # 验证最终文件存在
        assert file_path.exists()

        # 验证没有残留的临时文件
        temp_files = list(screenshots_dir.glob(".tmp_*"))
        assert len(temp_files) == 0

    @patch("frago.run.screenshot.CDPSession")
    @patch("frago.run.screenshot.CDPClient")
    def test_capture_screenshot_error_cleanup(
        self, mock_client_class, mock_session_class, tmp_path
    ):
        """测试错误时清理临时文件"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        # Mock CDP抛出异常
        mock_session = Mock()
        mock_session.capture_screenshot.side_effect = Exception("CDP error")
        mock_session_class.return_value = mock_session

        # 捕获应该失败
        from frago.run.exceptions import FileSystemError

        with pytest.raises(FileSystemError):
            capture_screenshot("test", screenshots_dir)

        # 验证没有残留的临时文件
        temp_files = list(screenshots_dir.glob(".tmp_*"))
        assert len(temp_files) == 0

    @patch("frago.run.screenshot.CDPSession")
    @patch("frago.run.screenshot.CDPClient")
    def test_capture_screenshot_long_description(
        self, mock_client_class, mock_session_class, tmp_path
    ):
        """测试长描述被截断"""
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        mock_session = Mock()
        mock_session.capture_screenshot.return_value = b"data"
        mock_session_class.return_value = mock_session

        long_desc = "这是一个非常非常非常非常非常非常长的描述" * 10
        file_path, _ = capture_screenshot(long_desc, screenshots_dir)

        # 文件名不应该太长(序号3位 + 下划线 + 描述<=40 + .png)
        assert len(file_path.name) <= 50
