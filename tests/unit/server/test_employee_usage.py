"""Verify `/api/employees` MRU sorting backed by real session history and launch invalidation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.agent_driver.tmux_session import tmux_name_for
from frago.employee import EmployeePostRecord, save_post
from frago.server.routes import workbench as workbench_routes
from frago.server.services import (
    coreagent_runner,
    employee_usage,
    tmux_sessions_service,
    workbench_new_session,
)
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


def test_list_employees_returns_session_counts_with_lineage_and_dedup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(
        EmployeePostRecord(
            member_post_id="alpha-bot",
            title="Alpha",
            active_session_ids=["s-unflushed"],
        )
    )
    save_post(
        EmployeePostRecord(
            member_post_id="beta-bot",
            title="Beta",
            active_session_ids=["s-active-slot"],
        )
    )
    save_post(EmployeePostRecord(member_post_id="idle-bot", title="Idle"))

    cards = [
        SessionCard(
            session_id="s-beta-run",
            family="claude-code",
            title="Beta running",
            directory="/tmp",
            created_at=1_700_000_100_000,
            last_active_at=1_700_000_200_000,
            status="running",
            employee_id="beta-bot",
        ),
        # 重复 session_id 应去重，不能重复计数
        SessionCard(
            session_id="s-beta-run",
            family="opencode",
            title="Beta running dup",
            directory="/tmp",
            created_at=1_700_000_100_000,
            last_active_at=1_700_000_200_000,
            status="running",
            employee_id="beta-bot",
        ),
        # branch 继承归属 beta-bot，且已结束
        SessionCard(
            session_id="s-beta-branch",
            family="claude-code",
            title="Beta branch",
            directory="/tmp",
            created_at=1_700_000_120_000,
            last_active_at=1_700_000_220_000,
            status="done",
            origin="human",
            relation="branch",
            parent_session_id="s-beta-run",
            employee_id=None,
        ),
        # 来自 active_session_ids 且已完结：total +1, active +0
        SessionCard(
            session_id="s-active-slot",
            family="codex",
            title="Slot finished",
            directory="/tmp",
            created_at=1_700_000_130_000,
            last_active_at=1_700_000_230_000,
            status="done",
            employee_id=None,
        ),
        # 普通 worker 不应继承 beta-bot 计数
        SessionCard(
            session_id="w-beta",
            family="claude-code",
            title="Worker",
            directory="/tmp",
            created_at=1_700_000_900_000,
            last_active_at=1_700_000_999_000,
            status="running",
            origin="worker",
            parent_session_id="s-beta-run",
            employee_id=None,
        ),
    ]
    monkeypatch.setattr(
        tmux_sessions_service,
        "open_session_names",
        lambda: {tmux_name_for("s-beta-run")},
    )
    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(record_reader, "list_sessions", lambda: cards)

    res = client.get("/api/employees")
    assert res.status_code == 200
    by_id = {item["member_post_id"]: item for item in res.json()["employees"]}

    assert by_id["beta-bot"]["session_counts"] == {"active": 1, "total": 3}
    # alpha-bot 含一条尚未落盘到 record_reader 的 active_session_ids
    assert by_id["alpha-bot"]["session_counts"] == {"active": 1, "total": 1}
    assert by_id["idle-bot"]["session_counts"] == {"active": 0, "total": 0}


def test_list_employees_counts_apply_liveness_closing_and_need_decision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(EmployeePostRecord(member_post_id="beta-bot", title="Beta"))

    captured_liveness: list[Mapping[str, bool] | None] = []
    cards = [
        # 1. 真实存活在 tmux：active +1
        SessionCard(
            session_id="s-live",
            family="claude-code",
            title="Live tmux",
            directory="/tmp",
            created_at=1_700_000_100_000,
            last_active_at=1_700_000_200_000,
            status="running",
            employee_id="beta-bot",
        ),
        # 2. transcript 遗留 running，但既不在 tmux 也不在 coreagent 实时态 -> 收口为非活跃
        SessionCard(
            session_id="s-stale",
            family="claude-code",
            title="Stale running",
            directory="/tmp",
            created_at=1_700_000_110_000,
            last_active_at=1_700_000_210_000,
            status="running",
            employee_id="beta-bot",
        ),
        # 3. 虽 status=done，但 observer 处于 need_decision -> 计为 active
        SessionCard(
            session_id="s-need-decision",
            family="codex",
            title="Waiting decision",
            directory="/tmp",
            created_at=1_700_000_120_000,
            last_active_at=1_700_000_220_000,
            status="done",
            employee_id="beta-bot",
        ),
    ]

    def _fake_list_sessions(*, liveness=None):
        captured_liveness.append(liveness)
        return cards

    monkeypatch.setattr(
        tmux_sessions_service,
        "open_session_names",
        lambda: {tmux_name_for("s-live")},
    )
    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(
        workbench_routes,
        "_observer_slots_state",
        lambda _sid, _family: (False, False),
    )
    monkeypatch.setattr(
        workbench_routes,
        "_session_needs_decision",
        lambda card, **_kwargs: card.session_id == "s-need-decision",
    )
    monkeypatch.setattr(record_reader, "list_sessions", _fake_list_sessions)

    res = client.get("/api/employees")
    assert res.status_code == 200
    assert len(captured_liveness) == 1
    live_map = captured_liveness[0]
    assert isinstance(live_map, Mapping)
    assert live_map["s-live"] is True
    assert live_map["s-stale"] is False
    assert list(live_map) == ["s-live"]

    by_id = {item["member_post_id"]: item for item in res.json()["employees"]}
    assert by_id["beta-bot"]["session_counts"] == {"active": 2, "total": 3}
