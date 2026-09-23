"""磁盘上那份状态怎么写都不影响这台机器连到哪。

中继地址**不从这个文件读**，写死在代码里：全世界只有那一台中继，它是 frago 自己的
服务器，装完就该能用。从前它是这个文件里的一项、可以用命令改，代价是改过的机器指向
哪儿只有那台机器自己知道，而地址一换，改过的机器全都不跟着走，谁都不报错。

老机器的文件里可能写着任何东西——出厂旧地址、调试指的回环、某次手改，还可能留着
更早那版的账号口令三件套。全部忽略，一条都不该让这份状态读不出来。
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
    """更早那版把账号口令也存在这里。留着的话读的时候会当场抛「不认识这个参数」，
    而这一步是界面进 teaming 页面的第一件事——整张页面只剩一行红字。"""
    状态文件.write_text(json.dumps({
        "member": "m1",
        "relay": {
            "url": "https://谁知道哪来的",
            "email": "someone@example.com",
            "password": "旧口令",
            "token": "旧 token",
        },
    }), encoding="utf-8")

    state = team_state.load_state()

    assert state.member == "m1"
    assert state.relay.url == team_state.RELAY_URL


def test_没有这个文件时给一份空状态(状态文件: Path):
    state = team_state.load_state()

    assert state.teams == {}
    assert state.member  # 现生成一个，但不落盘
    assert not 状态文件.exists()


def test_没有这个文件时中继地址就已经有了(状态文件: Path):
    """装完 frago 就该能结对，没有任何人需要去填中继在哪。

    从前这里读出来是空串，页面据此判成「这台机器还没配中继」，弹一句让人去跑命令。
    新装和刚升级的机器每一台都撞得上——只有在这台机器上跑过一次 team 命令、文件落了
    盘，它才正常。
    """
    relay = team_state.load_state().relay

    assert relay.url == team_state.RELAY_URL
    assert relay.configured()


def test_地址指的是公网那一台_不是本机(状态文件: Path):
    """中继的用处是给两台各自没有公网入口的机器当中间人。指向本机等于自己跟自己说话。"""
    assert not team_state.load_state().relay.loopback()


def test_文件里写着别的地址也不算数(状态文件: Path):
    """现阶段中继地址改不了。这台机器上被人改过、或调试时指过回环，一律不作数。"""
    for wrote in ("http://127.0.0.1:8093", "https://demo.frago.ai", "https://随便什么"):
        状态文件.write_text(json.dumps({"relay": {"url": wrote}}), encoding="utf-8")

        assert team_state.load_state().relay.url == team_state.RELAY_URL


def test_写回去的是写死的那个(状态文件: Path):
    """老机器上手改过的值，下次写盘时自己就被纠正过来，不必另跑一趟迁移。"""
    状态文件.write_text(
        json.dumps({"member": "m1", "relay": {"url": "http://127.0.0.1:8093"}}),
        encoding="utf-8",
    )

    team_state.save_state(team_state.load_state())

    wrote = json.loads(状态文件.read_text(encoding="utf-8"))
    assert wrote["relay"]["url"] == team_state.RELAY_URL
