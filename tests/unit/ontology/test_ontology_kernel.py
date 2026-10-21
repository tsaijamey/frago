"""Unit tests for src/frago/ontology/ (S1: metamodel, relations, contracts, introspection)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import pytest

from frago.ontology import (
    BUILTIN_DEFINED_CLASSES,
    ActionSignature,
    Actor,
    AlgebraicAxiomViolationError,
    Capability,
    ConditionCheck,
    Continuant,
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
    PostconditionViolationError,
    PreconditionViolationError,
    Process,
    QualityState,
    Resource,
    Rigidity,
    Role,
    RulePolicy,
    SideEffectSpec,
    SignatureViolationError,
    UpperQuadrant,
    compute_content_hash,
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

    def test_frago_ontology_json_passes_integrity_validation(self) -> None:
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
