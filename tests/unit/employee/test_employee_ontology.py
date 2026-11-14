"""Employee and Session Ontology integration unit tests."""

from pathlib import Path

import pytest

from frago.employee.ledger import _inspect_session_dir
from frago.ontology import AgentSessionProcess, SessionLifecycleState, SessionOriginState
from frago.session.service import SessionOntologyService
from frago.session.store import SessionOntologyStore


def test_employee_ledger_inspects_session_with_ontology_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_file = tmp_path / "sessions.json"
    store = SessionOntologyStore(store_file)
    monkeypatch.setattr("frago.session.store._DEFAULT_SESSION_STORE", store)
    service = SessionOntologyService(store=store)

    session_id = "sess-emp-ont-001"
    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True)
    metadata_file = session_dir / "metadata.json"
    metadata_file.write_text('{"id": "sess-emp-ont-001", "driver": "claude"}', encoding="utf-8")

    # Launch ontology session
    proj = service.launch_agent_session(
        session_id=session_id,
        agent_kernel="claude",
        origin="terminal",
        cwd=str(session_dir),
    )
    assert proj.lifecycle_state is not None
    assert proj.lifecycle_state.value == SessionLifecycleState.RUNNING.value
    assert proj.origin_state is not None
    assert proj.origin_state.value == SessionOriginState.TERMINAL.value

    # Inspect session directory using employee ledger inspect logic
    inspected = _inspect_session_dir(session_dir, session_id)
    assert inspected is not None
    assert inspected["session_id"] == session_id
    assert inspected["lifecycle_state"] == SessionLifecycleState.RUNNING.value
    assert inspected["origin"] == SessionOriginState.TERMINAL.value
    assert inspected.get("is_worker", False) is False

    # Verify AgentSessionProcess instance projection
    process = store.get(session_id)
    assert process is not None
    assert process.session_id == session_id
    session_process = service.get_session_process(session_id)
    assert isinstance(session_process, AgentSessionProcess)
