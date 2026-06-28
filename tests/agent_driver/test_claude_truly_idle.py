"""Phase 6 单测（spec 20260627）：claude ``is_truly_idle`` 四信号缺一不可。

真空闲 = ready 空输入框 + 无 spinner/工作转轮 + 无 "shell(s) still running" +
transcript mtime 静默 N 秒。任一不满足都视为「仍在干活」，绝不回收 / 插话。
"""

from __future__ import annotations

from pathlib import Path

import frago.agent_driver.drivers.claude as claude_mod
from frago.agent_driver.drivers.claude import is_truly_idle

# ready 空输入框（``❯ `` 行尾为空）+ 无任何忙碌标记的干净 pane。
_READY_PANE = "⏺ Done.\n❯ \n"


class _FakeSession:
    def __init__(self, pane: str) -> None:
        self._pane = pane
        self.session_id = "conv-x"
        self.native_session_id = True
        self.cwd = "/home/x"

    def capture_pane(self, *, full: bool = False) -> str:  # noqa: ARG002
        return self._pane


def _with_transcript(tmp_path: Path, monkeypatch, mtime: float) -> None:
    """让 transcript_path_for 指向一个 mtime 受控的真实文件。"""
    p = tmp_path / "t.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    import os
    os.utime(p, (mtime, mtime))
    monkeypatch.setattr(claude_mod, "transcript_path_for", lambda _s: p)


def test_all_four_signals_satisfied_is_idle(tmp_path, monkeypatch):
    _with_transcript(tmp_path, monkeypatch, mtime=1000.0)
    s = _FakeSession(_READY_PANE)
    # now 比 mtime 晚 10s > silence 3s → 静默信号成立。
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is True


def test_no_ready_box_not_idle(tmp_path, monkeypatch):
    _with_transcript(tmp_path, monkeypatch, mtime=1000.0)
    # 输入框里有命令回显（非空载）→ ready 信号不成立。
    s = _FakeSession("│ ❯ claude --resume abc │\n")
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is False


def test_spinner_present_not_idle(tmp_path, monkeypatch):
    _with_transcript(tmp_path, monkeypatch, mtime=1000.0)
    s = _FakeSession(_READY_PANE + "✻ Cogitating…\n")
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is False


def test_busy_esc_to_interrupt_not_idle(tmp_path, monkeypatch):
    _with_transcript(tmp_path, monkeypatch, mtime=1000.0)
    s = _FakeSession(_READY_PANE + "  (12s · esc to interrupt)\n")
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is False


def test_shell_still_running_not_idle(tmp_path, monkeypatch):
    _with_transcript(tmp_path, monkeypatch, mtime=1000.0)
    s = _FakeSession(_READY_PANE + "1 shell still running\n")
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is False
    # 复数形式同样命中。
    s2 = _FakeSession(_READY_PANE + "2 shells still running\n")
    assert is_truly_idle(s2, silence_s=3.0, now=1010.0) is False


def test_transcript_recent_mtime_not_idle(tmp_path, monkeypatch):
    _with_transcript(tmp_path, monkeypatch, mtime=1008.0)
    s = _FakeSession(_READY_PANE)
    # now - mtime = 2s < silence 3s → transcript 仍在被写，未静默。
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is False


def test_no_transcript_does_not_block_idle(monkeypatch):
    # 定位不到 transcript 时跳过 mtime 信号，前三信号成立即空闲。
    monkeypatch.setattr(claude_mod, "transcript_path_for", lambda _s: None)
    s = _FakeSession(_READY_PANE)
    assert is_truly_idle(s, silence_s=3.0, now=1010.0) is True
