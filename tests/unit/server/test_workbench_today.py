"""今天捡回来用的会话名单：存盘那一层与三条接口。

这些用例盯的是这份名单自己的承诺——只认一天、过期自然消失、下一次写盘顺手清干净、
坏掉的文件不连累左栏。会话清单本身怎么筛不在这里管，那由前端用例把关。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from frago.server.services import workbench_today

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CC_SID2 = "11b13080-8fc5-6d81-a5bf-978d9392f407"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"

TODAY = "2026-10-19"
YESTERDAY = "2026-10-18"


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def today_file(tmp_path, monkeypatch):
    """名单落在临时目录，用例 NEVER 碰真人的 ``~/.frago/workbench_today.json``。"""
    path = tmp_path / ".frago" / "workbench_today.json"
    monkeypatch.setattr(workbench_today, "TODAY_FILE", path)
    return path


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestStore:
    def test_一开始一场都没捡(self):
        assert workbench_today.list_picked(TODAY) == {}

    def test_捡回来之后今天的名单里就有它(self):
        assert workbench_today.pick(CC_SID, TODAY) == {CC_SID: TODAY}
        assert workbench_today.list_picked(TODAY) == {CC_SID: TODAY}

    def test_再捡一场回的是完整名单(self):
        workbench_today.pick(CC_SID, TODAY)
        assert workbench_today.pick(OC_SID, TODAY) == {CC_SID: TODAY, OC_SID: TODAY}

    def test_昨天捡的今天不再显示(self):
        """捡回来只给一天的位置；今天没在里面说过话，第二天自然消失。"""
        workbench_today.pick(CC_SID, YESTERDAY)
        assert workbench_today.list_picked(TODAY) == {}

    def test_写盘时顺手丢掉过期的条目(self, today_file):
        """读的一侧已经按日期筛过，但旧记录不该在盘上越积越多。"""
        workbench_today.pick(CC_SID, YESTERDAY)
        workbench_today.pick(OC_SID, TODAY)
        on_disk = json.loads(today_file.read_text(encoding="utf-8"))
        assert on_disk == {"picked": {OC_SID: TODAY}}

    def test_今天捡过之后第二天取不到(self):
        workbench_today.pick(CC_SID, TODAY)
        assert workbench_today.list_picked(YESTERDAY) == {}
        assert workbench_today.list_picked(TODAY) == {CC_SID: TODAY}

    def test_取消之后今天的名单里就没有它了(self):
        workbench_today.pick(CC_SID, TODAY)
        workbench_today.pick(OC_SID, TODAY)
        assert workbench_today.unpick(CC_SID, TODAY) == {OC_SID: TODAY}

    def test_取消一场本来就没捡的不算失败(self):
        workbench_today.pick(CC_SID, TODAY)
        assert workbench_today.unpick(OC_SID, TODAY) == {CC_SID: TODAY}

    def test_名单落在盘上_换个壳打开还在(self, today_file):
        workbench_today.pick(CC_SID, TODAY)
        assert json.loads(today_file.read_text(encoding="utf-8")) == {
            "picked": {CC_SID: TODAY}
        }

    def test_文件坏了当作空名单而不是抛(self, today_file):
        today_file.parent.mkdir(parents=True, exist_ok=True)
        today_file.write_text("{ 这不是 JSON", encoding="utf-8")
        assert workbench_today.list_picked(TODAY) == {}

    def test_文件里混进脏数据时只留认得出的条目(self, today_file):
        today_file.parent.mkdir(parents=True, exist_ok=True)
        today_file.write_text(
            json.dumps(
                {
                    "picked": {
                        CC_SID: TODAY,
                        "": TODAY,
                        "  ": TODAY,
                        OC_SID: "不是日期",
                        CC_SID2: 42,
                    }
                }
            ),
            encoding="utf-8",
        )
        assert workbench_today.list_picked(TODAY) == {CC_SID: TODAY}

    def test_空编号不受理(self):
        with pytest.raises(ValueError):
            workbench_today.pick("   ", TODAY)

    def test_过长的编号不受理(self):
        with pytest.raises(ValueError):
            workbench_today.pick("x" * (workbench_today.MAX_ID_LEN + 1), TODAY)

    def test_快照带回今天是哪一天(self):
        """过期判定以服务端为准，界面得能看出服务端认为今天是哪天。"""
        workbench_today.pick(CC_SID, TODAY)
        assert workbench_today.snapshot(TODAY) == {"today": TODAY, "picked": [CC_SID]}


class TestRoutes:
    def test_没捡过时回空名单与今天而不是_404(self, client):
        response = client.get("/api/workbench/today")
        assert response.status_code == 200
        body = response.json()
        assert body["picked"] == []
        assert body["today"] == date.today().isoformat()

    def test_捡回来之后取回来的名单里有它(self, client):
        put = client.put(f"/api/workbench/today/{CC_SID}")
        assert put.status_code == 200
        assert put.json()["picked"] == [CC_SID]
        assert client.get("/api/workbench/today").json()["picked"] == [CC_SID]

    def test_捡回来回的是整份名单而不是一句成功(self, client):
        client.put(f"/api/workbench/today/{CC_SID}")
        assert client.put(f"/api/workbench/today/{OC_SID}").json()["picked"] == [
            CC_SID,
            OC_SID,
        ]

    def test_取消回剩下的名单(self, client):
        client.put(f"/api/workbench/today/{CC_SID}")
        client.put(f"/api/workbench/today/{OC_SID}")
        assert client.delete(f"/api/workbench/today/{OC_SID}").json()["picked"] == [
            CC_SID
        ]

    def test_取消一场没捡过的会话仍是_200(self, client):
        assert client.delete(f"/api/workbench/today/{CC_SID}").status_code == 200

    def test_三家的编号都捡得了(self, client):
        for sid in (CC_SID, OC_SID, CC_SID2):
            assert client.put(f"/api/workbench/today/{sid}").status_code == 200

    def test_不像任何一家的编号捡不了(self, client):
        """名单里躺一条谁都对不上的编号，从此没人能把它清掉。"""
        assert client.put("/api/workbench/today/不像任何一家").status_code == 404

    def test_昨天捡的今天从接口里消失(self, client, today_file):
        """次日消失是日期比较的直接结果，不靠定时任务。"""
        today_file.parent.mkdir(parents=True, exist_ok=True)
        today_file.write_text(
            json.dumps({"picked": {CC_SID: _yesterday()}}), encoding="utf-8"
        )
        assert client.get("/api/workbench/today").json()["picked"] == []

    def test_捡回来不与会话清单核对(self, client, monkeypatch):
        """档案被滚删过的会话仍然留在名单里——核对会让一次滚删悄悄撤销人捡的动作。"""
        from frago.session import record_reader

        monkeypatch.setattr(record_reader, "list_sessions", list)
        client.put(f"/api/workbench/today/{CC_SID}")
        assert client.get("/api/workbench/today").json()["picked"] == [CC_SID]
