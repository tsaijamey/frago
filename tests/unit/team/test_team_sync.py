"""本机这一侧的契约。

中继换成一个记账的假货。要钉的不是配方算得对不对，而是**本机这一侧交出去了什么、
收回来之后怎么处理**——尤其是：每次说话都带指纹和钥匙（少一样，中继就认不出这是
已经在场的那一台，或者反过来，任何人拿着码都能冒充它）。
"""

from __future__ import annotations

import pytest

from frago.team import sync as team_sync
from frago.team.state import Relay, TeamBinding, TeamState


class FakeRelay:
    """一个记账的中继。回答由测试逐条摆好；调用原样记下来。"""

    def __init__(self, answers=None):
        self.calls: list[tuple[str, dict]] = []
        self._answers = answers or {}

    def call(self, action, **params):
        self.calls.append((action, params))
        answer = self._answers.get(action, {})
        if isinstance(answer, list):
            return answer.pop(0)
        return answer

    def params_of(self, action):
        return [p for name, p in self.calls if name == action]


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr("frago.team.state.STATE_PATH", tmp_path / "state.json")
    return TeamState(member="fingerprint-self", relay=Relay(url="https://relay.example"))


def _use(monkeypatch, fake):
    monkeypatch.setattr(team_sync, "RelayClient", lambda relay: fake)


def _no_records(monkeypatch):
    monkeypatch.setattr(team_sync.record_reader, "read_records", lambda *a, **k: [])


# ── 结成 team ──────────────────────────────────────────────────────────


def test_发起时中继当场给出码和钥匙(monkeypatch, state):
    fake = FakeRelay({"open": {"code": "ABCD234567", "side": "A", "secret": "k1"}})
    _use(monkeypatch, fake)

    binding = team_sync.open_team(state, "sess-1")

    assert binding.code == "ABCD234567"
    assert binding.secret == "k1", "钥匙没存下来，下一次说话就证明不了自己是这一侧"
    assert fake.params_of("open")[0]["fingerprint"] == "fingerprint-self"


def test_加入时把原来那把钥匙带上(monkeypatch, state):
    """断线回来、重启之后再来，中继要看它拿不拿得出当初那把钥匙。

    不带的话，中继只能凭指纹认人——任何能伪造指纹的人都能顶掉已经在场的一侧。
    """
    state.teams["ABCD234567"] = TeamBinding(
        code="ABCD234567", session_id="s", side="B", secret="老钥匙"
    )
    fake = FakeRelay({"join": {"side": "B", "secret": "老钥匙", "resumed": True}})
    _use(monkeypatch, fake)

    team_sync.join_team(state, "ABCD234567", "sess-1")

    assert fake.params_of("join")[0]["secret"] == "老钥匙"


def test_中继说不行就当场停下(monkeypatch, state):
    from frago.team.relay import RelayError

    class Refusing:
        def call(self, action, **params):
            raise RelayError("这个连接码在中继上不可用")

    _use(monkeypatch, Refusing())
    with pytest.raises(RelayError, match="不可用"):
        team_sync.join_team(state, "ZZZZZZZZZZ", "sess-1")


def test_退出之后本机这一侧不再同步(monkeypatch, state):
    state.teams["ABCD234567"] = TeamBinding(
        code="ABCD234567", session_id="s", side="A", secret="k1"
    )
    fake = FakeRelay()
    _use(monkeypatch, fake)

    team_sync.leave_team(state, "ABCD234567")

    assert state.active_teams() == []
    assert fake.params_of("leave")[0]["code"] == "ABCD234567"


# ── 进场之后每一次都要带钥匙 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "action, run",
    [
        ("send", lambda st: team_sync.send_to_peer(st, "ABCD234567", "干这个")),
        ("peer", lambda st: team_sync.peer_records(st, "ABCD234567")),
        ("status", lambda st: team_sync.team_status(st, "ABCD234567")),
        ("leave", lambda st: team_sync.leave_team(st, "ABCD234567")),
    ],
)
def test_每次说话都带指纹和钥匙(monkeypatch, state, action, run):
    state.teams["ABCD234567"] = TeamBinding(
        code="ABCD234567", session_id="s", side="A", secret="k1"
    )
    fake = FakeRelay()
    _use(monkeypatch, fake)

    run(state)

    sent = fake.params_of(action)[0]
    assert sent["fingerprint"] == "fingerprint-self"
    assert sent["secret"] == "k1", "少带钥匙，中继会把这台当成拿着码的陌生机器"


# ── 一轮同步 ────────────────────────────────────────────────────────────


def test_同步把对方的消息加上前缀投进会话(monkeypatch, state):
    _no_records(monkeypatch)
    state.prefix = "来自 {code} 的队友："
    binding = TeamBinding(code="ABCD234567", session_id="s", side="A", secret="k1")
    state.teams["ABCD234567"] = binding
    fake = FakeRelay({"pull": {"messages": [{"id": "m1", "text": "请你跑一遍测试"}]}})
    _use(monkeypatch, fake)

    got: list[str] = []
    outcome = team_sync.sync_once(state, binding, got.append)

    assert outcome.delivered == 1
    assert got == ["来自 ABCD234567 的队友：\n\n请你跑一遍测试"]


def test_投递失败不算已投下一轮还会再来(monkeypatch, state):
    _no_records(monkeypatch)
    binding = TeamBinding(code="ABCD234567", session_id="s", side="A", secret="k1")
    state.teams["ABCD234567"] = binding
    fake = FakeRelay({"pull": {"messages": [{"id": "m1", "text": "跑测试"}]}})
    _use(monkeypatch, fake)

    def explode(_prompt):
        raise RuntimeError("tmux 起不来")

    outcome = team_sync.sync_once(state, binding, explode)

    assert outcome.delivered == 0
    assert binding.delivered == []


def test_推记录按序号增量且游标落盘(monkeypatch, state):
    from frago.session.unified_record import UnifiedRecord

    binding = TeamBinding(code="ABCD234567", session_id="s", side="A",
                          secret="k1", pushed_seq=4)
    state.teams["ABCD234567"] = binding
    asked: dict = {}

    def fake_read(session_id, after=0, limit=0, **_):
        asked["after"] = after
        return [
            UnifiedRecord(id="r5", session_id=session_id, group_id=None, seq=5,
                          ts=1, kind="user.say", payload={"text": "hi"}),
            UnifiedRecord(id="r6", session_id=session_id, group_id=None, seq=6,
                          ts=2, kind="agent.say", payload={"text": "ok"}),
        ]

    monkeypatch.setattr(team_sync.record_reader, "read_records", fake_read)
    fake = FakeRelay()
    _use(monkeypatch, fake)

    outcome = team_sync.sync_once(state, binding, lambda _: None)

    assert asked["after"] == 5, "游标要从上次推到的那条之后开始，不重推也不跳过"
    assert outcome.pushed == 2
    assert binding.pushed_seq == 6


def test_没有新记录也要上报当心跳(monkeypatch, state):
    _no_records(monkeypatch)
    binding = TeamBinding(code="ABCD234567", session_id="s", side="A", secret="k1")
    state.teams["ABCD234567"] = binding
    fake = FakeRelay()
    _use(monkeypatch, fake)

    team_sync.sync_once(state, binding, lambda _: None)

    assert fake.params_of("push")[0]["records"] == [], \
        "一条新记录都没有就连心跳都不发，中继二十四小时后会把这个 team 清掉"


def test_会话读不出来也要发心跳(monkeypatch, state):
    def boom(*_a, **_k):
        raise RuntimeError("这场会话不在了")

    monkeypatch.setattr(team_sync.record_reader, "read_records", boom)
    binding = TeamBinding(code="ABCD234567", session_id="没了", side="A", secret="k1")
    state.teams["ABCD234567"] = binding
    fake = FakeRelay()
    _use(monkeypatch, fake)

    team_sync.sync_once(state, binding, lambda _: None)

    assert fake.params_of("push"), "读不到记录就不发心跳，这个 team 会被中继清掉"


def test_出厂默认的中继不是本机():
    """中继的用处是给两台各自没有公网入口的机器当中间人。

    指向本机等于让同一台机器既当甲方又当乙方又当中间人，那不是协作，是自己跟自己
    说话——这个默认值曾经就是本机，人点「发起」卡死二十秒，看起来像网络故障。
    """
    from frago.team.state import DEFAULT_RELAY_URL

    assert "127.0.0.1" not in DEFAULT_RELAY_URL
    assert "localhost" not in DEFAULT_RELAY_URL
    assert DEFAULT_RELAY_URL.startswith("https://")


def test_不需要账号口令就能用():
    """两个想结对的人手里只有一个连接码。

    要求他们先在中继那台服务器上注册账号，等于把一个两人之间的暗号换成一套账号体系。
    """
    assert Relay(url="https://www.frago.ai").configured()
