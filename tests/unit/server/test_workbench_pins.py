"""置顶会话名单：存盘那一层与三条接口。

这些用例盯的是名单自己的承诺——存在服务端所以换个壳还在、次序由人说了算、不设上限、
坏掉的文件不连累左栏。会话清单长什么样不在这里管，那由 ``test_workbench_routes.py``
把关。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from frago.server.services import workbench_pins

CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
CC_SID2 = "11b13080-8fc5-6d81-a5bf-978d9392f407"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"


@pytest.fixture(autouse=True)
def pins_file(tmp_path, monkeypatch):
    """名单落在临时目录，用例 NEVER 碰真人的 ``~/.frago/workbench_pins.json``。"""
    path = tmp_path / ".frago" / "workbench_pins.json"
    monkeypatch.setattr(workbench_pins, "PINS_FILE", path)
    return path


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


class TestStore:
    def test_一开始一场都没置顶(self):
        assert workbench_pins.list_pins() == []

    def test_置顶之后名单里就有它(self):
        assert workbench_pins.pin(CC_SID) == [CC_SID]
        assert workbench_pins.list_pins() == [CC_SID]

    def test_最近置顶的排在最前(self):
        workbench_pins.pin(CC_SID)
        workbench_pins.pin(OC_SID)
        assert workbench_pins.list_pins() == [OC_SID, CC_SID]

    def test_再置顶一次是挪到最前而不是加一行(self):
        """人对着已经置顶的那场再点一次，要的是"提到眼皮底下"，不是多一行重复。"""
        workbench_pins.pin(CC_SID)
        workbench_pins.pin(OC_SID)
        assert workbench_pins.pin(CC_SID) == [CC_SID, OC_SID]

    def test_取消置顶只去掉那一场(self):
        workbench_pins.pin(CC_SID)
        workbench_pins.pin(OC_SID)
        assert workbench_pins.unpin(CC_SID) == [OC_SID]

    def test_取消一场本来就没置顶的不算失败(self):
        workbench_pins.pin(CC_SID)
        assert workbench_pins.unpin(OC_SID) == [CC_SID]

    def test_名单落在盘上_换个壳打开还在(self, pins_file):
        """置顶存服务端的全部理由：桌面客户端与浏览器的本地存储天生不通。"""
        workbench_pins.pin(CC_SID)
        assert json.loads(pins_file.read_text(encoding="utf-8")) == {"pinned": [CC_SID]}

    def test_不设数量上限(self):
        """上限是替人做决定。愿意置顶两百场，那两百场对他就是有用的。"""
        many = [f"ses_{i:026d}" for i in range(200)]
        for sid in many:
            workbench_pins.pin(sid)
        assert len(workbench_pins.list_pins()) == 200

    def test_文件坏了当作空名单而不是抛(self, pins_file):
        """置顶是锦上添花的一层，它坏了 NEVER 连累人看会话清单。"""
        pins_file.parent.mkdir(parents=True, exist_ok=True)
        pins_file.write_text("{ 这不是 JSON", encoding="utf-8")
        assert workbench_pins.list_pins() == []

    def test_文件里混进脏数据时只留认得出的编号(self, pins_file):
        pins_file.parent.mkdir(parents=True, exist_ok=True)
        pins_file.write_text(
            json.dumps({"pinned": [CC_SID, None, 42, "", "  ", OC_SID]}), encoding="utf-8"
        )
        assert workbench_pins.list_pins() == [CC_SID, OC_SID]

    def test_空编号不受理(self):
        with pytest.raises(ValueError):
            workbench_pins.pin("   ")

    def test_过长的编号不受理(self):
        with pytest.raises(ValueError):
            workbench_pins.pin("x" * (workbench_pins.MAX_ID_LEN + 1))


class TestRoutes:
    def test_没置顶时回一份空名单而不是_404(self, client):
        response = client.get("/api/workbench/pins")
        assert response.status_code == 200
        assert response.json() == {"pinned": []}

    def test_置顶之后取回来的名单里有它(self, client):
        assert client.put(f"/api/workbench/pins/{CC_SID}").json() == {"pinned": [CC_SID]}
        assert client.get("/api/workbench/pins").json() == {"pinned": [CC_SID]}

    def test_置顶回的是整份名单而不是一句成功(self, client):
        """置顶会改次序，只说一句成功的话界面得自己猜新次序，猜错就是两边不一致。"""
        client.put(f"/api/workbench/pins/{CC_SID}")
        assert client.put(f"/api/workbench/pins/{OC_SID}").json() == {
            "pinned": [OC_SID, CC_SID]
        }

    def test_取消置顶回剩下的名单(self, client):
        client.put(f"/api/workbench/pins/{CC_SID}")
        client.put(f"/api/workbench/pins/{OC_SID}")
        assert client.delete(f"/api/workbench/pins/{OC_SID}").json() == {"pinned": [CC_SID]}

    def test_取消一场没置顶的会话仍是_200(self, client):
        """这条接口承诺的是"结束时它不在名单里"，连点两下不该弹报错。"""
        assert client.delete(f"/api/workbench/pins/{CC_SID}").status_code == 200

    def test_三家的编号都置得了顶(self, client):
        for sid in (CC_SID, OC_SID, CC_SID2):
            assert client.put(f"/api/workbench/pins/{sid}").status_code == 200

    def test_不像任何一家的编号置不了顶(self, client):
        """名单里躺一行谁都对不上的编号，从此没人能把它清掉。"""
        assert client.put("/api/workbench/pins/不像任何一家").status_code == 404

    def test_置顶不与会话清单核对(self, client, monkeypatch):
        """档案被滚删过的会话仍然留在名单里——核对过的名单会因为一次滚删悄悄变短。"""
        from frago.session import record_reader

        monkeypatch.setattr(record_reader, "list_sessions", list)
        client.put(f"/api/workbench/pins/{CC_SID}")
        assert client.get("/api/workbench/pins").json() == {"pinned": [CC_SID]}
