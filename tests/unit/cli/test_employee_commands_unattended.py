"""Tests for unattended / schedule env propagation across employee & worker turns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from frago.cli import agent_command, employee_commands
from frago.session import service as session_service_mod
from frago.session import store as session_store_mod
from frago.session.service import SessionOntologyService
from frago.session.store import SessionOntologyStore


def test_employee_turn_propagates_schedule_unattended_env_across_kernel_and_launcher(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    svc = SessionOntologyService(store)
    monkeypatch.setattr(session_store_mod, "_DEFAULT_SESSION_STORE", store)
    monkeypatch.setattr(session_service_mod, "_DEFAULT_SESSION_SERVICE", svc)
    monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: svc)

    monkeypatch.setenv("FRAGO_SESSION_ORIGIN", "schedule")
    monkeypatch.setenv("FRAGO_UNATTENDED", "1")
    monkeypatch.setenv("FRAGO_STOP_CHECK", "off")
    monkeypatch.setenv("FRAGO_REVIEW", "off")

    # 1) kernel_backend 分支（如 coreagent）
    captured_kernel_env: dict[str, str] = {}
    from frago.agent_driver import driver as driver_mod
    from frago.agent_driver import kernel_backend as kb_mod

    monkeypatch.setattr(driver_mod, "runs_on_kernel", lambda k: k == "coreagent")
    monkeypatch.setattr(kb_mod, "new_session_id", lambda: "core_emp_sched_001")

    def fake_run_turn(prompt, **kwargs):
        captured_kernel_env.update(kwargs.get("env") or {})
        return SimpleNamespace(status="completed", text="ok")

    monkeypatch.setattr(kb_mod, "run_turn", fake_run_turn)

    sid, status, text = employee_commands._run_agent_turn_for_employee(
        "coreagent",
        "整理日志",
        cwd=str(tmp_path),
        timeout_s=60,
        employee_id="ops",
    )
    assert sid == "core_emp_sched_001"
    assert status == "completed"
    assert text == "ok"
    assert captured_kernel_env["FRAGO_AGENT_ROLE"] == "employee"
    assert captured_kernel_env["FRAGO_SESSION_ORIGIN"] == "schedule"
    assert captured_kernel_env["FRAGO_UNATTENDED"] == "1"
    assert captured_kernel_env["FRAGO_STOP_CHECK"] == "off"
    assert captured_kernel_env["FRAGO_REVIEW"] == "off"
    rec = store.get("core_emp_sched_001")
    assert rec is not None
    assert rec.origin == "schedule"
    assert rec.is_worker is False

    # 2) SessionLauncher 分支（如 claude）
    captured_launcher_env: dict[str, str] = {}

    class FakeLauncher:
        def run(self, prompt, **kwargs):
            captured_launcher_env.update(kwargs.get("env") or {})
            return SimpleNamespace(status="ok", text="done", session_id=kwargs.get("session_id"))

    import frago.agent_driver as agent_driver_mod
    import frago.agent_driver.transcript as transcript_mod

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", FakeLauncher)
    monkeypatch.setattr(transcript_mod, "write_turn", lambda *_a, **_kw: None)
    monkeypatch.setattr(driver_mod, "listed_session_id", lambda _k, s, **_kw: s)

    sid2, status2, text2 = employee_commands._run_agent_turn_for_employee(
        "claude",
        "检查仓位",
        cwd=str(tmp_path),
        timeout_s=60,
        session_id="11111111-1111-4111-8111-111111111111",
        employee_id="stock",
    )
    assert sid2 == "11111111-1111-4111-8111-111111111111"
    assert status2 == "ok"
    assert text2 == "done"
    assert captured_launcher_env["FRAGO_AGENT_ROLE"] == "employee"
    assert captured_launcher_env["FRAGO_SESSION_ORIGIN"] == "schedule"
    assert captured_launcher_env["FRAGO_UNATTENDED"] == "1"
    assert captured_launcher_env["FRAGO_STOP_CHECK"] == "off"
    assert captured_launcher_env["FRAGO_REVIEW"] == "off"
    rec2 = store.get("11111111-1111-4111-8111-111111111111")
    assert rec2 is not None
    assert rec2.origin == "schedule"


def test_worker_sync_turn_retains_schedule_unattended_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRAGO_SESSION_ORIGIN", "schedule")
    monkeypatch.setenv("FRAGO_UNATTENDED", "1")
    monkeypatch.setenv("FRAGO_STOP_CHECK", "off")
    monkeypatch.setenv("FRAGO_REVIEW", "off")

    captured_env: dict[str, str] = {}
    from frago.agent_driver import driver as driver_mod
    from frago.agent_driver import kernel_backend as kb_mod

    monkeypatch.setattr(driver_mod, "runs_on_kernel", lambda k: k == "coreagent")
    monkeypatch.setattr(kb_mod, "new_session_id", lambda: "core_worker_sched_001")

    def fake_run_turn(prompt, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return SimpleNamespace(status="completed", text="worker done")

    monkeypatch.setattr(kb_mod, "run_turn", fake_run_turn)

    sid, status, text = agent_command._run_worker_turn_sync(
        "执行子任务",
        agent_type="coreagent",
        session_id=None,
        native_session_id=False,
        cwd=str(tmp_path),
        timeout=60,
    )
    assert sid == "core_worker_sched_001"
    assert status == "completed"
    assert text == "worker done"
    assert captured_env["FRAGO_AGENT_ROLE"] == "worker"
    assert captured_env["FRAGO_SESSION_ORIGIN"] == "schedule"
    assert captured_env["FRAGO_UNATTENDED"] == "1"
    assert captured_env["FRAGO_STOP_CHECK"] == "off"
    assert captured_env["FRAGO_REVIEW"] == "off"


def test_employee_commands_and_worker_sync_converge_to_launcher_single_exit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2：employee_commands 与 agent_command._run_worker_turn_sync 统一走 SessionLauncher 单出口且返回规范编号。"""
    import uuid as uuid_mod

    from frago.agent_driver import SessionLauncher, TurnResult
    from frago.agent_driver.drivers.claude import session_id_for
    from frago.agent_driver.transcript import persist_turn_result
    from frago.session import storage as session_storage

    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(session_storage, "get_session_base_dir", lambda: sessions_dir)
    monkeypatch.setenv("FRAGO_SESSION_ORIGIN", "schedule")

    raw_sid = "62d0beb0-d029-4820-8a79-c7727b7dd7cb"
    expected_canonical = session_id_for(raw_sid, native=False)
    monkeypatch.setattr(uuid_mod, "uuid4", lambda: uuid_mod.UUID(raw_sid))

    seen_calls: list[dict] = []

    def fake_run(self, prompt, **kwargs):
        seen_calls.append(kwargs)
        res = TurnResult(
            text="done",
            raw_delta="",
            status="ok",
            duration_ms=2000,
            canonical_session_id=expected_canonical,
        )
        if kwargs.get("persist_turn"):
            persist_turn_result(
                session_id=kwargs["session_id"],
                agent_type=kwargs["agent_type"],
                project_path=kwargs["cwd"],
                user_prompt=prompt,
                result=res,
                native_session_id=kwargs.get("native_session_id", False),
                source=kwargs.get("source", "terminal"),
            )
        return res

    monkeypatch.setattr(SessionLauncher, "run", fake_run)
    monkeypatch.setattr(
        employee_commands, "_register_schedule_origin_if_needed", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        "frago.cli.drive_command.register_transient_worker", lambda **_kw: None
    )
    monkeypatch.setattr(
        "frago.cli.drive_command.deregister_transient_worker", lambda *_a, **_kw: None
    )

    emp_sid, emp_status, emp_text = employee_commands._run_agent_turn_for_employee(
        "claude",
        "巡检任务",
        cwd=str(tmp_path),
        timeout_s=30,
        employee_id="demo-emp",
    )
    assert emp_sid == expected_canonical
    assert emp_status == "ok"
    assert emp_text == "done"
    assert seen_calls[-1]["persist_turn"] is True
    assert seen_calls[-1]["source"] == "schedule-employee"
    assert not (sessions_dir / "claude" / raw_sid).exists()

    worker_sid, worker_status, worker_text = agent_command._run_worker_turn_sync(
        "子任务",
        agent_type="claude",
        session_id=None,
        native_session_id=False,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert worker_sid == expected_canonical
    assert worker_status == "ok"
    assert worker_text == "done"
    assert seen_calls[-1]["persist_turn"] is True
    assert seen_calls[-1]["source"] == "schedule"
    assert not (sessions_dir / "claude" / raw_sid).exists()


def test_static_no_outer_write_turn_calls_outside_transcript_module() -> None:
    """AC-2 架构护栏：除 agent_driver/transcript.py 外，源码不得再直接调用 write_turn(raw_sid, ...)。"""
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[3] / "src" / "frago"
    offenders: list[str] = []
    for py_file in src_root.rglob("*.py"):
        rel = py_file.relative_to(src_root).as_posix()
        if rel == "agent_driver/transcript.py":
            continue
        text = py_file.read_text(encoding="utf-8")
        if "write_turn(" in text:
            offenders.append(rel)
    assert offenders == [], f"发现绕过统一出口直接调用 write_turn 的外层模块: {offenders}"

