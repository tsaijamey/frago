"""Unit tests for src/frago/ontology/ (S1: metamodel, relations, contracts, introspection)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import pytest

from frago.ontology import (
    BUILTIN_DEFINED_CLASSES,
    DEFAULT_DOMAIN_REGISTRY,
    ActionSignature,
    Actor,
    AlgebraicAxiomViolationError,
    Capability,
    CliActionRegistry,
    ConditionCheck,
    Continuant,
    DesktopStageLifecycleRuntime,
    DomainClassRegistry,
    DomainRangeViolationError,
    Event,
    IdentityCriterionError,
    InvariantViolationError,
    KnowledgeArtifact,
    MutabilityViolationError,
    Occurrent,
    OntoCleanViolationError,
    OntologicalActionContract,
    OntologyEntity,
    OntologyGraph,
    OntologyIntrospector,
    OntologyReasoner,
    PostconditionViolationError,
    PreconditionViolationError,
    Process,
    QualityState,
    ReasoningError,
    Resource,
    Rigidity,
    Role,
    RulePolicy,
    SideEffectSpec,
    SignatureViolationError,
    SparqlQuery,
    TriplePattern,
    UpperQuadrant,
    build_drive_agent_turn_contract,
    build_execute_recipe_mode_contract,
    build_reply_channel_contract,
    build_state_mutation_contract,
    compute_content_hash,
    compute_desktop_content_id,
    decompose_agent_session,
    merge_graph_snapshots,
    ontological_action,
)


class TestUpperOntologyMetamodel:
    """Tests for the 4 orthogonal quadrants, OntoClean rigidity, and identity criteria."""

    def test_ontoclean_forbids_rigid_inheriting_from_anti_rigid(self) -> None:
        with pytest.raises(OntoCleanViolationError, match="Anti-Rigid"):

            class IllegalRigidUserUnderRole(Role):
                rigidity: ClassVar[Rigidity | None] = Rigidity.RIGID

    def test_quadrant_disjointness_forbids_cross_quadrant_inheritance(self) -> None:
        with pytest.raises(OntoCleanViolationError, match="disjoint"):

            class HybridContinuantOccurrent(Continuant, Occurrent):  # type: ignore[misc]
                pass

    def test_independent_continuant_identity_and_version_advance(self) -> None:
        kernel = Actor(uid="kernel:claude", actor_kind="AgentKernel")
        assert kernel.quadrant == UpperQuadrant.CONTINUANT
        assert kernel.rigidity == Rigidity.RIGID
        assert kernel.ontological_id() == "kernel:claude"
        assert kernel.version == 1

        v2 = kernel.advance_version(actor_kind="AgentKernelUpdated")
        assert v2.ontological_id() == "kernel:claude"
        assert v2.version == 2

        with pytest.raises(MutabilityViolationError, match="Cannot mutate global identity"):
            kernel.advance_version(uid="kernel:other")

        with pytest.raises(IdentityCriterionError):
            Actor(uid="   ", actor_kind="AgentKernel")

    def test_dependent_continuant_composite_identity_and_remove_context_guard(self) -> None:
        worker_role = Role(
            bearer_id="kernel:claude",
            context_id="session:123",
            dependent_type="SubtaskWorkerRole",
        )
        assert worker_role.rigidity == Rigidity.ANTI_RIGID
        assert worker_role.ontological_id() == "SubtaskWorkerRole:kernel:claude@session:123"

        with pytest.raises(IdentityCriterionError, match="bearer_id"):
            Role(bearer_id="", context_id="session:123", dependent_type="SubtaskWorkerRole")

        with pytest.raises(IdentityCriterionError, match="context_id"):
            Role(bearer_id="kernel:claude", context_id="", dependent_type="SubtaskWorkerRole")

    def test_process_state_machine_and_temporal_guards(self) -> None:
        now = datetime.now()
        proc = Process(
            process_uid="proc:turn-1",
            process_kind="HarnessTurnProcess",
            started_at=now,
        )
        assert proc.state == "pending"
        running = proc.transition_to("running")
        assert running.state == "running"
        assert running.ended_at is None

        done = running.transition_to("completed")
        assert done.state == "completed"
        assert done.ended_at is not None

        with pytest.raises(MutabilityViolationError, match="Illegal state transition"):
            done.transition_to("running")

        with pytest.raises(MutabilityViolationError, match="cannot precede"):
            Process(
                process_uid="proc:bad",
                process_kind="HarnessTurnProcess",
                started_at=now,
                ended_at=now - timedelta(seconds=5),
            )

    def test_event_causal_identity_determinism(self) -> None:
        ts = datetime(2026, 10, 21, 8, 0, 0)
        e1 = Event(
            event_type="SessionStepEvent",
            causal_source_id="session:abc",
            occurred_at=ts,
            payload={"step": 1, "tool": "run_command"},
        )
        e2 = Event(
            event_type="SessionStepEvent",
            causal_source_id="session:abc",
            occurred_at=ts,
            payload={"tool": "run_command", "step": 1},
        )
        assert e1.ontological_id() == e2.ontological_id()

    def test_normative_entity_versioned_immutability_and_window(self) -> None:
        t0 = datetime(2026, 10, 1, 0, 0, 0)
        t1 = datetime(2026, 10, 31, 0, 0, 0)
        policy = RulePolicy(
            norm_id="policy:team-pairing",
            semantic_version="1.0.0",
            rule_kind="TeamPairingSecurityPolicy",
            valid_from=t0,
            valid_until=t1,
        )
        assert policy.ontological_id() == "policy:team-pairing@1.0.0"
        assert policy.is_effective_at(datetime(2026, 10, 15, 0, 0, 0)) is True
        assert policy.is_effective_at(datetime(2026, 11, 1, 0, 0, 0)) is False

        with pytest.raises(MutabilityViolationError, match="distinct semantic_version"):
            policy.supersede("1.0.0")

        v2 = policy.supersede("2.0.0")
        assert v2.ontological_id() == "policy:team-pairing@2.0.0"
        assert policy.ontological_id() == "policy:team-pairing@1.0.0"

    def test_information_entity_content_hash(self) -> None:
        digest = compute_content_hash("# must-output-shape")
        doc = KnowledgeArtifact(
            artifact_uri="book://must-output-shape",
            content_hash=digest,
            artifact_kind="BookTopicDocument",
        )
        assert doc.quadrant == UpperQuadrant.INFORMATION
        assert doc.ontological_id().startswith("book://must-output-shape#")


class TestFirstClassRelationsAndGraph:
    """Tests for Domain/Range guardrails, inverse lookup, and algebraic axioms."""

    def test_domain_and_range_guardrails_and_inverse_queries(self) -> None:
        graph = OntologyGraph()
        kernel = Actor(uid="kernel:claude", actor_kind="AgentKernel")
        harness = Resource(uid="harness:tmux-0", resource_kind="AgentHarness")
        pa_role = Role(
            bearer_id="kernel:claude",
            context_id="session:main",
            dependent_type="PrimarySchedulerRole",
        )

        graph.link(kernel, "hosted_on_harness", harness)
        graph.link(kernel, "plays_role", pa_role)

        assert graph.query_targets("kernel:claude", "hosted_on_harness") == [harness]
        assert graph.query_targets("harness:tmux-0", "hosts_actor") == [kernel]
        assert graph.query_targets(pa_role.ontological_id(), "borne_by") == [kernel]

        with pytest.raises(DomainRangeViolationError, match="domain violation"):
            graph.link(pa_role, "plays_role", pa_role)

        with pytest.raises(DomainRangeViolationError, match="range violation"):
            graph.link(kernel, "plays_role", harness)

    def test_transitive_closure_and_cycle_rejection_on_module_dependencies(self) -> None:
        graph = OntologyGraph()
        mod_a = Resource(uid="recipe:board", resource_kind="RecipeModule")
        mod_b = Resource(uid="recipe:engine", resource_kind="RecipeModule")
        mod_c = Resource(uid="recipe:feed", resource_kind="RecipeModule")

        graph.link(mod_a, "depends_on_module", mod_b)
        graph.link(mod_b, "depends_on_module", mod_c)

        transitive_deps = graph.query_targets("recipe:board", "depends_on_module")
        assert transitive_deps == [mod_b, mod_c]

        dependents_of_c = graph.query_targets("recipe:feed", "depended_on_by")
        assert dependents_of_c == [mod_b, mod_a]

        with pytest.raises(AlgebraicAxiomViolationError, match="cycle"):
            graph.link(mod_c, "depends_on_module", mod_a)

        with pytest.raises(AlgebraicAxiomViolationError, match="irreflexive"):
            graph.link(mod_a, "depends_on_module", mod_a)

    def test_functional_relation_enforcement(self) -> None:
        graph = OntologyGraph()
        caller_role = Role(
            bearer_id="principal:anon",
            context_id="req:1",
            dependent_type="CallerZoneRole",
        )
        zone_public = QualityState(
            bearer_id=caller_role.ontological_id(),
            context_id="req:1",
            dependent_type="SecurityZoneState",
            value="public",
        )
        zone_local = QualityState(
            bearer_id=caller_role.ontological_id(),
            context_id="req:1",
            dependent_type="SecurityZoneState",
            value="local",
        )

        graph.link(caller_role, "exhibits_state", zone_public)
        with pytest.raises(AlgebraicAxiomViolationError, match="functional"):
            graph.link(caller_role, "exhibits_state", zone_local)

        graph.link(caller_role, "exhibits_state", zone_local, replace_functional=True)
        assert graph.query_targets(caller_role.ontological_id(), "exhibits_state") == [
            zone_local
        ]


class TestDefinedClassesAndKineticContracts:
    """Tests for axiom-driven DefinedClass and the 3 concentric rings of @ontological_action."""

    def test_defined_classes_dynamic_classification(self) -> None:
        graph = OntologyGraph()
        owner_role = Role(
            bearer_id="principal:local",
            context_id="req:10",
            dependent_type="CallerZoneRole",
        )
        local_state = QualityState(
            bearer_id=owner_role.ontological_id(),
            context_id="req:10",
            dependent_type="SecurityZoneState",
            value="local",
        )
        graph.link(owner_role, "exhibits_state", local_state)

        readonly_recipe = Resource(uid="recipe:viewer", resource_kind="RecipeModule")
        export_cap = Capability(
            bearer_id="recipe:viewer",
            context_id="mode:summary",
            dependent_type="export_readonly",
        )
        graph.link(readonly_recipe, "has_capability", export_cap)

        writable_recipe = Resource(uid="recipe:editor", resource_kind="RecipeModule")
        action_cap = Capability(
            bearer_id="recipe:editor",
            context_id="mode:save",
            dependent_type="action_triggerable",
        )
        graph.link(writable_recipe, "has_capability", action_cap)

        teammate_evt = Event(
            event_type="user",
            causal_source_id="session:pair",
            payload={"text": "【frago team】请帮我跑测试", "relay_verified": True},
        )
        graph.register_entity(teammate_evt)

        assert BUILTIN_DEFINED_CLASSES["TrustedOwnerRequest"].matches(owner_role, graph)
        assert BUILTIN_DEFINED_CLASSES["PublicExposableRecipe"].matches(
            readonly_recipe, graph
        )
        assert not BUILTIN_DEFINED_CLASSES["PublicExposableRecipe"].matches(
            writable_recipe, graph
        )
        assert BUILTIN_DEFINED_CLASSES["VerifiedTeammateInstruction"].matches(
            teammate_evt, graph
        )

    def test_concentric_action_contract_enforces_signature_pre_post_and_invariants(
        self,
    ) -> None:
        contract = OntologicalActionContract(
            norm_id="action:drive_agent_turn",
            signature=ActionSignature(
                parameters=("initiator", "target", "prompt_text"),
                initiator_types=(Role, Actor),
                target_types=(Resource,),
                input_types={"prompt_text": str},
                return_type=dict,
            ),
            preconditions=(
                ConditionCheck(
                    description="SubtaskWorkerRole is prohibited from spawning nested sessions.",
                    predicate=lambda args: not (
                        isinstance(args["initiator"], Role)
                        and args["initiator"].dependent_type == "SubtaskWorkerRole"
                    ),
                ),
            ),
            postconditions=(
                ConditionCheck(
                    description="Turn with empty text cannot report status 'ok'.",
                    predicate=lambda ctx: not (
                        ctx["result"].get("status") == "ok"
                        and not ctx["result"].get("text")
                    ),
                ),
            ),
            invariants=(
                ConditionCheck(
                    description="Target resource must be an AgentHarness.",
                    predicate=lambda args: args["target"].resource_kind == "AgentHarness",
                ),
            ),
            side_effects=SideEffectSpec(
                initiates_process="HarnessTurnProcess",
                emits_events=("SessionStepEvent",),
                produces_artifacts=("SessionTranscriptArtifact",),
            ),
        )

        @ontological_action(contract)
        def drive_turn(
            initiator: OntologyEntity,
            target: Resource,
            prompt_text: str,
            *,
            simulate_empty_ok: bool = False,
        ) -> dict[str, str]:
            if simulate_empty_ok:
                return {"status": "ok", "text": ""}
            return {"status": "ok", "text": f"ack:{prompt_text}"}

        pa_role = Role(
            bearer_id="kernel:claude",
            context_id="session:pa",
            dependent_type="PrimarySchedulerRole",
        )
        worker_role = Role(
            bearer_id="kernel:claude",
            context_id="session:worker",
            dependent_type="SubtaskWorkerRole",
        )
        harness = Resource(uid="harness:tmux-1", resource_kind="AgentHarness")
        wrong_resource = Resource(uid="slot:data", resource_kind="DataSlot")

        res = drive_turn(pa_role, harness, "run check")
        assert res == {"status": "ok", "text": "ack:run check"}

        with pytest.raises(SignatureViolationError, match="type mismatch"):
            drive_turn(pa_role, harness, 123)  # type: ignore[arg-type]

        with pytest.raises(PreconditionViolationError, match="SubtaskWorkerRole"):
            drive_turn(worker_role, harness, "nested spawn")

        with pytest.raises(InvariantViolationError, match="AgentHarness"):
            drive_turn(pa_role, wrong_resource, "run check")

        with pytest.raises(PostconditionViolationError, match="empty text"):
            drive_turn(pa_role, harness, "run check", simulate_empty_ok=True)


class TestOntologyIntrospector:
    """Tests for schema integrity validation and self-explanation queries."""

    def test_frago_json_passes_integrity_validation(self) -> None:
        introspector = OntologyIntrospector()
        assert introspector.validate_schema_integrity() == []
        assert set(introspector.list_quadrants()) == {
            "Continuant",
            "Occurrent",
            "NormativeEntity",
            "InformationEntity",
        }

    def test_introspector_queries_by_code_path_and_allowed_actions(self) -> None:
        introspector = OntologyIntrospector()

        driver_classes = introspector.find_classes_by_code_path("agent_driver")
        class_ids = {c["class_id"] for c in driver_classes}
        assert {
            "AgentKernel",
            "AgentHarness",
            "SubtaskWorkerRole",
            "HarnessProbeCapability",
            "HarnessTurnProcess",
        } <= class_ids

        pa_actions = introspector.get_allowed_actions_for(
            "PrimarySchedulerRole", "AgentHarness"
        )
        assert [a["action_id"] for a in pa_actions] == ["drive_agent_turn"]

        rels = introspector.explain_entity_relations("AgentKernel")
        outgoing_preds = {r["predicate"] for r in rels["outgoing"]}
        assert {"plays_role", "hosted_on_harness", "initiates"} <= outgoing_preds

    def test_schema_driven_three_mainlines_instantiation(self) -> None:
        introspector = OntologyIntrospector()
        graph = OntologyGraph()

        # 主线一：Agent 五体拆分（主体 + 执行底座 + 角色 + 会话过程 + 连接配置）
        kernel = introspector.instantiate_domain_entity("AgentKernel", uid="kernel:claude")
        harness = introspector.instantiate_domain_entity("AgentHarness", uid="harness:tmux-0")
        pa_role = introspector.instantiate_domain_entity(
            "PrimarySchedulerRole",
            bearer_id=kernel.ontological_id(),
            context_id="sess:100",
        )
        turn_proc = introspector.create_process(
            "HarnessTurnProcess",
            process_uid="turn:100-1",
            state="submitting",
        )
        graph.link(kernel, "hosted_on_harness", harness)
        graph.link(kernel, "plays_role", pa_role)
        graph.link(pa_role, "initiates", turn_proc)
        assert turn_proc.transition_to("streaming").state == "streaming"

        # 主线二：长生命周期资源（agent_os / VirtualDesktopStage）与运行态分离
        stage = introspector.instantiate_domain_entity(
            "VirtualDesktopStage",
            uid="stage:default#a1b2c3d4e5f6",
        )
        running_state = introspector.create_quality_state(
            "DesktopInstanceRuntimeState",
            bearer_id=stage.ontological_id(),
            context_id="boot:1",
            value="running",
        )
        stopped_state = introspector.create_quality_state(
            "DesktopInstanceRuntimeState",
            bearer_id=stage.ontological_id(),
            context_id="boot:1",
            value="stopped",
        )
        graph.link(stage, "exhibits_state", running_state)
        graph.link(stage, "exhibits_state", stopped_state, replace_functional=True)
        assert stage.ontological_id() == "stage:default#a1b2c3d4e5f6"
        assert graph.query_targets(stage.ontological_id(), "exhibits_state") == [stopped_state]

        with pytest.raises(MutabilityViolationError, match="allowed_values"):
            introspector.create_quality_state(
                "DesktopInstanceRuntimeState",
                bearer_id=stage.ontological_id(),
                context_id="boot:1",
                value="deleted",
            )

        # 主线三：CLI 作为动能层动作契约直接从 frago.json 构建
        desktop_contract = introspector.build_action_contract("control_desktop_stage")
        assert desktop_contract.norm_id == "control_desktop_stage"
        assert desktop_contract.signature.parameters == (
            "instance_id",
            "command_verb",
            "stage_payload",
        )
        assert desktop_contract.side_effects.mutates_targets == ("VirtualDesktopStage",)


class TestDomainClassRegistryAndThreeMainlinesRuntime:
    """Tests for the zero-intrusion DomainClassRegistry and three mainlines runtime."""

    def test_all_63_domain_classes_compile_and_enforce_bearer_types(self) -> None:
        reg = DomainClassRegistry()
        assert len(reg.classes) == 63

        # PrimarySchedulerRole requires bearer_type == AgentKernel
        pa_role = reg.create(
            "PrimarySchedulerRole",
            bearer_id="recipe:demo",
            context_id="sess:1",
        )
        recipe = reg.create("RecipeModule", uid="recipe:demo")
        graph = OntologyGraph()

        with pytest.raises(DomainRangeViolationError, match="bearer_type violation"):
            graph.link(recipe, "plays_role", pa_role)

    def test_mainline_1_agent_five_part_decomposition_and_drive_contract(self) -> None:
        pa_decomp = decompose_agent_session(
            agent_family="claude",
            session_id="sess-pa-1",
            role_class_id="PrimarySchedulerRole",
            profile_id="prof-1",
            probes=("ready_signal", "done_signal", "transcript_completion_probe"),
        )
        assert pa_decomp.kernel.ontological_id() == "kernel:claude"
        assert pa_decomp.harness.ontological_id() == "harness:tmux:sess-pa-1"
        assert pa_decomp.origin_state.value == "terminal"
        assert pa_decomp.profile is not None
        assert len(pa_decomp.probe_capabilities) == 3

        worker_decomp = decompose_agent_session(
            agent_family="coreagent",
            session_id="core_worker_1",
            role_class_id="SubtaskWorkerRole",
        )
        assert worker_decomp.harness.ontological_id() == "harness:subprocess:core_worker_1"
        assert worker_decomp.origin_state.value == "worker"

        contract = build_drive_agent_turn_contract()

        @ontological_action(contract)
        def run_turn(
            initiator: OntologyEntity,
            target: Resource,
            *,
            session_id: str,
            agent_kernel_id: str,
            prompt_text: str,
            profile_id: str | None = None,
            simulated_output: dict[str, str] | None = None,
        ) -> dict[str, str]:
            return simulated_output or {"status": "ok", "text": f"done:{prompt_text}"}

        ok_res = run_turn(
            pa_decomp.role,
            pa_decomp.harness,
            session_id="sess-pa-1",
            agent_kernel_id="claude",
            prompt_text="check ontology",
            profile_id="prof-1",
        )
        assert ok_res["status"] == "ok"

        # Worker is blocked from spawning nested agent turns
        with pytest.raises(PreconditionViolationError, match="SubtaskWorkerRole"):
            run_turn(
                worker_decomp.role,
                pa_decomp.harness,
                session_id="sess-nested",
                agent_kernel_id="claude",
                prompt_text="nested task",
            )

        # Secret key inlined in prompt_text is blocked by invariant
        with pytest.raises(InvariantViolationError, match="API secret keys"):
            run_turn(
                pa_decomp.role,
                pa_decomp.harness,
                session_id="sess-pa-1",
                agent_kernel_id="claude",
                prompt_text="ANTHROPIC_API_KEY=sk-ant-1234567890abcdef run",
            )

        # Auth wall masquerading as status=='ok' is blocked by postcondition
        with pytest.raises(PostconditionViolationError, match="_AUTH_WALL"):
            run_turn(
                pa_decomp.role,
                pa_decomp.harness,
                session_id="sess-pa-1",
                agent_kernel_id="claude",
                prompt_text="check ontology",
                simulated_output={
                    "status": "ok",
                    "text": "HTTP 400 InvalidSubscription: subscription expired",
                },
            )

    def test_mainline_2_desktop_stage_lifecycle_and_screen_ownership(self) -> None:
        runtime = DesktopStageLifecycleRuntime()
        snap = runtime.register_stage("t-a", boot_context_id="boot:1")
        expected_cid = compute_desktop_content_id("t-a")
        assert snap.content_id == expected_cid
        assert snap.stage.ontological_id() == f"desktop:t-a#{expected_cid}"

        kernel = DEFAULT_DOMAIN_REGISTRY.create("AgentKernel", uid="kernel:agy")

        # Valid layout update from matching content_id succeeds
        res = runtime.execute_stage_command(
            kernel,
            snap.stage,
            instance_id="t-a",
            command_verb="layout",
            stage_payload={"client_content_id": expected_cid},
        )
        assert res["status"] == "running"

        # Foreign browser tab from instance t-b reconnecting to same port is rejected
        foreign_cid = compute_desktop_content_id("t-b")
        with pytest.raises(PreconditionViolationError, match="content_id"):
            runtime.execute_stage_command(
                kernel,
                snap.stage,
                instance_id="t-a",
                command_verb="layout",
                stage_payload={"client_content_id": foreign_cid},
            )

        # Stopping broker transitions state to stopped while preserving stage resource
        stop_res = runtime.execute_stage_command(
            kernel,
            snap.stage,
            instance_id="t-a",
            command_verb="stop",
            stage_payload={"boot_context_id": "boot:1"},
        )
        assert stop_res["status"] == "stopped"
        assert runtime.graph.get_entity(snap.stage.ontological_id()) is snap.stage

    def test_mainline_3_cli_contracts_recipe_mode_and_boundary_governance(self) -> None:
        cli_reg = CliActionRegistry()
        cmd_spec = cli_reg.get_command_spec("frago.desktop.control")
        assert cmd_spec.mutates_state is True
        assert cmd_spec.underlying_action_id == "control_desktop_stage"
        cli_contract_entity = cli_reg.materialize_contract_entity("frago.desktop.control")
        assert cli_contract_entity.ontological_id() == "frago.desktop.control@1.0.0"

        # DirectExecutableSchedule defined class
        direct_cls = BUILTIN_DEFINED_CLASSES["DirectExecutableSchedule"]
        graph = OntologyGraph()
        sched_cmd = DEFAULT_DOMAIN_REGISTRY.create(
            "ScheduleRuleSpec",
            norm_id="command:echo-hi",
        )
        sched_nl = DEFAULT_DOMAIN_REGISTRY.create(
            "ScheduleRuleSpec",
            norm_id="nl:summarize-inbox",
        )
        graph.register_entity(sched_cmd)
        graph.register_entity(sched_nl)
        assert direct_cls.classify_all(graph) == [sched_cmd]

        # Recipe mode execution contract
        recipe = DEFAULT_DOMAIN_REGISTRY.create("RecipeModule", uid="recipe:analytics")
        assert isinstance(recipe, Resource)
        export_cap = DEFAULT_DOMAIN_REGISTRY.create(
            "RecipeModeCapability",
            bearer_id=recipe.ontological_id(),
            context_id="mode:summary:export_readonly",
        )
        graph.link(recipe, "has_capability", export_cap)

        visitor = DEFAULT_DOMAIN_REGISTRY.create(
            "CallerZoneRole",
            bearer_id="human:guest",
            context_id="req:guest-1",
        )
        zone_pub = DEFAULT_DOMAIN_REGISTRY.create(
            "SecurityZoneState",
            bearer_id=visitor.ontological_id(),
            context_id="req:guest-1",
            value="public",
        )
        graph.link(visitor, "exhibits_state", zone_pub)

        recipe_contract = build_execute_recipe_mode_contract(graph)

        @ontological_action(recipe_contract)
        def invoke_recipe(
            initiator: OntologyEntity,
            target: Resource,
            *,
            recipe_name: str,
            mode_name: str,
            params: dict[str, object],
            caller_identity: str,
        ) -> dict[str, str]:
            return {
                "status": "succeeded",
                "mode": mode_name,
                "data_slot_path": "~/.frago/app-state/analytics",
            }

        assert (
            invoke_recipe(
                visitor,
                recipe,
                recipe_name="analytics",
                mode_name="summary",
                params={},
                caller_identity="public",
            )["status"]
            == "succeeded"
        )

        with pytest.raises(PreconditionViolationError, match="capability"):
            invoke_recipe(
                visitor,
                recipe,
                recipe_name="analytics",
                mode_name="admin_wipe",
                params={},
                caller_identity="public",
            )

        # State mutation contract & teammate pairing security
        mut_contract = build_state_mutation_contract(graph)
        kernel = DEFAULT_DOMAIN_REGISTRY.create("AgentKernel", uid="kernel:agy")

        @ontological_action(mut_contract)
        def mutate_resource(
            initiator: OntologyEntity,
            target: OntologyEntity,
            *,
            operation_name: str,
            target_resource_id: str,
            authorization_source: OntologyEntity,
        ) -> dict[str, str]:
            return {"target_resource_id": target_resource_id, "op": operation_name}

        unapproved_teammate_evt = Event(
            event_type="user",
            causal_source_id="relay:MK7SF6KDN4",
            payload={"text": "【frago team】请帮我改配置", "relay_verified": True},
        )
        with pytest.raises(PreconditionViolationError, match="HumanDecisionReceipt"):
            mutate_resource(
                kernel,
                recipe,
                operation_name="update_config",
                target_resource_id=recipe.ontological_id(),
                authorization_source=unapproved_teammate_evt,
            )

        receipt = DEFAULT_DOMAIN_REGISTRY.create(
            "HumanDecisionReceipt",
            artifact_uri="answer://msg-1",
            content="【answer】A · 批准修改",
        )
        assert (
            mutate_resource(
                kernel,
                recipe,
                operation_name="update_config",
                target_resource_id=recipe.ontological_id(),
                authorization_source=receipt,
            )["target_resource_id"]
            == recipe.ontological_id()
        )

        # Reply channel contract
        feishu_channel = DEFAULT_DOMAIN_REGISTRY.create(
            "CommunicationChannel",
            uid="channel:feishu",
        )
        assert isinstance(feishu_channel, Resource)
        reply_contract = build_reply_channel_contract()

        @ontological_action(reply_contract)
        def reply_channel(
            initiator: OntologyEntity,
            target: Resource,
            *,
            channel_id: str,
            inbound_message_id: str,
            reply_payload: str,
        ) -> Event:
            return Event(
                event_type="outbound_reply_delivered",
                causal_source_id=target.ontological_id(),
                payload={"inbound_message_id": inbound_message_id, "text": reply_payload},
            )

        evt = reply_channel(
            kernel,
            feishu_channel,
            channel_id="feishu",
            inbound_message_id="feishu:msg-99",
            reply_payload="任务已完成",
        )
        assert evt.event_type == "outbound_reply_delivered"

        with pytest.raises(PreconditionViolationError, match="channel_id prefix"):
            reply_channel(
                kernel,
                feishu_channel,
                channel_id="feishu",
                inbound_message_id="slack:msg-99",
                reply_payload="发错渠道",
            )


class TestGraphSnapshotsAndCrossSessionReasoning:
    """Tests for JSONL graph snapshots, SPARQL-style property path queries, and causal lineage tracing."""

    def test_jsonl_graph_snapshot_roundtrip_and_cross_session_merge(self) -> None:
        pa_decomp = decompose_agent_session(
            agent_family="claude",
            session_id="sess-pa-10",
            role_class_id="PrimarySchedulerRole",
            profile_id="prof-main",
        )
        worker_decomp = decompose_agent_session(
            agent_family="coreagent",
            session_id="core_worker_20",
            role_class_id="SubtaskWorkerRole",
        )

        pa_jsonl = pa_decomp.graph.to_jsonl()
        worker_jsonl = worker_decomp.graph.to_jsonl()

        restored_pa = OntologyGraph.from_jsonl(pa_jsonl)
        assert len(restored_pa.entities()) == len(pa_decomp.graph.entities())
        assert len(restored_pa.facts()) == len(pa_decomp.graph.facts())

        merged = merge_graph_snapshots([pa_jsonl, worker_jsonl])
        assert merged.get_entity("kernel:claude") is not None
        assert merged.get_entity("kernel:coreagent") is not None
        assert merged.get_entity("session:sess-pa-10") is not None
        assert merged.get_entity("session:core_worker_20") is not None

        with pytest.raises(ReasoningError, match="Malformed JSONL"):
            OntologyGraph.from_jsonl("{not-valid-json")

    def test_sparql_property_paths_and_declarative_query_engine(self) -> None:
        decomp = decompose_agent_session(
            agent_family="agy",
            session_id="sess-agy-1",
            role_class_id="PrimarySchedulerRole",
        )
        graph = decomp.graph

        # Add transitive recipe module dependency chain: R_app -> R_mid -> R_base
        r_app = DEFAULT_DOMAIN_REGISTRY.create("RecipeModule", uid="recipe:app")
        r_mid = DEFAULT_DOMAIN_REGISTRY.create("RecipeModule", uid="recipe:mid")
        r_base = DEFAULT_DOMAIN_REGISTRY.create("RecipeModule", uid="recipe:base")
        graph.link(r_app, "depends_on_module", r_mid)
        graph.link(r_mid, "depends_on_module", r_base)

        # Add CallerZoneRole with local SecurityZoneState (TrustedOwnerRequest)
        caller_local = DEFAULT_DOMAIN_REGISTRY.create(
            "CallerZoneRole",
            bearer_id="human:owner",
            context_id="req:local-1",
        )
        state_local = DEFAULT_DOMAIN_REGISTRY.create(
            "SecurityZoneState",
            bearer_id=caller_local.ontological_id(),
            context_id="req:local-1",
            value="local",
        )
        graph.link(caller_local, "exhibits_state", state_local)

        reasoner = OntologyReasoner(graph)

        # Sequence path: AgentKernel -> plays_role -> Role -> initiates -> Process -> produces -> Artifact
        artifacts = reasoner.evaluate_path(
            "kernel:agy",
            "plays_role/initiates/produces",
        )
        assert artifacts == [decomp.transcript_artifact]

        # Transitive closure path `+` and reflexive-transitive `*`
        plus_deps = reasoner.evaluate_path("recipe:app", "depends_on_module+")
        star_deps = reasoner.evaluate_path("recipe:app", "depends_on_module*")
        assert [e.ontological_id() for e in plus_deps] == ["recipe:mid", "recipe:base"]
        assert [e.ontological_id() for e in star_deps] == [
            "recipe:app",
            "recipe:mid",
            "recipe:base",
        ]

        # Declarative multi-pattern SPARQL query with type & DefinedClass constraints
        rows = reasoner.query(
            SparqlQuery(
                where=(
                    TriplePattern("?kernel", "plays_role", "?role"),
                    TriplePattern("?role", "initiates", "?session"),
                    TriplePattern("?session", "produces", "?artifact"),
                ),
                select=("?kernel", "?role", "?artifact"),
                type_constraints={
                    "?kernel": "AgentKernel",
                    "?role": "PrimarySchedulerRole",
                    "?artifact": "SessionTranscriptArtifact",
                },
            )
        )
        assert len(rows) == 1
        assert rows[0]["?kernel"] == decomp.kernel
        assert rows[0]["?role"] == decomp.role
        assert rows[0]["?artifact"] == decomp.transcript_artifact

        # DefinedClass constraint query for TrustedOwnerRequest
        owner_rows = reasoner.query(
            SparqlQuery(
                where=(TriplePattern("?caller", "exhibits_state", "?zone"),),
                select=("?caller",),
                defined_class_constraints={"?caller": "TrustedOwnerRequest"},
            )
        )
        assert [r["?caller"] for r in owner_rows] == [caller_local]

    def test_multi_hop_causal_lineage_and_forward_impact_tracing(self) -> None:
        decomp = decompose_agent_session(
            agent_family="claude",
            session_id="sess-lineage-1",
            role_class_id="PrimarySchedulerRole",
        )
        graph = decomp.graph

        stop_policy = DEFAULT_DOMAIN_REGISTRY.create(
            "StopGatePolicy",
            norm_id="policy:stop-gate",
        )
        step_event = DEFAULT_DOMAIN_REGISTRY.create(
            "SessionStepEvent",
            event_type="tool_call",
            causal_source_id=decomp.session_process.ontological_id(),
            payload={"tool": "Read"},
        )
        data_slot = DEFAULT_DOMAIN_REGISTRY.create(
            "DataSlot",
            uid="slot:users/owner",
        )
        graph.link(decomp.session_process, "governed_by", stop_policy)
        graph.link(decomp.session_process, "emits", step_event)
        graph.link(decomp.session_process, "mutates", data_slot)

        reasoner = OntologyReasoner(graph)

        # Backward causal lineage from SessionTranscriptArtifact
        report = reasoner.trace_causal_lineage(
            decomp.transcript_artifact.ontological_id()
        )
        assert report.focal_entity == decomp.transcript_artifact
        assert decomp.kernel in report.root_actors
        assert decomp.role in report.active_roles
        assert decomp.harness in report.harnesses_and_resources
        assert stop_policy in report.governing_norms
        assert decomp.session_process in report.processes

        # Forward impact from AgentKernel
        impact_hops = reasoner.trace_forward_impact(decomp.kernel.ontological_id())
        impacted_targets = {h.target_id for h in impact_hops}
        assert {
            decomp.role.ontological_id(),
            decomp.session_process.ontological_id(),
            decomp.transcript_artifact.ontological_id(),
            step_event.ontological_id(),
            data_slot.ontological_id(),
        } <= impacted_targets
