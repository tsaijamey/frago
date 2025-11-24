"""集成测试 - Run完整生命周期

测试: init → set-context → log → screenshot → archive 的完整流程
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

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


class TestRunLifecycle:
    """测试完整的run生命周期"""

    def test_full_lifecycle(self, temp_project):
        """测试完整流程: 创建 -> 设置上下文 -> 记录日志 -> 归档"""
        project_root = temp_project["root"]
        projects_dir = temp_project["projects_dir"]

        # 1. 初始化manager和context
        manager = RunManager(projects_dir)
        context_mgr = ContextManager(project_root, projects_dir)

        # 2. 创建run (模拟 `uv run frago run init`)
        instance = manager.create_run("测试任务生命周期")
        assert instance.run_id is not None
        assert (projects_dir / instance.run_id).exists()

        # 3. 设置上下文 (模拟 `uv run frago run set-context`)
        context = context_mgr.set_current_project(instance.run_id, instance.theme_description)
        assert context.run_id == instance.run_id

        # 4. 记录日志 (模拟 `uv run frago run log`)
        run_dir = projects_dir / instance.run_id
        logger = RunLogger(run_dir)

        log1 = logger.write_log(
            "导航到测试页面",
            LogStatus.SUCCESS,
            ActionType.NAVIGATION,
            ExecutionMethod.COMMAND,
            {"url": "https://example.com"},
        )
        assert log1 is not None

        log2 = logger.write_log(
            "提取数据",
            LogStatus.SUCCESS,
            ActionType.EXTRACTION,
            ExecutionMethod.RECIPE,
            {"items": ["item1", "item2"]},
        )
        assert log2 is not None

        # 5. 验证日志持久化
        logs = logger.read_logs()
        assert len(logs) == 2
        assert logs[0].step == "导航到测试页面"
        assert logs[1].step == "提取数据"

        # 6. 查看run详情 (模拟 `uv run frago run info`)
        stats = manager.get_run_statistics(instance.run_id)
        assert stats["log_entries"] == 2

        # 7. 归档run (模拟 `uv run frago run archive`)
        archived = manager.archive_run(instance.run_id)
        assert archived.status.value == "archived"

        # 8. 验证归档后仍可读取日志
        logs_after = logger.read_logs()
        assert len(logs_after) == 2

    def test_lifecycle_with_screenshots(self, temp_project):
        """测试包含截图的生命周期"""
        project_root = temp_project["root"]
        projects_dir = temp_project["projects_dir"]

        manager = RunManager(projects_dir)
        context_mgr = ContextManager(project_root, projects_dir)

        # 创建run
        instance = manager.create_run("截图测试")
        context_mgr.set_current_project(instance.run_id, instance.theme_description)

        run_dir = projects_dir / instance.run_id
        logger = RunLogger(run_dir)

        # 模拟截图 (不实际调用CDP)
        screenshots_dir = run_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        (screenshots_dir / "001_test-page.png").write_bytes(b"fake image")

        # 记录截图日志
        logger.write_log(
            "截图: 测试页面",
            LogStatus.SUCCESS,
            ActionType.SCREENSHOT,
            ExecutionMethod.COMMAND,
            {"file_path": "screenshots/001_test-page.png", "sequence_number": 1},
        )

        # 验证统计
        stats = manager.get_run_statistics(instance.run_id)
        assert stats["screenshots"] == 1
        assert stats["log_entries"] == 1

    def test_lifecycle_with_scripts(self, temp_project):
        """测试包含脚本文件的生命周期"""
        project_root = temp_project["root"]
        projects_dir = temp_project["projects_dir"]

        manager = RunManager(projects_dir)
        instance = manager.create_run("脚本测试")

        run_dir = projects_dir / instance.run_id
        logger = RunLogger(run_dir)

        # 创建脚本文件
        scripts_dir = run_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        script_path = scripts_dir / "process_data.py"
        script_path.write_text("print('processing')")

        # 记录脚本执行
        logger.write_log(
            "执行数据处理脚本",
            LogStatus.SUCCESS,
            ActionType.DATA_PROCESSING,
            ExecutionMethod.FILE,
            {
                "file": "scripts/process_data.py",
                "language": "python",
                "command": "python scripts/process_data.py",
                "exit_code": 0,
            },
        )

        # 验证统计
        stats = manager.get_run_statistics(instance.run_id)
        assert stats["scripts"] == 1

    def test_lifecycle_multiple_sessions(self, temp_project):
        """测试跨会话的生命周期(模拟重启)"""
        project_root = temp_project["root"]
        projects_dir = temp_project["projects_dir"]

        # Session 1: 创建run并记录日志
        manager1 = RunManager(projects_dir)
        instance = manager1.create_run("多会话测试")

        logger1 = RunLogger(projects_dir / instance.run_id)
        logger1.write_log("会话1日志", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # Session 2: 模拟重启,重新加载manager
        manager2 = RunManager(projects_dir)
        found = manager2.find_run(instance.run_id)
        assert found.run_id == instance.run_id

        logger2 = RunLogger(projects_dir / instance.run_id)
        logger2.write_log("会话2日志", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证日志累积
        logs = logger2.read_logs()
        assert len(logs) == 2
        assert logs[0].step == "会话1日志"
        assert logs[1].step == "会话2日志"

    def test_lifecycle_error_handling(self, temp_project):
        """测试生命周期中的错误处理"""
        project_root = temp_project["root"]
        projects_dir = temp_project["projects_dir"]

        manager = RunManager(projects_dir)
        context_mgr = ContextManager(project_root, projects_dir)

        # 创建run
        instance = manager.create_run("错误处理测试")
        context_mgr.set_current_project(instance.run_id, instance.theme_description)

        logger = RunLogger(projects_dir / instance.run_id)

        # 记录成功和失败的步骤
        logger.write_log("步骤1: 成功", LogStatus.SUCCESS, ActionType.NAVIGATION, ExecutionMethod.COMMAND, {})
        logger.write_log(
            "步骤2: 失败",
            LogStatus.ERROR,
            ActionType.EXTRACTION,
            ExecutionMethod.RECIPE,
            {"error": "连接超时"},
        )
        logger.write_log("步骤3: 警告", LogStatus.WARNING, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证所有日志都被记录
        logs = logger.read_logs()
        assert len(logs) == 3
        assert logs[0].status == LogStatus.SUCCESS
        assert logs[1].status == LogStatus.ERROR
        assert logs[2].status == LogStatus.WARNING
