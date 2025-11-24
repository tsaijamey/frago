"""单元测试 - RunLogger

测试日志记录、读取、schema验证功能
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

from frago.run.logger import RunLogger
from frago.run.models import ActionType, ExecutionMethod, LogStatus
from frago.run.exceptions import FileSystemError


@pytest.fixture
def temp_run_dir(tmp_path):
    """创建临时run目录"""
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    return run_dir


@pytest.fixture
def logger(temp_run_dir):
    """创建RunLogger实例"""
    return RunLogger(temp_run_dir)


class TestWriteLog:
    """测试write_log方法"""

    def test_write_log_success(self, logger, temp_run_dir):
        """测试成功写入日志"""
        entry = logger.write_log(
            step="测试步骤",
            status=LogStatus.SUCCESS,
            action_type=ActionType.ANALYSIS,
            execution_method=ExecutionMethod.MANUAL,
            data={"key": "value"},
        )

        # 验证返回值
        assert entry.step == "测试步骤"
        assert entry.status == LogStatus.SUCCESS
        assert entry.action_type == ActionType.ANALYSIS
        assert entry.execution_method == ExecutionMethod.MANUAL
        assert entry.data == {"key": "value"}
        assert entry.schema_version == "1.0"

        # 验证文件写入
        log_file = temp_run_dir / "logs" / "execution.jsonl"
        assert log_file.exists()

        # 验证JSONL格式
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        log_data = json.loads(lines[0])
        assert log_data["step"] == "测试步骤"
        assert log_data["status"] == "success"

    def test_write_log_multiple_entries(self, logger, temp_run_dir):
        """测试追加多条日志"""
        logger.write_log("步骤1", LogStatus.SUCCESS, ActionType.NAVIGATION, ExecutionMethod.COMMAND, {})
        logger.write_log("步骤2", LogStatus.ERROR, ActionType.EXTRACTION, ExecutionMethod.RECIPE, {})
        logger.write_log("步骤3", LogStatus.WARNING, ActionType.SCREENSHOT, ExecutionMethod.FILE, {})

        log_file = temp_run_dir / "logs" / "execution.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_write_log_chinese_support(self, logger, temp_run_dir):
        """测试中文字符支持"""
        entry = logger.write_log(
            step="导航到百度搜索",
            status=LogStatus.SUCCESS,
            action_type=ActionType.NAVIGATION,
            execution_method=ExecutionMethod.COMMAND,
            data={"url": "https://baidu.com", "中文键": "中文值"},
        )

        log_file = temp_run_dir / "logs" / "execution.jsonl"
        content = log_file.read_text()
        log_data = json.loads(content.strip())

        assert log_data["step"] == "导航到百度搜索"
        assert log_data["data"]["中文键"] == "中文值"


class TestReadLogs:
    """测试read_logs方法"""

    def test_read_logs_empty(self, logger):
        """测试读取空日志"""
        logs = logger.read_logs()
        assert logs == []

    def test_read_logs_single_entry(self, logger):
        """测试读取单条日志"""
        logger.write_log("测试", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        logs = logger.read_logs()
        assert len(logs) == 1
        assert logs[0].step == "测试"

    def test_read_logs_with_limit(self, logger):
        """测试限制读取数量"""
        for i in range(10):
            logger.write_log(f"步骤{i}", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        logs = logger.read_logs(limit=5)
        assert len(logs) == 5
        # 应该返回最后5条
        assert logs[-1].step == "步骤9"

    def test_read_logs_skip_corrupted(self, logger, temp_run_dir):
        """测试跳过损坏的日志行"""
        # 写入正常日志
        logger.write_log("正常1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 手动写入损坏的日志
        log_file = temp_run_dir / "logs" / "execution.jsonl"
        with log_file.open("a") as f:
            f.write("这是损坏的JSON\n")

        # 再写入正常日志
        logger.write_log("正常2", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 默认跳过损坏行
        logs = logger.read_logs(skip_corrupted=True)
        assert len(logs) == 2
        assert logs[0].step == "正常1"
        assert logs[1].step == "正常2"


class TestCountLogs:
    """测试count_logs方法"""

    def test_count_logs_empty(self, logger):
        """测试空日志计数"""
        assert logger.count_logs() == 0

    def test_count_logs_multiple(self, logger):
        """测试多条日志计数"""
        for i in range(5):
            logger.write_log(f"步骤{i}", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        assert logger.count_logs() == 5


class TestGetRecentLogs:
    """测试get_recent_logs方法"""

    def test_get_recent_logs_default(self, logger):
        """测试默认获取最近5条"""
        for i in range(10):
            logger.write_log(f"步骤{i}", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        recent = logger.get_recent_logs()
        assert len(recent) == 5
        assert recent[-1].step == "步骤9"

    def test_get_recent_logs_custom_count(self, logger):
        """测试自定义获取数量"""
        for i in range(10):
            logger.write_log(f"步骤{i}", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        recent = logger.get_recent_logs(count=3)
        assert len(recent) == 3


class TestSchemaValidation:
    """测试日志schema验证"""

    def test_valid_action_types(self, logger):
        """测试所有有效的action_type"""
        action_types = [
            ActionType.NAVIGATION,
            ActionType.EXTRACTION,
            ActionType.INTERACTION,
            ActionType.SCREENSHOT,
            ActionType.RECIPE_EXECUTION,
            ActionType.DATA_PROCESSING,
            ActionType.ANALYSIS,
            ActionType.USER_INTERACTION,
            ActionType.OTHER,
        ]

        for action_type in action_types:
            entry = logger.write_log(
                f"测试{action_type.value}",
                LogStatus.SUCCESS,
                action_type,
                ExecutionMethod.MANUAL,
                {},
            )
            assert entry.action_type == action_type

    def test_valid_execution_methods(self, logger):
        """测试所有有效的execution_method"""
        methods = [
            ExecutionMethod.COMMAND,
            ExecutionMethod.RECIPE,
            ExecutionMethod.FILE,
            ExecutionMethod.MANUAL,
            ExecutionMethod.ANALYSIS,
            ExecutionMethod.TOOL,
        ]

        for method in methods:
            entry = logger.write_log(
                f"测试{method.value}",
                LogStatus.SUCCESS,
                ActionType.OTHER,
                method,
                {},
            )
            assert entry.execution_method == method

    def test_schema_version_present(self, logger, temp_run_dir):
        """测试schema_version字段存在"""
        logger.write_log("测试", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        log_file = temp_run_dir / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        assert "schema_version" in log_data
        assert log_data["schema_version"] == "1.0"
