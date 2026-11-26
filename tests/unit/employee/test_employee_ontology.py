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


class TestDirectAnswerVsWorkerAndTerminalDelivery:
    """Verify C-1..C-8 & DEV-01..DEV-05 contracts across service, ledger, and hook prompt."""

    def test_build_business_context_block_direct_answer_and_terminal_delivery_rules(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from frago.employee import EmployeeOntologyService
        from frago.employee.store import EmployeeLedger, save_ledger

        emp_dir = tmp_path / "employees"
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(emp_dir))
        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))

        svc = EmployeeOntologyService()
        svc.hire(
            "general-specialist",
            title="通用业务专员",
            agent_kernel="claude",
            description="处理通用分析与业务协同。",
            knowledge_domains=["ops-notes"],
            recipes=["daily_summary"],
        )
        save_ledger(
            EmployeeLedger(
                member_post_id="general-specialist",
                intent_playbooks=[
                    {
                        "intent": "看现状 / 复盘 / 拆解当前情况",
                        "trigger_phrases": ["进展"],
                        "default_action": "上下文能答则直答，否则写清终态派 Worker。",
                    }
                ],
                claimed_resources={
                    "matched_sessions": [
                        {
                            "session_id": "sess-prev-001",
                            "title": "前序核查",
                            "latest_conclusion": "已完成初步排查",
                            "bound_to_post": True,
                        }
                    ]
                },
            )
        )

        block = svc.build_business_context_block(
            "general-specialist",
            auto_sync=False,
        )

        # C-1: 严禁出现「多份」数量灰区
        assert "多份" not in block

        # 直答三场景 & 派 Worker 四场景
        assert "能直答的场景当场直接回答（不派 Worker）" in block
        assert "① 上下文已有明确答案" in block
        assert "② 纯思考、判断与参谋" in block
        assert "③ 轻量追问与意图澄清" in block
        assert "必须派 Worker 的场景" in block
        assert "① 缺一手证据" in block
        assert "② 涉及真实执行与改动" in block
        assert "③ 需要独立视角验证" in block
        assert "④ 保护主会话上下文" in block

        # 终态交付四准则 + C-6 免问边界与决策卡口径
        assert "意图反推" in block
        assert "免确认直推与动前确认边界" in block
        assert "禁止再问、直接推进" in block
        assert "frago app ask" in block
        assert "定时/子任务禁发卡" in block
        assert "严禁裸写纯文本选项" in block
        assert "并在任务书中写清人类验收的终态定义与终态回读核验步骤" in block

        # C-7 终态回读由 Worker 执行，主会话只审不代查
        assert "由后台 Worker 在人类最终看到的位置" in block
        assert "主会话只基于回传证据做管理审阅把关" in block
        assert "主会话严禁亲自调工具补查，必须续接原 Worker 或新开独立 Worker 补做终态回读" in block

        # C-8 导语去重压长 & 四铁律基线保留
        assert "直接动手，不要先反问再找" not in block
        assert "上下文可无猜直答则直答" in block
        assert "非我职责绝对不由我来处理" in block
        assert "Employee **绝对不要自己去理解问题细节**" in block
        assert ">= 500k tokens" in block

        # desktop-operator 分支仍保持独立范式
        svc.hire(
            "desktop-operator",
            title="桌面操作员",
            agent_kernel="agy",
            description="操作 agent_os 虚拟桌面。",
        )
        desktop_block = svc.build_business_context_block("desktop-operator", auto_sync=False)
        assert "【桌面主操作员核心范式" in desktop_block
        assert "能直答的场景当场直接回答" not in desktop_block

    def test_derive_intent_playbooks_direct_answer_terminal_and_neutrality(self) -> None:
        import json

        from frago.employee.ledger import _derive_intent_playbooks
        from frago.employee.store import EmployeePostRecord

        rec = EmployeePostRecord(
            member_post_id="office-clerk",
            title="办公专员",
            description="处理日常文档与配方调度。",
        )
        playbooks = _derive_intent_playbooks(
            rec,
            claimed_recipes=[{"name": "office_doc_archive", "description": "归档文档"}],
            claimed_slots=[{"path": "~/.frago/data/office-clerk"}],
            claimed_domains=[{"name": "office-rules"}],
        )
        by_intent = {pb["intent"]: pb for pb in playbooks}
        assert "看现状 / 复盘 / 拆解当前情况" in by_intent
        assert "调度本岗位配方与自动化工具" in by_intent
        assert "调取本岗位既有结论与领域准则" in by_intent

        status_action = by_intent["看现状 / 复盘 / 拆解当前情况"]["default_action"]
        assert "无猜地回答人类" in status_action
        assert "终态定义与回读核验步骤" in status_action

        recipe_action = by_intent["调度本岗位配方与自动化工具"]["default_action"]
        assert "终态定义与回读核验步骤" in recipe_action
        assert "不可逆外部副作用" in recipe_action

        domain_action = by_intent["调取本岗位既有结论与领域准则"]["default_action"]
        assert "当场直答" in domain_action
        assert "回读核验" in domain_action

        # recipe-builder 专属剧本同样含终态与回读核验
        rb_rec = EmployeePostRecord(
            member_post_id="recipe-builder",
            title="配方构建师",
            knowledge_domains=["frago-recipe-ops"],
        )
        rb_playbooks = _derive_intent_playbooks(
            rb_rec,
            claimed_recipes=[],
            claimed_slots=[],
            claimed_domains=[{"name": "frago-recipe-ops"}],
        )
        rb_authoring = next(
            pb for pb in rb_playbooks if "新建或迭代本机配方" in pb["intent"]
        )
        assert "终态定义及实际页面/运行态回读核验步骤" in rb_authoring["default_action"]

        all_text = json.dumps(playbooks + rb_playbooks, ensure_ascii=False)
        assert "多份" not in all_text
        for leaked in ("投研框架", "回测", "算信号"):
            assert leaked not in all_text

    def test_lightagent_hook_prompt_employee_direct_answer_and_terminal_rules(self) -> None:
        prompt_path = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "frago"
            / "resources"
            / "hook"
            / "prompt.md"
        )
        text = prompt_path.read_text(encoding="utf-8")
        assert "多份" not in text

        emp_line = next(
            line for line in text.splitlines() if line.startswith("**员工岗位会话")
        )
        assert "免问直推" in emp_line
        assert "动前确认" in emp_line
        assert "frago app ask" in emp_line
        assert "定时/子任务禁发卡" in emp_line
        assert "②a" in emp_line and "②b" in emp_line
        assert "终态定义及回读核验步骤" in emp_line
        assert "主会话只审 Worker 带回的真实位置终态回读证据" in emp_line
        assert "严禁主会话亲自补查，必须续接/补派 Worker 核验" in emp_line
        assert ">=500k" in emp_line


