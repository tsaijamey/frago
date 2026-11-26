"""schedule_executor 的通知回路与原生执行。

这里验的几乎全是「看输出看不出来」的事：任务照样在跑、日志照样有记录，
但该说话时没说、或者不该说时天天说。后者比前者更隐蔽——它不会被报障，
只会让人在两周内学会无视这个通知源。
"""

from datetime import datetime, timedelta

import pytest

from frago.server.services import schedule_executor as ex


def sched(**kw):
    base = {
        "id": "sch_test",
        "name": "测试任务",
        "kind": "recipe",
        "notify": {"on": "change", "to": "desktop", "context": {}},
        "created_at": datetime(2026, 8, 1, 9, 0, 0).isoformat(),
    }
    base.update(kw)
    return base


def ok(**kw):
    d = {"ok": True, "kind": "recipe", "exit_code": 0, "digest": "d1"}
    d.update(kw)
    return ex.RunOutcome(**d)


def bad(**kw):
    d = {"ok": False, "kind": "recipe", "exit_code": 1, "error": "炸了"}
    d.update(kw)
    return ex.RunOutcome(**d)


# --- 沉默必须有意义 ---------------------------------------------------------

class TestChangeIsTheDefault:
    def test_配方没报_notify_就不说话(self):
        d = ex.decide_notification(sched(), ok(notify_text=None), {})
        assert d.should is False

    def test_配方报了_notify_就说话且原话带上(self):
        d = ex.decide_notification(sched(), ok(notify_text="新增 3 位 star"), {})
        assert d.should is True
        assert "新增 3 位 star" in d.text

    def test_always_即使无事也说话(self):
        s = sched(notify={"on": "always", "to": "desktop"})
        assert ex.decide_notification(s, ok(notify_text=None), {}).should is True

    def test_never_连失败都不说(self):
        s = sched(notify={"on": "never", "to": "desktop"})
        assert ex.decide_notification(s, bad(), {}).should is False


class TestCommandChangeDetection:
    def test_首轮只记基线不打扰(self):
        s = sched(kind="command")
        d = ex.decide_notification(s, ok(kind="command", digest="a"), {})
        assert d.should is False
        assert "基线" in d.reason

    def test_输出没变就不说话(self):
        s = sched(kind="command")
        d = ex.decide_notification(s, ok(kind="command", digest="a"), {"last_digest": "a"})
        assert d.should is False

    def test_输出变了才说话(self):
        s = sched(kind="command")
        d = ex.decide_notification(s, ok(kind="command", digest="b", stdout="新内容"),
                                   {"last_digest": "a"})
        assert d.should is True


# --- 失败必须说话，但不能刷屏 -----------------------------------------------

class TestFailureEscalation:
    def test_首次失败一定说(self):
        d = ex.decide_notification(sched(), bad(), {"consecutive_failures": 0})
        assert d.should is True
        assert "失败" in d.text

    def test_第三次失败收敛掉(self):
        d = ex.decide_notification(sched(), bad(), {"consecutive_failures": 2})
        assert d.should is False

    def test_第五次失败再喊一声(self):
        d = ex.decide_notification(sched(), bad(), {"consecutive_failures": 4})
        assert d.should is True
        assert "连续失败 5 次" in d.text

    def test_失败时_on_change_也照样说话(self):
        """任务自己没机会报 notify——它根本没跑完。这时沉默等于把故障藏起来。"""
        s = sched(notify={"on": "change", "to": "desktop"})
        assert ex.decide_notification(s, bad(), {}).should is True

    def test_恢复正常要说一声(self):
        d = ex.decide_notification(sched(), ok(notify_text=None), {"consecutive_failures": 3})
        assert d.should is True
        assert "恢复" in d.text

    def test_没失败过就不会报恢复(self):
        d = ex.decide_notification(sched(), ok(notify_text=None), {"consecutive_failures": 0})
        assert d.should is False


# --- 指纹不能被时间戳污染 ---------------------------------------------------

class TestDigestStability:
    def test_只有时间变了不算变化(self):
        a = ex._stable_for_digest(
            {"total": 59, "generated_at": "2026-08-21T09:00:00Z", "elapsed_sec": 2.4}, "")
        b = ex._stable_for_digest(
            {"total": 59, "generated_at": "2026-08-22T21:00:00Z", "elapsed_sec": 9.9}, "")
        assert a == b, "时间戳进了指纹，会让每一轮都被判成有变化"

    def test_实质变了就是变了(self):
        a = ex._stable_for_digest({"total": 59, "generated_at": "x"}, "")
        b = ex._stable_for_digest({"total": 62, "generated_at": "x"}, "")
        assert a != b


# --- 逾期未跑 ---------------------------------------------------------------

class TestStaleness:
    def test_按时跑的不算逾期(self):
        now = datetime(2026, 8, 22, 10, 0, 0)
        s = sched(last_success_at=(now - timedelta(hours=2)).isoformat())
        assert ex.is_stale(s, now, 12 * 3600) is None

    def test_超过三个周期算逾期(self):
        now = datetime(2026, 8, 22, 10, 0, 0)
        s = sched(last_success_at=(now - timedelta(days=3)).isoformat())
        overdue = ex.is_stale(s, now, 12 * 3600)
        assert overdue is not None and overdue.total_seconds() > 0

    def test_从来没成功过就以创建时间起算(self):
        now = datetime(2026, 8, 22, 10, 0, 0)
        s = sched(created_at=datetime(2026, 8, 1).isoformat(), last_success_at=None)
        assert ex.is_stale(s, now, 3600) is not None

    def test_没有周期就不判逾期(self):
        assert ex.is_stale(sched(), datetime.now(), None) is None

    def test_逾期通知里说得出是哪个任务(self):
        text = ex.staleness_text(sched(name="star 名单"), timedelta(hours=30))
        assert "star 名单" in text
        assert "30 小时" in text


# --- 命令执行 ---------------------------------------------------------------

class TestCommandExecution:
    def test_成功的命令拿得到输出(self):
        r = ex.execute_command("echo 你好", timeout=30)
        assert r.ok is True
        assert r.stdout == "你好"
        assert r.exit_code == 0

    def test_失败的命令带着错误信息回来(self):
        r = ex.execute_command("echo 出事了 >&2; exit 3", timeout=30)
        assert r.ok is False
        assert r.exit_code == 3
        assert "出事了" in r.error

    def test_超时被当成失败而不是挂死(self):
        r = ex.execute_command("sleep 5", timeout=1)
        assert r.ok is False
        assert "超时" in r.error

    def test_相同输出指纹相同(self):
        a = ex.execute_command("echo same", timeout=30)
        b = ex.execute_command("echo same", timeout=30)
        assert a.digest == b.digest

    def test_execute_command_injects_schedule_unattended_env(self):
        r = ex.execute_command(
            "python3 -c 'import os; print(os.environ.get(\"FRAGO_SESSION_ORIGIN\"), os.environ.get(\"FRAGO_UNATTENDED\"))'",
            timeout=30,
        )
        assert r.ok is True
        assert r.stdout == "schedule 1"


# --- 投递落点 ---------------------------------------------------------------

class TestDelivery:
    def test_落点不认识时说清楚有哪些可选(self):
        s = sched(notify={"on": "change", "to": "不存在的落点", "context": {}})
        r = ex.deliver(s, "文本")
        assert r["status"] == "error"
        assert "不存在的落点" in r["error"]

    def test_pa_落点在队列不可用时明确报错(self):
        s = sched(notify={"on": "change", "to": "pa", "context": {}})
        r = ex.deliver(s, "文本", pa_enqueue=None)
        assert r["status"] == "error"

    def test_pa_落点可用时交回给调用方入队(self):
        s = sched(notify={"on": "change", "to": "pa", "context": {}})
        r = ex.deliver(s, "文本", pa_enqueue=lambda *_: None)
        assert r["status"] == "queued"


# --- 结果解析 ---------------------------------------------------------------

class TestPayloadParsing:
    @pytest.mark.parametrize("field", ["notify", "summary", "notify_text"])
    def test_三种字段名都认(self, field):
        assert ex._extract_notify_field({field: "有事"}) == "有事"

    def test_空字符串不算有事(self):
        assert ex._extract_notify_field({"notify": "   "}) is None

    def test_不是字典就没有通知文本(self):
        assert ex._extract_notify_field("一串文本") is None


# --- 自然语言任务交给 CoreAgent ----------------------------------------------


class TestPromptViaCoreAgent:
    """不起真进程：替掉子进程那一步，喂 CoreAgent 结束时交的那一行结论。"""

    @pytest.fixture
    def core(self, tmp_path, monkeypatch):
        from frago.session import service as session_service_mod
        from frago.session import store as session_store_mod
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyStore

        binary = tmp_path / "frago-core"
        binary.write_text("")
        monkeypatch.setattr("frago.init.hook_binary.get_hook_deploy_dir", lambda: tmp_path)
        monkeypatch.setattr("frago.init.hook_binary.get_binary_name", lambda: "frago-core")

        store = SessionOntologyStore(
            tmp_path / "session-ontology-store.json",
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store)
        monkeypatch.setattr(session_store_mod, "_DEFAULT_SESSION_STORE", store)
        monkeypatch.setattr(session_service_mod, "_DEFAULT_SESSION_SERVICE", svc)
        monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: svc)

        calls = []
        envs = []

        def install(stdout="", returncode=0, stderr=""):
            import subprocess

            def fake_run(cmd, **kw):
                calls.append(cmd)
                envs.append(kw.get("env") or {})
                return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

            monkeypatch.setattr(ex.subprocess, "run", fake_run)

        install.calls = calls
        install.envs = envs
        install.store = store
        install.workdir = tmp_path
        return install

    def test_参数照任务带过去(self, core):
        core('{"type":"final","ok":true,"text":"分好了"}\n')
        ex.execute_prompt(
            "给事务分类", 900, "todo-triage.md",
            ["Read", "Bash(frago todo:*)"], ["Bash(rm:*)"], str(core.workdir),
        )
        cmd = core.calls[0]
        assert cmd[1:5] == ["--mode", "agent", "--output-format", "json"]
        assert cmd[cmd.index("--prompt") + 1] == "给事务分类"
        assert cmd[cmd.index("--instructions") + 1] == "todo-triage.md"
        assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "--allowed-tools"] == [
            "Read", "Bash(frago todo:*)",
        ]
        assert cmd[cmd.index("--disallowed-tools") + 1] == "Bash(rm:*)"
        assert cmd[cmd.index("--cwd") + 1] == str(core.workdir)
        assert cmd[cmd.index("--timeout") + 1] == "900"

    def test_没给工作目录就在家目录干活(self, core):
        from pathlib import Path

        core('{"type":"final","ok":true,"text":"x"}\n')
        ex.execute_prompt("x", 60)
        cmd = core.calls[0]
        assert cmd[cmd.index("--cwd") + 1] == str(Path.home())

    def test_办完了算成功_答案进输出(self, core):
        core('{"type":"final","ok":true,"text":"分好了 87 件"}\n')
        out = ex.execute_prompt("x", 60)
        assert out.ok and out.kind == "prompt" and out.stdout == "分好了 87 件"

    def test_没办完时原因带出来(self, core):
        core('{"type":"final","ok":false,"text":"","error_kind":"max_rounds","error":"轮数到顶"}\n', returncode=1)
        out = ex.execute_prompt("x", 60)
        assert not out.ok and "轮数到顶" in out.error

    def test_报了成功但答案为空_算没办完(self, core):
        core('{"type":"final","ok":true,"text":"  "}\n')
        out = ex.execute_prompt("x", 60)
        assert not out.ok and "答案是空的" in out.error

    def test_execute_prompt_injects_unattended_env_and_registers_schedule_origin(self, core):
        core('{"type":"final","ok":true,"text":"done"}\n')
        out = ex.execute_prompt("定时清理", 60, title="事务清理")
        assert out.ok is True
        env = core.envs[0]
        assert env["FRAGO_SESSION_ORIGIN"] == "schedule"
        assert env["FRAGO_UNATTENDED"] == "1"
        assert env["FRAGO_STOP_CHECK"] == "off"
        assert env["FRAGO_REVIEW"] == "off"
        records = core.store.list_all()
        assert len(records) == 1
        assert records[0].origin == "schedule"
        assert records[0].is_worker is False
        assert records[0].lifecycle_state == "completed"

    def test_execute_prompt_failure_marks_schedule_ontology_error(self, core):
        core('{"type":"final","ok":false,"text":"","error_kind":"max_rounds","error":"boom"}\n', returncode=1)
        out = ex.execute_prompt("定时失败", 60, title="失败探针")
        assert out.ok is False
        records = core.store.list_all()
        assert len(records) == 1
        assert records[0].origin == "schedule"
        assert records[0].lifecycle_state == "error"

    def test_空答案被判失败时原因带出来(self, core):
        core('{"type":"final","ok":false,"text":"","error_kind":"empty_answer","error":"模型这一轮既没有文字也没有工具调用"}\n', returncode=1)
        out = ex.execute_prompt("x", 60)
        assert not out.ok and "既没有文字" in out.error

    def test_一行结论都没交就算失败_不假装成功(self, core):
        core("not json\n", returncode=2, stderr="frago-core: 连接解析失败")
        out = ex.execute_prompt("x", 60)
        assert not out.ok and "连接解析失败" in out.error


class TestCommandSessionCapture:
    def test_从环境变量回传文件捕获会话编号(self):
        # 模拟命令往 FRAGO_SCHEDULE_SESSION_FILE 写 session_id
        cmd = 'echo "core_test123456789012345678901234" > "$FRAGO_SCHEDULE_SESSION_FILE"'
        out = ex.execute_command(cmd, 10)
        assert out.ok
        assert out.session_id == "core_test123456789012345678901234"

    def test_从标准输出正则提取会话编号(self):
        cmd = 'echo "[ok] frago-developer (session=core_abc123456789012345678901234): 任务完成"'
        out = ex.execute_command(cmd, 10)
        assert out.ok
        assert out.session_id == "core_abc123456789012345678901234"

    def test_配方结果透传会话编号(self, monkeypatch):
        from frago.recipes import runner as r_mod

        class DummyRunner:
            def run(self, *args, **kwargs):
                return {"success": True, "session_id": "ses_dummy_recipe_9876"}

        monkeypatch.setattr(r_mod, "RecipeRunner", DummyRunner)
        out = ex.execute_recipe("dummy", {}, 10)
        assert out.ok
        assert out.session_id == "ses_dummy_recipe_9876"


class TestSessionTitleTemplate:
    def test_员工默认模板包含日期星期员工名与任务名(self):
        s = {
            "id": "sch_emp_1",
            "name": "盘中简报",
            "kind": "employee",
            "employee_id": "analyst",
        }
        # 2026-11-04 是周三
        title = ex.render_session_title(
            s,
            triggered_at=datetime(2026, 11, 4, 9, 30, 0),
            seq=3,
            employee_title="投研助手",
        )
        assert title == "[11-04 周三] 投研助手 · 盘中简报"

    def test_自定义模板支持全部占位符含序号(self):
        s = {
            "id": "sch_emp_2",
            "name": "盘后复盘",
            "kind": "employee",
            "employee_id": "analyst",
            "session_title_template": "[{date} {weekday}] {employee} · {schedule_name} #{seq}",
        }
        title = ex.render_session_title(
            s,
            triggered_at=datetime(2026, 11, 6, 15, 5, 0),
            seq=31,
            employee_title="金融专家",
        )
        assert title == "[11-06 周五] 金融专家 · 盘后复盘 #31"

    def test_非员工默认保持历史定时任务前缀(self):
        s = {"id": "sch_p", "name": "事务分类", "kind": "prompt"}
        assert ex.render_session_title(s, triggered_at=datetime(2026, 11, 6, 9, 0, 0)) == "定时任务：事务分类"


class TestEmployeeScheduleExecution:
    @pytest.fixture
    def isolated_emp(self, tmp_path, monkeypatch):
        from frago.employee.store import EmployeePostRecord, save_post
        from frago.session import service as session_service_mod
        from frago.session import store as session_store_mod
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyStore

        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))
        emp_cwd = tmp_path / "emp-workspace"
        emp_cwd.mkdir(parents=True, exist_ok=True)
        rec = EmployeePostRecord(
            member_post_id="demo-emp",
            title="示例巡检专员",
            description="负责例行检查与汇总",
            agent_kernel="coreagent",
            cwd=str(emp_cwd),
            skills=["how-to-add-skill"],
        )
        save_post(rec)

        store = SessionOntologyStore(
            tmp_path / "session-ontology-store.json",
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store)
        monkeypatch.setattr(session_store_mod, "_DEFAULT_SESSION_STORE", store)
        monkeypatch.setattr(session_service_mod, "_DEFAULT_SESSION_SERVICE", svc)
        monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: svc)

        dispatch_root = tmp_path / "dispatches"
        dispatch_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("frago.session.async_dispatch.dispatch_store_dir", lambda: dispatch_root)

        return {"record": rec, "store": store, "svc": svc, "cwd": emp_cwd, "tmp_path": tmp_path}

    def test_缺失或已删除员工返回结构化失败提示且不崩溃(self, isolated_emp):
        s = {
            "id": "sch_missing",
            "name": "失踪员工任务",
            "kind": "employee",
            "employee_id": "deleted-ghost",
            "prompt": "跑一次",
        }
        out = ex.execute_employee(s, timeout=30, triggered_at=datetime(2026, 11, 4, 9, 0, 0))
        assert out.ok is False
        assert out.kind == "employee"
        assert out.payload["error_code"] == "EMPLOYEE_NOT_FOUND"
        assert out.payload["employee_id"] == "deleted-ghost"
        assert "deleted-ghost" in out.error

    def test_原生员工调度注入无人值守环境并渲染动态标题(self, isolated_emp, monkeypatch):
        from types import SimpleNamespace

        from frago.agent_driver import driver as driver_mod
        from frago.agent_driver import kernel_backend as kb_mod

        monkeypatch.setattr(driver_mod, "runs_on_kernel", lambda k: k == "coreagent")
        monkeypatch.setattr(kb_mod, "new_session_id", lambda: "core_emp_sched_native_01")
        captured: dict[str, object] = {}

        def fake_run_turn(prompt, **kwargs):
            captured["prompt"] = prompt
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = dict(kwargs.get("env") or {})
            return SimpleNamespace(status="completed", text="巡检完毕：一切正常")

        monkeypatch.setattr(kb_mod, "run_turn", fake_run_turn)

        s = {
            "id": "sch_emp_ok",
            "name": "每日巡检",
            "kind": "employee",
            "employee_id": "demo-emp",
            "prompt": "检查业务底账",
            "session_title_template": "[{date} {weekday}] {employee} · {schedule_name} #{seq}",
        }
        out = ex.execute_employee(
            s,
            timeout=60,
            triggered_at=datetime(2026, 11, 4, 9, 0, 0),
            seq=5,
        )
        assert out.ok is True
        assert out.kind == "employee"
        assert out.session_id == "core_emp_sched_native_01"
        assert out.session_title == "[11-04 周三] 示例巡检专员 · 每日巡检 #5"
        assert "巡检完毕" in out.stdout
        assert captured["cwd"] == str(isolated_emp["cwd"])
        env = captured["env"]
        assert env["FRAGO_SESSION_ORIGIN"] == "schedule"
        assert env["FRAGO_UNATTENDED"] == "1"
        assert env["FRAGO_STOP_CHECK"] == "off"
        assert env["FRAGO_REVIEW"] == "off"
        assert env["FRAGO_AGENT_ROLE"] == "employee"
        assert env["FRAGO_EMPLOYEE_ID"] == "demo-emp"
        assert "<frago-employee" in str(captured["prompt"])

        rec = isolated_emp["store"].get("core_emp_sched_native_01")
        assert rec is not None
        assert rec.origin == "schedule"
        assert rec.employee_id == "demo-emp"
        assert rec.lifecycle_state == "completed"

    def test_多跳等待屏障等待未结子派发收口后才结束(self, isolated_emp, monkeypatch):
        import threading
        import time as time_mod
        from types import SimpleNamespace

        from frago.agent_driver import driver as driver_mod
        from frago.agent_driver import kernel_backend as kb_mod
        from frago.session import async_dispatch

        monkeypatch.setattr(driver_mod, "runs_on_kernel", lambda k: k == "coreagent")
        monkeypatch.setattr(kb_mod, "new_session_id", lambda: "core_emp_barrier_01")
        monkeypatch.setattr(async_dispatch, "_extract_latest_assistant_output", lambda _sid: "")

        def fake_run_turn(_prompt, **_kwargs):
            job = async_dispatch.AsyncDispatchJob(
                job_id="job_child_barrier_01",
                kind="worker",
                mode="new",
                caller_session_id="core_emp_barrier_01",
                caller_employee_id="demo-emp",
                caller_cwd=str(isolated_emp["cwd"]),
                target_session_id="core_child_worker_01",
                target_name="子任务",
                employee_id=None,
                agent="coreagent",
                cwd=str(isolated_emp["cwd"]),
                prompt="子任务",
                task_summary="子任务",
                status="running",
            )
            async_dispatch.save_dispatch_job(job)

            def settle_later():
                time_mod.sleep(0.25)
                job.status = "completed"
                job.delivery_state = "delivered"
                job.output = "子 Worker 已完成数据汇总"
                async_dispatch.save_dispatch_job(job)

            threading.Thread(target=settle_later, daemon=True).start()
            return SimpleNamespace(status="completed", text="已派发子 worker 处理")

        monkeypatch.setattr(kb_mod, "run_turn", fake_run_turn)

        s = {
            "id": "sch_emp_barrier",
            "name": "带子派发的任务",
            "kind": "employee",
            "employee_id": "demo-emp",
            "prompt": "派发子任务并汇报",
        }
        out = ex.execute_employee(s, timeout=5, triggered_at=datetime(2026, 11, 4, 10, 0, 0))
        assert out.ok is True
        assert "子 Worker 已完成数据汇总" in out.stdout

    def test_超时强杀连带作废未结子派发并终止子会话(self, isolated_emp, monkeypatch):
        from types import SimpleNamespace

        from frago.agent_driver import driver as driver_mod
        from frago.agent_driver import kernel_backend as kb_mod
        from frago.server.services import coreagent_runner, tmux_sessions_service
        from frago.session import async_dispatch

        monkeypatch.setattr(driver_mod, "runs_on_kernel", lambda k: k == "coreagent")
        monkeypatch.setattr(kb_mod, "new_session_id", lambda: "core_emp_timeout_01")

        stopped_sids: list[str] = []
        closed_tmux: list[str] = []
        monkeypatch.setattr(coreagent_runner, "stop", lambda sid, by="": stopped_sids.append(sid))
        monkeypatch.setattr(tmux_sessions_service, "close_sessions", lambda names: closed_tmux.extend(names))

        def fake_run_turn(_prompt, **_kwargs):
            job = async_dispatch.AsyncDispatchJob(
                job_id="job_child_hang_01",
                kind="worker",
                mode="new",
                caller_session_id="core_emp_timeout_01",
                caller_employee_id="demo-emp",
                caller_cwd=str(isolated_emp["cwd"]),
                target_session_id="core_child_hang_01",
                target_name="卡住子任务",
                employee_id=None,
                agent="coreagent",
                cwd=str(isolated_emp["cwd"]),
                prompt="永不结束的子任务",
                task_summary="永不结束的子任务",
                status="running",
            )
            async_dispatch.save_dispatch_job(job)
            return SimpleNamespace(status="completed", text="首轮派发完成")

        monkeypatch.setattr(kb_mod, "run_turn", fake_run_turn)

        s = {
            "id": "sch_emp_timeout",
            "name": "超时任务",
            "kind": "employee",
            "employee_id": "demo-emp",
            "prompt": "跑一个会卡住的子派发",
        }
        out = ex.execute_employee(s, timeout=1, triggered_at=datetime(2026, 11, 4, 11, 0, 0))
        assert out.ok is False
        assert out.payload.get("error_code") == "SCHEDULE_TIMEOUT"
        assert "core_emp_timeout_01" in stopped_sids
        assert "core_child_hang_01" in stopped_sids
        assert "frago-agent-core_emp_timeout_01" in closed_tmux
        assert "frago-agent-core_child_hang_01" in closed_tmux

        jobs = async_dispatch.list_dispatch_jobs(caller_session_id="core_emp_timeout_01", active_only=False)
        assert len(jobs) == 1
        assert jobs[0].status == "superseded"
        assert isolated_emp["store"].get("core_emp_timeout_01").lifecycle_state == "error"


class TestScheduleDecisionInboxLoop:
    """定时任务环境变量注入 + employee/prompt 统一决策收件箱闭环回归测试。"""

    def test_prompt_schedule_injects_schedule_env_and_consumes_resolution(
        self, tmp_path, monkeypatch
    ):
        import asyncio
        import json
        import subprocess

        from click.testing import CliRunner

        from frago.cli.propose_commands import propose_group
        from frago.decision_inbox import get_decision_inbox_service
        from frago.server.services import schedule_resume as sr
        from frago.session import service as session_service_mod
        from frago.session import store as session_store_mod
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyStore

        monkeypatch.setattr(sr, "ROOT", tmp_path / "resume")
        inbox_dir = tmp_path / "decision-inbox"
        monkeypatch.setenv("FRAGO_DECISION_INBOX_DIR", str(inbox_dir))

        binary = tmp_path / "frago-core"
        binary.write_text("")
        monkeypatch.setattr("frago.init.hook_binary.get_hook_deploy_dir", lambda: tmp_path)
        monkeypatch.setattr("frago.init.hook_binary.get_binary_name", lambda: "frago-core")

        store = SessionOntologyStore(
            tmp_path / "session-ontology-store.json",
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store)
        monkeypatch.setattr(session_store_mod, "_DEFAULT_SESSION_STORE", store)
        monkeypatch.setattr(session_service_mod, "_DEFAULT_SESSION_SERVICE", svc)
        monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: svc)

        seen_prompts: list[str] = []
        seen_envs: list[dict[str, str]] = []

        def fake_run(cmd, **kw):
            seen_prompts.append(cmd[cmd.index("--prompt") + 1])
            seen_envs.append(dict(kw.get("env") or {}))
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"type":"final","ok":true,"text":"done"}\n', stderr=""
            )

        monkeypatch.setattr(ex.subprocess, "run", fake_run)

        broadcasts: list[str] = []

        async def fake_broadcast(*_args, action="refresh", **_kwargs):
            broadcasts.append(action)

        monkeypatch.setattr(
            "frago.server.websocket.broadcast_decision_inbox_update", fake_broadcast
        )

        schedule_obj = {
            "id": "sch_prompt_loop",
            "name": "夜间磁盘巡检",
            "kind": "prompt",
            "prompt": "检查并清理过期构建缓存",
            "cwd": str(tmp_path),
        }

        # 第 1 轮触发：子进程拿到 FRAGO_SCHEDULE_ID / FRAGO_SCHEDULE_NAME
        out1 = asyncio.run(ex.run_scheduled(schedule_obj))
        assert out1.ok is True
        env1 = seen_envs[0]
        assert env1["FRAGO_SCHEDULE_ID"] == "sch_prompt_loop"
        assert env1["FRAGO_SCHEDULE_NAME"] == "夜间磁盘巡检"

        # 模拟定时任务子进程内调用 `frago app propose`（未显式传 --schedule-id）
        for k in ("FRAGO_SCHEDULE_ID", "FRAGO_SCHEDULE_NAME", "FRAGO_SESSION_ORIGIN", "FRAGO_UNATTENDED"):
            monkeypatch.setenv(k, env1[k])
        cli_res = CliRunner().invoke(
            propose_group,
            ["binary", "-q", "是否删除 12GB 过期缓存？", "--dedup-key", "cache:gc:12gb"],
        )
        assert cli_res.exit_code == 0, cli_res.output
        proposal_id = json.loads(cli_res.output)["proposal_id"]

        inbox_svc = get_decision_inbox_service()
        saved = inbox_svc.get(proposal_id)
        assert saved["schedule_id"] == "sch_prompt_loop"
        assert saved["schedule_name"] == "夜间磁盘巡检"

        # 人类在收件箱批复同意
        inbox_svc.resolve(proposal_id, choice="approve", note="已确认可清理")

        # 第 2 轮触发：note_for_schedule 注入人类回执到任务正文前，并消费标记
        out2 = asyncio.run(ex.run_scheduled(schedule_obj))
        assert out2.ok is True
        prompt2 = seen_prompts[1]
        assert "【统一决策收件箱最新回执】" in prompt2
        assert "是否删除 12GB 过期缓存？" in prompt2
        assert "已确认可清理" in prompt2
        assert prompt2.index("【统一决策收件箱最新回执】") < prompt2.index("检查并清理过期构建缓存")
        assert inbox_svc.note_for_schedule("sch_prompt_loop") is None
        assert broadcasts == ["schedule_run_finished", "schedule_run_finished"]

    def test_employee_schedule_injects_env_pending_receipt_and_broadcasts_ws(
        self, tmp_path, monkeypatch
    ):
        import asyncio
        import json
        from types import SimpleNamespace

        from click.testing import CliRunner

        from frago.agent_driver import driver as driver_mod
        from frago.agent_driver import kernel_backend as kb_mod
        from frago.cli.propose_commands import propose_group
        from frago.decision_inbox import get_decision_inbox_service
        from frago.employee.store import EmployeePostRecord, save_post
        from frago.session import service as session_service_mod
        from frago.session import store as session_store_mod
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyStore

        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))
        monkeypatch.setenv("FRAGO_DECISION_INBOX_DIR", str(tmp_path / "decision-inbox"))
        emp_cwd = tmp_path / "emp-workspace"
        emp_cwd.mkdir(parents=True, exist_ok=True)
        save_post(
            EmployeePostRecord(
                member_post_id="ops-emp",
                title="值班专员",
                description="负责定时运维巡检",
                agent_kernel="coreagent",
                cwd=str(emp_cwd),
            )
        )

        store = SessionOntologyStore(
            tmp_path / "session-ontology-store.json",
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store)
        monkeypatch.setattr(session_store_mod, "_DEFAULT_SESSION_STORE", store)
        monkeypatch.setattr(session_service_mod, "_DEFAULT_SESSION_SERVICE", svc)
        monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: svc)

        dispatch_root = tmp_path / "dispatches"
        dispatch_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("frago.session.async_dispatch.dispatch_store_dir", lambda: dispatch_root)

        monkeypatch.setattr(driver_mod, "runs_on_kernel", lambda k: k == "coreagent")
        monkeypatch.setattr(kb_mod, "new_session_id", lambda: "core_emp_inbox_loop_01")

        captured_runs: list[dict[str, object]] = []

        def fake_run_turn(prompt, **kwargs):
            captured_runs.append({"prompt": prompt, "env": dict(kwargs.get("env") or {})})
            return SimpleNamespace(status="completed", text="巡检完毕")

        monkeypatch.setattr(kb_mod, "run_turn", fake_run_turn)

        broadcasts: list[str] = []

        async def fake_broadcast(*_args, action="refresh", **_kwargs):
            broadcasts.append(action)

        monkeypatch.setattr(
            "frago.server.websocket.broadcast_decision_inbox_update", fake_broadcast
        )

        schedule_obj = {
            "id": "sch_emp_loop",
            "name": "员工每日发布巡检",
            "kind": "employee",
            "employee_id": "ops-emp",
            "prompt": "核对待发布队列并执行",
        }

        # 第 1 轮：员工子进程拿到 FRAGO_SCHEDULE_ID / FRAGO_SCHEDULE_NAME
        out1 = asyncio.run(ex.run_scheduled(schedule_obj))
        assert out1.ok is True
        env1 = captured_runs[0]["env"]
        assert isinstance(env1, dict)
        assert env1["FRAGO_SCHEDULE_ID"] == "sch_emp_loop"
        assert env1["FRAGO_SCHEDULE_NAME"] == "员工每日发布巡检"
        assert env1["FRAGO_EMPLOYEE_ID"] == "ops-emp"

        # 模拟员工子进程内通过 frago app propose 提交提案（自动继承 schedule env）
        for k in (
            "FRAGO_SCHEDULE_ID",
            "FRAGO_SCHEDULE_NAME",
            "FRAGO_SESSION_ORIGIN",
            "FRAGO_UNATTENDED",
            "FRAGO_AGENT_ROLE",
            "FRAGO_EMPLOYEE_ID",
        ):
            monkeypatch.setenv(k, str(env1[k]))
        cli_res = CliRunner().invoke(
            propose_group,
            [
                "single-choice",
                "-q",
                "选择哪批镜像进行灰度？",
                "-o",
                "A|发布 v1.2|灰度 10%",
                "--dedup-key",
                "emp:canary:v1.2",
            ],
        )
        assert cli_res.exit_code == 0, cli_res.output
        proposal_id = json.loads(cli_res.output)["proposal_id"]

        inbox_svc = get_decision_inbox_service()
        saved = inbox_svc.get(proposal_id)
        assert saved["schedule_id"] == "sch_emp_loop"
        assert saved["schedule_name"] == "员工每日发布巡检"

        # 人类批复
        inbox_svc.resolve(proposal_id, choice="A", note="先灰度 10% 观测")

        # 第 2 轮：run_scheduled 自动将回执置于任务正文之前，消费标记，并广播 WS
        out2 = asyncio.run(ex.run_scheduled(schedule_obj))
        assert out2.ok is True
        prompt2 = str(captured_runs[1]["prompt"])
        assert "【统一决策收件箱最新回执】" in prompt2
        assert "选择哪批镜像进行灰度？" in prompt2
        assert "先灰度 10% 观测" in prompt2
        assert prompt2.index("【统一决策收件箱最新回执】") < prompt2.index("核对待发布队列并执行")
        assert "<frago-employee" in prompt2
        assert inbox_svc.note_for_schedule("sch_emp_loop") is None
        assert broadcasts == ["schedule_run_finished", "schedule_run_finished"]


