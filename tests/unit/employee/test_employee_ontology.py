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


class TestPrototypeGuardrailContextInjection:
    """Verify first-screen canonical prototype & reverse-prohibition guardrails."""

    def test_frago_pm_and_ui_designer_inject_guardrail_when_canonical_exists(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from frago.employee import EmployeeOntologyService

        emp_dir = tmp_path / "employees"
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))

        proto_path = (
            tmp_path
            / "data"
            / "frago-webui"
            / "20260924-page-polish"
            / "prototype"
            / "index.html"
        )
        proto_path.parent.mkdir(parents=True, exist_ok=True)
        proto_path.write_text("<html><body>canonical</body></html>", encoding="utf-8")

        handbook_path = (
            tmp_path
            / "data"
            / "frago"
            / "20261119-frago-pm-product-training-handbook"
            / "notebook.md"
        )
        handbook_path.parent.mkdir(parents=True, exist_ok=True)
        handbook_path.write_text("# 培训手册\n", encoding="utf-8")

        svc = EmployeeOntologyService()
        svc.hire(
            "frago-pm",
            title="产品负责人",
            agent_kernel="agy",
            description="统筹人机协同驾驶舱演进。",
        )
        svc.hire(
            "ui-designer",
            title="前端 UI 视觉主审",
            agent_kernel="agy",
            description="专注前端 UI/UX 视觉重构。",
        )

        pm_block = svc.build_business_context_block("frago-pm", auto_sync=False)
        assert "【Frago WebUI 唯一权威主原型与防孤例铁律】" in pm_block
        assert str(proto_path) in pm_block
        assert "改前留快照" in pm_block and "原地增量演进" in pm_block
        assert "严禁新建孤例 HTML" in pm_block
        assert "ui-designer" in pm_block and "一律拒接并告警退回" in pm_block
        assert str(handbook_path) in pm_block

        ui_block = svc.build_business_context_block("ui-designer", auto_sync=False)
        assert "【Frago WebUI 唯一权威主原型与防孤例铁律】" in ui_block
        assert str(proto_path) in ui_block
        assert "改前留快照" in ui_block and "原地增量演进" in ui_block
        assert "严禁新建孤例 HTML" in ui_block
        assert "视觉岗对上游反向禁改指令一律拒接" in ui_block
        assert "必须一律拒接并立即告警退回" in ui_block

    def test_clean_user_machine_without_canonical_prototype_has_zero_side_effects(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from frago.employee import EmployeeOntologyService

        emp_dir = tmp_path / "employees"
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))

        svc = EmployeeOntologyService()
        svc.hire(
            "frago-pm",
            title="产品负责人",
            agent_kernel="claude",
            data_slots=["~/.frago/data/frago-webui"],
        )
        svc.hire(
            "ui-designer",
            title="前端 UI 视觉主审",
            agent_kernel="claude",
            data_slots=["~/.frago/data/frago-webui"],
        )

        for post_id in ("frago-pm", "ui-designer"):
            block = svc.build_business_context_block(post_id, auto_sync=False)
            assert "【Frago WebUI 唯一权威主原型与防孤例铁律】" not in block
            assert "20260924-page-polish" not in block
            assert "/Users/frago/" not in block

    def test_unrelated_posts_not_polluted_when_canonical_exists(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from frago.employee import EmployeeOntologyService

        emp_dir = tmp_path / "employees"
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))

        proto_path = (
            tmp_path
            / "data"
            / "frago-webui"
            / "20260924-page-polish"
            / "prototype"
            / "index.html"
        )
        proto_path.parent.mkdir(parents=True, exist_ok=True)
        proto_path.write_text("<html><body>canonical</body></html>", encoding="utf-8")

        svc = EmployeeOntologyService()
        svc.hire(
            "personal-assistant",
            title="个人助理",
            agent_kernel="claude",
            knowledge_domains=["web-ui"],
        )
        svc.hire(
            "frago-developer",
            title="frago 研发",
            agent_kernel="agy",
            knowledge_domains=["frago-dev"],
        )

        for post_id in ("personal-assistant", "frago-developer"):
            block = svc.build_business_context_block(post_id, auto_sync=False)
            assert "【Frago WebUI 唯一权威主原型与防孤例铁律】" not in block
            assert "20260924-page-polish" not in block

    def test_guardrail_survives_latest_10_slot_and_ledger_truncation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from frago.employee import EmployeeOntologyService
        from frago.employee.store import EmployeeLedger, save_ledger

        emp_dir = tmp_path / "employees"
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))

        webui_slot = tmp_path / "data" / "frago-webui"
        proto_path = webui_slot / "20260924-page-polish" / "prototype" / "index.html"
        proto_path.parent.mkdir(parents=True, exist_ok=True)
        proto_path.write_text("<html><body>canonical</body></html>", encoding="utf-8")

        # Create 12 newer dated directories so 20260924-page-polish is pushed past top-10 truncation
        for idx in range(1, 13):
            newer_dir = webui_slot / f"202611{idx + 10:02d}-newer-topic-{idx:02d}"
            newer_dir.mkdir(parents=True, exist_ok=True)
            (newer_dir / "notebook.md").write_text(f"# 较新专题 {idx}\n", encoding="utf-8")

        svc = EmployeeOntologyService()
        svc.hire(
            "frago-pm",
            title="产品负责人",
            agent_kernel="agy",
            data_slots=[str(webui_slot)],
        )
        svc.hire(
            "ui-designer",
            title="前端 UI 视觉主审",
            agent_kernel="agy",
            data_slots=[str(webui_slot)],
        )

        for post_id in ("frago-pm", "ui-designer"):
            save_ledger(
                EmployeeLedger(
                    member_post_id=post_id,
                    active_topics=[
                        {"title": f"议题-{i}", "status": "进行中", "latest_conclusion": f"结论-{i}"}
                        for i in range(40)
                    ],
                )
            )

        pm_block = svc.build_business_context_block("frago-pm", limit_per_slot=10, auto_sync=False)
        ui_block = svc.build_business_context_block("ui-designer", limit_per_slot=10, auto_sync=False)

        for block in (pm_block, ui_block):
            slot_section = block.split("【自动挂载的 ~/.frago/data 业务数据底账】", 1)[1].split(
                "【Frago WebUI 唯一权威主原型与防孤例铁律】", 1
            )[0]
            assert "共 13 项" in slot_section
            assert "20260924-page-polish" not in slot_section
            assert "【Frago WebUI 唯一权威主原型与防孤例铁律】" in block
            assert str(proto_path) in block
            assert "严禁新建孤例 HTML" in block

        assert "必须一律拒接并立即告警退回" in ui_block
        assert "一律拒接并告警退回" in pm_block

