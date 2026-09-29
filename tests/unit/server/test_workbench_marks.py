"""会话页标注（引用、暂存）：存盘那一层与两条接口。

这些用例盯的是标注自己的承诺——跟着会话目录走所以换个浏览器还在、整份覆盖、坏掉的
文件不连累页面、超限整份拒收、认不出的会话回 404。会话目录一律换成 ``tmp_path``，
用例 NEVER 碰真人的 ``~/.frago/sessions``。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from frago.server.services import workbench_marks as wm

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
UNKNOWN_SID = "not a session id"


def mark(**fields):
    base = {
        "id": "mk_1",
        "kind": "stack",
        "record_id": "rec-1",
        "text": "第二个决策点",
        "occurrence": 0,
        "note": "",
        "used": False,
        "created_at": 1,
        "used_at": None,
    }
    base.update(fields)
    return base


@pytest.fixture(autouse=True)
def session_dirs(tmp_path, monkeypatch):
    """会话目录落在临时目录；家族判定只认 CC_SID，其余照真的走（抛认不出）。"""
    from frago.server.services import session_observer
    from frago.session import record_reader

    real_detect = record_reader.detect_family

    def detect(sid):
        return "claude-code" if sid == CC_SID else real_detect(sid)

    monkeypatch.setattr(record_reader, "detect_family", detect)
    monkeypatch.setattr(
        session_observer, "session_dir", lambda sid, family: tmp_path / family / sid
    )
    return tmp_path / "claude-code" / CC_SID


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestStore:
    def test_还没有标注时读出空列表(self):
        assert wm.load_marks(CC_SID) == {"version": 1, "marks": []}

    def test_写下去读得回来(self, session_dirs):
        saved = wm.save_marks(CC_SID, {"version": 1, "marks": [mark(note="先看这条")]})
        assert saved["marks"][0]["note"] == "先看这条"
        assert (session_dirs / wm.MARKS_FILENAME).exists()
        assert wm.load_marks(CC_SID) == saved

    def test_整份覆盖_顺序照交上来的(self):
        wm.save_marks(CC_SID, {"marks": [mark(id="a"), mark(id="b")]})
        wm.save_marks(CC_SID, {"marks": [mark(id="b"), mark(id="c", kind="quote")]})
        assert [m["id"] for m in wm.load_marks(CC_SID)["marks"]] == ["b", "c"]

    def test_认不得的字段丢掉_缺省字段补上(self):
        raw = {"id": "x", "kind": "quote", "record_id": "r", "text": "t", "junk": 1}
        saved = wm.save_marks(CC_SID, {"marks": [raw]})
        assert saved["marks"][0] == {
            "id": "x",
            "kind": "quote",
            "record_id": "r",
            "text": "t",
            "occurrence": 0,
            "note": "",
            "used": False,
            "created_at": 0,
            "used_at": None,
        }

    def test_坏文件读出空列表_不抛(self, session_dirs):
        session_dirs.mkdir(parents=True)
        (session_dirs / wm.MARKS_FILENAME).write_text("{不是 json", encoding="utf-8")
        assert wm.load_marks(CC_SID) == {"version": 1, "marks": []}

    def test_形状不对的文件也读出空列表(self, session_dirs):
        session_dirs.mkdir(parents=True)
        (session_dirs / wm.MARKS_FILENAME).write_text(
            json.dumps({"marks": [{"kind": "nope"}]}), encoding="utf-8"
        )
        assert wm.load_marks(CC_SID)["marks"] == []

    def test_写入不留临时文件(self, session_dirs):
        wm.save_marks(CC_SID, {"marks": [mark()]})
        assert [p.name for p in session_dirs.iterdir()] == [wm.MARKS_FILENAME]

    @pytest.mark.parametrize(
        "bad",
        [
            {"marks": [mark(kind="todo")]},
            {"marks": [mark(text="x" * (wm.MAX_TEXT + 1))]},
            {"marks": [mark(note="x" * (wm.MAX_NOTE + 1))]},
            {"marks": [mark(id=f"m{i}") for i in range(wm.MAX_MARKS + 1)]},
            {"marks": [mark(), mark()]},
            {"marks": [mark(text="")]},
            {"marks": [mark(occurrence=-1)]},
            {"marks": [mark(created_at=True)]},
            {"marks": "nope"},
            [],
        ],
    )
    def test_不合规矩整份拒收_原文件不动(self, bad):
        wm.save_marks(CC_SID, {"marks": [mark(id="keep")]})
        with pytest.raises(wm.MarksError):
            wm.save_marks(CC_SID, bad)
        assert [m["id"] for m in wm.load_marks(CC_SID)["marks"]] == ["keep"]

    def test_上限本身收得下(self):
        payload = {"marks": [mark(id=f"m{i}") for i in range(wm.MAX_MARKS)]}
        payload["marks"][0]["text"] = "x" * wm.MAX_TEXT
        payload["marks"][0]["note"] = "x" * wm.MAX_NOTE
        assert len(wm.save_marks(CC_SID, payload)["marks"]) == wm.MAX_MARKS


class TestRoutes:
    def test_读空(self, client):
        res = client.get(f"/api/workbench/sessions/{CC_SID}/marks")
        assert res.status_code == 200
        assert res.json() == {"version": 1, "marks": []}

    def test_写后读回(self, client):
        body = {"version": 1, "marks": [mark(used=True, used_at=5)]}
        res = client.put(f"/api/workbench/sessions/{CC_SID}/marks", json=body)
        assert res.status_code == 200
        assert res.json()["marks"][0]["used"] is True
        again = client.get(f"/api/workbench/sessions/{CC_SID}/marks")
        assert again.json() == res.json()

    def test_超限回400(self, client):
        body = {"marks": [mark(text="x" * (wm.MAX_TEXT + 1))]}
        res = client.put(f"/api/workbench/sessions/{CC_SID}/marks", json=body)
        assert res.status_code == 400
        assert "text" in res.json()["detail"]

    def test_未知会话回404(self, client):
        assert client.get(f"/api/workbench/sessions/{UNKNOWN_SID}/marks").status_code == 404
        res = client.put(f"/api/workbench/sessions/{UNKNOWN_SID}/marks", json={"marks": [mark()]})
        assert res.status_code == 404


def branch(**fields):
    return mark(**{"kind": "branch", "child_session_id": "child-1", "closed": False, **fields})


class TestCoreAgentMarks:
    """CoreAgent 那一家的标注要能用。

    它的记录另有根目录，但标注是 frago 服务端自己产的旁挂文件，与另外三家同级落在
    ``~/.frago/sessions/coreagent/<编号>/``。从前落点表里没有这一家，``marks_dir`` 抛
    ``KeyError``，页面上暂存与引用一律存不下（2026-09-29 实测）。
    """

    CORE_SID = "core_e2edemo0001"

    def test_标注落在自己那一家的目录下(self, monkeypatch, tmp_path):
        from frago.session import record_reader

        monkeypatch.setattr(record_reader, "detect_family", lambda sid: "coreagent")
        assert wm.marks_dir(self.CORE_SID) == tmp_path / "coreagent" / self.CORE_SID

    def test_写下去读得回来(self, monkeypatch):
        from frago.session import record_reader

        monkeypatch.setattr(record_reader, "detect_family", lambda sid: "coreagent")
        saved = wm.save_marks(self.CORE_SID, {"version": 1, "marks": [mark(note="先看这条")]})
        assert saved["marks"][0]["note"] == "先看这条"
        assert wm.load_marks(self.CORE_SID) == saved

    def test_接口不再回500(self, client, monkeypatch):
        from frago.session import record_reader

        monkeypatch.setattr(record_reader, "detect_family", lambda sid: "coreagent")
        res = client.get(f"/api/workbench/sessions/{self.CORE_SID}/marks")
        assert res.status_code == 200
        assert res.json() == {"version": 1, "marks": []}


class TestBranchMarks:
    """分支标注（spec 20260928-webui-session-branch）：由服务端追加、收口由服务端改。"""

    def test_服务端追加的分支标注读得回来(self):
        entry = wm.append_branch_mark(CC_SID, branch(id="mk_b"))
        assert entry["kind"] == "branch"
        assert (entry["child_session_id"], entry["closed"]) == ("child-1", False)
        assert wm.load_marks(CC_SID)["marks"] == [entry]

    def test_分支标注缺了分出去的会话不收(self):
        with pytest.raises(wm.MarksError):
            wm.normalize_mark(mark(kind="branch"))
        with pytest.raises(wm.MarksError):
            wm.normalize_mark(mark(kind="branch", child_session_id=""))

    def test_引用与暂存不多出分支那两项(self):
        saved = wm.save_marks(CC_SID, {"marks": [mark(child_session_id="x", closed=True)]})
        assert "child_session_id" not in saved["marks"][0]
        assert "closed" not in saved["marks"][0]

    def test_追加不动已有的标注(self):
        wm.save_marks(CC_SID, {"marks": [mark(id="a")]})
        wm.append_branch_mark(CC_SID, branch(id="b"))
        assert [m["id"] for m in wm.load_marks(CC_SID)["marks"]] == ["a", "b"]

    def test_收口只改指向那场会话的分支(self):
        wm.append_branch_mark(CC_SID, branch(id="b1"))
        wm.append_branch_mark(CC_SID, branch(id="b2", child_session_id="child-2"))
        assert wm.set_branch_closed(CC_SID, "child-1") is True
        closed = {m["id"]: m["closed"] for m in wm.load_marks(CC_SID)["marks"]}
        assert closed == {"b1": True, "b2": False}

    def test_没有这条分支时收口返回假(self):
        assert wm.set_branch_closed(CC_SID, "nobody") is False

    def test_页面编不出分支标注(self):
        saved = wm.save_marks(CC_SID, {"marks": [mark(id="a"), branch(id="forged")]})
        assert [m["id"] for m in saved["marks"]] == ["a"]

    def test_页面交回的那份里收口状态以盘上为准(self):
        wm.append_branch_mark(CC_SID, branch(id="b"))
        wm.set_branch_closed(CC_SID, "child-1")
        saved = wm.save_marks(CC_SID, {"marks": [branch(id="b", closed=False)]})
        assert saved["marks"][0]["closed"] is True

    def test_页面手里那份旧了_没带上的分支标注照样留着(self):
        wm.append_branch_mark(CC_SID, branch(id="b"))
        saved = wm.save_marks(CC_SID, {"marks": [mark(id="new-stack")]})
        assert [m["id"] for m in saved["marks"]] == ["new-stack", "b"]

    def test_存不了标注的那一家追加时抛KeyError(self, monkeypatch):
        from frago.server.services import session_observer

        def no_dir(sid, family):
            raise KeyError(family)

        monkeypatch.setattr(session_observer, "session_dir", no_dir)
        with pytest.raises(KeyError):
            wm.append_branch_mark(CC_SID, branch())

    def test_接口读得到分支标注(self, client):
        wm.append_branch_mark(CC_SID, branch(id="b"))
        res = client.get(f"/api/workbench/sessions/{CC_SID}/marks")
        assert res.json()["marks"][0]["child_session_id"] == "child-1"
