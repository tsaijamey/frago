"""退出一个 team：本机这一侧一定退得掉。

「我不干了」是这台机器自己的决定，不需要任何人批准。从前这里先敲中继、敲不通就整个
失败，于是一个中继早已扫掉的旧 team——码过期、服务器重装过、网断了——在本机永远退不掉：
人点一次退出，界面原地不动，只多一行「这个连接码在中继上不可用」的红字，再点还是那样。

越是中继不认识它，越该让它从本机消失，而那时的行为恰好相反。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.team import state as team_state
from frago.team import sync as team_sync
from frago.team.relay import RelayError


@pytest.fixture
def 一个在里面的team(tmp_path: Path, monkeypatch) -> team_state.TeamState:
    monkeypatch.setattr(team_state, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(team_sync, "save_state", team_state.save_state)
    state = team_state.TeamState(member="m1")
    state.teams["AAAAAAAAAA"] = team_state.TeamBinding(
        code="AAAAAAAAAA", session_id="sid", side="A", secret="k"
    )
    return state


def _relay_says(monkeypatch, err: Exception | None):
    """中继这一次怎么回。给 None 就是收到了。"""
    called: list[str] = []

    def fake(state, binding, action, **params):  # noqa: ANN001
        called.append(action)
        if err is not None:
            raise err
        return {"success": True}

    monkeypatch.setattr(team_sync, "_call", fake)
    return called


def test_中继收到了就是两边都知道(一个在里面的team, monkeypatch):
    called = _relay_says(monkeypatch, None)

    assert team_sync.leave_team(一个在里面的team, "AAAAAAAAAA") == "done"
    assert called == ["leave"]
    assert 一个在里面的team.teams["AAAAAAAAAA"].active is False


def test_中继不认识这个码_本机照样退得掉(一个在里面的team, monkeypatch):
    """这正是人在界面上撞到的那一种：码早被中继扫掉了。

    从前这里抛出去，本机那条记录一行没动，人点多少次都退不掉。
    """
    _relay_says(monkeypatch, RelayError("这个连接码在中继上不可用"))

    assert team_sync.leave_team(一个在里面的team, "AAAAAAAAAA") == "local-only"
    assert 一个在里面的team.teams["AAAAAAAAAA"].active is False


def test_中继连不上_本机照样退得掉(一个在里面的team, monkeypatch):
    _relay_says(monkeypatch, RelayError("连不上中继 https://www.frago.ai：timed out"))

    assert team_sync.leave_team(一个在里面的team, "AAAAAAAAAA") == "local-only"
    assert 一个在里面的team.teams["AAAAAAAAAA"].active is False


def test_退出这件事当场落盘(一个在里面的team, monkeypatch):
    """只改内存不落盘，等于重启之后它又回来了。"""
    _relay_says(monkeypatch, RelayError("中继在限流，等一会儿再来"))

    team_sync.leave_team(一个在里面的team, "AAAAAAAAAA")

    wrote = json.loads(team_state.STATE_PATH.read_text(encoding="utf-8"))
    assert wrote["teams"]["AAAAAAAAAA"]["active"] is False


def test_本机压根没有这个码才是真失败(一个在里面的team, monkeypatch):
    """退一个从没参加过的 team，是调用方搞错了，该报出来。"""
    _relay_says(monkeypatch, None)

    with pytest.raises(LookupError):
        team_sync.leave_team(一个在里面的team, "ZZZZZZZZZZ")
