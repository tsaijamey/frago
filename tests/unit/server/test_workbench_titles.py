"""会话详情页标题别名与 CoreAgent 自动生成标题单测。"""

from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from frago.init import hook_binary
from frago.server.services import session_observer, workbench_titles
from frago.session import record_reader
from frago.session.record_reader import SessionCard
from frago.session.unified_record import UnifiedRecord

SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CWD = "/tmp/repo"


def _rec(seq: int, kind: str, payload: dict) -> UnifiedRecord:
    return UnifiedRecord(
        id=f"r{seq}",
        session_id=SID,
        group_id=None,
        seq=seq,
        ts=seq,
        kind=kind,  # type: ignore[arg-type]
        agent_path=[],
        payload=payload,
    )


RECORDS = [
    _rec(0, "user.say", {"text": "为webUI的session detail的title增加一个editable功能"}),
    _rec(1, "agent.say", {"text": "已实现内联标题编辑和星号按钮调用 CoreAgent 生成标题。"}),
]


@pytest.fixture
def sessions_root(tmp_path, monkeypatch):
    """重定向 TITLES_FILE 到临时目录，使 _sessions_base_dir() 落在 tmp_path/sessions。"""
    titles_file = tmp_path / "workbench_titles.json"
    monkeypatch.setattr(workbench_titles, "TITLES_FILE", titles_file)
    return tmp_path / "sessions"


@pytest.fixture
def client(sessions_root, monkeypatch):
    from frago.server.app import create_app

    monkeypatch.setattr(
        record_reader,
        "list_sessions",
        lambda: [
            SessionCard(
                session_id=SID,
                family="claude-code",
                title="原始卡片标题",
                directory=CWD,
                created_at=0,
                last_active_at=0,
            )
        ],
    )
    monkeypatch.setattr(
        "frago.server.services.tmux_sessions_service.open_session_names", lambda: set()
    )
    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestPerSessionTitleStorage:
    def test_写入同目录workbench_title文件并优先于原始标题(self, client, sessions_root):
        # 未修改时使用原始卡片标题
        rows = client.get("/api/workbench/sessions").json()
        assert rows[0]["title"] == "原始卡片标题"

        # 人类修改标题后写入 ~/.frago/sessions/<family>/<sid>/workbench-title.json
        resp = client.put(
            f"/api/workbench/sessions/{SID}/title",
            json={"title": "  自定义会话别名  "},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"session_id": SID, "title": "自定义会话别名"}

        title_file = sessions_root / "claude" / SID / workbench_titles.TITLE_FILENAME
        assert title_file.is_file()
        saved = json.loads(title_file.read_text(encoding="utf-8"))
        assert saved == {"title": "自定义会话别名"}

        # WebUI 列表接口优先返回修改后的标题
        rows_after = client.get("/api/workbench/sessions").json()
        assert rows_after[0]["title"] == "自定义会话别名"

    def test_空标题返回400(self, client):
        resp = client.put(f"/api/workbench/sessions/{SID}/title", json={"title": "   "})
        assert resp.status_code == 400

    def test_未知会话返回404(self, client, monkeypatch):
        monkeypatch.setattr(record_reader, "list_sessions", lambda: [])
        resp = client.put(
            "/api/workbench/sessions/not-a-valid-sid/title",
            json={"title": "新标题"},
        )
        assert resp.status_code == 404


class TestGenerateTitleWithCoreAgent:
    def test_星号按钮调用coreagent生成并持久化到会话目录(
        self, client, sessions_root, monkeypatch
    ):
        monkeypatch.setattr(
            record_reader,
            "detect_family",
            lambda sid: "claude-code",
        )
        monkeypatch.setattr(
            session_observer,
            "load_slots",
            lambda directory, sid, family: {
                **session_observer.empty_slots(sid, family),
                "anchor": {"seq": 0, "text": "为 session detail 增加可编辑标题"},
            },
        )
        monkeypatch.setattr(
            record_reader,
            "read_records",
            lambda sid, after=0, limit=200, tail=False: list(RECORDS),
        )

        captured_prompts: list[str] = []

        def fake_ask(prompt: str) -> str:
            captured_prompts.append(prompt)
            return json.dumps({"title": "「会话详情页可编辑标题与AI生成」"}, ensure_ascii=False)

        monkeypatch.setattr(workbench_titles, "_ask_coreagent", fake_ask)

        resp = client.post(f"/api/workbench/sessions/{SID}/title/generate")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "session_id": SID,
            "title": "会话详情页可编辑标题与AI生成",
        }
        assert len(captured_prompts) == 1
        assert "为webUI的session detail的title增加一个editable功能" in captured_prompts[0]

        title_file = sessions_root / "claude" / SID / workbench_titles.TITLE_FILENAME
        assert title_file.is_file()
        assert json.loads(title_file.read_text(encoding="utf-8"))["title"] == (
            "会话详情页可编辑标题与AI生成"
        )

    def test_coreagent单轮命令行参数符合规范(self, tmp_path, monkeypatch):
        called: dict = {}
        fake_bin = tmp_path / "frago-core"
        fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            called["cmd"] = cmd
            called["input"] = kwargs.get("input")
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "type": "final",
                        "ok": True,
                        "text": json.dumps({"title": "单轮生成标题"}, ensure_ascii=False),
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        monkeypatch.setattr(hook_binary, "get_hook_binary_path", lambda: str(fake_bin))
        monkeypatch.setattr(subprocess, "run", fake_run)

        out = workbench_titles._ask_coreagent("测试提示词")
        cmd = called["cmd"]
        assert cmd[:5] == [
            str(fake_bin),
            "--mode",
            "chat",
            "--as-role",
            "coreagent",
        ]
        assert "--instructions" in cmd
        idx = cmd.index("--instructions")
        assert cmd[idx + 1] == "session-title.md"
        assert "/" not in cmd[idx + 1]
        assert "-p" in cmd and "-" in cmd
        assert called["input"] == "测试提示词"
        assert workbench_titles._parse_generated_title(out) == "单轮生成标题"

    def test_无对话记录返回409(self, client, monkeypatch):
        monkeypatch.setattr(
            record_reader,
            "detect_family",
            lambda sid: "claude-code",
        )
        monkeypatch.setattr(
            session_observer,
            "load_slots",
            lambda directory, sid, family: session_observer.empty_slots(sid, family),
        )
        monkeypatch.setattr(
            record_reader,
            "read_records",
            lambda sid, after=0, limit=200, tail=False: [],
        )
        resp = client.post(f"/api/workbench/sessions/{SID}/title/generate")
        assert resp.status_code == 409
