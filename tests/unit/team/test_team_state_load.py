"""磁盘上那份状态是旧版写的，照样要读得出来。

中继早先要配账号口令，后来定成「连接码本身就是凭证」，中继这一项只剩一个地址。
**升级不会去改已经写在磁盘上的文件**，于是每一台用过旧版的机器，文件里都还留着
`email` / `password` / `token` 三个键。

读的时候照单全收就会当场抛「不认识 email 这个参数」，而这一步是界面进 teaming 页面
的第一件事：整张页面只剩一行红字，命令行那侧同样过这条路。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.team import state as team_state


@pytest.fixture
def 状态文件(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "state.json"
    monkeypatch.setattr(team_state, "STATE_PATH", path)
    return path


def test_旧版留下的凭证字段不让整份状态读不出来(状态文件: Path):
    状态文件.write_text(json.dumps({
        "member": "m1",
        "relay": {
            "url": "https://relay.example",
            "email": "someone@example.com",
            "password": "旧口令",
            "token": "旧 token",
        },
    }), encoding="utf-8")

    state = team_state.load_state()

    assert state.relay.base() == "https://relay.example"
    assert state.member == "m1"


def test_中继这一项只剩地址(状态文件: Path):
    """多出来的键一律忽略：文件的形状由代码说了算。"""
    状态文件.write_text(json.dumps({
        "relay": {"url": "https://relay.example", "以后某个新键": 1},
    }), encoding="utf-8")

    assert team_state.load_state().relay.base() == "https://relay.example"


def test_没有这个文件时给一份空状态(状态文件: Path):
    state = team_state.load_state()

    assert state.teams == {}
    assert state.member  # 现生成一个，但不落盘
    assert not 状态文件.exists()
