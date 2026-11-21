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
