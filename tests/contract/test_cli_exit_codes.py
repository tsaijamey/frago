"""契约测试 - CLI命令退出码

验证所有run命令的退出码符合Unix标准：
- 成功: 退出码0
- 失败: 退出码非0（通常为1）
"""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def temp_project_dir(tmp_path):
    """创建临时项目目录"""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    runs_dir = project_dir / "runs"
    runs_dir.mkdir()
    return project_dir


class TestInitCommand:
    """测试init命令退出码"""

    def test_init_success_exit_code(self, temp_project_dir):
        """契约: init成功返回退出码0"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试任务"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_init_with_custom_id_success(self, temp_project_dir):
        """契约: 带自定义ID的init成功返回退出码0"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试任务", "--run-id", "custom-id"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_init_invalid_run_id_failure(self, temp_project_dir):
        """契约: 无效run_id返回非零退出码"""
        result = subprocess.run(
            [
                "uv",
                "run",
                "frago",
                "run",
                "init",
                "测试",
                "--run-id",
                "INVALID_ID",
            ],  # 大写无效
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0


class TestSetContextCommand:
    """测试set-context命令退出码"""

    def test_set_context_success_exit_code(self, temp_project_dir):
        """契约: set-context成功返回退出码0"""
        # 先创建run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        # 设置上下文
        result = subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_set_context_nonexistent_run_failure(self, temp_project_dir):
        """契约: 不存在的run_id返回非零退出码"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "nonexistent-run"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0


class TestListCommand:
    """测试list命令退出码"""

    def test_list_empty_success_exit_code(self, temp_project_dir):
        """契约: list空列表返回退出码0"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "list"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_list_with_runs_success(self, temp_project_dir):
        """契约: list有run的情况返回退出码0"""
        # 创建run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试1"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试2"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            ["uv", "run", "frago", "run", "list"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_list_json_format_success(self, temp_project_dir):
        """契约: list --format json返回退出码0"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "list", "--format", "json"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0


class TestInfoCommand:
    """测试info命令退出码"""

    def test_info_existing_run_success(self, temp_project_dir):
        """契约: info存在的run返回退出码0"""
        # 创建run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            ["uv", "run", "frago", "run", "info", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_info_nonexistent_run_failure(self, temp_project_dir):
        """契约: info不存在的run返回非零退出码"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "info", "nonexistent-run"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0


class TestArchiveCommand:
    """测试archive命令退出码"""

    def test_archive_existing_run_success(self, temp_project_dir):
        """契约: archive存在的run返回退出码0"""
        # 创建run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            ["uv", "run", "frago", "run", "archive", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_archive_nonexistent_run_failure(self, temp_project_dir):
        """契约: archive不存在的run返回非零退出码"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "archive", "nonexistent-run"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0


class TestLogCommand:
    """测试log命令退出码"""

    def test_log_with_context_success(self, temp_project_dir):
        """契约: log命令在有上下文时返回退出码0"""
        # 创建run并设置上下文
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            [
                "uv",
                "run",
                "frago",
                "run",
                "log",
                "--step",
                "测试步骤",
                "--status",
                "success",
                "--action-type",
                "analysis",
                "--execution-method",
                "manual",
                "--data",
                "{}",
            ],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_log_without_context_failure(self, temp_project_dir):
        """契约: log命令在无上下文时返回非零退出码"""
        result = subprocess.run(
            [
                "uv",
                "run",
                "frago",
                "run",
                "log",
                "--step",
                "测试",
                "--status",
                "success",
                "--action-type",
                "analysis",
                "--execution-method",
                "manual",
                "--data",
                "{}",
            ],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0

    def test_log_invalid_enum_failure(self, temp_project_dir):
        """契约: log命令使用无效枚举值返回非零退出码"""
        # 创建run并设置上下文
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            [
                "uv",
                "run",
                "frago",
                "run",
                "log",
                "--step",
                "测试",
                "--status",
                "invalid_status",  # 无效枚举值
                "--action-type",
                "analysis",
                "--execution-method",
                "manual",
                "--data",
                "{}",
            ],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0


class TestScreenshotCommand:
    """测试screenshot命令退出码"""

    @pytest.mark.skip(reason="screenshot需要CDP连接，集成测试覆盖")
    def test_screenshot_with_context_success(self, temp_project_dir):
        """契约: screenshot命令在有上下文时返回退出码0"""
        # 创建run并设置上下文
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            ["uv", "run", "frago", "run", "screenshot", "测试截图"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode == 0

    def test_screenshot_without_context_failure(self, temp_project_dir):
        """契约: screenshot命令在无上下文时返回非零退出码"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "screenshot", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        assert result.returncode != 0
