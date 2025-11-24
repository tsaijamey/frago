"""集成测试 - 日志持久化

测试跨会话日志累积、文件读写正确性
"""

import json
import pytest
from pathlib import Path
from datetime import datetime

from frago.run.manager import RunManager
from frago.run.logger import RunLogger
from frago.run.models import ActionType, ExecutionMethod, LogStatus


@pytest.fixture
def temp_runs_dir(tmp_path):
    """创建临时runs目录"""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    return runs_dir


class TestLogPersistence:
    """测试日志持久化功能"""

    def test_logs_survive_restart(self, temp_runs_dir):
        """测试日志在重启后仍然存在"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("持久化测试")

        # Session 1: 写入日志
        logger1 = RunLogger(temp_runs_dir / instance.run_id)
        logger1.write_log("第一条日志", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 模拟重启: 创建新的logger实例
        logger2 = RunLogger(temp_runs_dir / instance.run_id)
        logs = logger2.read_logs()

        assert len(logs) == 1
        assert logs[0].step == "第一条日志"

    def test_logs_append_correctly(self, temp_runs_dir):
        """测试日志正确追加"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("追加测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        # 写入多条日志
        for i in range(10):
            logger.write_log(f"日志{i}", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证所有日志都存在且顺序正确
        logs = logger.read_logs()
        assert len(logs) == 10
        for i, log in enumerate(logs):
            assert log.step == f"日志{i}"

    def test_jsonl_format_valid(self, temp_runs_dir):
        """测试JSONL格式有效性"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("格式测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log("测试日志", LogStatus.SUCCESS, ActionType.NAVIGATION, ExecutionMethod.COMMAND, {"key": "value"})

        # 直接读取文件验证JSONL格式
        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        lines = log_file.read_text().strip().split("\n")

        assert len(lines) == 1

        # 每行都应该是有效的JSON
        for line in lines:
            data = json.loads(line)
            assert "timestamp" in data
            assert "step" in data
            assert "status" in data
            assert "action_type" in data
            assert "execution_method" in data
            assert "data" in data
            assert "schema_version" in data

    def test_large_log_file(self, temp_runs_dir):
        """测试大量日志的持久化"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("大文件测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        # 写入1000条日志
        for i in range(1000):
            logger.write_log(
                f"日志{i}",
                LogStatus.SUCCESS,
                ActionType.ANALYSIS,
                ExecutionMethod.MANUAL,
                {"index": i},
            )

        # 验证计数正确
        count = logger.count_logs()
        assert count == 1000

        # 验证可以读取最后几条
        recent = logger.get_recent_logs(count=10)
        assert len(recent) == 10
        assert recent[-1].step == "日志999"

    def test_log_data_integrity(self, temp_runs_dir):
        """测试日志数据完整性"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("完整性测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        # 写入包含复杂数据的日志
        complex_data = {
            "url": "https://example.com",
            "result": {"items": [1, 2, 3], "total": 3},
            "metadata": {"author": "test", "timestamp": "2025-11-22T10:00:00Z"},
        }

        logger.write_log(
            "复杂数据日志",
            LogStatus.SUCCESS,
            ActionType.EXTRACTION,
            ExecutionMethod.RECIPE,
            complex_data,
        )

        # 读取并验证数据完整
        logs = logger.read_logs()
        assert len(logs) == 1
        assert logs[0].data == complex_data

    def test_chinese_characters_preserved(self, temp_runs_dir):
        """测试中文字符正确保存"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("中文测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        # 写入包含中文的日志
        logger.write_log(
            "导航到百度搜索",
            LogStatus.SUCCESS,
            ActionType.NAVIGATION,
            ExecutionMethod.COMMAND,
            {"url": "https://baidu.com", "关键词": "测试搜索"},
        )

        # 读取并验证中文正确
        logs = logger.read_logs()
        assert logs[0].step == "导航到百度搜索"
        assert logs[0].data["关键词"] == "测试搜索"

        # 验证文件编码正确(UTF-8)
        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        content = log_file.read_text(encoding="utf-8")
        assert "导航到百度搜索" in content
        assert "关键词" in content

    def test_corrupted_log_recovery(self, temp_runs_dir):
        """测试损坏日志的恢复"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("损坏恢复测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        # 写入正常日志
        logger.write_log("正常1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 手动损坏日志文件
        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        with log_file.open("a") as f:
            f.write("这是损坏的数据\n")
            f.write("{不完整的JSON\n")

        # 再写入正常日志
        logger.write_log("正常2", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证可以跳过损坏行
        logs = logger.read_logs(skip_corrupted=True)
        assert len(logs) == 2
        assert logs[0].step == "正常1"
        assert logs[1].step == "正常2"


class TestCrossSessionAccumulation:
    """测试跨会话日志累积"""

    def test_accumulate_across_sessions(self, temp_runs_dir):
        """测试多个会话累积日志"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("累积测试")

        # Session 1
        logger1 = RunLogger(temp_runs_dir / instance.run_id)
        logger1.write_log("会话1-日志1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})
        logger1.write_log("会话1-日志2", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # Session 2 (模拟重启)
        logger2 = RunLogger(temp_runs_dir / instance.run_id)
        logger2.write_log("会话2-日志1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # Session 3 (模拟再次重启)
        logger3 = RunLogger(temp_runs_dir / instance.run_id)
        logger3.write_log("会话3-日志1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})
        logger3.write_log("会话3-日志2", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证所有会话的日志都累积
        logs = logger3.read_logs()
        assert len(logs) == 5
        assert logs[0].step == "会话1-日志1"
        assert logs[4].step == "会话3-日志2"

    def test_timestamp_ordering(self, temp_runs_dir):
        """测试跨会话时间戳顺序"""
        import time

        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("时间戳测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        # 写入带时间间隔的日志
        logger.write_log("日志1", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})
        time.sleep(0.1)
        logger.write_log("日志2", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})
        time.sleep(0.1)
        logger.write_log("日志3", LogStatus.SUCCESS, ActionType.ANALYSIS, ExecutionMethod.MANUAL, {})

        # 验证时间戳递增
        logs = logger.read_logs()
        assert logs[0].timestamp < logs[1].timestamp < logs[2].timestamp
