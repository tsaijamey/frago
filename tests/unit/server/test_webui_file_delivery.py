"""WebUI file:// 链接交付链路与目录探针的回归测试。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from frago.server.routes import workbench as workbench_routes
from frago.server.services import coreagent_runner, session_send, workbench_new_session


def test_builtin_rules_include_webui_file_links_rule():
    """随包 builtin-rules.json 必须包含面向 WebUI 载体的 file:// 超链接交付规则。"""
    rules_path = (
        Path(__file__).resolve().parents[3] / "src" / "frago" / "resources" / "hook" / "builtin-rules.json"
    )
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = {rule["id"]: rule for rule in data["rules"]}
    assert "builtin-prompt-file-links" in rules

    rule = rules["builtin-prompt-file-links"]
    assert rule.get("enabled", True) is True
    assert rule["event"] == "UserPromptSubmit"
    assert rule["dedup_scope"] == "always"
    clauses = rule["match"]["clauses"]
    assert {
        "type": "any_of",
        "clauses": [
            {"type": "env_exists", "name": "FRAGO_CONV_KEY"},
            {
                "type": "not",
                "clause": {"type": "env_ne", "name": "FRAGO_SURFACE", "value": "webui"},
            },
        ],
    } in clauses
    context = rule["action"]["text"]
    assert "file://" in context
    assert "%20" in context
    assert "目录" in context


def test_coreagent_runner_spawn_injects_frago_surface_only_when_specified(monkeypatch, tmp_path):
    """CoreAgent 仅在显式传入 surface='webui' 时注入 FRAGO_SURFACE，不污染非 WebUI 调用方。"""
    seen_envs: list[dict[str, str]] = []

    class FakeProc:
        def __init__(self, env):
            self.env = env
            self.pid = 12345
            self.returncode = None
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("")

        def poll(self):
            return 0

    def fake_popen(cmd, **kwargs):
        seen_envs.append(dict(kwargs.get("env") or {}))
        return FakeProc(kwargs.get("env"))

    class DummyThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(coreagent_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(coreagent_runner, "binary", lambda: Path("/bin/echo"))
    monkeypatch.setattr(coreagent_runner.threading, "Thread", DummyThread)
    monkeypatch.delenv("FRAGO_SURFACE", raising=False)

    # 1. WebUI 会话显式设置 surface="webui"
    sess_webui = coreagent_runner._Session(
        session_id="core_webui_1", cwd=str(tmp_path), title=None, surface="webui"
    )
    coreagent_runner._spawn(sess_webui)
    assert seen_envs[-1].get("FRAGO_SURFACE") == "webui"

    # 2. 非 WebUI 调用方（如定时任务）未设 surface 时不注入
    sess_cli = coreagent_runner._Session(
        session_id="core_cli_1", cwd=str(tmp_path), title=None, surface=None
    )
    coreagent_runner._spawn(sess_cli)
    assert "FRAGO_SURFACE" not in seen_envs[-1]


def test_session_send_and_new_session_forward_webui_surface_to_coreagent(monkeypatch):
    """WebUI 发消息与新建 CoreAgent 会话均传入 surface='webui'。"""
    calls: list[dict] = []

    def fake_core_send(session_id, prompt, *, cwd, title=None, wait_s=None, surface=None):
        calls.append({"fn": "send", "sid": session_id, "surface": surface})
        return None

    def fake_core_queued(session_id, prompt, *, cwd, surface=None):
        calls.append({"fn": "queued", "sid": session_id, "surface": surface})
        return "q1"

    monkeypatch.setattr(coreagent_runner, "send", fake_core_send)
    monkeypatch.setattr(coreagent_runner, "send_queued", fake_core_queued)
    monkeypatch.setattr(
        session_send,
        "resolve_target",
        lambda sid, cwd_hint=None: SimpleNamespace(
            session_id=sid,
            family="coreagent",
            agent_type="coreagent",
            cwd="/tmp/repo",
            is_new=False,
        ),
    )

    session_send.send("core_1", "test")
    session_send.send_queued("core_1", "test2")
    launch = SimpleNamespace(handle="core_2", cwd="/tmp/repo", display_name="CoreAgent", error=None, finished=False)
    workbench_new_session._run_coreagent_first_turn(launch, "first")

    assert calls == [
        {"fn": "send", "sid": "core_1", "surface": "webui"},
        {"fn": "queued", "sid": "core_1", "surface": "webui"},
        {"fn": "send", "sid": "core_2", "surface": "webui"},
    ]


@pytest.mark.asyncio
async def test_probe_session_path_returns_is_dir_flag(tmp_path, monkeypatch):
    """probe_session_path 准确区分文件与目录并附带 is_dir 字段。"""
    sub = tmp_path / "00_下载原件-20261120"
    sub.mkdir()
    doc = sub / "note.md"
    doc.write_text("# hi\n", encoding="utf-8")

    card = SimpleNamespace(session_id="sid-probe", directory=str(tmp_path))
    monkeypatch.setattr(workbench_routes.record_reader, "list_sessions", lambda: [card])

    dir_res = await workbench_routes.probe_session_path("sid-probe", "00_下载原件-20261120")
    assert dir_res["exists"] is True
    assert dir_res["is_dir"] is True
    assert dir_res["is_file"] is False
    assert dir_res["resolved"] == str(sub.resolve())

    file_res = await workbench_routes.probe_session_path("sid-probe", "00_下载原件-20261120/note.md")
    assert file_res["exists"] is True
    assert file_res["is_dir"] is False
    assert file_res["is_file"] is True
    assert file_res["resolved"] == str(doc.resolve())
