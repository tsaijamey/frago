"""单元测试 - utils

测试主题slug生成、中文处理、路径工具等
"""

import pytest
from pathlib import Path

from frago.run.utils import (
    generate_theme_slug,
    is_valid_run_id,
    scan_run_directories,
    ensure_directory_exists,
)


class TestGenerateThemeSlug:
    """测试generate_theme_slug函数"""

    def test_slug_preserves_english(self):
        """测试保留英文单词"""
        slug = generate_theme_slug("upwork python jobs search")
        assert slug == "upwork-python-jobs-search"

    def test_slug_english(self):
        """测试纯英文"""
        slug = generate_theme_slug("Find Python Jobs on Upwork")
        assert slug == "find-python-jobs-on-upwork"

    def test_slug_mixed(self):
        """测试中英文混合"""
        slug = generate_theme_slug("测试Task 123")
        assert "ce-shi-task" in slug
        assert "123" in slug

    def test_slug_special_characters(self):
        """测试特殊字符处理"""
        slug = generate_theme_slug("任务@#$%标题!!!")
        assert "@" not in slug
        assert "#" not in slug
        assert "!" not in slug

    def test_slug_max_length(self):
        """测试长度限制"""
        long_description = "这是一个非常非常非常非常非常非常长的任务描述" * 5
        slug = generate_theme_slug(long_description, max_length=50)
        assert len(slug) <= 50

    def test_slug_empty_fallback(self):
        """测试纯符号输入回退到timestamp"""
        slug = generate_theme_slug("@#$%^&*()")
        assert slug.startswith("task-")
        assert slug[5:].isdigit()

    def test_slug_lowercase(self):
        """测试结果为小写"""
        slug = generate_theme_slug("ABC DEF")
        assert slug.islower()

    def test_slug_no_spaces(self):
        """测试无空格"""
        slug = generate_theme_slug("测试 空格 处理")
        assert " " not in slug
        assert "-" in slug


class TestIsValidRunId:
    """测试is_valid_run_id函数"""

    def test_valid_run_ids(self):
        """测试有效的run_id"""
        valid_ids = [
            "abc",
            "test-123",
            "a-b-c-d-e",
            "123",
            "a" * 50,  # 最大长度
        ]

        for run_id in valid_ids:
            assert is_valid_run_id(run_id) is True

    def test_invalid_run_ids(self):
        """测试无效的run_id"""
        invalid_ids = [
            "",  # 空字符串
            "a" * 51,  # 超过50字符
            "ABC",  # 大写字母
            "test_id",  # 下划线
            "test id",  # 空格
            "test@id",  # 特殊字符
            "中文id",  # 中文字符
        ]

        for run_id in invalid_ids:
            assert is_valid_run_id(run_id) is False


class TestScanRunDirectories:
    """测试scan_run_directories函数"""

    def test_scan_empty_directory(self, tmp_path):
        """测试空目录"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run_ids = scan_run_directories(runs_dir)
        assert run_ids == []

    def test_scan_multiple_runs(self, tmp_path):
        """测试扫描多个run"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # 创建有效的run目录
        (runs_dir / "test-1").mkdir()
        (runs_dir / "test-2").mkdir()
        (runs_dir / "test-3").mkdir()

        run_ids = scan_run_directories(runs_dir)
        assert len(run_ids) == 3
        assert "test-1" in run_ids
        assert "test-2" in run_ids
        assert "test-3" in run_ids

    def test_scan_ignores_invalid_ids(self, tmp_path):
        """测试忽略无效的run_id"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # 创建有效和无效的目录
        (runs_dir / "valid-run").mkdir()
        (runs_dir / "Invalid_Run").mkdir()  # 无效(大写+下划线)
        (runs_dir / "中文run").mkdir()  # 无效(中文)

        run_ids = scan_run_directories(runs_dir)
        assert len(run_ids) == 1
        assert "valid-run" in run_ids

    def test_scan_ignores_files(self, tmp_path):
        """测试忽略文件"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # 创建目录和文件
        (runs_dir / "valid-run").mkdir()
        (runs_dir / "some-file.txt").touch()

        run_ids = scan_run_directories(runs_dir)
        assert len(run_ids) == 1
        assert "valid-run" in run_ids

    def test_scan_sorted_by_mtime(self, tmp_path):
        """测试按修改时间排序"""
        import time

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # 按顺序创建目录
        (runs_dir / "run-1").mkdir()
        time.sleep(0.1)
        (runs_dir / "run-2").mkdir()
        time.sleep(0.1)
        (runs_dir / "run-3").mkdir()

        run_ids = scan_run_directories(runs_dir)
        # 最近的在前
        assert run_ids[0] == "run-3"
        assert run_ids[-1] == "run-1"

    def test_scan_nonexistent_directory(self, tmp_path):
        """测试不存在的目录"""
        runs_dir = tmp_path / "nonexistent"

        run_ids = scan_run_directories(runs_dir)
        assert run_ids == []


class TestEnsureDirectoryExists:
    """测试ensure_directory_exists函数"""

    def test_create_directory(self, tmp_path):
        """测试创建目录"""
        new_dir = tmp_path / "new_directory"
        assert not new_dir.exists()

        ensure_directory_exists(new_dir)
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_create_nested_directories(self, tmp_path):
        """测试创建嵌套目录"""
        nested_dir = tmp_path / "level1" / "level2" / "level3"
        assert not nested_dir.exists()

        ensure_directory_exists(nested_dir)
        assert nested_dir.exists()

    def test_existing_directory(self, tmp_path):
        """测试已存在的目录"""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()

        # 不应该报错
        ensure_directory_exists(existing_dir)
        assert existing_dir.exists()

    def test_permission_error(self, tmp_path):
        """测试权限错误(需要mock)"""
        from frago.run.exceptions import FileSystemError

        # 创建只读目录
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # 只读

        new_dir = readonly_dir / "subdir"

        try:
            with pytest.raises(FileSystemError):
                ensure_directory_exists(new_dir)
        finally:
            # 恢复权限以便清理
            readonly_dir.chmod(0o755)
