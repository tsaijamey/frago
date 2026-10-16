"""窗口改名：认领到真编号之后，tmux 会话名必须跟着换成真编号那一个。

页面新建一场 codex / opencode 会话时，真编号要等会话起来之后才认领得到，在那之前那个
窗口只能先挂在 frago 自己 mint 的把手底下（``frago-agent-webui-<uuid>``）。名字与真编号
一分家，常驻池一重启就按真编号找不到这个还活着的窗口——于是另起一个窗口去 ``codex
resume`` 同一场对话，撞上单写者锁，用户那句话被挡在门外，页面上只有「发不出去」
（20261009 现场）。
"""

from __future__ import annotations

from frago.agent_driver import tmux_session as ts

_HANDLE = "webui-7363edfb-ae6f-4183-9512-2bad3aa615a7"
_CLAIMED = "01a11f42-0548-79f0-9723-9f1d69e33771"


class _FakeTmux:
    """记下每次 tmux 调用，按需让某条命令失败。"""

    def __init__(self, *, fail: tuple[str, ...] = ()) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(list(argv))
        if self._fail and tuple(argv[1 : 1 + len(self._fail)]) == self._fail:
            raise RuntimeError("tmux said no")
        return ""


def _session(runner: _FakeTmux, session_id: str = _HANDLE, **kw) -> ts.TmuxAgentSession:
    return ts.TmuxAgentSession(
        session_id=session_id,
        driver=object(),
        cwd="/repo",
        runner=runner,
        poll_interval_s=0.0,
        sleep=lambda _s: None,
        **kw,
    )


def test_rename_tmux_takes_the_name_of_the_claimed_session():
    runner = _FakeTmux()
    session = _session(runner)
    assert session.tmux_name == f"frago-agent-{_HANDLE}"

    assert session.rename_tmux(_CLAIMED) is True

    assert session.tmux_name == f"frago-agent-{_CLAIMED}"
    assert runner.calls[-1] == [
        "tmux",
        "rename-session",
        "-t",
        f"frago-agent-{_HANDLE}",
        f"frago-agent-{_CLAIMED}",
    ]
    # 会话对象自己的编号一个字不改：认领映射（binding）拿它当键，改了等于让 driver 重认。
    assert session.session_id == _HANDLE


def test_rename_tmux_is_a_noop_when_the_name_already_matches():
    runner = _FakeTmux()
    session = _session(runner, session_id=_CLAIMED)
    assert session.rename_tmux(_CLAIMED) is True
    assert runner.calls == []  # 一条命令都没发


def test_rename_tmux_reports_failure_without_raising():
    """改不动只是名字留在原处，NEVER 因此把认领本身或这一轮打断。"""
    runner = _FakeTmux(fail=("rename-session",))
    session = _session(runner)
    assert session.rename_tmux(_CLAIMED) is False
    assert session.tmux_name == f"frago-agent-{_HANDLE}"


def test_rename_tmux_never_touches_a_borrowed_session():
    """借住别人的窗口（虚拟桌面那个终端）——改名等于替主人改了它。"""
    runner = _FakeTmux()
    session = _session(runner, session_id="s1", tmux_target="someones-terminal")
    assert session.rename_tmux(_CLAIMED) is False
    assert runner.calls == []


def test_caller_may_hand_over_the_window_name():
    """改名之后名字与会话名分家，下一个进程只能靠记下的那个名字重新绑上它。

    照会话名重推会绑到一个不存在的窗口上，此后每一轮都崩在 ``capture-pane``。
    """
    runner = _FakeTmux()
    session = _session(runner, session_id=_HANDLE, tmux_name=f"frago-agent-{_CLAIMED}")

    assert session.tmux_name == f"frago-agent-{_CLAIMED}"
    # 与借住语义分开：这一个不改变"窗口归谁所有"，close() 照旧收得走。
    assert session.tmux_target is None


def test_handed_over_name_still_renames_and_closes_its_own_window():
    runner = _FakeTmux()
    session = _session(runner, session_id=_HANDLE, tmux_name=f"frago-agent-{_CLAIMED}")

    session.close()

    assert runner.calls[-1] == ["tmux", "kill-session", "-t", f"frago-agent-{_CLAIMED}"]


def test_created_at_reads_the_session_creation_time():
    """认领会话编号要拿它当锚点：进程内记的启动时刻活不过第一条命令，tmux 记的活得过。"""
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> str:
        calls.append(list(argv))
        return "1791941895\n"

    session = _session(runner)

    assert session.created_at() == 1791941895.0
    assert calls[-1] == [
        "tmux",
        "display-message",
        "-p",
        "-t",
        f"frago-agent-{_HANDLE}",
        "#{session_created}",
    ]


def test_created_at_gives_up_quietly():
    """问不出来返回 None，NEVER 抛——认领是尽力而为，不该把这一轮打断。"""

    def boom(argv: list[str]) -> str:
        raise RuntimeError("tmux said no")

    assert _session(boom).created_at() is None

    def garbage(argv: list[str]) -> str:
        return "不知道"

    assert _session(garbage).created_at() is None
