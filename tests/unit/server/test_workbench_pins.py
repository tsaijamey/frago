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
        """置顶存服务端的全部理由：不同浏览器、不同设备的本地存储天生不通。"""
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


class TestFilePins:
    def test_文件固定项规范化_去重与绝对路径校验(self):
        assert workbench_pins.list_file_pins() == []
        res = workbench_pins.pin_file("/Users/frago/Repos/", is_dir=True)
        assert res == [{"path": "/Users/frago/Repos", "is_dir": True}]
        # 重复固定同一路径（不带末尾斜杠）保持幂等不增行
        assert workbench_pins.pin_file("/Users/frago/Repos", is_dir=True) == res
        with pytest.raises(ValueError):
            workbench_pins.pin_file("relative/path.md", is_dir=False)
        with pytest.raises(ValueError):
            workbench_pins.pin_file("~/notes.md", is_dir=False)

    def test_文件固定项与会话置顶互不覆盖(self):
        workbench_pins.pin(CC_SID)
        workbench_pins.pin_file("/Users/frago/notes.md", is_dir=False)
        workbench_pins.pin_recipe_app("kline")
        assert workbench_pins.list_pins() == [CC_SID]
        assert workbench_pins.list_file_pins() == [{"path": "/Users/frago/notes.md", "is_dir": False}]
        assert workbench_pins.list_recipe_app_pins() == ["kline"]
        # 取消其中一类不影响另外两类
        workbench_pins.unpin_file("/Users/frago/notes.md")
        assert workbench_pins.list_file_pins() == []
        assert workbench_pins.list_pins() == [CC_SID]
        assert workbench_pins.list_recipe_app_pins() == ["kline"]

    def test_合并文件固定项自动过滤非法路径并保序去重(self):
        workbench_pins.pin_file("/Users/frago/a", is_dir=True)
        merged = workbench_pins.merge_file_pins(
            [
                {"path": "/Users/frago/a/", "is_dir": True},
                {"path": "relative.md", "is_dir": False},
                {"path": "/Users/frago/b.md", "is_dir": False},
            ]
        )
        assert merged == [
            {"path": "/Users/frago/a", "is_dir": True},
            {"path": "/Users/frago/b.md", "is_dir": False},
        ]

    def test_文件固定项接口契约_GET_PUT_DELETE_MERGE(self, client):
        assert client.get("/api/workbench/file-pins").json() == {"pins": []}
        bad = client.put(
            "/api/workbench/file-pins",
            json={"path": "relative.md", "is_dir": False},
        )
        assert bad.status_code == 400
        ok = client.put(
            "/api/workbench/file-pins",
            json={"path": "/Users/frago/Repos/", "is_dir": True},
        )
        assert ok.status_code == 200
        assert ok.json() == {"pins": [{"path": "/Users/frago/Repos", "is_dir": True}]}
        merged = client.post(
            "/api/workbench/file-pins/merge",
            json={
                "pins": [
                    {"path": "/Users/frago/Repos", "is_dir": True},
                    {"path": "/Users/frago/doc.md", "is_dir": False},
                    {"path": "bad/rel.md", "is_dir": False},
                ]
            },
        )
        assert merged.status_code == 200
        assert merged.json() == {
            "pins": [
                {"path": "/Users/frago/Repos", "is_dir": True},
                {"path": "/Users/frago/doc.md", "is_dir": False},
            ]
        }
        deleted = client.delete(
            "/api/workbench/file-pins",
            params={"path": "/Users/frago/Repos"},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"pins": [{"path": "/Users/frago/doc.md", "is_dir": False}]}


class TestRecipeAppPins:
    def test_配方界面固定项_同配方保持已有槽位与默认槽位归一(self):
        assert workbench_pins.list_recipe_app_pins() == []
        kept, pins = workbench_pins.pin_recipe_app("kline/default")
        assert kept == "kline"
        assert pins == ["kline"]
        # 同名配方再来不同槽位时返回已开的那一项
        kept2, pins2 = workbench_pins.pin_recipe_app("kline/r2")
        assert kept2 == "kline"
        assert pins2 == ["kline"]
        assert workbench_pins.unpin_recipe_app("kline") == []
        assert workbench_pins.unpin_recipe_app("kline") == []

    def test_配方界面接口契约_GET_PUT_DELETE_MERGE(self, client):
        assert client.get("/api/workbench/recipe-app-pins").json() == {"pins": []}
        put1 = client.put("/api/workbench/recipe-app-pins", json={"id": "kline/r1"})
        assert put1.status_code == 200
        assert put1.json() == {"kept": "kline/r1", "pins": ["kline/r1"]}
        put2 = client.put("/api/workbench/recipe-app-pins", json={"id": "kline/r2"})
        assert put2.status_code == 200
        assert put2.json() == {"kept": "kline/r1", "pins": ["kline/r1"]}
        merged = client.post(
            "/api/workbench/recipe-app-pins/merge",
            json={"pins": ["kline/r3", "ledger", "board/s1"]},
        )
        assert merged.status_code == 200
        assert merged.json() == {"pins": ["kline/r1", "ledger", "board/s1"]}
        deleted = client.delete("/api/workbench/recipe-app-pins", params={"id": "kline/r1"})
        assert deleted.status_code == 200
        assert deleted.json() == {"pins": ["ledger", "board/s1"]}
