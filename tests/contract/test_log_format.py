"""契约测试 - log命令JSONL格式

验证所有必需字段、枚举值、schema_version符合契约
"""

import json
import pytest
from pathlib import Path

from frago.run.manager import RunManager
from frago.run.logger import RunLogger
from frago.run.models import ActionType, ExecutionMethod, LogStatus


@pytest.fixture
def temp_runs_dir(tmp_path):
    """创建临时runs目录"""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    return runs_dir


class TestLogFormatContract:
    """测试log命令的JSONL格式契约"""

    def test_required_fields_present(self, temp_runs_dir):
        """契约: 所有必需字段必须存在"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("契约测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log(
            "测试步骤",
            LogStatus.SUCCESS,
            ActionType.NAVIGATION,
            ExecutionMethod.COMMAND,
            {"test": "data"},
        )

        # 读取JSONL文件
        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        # 验证必需字段
        required_fields = [
            "timestamp",
            "step",
            "status",
            "action_type",
            "execution_method",
            "data",
            "schema_version",
        ]

        for field in required_fields:
            assert field in log_data, f"缺少必需字段: {field}"

    def test_field_types_correct(self, temp_runs_dir):
        """契约: 字段类型必须正确"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("类型测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log(
            "测试",
            LogStatus.SUCCESS,
            ActionType.ANALYSIS,
            ExecutionMethod.MANUAL,
            {"key": "value"},
        )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        # 验证类型
        assert isinstance(log_data["timestamp"], str)
        assert isinstance(log_data["step"], str)
        assert isinstance(log_data["status"], str)
        assert isinstance(log_data["action_type"], str)
        assert isinstance(log_data["execution_method"], str)
        assert isinstance(log_data["data"], dict)
        assert isinstance(log_data["schema_version"], str)

    def test_status_enum_values(self, temp_runs_dir):
        """契约: status必须是枚举值之一"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("状态枚举测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        valid_statuses = ["success", "error", "warning"]

        for status_value in [LogStatus.SUCCESS, LogStatus.ERROR, LogStatus.WARNING]:
            logger.write_log(
                f"测试{status_value.value}",
                status_value,
                ActionType.ANALYSIS,
                ExecutionMethod.MANUAL,
                {},
            )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        lines = log_file.read_text().strip().split("\n")

        for line in lines:
            log_data = json.loads(line)
            assert log_data["status"] in valid_statuses

    def test_action_type_enum_values(self, temp_runs_dir):
        """契约: action_type必须是9种枚举值之一"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("操作类型枚举测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        valid_action_types = [
            "navigation",
            "extraction",
            "interaction",
            "screenshot",
            "recipe_execution",
            "data_processing",
            "analysis",
            "user_interaction",
            "other",
        ]

        # 测试所有有效的action_type
        for action_type in ActionType:
            logger.write_log(
                f"测试{action_type.value}",
                LogStatus.SUCCESS,
                action_type,
                ExecutionMethod.MANUAL,
                {},
            )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        lines = log_file.read_text().strip().split("\n")

        assert len(lines) == 9  # 应该有9条日志

        for line in lines:
            log_data = json.loads(line)
            assert log_data["action_type"] in valid_action_types

    def test_execution_method_enum_values(self, temp_runs_dir):
        """契约: execution_method必须是6种枚举值之一"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("执行方法枚举测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)

        valid_execution_methods = [
            "command",
            "recipe",
            "file",
            "manual",
            "analysis",
            "tool",
        ]

        # 测试所有有效的execution_method
        for method in ExecutionMethod:
            logger.write_log(
                f"测试{method.value}",
                LogStatus.SUCCESS,
                ActionType.OTHER,
                method,
                {},
            )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        lines = log_file.read_text().strip().split("\n")

        assert len(lines) == 6  # 应该有6条日志

        for line in lines:
            log_data = json.loads(line)
            assert log_data["execution_method"] in valid_execution_methods

    def test_schema_version_field(self, temp_runs_dir):
        """契约: schema_version必须为"1.0"
"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("版本测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log(
            "测试",
            LogStatus.SUCCESS,
            ActionType.ANALYSIS,
            ExecutionMethod.MANUAL,
            {},
        )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        assert log_data["schema_version"] == "1.0"

    def test_timestamp_iso8601_format(self, temp_runs_dir):
        """契约: timestamp必须是ISO 8601格式"""
        from datetime import datetime

        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("时间戳测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log(
            "测试",
            LogStatus.SUCCESS,
            ActionType.ANALYSIS,
            ExecutionMethod.MANUAL,
            {},
        )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        # 验证可以解析为ISO 8601
        try:
            parsed_time = datetime.fromisoformat(log_data["timestamp"].replace("Z", "+00:00"))
            assert parsed_time is not None
        except ValueError:
            pytest.fail(f"timestamp不是有效的ISO 8601格式: {log_data['timestamp']}")

    def test_data_is_valid_json_object(self, temp_runs_dir):
        """契约: data必须是有效的JSON对象"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("数据对象测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log(
            "测试",
            LogStatus.SUCCESS,
            ActionType.ANALYSIS,
            ExecutionMethod.MANUAL,
            {"nested": {"key": "value"}, "list": [1, 2, 3]},
        )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        assert isinstance(log_data["data"], dict)
        assert "nested" in log_data["data"]
        assert "list" in log_data["data"]

    def test_execution_method_file_requires_file_field(self, temp_runs_dir):
        """契约: execution_method为file时,data必须包含file字段"""
        manager = RunManager(temp_runs_dir)
        instance = manager.create_run("文件方法测试")

        logger = RunLogger(temp_runs_dir / instance.run_id)
        logger.write_log(
            "执行脚本",
            LogStatus.SUCCESS,
            ActionType.DATA_PROCESSING,
            ExecutionMethod.FILE,
            {"file": "scripts/process.py", "language": "python"},
        )

        log_file = temp_runs_dir / instance.run_id / "logs" / "execution.jsonl"
        log_data = json.loads(log_file.read_text().strip())

        # 验证file字段存在
        assert "file" in log_data["data"]
        assert log_data["data"]["file"] is not None
