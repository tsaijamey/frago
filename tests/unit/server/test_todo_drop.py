"""界面上那个「弃置」：id 和人填的理由交给 `frago todo drop` 去执行。

这里不起真进程——起了就会往本机真实待办里写东西，而且被测的本来也不是那条命令
（它自己的用例在 ``tests/unit/cli`` 和 ``tests/unit/todo``）。替掉起进程那一步，
盯的是这一路对界面许下的四个承诺：

- 服务端自己不碰事务文件：落盘的必须是那条命令，参数里带着人填的原话；
- 理由是空的、id 是空的，在起进程之前就拒绝；
- 命令拒绝时（事务不存在、前缀撞了多条、它已经弃置过了）把原话带回去，而不是
  丢一个状态码让人猜；
- 回给界面的是重新读回来的那件事务，不是照着请求拼出来的「应该变成什么样」。
"""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from frago.server.services.todo_drop_service import TodoDropError, TodoDropService
from frago.todo import store


@pytest.fixture(autouse=True)
def _isolate_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_TODO_DIR", str(tmp_path / "todo"))


class FakeCommand:
    """`frago todo drop` 的替身：记下敲出去的那条命令，并按要求装成功或装失败。

    装成功的那一路真的去动存储层——这一路的下半截（重新读回那件事务）只有在盘上
    确实变了的时候才测得出来。
    """

    def __init__(self):
        self.seen: list[list[str]] = []
        self._stderr: str | None = None

    def fail(self, stderr: str) -> None:
        """往后的调用都按命令拒绝处理，``stderr`` 是它留给人读的那句话。"""
        self._stderr = stderr

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.seen.append(cmd)
        if self._stderr is not None:
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="", stderr=self._stderr
            )
        # 命令那边做的事：`frago todo drop <ref> --reason <text>`。
        store.drop(cmd[-3], cmd[-1])
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="Dropped\n", stderr="")


@pytest.fixture
def command(monkeypatch):
    fake = FakeCommand()
    monkeypatch.setattr(TodoDropService, "_run", staticmethod(fake))
    return fake


class TestHandingItToTheCommand:
    def test_理由原样交给命令不改写(self, command):
        todo = store.add("drop me")
        TodoDropService.drop(todo.id, "  上游换了做法，这条不再成立  ")

        cmd = command.seen[0]
        assert cmd[-4:] == ["drop", todo.id, "--reason", "上游换了做法，这条不再成立"]
        # 理由是人自由输入的一段话，里面有引号分号都很正常——参数走列表，不拼成一行。
        assert isinstance(cmd, list)

    def test_落盘的样子按重新读回来的为准(self, command):
        todo = store.add("drop me")
        result = TodoDropService.drop(todo.id, "不做了")
        assert result["todo"]["status"] == "dropped"
        assert result["todo"]["drop_reason"] == "不做了"
        assert result["todo"]["dropped_at"]

    def test_理由是空的就不起进程(self, command):
        todo = store.add("drop me")
        with pytest.raises(TodoDropError, match="必填"):
            TodoDropService.drop(todo.id, "   ")
        assert command.seen == []
        assert store.get(todo.id).status == "todo"

    def test_没说弃置哪一件就不起进程(self, command):
        with pytest.raises(TodoDropError, match="哪一件"):
            TodoDropService.drop("", "不做了")
        assert command.seen == []

    def test_命令拒绝时把它的原话带出来(self, command):
        """「它已经弃置过了」这种话本来就是写给人读的，别改写成别的说法。"""
        command.fail("Error: 20260909-x was already dropped on 2026-09-01: 当初的理由")
        with pytest.raises(TodoDropError) as excinfo:
            TodoDropService.drop("20260909-x", "再来一次")
        assert "当初的理由" in excinfo.value.detail
        # 界面另有报错的样式，命令行那个 "Error: " 前缀顶上去就成了「错误：错误：……」。
        assert not excinfo.value.detail.startswith("Error: ")

    def test_命令没留下话时也要给个说法(self, command):
        command.fail("")
        with pytest.raises(TodoDropError, match="exit code 1"):
            TodoDropService.drop("20260909-x", "不做了")

    def test_超时说成超时(self, monkeypatch):
        def slow(_cmd):
            raise subprocess.TimeoutExpired(cmd="frago", timeout=30)

        monkeypatch.setattr(TodoDropService, "_run", staticmethod(slow))
        with pytest.raises(TodoDropError, match="还没结束"):
            TodoDropService.drop("20260909-x", "不做了")


class TestTheEndpoint:
    @pytest.fixture
    def client(self):
        from frago.server.app import create_app

        # 本机席位：事务是机主自己的账本，非本机调用先撞访问带。
        return TestClient(create_app(), client=("127.0.0.1", 50000))

    def test_弃置之后整件事务和那条命令都回给界面(self, client, command):
        todo = store.add("drop me")
        body = client.post(f"/api/todos/{todo.id}/drop", json={"reason": "不做了"}).json()

        assert body["todo"]["id"] == todo.id
        assert body["todo"]["status"] == "dropped"
        assert body["todo"]["drop_reason"] == "不做了"
        # 界面要把它印出来——看不见执行了什么的按钮，没人敢按第二次。
        assert body["command"][-4:] == ["drop", todo.id, "--reason", "不做了"]

    def test_弃置不成时原因原样带给人看(self, client, command):
        """「HTTP 400」对着人说等于什么都没说。"""
        command.fail("Error: no todo matching 'nope'; run `frago todo list`")
        response = client.post("/api/todos/nope/drop", json={"reason": "不做了"})
        assert response.status_code == 400
        assert "no todo matching" in response.json()["detail"]

    def test_理由是空的当场拒绝(self, client, command):
        todo = store.add("drop me")
        response = client.post(f"/api/todos/{todo.id}/drop", json={"reason": "  "})
        assert response.status_code == 400
        assert command.seen == []
        assert store.get(todo.id).status == "todo"

    def test_清单接口照实带出弃置的日期与理由(self, client, command):
        todo = store.add("drop me")
        client.post(f"/api/todos/{todo.id}/drop", json={"reason": "上游换了做法"})

        row = client.get("/api/todos?status=dropped").json()["todos"][0]
        assert row["drop_reason"] == "上游换了做法"
        assert row["dropped_at"]
