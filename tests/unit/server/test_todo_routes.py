"""事务清单的两个只读接口。

盯的是接口自己的承诺：顺序不重排、计数不随状态筛选变、词表外的取值当场拒绝而
不是静默筛空、深链能单独取到一件。事务本身怎么存怎么排由 ``tests/unit/`` 里
``frago.todo.store`` 的用例把关，这里全程走临时目录，不碰 ``~/.frago/todo``。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.todo import store


@pytest.fixture
def todo_dir(tmp_path, monkeypatch):
    """把事务目录挪到临时目录——用例绝不能碰本机真实待办。"""
    monkeypatch.setenv("FRAGO_TODO_DIR", str(tmp_path / "todo"))
    return tmp_path / "todo"


@pytest.fixture
def client(todo_dir):
    from frago.server.app import create_app

    # 本机席位：事务是机主自己的账本，非本机调用先撞访问带（见 test_security.py）。
    return TestClient(create_app(), client=("127.0.0.1", 50000))


def _seed() -> None:
    store.add("低优先的那件", priority="low")
    store.add("在做的那件", priority="high", status="doing", tags=["webui"])
    store.add("已经做完的那件", status="done")
    store.add("普通那件", tags=["webui"])


class TestList:
    def test_顺序照搬存储层不重排(self, client):
        """命令行说第一条是 A、页面说是 B，是这里多排一次就会造出的分裂。"""
        _seed()
        ids = [row["id"] for row in client.get("/api/todos").json()["todos"]]
        assert ids == [t.id for t in store.list_todos()]

    def test_一件事务的字段一个不少(self, client):
        _seed()
        row = client.get("/api/todos").json()["todos"][0]
        assert set(row) == {
            "id",
            "title",
            "summary",
            "status",
            "priority",
            "tags",
            "created",
            "updated",
            "done_at",
            "context",
            "steps",
            "done_when",
            "links",
        }

    def test_计数不随状态筛选变(self, client):
        """点进「已完成」看到 1 件、退回「全部」变成 4，人会以为漏了。"""
        _seed()
        unfiltered = client.get("/api/todos").json()["counts"]
        filtered = client.get("/api/todos?status=done").json()
        assert filtered["counts"] == unfiltered
        assert len(filtered["todos"]) == 1

    def test_计数把每一档都报出来(self, client):
        _seed()
        counts = client.get("/api/todos").json()["counts"]
        assert counts == {"all": 4, "todo": 2, "doing": 1, "done": 1, "dropped": 0}

    def test_标签筛选同时收窄计数(self, client):
        """标签这一道筛在计数之前——收窄之后每档还剩几件，也得是真数。"""
        _seed()
        body = client.get("/api/todos?tag=webui").json()
        assert body["counts"] == {"all": 2, "todo": 1, "doing": 1, "done": 0, "dropped": 0}

    def test_词表外的状态当场拒绝(self, client):
        """静默筛出个空清单会被读成「一件都没有」，那是谎报。"""
        _seed()
        assert client.get("/api/todos?status=在做").status_code == 400

    def test_词表外的优先级当场拒绝(self, client):
        _seed()
        assert client.get("/api/todos?priority=urgent").status_code == 400

    def test_一件事务都没有时是空清单不是报错(self, client):
        body = client.get("/api/todos")
        assert body.status_code == 200
        assert body.json()["todos"] == []
        assert body.json()["counts"]["all"] == 0


class TestDetail:
    def test_按编号取单件(self, client):
        todo = store.add("单独取这件")
        body = client.get(f"/api/todos/{todo.id}").json()
        assert body["id"] == todo.id
        assert body["title"] == "单独取这件"

    def test_前缀也认(self, client):
        """深链带的是完整编号，但人手敲一截前缀同样该认——与命令行一致。"""
        todo = store.add("前缀取这件")
        assert client.get(f"/api/todos/{todo.id[:12]}").json()["id"] == todo.id

    def test_没有这件回404(self, client):
        assert client.get("/api/todos/根本没有这件").status_code == 404

    def test_前缀撞多条时报出候选而不是替人挑一条(self, client):
        store.add("撞名的甲")
        store.add("撞名的乙")
        prefix = store.list_todos()[0].id[:8]
        response = client.get(f"/api/todos/{prefix}")
        assert response.status_code == 400
        assert "ambiguous" in response.json()["detail"]
