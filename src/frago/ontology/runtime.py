"""Zero-intrusion operational ontology runtime for the three core modeling mainlines.

Implements the complete business ontology execution model entirely inside
`src/frago/ontology/` without modifying any existing business modules:

1. **Mainline 1 (`AgentFivePartDecomposition` & `AgentTurnRuntime`)**:
   Splits an AI Agent into 5 orthogonal ontological entities (`AgentKernel`,
   `AgentHarness`, context-bound `Role`, `AgentSessionProcess`/`HarnessTurnProcess`,
   and `ApiProfile`), connects them in an `OntologyGraph`, and enforces the
   `drive_agent_turn` kinetic contract (preventing nested worker spawning,
   raw credential leakage in command lines, and auth-wall/empty-output false-OKs).

2. **Mainline 2 (`DesktopStageLifecycleRuntime`)**:
   Separates the persistent identity of a long-lived resource (`VirtualDesktopStage`,
   whose `content_id` is derived deterministically from `instance_id` independent of
   broker port) from its volatile runtime state (`DesktopInstanceRuntimeState`:
   `running` | `stopped` | `stale`), and enforces the `control_desktop_stage`
   kinetic contract (rejecting foreign screen clients and preserving resource
   identity on stop).

3. **Mainline 3 (`CliActionRegistry` & `RecipeAndBoundaryRuntime`)**:
   Models `frago` CLI commands as kinetic action contracts (`CliCommandActionContract`)
   that initiate processes or mutate target resources, and enforces
   `execute_recipe_mode`, `execute_state_mutating_operation`, and
   `reply_to_inbound_channel` contracts.

Layer: pure ontology runtime (imports only `frago.ontology.*` and Python stdlib).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from frago.ontology.contracts import (
    BUILTIN_DEFINED_CLASSES,
    ConditionCheck,
    OntologicalActionContract,
    ontological_action,
)
from frago.ontology.introspection import OntologyIntrospector
from frago.ontology.metamodel import (
    Actor,
    Capability,
    Contract,
    Event,
    InformationEntity,
    OntologyEntity,
    Process,
    QualityState,
    Resource,
    Role,
)
from frago.ontology.registry import DEFAULT_DOMAIN_REGISTRY, DomainClassRegistry
from frago.ontology.relations import OntologyGraph

_AUTH_WALL_PATTERN = re.compile(
    r"invalid\s+api\s+key|api\s+key.{0,24}(?:invalid|expired|revoked)"
    r"|unauthorized|authentication\s+failed|not\s+logged\s+in|invalidsubscription"
    r"|credit\s+balance|insufficient\s+(?:balance|quota|credit)|quota\s+exceeded"
    r"|subscription.{0,24}(?:expired|invalid|not\s+valid)"
    r"|未授权|余额|欠费|订阅.{0,8}(?:过期|失效)",
    re.IGNORECASE,
)

_SECRET_LEAK_PATTERN = re.compile(
    r"sk-ant-[a-zA-Z0-9_-]{8,}|ANTHROPIC_API_KEY\s*=|OPENAI_API_KEY\s*=|PRIVATE_KEY",
    re.IGNORECASE,
)


# ============================================================================
# Mainline 1: Agent Five-Part Orthogonal Decomposition & Turn Contract Runtime
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class AgentFivePartDecomposition:
    """Orthogonal 5-part ontology decomposition of an AI Agent session."""

    kernel: Actor
    harness: Resource
    role: Role
    session_process: Process
    origin_state: QualityState
    transcript_artifact: InformationEntity
    profile: Resource | None
    probe_capabilities: tuple[Capability, ...]
    graph: OntologyGraph


def decompose_agent_session(
    *,
    agent_family: str,
    session_id: str,
    role_class_id: str = "PrimarySchedulerRole",
    session_state: str = "running",
    origin: str = "terminal",
    harness_kind: str | None = None,
    profile_id: str | None = None,
    transcript_uri: str | None = None,
    probes: tuple[str, ...] = ("ready_signal", "done_signal"),
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> AgentFivePartDecomposition:
    """Decompose an Agent into 5 orthogonal ontology entities and wire their graph relations."""
    g = graph if graph is not None else OntologyGraph()

    kernel = registry.create("AgentKernel", uid=f"kernel:{agent_family}")
    assert isinstance(kernel, Actor)

    resolved_harness_kind = harness_kind or (
        "subprocess" if agent_family == "coreagent" else "tmux"
    )
    harness = registry.create(
        "AgentHarness",
        uid=f"harness:{resolved_harness_kind}:{session_id}",
    )
    assert isinstance(harness, Resource)

    role = registry.create(
        role_class_id,
        bearer_id=kernel.ontological_id(),
        context_id=f"session:{session_id}",
    )
    assert isinstance(role, Role)

    session_process = registry.create(
        "AgentSessionProcess",
        process_uid=f"session:{session_id}",
        state=session_state,
    )
    assert isinstance(session_process, Process)

    origin_value = "worker" if role_class_id == "SubtaskWorkerRole" else origin
    origin_state = registry.create(
        "SessionOriginState",
        bearer_id=harness.ontological_id(),
        context_id=f"session:{session_id}",
        value=origin_value,
    )
    assert isinstance(origin_state, QualityState)

    resolved_uri = transcript_uri or f"~/.frago/sessions/{agent_family}/{session_id}/raw.jsonl"
    transcript_artifact = registry.create(
        "SessionTranscriptArtifact",
        artifact_uri=resolved_uri,
        content=f"{agent_family}:{session_id}:{session_state}",
    )
    assert isinstance(transcript_artifact, InformationEntity)

    profile: Resource | None = None
    if profile_id is not None:
        prof = registry.create("ApiProfile", uid=f"profile:{profile_id}")
        assert isinstance(prof, Resource)
        profile = prof
        g.register_entity(profile)

    probe_caps: list[Capability] = []
    for probe_name in probes:
        cap = registry.create(
            "HarnessProbeCapability",
            bearer_id=harness.ontological_id(),
            context_id=f"probe:{probe_name}",
        )
        assert isinstance(cap, Capability)
        probe_caps.append(cap)
        g.link(harness, "has_capability", cap)

    g.link(kernel, "hosted_on_harness", harness)
    g.link(kernel, "plays_role", role)
    g.link(role, "initiates", session_process)
    g.link(harness, "exhibits_state", origin_state)
    g.link(session_process, "produces", transcript_artifact)

    return AgentFivePartDecomposition(
        kernel=kernel,
        harness=harness,
        role=role,
        session_process=session_process,
        origin_state=origin_state,
        transcript_artifact=transcript_artifact,
        profile=profile,
        probe_capabilities=tuple(probe_caps),
        graph=g,
    )


def build_drive_agent_turn_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `drive_agent_turn` contract from `frago.json` with executable Ring 3 checks."""
    insp = introspector if introspector is not None else OntologyIntrospector()
    return insp.build_action_contract(
        "drive_agent_turn",
        preconditions=(
            ConditionCheck(
                description="Caller MUST NOT bear SubtaskWorkerRole (workers cannot spawn nested agent sessions).",
                predicate=lambda args: not (
                    isinstance(args.get("initiator"), Role)
                    and args["initiator"].dependent_type == "SubtaskWorkerRole"
                ),
            ),
            ConditionCheck(
                description="Target Resource MUST be an AgentHarness.",
                predicate=lambda args: (
                    isinstance(args.get("target"), Resource)
                    and args["target"].resource_kind == "AgentHarness"
                ),
            ),
            ConditionCheck(
                description="prompt_text MUST be non-empty.",
                predicate=lambda args: bool(str(args.get("prompt_text", "")).strip()),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="API secret keys MUST NOT be inlined into prompt_text.",
                predicate=lambda args: not bool(
                    _SECRET_LEAK_PATTERN.search(str(args.get("prompt_text", "")))
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Turn result MUST NOT report status=='ok' when text is empty or matches _AUTH_WALL.",
                predicate=lambda ctx: not (
                    isinstance(ctx.get("result"), Mapping)
                    and ctx["result"].get("status") == "ok"
                    and (
                        not str(ctx["result"].get("text", "")).strip()
                        or bool(_AUTH_WALL_PATTERN.search(str(ctx["result"].get("text", ""))))
                    )
                ),
            ),
        ),
    )


# ============================================================================
# Mainline 2: Long-Lived Resource (`VirtualDesktopStage`) vs. Runtime State
# ============================================================================


def compute_desktop_content_id(instance_id: str) -> str:
    """Compute the deterministic 12-char SHA-256 `content_id` solely from `instance_id`."""
    return hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, kw_only=True)
class DesktopStageSnapshot:
    """Ontological snapshot separating persistent `VirtualDesktopStage` from its runtime state."""

    instance_id: str
    content_id: str
    stage: Resource
    runtime_state: QualityState
    graph: OntologyGraph


class DesktopStageLifecycleRuntime:
    """Manages `VirtualDesktopStage` identity invariance and `DesktopInstanceRuntimeState` transitions."""

    def __init__(
        self,
        *,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
        introspector: OntologyIntrospector | None = None,
        graph: OntologyGraph | None = None,
    ) -> None:
        self._registry = registry
        self._introspector = (
            introspector if introspector is not None else OntologyIntrospector()
        )
        self._graph = graph if graph is not None else OntologyGraph()
        self._contract = self._build_control_contract()

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    @property
    def contract(self) -> OntologicalActionContract:
        return self._contract

    def register_stage(
        self,
        instance_id: str,
        *,
        boot_context_id: str = "boot:initial",
        initial_status: str = "running",
    ) -> DesktopStageSnapshot:
        """Create or update a `VirtualDesktopStage` resource and bind its functional runtime state."""
        content_id = compute_desktop_content_id(instance_id)
        stage_uid = f"desktop:{instance_id}#{content_id}"
        existing = self._graph.get_entity(stage_uid)
        if existing is not None and isinstance(existing, Resource):
            stage = existing
        else:
            stage_entity = self._registry.create("VirtualDesktopStage", uid=stage_uid)
            assert isinstance(stage_entity, Resource)
            stage = stage_entity

        state_entity = self._registry.create(
            "DesktopInstanceRuntimeState",
            bearer_id=stage.ontological_id(),
            context_id=boot_context_id,
            value=initial_status,
        )
        assert isinstance(state_entity, QualityState)
        self._graph.link(stage, "exhibits_state", state_entity, replace_functional=True)

        return DesktopStageSnapshot(
            instance_id=instance_id,
            content_id=content_id,
            stage=stage,
            runtime_state=state_entity,
            graph=self._graph,
        )

    def execute_stage_command(
        self,
        initiator: OntologyEntity,
        target: Resource,
        *,
        instance_id: str,
        command_verb: str,
        stage_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Execute a stage command guarded by the `control_desktop_stage` ontological contract."""

        @ontological_action(self._contract)
        def _invoke(
            initiator: OntologyEntity,
            target: Resource,
            instance_id: str,
            command_verb: str,
            stage_payload: Mapping[str, Any],
        ) -> dict[str, Any]:
            expected_cid = compute_desktop_content_id(instance_id)
            if command_verb == "stop":
                stopped_state = self._registry.create(
                    "DesktopInstanceRuntimeState",
                    bearer_id=target.ontological_id(),
                    context_id=str(stage_payload.get("boot_context_id", "boot:stop")),
                    value="stopped",
                )
                assert isinstance(stopped_state, QualityState)
                self._graph.link(
                    target,
                    "exhibits_state",
                    stopped_state,
                    replace_functional=True,
                )
                return {
                    "instance_id": instance_id,
                    "content_id": expected_cid,
                    "status": "stopped",
                    "stage_uid": target.ontological_id(),
                }

            return {
                "instance_id": instance_id,
                "content_id": expected_cid,
                "status": "running",
                "command_verb": command_verb,
                "stage_uid": target.ontological_id(),
                "initiator_uid": initiator.ontological_id(),
            }

        return _invoke(
            initiator,
            target,
            instance_id=instance_id,
            command_verb=command_verb,
            stage_payload=stage_payload,
        )

    def _build_control_contract(self) -> OntologicalActionContract:
        return self._introspector.build_action_contract(
            "control_desktop_stage",
            preconditions=(
                ConditionCheck(
                    description="Target Resource MUST be a VirtualDesktopStage whose UID embeds sha256(instance_id)[:12].",
                    predicate=lambda args: (
                        isinstance(args.get("target"), Resource)
                        and args["target"].resource_kind == "VirtualDesktopStage"
                        and args["target"].ontological_id().endswith(
                            f"#{compute_desktop_content_id(str(args.get('instance_id', '')))}"
                        )
                    ),
                ),
                ConditionCheck(
                    description="Client payload content_id (if present) MUST match target VirtualDesktopStage content_id.",
                    predicate=lambda args: (
                        "client_content_id" not in args.get("stage_payload", {})
                        or args["stage_payload"]["client_content_id"]
                        == compute_desktop_content_id(str(args.get("instance_id", "")))
                    ),
                ),
            ),
            invariants=(
                ConditionCheck(
                    description="VirtualDesktopStage remains registered in the OntologyGraph across stop/restart.",
                    predicate=lambda args: (
                        isinstance(args.get("target"), Resource)
                        and self._graph.get_entity(args["target"].ontological_id())
                        is not None
                    ),
                ),
            ),
            postconditions=(
                ConditionCheck(
                    description="When command_verb=='stop', VirtualDesktopStage exhibits_state=='stopped' without deleting stage.",
                    predicate=lambda ctx: (
                        ctx.get("command_verb") != "stop"
                        or (
                            isinstance(ctx.get("result"), Mapping)
                            and ctx["result"].get("status") == "stopped"
                            and any(
                                isinstance(s, QualityState) and s.value == "stopped"
                                for s in self._graph.query_targets(
                                    ctx["target"].ontological_id(), "exhibits_state"
                                )
                            )
                        )
                    ),
                ),
            ),
        )


# ============================================================================
# Mainline 3: CLI as Kinetic Action Contract & Cross-Boundary Governance
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class CliCommandSpec:
    """Ontological specification of a `frago` CLI command as a system-call contract."""

    command_path: str
    mutates_state: bool
    underlying_action_id: str | None
    initiator_domain: str
    target_range: str
    initiates_process_class: str | None
    description: str


STANDARD_CLI_COMMANDS: dict[str, CliCommandSpec] = {
    "frago.agent.run": CliCommandSpec(
        command_path="frago.agent.run",
        mutates_state=True,
        underlying_action_id="drive_agent_turn",
        initiator_domain="PrimarySchedulerRole | HumanPrincipal",
        target_range="AgentHarness",
        initiates_process_class="HarnessTurnProcess",
        description="拉起或驱动智能体执行单轮任务（系统调用契约 drive_agent_turn）。",
    ),
    "frago.desktop.control": CliCommandSpec(
        command_path="frago.desktop.control",
        mutates_state=True,
        underlying_action_id="control_desktop_stage",
        initiator_domain="AgentKernel | HumanPrincipal | PrimarySchedulerRole",
        target_range="VirtualDesktopStage",
        initiates_process_class=None,
        description="控制虚拟桌面舞台启停、布局或录屏（系统调用契约 control_desktop_stage）。",
    ),
    "frago.recipe.run": CliCommandSpec(
        command_path="frago.recipe.run",
        mutates_state=True,
        underlying_action_id="execute_recipe_mode",
        initiator_domain="CallerZoneRole | AgentKernel",
        target_range="RecipeModule",
        initiates_process_class="RecipeExecutionProcess",
        description="在受限隔离视图中运行指定配方模式（系统调用契约 execute_recipe_mode）。",
    ),
    "frago.reply": CliCommandSpec(
        command_path="frago.reply",
        mutates_state=True,
        underlying_action_id="reply_to_inbound_channel",
        initiator_domain="PrimarySchedulerRole | AgentKernel",
        target_range="CommunicationChannel",
        initiates_process_class="ChannelIngestionProcess",
        description="向外部进件渠道原路回传处理结果（系统调用契约 reply_to_inbound_channel）。",
    ),
    "frago.session.search": CliCommandSpec(
        command_path="frago.session.search",
        mutates_state=False,
        underlying_action_id=None,
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="SessionTranscriptArtifact",
        initiates_process_class=None,
        description="过程层只读召回查询，不改变任何独立资源状态。",
    ),
    "frago.def.find": CliCommandSpec(
        command_path="frago.def.find",
        mutates_state=False,
        underlying_action_id=None,
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="KnowledgeDomain",
        initiates_process_class=None,
        description="结论层知识域只读检索，不改变任何独立资源状态。",
    ),
    "frago.context.search": CliCommandSpec(
        command_path="frago.context.search",
        mutates_state=False,
        underlying_action_id=None,
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="ContextRecallIndex",
        initiates_process_class=None,
        description="产物层落点位置索引只读检索，不改变任何独立资源状态。",
    ),
}


class CliActionRegistry:
    """Registry that binds `frago` CLI commands to `CliCommandActionContract` and kinetic guards."""

    def __init__(
        self,
        *,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
        introspector: OntologyIntrospector | None = None,
    ) -> None:
        self._registry = registry
        self._introspector = (
            introspector if introspector is not None else OntologyIntrospector()
        )
        self._commands: dict[str, CliCommandSpec] = dict(STANDARD_CLI_COMMANDS)

    def list_commands(self) -> list[CliCommandSpec]:
        return list(self._commands.values())

    def get_command_spec(self, command_path: str) -> CliCommandSpec:
        if command_path not in self._commands:
            raise KeyError(f"Unregistered CLI command_path: '{command_path}'.")
        return self._commands[command_path]

    def materialize_contract_entity(self, command_path: str) -> Contract:
        """Instantiate a `CliCommandActionContract` normative entity for `command_path`."""
        spec = self.get_command_spec(command_path)
        entity = self._registry.create(
            "CliCommandActionContract",
            norm_id=spec.command_path,
        )
        assert isinstance(entity, Contract)
        return entity


def build_state_mutation_contract(
    graph: OntologyGraph,
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `execute_state_mutating_operation` contract enforcing authorization & team rules."""
    insp = introspector if introspector is not None else OntologyIntrospector()
    teammate_cls = BUILTIN_DEFINED_CLASSES["VerifiedTeammateInstruction"]

    def _has_valid_authorization(args: Mapping[str, Any]) -> bool:
        auth = args.get("authorization_source")
        target_id = str(args.get("target_resource_id", ""))
        op_name = str(args.get("operation_name", ""))
        if not target_id or not op_name:
            return False

        # Case 1: HumanDecisionReceipt InformationEntity whose uri/content authorizes operation
        if isinstance(auth, InformationEntity) and auth.artifact_kind == "HumanDecisionReceipt":
            return True

        # Case 2: Explicit user command Event in current turn (NOT an unapproved teammate request)
        if isinstance(auth, Event) and auth.event_type == "user":
            if teammate_cls.matches(auth, graph):
                return bool(auth.payload.get("owner_approved", False))
            return bool(auth.payload.get("explicit_command", False))

        return False

    return insp.build_action_contract(
        "execute_state_mutating_operation",
        preconditions=(
            ConditionCheck(
                description="State-mutating operation requires current-turn explicit command or HumanDecisionReceipt (and owner approval for VerifiedTeammateInstruction).",
                predicate=_has_valid_authorization,
            ),
        ),
        invariants=(
            ConditionCheck(
                description="Red-line operations (secret leak, unrecoverable deletion, hook bypass) are unconditionally forbidden.",
                predicate=lambda args: str(args.get("operation_name", ""))
                not in {"leak_secret", "unrecoverable_delete", "bypass_hook"},
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Mutation receipt must record the exact target_resource_id.",
                predicate=lambda ctx: (
                    isinstance(ctx.get("result"), Mapping)
                    and ctx["result"].get("target_resource_id")
                    == ctx.get("target_resource_id")
                ),
            ),
        ),
    )


def build_reply_channel_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `reply_to_inbound_channel` contract enforcing originating channel & secret redaction."""
    insp = introspector if introspector is not None else OntologyIntrospector()
    return insp.build_action_contract(
        "reply_to_inbound_channel",
        preconditions=(
            ConditionCheck(
                description="channel_id MUST match the target CommunicationChannel UID.",
                predicate=lambda args: (
                    isinstance(args.get("target"), Resource)
                    and args["target"].resource_kind == "CommunicationChannel"
                    and args["target"].ontological_id() == f"channel:{args.get('channel_id')}"
                ),
            ),
            ConditionCheck(
                description="inbound_message_id MUST carry the matching channel_id prefix.",
                predicate=lambda args: str(args.get("inbound_message_id", "")).startswith(
                    f"{args.get('channel_id')}:"
                ),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="reply_payload MUST NOT leak API keys or secrets.",
                predicate=lambda args: not bool(
                    _SECRET_LEAK_PATTERN.search(str(args.get("reply_payload", "")))
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Result MUST be a ChannelMessageEvent with event_type=='outbound_reply_delivered'.",
                predicate=lambda ctx: (
                    isinstance(ctx.get("result"), Event)
                    and ctx["result"].event_type == "outbound_reply_delivered"
                ),
            ),
        ),
    )


def build_execute_recipe_mode_contract(
    graph: OntologyGraph,
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `execute_recipe_mode` contract enforcing zone access, shares handshake, and command grants."""
    insp = introspector if introspector is not None else OntologyIntrospector()
    trusted_owner_cls = BUILTIN_DEFINED_CLASSES["TrustedOwnerRequest"]

    def _caller_permitted_for_mode(args: Mapping[str, Any]) -> bool:
        initiator = args.get("initiator")
        target = args.get("target")
        mode_name = str(args.get("mode_name", ""))
        if not isinstance(target, Resource) or target.resource_kind != "RecipeModule":
            return False

        # AgentKernel or TrustedOwnerRequest can run any mode
        if isinstance(initiator, Actor) and initiator.actor_kind == "AgentKernel":
            return True
        if isinstance(initiator, Role) and trusted_owner_cls.matches(initiator, graph):
            return True

        # Non-owner CallerZoneRole may only invoke modes bearing export_readonly or action_triggerable capability
        caps = graph.query_targets(target.ontological_id(), "has_capability")
        return any(
            isinstance(c, Capability)
            and c.context_id in {f"mode:{mode_name}:export_readonly", f"mode:{mode_name}:action_triggerable"}
            for c in caps
        )

    return insp.build_action_contract(
        "execute_recipe_mode",
        preconditions=(
            ConditionCheck(
                description="caller_identity MUST be non-empty.",
                predicate=lambda args: bool(str(args.get("caller_identity", "")).strip()),
            ),
            ConditionCheck(
                description="Caller MUST be owner/AgentKernel OR mode_name MUST expose @export/@action capability.",
                predicate=_caller_permitted_for_mode,
            ),
        ),
        invariants=(
            ConditionCheck(
                description="Target MUST be a RecipeModule resource.",
                predicate=lambda args: (
                    isinstance(args.get("target"), Resource)
                    and args["target"].resource_kind == "RecipeModule"
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Execution result MUST report status in {'succeeded', 'failed'} and stay within bound data slot.",
                predicate=lambda ctx: (
                    isinstance(ctx.get("result"), Mapping)
                    and ctx["result"].get("status") in {"succeeded", "failed"}
                    and not str(ctx["result"].get("data_slot_path", "")).startswith(
                        "~/.frago/recipes/"
                    )
                ),
            ),
        ),
    )
