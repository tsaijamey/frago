"""会话页「交接到新会话」—— 第一句话怎么拼，接口怎么起新会话。

盯的是三件事：

1. 材料齐全时，右栏槽位、人的原话、最后一段回复、动过的文件都进第一句话，而且原话逐字；
2. 右栏槽位没有（旁路 AI 没配连接或没跑过）时照样交接得出去，缺的段落整段不写，
   NEVER 留一个空标题；
3. 新会话与原会话同一家、同一目录，原会话一个字不动。

全程打桩，不碰真实档案、不起真实 tmux。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.server.services import (
    session_observer,
    session_send,
    workbench_handoff,
    workbench_new_session,
    workbench_titles,
)
from frago.session import record_reader
from frago.session.record_reader import SessionCard
from frago.session.unified_record import UnifiedRecord

SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CWD = "/tmp/repo"


def _rec(seq: int, kind: str, payload: dict, agent_path: list[str] | None = None) -> UnifiedRecord:
    return UnifiedRecord(
        id=f"r{seq}",
        session_id=SID,
        group_id=None,
        seq=seq,
        ts=seq,
        kind=kind,  # type: ignore[arg-type]
        agent_path=agent_path or [],
        payload=payload,
    )


RECORDS = [
    _rec(0, "user.say", {"text": "把登录页改成一次性链接"}),
    _rec(
        1,
        "tool.call",
        {"tool_name": "Edit", "tool_family": "file-write", "args": {"file_path": "src/auth.ts"}},
    ),
    _rec(2, "user.say", {"text": "工具结果", "is_tool_result": True}),
    _rec(3, "agent.say", {"text": "子 agent 的中间结果"}, agent_path=["sub-1"]),
    _rec(
        4,
        "tool.call",
        {"tool_name": "Write", "tool_family": "file-write", "args": {"file_path": "src/login.tsx"}},
    ),
    _rec(
        5,
        "tool.call",
        {"tool_name": "Edit", "tool_family": "file-write", "args": {"file_path": "src/auth.ts"}},
    ),
    _rec(
        6,
        "tool.call",
        {
            "tool_name": "apply_patch",
            "tool_family": "file-write",
            "args": "*** Begin Patch\n*** Update File: src/mail.py\n*** End Patch",
        },
    ),
    _rec(
        7,
        "tool.call",
        {"tool_name": "Read", "tool_family": "file-read", "args": {"file_path": "README.md"}},
    ),
    _rec(8, "agent.say", {"text": "登录页改完了，邮件模板还没接。"}),
]

SLOTS = {
    "anchor": {"seq": 0, "text": "把登录页改成一次性链接"},
    "happened": ["改了 src/auth.ts", "新建 src/login.tsx"],
    "tail": {"kind": "now", "text": "等人确认邮件模板用哪套"},
    "decision": "邮件模板用旧的还是新写一套",
}


@pytest.fixture
def patched(monkeypatch):
    """落点、槽位、记录全换成替身。返回可改的槽位，用例自己决定有没有右栏内容。"""
    slots = dict(SLOTS)
    monkeypatch.setattr(
        session_send,
        "resolve_target",
        lambda sid, cwd_hint=None: session_send.SendTarget(
            sid, "claude-code", "claude", CWD, is_new=False
        ),
    )
    monkeypatch.setattr(
        session_observer,
        "load_slots",
        lambda directory, sid, family: {**session_observer.empty_slots(sid, family), **slots},
    )
    monkeypatch.setattr(
        record_reader,
        "read_records",
        lambda sid, after=0, limit=200, tail=False: list(RECORDS),
    )
    return slots


class TestCompose:
    def test_材料齐全时每一段都在(self, patched):
        handoff = workbench_handoff.compose(SID)
        text = handoff.text
        assert handoff.agent_type == "claude"
        assert handoff.cwd == CWD
        assert SID in text and CWD in text
        for heading in ("## 这场在做什么", "## 已经发生的事", "## 停在哪", "## 等人拍板的事"):
            assert heading in text
        assert "邮件模板用旧的还是新写一套" in text
        # 新会话起来先不动手，等人发下一句。
        assert "现在不要做任何事" in text
        assert "## 你第一步" not in text

    def test_人的原话逐字_工具结果不算(self, patched):
        text = workbench_handoff.compose(SID).text
        assert '"""\n把登录页改成一次性链接\n"""' in text
        assert "工具结果" not in text.split("## 人的原话")[1].split("##")[0]

    def test_最后一段回复取主会话的_不取子agent的(self, patched):
        text = workbench_handoff.compose(SID).text
        assert "登录页改完了，邮件模板还没接。" in text
        assert "子 agent 的中间结果" not in text

    def test_动过的文件去重_按最后一次写排_读过的不算(self, patched):
        files = workbench_handoff.touched_files(RECORDS)
        assert files == ["src/login.tsx", "src/auth.ts", "src/mail.py"]
        assert "README.md" not in workbench_handoff.compose(SID).text

    def test_右栏没有内容时照样交接得出去(self, patched):
        patched.clear()
        text = workbench_handoff.compose(SID).text
        for heading in ("## 这场在做什么", "## 已经发生的事", "## 停在哪", "## 等人拍板的事"):
            assert heading not in text
        assert "## 人的原话" in text
        assert "## 原会话最后一段回复" in text
        assert "## 动过的文件" in text
        assert "人发来下一句之后" in text

    def test_图片标记不带过去_免得被认成附图(self, patched, monkeypatch):
        records = [
            *RECORDS,
            _rec(9, "user.say", {"text": "这是什么错误 [Image #1] [Image #2]"}),
        ]
        monkeypatch.setattr(
            record_reader,
            "read_records",
            lambda sid, after=0, limit=200, tail=False: list(records),
        )
        text = workbench_handoff.compose(SID).text
        assert "[Image #" not in text
        assert "这是什么错误 （这里附了图） （这里附了图）" in text

    def test_还没有记录的会话交接不了(self, monkeypatch):
        monkeypatch.setattr(
            session_send,
            "resolve_target",
            lambda sid, cwd_hint=None: session_send.SendTarget(
                sid, "claude-code", "claude", None, is_new=True
            ),
        )
        with pytest.raises(workbench_handoff.HandoffUnavailable):
            workbench_handoff.compose(SID)

    def test_人的原话不够时往回翻页(self, monkeypatch, patched):
        """尾巴那一页全是工具调用时，要往前翻才找得到人说的话。"""
        tail = [
            _rec(seq, "tool.call", {"tool_name": "Bash", "args": {}}) for seq in range(500, 1000)
        ]
        head = [_rec(seq, "user.say", {"text": f"第 {seq} 句"}) for seq in range(0, 500)]
        calls: list[tuple[int, int, bool]] = []

        def read(sid, after=0, limit=200, tail_flag=False, **kw):
            is_tail = kw.get("tail", tail_flag)
            calls.append((after, limit, is_tail))
            return tail if is_tail else [r for r in head if after <= r.seq < after + limit]

        monkeypatch.setattr(record_reader, "read_records", read)
        text = workbench_handoff.compose(SID).text
        assert "第 499 句" in text
        assert len(calls) == 2


class TestNumberedPair:
    def test_没带序号的从1开始(self):
        assert workbench_titles.numbered_pair("修登录页") == ("修登录页 #1", "修登录页 #2")

    def test_已经带序号的原会话不动_新会话接着数(self):
        assert workbench_titles.numbered_pair("修登录页 #2") == ("修登录页 #2", "修登录页 #3")

    def test_长标题截短后再挂序号(self):
        old, new = workbench_titles.numbered_pair("字" * 100)
        assert old.endswith("… #1") and new.endswith("… #2")
        assert len(old) < 70

    def test_光有序号没有正文的不当成序号名(self):
        assert workbench_titles.numbered_pair("#3") == ("#3 #1", "#3 #2")


@pytest.fixture
def titles_file(tmp_path, monkeypatch):
    path = tmp_path / "workbench_titles.json"
    monkeypatch.setattr(workbench_titles, "TITLES_FILE", path)
    return path


class TestRoute:
    @pytest.fixture
    def client(self, titles_file, monkeypatch):
        from frago.server.app import create_app

        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [
                SessionCard(
                    session_id=SID,
                    family="claude-code",
                    title="修登录页",
                    directory=CWD,
                    created_at=0,
                    last_active_at=0,
                )
            ],
        )
        return TestClient(create_app(), client=("127.0.0.1", 50000))

    def test_两场各起一个带序号的名字_清单里看得到(self, client, monkeypatch, patched):
        monkeypatch.setattr(
            workbench_new_session,
            "start_with_id",
            lambda agent_type, cwd, prompt, *, session_id: workbench_new_session.PendingLaunch(
                handle=session_id,
                agent_type=agent_type,
                display_name="Claude Code",
                cwd=cwd,
                session_id=session_id,
            ),
        )
        monkeypatch.setattr(
            "frago.server.services.tmux_sessions_service.open_session_names", lambda: set()
        )
        body = client.post(f"/api/workbench/sessions/{SID}/handoff").json()
        assert (body["old_title"], body["new_title"]) == ("修登录页 #1", "修登录页 #2")
        assert workbench_titles.load() == {SID: "修登录页 #1", body["session_id"]: "修登录页 #2"}
        rows = client.get("/api/workbench/sessions").json()
        assert rows[0]["title"] == "修登录页 #1"

    def test_要等认领编号的那两家_认到了再起名(self, titles_file, monkeypatch):
        launch = workbench_new_session.PendingLaunch(
            handle="webui-x", agent_type="codex", display_name="codex", cwd=CWD
        )
        states = iter([launch, launch])

        def status(handle):
            current = next(states, None)
            if current is None:
                launch.session_id = "01a01a98-82e9-7013-b24e-e5e91b03995a"
                return launch
            return current

        monkeypatch.setattr(workbench_new_session, "status", status)
        monkeypatch.setattr(workbench_handoff, "CLAIM_POLL_S", 0.0)
        workbench_handoff._name_when_claimed("webui-x", "修登录页 #2")
        assert workbench_titles.load() == {launch.session_id: "修登录页 #2"}

    def test_起一场同家同目录的新会话_第一句是交接内容(self, client, monkeypatch, patched):
        started: list[tuple] = []

        def fake_start(agent_type, cwd, prompt, *, session_id):
            started.append((agent_type, cwd, prompt, session_id))
            return workbench_new_session.PendingLaunch(
                handle=session_id,
                agent_type=agent_type,
                display_name="Claude Code",
                cwd=cwd,
                session_id=session_id,
            )

        monkeypatch.setattr(workbench_new_session, "start_with_id", fake_start)
        response = client.post(f"/api/workbench/sessions/{SID}/handoff")
        assert response.status_code == 201
        body = response.json()
        assert len(started) == 1
        agent_type, cwd, prompt, new_sid = started[0]
        assert (agent_type, cwd) == ("claude", CWD)
        assert new_sid != SID
        assert body["session_id"] == new_sid
        assert body["text"] == prompt
        assert prompt.startswith(f"你接手会话 {SID}")

    def test_交接不了回409(self, client, monkeypatch):
        def gone(sid, cwd_hint=None):
            raise session_send.SessionGone("记录没了")

        monkeypatch.setattr(session_send, "resolve_target", gone)
        response = client.post(f"/api/workbench/sessions/{SID}/handoff")
        assert response.status_code == 409
        assert "记录没了" in response.json()["detail"]

    def test_编号不认回404(self, client):
        response = client.post("/api/workbench/sessions/not-a-session/handoff")
        assert response.status_code == 404
