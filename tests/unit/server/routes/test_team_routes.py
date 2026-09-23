"""界面那几条接口的契约。

只钉一件事，因为坏了就整台服务端停摆：**去敲中继的活不许跑在接单那条线上。**

本机这一侧办的每件事最后都要敲一次中继，而中继常常就住在同一个 frago 里（自己跟
自己结 team，或者经 SSH 隧道把服务器那一端映射到本地）。活写在接单线上，服务端就会
在接下这一单之后去等自己回话——而它正忙着等，于是连最普通的接口都不答，二十秒后
客户端先放弃，报出来的却是一句「中继连不上」，与真正的网络故障一个样子。

判据用的是「这段代码跑的时候有没有事件循环在身边」：在接单线上跑就有，被挪到线程池里
跑就没有。比数秒表可靠，也说得出为什么。
"""

from __future__ import annotations

import asyncio

import pytest

from frago.server.routes import team as team_routes


def _off_the_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise AssertionError(
        "这段活跑在接单那条线上：它要等中继回话，而中继可能就是这台服务端自己，"
        "于是整台服务端在这二十秒里谁也不答"
    )


@pytest.mark.parametrize(
    "patched, call",
    [
        ("open_team", lambda: team_routes.open_team(
            team_routes.OpenRequest(session_id="s"))),
        ("join_team", lambda: team_routes.join_team(
            team_routes.JoinRequest(code="ABC234", session_id="s"))),
        ("leave_team", lambda: team_routes.leave_team("ABC234")),
        ("team_status", lambda: team_routes.team_status("ABC234")),
        ("peer_records", lambda: team_routes.peer_records("ABC234")),
        ("send_to_peer", lambda: team_routes.send_to_peer(
            "ABC234", team_routes.SendRequest(text="hi"))),
    ],
)
def test_敲中继的活不跑在接单线上(monkeypatch, patched, call):
    from frago.team import sync as team_sync
    from frago.team.state import Relay, TeamBinding, TeamState

    state = TeamState(member="m", relay=Relay(url="https://relay.example"))
    state.teams["ABC234"] = TeamBinding(code="ABC234", session_id="s", side="A")
    monkeypatch.setattr("frago.team.state.load_state", lambda: state)

    def stub(*_args, **_kwargs):
        _off_the_event_loop()
        if patched in ("open_team", "join_team"):
            return TeamBinding(code="ABC234", session_id="s", side="A")
        if patched == "team_status":
            return {"exists": True}
        if patched == "peer_records":
            return []
        return None

    monkeypatch.setattr(team_sync, patched, stub)
    asyncio.run(call())


class TestTheRefusalSaysWhichKind:
    """一次失败属于哪一类，由这一层说，NEVER 让界面去那句话里找词。

    三类各自的下一步完全不同——改码、等网络、等一会儿。从前这里只回一句中文，界面
    靠在里面找「限流」「连不上中继」这几个字来分支：换个说法、翻成别的语言，判读当场
    失效，而且不报错，只会把三种处境一律显示成同一种。
    """

    def test_码不对是一类(self):
        from frago.server.routes import team as route

        err = Exception("这个连接码在中继上不可用。它可能打错了、已经作废了")
        assert route._classify(err) == route.TROUBLE_BAD_CODE

    def test_够不着中继是另一类(self):
        from frago.server.routes import team as route

        assert route._classify(Exception("连不上中继 https://www.frago.ai：timed out")) == (
            route.TROUBLE_RELAY_DOWN
        )

    def test_被限流又是一类(self):
        from frago.server.routes import team as route

        assert route._classify(Exception("中继在限流，等一会儿再来")) == route.TROUBLE_BUSY

    def test_认不出的落到够不着那一类(self):
        """那一类的说法最不武断，给的也是「再试一次」，不会把人引到改码那条错路上。"""
        from frago.server.routes import team as route

        assert route._classify(Exception("某种谁也没见过的故障")) == route.TROUBLE_RELAY_DOWN

    def test_那句原话一个字都没丢(self):
        """上面那句是给人看的，这句是排查时对得上的那一句。两样都要。"""
        from frago.server.routes import team as route

        refused = route._refuse(Exception("中继在限流，等一会儿再来"))

        assert refused.status_code == 400
        assert refused.detail["detail"] == "中继在限流，等一会儿再来"
        assert refused.detail["trouble"] == route.TROUBLE_BUSY
