"""界面上那个「添一件」：一句话交给 agent，由它去敲 `frago todo add`。

这里全程不起真进程——起了就得等一个模型跑十几秒，还会往本机真实待办里塞东西。
喂的是内核那一行一个 JSON 的输出，盯的是这一路对界面许下的四个承诺：

- 认得出事务落在哪一件上，以及是新建还是追加到已有那条（界面照实说，不能把追加
  说成新建）；
- 带回界面的那条命令是真正动了账本的那条，不是 agent 自己查重用的 `todo list`；
- agent 跑完却一件都没落下时，说出来而不是假装成功；
- 没配模型、描述是空的，在起进程之前就拒绝——内核在没配模型时会转成交互式追问，
  在服务端那是一个永远等不到输入的进程。
"""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

import pytest
from fastapi.testclient import TestClient

from frago.server.services.todo_compose_service import TodoComposeError, TodoComposeService


def _proc(events: list[dict[str, Any]], *, returncode: int = 0, stderr: str = ""):
    """内核跑完的样子：stdout 一行一个 JSON 事件，stderr 留给人读。"""
    stdout = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    return subprocess.CompletedProcess(
        args=["frago-core"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _tool(args: list[str]) -> dict[str, Any]:
    """CoreAgent 执行 frago 命令走的是 Bash，跟 Claude Code 一样。"""
    return {"type": "tool", "tool_name": "Bash", "input": {"command": shlex.join(["frago", *args])}}


def _result(output: str) -> dict[str, Any]:
    return {"type": "result", "output": output, "denied": False}


@pytest.fixture
def kernel(monkeypatch):
    """替掉起进程那一步，并放行模型检查——这两件事都不该在用例里真的发生。"""
    monkeypatch.setattr(TodoComposeService, "_require_model", staticmethod(lambda: None))
    monkeypatch.setattr(
        TodoComposeService, "_binary_path", staticmethod(lambda: "/nonexistent/frago-core")
    )

    def install(proc):
        monkeypatch.setattr(TodoComposeService, "_run", staticmethod(lambda _cmd: proc))

    return install


class TestReadingWhatTheAgentDid:
    def test_新建的事务认得出id(self, kernel):
        kernel(
            _proc(
                [
                    _tool(["todo", "add", "webui-add-todo-button"]),
                    _result("Created todo 20260909-webui-add-todo-button\nPath: /x.json"),
                    {"type": "done", "final_text": "建好了"},
                ]
            )
        )
        result = TodoComposeService.compose("给事务页加个添加按钮")
        assert result["todo_id"] == "20260909-webui-add-todo-button"
        assert result["created"] is True
        assert result["message"] == "建好了"

    def test_追加到已有那条时不报成新建(self, kernel):
        """这件事已经有一条了，规矩要求 agent 追加。界面得照实说。"""
        kernel(
            _proc(
                [
                    _tool(["todo", "list"]),
                    _result("〔tool output〕\n20260901-same-thing  todo  high  这件事"),
                    _tool(["todo", "log", "20260901-same-thing", "又提了一次"]),
                    _result(
                        "Logged to 20260901-same-thing (todo) · session a4c29a70-3bcd-488f-b02b-3d1275e3f8fb"
                    ),
                    {"type": "done", "final_text": "记到已有那条上了"},
                ]
            )
        )
        result = TodoComposeService.compose("这件事")
        assert result["todo_id"] == "20260901-same-thing"
        assert result["created"] is False

    def test_既追加又新建时以新建的为准(self, kernel):
        """人关心的是新冒出来的那一件，不是被顺手补了一句的旧账。"""
        kernel(
            _proc(
                [
                    _tool(["todo", "log", "20260901-old", "顺手补一句"]),
                    _result(
                        "Logged to 20260901-old (todo) · session a4c29a70-3bcd-488f-b02b-3d1275e3f8fb"
                    ),
                    _tool(["todo", "add", "new-thing"]),
                    _result("Created todo 20260909-new-thing"),
                    {"type": "done", "final_text": "另开了一条"},
                ]
            )
        )
        result = TodoComposeService.compose("另一件事")
        assert result["todo_id"] == "20260909-new-thing"
        assert result["created"] is True

    def test_一件都没落下时说出来(self, kernel):
        """agent 只讲了一通道理没动手——假装成功，人下次就不敢信这个按钮了。"""
        kernel(_proc([{"type": "done", "final_text": "描述太含糊，我没敢建"}]))
        result = TodoComposeService.compose("那个东西")
        assert result["todo_id"] is None
        assert result["created"] is False
        assert "含糊" in result["message"]

    def test_没有最终答复时退回它最后想的那句(self, kernel):
        """给界面一片空白，等于让人对着一个没有回声的按钮猜。"""
        kernel(
            _proc(
                [
                    {"type": "thinking", "text": "我先看看有没有重的"},
                    _tool(["todo", "add", "x"]),
                    _result("Created todo 20260909-x"),
                ]
            )
        )
        assert TodoComposeService.compose("随便一件")["message"] == "我先看看有没有重的"

    def test_读不懂的行跳过而不是整单失败(self, kernel):
        """内核往 stdout 里混进一行别的，不该让一件已经建好的事务变成失败。"""
        proc = _proc([_tool(["todo", "add", "x"]), _result("Created todo 20260909-x")])
        proc.stdout = "not json at all\n" + proc.stdout + "\n\n"
        kernel(proc)
        assert TodoComposeService.compose("一件事")["todo_id"] == "20260909-x"


class TestWhatItRanForMe:
    def test_带回的是动了账本的那条命令(self, kernel):
        """查重用的 todo list 摆到人面前，看着像「按了一下什么也没干」。"""
        kernel(
            _proc(
                [
                    _tool(["todo", "list"]),
                    _result("〔tool output〕\n(一大片清单)"),
                    _tool(["todo", "add", "webui-x", "--summary", "中文摘要"]),
                    _result("Created todo 20260909-webui-x"),
                    {"type": "done", "final_text": "建好了"},
                ]
            )
        )
        assert TodoComposeService.compose("一件事")["command"] == [
            "frago",
            "todo",
            "add",
            "webui-x",
            "--summary",
            "中文摘要",
        ]

    def test_建好之后又补了一步时报的仍是建它的那条(self, kernel):
        """agent 常在建完之后再 log 一句接手第一步。

        界面上「建好了 xxx」下面印的要是那条 log，人看到的是「说建好了，底下却是
        往已有条目上追加」——真界面上撞见过一次。
        """
        kernel(
            _proc(
                [
                    _tool(["todo", "add", "--title", "tags-not-clickable"]),
                    _result("Created todo 20260909-tags-not-clickable"),
                    _tool(["todo", "log", "20260909-tags-not-clickable", "接手第一步：……"]),
                    _result("Logged to 20260909-tags-not-clickable (todo) · session abc"),
                    {"type": "done", "final_text": "建好并补了第一步"},
                ]
            )
        )
        result = TodoComposeService.compose("一件事")
        assert result["created"] is True
        assert result["command"] == ["frago", "todo", "add", "--title", "tags-not-clickable"]

    def test_追加时报的是那条追加命令(self, kernel):
        kernel(
            _proc(
                [
                    _tool(["todo", "log", "20260901-old", "又提了一次"]),
                    _result("Logged to 20260901-old (todo) · session abc"),
                    {"type": "done", "final_text": "记到已有那条上了"},
                ]
            )
        )
        result = TodoComposeService.compose("一件事")
        assert result["created"] is False
        assert result["command"] == ["frago", "todo", "log", "20260901-old", "又提了一次"]

    def test_组合命令里认得出那条_frago_命令(self, kernel):
        """模型常写成 `cd ~ && frago todo add ...`，拆开认，引号里的中文和空格原样保留。"""
        kernel(
            _proc(
                [
                    {
                        "type": "tool",
                        "tool_name": "Bash",
                        "input": {"command": "cd ~ && frago todo add webui-x --summary '中文 摘要'"},
                    },
                    _result("Created todo 20260909-webui-x"),
                    {"type": "done", "final_text": "建好了"},
                ]
            )
        )
        assert TodoComposeService.compose("一件事")["command"] == [
            "frago", "todo", "add", "webui-x", "--summary", "中文 摘要",
        ]

    def test_被拦下没执行的命令不报(self, kernel):
        """拦下的 add 没落盘，界面上不能说「它替你执行了这条」。"""
        kernel(
            _proc(
                [
                    {"type": "tool", "tool_call_id": "c1", "tool_name": "Bash",
                     "input": {"command": "frago todo add blocked-one"}},
                    {"type": "result", "tool_call_id": "c1", "denied": True,
                     "output": "〔not allowed〕不在允许范围"},
                    {"type": "done", "final_text": "被拦了"},
                ]
            )
        )
        assert TodoComposeService.compose("一件事")["command"] is None

    def test_只准它执行_frago_todo(self, kernel, monkeypatch):
        """它手上有 Bash，建一条待办用不着别的命令。"""
        seen = {}

        def run(cmd):
            seen["cmd"] = cmd
            return _proc([{"type": "done", "final_text": "没建"}])

        monkeypatch.setattr(TodoComposeService, "_run", staticmethod(run))
        TodoComposeService.compose("一件事")
        cmd = seen["cmd"]
        assert cmd[cmd.index("--allowed-tools") + 1] == "Bash(frago todo:*)"

    def test_只查了没动手就没有命令可报(self, kernel):
        kernel(
            _proc(
                [
                    _tool(["todo", "list"]),
                    _result("〔tool output〕\n(清单)"),
                    {"type": "done", "final_text": "我没建"},
                ]
            )
        )
        assert TodoComposeService.compose("一件事")["command"] is None


class TestRefusingBeforeSpawning:
    def test_描述是空的当场拒绝(self, kernel):
        kernel(_proc([]))
        with pytest.raises(TodoComposeError, match="空"):
            TodoComposeService.compose("   \n  ")

    def test_没配模型就不起进程(self, monkeypatch):
        """内核没配模型时会转成交互式追问，在服务端那是一个只能等超时的进程。"""

        def boom(_cmd):
            raise AssertionError("模型没配好的时候不该起进程")

        monkeypatch.setattr(TodoComposeService, "_run", staticmethod(boom))
        monkeypatch.setattr(
            "frago.server.services.hook_review_service.HookReviewService._resolve_profile",
            staticmethod(lambda: ("not_configured", None, None, "profile has no default_model")),
        )
        with pytest.raises(TodoComposeError, match="模型"):
            TodoComposeService.compose("一件事")

    def test_超时说成超时(self, kernel, monkeypatch):
        def slow(_cmd):
            raise subprocess.TimeoutExpired(cmd="frago-core", timeout=120)

        kernel(_proc([]))
        monkeypatch.setattr(TodoComposeService, "_run", staticmethod(slow))
        with pytest.raises(TodoComposeError, match="没结束"):
            TodoComposeService.compose("一件事")

    def test_agent非零退出时把原因带出来(self, kernel):
        kernel(
            _proc(
                [],
                returncode=1,
                stderr="frago-core: final: reached max rounds (8) without a final answer",
            )
        )
        with pytest.raises(TodoComposeError, match="max rounds"):
            TodoComposeService.compose("一件事")


class TestTheEndpoint:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRAGO_TODO_DIR", str(tmp_path / "todo"))
        from frago.server.app import create_app

        # 本机席位：事务是机主自己的账本，非本机调用先撞访问带。
        return TestClient(create_app(), client=("127.0.0.1", 50000))

    def test_建好之后四样都回给界面(self, client, monkeypatch):
        monkeypatch.setattr(
            TodoComposeService,
            "compose",
            staticmethod(
                lambda _d: {
                    "todo_id": "20260909-x",
                    "created": True,
                    "message": "建好了",
                    "command": ["frago", "todo", "add", "x"],
                }
            ),
        )
        body = client.post("/api/todos", json={"description": "一件事"}).json()
        assert body == {
            "todo_id": "20260909-x",
            "created": True,
            "message": "建好了",
            "command": ["frago", "todo", "add", "x"],
        }

    def test_建不成时原因原样带给人看(self, client, monkeypatch):
        """「HTTP 502」对着人说等于什么都没说，得让他看见是模型没配。"""

        def fail(_d):
            raise TodoComposeError("还没有可用的模型配置。去设置里配一个 profile")

        monkeypatch.setattr(TodoComposeService, "compose", staticmethod(fail))
        response = client.post("/api/todos", json={"description": "一件事"})
        assert response.status_code == 502
        assert "配一个 profile" in response.json()["detail"]
