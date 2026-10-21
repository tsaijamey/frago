"""会话页文件预览（FileViewer）文档批注：落盘服务与读写路由测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from frago.server.services import file_annotations as fa
from frago.server.services.workbench_marks import MarksError

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
UNKNOWN_SID = "not a session id"


def annotation(**fields):
    base = {
        "id": "ann_1",
        "file": "~/Repos/frago/src/frago/server/services/session_observer.py",
        "line_start": 4,
        "line_end": 7,
        "quote": "def write_slots(session_id: str, slots: dict) -> None:",
        "note": "同目录写临时文件再 os.replace 原子替换",
        "created_at": 1700000000000,
    }
    base.update(fields)
    return base


@pytest.fixture(autouse=True)
def session_dirs(tmp_path, monkeypatch):
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


class TestFileAnnotationsService:
    def test_empty_when_not_created(self, session_dirs):
        res = fa.load_file_annotations(CC_SID)
        assert res["version"] == 1
        assert res["annotations"] == []
        assert res["trace_path"].endswith(f"claude-code/{CC_SID}/{fa.ANNOTATIONS_FILENAME}")

    def test_save_and_reload(self, session_dirs):
        saved = fa.save_file_annotations(
            CC_SID,
            {"version": 1, "annotations": [annotation(note="改为原子替换")]},
        )
        assert len(saved["annotations"]) == 1
        assert saved["annotations"][0]["note"] == "改为原子替换"
        assert (session_dirs / fa.ANNOTATIONS_FILENAME).exists()
        assert fa.load_file_annotations(CC_SID) == saved

    def test_atomic_write_leaves_no_temp_file(self, session_dirs):
        fa.save_file_annotations(CC_SID, {"annotations": [annotation()]})
        assert [p.name for p in session_dirs.iterdir()] == [fa.ANNOTATIONS_FILENAME]

    def test_corrupted_file_returns_empty_list(self, session_dirs):
        session_dirs.mkdir(parents=True)
        (session_dirs / fa.ANNOTATIONS_FILENAME).write_text("{bad json", encoding="utf-8")
        res = fa.load_file_annotations(CC_SID)
        assert res["annotations"] == []

    @pytest.mark.parametrize(
        "bad",
        [
            {"annotations": [annotation(id="")]},
            {"annotations": [annotation(file="")]},
            {"annotations": [annotation(note="   ")]},
            {"annotations": [annotation(line_start=0)]},
            {"annotations": [annotation(line_start=8, line_end=5)]},
            {"annotations": [annotation(), annotation()]},
            {"annotations": "not-a-list"},
            [],
        ],
    )
    def test_invalid_payload_raises_marks_error(self, bad):
        with pytest.raises(MarksError):
            fa.save_file_annotations(CC_SID, bad)


class TestFileAnnotationsRoutes:
    def test_get_and_put_roundtrip(self, client):
        r1 = client.get(f"/api/workbench/sessions/{CC_SID}/file-annotations")
        assert r1.status_code == 200
        assert r1.json()["annotations"] == []

        item = annotation(id="ann_a", line_start=10, line_end=12)
        r2 = client.put(
            f"/api/workbench/sessions/{CC_SID}/file-annotations",
            json={"version": 1, "annotations": [item]},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert len(body["annotations"]) == 1
        assert body["annotations"][0]["id"] == "ann_a"
        assert "trace_path" in body

        r3 = client.get(f"/api/workbench/sessions/{CC_SID}/file-annotations")
        assert r3.status_code == 200
        assert r3.json() == body

    def test_unknown_session_returns_404(self, client):
        r = client.get(f"/api/workbench/sessions/{UNKNOWN_SID}/file-annotations")
        assert r.status_code == 404

    def test_invalid_payload_returns_400(self, client):
        r = client.put(
            f"/api/workbench/sessions/{CC_SID}/file-annotations",
            json={"version": 1, "annotations": [annotation(note="")]},
        )
        assert r.status_code == 400
