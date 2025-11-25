"""
中断恢复模块测试

测试 recovery.py 中的功能：
- 临时状态保存/加载/删除 (Phase 9)
- 状态过期检测
- 恢复提示
- GracefulInterruptHandler
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime, timedelta
import json


from frago.init.models import TemporaryState


# =============================================================================
# Phase 9: Ctrl+C 恢复和错误处理测试
# =============================================================================


class TestGetTempStatePath:
    """get_temp_state_path() 函数测试"""

    def test_get_temp_state_path_default(self):
        """获取默认临时状态路径"""
        from frago.init.recovery import get_temp_state_path

        path = get_temp_state_path()

        assert path.name == ".init_state.json"
        assert ".frago" in str(path)

    def test_get_temp_state_path_custom_home(self, tmp_path):
        """使用自定义 HOME 目录"""
        from frago.init.recovery import get_temp_state_path

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            path = get_temp_state_path()

        assert str(tmp_path) in str(path)


class TestSaveTempState:
    """save_temp_state() 函数测试 (T080)"""

    def test_save_temp_state_creates_file(self, tmp_path):
        """保存临时状态创建文件"""
        from frago.init.recovery import save_temp_state, get_temp_state_path

        state = TemporaryState(
            completed_steps=["check_node"],
            current_step="install_node",
            interrupted_at=datetime.now(),
            recoverable=True,
        )

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            save_temp_state(state)
            state_file = get_temp_state_path()

        assert state_file.exists()

    def test_save_temp_state_content(self, tmp_path):
        """保存的内容正确"""
        from frago.init.recovery import save_temp_state, get_temp_state_path

        state = TemporaryState(
            completed_steps=["check"],
            current_step="install_node",
            interrupted_at=datetime.now(),
            recoverable=True,
        )

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            save_temp_state(state)
            state_file = get_temp_state_path()

        data = json.loads(state_file.read_text())
        assert data["current_step"] == "install_node"
        assert "check" in data["completed_steps"]


class TestLoadTempState:
    """load_temp_state() 函数测试 (T079)"""

    def test_load_temp_state_returns_none_if_not_exists(self, tmp_path):
        """文件不存在返回 None"""
        from frago.init.recovery import load_temp_state

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            state = load_temp_state()

        assert state is None

    def test_load_temp_state_returns_valid_state(self, tmp_path):
        """加载有效状态"""
        from frago.init.recovery import load_temp_state, save_temp_state

        original_state = TemporaryState(
            completed_steps=["step1"],
            current_step="step2",
            interrupted_at=datetime.now(),
            recoverable=True,
        )

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            save_temp_state(original_state)
            loaded_state = load_temp_state()

        assert loaded_state is not None
        assert loaded_state.current_step == "step2"
        assert "step1" in loaded_state.completed_steps

    def test_load_temp_state_corrupted_returns_none(self, tmp_path):
        """损坏的状态文件返回 None"""
        from frago.init.recovery import load_temp_state, get_temp_state_path

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            state_file = get_temp_state_path()
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text("invalid json {{{")

            state = load_temp_state()

        assert state is None


class TestDeleteTempState:
    """delete_temp_state() 函数测试 (T081)"""

    def test_delete_temp_state_removes_file(self, tmp_path):
        """删除临时状态文件"""
        from frago.init.recovery import delete_temp_state, save_temp_state, get_temp_state_path

        state = TemporaryState(
            completed_steps=[],
            current_step="test",
            interrupted_at=datetime.now(),
        )

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            save_temp_state(state)
            state_file = get_temp_state_path()
            assert state_file.exists()

            result = delete_temp_state()

        assert result is True
        assert not state_file.exists()

    def test_delete_temp_state_nonexistent_returns_true(self, tmp_path):
        """删除不存在的文件返回 True"""
        from frago.init.recovery import delete_temp_state

        with patch.dict("os.environ", {"HOME": str(tmp_path)}):
            result = delete_temp_state()

        assert result is True


class TestStateExpired:
    """状态过期检测测试 (T084)"""

    def test_state_not_expired(self):
        """未过期的状态"""
        state = TemporaryState(
            completed_steps=[],
            current_step="test",
            interrupted_at=datetime.now(),
        )

        assert state.is_expired(days=7) is False

    def test_state_expired(self):
        """已过期的状态"""
        state = TemporaryState(
            completed_steps=[],
            current_step="test",
            interrupted_at=datetime.now() - timedelta(days=8),
        )

        assert state.is_expired(days=7) is True


class TestPromptResume:
    """prompt_resume() 函数测试 (T082)"""

    def test_prompt_resume_yes(self):
        """用户选择恢复"""
        from frago.init.recovery import prompt_resume

        state = TemporaryState(
            completed_steps=["check"],
            current_step="install_node",
            interrupted_at=datetime.now(),
        )

        with patch("click.confirm", return_value=True):
            with patch("click.echo"):
                result = prompt_resume(state)

        assert result is True

    def test_prompt_resume_no(self):
        """用户选择不恢复"""
        from frago.init.recovery import prompt_resume

        state = TemporaryState(
            completed_steps=[],
            current_step="test",
            interrupted_at=datetime.now(),
        )

        with patch("click.confirm", return_value=False):
            with patch("click.echo"):
                result = prompt_resume(state)

        assert result is False


class TestGracefulInterruptHandler:
    """GracefulInterruptHandler 类测试 (T078)"""

    def test_handler_initial_state(self):
        """初始状态未中断"""
        from frago.init.recovery import GracefulInterruptHandler

        handler = GracefulInterruptHandler()

        assert handler.interrupted is False

    def test_handler_context_manager(self):
        """作为上下文管理器使用"""
        from frago.init.recovery import GracefulInterruptHandler

        with GracefulInterruptHandler() as handler:
            assert handler.interrupted is False

    def test_handler_callback_called_on_interrupt(self):
        """中断时调用回调"""
        from frago.init.recovery import GracefulInterruptHandler

        callback = MagicMock()
        handler = GracefulInterruptHandler(on_interrupt=callback)

        with patch("click.echo"):
            handler._handler(None, None)

        assert handler.interrupted is True
        callback.assert_called_once()


class TestCreateInitialState:
    """create_initial_state() 函数测试"""

    def test_create_initial_state(self):
        """创建初始状态"""
        from frago.init.recovery import create_initial_state

        state = create_initial_state()

        assert state.current_step is None
        assert len(state.completed_steps) == 0
        assert state.recoverable is True


class TestMarkStepCompleted:
    """mark_step_completed() 函数测试"""

    def test_mark_step_completed(self):
        """标记步骤为已完成"""
        from frago.init.recovery import create_initial_state, mark_step_completed

        state = create_initial_state()
        mark_step_completed(state, "step1")

        assert "step1" in state.completed_steps


class TestSetCurrentStep:
    """set_current_step() 函数测试"""

    def test_set_current_step(self):
        """设置当前步骤"""
        from frago.init.recovery import create_initial_state, set_current_step

        state = create_initial_state()
        set_current_step(state, "install_node")

        assert state.current_step == "install_node"
