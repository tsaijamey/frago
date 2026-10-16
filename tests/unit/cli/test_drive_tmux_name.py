"""侧车记的窗口名：认领之后窗口会被改名，此后每一条命令都得照着新名字找它。

认领发生在**会话起来之后**（页面新建 codex / opencode / agy 时真编号要等会话自己报）。
改完名，名字与侧车里的会话名就分家了，而侧车是下一个进程找这个窗口的唯一依据。两处
各自会出一类毛病，都是 2026-10-14 实机撞上的：

- 判活仍按老名字问 → 一场好好活着的会话被报成"已经不在了"，此后每一条 ``send`` 都拒绝；
- 绑定仍按会话名重推窗口名 → 绑到一个不存在的窗口上，每一轮崩在 ``capture-pane``。

所以这里盯三件事：改完名侧车要跟上、绑定要照侧车记的那个名字走、名字没变时一个字节都不写。
"""

from __future__ import annotations

import json

import pytest

from frago.cli import drive_command as dc

_HANDLE = "e2e"
_CLAIMED_TMUX = "frago-agent-bf4589e2-8eaf-47b3-a7bc-5dc76e6d631d"


@pytest.fixture()
def drive_dir(tmp_path, monkeypatch):
    """把侧车目录指到临时目录，别碰本机真实的那一份。"""
    monkeypatch.setattr(dc, "_drive_dir", lambda: tmp_path)
    return tmp_path


class _FakeSession:
    """只带 driver 会读的那一格：当前的 tmux 名。"""

    def __init__(self, tmux_name: str) -> None:
        self.tmux_name = tmux_name


def _entry(tmux_name: str = f"frago-agent-{_HANDLE}") -> dc.DriveEntry:
    return dc.DriveEntry(
        name=_HANDLE, agent_type="agy", tmux_name=tmux_name, pid=1, cwd="/repo"
    )


def test_名字变了就刷回侧车(drive_dir):
    entry = _entry()
    dc._write_entry(entry)

    dc._refresh_tmux_name(entry, _FakeSession(_CLAIMED_TMUX))

    assert entry.tmux_name == _CLAIMED_TMUX
    data = json.loads((drive_dir / f"{_HANDLE}.json").read_text(encoding="utf-8"))
    assert data["tmux_name"] == _CLAIMED_TMUX


def test_名字没变就不动盘(drive_dir):
    """每一轮都重写一遍侧车是没必要的写盘，也别去和别的进程抢。"""
    entry = _entry()
    path = drive_dir / f"{_HANDLE}.json"
    path.write_text("别动我", encoding="utf-8")

    dc._refresh_tmux_name(entry, _FakeSession(f"frago-agent-{_HANDLE}"))

    assert path.read_text(encoding="utf-8") == "别动我"


def test_绑定照侧车记的窗口名走(drive_dir):
    """按会话名重推会绑到一个不存在的窗口上。"""
    entry = _entry(_CLAIMED_TMUX)

    session = dc._bind_session(entry, object(), None)

    assert session.tmux_name == _CLAIMED_TMUX
    # 与借住语义分开：这不是别人的窗口，close() 照旧收得走。
    assert session.tmux_target is None


def test_判活按侧车记的窗口名问(tmp_path):
    """改完名之后按会话名问，一场活着的会话会被报成 dead。"""
    seen: list[list[str]] = []

    def runner(argv: list[str]) -> str:
        seen.append(list(argv))
        return ""

    assert dc._is_alive(_entry(_CLAIMED_TMUX), runner) is True
    assert seen[-1] == ["tmux", "has-session", "-t", _CLAIMED_TMUX]
