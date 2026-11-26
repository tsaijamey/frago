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

    def test_自然语言任务交给_CoreAgent_不看_PA_在不在(
        self, client, service, monkeypatch, tmp_path
    ):
        """PA 没起来（这里压根没接）也照跑：执行者已经换成 CoreAgent 子进程。"""
        from frago.server.services import schedule_resume as sr

        # 续跑包与统一决策收件箱都不该读到这一台机器自己的 ~/.frago 去。
        monkeypatch.setattr(sr, "ROOT", tmp_path / "resume")
        monkeypatch.setenv("FRAGO_DECISION_INBOX_DIR", str(tmp_path / "decision-inbox"))
        s = service.add_schedule(
            prompt="给事务分类", interval_seconds=60,
            instructions="todo-triage.md", allowed_tools=["Bash(frago todo:*)"],
            cwd="/tmp", name="事务分类",
        )
        seen = {}

        def fake_prompt(
            prompt, timeout, instructions, allowed, disallowed, cwd, title=None,
            *, resume=None, pending=None, schedule_id=None, schedule_name=None,
        ):
            seen.update(
                prompt=prompt, instructions=instructions, allowed=allowed, cwd=cwd, title=title,
                schedule_id=schedule_id, schedule_name=schedule_name,
            )
            assert resume is None, "这一趟没有上一趟留下的续跑包"
            assert pending is None, "这一趟也没有挂着没人答的卡片"
            return ex.RunOutcome(ok=True, kind="prompt", stdout="分好了", digest="d")

        monkeypatch.setattr(ex, "execute_prompt", fake_prompt)
        assert client.post(f"/api/schedules/{s['id']}/run").status_code == 202

        for _ in range(50):
            if service.list_schedules()[0]["history"]:
                break
            asyncio.run(asyncio.sleep(0.02))

        # 名字带着这条任务自己的名字下去：会话页左栏摆的是它，不是开口第一句那一整段。
        assert seen == {
            "prompt": "给事务分类", "instructions": "todo-triage.md",
            "allowed": ["Bash(frago todo:*)"], "cwd": "/tmp", "title": "定时任务：事务分类",
            "schedule_id": s["id"], "schedule_name": "事务分类",
        }
        row = client.get("/api/schedules").json()["schedules"][0]
        assert row["history"][-1]["status"] == "success"
        assert row["instructions"] == "todo-triage.md"
        assert row["allowed_tools"] == ["Bash(frago todo:*)"]
        assert row["disallowed_tools"] == []
        assert "last_session_id" in row
        assert "last_run" in row


class TestScheduleSessionLinkRoutes:
    def test_列表接口正确透传_last_session_id_和_last_run(self, client, service):
        s = service.add_schedule(command="echo 'hi'", interval_seconds=60, name="命令任务")
        service._load()
        for item in service._schedules:
            if item["id"] == s["id"]:
                item["last_session_id"] = "core_test998877665544332211"
                item["last_run"] = {
                    "session_id": "core_test998877665544332211",
                    "status": "success",
                    "exit_code": 0,
                }
        service._save()
        res = client.get("/api/schedules").json()
        target = next(it for it in res["schedules"] if it["id"] == s["id"])
        assert target["last_session_id"] == "core_test998877665544332211"
        assert target["last_run"]["session_id"] == "core_test998877665544332211"


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


class TestStructuredScheduleEndpoints:
    @pytest.fixture
    def isolated_employees(self, tmp_path, monkeypatch):
        from frago.employee.store import EmployeePostRecord, save_post

        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))
        save_post(
            EmployeePostRecord(
                member_post_id="demo-emp",
                title="示例分析师",
                description="负责例行分析",
                agent_kernel="coreagent",
            )
        )
        return tmp_path

    def test_结构化创建读取编辑员工定时任务与预览(self, client, isolated_employees):
        # 1) 员工不存在时拒绝创建
        bad_resp = client.post(
            "/api/schedules/create",
            json={
                "name": "坏任务",
                "kind": "employee",
                "employee_id": "nonexistent-emp",
                "prompt": "干活",
                "cron": "0 9 * * *",
            },
        )
        assert bad_resp.status_code == 422
        assert "nonexistent-emp" in bad_resp.json()["detail"]

        # 2) 合法创建
        create_resp = client.post(
            "/api/schedules/create",
            json={
                "name": "早盘巡检",
                "kind": "employee",
                "employee_id": "demo-emp",
                "prompt": "输出今日要点",
                "cron": "0 9 * * 1-5",
                "session_title_template": "[{date} {weekday}] {employee} · {schedule_name} #{seq}",
            },
        )
        assert create_resp.status_code == 200
        created = create_resp.json()
        sid = created["id"]
        assert created["kind"] == "employee"
        assert created["employee_id"] == "demo-emp"
        assert created["employee_title"] == "示例分析师"
        assert created["employee_missing"] is False
        assert created["session_title_template"] == "[{date} {weekday}] {employee} · {schedule_name} #{seq}"

        # 3) 详情接口可读且预览接口返回 3 条未来运行记录
        detail_resp = client.get(f"/api/schedules/{sid}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == sid

        prev_resp = client.post(
            "/api/schedules/preview",
            json={
                "name": "早盘巡检",
                "kind": "employee",
                "employee_id": "demo-emp",
                "cron": "0 9 * * 1-5",
                "session_title_template": "[{date} {weekday}] {employee} · {schedule_name} #{seq}",
                "run_count": 2,
                "count": 3,
            },
        )
        assert prev_resp.status_code == 200
        runs = prev_resp.json()["runs"]
        assert len(runs) == 3
        assert runs[0]["seq"] == 3
        assert "示例分析师" in runs[0]["session_title"]
        assert "#3" in runs[0]["session_title"]

        # 4) 编辑更新保持 ID 不变
        edit_resp = client.put(
            f"/api/schedules/{sid}",
            json={
                "name": "早盘巡检修订版",
                "kind": "employee",
                "employee_id": "demo-emp",
                "prompt": "补充风控提示",
                "interval_seconds": 1800,
            },
        )
        assert edit_resp.status_code == 200
        edited = edit_resp.json()
        assert edited["id"] == sid
        assert edited["name"] == "早盘巡检修订版"
        assert edited["interval_seconds"] == 1800
        assert edited["cron"] is None

    def test_已绑定员工被删除后列表与详情显式标记_employee_missing(self, client, service, isolated_employees):
        from frago.employee.store import delete_post

        s = service.add_schedule(
            name="已删员工任务",
            employee_id="demo-emp",
            prompt="跑一次",
            interval_seconds=600,
        )
        delete_post("demo-emp")
        row = client.get(f"/api/schedules/{s['id']}").json()
        assert row["kind"] == "employee"
        assert row["employee_id"] == "demo-emp"
        assert row["employee_missing"] is True

