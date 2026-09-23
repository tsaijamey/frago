"""结对场景里 agent 拿到的指引：前缀、核实、场景、规则、手册，彼此对得上。

实际发生过：主人在界面右栏亲手给队友发了一句「报告你的系统info」，对方的 agent 读到
的前缀是「我是 team 伙伴的 Agent」，它想核实这个连接码，去查了 channel 和 remote——
结对关系根本不记在那两处——查无此码，于是拒绝。前缀说错了发件人，手册里没有 team，
也没有任何核实办法。
"""

from __future__ import annotations

import json
import re
from importlib.resources import files as pkg_files
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from frago.cli.team_commands import team_group
from frago.team import state as team_state
from frago.team import sync
from frago.team.state import TeamBinding, TeamState

RESOURCES = pkg_files("frago.resources")
CODE = "ABCDEFGHJK"


@pytest.fixture(autouse=True)
def 状态文件(tmp_path: Path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr(team_state, "STATE_PATH", path)
    return path


def _paired(session_id: str = "s-1") -> tuple[TeamState, TeamBinding]:
    binding = TeamBinding(code=CODE, session_id=session_id, side="B", secret="k")
    state = TeamState(member="m")
    state.teams[CODE] = binding
    team_state.save_state(state)
    return state, binding


# ── 前缀 ────────────────────────────────────────────────────────────────


def test_存着旧默认前缀的机器换成新默认(状态文件: Path):
    状态文件.write_text(json.dumps({"member": "m", "prefix": team_state._OLD_DEFAULT_PREFIX}))
    assert team_state.load_state().prefix == team_state.DEFAULT_PREFIX


def test_人自己改过的前缀原样保留(状态文件: Path):
    状态文件.write_text(json.dumps({"member": "m", "prefix": "队友说："}))
    assert team_state.load_state().prefix == "队友说："


def test_新默认前缀不再把发件人说成_agent():
    rendered = team_state.render_prefix(team_state.DEFAULT_PREFIX, CODE)
    assert "我是 team 伙伴的 Agent" not in rendered
    assert "不是本机主人" in rendered and CODE in rendered


def test_核实那一行不随前缀被改没():
    out = team_state.render_delivery("随便写的前缀", CODE, "m" * 32, "做点事")
    assert out.endswith(team_state.VERIFY_LINE.format(code=CODE, message="m" * 32))


# ── 核实 ────────────────────────────────────────────────────────────────


def _pull_one(monkeypatch, mid: str) -> None:
    monkeypatch.setattr(sync, "_push_records", lambda *a, **k: 0)
    monkeypatch.setattr(
        sync, "_call",
        lambda *a, **k: {"messages": [{"id": mid, "text": "报告系统info"}], "peer_present": True},
    )


def test_真经中继投进来的消息核实得过(monkeypatch):
    state, binding = _paired()
    mid = "a" * 32
    _pull_one(monkeypatch, mid)
    seen: list[str] = []

    def deliver(prompt: str) -> None:
        seen.append(prompt)

    sync.sync_once(state, binding, deliver)
    line = re.search(r"--team-code (\S+) --message (\S+)）", seen[0])
    assert line is not None
    verdict = sync.verify_message(team_state.load_state(), line.group(1), line.group(2))
    assert verdict.genuine and verdict.session_id == "s-1"


def test_投一条就落盘_收件方马上核实也查得到(monkeypatch):
    state, binding = _paired()
    monkeypatch.setattr(sync, "_push_records", lambda *a, **k: 0)
    monkeypatch.setattr(sync, "_call", lambda *a, **k: {"messages": [
        {"id": "1" * 32, "text": "第一条"}, {"id": "2" * 32, "text": "第二条"},
    ], "peer_present": True})
    checked: list[bool] = []

    def deliver(prompt: str) -> None:
        if "第二条" in prompt:
            # 第二条投进去的那一刻，第一条必须已经在盘上
            checked.append(sync.verify_message(team_state.load_state(), CODE, "1" * 32).genuine)

    sync.sync_once(state, binding, deliver)
    assert checked == [True]


@pytest.mark.parametrize("code,mid,why", [
    (CODE, "f" * 32, "投递记录里没有"),
    ("ZZZZZZZZZZ", "a" * 32, "没有参加"),
    (CODE, "abc", "太短"),
])
def test_对不上的一律核实不过(code, mid, why):
    state, _ = _paired()
    verdict = sync.verify_message(state, code, mid)
    assert not verdict.genuine and why in verdict.reason


def test_退出之后的消息核实不过():
    state, binding = _paired()
    binding.delivered.append("a" * 32)
    binding.active = False
    assert not sync.verify_message(state, CODE, "a" * 32).genuine


def test_verify_命令用退出码说结果():
    state, binding = _paired()
    binding.delivered.append("a" * 32)
    team_state.save_state(state)
    runner = CliRunner()
    ok = runner.invoke(team_group, ["verify", "--team-code", CODE, "--message", "a" * 32])
    bad = runner.invoke(team_group, ["verify", "--team-code", CODE, "--message", "b" * 32])
    assert ok.exit_code == 0 and "核实通过" in ok.output
    assert bad.exit_code == 1 and "核实没通过" in bad.output


# ── 场景 ────────────────────────────────────────────────────────────────


def _as_session(monkeypatch, sid: str | None) -> None:
    import frago.session.self_id as self_id

    monkeypatch.setattr(
        self_id, "resolve_self",
        lambda **_: SimpleNamespace(session_id=sid) if sid else None,
    )


def test_没在任何_team_里时场景一个字都不说():
    out = CliRunner().invoke(team_group, ["scene", "--for-hook"])
    assert out.exit_code == 0 and out.output == ""


def test_别的会话不受打扰(monkeypatch):
    _paired("s-1")
    _as_session(monkeypatch, "s-other")
    assert CliRunner().invoke(team_group, ["scene", "--for-hook"]).output == ""


def test_结对中的会话拿到场景和规矩(monkeypatch):
    _paired("s-1")
    _as_session(monkeypatch, "s-1")
    out = CliRunner().invoke(team_group, ["scene", "--for-hook"]).output
    assert CODE in out and "frago team verify" in out and "先问主人" in out
    assert "NEVER 替主人授权" in out


def test_认不出是哪一场时列出来让它自己对照(monkeypatch):
    _paired("s-1")
    _as_session(monkeypatch, None)
    out = CliRunner().invoke(team_group, ["scene", "--for-hook"]).output
    assert "{{session_id}}" in out and "s-1" in out


# ── 规则与手册 ──────────────────────────────────────────────────────────


def _rules() -> list[dict]:
    return json.loads((RESOURCES / "hook" / "builtin-rules.json").read_text(encoding="utf-8"))["rules"]


def _sections(topic: str) -> list[str]:
    text = (RESOURCES / "book" / f"{topic}.md").read_text(encoding="utf-8")
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def test_认队友消息的规则跟投递时加的那一行对得上():
    rendered = team_state.render_delivery("x", CODE, "a" * 32, "y")
    matchers = [r["match"]["value"] for r in _rules()
                if r["id"].startswith("builtin-prompt-team-message")]
    assert matchers and all(value in rendered for value in matchers)


def test_规则引用的手册小节都存在():
    sections = _sections("team-pairing")
    for rule in _rules():
        action = rule["action"]
        if action.get("topic") == "team-pairing" and "section" in action:
            assert action["section"] in sections, rule["id"]


def test_手册登记进了目录():
    index = (RESOURCES / "book" / "_index.yaml").read_text(encoding="utf-8")
    assert "- name: team-pairing" in index


def test_手册覆盖了全部子命令():
    book = (RESOURCES / "book" / "team-pairing.md").read_text(encoding="utf-8")
    for name in team_group.commands:
        assert f"frago team {name}" in book, name
