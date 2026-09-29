"""会话页「分支」—— 第一句话怎么拼、起会话之后记什么、收口怎么两边一起改。

盯的是五件事：

1. 第一句话照 spec 的格式，带原会话编号、原文与人写的那句话，回原会话翻记录的办法与交接
   共用同一句；
2. 原会话不改名；
3. 编号到手就把关系账与主线标注都记上；
4. 编号认不到就一样都不记，NEVER 编一个出来；
5. 收口时关系账与标注一起改。

全程打桩：关系账、会话目录、名字表一律换到 ``tmp_path``，不碰真人的 ``~/.frago``，
也不起真实 tmux。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from frago.server.services import (
    session_send,
    workbench_branch,
    workbench_handoff,
    workbench_marks,
    workbench_new_session,
    workbench_titles,
)
from frago.session import record_reader, session_origin

SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CORE_SID = "core_0123456789abcdef0123456789abcdef"
CWD = "/tmp/repo"
BODY = {
    "record_id": "rec-7",
    "text": "ECONNRESET 那个报错",
    "occurrence": 1,
    "note": "这个要不要查",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """关系账、会话目录、名字表都落在临时目录；落点换成替身。"""
    from frago.server.services import session_observer

    monkeypatch.setattr(session_origin, "LAUNCH_LEDGER", tmp_path / "agent-launches.json")
    monkeypatch.setattr(session_origin, "PARENT_SCAN_CACHE", tmp_path / "agent-parent-scan.json")
    monkeypatch.setattr(workbench_titles, "TITLES_FILE", tmp_path / "workbench_titles.json")

    real_detect = record_reader.detect_family

    def detect(sid):
        return "claude-code" if sid == SID else real_detect(sid)

    monkeypatch.setattr(record_reader, "detect_family", detect)

    def session_dir(sid, family):
        # 与真的一致：CoreAgent 那一家没有备份目录。
        if family == "coreagent":
            raise KeyError(family)
        return tmp_path / family / sid

    monkeypatch.setattr(session_observer, "session_dir", session_dir)

    agent_of = {"claude-code": "claude", "coreagent": "coreagent"}

    def resolve_target(sid, cwd_hint=None):
        # 家族照真的判：认不出的编号在这里抛，与真的落点判法同一处出口。
        family = record_reader.detect_family(sid)
        return session_send.SendTarget(sid, family, agent_of[family], CWD, is_new=False)

    monkeypatch.setattr(session_send, "resolve_target", resolve_target)
    session_origin.clear_cache()
    yield tmp_path
    session_origin.clear_cache()


def _ledger():
    return json.loads(session_origin.LAUNCH_LEDGER.read_text(encoding="utf-8"))


def _branch_marks(sid=SID):
    return [m for m in workbench_marks.load_marks(sid)["marks"] if m["kind"] == "branch"]


@pytest.fixture
def started(monkeypatch):
    """起会话换成替身：claude 那样编号当场就有。记下每一次起的是什么。"""
    calls: list[tuple] = []

    def fake_start(agent_type, cwd, prompt, *, session_id):
        calls.append((agent_type, cwd, prompt, session_id))
        return workbench_new_session.PendingLaunch(
            handle=session_id,
            agent_type=agent_type,
            display_name="Claude Code",
            cwd=cwd,
            session_id=session_id,
        )

    monkeypatch.setattr(workbench_new_session, "start_with_id", fake_start)
    return calls


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestRender:
    def test_第一句话照spec的格式(self):
        text = workbench_branch.render(SID, "ECONNRESET 那个报错", "这个要不要查")
        assert text.startswith(
            "这是从另一场会话分出来的旁支问题。主线仍在原会话继续，这里只处理下面这个问题。\n\n"
            f"原会话编号：{SID}（需要细节时按编号回去翻原会话记录）\n"
        )
        assert text.endswith('原文：\n"""\nECONNRESET 那个报错\n"""\n>>> 这个要不要查')

    def test_回原会话的翻法与交接共用同一句(self):
        text = workbench_branch.render(SID, "x", "y")
        assert workbench_handoff.lookup_hint(SID) in text

    def test_图片标记不带过去(self):
        text = workbench_branch.render(SID, "看这张 [Image #2]", "y")
        assert "[Image #" not in text

    def test_标题拿那句话开头(self):
        assert workbench_branch.title_for("  这个  要不要查 ") == "这个 要不要查"
        assert workbench_branch.title_for("字" * 100).endswith("…")


class TestValidate:
    @pytest.mark.parametrize(
        ("record_id", "text", "occurrence", "note"),
        [
            ("r", "原文", 0, "   "),
            ("r", "  ", 0, "问"),
            ("", "原文", 0, "问"),
            ("r", "原文", -1, "问"),
            ("r", "x" * (workbench_marks.MAX_TEXT + 1), 0, "问"),
            ("r", "原文", 0, "x" * (workbench_marks.MAX_NOTE + 1)),
        ],
    )
    def test_不合规矩不起(self, record_id, text, occurrence, note):
        with pytest.raises(workbench_branch.BranchRequestInvalid):
            workbench_branch.validate(record_id, text, occurrence, note)


class TestRoute:
    def test_起分支_记账与标注都写上_原会话不改名(self, client, started):
        res = client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY)
        assert res.status_code == 201
        body = res.json()

        assert len(started) == 1
        agent_type, cwd, prompt, child = started[0]
        assert (agent_type, cwd) == ("claude", CWD)
        assert child != SID and body["session_id"] == child
        assert body["text"] == prompt
        assert f"原会话编号：{SID}" in prompt and ">>> 这个要不要查" in prompt
        assert body["title"] == "这个要不要查"
        assert (body["recorded"], body["mark_saved"]) == (True, True)

        # 原会话不改名：名字表一个字都没写。
        assert workbench_titles.load() == {}

        [entry] = _ledger()
        assert entry["kind"] == "branch"
        assert (entry["child"], entry["parent"]) == (child, SID)
        assert entry["note"] == "这个要不要查"
        assert entry["anchor"] == {
            "record_id": "rec-7",
            "text": "ECONNRESET 那个报错",
            "occurrence": 1,
            "mark_id": body["mark_id"],
        }
        assert entry["closed_at"] is None

        [mark] = _branch_marks()
        assert mark["id"] == body["mark_id"]
        assert (mark["record_id"], mark["text"], mark["occurrence"]) == (
            "rec-7",
            "ECONNRESET 那个报错",
            1,
        )
        assert (mark["child_session_id"], mark["closed"]) == (child, False)

    def test_分支在清单里算人开的_挂在原会话下(self, client, started):
        child = client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY).json()["session_id"]
        index = session_origin.load_origin_index(use_memo=False, projects_root=_empty_projects())
        assert index.origin_of(child) == "human"
        assert index.parent_of(child) == SID
        assert index.relation_of(child) == session_origin.SessionRelation("branch")

    def test_同一段原文分两次是两条独立的分支(self, client, started):
        a = client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY).json()
        b = client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY).json()
        assert a["session_id"] != b["session_id"]
        assert len(_ledger()) == 2
        assert {m["child_session_id"] for m in _branch_marks()} == {
            a["session_id"],
            b["session_id"],
        }

    def test_没写那句话回400_不起会话(self, client, started):
        res = client.post(f"/api/workbench/sessions/{SID}/branch", json={**BODY, "note": " "})
        assert res.status_code == 400
        assert started == []
        assert not session_origin.LAUNCH_LEDGER.exists()

    def test_落点判不出回409(self, client, started, monkeypatch):
        def gone(sid, cwd_hint=None):
            raise session_send.SessionGone("记录没了")

        monkeypatch.setattr(session_send, "resolve_target", gone)
        res = client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY)
        assert res.status_code == 409
        assert started == []

    def test_编号不认回404(self, client, started):
        res = client.post("/api/workbench/sessions/not-a-session/branch", json=BODY)
        assert res.status_code == 404

    def test_存不了标注的那一家_关系照记(self, client, started):
        res = client.post(f"/api/workbench/sessions/{CORE_SID}/branch", json=BODY)
        assert res.status_code == 201
        body = res.json()
        assert (body["recorded"], body["mark_saved"]) == (True, False)
        assert _ledger()[0]["parent"] == CORE_SID


def _empty_projects():
    """一个空的会话库，免得出身索引去扫真人的会话记录。"""
    root = session_origin.LAUNCH_LEDGER.parent / "projects"
    root.mkdir(exist_ok=True)
    return root


class TestClaim:
    """编号要等认领的那两家。"""

    def _branch(self):
        anchor, note = workbench_branch.validate("rec-7", "原文", 0, "问一句")
        return workbench_branch.compose(SID, anchor, note)

    def test_认到编号再记(self, monkeypatch):
        launch = workbench_new_session.PendingLaunch(
            handle="webui-x", agent_type="codex", display_name="codex", cwd=CWD
        )
        states = iter([launch, launch])

        def status(handle):
            if next(states, None) is None:
                launch.session_id = "01a01a98-82e9-7013-b24e-e5e91b03995a"
            return launch

        monkeypatch.setattr(workbench_new_session, "status", status)
        monkeypatch.setattr(workbench_handoff, "CLAIM_POLL_S", 0.0)
        workbench_branch._record_when_claimed(self._branch(), "webui-x")
        [entry] = _ledger()
        assert entry["child"] == launch.session_id
        assert _branch_marks()[0]["child_session_id"] == launch.session_id

    def test_首轮跑完仍没认到就一样都不记(self, monkeypatch):
        launch = workbench_new_session.PendingLaunch(
            handle="webui-y", agent_type="opencode", display_name="opencode", cwd=CWD
        )
        launch.finished = True
        monkeypatch.setattr(workbench_new_session, "status", lambda handle: launch)
        workbench_branch._record_when_claimed(self._branch(), "webui-y")
        assert not session_origin.LAUNCH_LEDGER.exists()
        assert _branch_marks() == []

    def test_起的时候编号没到_接口回null而不是编一个(self, client, monkeypatch):
        launch = workbench_new_session.PendingLaunch(
            handle="webui-z", agent_type="codex", display_name="codex", cwd=CWD
        )
        monkeypatch.setattr(workbench_new_session, "start_with_id", lambda *a, **k: launch)
        waited: list[str] = []
        monkeypatch.setattr(
            workbench_branch, "record_when_claimed", lambda branch, handle: waited.append(handle)
        )
        body = client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY).json()
        assert body["session_id"] is None
        assert body["recorded"] is None and body["mark_saved"] is None
        assert waited == ["webui-z"]
        assert not session_origin.LAUNCH_LEDGER.exists()


class TestClose:
    def _start(self, client):
        return client.post(f"/api/workbench/sessions/{SID}/branch", json=BODY).json()["session_id"]

    def test_收口两边一起改(self, client, started):
        child = self._start(client)
        res = client.post(
            f"/api/workbench/sessions/{SID}/branches/{child}/close", json={"by": "bring-back"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["closed_by"] == "bring-back" and body["mark_updated"] is True
        [entry] = _ledger()
        assert entry["closed_by"] == "bring-back" and entry["closed_at"] is not None
        assert _branch_marks()[0]["closed"] is True
        index = session_origin.load_origin_index(use_memo=False, projects_root=_empty_projects())
        assert index.relation_of(child) == session_origin.SessionRelation("branch", closed=True)

    def test_手动收口(self, client, started):
        child = self._start(client)
        res = client.post(
            f"/api/workbench/sessions/{SID}/branches/{child}/close", json={"by": "manual"}
        )
        assert res.json()["closed_by"] == "manual"
        assert _branch_marks()[0]["closed"] is True

    def test_只改对得上的那条分支(self, client, started):
        a = self._start(client)
        b = self._start(client)
        client.post(f"/api/workbench/sessions/{SID}/branches/{a}/close", json={"by": "manual"})
        closed = {m["child_session_id"]: m["closed"] for m in _branch_marks()}
        assert closed == {a: True, b: False}
        assert [e["closed_at"] is not None for e in _ledger()] == [True, False]

    def test_账上没有这条分支回404(self, client):
        res = client.post(
            f"/api/workbench/sessions/{SID}/branches/nobody/close", json={"by": "manual"}
        )
        assert res.status_code == 404

    def test_来路不认得回400(self, client, started):
        child = self._start(client)
        res = client.post(
            f"/api/workbench/sessions/{SID}/branches/{child}/close", json={"by": "auto"}
        )
        assert res.status_code == 400
        assert _ledger()[0]["closed_at"] is None

    def test_页面交回旧的一份也冲不掉分支标注与收口状态(self, client, started):
        # 页面整份覆盖标注。它手里那份若是起分支之前读的、或收口之前读的，
        # 交回来也不能把服务端记的分支抹掉、把收口改回去。
        child = self._start(client)
        client.post(f"/api/workbench/sessions/{SID}/branches/{child}/close", json={"by": "manual"})
        stale = list(workbench_marks.load_marks(SID)["marks"])
        stale[0] = {**stale[0], "closed": False, "child_session_id": "别的"}
        forged = {**stale[0], "id": "mk_forged"}
        workbench_marks.save_marks(SID, {"marks": [*stale, forged]})
        [mark] = _branch_marks()
        assert (mark["child_session_id"], mark["closed"]) == (child, True)

        workbench_marks.save_marks(SID, {"marks": []})
        assert [m["child_session_id"] for m in _branch_marks()] == [child]
