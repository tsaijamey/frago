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
        res = client.put(
            f"/api/workbench/sessions/{UNKNOWN_SID}/marks", json={"marks": [mark()]}
        )
        assert res.status_code == 404
