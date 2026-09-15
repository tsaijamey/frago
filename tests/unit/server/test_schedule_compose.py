"""界面上定时任务的「新建」：一句话交给 agent，由它去敲 `frago schedule add`。

不起真进程，喂的是内核一行一个 JSON 的输出。盯三件事：认得出建出的是哪一条、
带回界面的是 `schedule add` 那条命令而不是查重用的 list、一条没建时不假装成功。
"""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

import pytest

from frago.server.services.schedule_compose_service import ScheduleComposeService
from frago.server.services.todo_compose_service import TodoComposeError, TodoComposeService


def _proc(events: list[dict[str, Any]], *, returncode: int = 0, stderr: str = ""):
    stdout = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    return subprocess.CompletedProcess(
        args=["frago-core"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _tool(args: list[str]) -> dict[str, Any]:
    return {"type": "tool", "tool_name": "Bash", "input": {"command": shlex.join(["frago", *args])}}


def _result(output: str) -> dict[str, Any]:
    return {"type": "result", "output": output, "denied": False}


@pytest.fixture
def kernel(monkeypatch):
    monkeypatch.setattr(TodoComposeService, "_require_model", staticmethod(lambda: None))
    monkeypatch.setattr(
        TodoComposeService, "_binary_path", staticmethod(lambda: "/nonexistent/frago-core")
    )

    def install(proc):
        monkeypatch.setattr(ScheduleComposeService, "_run", staticmethod(lambda _cmd: proc))

    return install


def test_认出新建的那条和它的命令(kernel):
    add = ["schedule", "add", "--command", "df -h /", "--cron", "0 9 * * *", "--notify-on", "never"]
    kernel(
        _proc(
            [
                _tool(["schedule", "list"]),
                _result("No schedules configured."),
                _tool(add),
                _result("Schedule created: sch_1a2b3c4d\n  Name: 看磁盘"),
                {"type": "done", "final_text": "建好了 sch_1a2b3c4d"},
            ]
        )
    )
    result = ScheduleComposeService.compose("每天九点看磁盘")
    assert result["schedule_id"] == "sch_1a2b3c4d"
    assert result["command"] == ["frago", *add]
    assert result["message"] == "建好了 sch_1a2b3c4d"


def test_一条没建时说出来(kernel):
    kernel(
        _proc(
            [
                _tool(["schedule", "list"]),
                _result("sch_old  ✓  command  看磁盘"),
                {"type": "done", "final_text": "已经有 sch_old 了，没再建"},
            ]
        )
    )
    result = ScheduleComposeService.compose("每天九点看磁盘")
    assert result["schedule_id"] is None
    assert result["command"] is None
    assert "sch_old" in result["message"]


def test_命令报错时不算建成(kernel):
    """`schedule add` 校验没过（比如通知落点不认识），输出里没有 created 那行。"""
    kernel(
        _proc(
            [
                _tool(["schedule", "add", "--prompt", "x", "--every", "1h", "--notify-to", "slack"]),
                _result("Error: 通知落点 'slack' 不认识。"),
                {"type": "done", "final_text": "没建成"},
            ]
        )
    )
    assert ScheduleComposeService.compose("每小时推 slack")["schedule_id"] is None


def test_描述是空的当场拒绝(kernel):
    kernel(_proc([]))
    with pytest.raises(TodoComposeError, match="空"):
        ScheduleComposeService.compose("  ")


def test_agent非零退出时把原因带出来(kernel):
    kernel(_proc([], returncode=1, stderr="frago-core: reached max rounds (10)"))
    with pytest.raises(TodoComposeError, match="max rounds"):
        ScheduleComposeService.compose("一件事")
