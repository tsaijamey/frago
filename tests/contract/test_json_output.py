"""契约测试 - JSON输出格式

使用JSON Schema验证list/info/init命令的JSON输出格式
"""

import json
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


class TestInitCommandOutput:
    """测试init命令的JSON输出格式"""

    def test_init_output_structure(self, temp_project_dir):
        """契约: init命令输出包含必需字段"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试任务"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证必需字段
        assert "run_id" in output
        assert "created_at" in output
        assert "path" in output

        # 验证字段类型
        assert isinstance(output["run_id"], str)
        assert isinstance(output["created_at"], str)
        assert isinstance(output["path"], str)

        # 验证run_id格式（小写字母、数字、连字符）
        assert output["run_id"].islower() or "-" in output["run_id"]

        # 验证created_at是ISO 8601格式（包含T分隔符）
        assert "T" in output["created_at"]

    def test_init_with_custom_id_output(self, temp_project_dir):
        """契约: 带自定义ID的init输出包含指定的run_id"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试", "--run-id", "custom-id"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        assert output["run_id"] == "custom-id"


class TestListCommandOutput:
    """测试list命令的JSON输出格式"""

    def test_list_empty_output_structure(self, temp_project_dir):
        """契约: list空列表输出正确的JSON结构"""
        result = subprocess.run(
            ["uv", "run", "frago", "run", "list", "--format", "json"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证根结构
        assert "runs" in output
        assert isinstance(output["runs"], list)
        assert len(output["runs"]) == 0

    def test_list_with_runs_output_structure(self, temp_project_dir):
        """契约: list命令输出包含run列表和所有必需字段"""
        # 创建多个run
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
            ["uv", "run", "frago", "run", "list", "--format", "json"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证根结构
        assert "runs" in output
        assert isinstance(output["runs"], list)
        assert len(output["runs"]) >= 2

        # 验证每个run的字段
        for run in output["runs"]:
            # 必需字段
            assert "run_id" in run
            assert "status" in run
            assert "created_at" in run
            assert "last_accessed" in run
            assert "theme_description" in run
            assert "log_count" in run
            assert "screenshot_count" in run

            # 字段类型
            assert isinstance(run["run_id"], str)
            assert isinstance(run["status"], str)
            assert isinstance(run["created_at"], str)
            assert isinstance(run["last_accessed"], str)
            assert isinstance(run["theme_description"], str)
            assert isinstance(run["log_count"], int)
            assert isinstance(run["screenshot_count"], int)

            # status枚举值
            assert run["status"] in ["active", "archived"]

            # 时间戳格式（ISO 8601）
            assert "T" in run["created_at"]
            assert "T" in run["last_accessed"]

    def test_list_status_filter_output(self, temp_project_dir):
        """契约: list --status过滤输出正确的JSON"""
        # 创建并归档一个run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试1"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "run", "frago", "run", "archive", "ce-shi-1"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        # 创建一个active run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试2"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        # 测试active过滤
        result = subprocess.run(
            ["uv", "run", "frago", "run", "list", "--format", "json", "--status", "active"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证所有返回的run都是active状态
        for run in output["runs"]:
            assert run["status"] == "active"

        # 测试archived过滤
        result = subprocess.run(
            [
                "uv",
                "run",
                "frago",
                "run",
                "list",
                "--format",
                "json",
                "--status",
                "archived",
            ],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证所有返回的run都是archived状态
        for run in output["runs"]:
            assert run["status"] == "archived"


class TestInfoCommandOutput:
    """测试info命令的JSON输出格式"""

    def test_info_output_structure(self, temp_project_dir):
        """契约: info命令输出包含所有必需字段"""
        # 创建run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试任务"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        # 设置上下文并记录日志
        subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "ce-shi-ren-wu"],
            cwd=temp_project_dir,
            capture_output=True,
        )
        subprocess.run(
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

        result = subprocess.run(
            ["uv", "run", "frago", "run", "info", "ce-shi-ren-wu", "--format", "json"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证必需字段
        assert "run_id" in output
        assert "status" in output
        assert "theme_description" in output
        assert "created_at" in output
        assert "last_accessed" in output
        assert "statistics" in output
        assert "recent_logs" in output

        # 验证字段类型
        assert isinstance(output["run_id"], str)
        assert isinstance(output["status"], str)
        assert isinstance(output["theme_description"], str)
        assert isinstance(output["created_at"], str)
        assert isinstance(output["last_accessed"], str)
        assert isinstance(output["statistics"], dict)
        assert isinstance(output["recent_logs"], list)

        # 验证statistics字段
        stats = output["statistics"]
        assert "log_entries" in stats or "log_count" in stats  # 兼容不同字段名
        assert "screenshots" in stats or "screenshot_count" in stats
        assert "scripts" in stats or "script_count" in stats
        assert "disk_usage_bytes" in stats

        # 验证类型（使用实际存在的字段名）
        log_key = "log_entries" if "log_entries" in stats else "log_count"
        screenshot_key = "screenshots" if "screenshots" in stats else "screenshot_count"
        script_key = "scripts" if "scripts" in stats else "script_count"

        assert isinstance(stats[log_key], int)
        assert isinstance(stats[screenshot_key], int)
        assert isinstance(stats[script_key], int)
        assert isinstance(stats["disk_usage_bytes"], int)

        # 验证recent_logs结构
        if len(output["recent_logs"]) > 0:
            log = output["recent_logs"][0]
            assert "timestamp" in log
            assert "step" in log
            assert "status" in log
            assert "action_type" in log
            assert "execution_method" in log


class TestSetContextCommandOutput:
    """测试set-context命令的JSON输出格式"""

    def test_set_context_output_structure(self, temp_project_dir):
        """契约: set-context命令输出包含必需字段"""
        # 创建run
        subprocess.run(
            ["uv", "run", "frago", "run", "init", "测试"],
            cwd=temp_project_dir,
            capture_output=True,
        )

        result = subprocess.run(
            ["uv", "run", "frago", "run", "set-context", "ce-shi"],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证必需字段
        assert "run_id" in output
        assert "theme_description" in output
        assert "set_at" in output

        # 验证字段类型
        assert isinstance(output["run_id"], str)
        assert isinstance(output["theme_description"], str)
        assert isinstance(output["set_at"], str)

        # 验证set_at是ISO 8601格式
        assert "T" in output["set_at"]


class TestArchiveCommandOutput:
    """测试archive命令的JSON输出格式"""

    def test_archive_output_structure(self, temp_project_dir):
        """契约: archive命令输出包含必需字段"""
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
            text=True,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # 验证必需字段
        assert "run_id" in output
        assert "archived_at" in output
        assert "previous_status" in output

        # 验证字段类型
        assert isinstance(output["run_id"], str)
        assert isinstance(output["archived_at"], str)
        assert isinstance(output["previous_status"], str)

        # 验证archived_at是ISO 8601格式
        assert "T" in output["archived_at"]

        # 验证previous_status是有效的状态
        assert output["previous_status"] in ["active", "archived"]
