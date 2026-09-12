"""会话查看记录：存盘那一层与两条接口。

盯的是这份记录自己的承诺：存服务端所以换个壳还算数、时刻由服务端取、没点开过的不在
名单里、坏掉的文件不连累左栏。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from frago.server.services import workbench_views as views

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"


@pytest.fixture(autouse=True)
def views_file(tmp_path, monkeypatch):
    """记录落在临时目录，用例 NEVER 碰真人的 ``~/.frago/workbench_views.json``。"""
    path = tmp_path / ".frago" / "workbench_views.json"
    monkeypatch.setattr(views, "VIEWS_FILE", path)
    return path


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestStore:
    def test_一开始一场都没点开过(self):
        assert views.list_views() == {}

    def test_点开之后记下时刻(self):
        entry = views.mark_viewed(CC_SID, at=1_753_800_000_000)
        assert entry == {"session_id": CC_SID, "viewed_at": 1_753_800_000_000}
        assert views.list_views() == {CC_SID: 1_753_800_000_000}

    def test_再点开一次就往后挪(self):
        views.mark_viewed(CC_SID, at=1_753_800_000_000)
        views.mark_viewed(CC_SID, at=1_753_900_000_000)
        assert views.list_views()[CC_SID] == 1_753_900_000_000

    def test_没给时刻就取服务端此刻(self):
        """两个时刻要比大小，必须出自同一个钟。"""
        before = views.mark_viewed(CC_SID)["viewed_at"]
        assert before > 1_700_000_000_000

    def test_记录落在盘上_换个壳打开还算数(self, views_file):
        views.mark_viewed(CC_SID, at=1_753_800_000_000)
        assert json.loads(views_file.read_text(encoding="utf-8")) == {
            "viewed": {CC_SID: 1_753_800_000_000}
        }

    def test_文件坏了当作一场都没看过(self, views_file):
        views_file.parent.mkdir(parents=True, exist_ok=True)
        views_file.write_text("{ 这不是 JSON", encoding="utf-8")
        assert views.list_views() == {}

    def test_脏数据只留认得出的(self, views_file):
        views_file.parent.mkdir(parents=True, exist_ok=True)
        views_file.write_text(
            json.dumps({"viewed": {CC_SID: 1_753_800_000_000, "": 5, OC_SID: "昨天", "x": 0}}),
            encoding="utf-8",
        )
        assert views.list_views() == {CC_SID: 1_753_800_000_000}

    def test_空编号与过长的编号不受理(self):
        with pytest.raises(ValueError):
            views.mark_viewed("   ")
        with pytest.raises(ValueError):
            views.mark_viewed("x" * (views.MAX_ID_LEN + 1))


class TestRoutes:
    def test_没点开过时回一份空名单而不是_404(self, client):
        assert client.get("/api/workbench/views").json() == {"viewed": {}}

    def test_点开之后名单里就有它(self, client):
        body = client.put(f"/api/workbench/views/{CC_SID}").json()
        assert body["session_id"] == CC_SID and body["viewed_at"] > 0
        assert list(client.get("/api/workbench/views").json()["viewed"]) == [CC_SID]

    def test_不像任何一家的编号不受理(self, client):
        """名单里躺一行谁都对不上的编号，从此没人能把它清掉。"""
        assert client.put("/api/workbench/views/不像任何一家").status_code == 404

    def test_记录不与会话清单核对(self, client, monkeypatch):
        """会话档案被滚删过也照样留着：核对过的名单会因为一次滚删悄悄变短。"""
        from frago.session import record_reader

        client.put(f"/api/workbench/views/{CC_SID}")
        monkeypatch.setattr(record_reader, "list_sessions", list)
        assert list(client.get("/api/workbench/views").json()["viewed"]) == [CC_SID]
