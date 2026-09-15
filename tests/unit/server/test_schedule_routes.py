"""定时任务页的接口。

盯的是接口对界面的承诺：清单与调度器读到的是同一份、停用的任务不报「下次运行」、
启停和删除落到文件上、立即跑不改正常周期且执行记录上的时间是这一次的、新建时把
agent 的结果原样带回。全程用临时文件，不碰 ``~/.frago/schedules.json``。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from frago.server.services import schedule_executor as ex
from frago.server.services.schedule_compose_service import ScheduleComposeService
from frago.server.services.scheduler_service import SchedulerService
from frago.server.services.todo_compose_service import TodoComposeError


@pytest.fixture
def service(tmp_path, monkeypatch):
    """换一个指向临时文件的调度器单例——用例绝不能碰本机真实定时任务。"""
    svc = SchedulerService()
    svc._schedules_path = tmp_path / "schedules.json"
    monkeypatch.setattr(SchedulerService, "_instance", svc)
    return svc


@pytest.fixture
def client(service):
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def _command(service: SchedulerService, **kw) -> dict:
    return service.add_schedule(command="echo hi", interval_seconds=600, **kw)


class TestList:
    def test_顺序与字段(self, client, service):
        a = _command(service, name="甲")
        b = service.add_schedule(prompt="汇总昨天的消息", cron="0 8 * * *", name="乙")
        body = client.get("/api/schedules").json()
        assert [s["id"] for s in body["schedules"]] == [a["id"], b["id"]]
        first, second = body["schedules"]
        assert first["kind"] == "command"
        assert first["interval_seconds"] == 600
        assert second["kind"] == "prompt"
        assert second["cron"] == "0 8 * * *"
        assert second["next_run_at"] is not None
        assert body["scheduler_running"] is False

    def test_空清单(self, client):
        assert client.get("/api/schedules").json() == {"schedules": [], "scheduler_running": False}

    def test_停用的任务没有下次运行(self, client, service):
        s = _command(service)
        service.toggle_schedule(s["id"])
        row = client.get("/api/schedules").json()["schedules"][0]
        assert row["enabled"] is False
        assert row["next_run_at"] is None

    def test_老格式的配方任务也读得出配方名(self, client, service):
        service._schedules_path.write_text(
            '{"schedules": [{"id": "sch_old", "recipe_name": "r1", "interval_seconds": 60,'
            ' "enabled": true, "created_at": "2026-01-01T00:00:00"}]}',
            encoding="utf-8",
        )
        row = client.get("/api/schedules").json()["schedules"][0]
        assert row["kind"] == "recipe"
        assert row["recipe"] == "r1"


class TestWrites:
    def test_启停落到文件上(self, client, service):
        s = _command(service)
        assert client.post(f"/api/schedules/{s['id']}/toggle").json()["enabled"] is False
        assert service.list_schedules()[0]["enabled"] is False
        assert client.post(f"/api/schedules/{s['id']}/toggle").json()["enabled"] is True

    def test_删除(self, client, service):
        s = _command(service)
        assert client.delete(f"/api/schedules/{s['id']}").status_code == 200
        assert service.list_schedules() == []

    def test_不存在的编号回404(self, client):
        assert client.post("/api/schedules/sch_nope/toggle").status_code == 404
        assert client.delete("/api/schedules/sch_nope").status_code == 404
        assert client.post("/api/schedules/sch_nope/run").status_code == 404


class TestRunNow:
    def test_不改周期且记录的是这一次的时间(self, client, service, monkeypatch):
        s = _command(service)
        before = service.list_schedules()[0]["last_run_at"]

        async def fake_run(_schedule):
            return ex.RunOutcome(ok=True, kind="command", digest="d")

        monkeypatch.setattr(ex, "run_scheduled", fake_run)
        response = client.post(f"/api/schedules/{s['id']}/run")
        assert response.status_code == 202

        # 接口不等执行结束；给后台那一步留出跑完的时间。
        for _ in range(50):
            if service.list_schedules()[0]["history"]:
                break
            asyncio.run(asyncio.sleep(0.02))

        row = service.list_schedules()[0]
        assert row["last_run_at"] == before
        assert row["history"][-1]["status"] == "success"
        assert row["history"][-1]["manual"] is True
        assert row["history"][-1]["triggered_at"] == response.json()["triggered_at"]

    def test_上一次还没结束就拒绝(self, client, service):
        s = _command(service)
        service._active_schedule_ids.add(s["id"])
        assert client.post(f"/api/schedules/{s['id']}/run").status_code == 409

    def test_自然语言任务交给_CoreAgent_不看_PA_在不在(self, client, service, monkeypatch):
        """PA 没起来（这里压根没接）也照跑：执行者已经换成 CoreAgent 子进程。"""
        s = service.add_schedule(
            prompt="给事务分类", interval_seconds=60,
            instructions="todo-triage.md", allowed_tools=["Bash(frago todo:*)"],
            cwd="/tmp",
        )
        seen = {}

        def fake_prompt(prompt, timeout, instructions, allowed, disallowed, cwd):
            seen.update(prompt=prompt, instructions=instructions, allowed=allowed, cwd=cwd)
            return ex.RunOutcome(ok=True, kind="prompt", stdout="分好了", digest="d")

        monkeypatch.setattr(ex, "execute_prompt", fake_prompt)
        assert client.post(f"/api/schedules/{s['id']}/run").status_code == 202

        for _ in range(50):
            if service.list_schedules()[0]["history"]:
                break
            asyncio.run(asyncio.sleep(0.02))

        assert seen == {
            "prompt": "给事务分类", "instructions": "todo-triage.md",
            "allowed": ["Bash(frago todo:*)"], "cwd": "/tmp",
        }
        row = client.get("/api/schedules").json()["schedules"][0]
        assert row["history"][-1]["status"] == "success"
        assert row["instructions"] == "todo-triage.md"
        assert row["allowed_tools"] == ["Bash(frago todo:*)"]
        assert row["disallowed_tools"] == []


class TestCompose:
    def test_建好之后三样都回给界面(self, client, monkeypatch):
        monkeypatch.setattr(
            ScheduleComposeService,
            "compose",
            staticmethod(
                lambda _d: {
                    "schedule_id": "sch_12345678",
                    "message": "建好了",
                    "command": ["frago", "schedule", "add", "--command", "df -h /"],
                }
            ),
        )
        body = client.post("/api/schedules", json={"description": "每天看磁盘"}).json()
        assert body["schedule_id"] == "sch_12345678"
        assert body["command"][:3] == ["frago", "schedule", "add"]

    def test_建不成时原因原样带给人看(self, client, monkeypatch):
        def fail(_d):
            raise TodoComposeError("还没有可用的模型配置。去设置里配一个 profile")

        monkeypatch.setattr(ScheduleComposeService, "compose", staticmethod(fail))
        response = client.post("/api/schedules", json={"description": "一件事"})
        assert response.status_code == 502
        assert "配一个 profile" in response.json()["detail"]
