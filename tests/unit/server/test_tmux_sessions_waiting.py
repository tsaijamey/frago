"""Unit tests for TmuxSessionsService awaiting_input 3-tier fallback chain and generic heuristic probe."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.server.services.tmux_sessions_service import (
    _detect_session_kernel,
    _fallback_awaiting_input,
    list_waiting,
)


class TestAwaitingInputThreeTierFallbackChain:
    """Tests covering Claude (adapted), AGY/Codex/OpenCode (fallback), CoreAgent (unsupported)."""

    def test_detect_session_kernel(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _detect_session_kernel("core_1234567890abcdef") == "coreagent"
        assert _detect_session_kernel("ses_058288655ffeYMxYC1AZKCcv56") == "opencode"
        assert _detect_session_kernel("") == "unknown"

    def test_fallback_gate1_silence_threshold_under_3_seconds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Create a mock session dir under ~/.frago/sessions/agy/sid
        sid = "88888888-4444-4444-4444-121212121212"
        sess_dir = tmp_path / ".frago" / "sessions" / "agy" / sid
        sess_dir.mkdir(parents=True)
        raw_file = sess_dir / "raw.jsonl"
        raw_file.write_text(
            json.dumps({"type": "assistant", "message": {"content": "已完成所有任务。"}}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # File just modified: silence duration < 3.0 seconds -> must return False
        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is False

        # Simulate time moving forward by 5 seconds
        past_time = time.time() - 5.0
        import os

        os.utime(raw_file, (past_time, past_time))

        # Now silence >= 3.0s, should pass Gate 1 & Gate 2 -> return True
        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is True

    def test_fallback_gate1_busy_pane_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = "77777777-4444-4444-4444-121212121212"
        sess_dir = tmp_path / ".frago" / "sessions" / "agy" / sid
        sess_dir.mkdir(parents=True)
        raw_file = sess_dir / "raw.jsonl"
        raw_file.write_text(
            json.dumps({"type": "assistant", "message": {"content": "思考中"}}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        past_time = time.time() - 10.0
        import os

        os.utime(raw_file, (past_time, past_time))

        # When pane is busy (e.g. running spinner), must return False
        with patch("frago.server.services.tmux_sessions_service._is_busy", return_value=True):
            assert _fallback_awaiting_input(sid, "busy_pane", client_alive=True) is False

    def test_fallback_gate2_last_record_substantive_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        from frago.server.services.tmux_sessions_service import _FALLBACK_VERDICT_CACHE

        _FALLBACK_VERDICT_CACHE.clear()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        sid = "66666666-4444-4444-4444-121212121212"
        sess_dir = tmp_path / ".frago" / "sessions" / "codex" / sid
        sess_dir.mkdir(parents=True)
        raw_file = sess_dir / "raw.jsonl"
        t0 = time.time() - 30.0

        # Case A: Last record is user -> False
        raw_file.write_text(
            json.dumps({"role": "user", "content": "请帮我修改代码"}) + "\n",
            encoding="utf-8",
        )
        os.utime(raw_file, (t0 + 1, t0 + 1))
        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is False

        # Case B: Last record is assistant with pending tool_use -> False
        raw_file.write_text(
            json.dumps({
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}],
            })
            + "\n",
            encoding="utf-8",
        )
        os.utime(raw_file, (t0 + 2, t0 + 2))
        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is False

        # Case C: Last record is assistant reply finished -> True
        raw_file.write_text(
            json.dumps({
                "role": "assistant",
                "content": [{"type": "text", "text": "代码已修改完成，测试全绿。"}],
            })
            + "\n",
            encoding="utf-8",
        )
        os.utime(raw_file, (t0 + 3, t0 + 3))
        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is True

    def test_fallback_gate3_o1_caching_and_invalidation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sid = "55555555-4444-4444-4444-121212121212"
        sess_dir = tmp_path / ".frago" / "sessions" / "opencode" / sid
        sess_dir.mkdir(parents=True)
        raw_file = sess_dir / "raw.jsonl"
        past_time = time.time() - 20.0
        raw_file.write_text(
            json.dumps({"type": "assistant", "content": "任务完毕。"}) + "\n",
            encoding="utf-8",
        )
        os.utime(raw_file, (past_time, past_time))

        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is True

        # Append user record without updating mtime to verify cache hit
        # Then touch file with new mtime -> cache invalidated
        new_time = time.time() - 10.0
        raw_file.write_text(
            json.dumps({"type": "user", "content": "继续第二步"}) + "\n",
            encoding="utf-8",
        )
        os.utime(raw_file, (new_time, new_time))
        assert _fallback_awaiting_input(sid, "ansi_idle", client_alive=True) is False

    def test_fallback_exception_safety_isolation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Corrupted / unparseable file should quietly return False / None, NEVER raise
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sid = "44444444-4444-4444-4444-121212121212"
        sess_dir = tmp_path / ".frago" / "sessions" / "agy" / sid
        sess_dir.mkdir(parents=True)
        raw_file = sess_dir / "raw.jsonl"
        raw_file.write_bytes(b"\xff\xfe\x00\x00corrupted-binary-noise")

        # Must not raise any exception
        result = _fallback_awaiting_input(sid, "ansi_idle", client_alive=True)
        assert result in (False, None)

    def test_list_waiting_four_kernels_tiered_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        from frago.server.services.tmux_sessions_service import _FALLBACK_VERDICT_CACHE, _PATH_CACHE

        _FALLBACK_VERDICT_CACHE.clear()
        _PATH_CACHE.clear()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))

        claude_sid = "11111111-1111-1111-1111-111111111111"
        agy_sid = "22222222-2222-2222-2222-222222222222"
        core_sid = "core_33333333333333333333333333333333"

        # Mock Claude session
        claude_dir = tmp_path / ".claude" / "projects" / "test_proj"
        claude_dir.mkdir(parents=True)
        claude_file = claude_dir / f"{claude_sid}.jsonl"
        claude_file.write_text(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Claude 已就绪"}]}})
            + "\n",
            encoding="utf-8",
        )

        # Mock AGY session
        agy_dir = tmp_path / ".frago" / "sessions" / "agy" / agy_sid
        agy_dir.mkdir(parents=True)
        agy_file = agy_dir / "raw.jsonl"
        agy_file.write_text(
            json.dumps({"type": "assistant", "message": {"content": "AGY 已回答完成，等待下一步。"}})
            + "\n",
            encoding="utf-8",
        )
        past_time = time.time() - 10.0
        os.utime(agy_file, (past_time, past_time))

        tmux_sessions = [
            f"frago-agent-{claude_sid}",
            f"frago-agent-{agy_sid}",
            f"frago-agent-{core_sid}",
        ]
        tmux_commands = {
            f"frago-agent-{claude_sid}": "claude",
            f"frago-agent-{agy_sid}": "antigravity",
            f"frago-agent-{core_sid}": "frago-core",
        }

        with (
            patch("frago.server.services.tmux_sessions_service._session_names", return_value=tmux_sessions),
            patch("frago.server.services.tmux_sessions_service._pane_commands", return_value=tmux_commands),
            patch("frago.server.services.tmux_sessions_service._tmux", return_value=""),
            patch(
                "frago.server.services.tmux_sessions_service._awaiting_input",
                return_value=True,
            ),
            patch(
                "frago.server.services.tmux_sessions_service._is_busy",
                return_value=False,
            ),
        ):
            waiting = list_waiting()
            by_sid = {w.session_id: w for w in waiting if w.session_id}

            # 1. Claude: level 1 adapted probe
            assert claude_sid in by_sid
            assert by_sid[claude_sid].awaiting_input is True

            # 2. AGY: level 2 generic fallback probe triggered & awaiting_input = True
            assert agy_sid in by_sid
            assert by_sid[agy_sid].awaiting_input is True
            assert "AGY 已回答完成" in by_sid[agy_sid].closing_text

            # 3. CoreAgent: level 3 unsupported -> awaiting_input is None
            assert core_sid in by_sid
            assert by_sid[core_sid].awaiting_input is None

    def test_ontology_busy_probe_three_tier_dispatch_no_cross_kernel_regex_pollution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验证 busy_probe 按本体四级能力声明派发，AGY/Codex/OpenCode 面板残留 `(45s` 不再被 Claude 正则误判为忙碌。"""
        from frago.server.services.tmux_sessions_service import (
            _is_busy,
            check_session_terminal_busy,
        )

        timer_residual_pane = (
            "● Scheduled 1 timer (45s: Check if implementation worker finished)\n"
            "  ⎿  Timer task-160 started\n"
            "> \n"
            "? for shortcuts"
        )
        # 1. AGY (adapted): 屏幕残留 `(45s` 时绝不误判为 busy；处于 Generating / esc to cancel 时准确判为 busy
        assert _is_busy(timer_residual_pane, kernel="agy") is False
        assert check_session_terminal_busy(timer_residual_pane, kernel="agy") is False
        assert _is_busy("Generating response... esc to cancel", kernel="agy") is True

        # 2. Codex / OpenCode (fallback): 屏幕残留 `(45s` 时绝不误判为 busy；有通用转轮或中断提示时判为 busy
        assert _is_busy(timer_residual_pane, kernel="codex") is False
        assert _is_busy(timer_residual_pane, kernel="opencode") is False
        assert _is_busy("⠋ Working on files…", kernel="codex") is True
        assert _is_busy("Press esc to interrupt", kernel="opencode") is True

        # 3. Claude (native): 保持存量专用探针，匹配带括号秒数 `(45s` 与 token 计数
        assert _is_busy("✻ Thinking (45s · ↑ 1.2k tokens)", kernel="claude") is True
        assert _is_busy("❯ \n  ? for shortcuts", kernel="claude") is False
