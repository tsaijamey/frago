"""Verify `GET /api/employees/{member_post_id}/sessions` lineage, sorting, filtering, pagination and 404."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.employee import EmployeePostRecord, save_post
from frago.server.routes import workbench as workbench_routes
from frago.server.services import coreagent_runner, tmux_sessions_service, workbench_titles
from frago.session import record_reader
from frago.session.record_reader import SessionCard


@dataclass
class _FakeOntoRec:
    session_id: str
    employee_id: str | None = None
    lifecycle_state: str | None = None
    turn_seq: int = 0
    updated_at: float = 0.0


class _FakeOntoService:
    def __init__(self, records: list[_FakeOntoRec] | None = None) -> None:
        self._records = records or []
        self.store = self

    def list_sessions(self) -> list[_FakeOntoRec]:
        return list(self._records)

    def batch_reconcile_states(self, _heals: list[tuple[str, str, str | None]]) -> None:
        return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    emp_dir = tmp_path / "employees"
    emp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
    monkeypatch.setenv("FRAGO_HOME", str(tmp_path / "frago_home"))
    monkeypatch.setattr(tmux_sessions_service, "open_session_names", lambda: set())
    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(workbench_titles, "load", lambda: {})
    monkeypatch.setattr(workbench_routes, "_observer_slots_state", lambda _sid, _fam: (False, False))
    monkeypatch.setattr(workbench_routes, "_keep_watching_only", lambda _alive: None)
    monkeypatch.setattr("frago.server.routes.workbench.workbench_groups.local_ops_session_ids", lambda: set())

    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def test_employee_sessions_404_for_unknown_employee(client: TestClient) -> None:
    save_post(EmployeePostRecord(member_post_id="stock", title="Stock"))
    res = client.get("/api/employees/nonexistent-emp/sessions")
    assert res.status_code == 404


def test_employee_sessions_empty_for_zero_sessions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(EmployeePostRecord(member_post_id="empty-bot", title="Empty Bot"))
    monkeypatch.setattr(record_reader, "list_sessions", lambda: [])
    monkeypatch.setattr(
        "frago.session.service.get_default_session_service",
        lambda: _FakeOntoService([]),
    )

    res = client.get("/api/employees/empty-bot/sessions")
    assert res.status_code == 200
    assert res.json() == {
        "employee_id": "empty-bot",
        "sessions": [],
        "total": 0,
        "active_count": 0,
        "completed_count": 0,
        "has_more": False,
    }


def test_employee_sessions_four_level_lineage_excludes_plain_workers_and_sorts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(
        EmployeePostRecord(
            member_post_id="dev-bot",
            title="Dev Bot",
            color="violet",
            active_session_ids=["s-active-slot"],
        )
    )
    save_post(EmployeePostRecord(member_post_id="other-bot", title="Other", color="ocean"))

    # 1) direct tag (running, older reply -> active)
    c_direct = SessionCard(
        session_id="s-direct",
        family="claude-code",
        title="Direct session",
        directory="/tmp/repo",
        created_at=1_700_000_100_000,
        last_active_at=1_700_000_150_000,
        last_reply_at=1_700_000_160_000,
        status="running",
        last_kind="tool.use",
        employee_id="dev-bot",
    )
    # 2) SessionOntologyService (awaiting_input / need_decision -> active, newer than s-direct)
    c_onto = SessionCard(
        session_id="s-onto",
        family="codex",
        title="Onto awaiting decision",
        directory="/tmp/repo",
        created_at=1_700_000_200_000,
        last_active_at=1_700_000_300_000,
        last_reply_at=1_700_000_350_000,
        status="done",
        lifecycle_state="awaiting_input",
        employee_id=None,
    )
    # 3) active_session_ids (completed -> completed)
    c_slot = SessionCard(
        session_id="s-active-slot",
        family="coreagent",
        title="Slot completed",
        directory="/tmp/repo",
        created_at=1_700_000_400_000,
        last_active_at=1_700_000_500_000,
        last_reply_at=1_700_000_550_000,
        status="done",
        employee_id=None,
    )
    # 4) 8-hop non-worker inheritance (hop1 -> hop2 -> ... -> hop8 from s-direct)
    lineage_cards: list[SessionCard] = []
    parent = "s-direct"
    for hop in range(1, 9):
        sid = f"s-hop-{hop}"
        lineage_cards.append(
            SessionCard(
                session_id=sid,
                family="claude-code",
                title=f"Hop {hop}",
                directory="/tmp/repo",
                created_at=1_700_000_010_000 + hop * 1000,
                last_active_at=1_700_000_010_000 + hop * 1000,
                status="done",
                origin="human",
                relation="branch" if hop % 2 == 1 else "handoff",
                parent_session_id=parent,
                employee_id=None,
            )
        )
        parent = sid
    # 9th hop exceeds 8-hop limit and should not belong to dev-bot
    c_hop9 = SessionCard(
        session_id="s-hop-9",
        family="claude-code",
        title="Hop 9 out of range",
        directory="/tmp/repo",
        created_at=1_700_000_999_000,
        last_active_at=1_700_000_999_000,
        status="done",
        origin="human",
        relation="branch",
        parent_session_id="s-hop-8",
        employee_id=None,
    )
    # Plain worker child (no explicit employee_id) must be excluded
    c_worker = SessionCard(
        session_id="w-plain",
        family="claude-code",
        title="Plain worker",
        directory="/tmp/repo",
        created_at=1_700_000_999_000,
        last_active_at=1_700_000_999_000,
        status="running",
        origin="worker",
        parent_session_id="s-direct",
        employee_id=None,
    )
    # Other employee session must be excluded
    c_other = SessionCard(
        session_id="s-other",
        family="claude-code",
        title="Other employee",
        directory="/tmp/repo",
        created_at=1_700_000_999_000,
        last_active_at=1_700_000_999_000,
        status="running",
        employee_id="other-bot",
    )

    monkeypatch.setattr(
        record_reader,
        "list_sessions",
        lambda: [c_direct, c_onto, c_slot, *lineage_cards, c_hop9, c_worker, c_other],
    )
    monkeypatch.setattr(
        "frago.session.service.get_default_session_service",
        lambda: _FakeOntoService(
            [
                _FakeOntoRec(session_id="s-onto", employee_id="dev-bot", lifecycle_state="awaiting_input"),
                _FakeOntoRec(session_id="s-direct", employee_id="dev-bot", lifecycle_state="running"),
            ]
        ),
    )
    # s-direct is alive in tmux so running stays running
    monkeypatch.setattr(
        tmux_sessions_service,
        "open_session_names",
        lambda: {"frago-agent-s-direct"},
    )
    # s-onto has need_decision via trailing unanswered card check
    monkeypatch.setattr(
        workbench_routes,
        "_session_needs_decision",
        lambda card, **_kwargs: card.session_id == "s-onto",
    )

    res = client.get("/api/employees/dev-bot/sessions")
    assert res.status_code == 200
    body = res.json()
    assert body["employee_id"] == "dev-bot"
    assert body["active_count"] == 2
    assert body["completed_count"] == 9
    assert body["total"] == 11
    assert body["has_more"] is False

    ids = [s["session_id"] for s in body["sessions"]]
    # Active/need_decision first, ordered by latest activity desc (s-onto 350k > s-direct 160k),
    # then completed ordered by latest activity desc (s-active-slot 550k > s-hop-8..1)
    assert ids[:3] == ["s-onto", "s-direct", "s-active-slot"]
    assert ids[3:] == [f"s-hop-{h}" for h in range(8, 0, -1)]
    assert "s-hop-9" not in ids
    assert "w-plain" not in ids
    assert "s-other" not in ids

    # Check enriched employee fields on returned items
    first = body["sessions"][0]
    assert first["employee_id"] == "dev-bot"
    assert first["employee_title"] == "Dev Bot"
    assert first["employee_color"] == "violet"
    assert first["need_decision"] is True


def test_employee_sessions_status_filter_and_pagination(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_post(EmployeePostRecord(member_post_id="page-bot", title="Page Bot"))

    cards = [
        SessionCard(
            session_id=f"s-run-{i}",
            family="claude-code",
            title=f"Run {i}",
            directory="/tmp",
            created_at=1_700_000_000_000 + i * 1000,
            last_active_at=1_700_000_000_000 + i * 1000,
            status="running",
            last_kind="tool.use",
            employee_id="page-bot",
        )
        for i in range(3)
    ] + [
        SessionCard(
            session_id=f"s-done-{i}",
            family="claude-code",
            title=f"Done {i}",
            directory="/tmp",
            created_at=1_700_000_100_000 + i * 1000,
            last_active_at=1_700_000_100_000 + i * 1000,
            status="done",
            employee_id="page-bot",
        )
        for i in range(4)
    ]

    monkeypatch.setattr(record_reader, "list_sessions", lambda: cards)
    monkeypatch.setattr(
        "frago.session.service.get_default_session_service",
        lambda: _FakeOntoService([]),
    )
    monkeypatch.setattr(
        tmux_sessions_service,
        "open_session_names",
        lambda: {f"frago-agent-s-run-{i}" for i in range(3)},
    )

    # Active filter
    r_active = client.get("/api/employees/page-bot/sessions?status=active&limit=2&offset=0")
    assert r_active.status_code == 200
    d_active = r_active.json()
    assert d_active["total"] == 3
    assert d_active["active_count"] == 3
    assert d_active["completed_count"] == 4
    assert d_active["has_more"] is True
    assert [s["session_id"] for s in d_active["sessions"]] == ["s-run-2", "s-run-1"]

    # Second page of active
    r_active_p2 = client.get("/api/employees/page-bot/sessions?status=active&limit=2&offset=2")
    assert r_active_p2.status_code == 200
    d_p2 = r_active_p2.json()
    assert d_p2["has_more"] is False
    assert [s["session_id"] for s in d_p2["sessions"]] == ["s-run-0"]

    # Completed filter
    r_done = client.get("/api/employees/page-bot/sessions?status=completed&limit=2&offset=1")
    assert r_done.status_code == 200
    d_done = r_done.json()
    assert d_done["total"] == 4
    assert d_done["active_count"] == 3
    assert d_done["completed_count"] == 4
    assert d_done["has_more"] is True
    assert [s["session_id"] for s in d_done["sessions"]] == ["s-done-2", "s-done-1"]

    # Limit > 200 rejected
    r_bad = client.get("/api/employees/page-bot/sessions?limit=201")
    assert r_bad.status_code == 422
