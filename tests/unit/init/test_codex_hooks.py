"""codex 钩子注册的单测。

注册文件是 ``$CODEX_HOME/hooks.json``，格式与 Claude Code 的 ``settings.json``
``hooks`` 段同构（事件名 → 匹配器分组 → 处理器）。这里守的是三件事：注册对、
不动别人的钩子、读不动的文件绝不覆盖。
"""

import json

import pytest

from frago.init import codex_hooks

HOOK_CMD = "/Users/x/.frago/bin/frago-core --engine"
SUPPORTED = [
    {"event": "SessionStart", "matcher": ""},
    {"event": "UserPromptSubmit", "matcher": ""},
    {"event": "PreToolUse", "matcher": ""},
]


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    home = tmp_path / ".codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(
        codex_hooks, "query_supported_events", lambda _p: SUPPORTED, raising=False
    )
    monkeypatch.setattr(
        "frago.init.hook_binary.query_supported_events", lambda _p: SUPPORTED
    )
    return home


def _read(home):
    return json.loads((home / "hooks.json").read_text(encoding="utf-8"))


def test_registers_every_event_frago_core_reports(codex_home):
    path = codex_hooks.sync_codex_hook_events(HOOK_CMD)
    assert path == codex_home / "hooks.json"
    hooks = _read(codex_home)["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse"}
    entry = hooks["SessionStart"][0]["hooks"][0]
    assert entry["type"] == "command"
    assert entry["command"] == HOOK_CMD
    # codex 自己的默认超时是 600 秒，挂住的钩子会把一轮拖住十分钟。
    assert entry["timeout"] == codex_hooks.HOOK_TIMEOUT_SECONDS
    assert entry["additionalContextLimit"] == codex_hooks.ADDITIONAL_CONTEXT_LIMIT


def test_is_idempotent(codex_home):
    codex_hooks.sync_codex_hook_events(HOOK_CMD)
    first = (codex_home / "hooks.json").read_text(encoding="utf-8")
    codex_hooks.sync_codex_hook_events(HOOK_CMD)
    assert (codex_home / "hooks.json").read_text(encoding="utf-8") == first


def test_leaves_other_peoples_hooks_alone(codex_home):
    """别人在同一个文件里注册的钩子 MUST 原样活下来，包括在 frago 也注册的事件里。"""
    foreign = {
        "description": "team policy",
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "python3 team.py"}]}
            ],
            "PostToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "audit.sh"}]}
            ],
        },
    }
    (codex_home / "hooks.json").write_text(json.dumps(foreign), encoding="utf-8")

    codex_hooks.sync_codex_hook_events(HOOK_CMD)
    document = _read(codex_home)

    assert document["description"] == "team policy"
    assert document["hooks"]["PostToolUse"] == foreign["hooks"]["PostToolUse"]
    commands = [
        h["command"]
        for group in document["hooks"]["SessionStart"]
        for h in group["hooks"]
    ]
    assert "python3 team.py" in commands
    assert HOOK_CMD in commands


def test_replaces_a_stale_frago_entry_rather_than_adding_a_second(codex_home):
    """升级过的机器上旧登记 MUST 被换掉，NEVER 让同一个事件跑两份 frago 钩子。"""
    stale = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/old/path/frago-hook --engine",
                            "timeout": 10,
                        }
                    ]
                }
            ]
        }
    }
    (codex_home / "hooks.json").write_text(json.dumps(stale), encoding="utf-8")

    codex_hooks.sync_codex_hook_events(HOOK_CMD)
    commands = [
        h["command"]
        for group in _read(codex_home)["hooks"]["SessionStart"]
        for h in group["hooks"]
    ]
    assert commands == [HOOK_CMD]


def test_drops_frago_from_events_it_no_longer_supports(codex_home, monkeypatch):
    codex_hooks.sync_codex_hook_events(HOOK_CMD)
    monkeypatch.setattr(
        "frago.init.hook_binary.query_supported_events",
        lambda _p: [{"event": "SessionStart", "matcher": ""}],
    )
    codex_hooks.sync_codex_hook_events(HOOK_CMD)
    assert set(_read(codex_home)["hooks"]) == {"SessionStart"}


def test_never_overwrites_a_file_it_cannot_read(codex_home):
    """读不动就不动它：重写等于静默删掉用户手写的钩子，而唯一的证据是它们不再触发。"""
    broken = "{ this is not json"
    (codex_home / "hooks.json").write_text(broken, encoding="utf-8")
    assert codex_hooks.sync_codex_hook_events(HOOK_CMD) is None
    assert (codex_home / "hooks.json").read_text(encoding="utf-8") == broken


def test_writes_nothing_when_frago_core_reports_no_events(codex_home, monkeypatch):
    """空事件表意味着查询失败，而不是"frago 想要零个钩子"。"""
    monkeypatch.setattr("frago.init.hook_binary.query_supported_events", lambda _p: [])
    assert codex_hooks.sync_codex_hook_events(HOOK_CMD) is None
    assert not (codex_home / "hooks.json").exists()


def test_skips_machines_without_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "absent"))
    monkeypatch.setattr(codex_hooks.shutil, "which", lambda _n: None)
    assert codex_hooks.sync_codex_hook_events(HOOK_CMD) is None
