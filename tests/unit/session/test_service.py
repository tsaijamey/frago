"""`SessionOntologyService` 五个动作的契约护栏。

这一条测试盯的是**同层双轨**这个病：`frago.json` 里写全了 preconditions / postconditions
/ invariants，但动作入口没有执行点，契约就只是文档——改 JSON 不会改变任何行为。这里每个
动作都断言「契约真的在拦」，而不只是「函数返回了预期值」。

另外两件事也在这里兜着：
1. 三个状态跃迁在记录消失时**显式抛错**（从前是 `assert`，`-O` 下会被剥掉）；
2. `adopt_existing_session` 的拒绝路径——补档是给「frago 没开过」的会话用的，不能拿它
   当改写既有记录的入口。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.ontology import ActionContractError
from frago.session.service import SessionOntologyService
from frago.session.store import SessionOntologyRecord, SessionOntologyStore


@pytest.fixture
def service(tmp_path: Path) -> SessionOntologyService:
    store = SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    return SessionOntologyService(store=store)


class TestLaunchAgentSession:
    """动作 1：`launch_agent_session`。"""

    def test_launch_records_kernel_origin_and_state(self, service: SessionOntologyService) -> None:
        proj = service.launch_agent_session(
            session_id="sess-launch-1",
            agent_kernel_id="claude",
            origin="web",
            initial_prompt="第一句话",
            cwd="/repo",
        )
        assert proj.session_process.process_uid == "session:sess-launch-1"
        assert proj.lifecycle_state is not None
        assert proj.lifecycle_state.value == "running"
        assert proj.origin_state.value == "web"

        rec = service.get_session("sess-launch-1")
        assert rec is not None
        assert rec.agent_kernel == "claude"
        assert rec.origin == "web"
        assert rec.prompt_head == "第一句话"

    def test_claude_code_alias_normalizes_to_claude(self, service: SessionOntologyService) -> None:
        """`claude-code` 是同一个内核的旧写法，归一到 `claude` 而不是当成未知内核拒掉。"""
        service.launch_agent_session(session_id="sess-alias-1", agent_kernel_id="claude-code")
        rec = service.get_session("sess-alias-1")
        assert rec is not None
        assert rec.agent_kernel == "claude"

    def test_unknown_kernel_is_rejected_not_defaulted(self, service: SessionOntologyService) -> None:
        """拼错的内核名当场拒掉，绝不静默回落成某个默认内核。"""
        with pytest.raises(ActionContractError, match="Unknown agent kernel"):
            service.launch_agent_session(session_id="sess-bad-kernel", agent_kernel_id="nope")
        assert service.get_session("sess-bad-kernel") is None

    def test_invalid_origin_is_rejected(self, service: SessionOntologyService) -> None:
        with pytest.raises(ActionContractError, match="Invalid session origin"):
            service.launch_agent_session(
                session_id="sess-bad-origin", agent_kernel_id="claude", origin="outer_space"
            )

    def test_worker_nesting_is_forbidden(self, service: SessionOntologyService) -> None:
        """worker 不许再派子会话——这是契约层的前置条件，也是函数体的硬护栏。"""
        with pytest.raises(ActionContractError, match="SubtaskWorkerRole is strictly prohibited"):
            service.launch_agent_session(
                session_id="sess-nested-1", agent_kernel_id="claude", caller_is_worker=True
            )
        with pytest.raises(ActionContractError, match="SubtaskWorkerRole is strictly prohibited"):
            service.launch_agent_session(
                session_id="sess-nested-2", agent_kernel_id="claude", caller_role="worker"
            )

    def test_empty_session_id_is_rejected_by_contract(self, service: SessionOntologyService) -> None:
        """空编号由契约前置条件拦下（`session_id MUST be a non-empty string`）。"""
        with pytest.raises(ActionContractError, match="session_id"):
            service.launch_agent_session(session_id="   ", agent_kernel_id="claude")

    def test_relaunching_active_session_is_rejected(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-dup-1", agent_kernel_id="claude")
        with pytest.raises(ActionContractError, match="already exists and is currently in active state"):
            service.launch_agent_session(session_id="sess-dup-1", agent_kernel_id="claude")


class TestRecordSessionStep:
    """动作 2：`record_session_step`。"""

    def test_steps_increment_monotonically(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-step-1", agent_kernel_id="claude")
        assert service.record_session_step(
            session_id="sess-step-1", step_type="user", payload_dict={"text": "hi"}
        ) == 1
        assert service.record_session_step(
            session_id="sess-step-1", step_type="tool_call", payload_dict={"tool": "Read"}, tool_name="Read"
        ) == 2
        rec = service.get_session("sess-step-1")
        assert rec is not None
        assert rec.step_count == 2
        assert rec.extra["latest_step"]["step_type"] == "tool_call"

    def test_unknown_session_is_rejected(self, service: SessionOntologyService) -> None:
        with pytest.raises(ActionContractError, match="does not exist"):
            service.record_session_step(session_id="sess-ghost", step_type="user")

    def test_invalid_step_type_is_rejected_by_contract(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-step-2", agent_kernel_id="claude")
        with pytest.raises(ActionContractError, match="step_type"):
            service.record_session_step(session_id="sess-step-2", step_type="telepathy")

    def test_step_on_terminated_session_is_rejected(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-step-3", agent_kernel_id="claude")
        service.terminate_agent_session(session_id="sess-step-3", terminal_status="completed")
        with pytest.raises(ActionContractError, match="is terminated"):
            service.record_session_step(session_id="sess-step-3", step_type="user")


class TestYieldAwaitingInput:
    """动作 3：`yield_awaiting_input`。"""

    def test_transitions_running_to_awaiting_input(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-yield-1", agent_kernel_id="claude")
        rec = service.yield_awaiting_input(
            session_id="sess-yield-1", waiting_reason="等人在决策卡上拍板"
        )
        assert rec.lifecycle_state == "awaiting_input"
        assert rec.waiting_reason == "等人在决策卡上拍板"

    def test_empty_waiting_reason_is_rejected_by_contract(self, service: SessionOntologyService) -> None:
        """不说为什么在等，这条动作就失去了意义——契约层直接拒。"""
        service.launch_agent_session(session_id="sess-yield-2", agent_kernel_id="claude")
        with pytest.raises(ActionContractError, match="waiting_reason"):
            service.yield_awaiting_input(session_id="sess-yield-2", waiting_reason="   ")

    def test_unknown_session_is_rejected(self, service: SessionOntologyService) -> None:
        with pytest.raises(ActionContractError, match="does not exist"):
            service.yield_awaiting_input(session_id="sess-ghost-2", waiting_reason="r")

    def test_terminal_session_cannot_yield(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-yield-3", agent_kernel_id="claude")
        service.terminate_agent_session(session_id="sess-yield-3", terminal_status="completed")
        with pytest.raises(ActionContractError, match="terminal state"):
            service.yield_awaiting_input(session_id="sess-yield-3", waiting_reason="r")


class TestTerminateAgentSession:
    """动作 4：`terminate_agent_session`。"""

    def test_terminate_to_completed(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-term-1", agent_kernel_id="claude")
        rec = service.terminate_agent_session(
            session_id="sess-term-1", terminal_status="completed", summary="都办完了"
        )
        assert rec.lifecycle_state == "completed"
        assert rec.summary == "都办完了"

    def test_invalid_terminal_status_is_rejected_by_contract(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-term-2", agent_kernel_id="claude")
        with pytest.raises(ActionContractError, match="terminal_status"):
            service.terminate_agent_session(session_id="sess-term-2", terminal_status="paused")

    def test_double_terminate_is_rejected(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-term-3", agent_kernel_id="claude")
        service.terminate_agent_session(session_id="sess-term-3", terminal_status="completed")
        with pytest.raises(ActionContractError, match="already in terminal state"):
            service.terminate_agent_session(session_id="sess-term-3", terminal_status="cancelled")

    def test_illegal_backward_transition_needs_explicit_resume(self, service: SessionOntologyService) -> None:
        service.launch_agent_session(session_id="sess-term-4", agent_kernel_id="claude")
        service.terminate_agent_session(session_id="sess-term-4", terminal_status="completed")
        with pytest.raises(ActionContractError, match="Illegal state machine transition"):
            service.transition_state(session_id="sess-term-4", target_state="running")
        resumed = service.transition_state(
            session_id="sess-term-4", target_state="running", allow_resume=True
        )
        assert resumed.lifecycle_state == "running"


class TestAdoptExistingSession:
    """动作 5：`adopt_existing_session` —— 补档的显式入口。"""

    def test_adopts_unregistered_session_with_observed_origin(self, service: SessionOntologyService) -> None:
        rec = service.adopt_existing_session(
            session_id="sess-adopt-1",
            agent_kernel_id="agy",
            origin="web",
            initial_state="running",
        )
        assert rec.session_id == "sess-adopt-1"
        assert rec.agent_kernel == "agy"
        assert rec.origin == "web"
        assert rec.lifecycle_state == "running"
        # 补档不编造父子关系：没有一条「谁派了谁」的事实可记。
        assert rec.relation_kind is None
        assert rec.is_worker is False

    def test_adoption_never_invents_a_dispatch_relation(self, service: SessionOntologyService) -> None:
        """补档不许带关系进来——那会把人的会话写成 worker，从会话树上掉下去。

        这一条由**契约前置条件**拦下（不是函数体）：契约谓词看得见 ``relation_kind``
        这个入参，而「不许编造父子关系」正是从入参就能判死的事。
        """
        with pytest.raises(ActionContractError, match="NEVER invents a parent relation"):
            service.adopt_existing_session(
                session_id="sess-adopt-2",
                agent_kernel_id="claude",
                origin="terminal",
                relation_kind="dispatch",
            )
        assert service.get_session("sess-adopt-2") is None

    def test_adoption_of_registered_session_is_rejected(self, service: SessionOntologyService) -> None:
        """已经在册的会话不能借补档之名重写——那会覆盖掉已认准的内核与出身。"""
        service.launch_agent_session(
            session_id="sess-adopt-3", agent_kernel_id="codex", origin="terminal"
        )
        with pytest.raises(ActionContractError, match="already registered"):
            service.adopt_existing_session(
                session_id="sess-adopt-3", agent_kernel_id="claude", origin="web"
            )
        # 既有记录原样不动。
        rec = service.get_session("sess-adopt-3")
        assert rec is not None
        assert rec.agent_kernel == "codex"
        assert rec.origin == "terminal"

    def test_declared_registered_but_missing_is_rejected(self, service: SessionOntologyService) -> None:
        """调用方声称在册、存储里却查不到：不替它圆过去。"""
        with pytest.raises(ActionContractError, match="no such record"):
            service.adopt_existing_session(
                session_id="sess-adopt-4", agent_kernel_id="claude", already_registered=True
            )

    def test_registered_read_back_when_declared(self, service: SessionOntologyService) -> None:
        """声明在册且确实在册时，走读回路径，返回既有记录。"""
        service.launch_agent_session(session_id="sess-adopt-5", agent_kernel_id="opencode")
        rec = service.adopt_existing_session(
            session_id="sess-adopt-5", agent_kernel_id="claude", already_registered=True
        )
        assert rec.agent_kernel == "opencode"

    def test_terminal_initial_state_is_rejected_by_invariant(self, service: SessionOntologyService) -> None:
        """补档进来就是终态，等于把一场活着的会话记成已结束——契约不变量拦住它。"""
        with pytest.raises(ActionContractError, match="terminal state"):
            service.adopt_existing_session(
                session_id="sess-adopt-6", agent_kernel_id="claude", initial_state="completed"
            )

    def test_ensure_managed_session_goes_through_the_registered_action(
        self, service: SessionOntologyService
    ) -> None:
        """`ensure_managed_session` 是 `adopt_existing_session` 的封装，不是旁路。"""
        rec = service.ensure_managed_session("sess-managed-1", agent_kernel_id="codex", origin="web")
        assert rec.agent_kernel == "codex"
        assert rec.origin == "web"
        assert service.get_session("sess-managed-1") is not None

        # 已存在的直接读回，不重复建档。
        again = service.ensure_managed_session("sess-managed-1", agent_kernel_id="claude")
        assert again.agent_kernel == "codex"


class TestContractIsActuallyWired:
    """契约真的挂上了，不是只写在 `frago.json` 里当文档。"""

    def test_each_action_exposes_its_ontology_contract(self) -> None:
        from frago.session import service as service_mod

        for name in (
            "_LAUNCH_AGENT_SESSION_CONTRACT",
            "_RECORD_SESSION_STEP_CONTRACT",
            "_YIELD_AWAITING_INPUT_CONTRACT",
            "_TERMINATE_AGENT_SESSION_CONTRACT",
            "_ADOPT_EXISTING_SESSION_CONTRACT",
        ):
            contract = getattr(service_mod, name)
            assert contract.norm_id in {
                "launch_agent_session",
                "record_session_step",
                "yield_awaiting_input",
                "terminate_agent_session",
                "adopt_existing_session",
            }
            # 三层同心圆都齐：参数表、签名、契约判据。
            assert contract.signature.parameters
            assert contract.preconditions

    def test_decorated_methods_carry_the_contract_object(self) -> None:
        """方法上带着 `ontology_contract`，说明装饰器确实执行过（不是手写护栏）。"""
        for method_name, expected_action in (
            ("launch_agent_session", "launch_agent_session"),
            ("record_session_step", "record_session_step"),
            ("yield_awaiting_input", "yield_awaiting_input"),
            ("terminate_agent_session", "terminate_agent_session"),
            ("adopt_existing_session", "adopt_existing_session"),
        ):
            method = getattr(SessionOntologyService, method_name)
            contract = getattr(method, "ontology_contract", None)
            assert contract is not None, f"{method_name} 没挂 @ontological_action"
            assert contract.norm_id == expected_action

    def test_no_bare_asserts_left_in_action_paths(self) -> None:
        """三个跃迁点不许再用 `assert` 做契约断言：`-O` 下它会被整句剥掉。"""
        import inspect

        from frago.session import service as service_mod

        src = inspect.getsource(service_mod)
        assert "assert updated is not None" not in src
