"""集成测试 - 多run实例管理

测试创建多个run、切换上下文、互不干扰
"""

import pytest
from pathlib import Path

from frago.run.manager import RunManager
from frago.run.context import ContextManager
from frago.run.logger import RunLogger
from frago.run.models import ActionType, ExecutionMethod, LogStatus


@pytest.fixture
def temp_project(tmp_path):
    """创建临时项目环境"""
    project_root = tmp_path / "project"
    project_root.mkdir()

    projects_dir = project_root / "runs"
    projects_dir.mkdir()

    return {
        "root": project_root,
        "projects_dir": projects_dir,
    }


class TestMultipleRuns:
    """测试多个run实例的管理"""

    def test_create_multiple_runs(self, temp_project):
        """测试创建多个run"""
        projects_dir = temp_project["projects_dir"]
        manager = RunManager(projects_dir)

        # 创建3个不同的run
        run1 = manager.create_run("任务1: Python开发")
        run2 = manager.create_run("任务2: 数据分析")
        run3 = manager.create_run("任务3: 前端开发")

        # 验证都被创建
        assert run1.run_id != run2.run_id != run3.run_id
        assert (projects_dir / run1.run_id).exists()
        assert (projects_dir / run2.run_id).exists()
        assert (projects_dir / run3.run_id).exists()

        # 验证可以列出所有run
        all_runs = manager.list_runs()
        assert len(all_runs) == 3

    def test_switch_context_between_runs(self, temp_project):
        """测试在多个run之间切换上下文"""
        project_root = temp_project["root"]
        projects_dir = temp_project["projects_dir"]

        manager = RunManager(projects_dir)
        context_mgr = ContextManager(project_root, projects_dir)

        # 创建两个run
        run1 = manager.create_run("Run 1")
        run2 = manager.create_run("Run 2")

        # 设置为run1
        context_mgr.set_current_project(run1.run_id, run1.theme_description)
        assert context_mgr.get_current_project().run_id == run1.run_id

        # 切换到run2
        context_mgr.set_current_project(run2.run_id, run2.theme_description)
        assert context_mgr.get_current_project().run_id == run2.run_id

        # 再切换回run1
        context_mgr.set_current_project(run1.run_id, run1.theme_description)
        assert context_mgr.get_current_project().run_id == run1.run_id

    def test_logs_isolated_between_runs(self, temp_project):
        """测试不同run的日志互相隔离"""
        projects_dir = temp_project["projects_dir"]
        manager = RunManager(projects_dir)

        # 创建两个run
        run1 = manager.create_run("Run 1")
        run2 = manager.create_run("Run 2")

        # 分别记录日志
        logger1 = RunLogger(projects_dir / run1.run_id)
        logger1.write_log("Run1的日志", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})
        logger1.write_log("Run1的第二条", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        logger2 = RunLogger(projects_dir / run2.run_id)
        logger2.write_log("Run2的日志", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证日志隔离
        logs1 = logger1.read_logs()
        logs2 = logger2.read_logs()

        assert len(logs1) == 2
        assert len(logs2) == 1
        assert logs1[0].step == "Run1的日志"
        assert logs2[0].step == "Run2的日志"

    def test_statistics_independent(self, temp_project):
        """测试不同run的统计独立"""
        projects_dir = temp_project["projects_dir"]
        manager = RunManager(projects_dir)

        run1 = manager.create_run("Run 1")
        run2 = manager.create_run("Run 2")

        # Run1: 记录2条日志
        logger1 = RunLogger(projects_dir / run1.run_id)
        logger1.write_log("日志1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})
        logger1.write_log("日志2", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # Run2: 记录5条日志
        logger2 = RunLogger(projects_dir / run2.run_id)
        for i in range(5):
            logger2.write_log(f"日志{i}", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证统计独立
        stats1 = manager.get_run_statistics(run1.run_id)
        stats2 = manager.get_run_statistics(run2.run_id)

        assert stats1["log_entries"] == 2
        assert stats2["log_entries"] == 5

    def test_archive_does_not_affect_others(self, temp_project):
        """测试归档一个run不影响其他run"""
        projects_dir = temp_project["projects_dir"]
        manager = RunManager(projects_dir)

        run1 = manager.create_run("Active Run")
        run2 = manager.create_run("To Archive")
        run3 = manager.create_run("Another Active")

        # 归档run2
        manager.archive_run(run2.run_id)

        # 验证run1和run3仍然活跃
        all_runs = manager.list_runs()
        active_runs = [r for r in all_runs if r["status"] == "active"]
        archived_runs = [r for r in all_runs if r["status"] == "archived"]

        assert len(active_runs) == 2
        assert len(archived_runs) == 1
        assert run2.run_id in [r["run_id"] for r in archived_runs]

    def test_concurrent_access_safe(self, temp_project):
        """测试并发访问安全性(文件系统层面)"""
        projects_dir = temp_project["projects_dir"]

        # 创建两个独立的manager实例(模拟并发)
        manager1 = RunManager(projects_dir)
        manager2 = RunManager(projects_dir)

        # 两个manager同时创建run
        run1 = manager1.create_run("Manager1的Run")
        run2 = manager2.create_run("Manager2的Run")

        # 验证都成功创建且不冲突
        assert run1.run_id != run2.run_id

        # 两个manager都能列出所有run
        runs_from_m1 = manager1.list_runs()
        runs_from_m2 = manager2.list_runs()

        assert len(runs_from_m1) == len(runs_from_m2) == 2


class TestRunFiltering:
    """测试run过滤和查询"""

    def test_filter_by_status(self, temp_project):
        """测试按状态过滤"""
        projects_dir = temp_project["projects_dir"]
        manager = RunManager(projects_dir)

        # 创建多个run并归档部分
        run1 = manager.create_run("Active 1")
        run2 = manager.create_run("To Archive 1")
        run3 = manager.create_run("Active 2")
        run4 = manager.create_run("To Archive 2")

        manager.archive_run(run2.run_id)
        manager.archive_run(run4.run_id)

        # 过滤活跃的
        from frago.run.models import RunStatus

        active_runs = manager.list_runs(status=RunStatus.ACTIVE)
        assert len(active_runs) == 2
        assert all(r["status"] == "active" for r in active_runs)

        # 过滤归档的
        archived_runs = manager.list_runs(status=RunStatus.ARCHIVED)
        assert len(archived_runs) == 2
        assert all(r["status"] == "archived" for r in archived_runs)

    def test_runs_sorted_by_time(self, temp_project):
        """测试run按时间排序"""
        import time

        projects_dir = temp_project["projects_dir"]
        manager = RunManager(projects_dir)

        # 按顺序创建
        run1 = manager.create_run("First")
        time.sleep(0.1)
        run2 = manager.create_run("Second")
        time.sleep(0.1)
        run3 = manager.create_run("Third")

        # 列表应该按最后访问时间降序
        all_runs = manager.list_runs()
        assert all_runs[0]["run_id"] == run3.run_id  # 最新的在前
        assert all_runs[-1]["run_id"] == run1.run_id  # 最旧的在后
