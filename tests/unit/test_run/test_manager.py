"""单元测试 - RunManager

测试run实例的创建、查找、列表、归档功能
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

from frago.run.manager import RunManager
from frago.run.models import RunStatus
from frago.run.exceptions import RunNotFoundError, InvalidRunIDError


@pytest.fixture
def temp_runs_dir(tmp_path):
    """创建临时runs目录"""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    return runs_dir


@pytest.fixture
def manager(temp_runs_dir):
    """创建RunManager实例"""
    return RunManager(temp_runs_dir)


class TestCreateRun:
    """测试create_run方法"""

    def test_create_run_success(self, manager, temp_runs_dir):
        """测试成功创建run"""
        instance = manager.create_run("测试任务")

        # 验证返回值
        assert instance.run_id == "ce-shi-ren-wu"
        assert instance.theme_description == "测试任务"
        assert instance.status == RunStatus.ACTIVE

        # 验证目录结构
        run_dir = temp_runs_dir / instance.run_id
        assert run_dir.exists()
        assert (run_dir / "logs").exists()
        assert (run_dir / "screenshots").exists()
        assert (run_dir / "scripts").exists()
        assert (run_dir / "outputs").exists()

        # 验证元数据文件
        metadata_file = run_dir / ".metadata.json"
        assert metadata_file.exists()
        metadata = json.loads(metadata_file.read_text())
        assert metadata["run_id"] == instance.run_id
        assert metadata["theme_description"] == "测试任务"

    def test_create_run_with_custom_id(self, manager, temp_runs_dir):
        """测试使用自定义run_id创建"""
        instance = manager.create_run("测试", run_id="custom-id")

        assert instance.run_id == "custom-id"
        assert (temp_runs_dir / "custom-id").exists()

    def test_create_run_invalid_id(self, manager):
        """测试无效的run_id格式"""
        with pytest.raises(InvalidRunIDError):
            manager.create_run("测试", run_id="Invalid_ID_With_Underscore")

        with pytest.raises(InvalidRunIDError):
            manager.create_run("测试", run_id="A" * 51)  # 超过50字符


class TestFindRun:
    """测试find_run方法"""

    def test_find_run_success(self, manager):
        """测试成功查找run"""
        created = manager.create_run("查找测试")
        found = manager.find_run(created.run_id)

        assert found.run_id == created.run_id
        assert found.theme_description == created.theme_description

    def test_find_run_not_found(self, manager):
        """测试查找不存在的run"""
        with pytest.raises(RunNotFoundError) as exc:
            manager.find_run("non-existent-id")

        assert "non-existent-id" in str(exc.value)


class TestListRuns:
    """测试list_runs方法"""

    def test_list_runs_empty(self, manager):
        """测试空列表"""
        runs = manager.list_runs()
        assert runs == []

    def test_list_runs_multiple(self, manager):
        """测试列出多个run"""
        manager.create_run("任务1")
        manager.create_run("任务2")
        manager.create_run("任务3")

        runs = manager.list_runs()
        assert len(runs) == 3
        assert all("run_id" in r for r in runs)
        assert all("theme_description" in r for r in runs)
        assert all("log_count" in r for r in runs)

    def test_list_runs_filter_status(self, manager):
        """测试按状态过滤"""
        run1 = manager.create_run("活跃任务")
        run2 = manager.create_run("待归档任务")

        # 归档一个run
        manager.archive_run(run2.run_id)

        # 仅列出活跃的
        active_runs = manager.list_runs(status=RunStatus.ACTIVE)
        assert len(active_runs) == 1
        assert active_runs[0]["run_id"] == run1.run_id

        # 仅列出归档的
        archived_runs = manager.list_runs(status=RunStatus.ARCHIVED)
        assert len(archived_runs) == 1
        assert archived_runs[0]["run_id"] == run2.run_id

    def test_list_runs_sorted_by_time(self, manager):
        """测试按最后访问时间排序"""
        import time

        run1 = manager.create_run("任务1")
        time.sleep(0.1)
        run2 = manager.create_run("任务2")

        runs = manager.list_runs()
        # 最近的在前
        assert runs[0]["run_id"] == run2.run_id
        assert runs[1]["run_id"] == run1.run_id


class TestArchiveRun:
    """测试archive_run方法"""

    def test_archive_run_success(self, manager, temp_runs_dir):
        """测试成功归档"""
        instance = manager.create_run("待归档")
        archived = manager.archive_run(instance.run_id)

        assert archived.status == RunStatus.ARCHIVED

        # 验证元数据文件更新
        metadata_file = temp_runs_dir / instance.run_id / ".metadata.json"
        metadata = json.loads(metadata_file.read_text())
        assert metadata["status"] == "archived"

    def test_archive_run_not_found(self, manager):
        """测试归档不存在的run"""
        with pytest.raises(RunNotFoundError):
            manager.archive_run("non-existent")


class TestGetRunStatistics:
    """测试get_run_statistics方法"""

    def test_statistics_empty_run(self, manager):
        """测试空run的统计"""
        instance = manager.create_run("统计测试")
        stats = manager.get_run_statistics(instance.run_id)

        assert stats["log_entries"] == 0
        assert stats["screenshots"] == 0
        assert stats["scripts"] == 0
        assert stats["disk_usage_bytes"] > 0  # 至少有.metadata.json

    def test_statistics_with_files(self, manager, temp_runs_dir):
        """测试包含文件的run统计"""
        instance = manager.create_run("文件测试")
        run_dir = temp_runs_dir / instance.run_id

        # 创建测试文件
        (run_dir / "screenshots" / "001_test.png").write_bytes(b"fake image")
        (run_dir / "scripts" / "test.py").write_text("print('test')")
        (run_dir / "logs" / "execution.jsonl").write_text('{"test": "log"}\n')

        stats = manager.get_run_statistics(instance.run_id)

        assert stats["screenshots"] == 1
        assert stats["scripts"] == 1
        # log_count通过logger.count_logs()计算,需要有效的JSONL格式
        assert stats["disk_usage_bytes"] > 100
