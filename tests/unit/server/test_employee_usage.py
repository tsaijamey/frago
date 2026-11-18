"""Verify `/api/employees` MRU sorting backed by real session history and launch invalidation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.employee import EmployeePostRecord, save_post
from frago.server.services import employee_usage, workbench_new_session
from frago.session import record_reader
from frago.session.record_reader import SessionCard


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    emp_dir = tmp_path / "employees"
    emp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    employee_usage.invalidate_employee_usage_cache()
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def test_list_employees_orders_by_session_last_used_at_desc(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(EmployeePostRecord(member_post_id="alpha-bot", title="Alpha"))
    save_post(EmployeePostRecord(member_post_id="beta-bot", title="Beta"))
    save_post(EmployeePostRecord(member_post_id="gamma-bot", title="Gamma"))
    save_post(EmployeePostRecord(member_post_id="delta-bot", title="Delta"))

    cards = [
        SessionCard(
            session_id="s-beta",
            family="claude-code",
            title="Beta task",
            directory="/tmp",
            created_at=1_700_000_100_000,
            last_active_at=1_700_000_200_000,
            employee_id="beta-bot",
        ),
        SessionCard(
            session_id="s-gamma",
            family="codex",
            title="Gamma task",
            directory="/tmp",
            created_at=1_700_000_300_000,
            last_active_at=1_700_000_500_000,
            employee_id="gamma-bot",
        ),
        # Worker card should not propagate employee via parent fallback
        SessionCard(
            session_id="w-alpha",
            family="claude-code",
            title="Worker",
            directory="/tmp",
            created_at=1_700_000_900_000,
            last_active_at=1_700_000_999_000,
            origin="worker",
            parent_session_id="s-beta",
            employee_id=None,
        ),
    ]
    monkeypatch.setattr(record_reader, "list_sessions", lambda: cards)

    res = client.get("/api/employees")
    assert res.status_code == 200
    items = res.json()["employees"]
    assert [e["member_post_id"] for e in items] == [
        "gamma-bot",
        "beta-bot",
        "alpha-bot",
        "delta-bot",
    ]
    assert items[0]["last_used_at"] is not None
    assert items[1]["last_used_at"] is not None
    assert items[2]["last_used_at"] is None
    assert items[3]["last_used_at"] is None


def test_create_employee_session_promotes_employee_immediately(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(EmployeePostRecord(member_post_id="alpha-bot", title="Alpha", cwd=str(tmp_path)))
    save_post(EmployeePostRecord(member_post_id="zeta-bot", title="Zeta", cwd=str(tmp_path)))
    monkeypatch.setattr(record_reader, "list_sessions", lambda: [])

    # Before launch: alphabetical fallback puts alpha-bot first
    before = client.get("/api/employees").json()["employees"]
    assert [e["member_post_id"] for e in before] == ["alpha-bot", "zeta-bot"]

    # Mock session start & context block
    class _FakeService:
        def build_business_context_block(self, _post_id: str) -> str:
            return "<frago-employee>ctx</frago-employee>"

    monkeypatch.setattr("frago.server.routes.workbench.EmployeeOntologyService", _FakeService)
    monkeypatch.setattr(
        workbench_new_session,
        "start_with_id",
        lambda agent_type, cwd, prompt, *, session_id: workbench_new_session.PendingLaunch(
            handle=session_id,
            agent_type=agent_type,
            display_name="Claude Code",
            cwd=cwd,
            session_id=session_id,
        ),
    )

    resp = client.post(
        "/api/workbench/sessions",
        json={"agent": "claude", "cwd": str(tmp_path), "text": "hi", "employee": "zeta-bot"},
    )
    assert resp.status_code == 201

    after = client.get("/api/employees").json()["employees"]
    assert [e["member_post_id"] for e in after] == ["zeta-bot", "alpha-bot"]
    assert after[0]["last_used_at"] is not None
