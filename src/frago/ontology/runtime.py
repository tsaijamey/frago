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
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
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
    Specification,
)
from frago.ontology.registry import DEFAULT_DOMAIN_REGISTRY, DomainClassRegistry
from frago.ontology.relations import OntologyGraph

logger = logging.getLogger(__name__)

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


class SessionLifecycleState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class SessionOriginState(StrEnum):
    TERMINAL = "terminal"
    WEB = "web"
    WORKER = "worker"
    SCHEDULE = "schedule"
    CHANNEL = "channel"


SESSION_VALID_KERNELS: tuple[str, ...] = (
    "claude",
    "codex",
    "opencode",
    "agy",
    "coreagent",
)

SESSION_VALID_LIFECYCLE_STATES: tuple[str, ...] = tuple(s.value for s in SessionLifecycleState)
SESSION_VALID_ORIGINS: tuple[str, ...] = tuple(s.value for s in SessionOriginState)

#: ``AgentSessionProcess`` 在代码里的落点。``frago.json`` 把它登记为 ``Occurrent.Process``
#: 下的独立领域类，但**类实体只有 ``Process`` 一个**：注册表按 ``class_id`` 建档、按
#: ``process_kind`` 记住它具体是哪一类（``registry.create("AgentSessionProcess", ...)``
#: 建出来的节点 ``process_kind`` 就是它）。所以这里是有意的别名，不是漏建的类——
#: 判「这是不是一场会话」要用 ``process_kind`` 或 ``isinstance(x, Process)``，不要拿这个
#: 别名去做第二套类型判断。真要给会话过程加独立行为时，才在 metamodel 里建独立子类。
AgentSessionProcess = Process

SESSION_STATE_ALIASES: Mapping[str, str] = {
    "pending": "queued",
    "waiting": "queued",
    "in_progress": "running",
    "active": "running",
    "busy": "running",
    "needs_input": "awaiting_input",
    "awaiting": "awaiting_input",
    "done": "completed",
    "finished": "completed",
    "succeeded": "completed",
    "ok": "completed",
    "failed": "error",
    "fail": "error",
    "stopped": "cancelled",
    "aborted": "cancelled",
}

SESSION_ORIGIN_ALIASES: Mapping[str, str] = {
    "cli": "terminal",
    "term": "terminal",
    "ui": "web",
    "workbench": "web",
    "subagent": "worker",
    "subtask": "worker",
    "cron": "schedule",
    "timer": "schedule",
    "feishu": "channel",
    "slack": "channel",
    "email": "channel",
}


def normalize_session_lifecycle_state(raw_state: str | None) -> str:
    """Normalize raw session status string to canonical SessionLifecycleState enum."""
    if not raw_state:
        return "running"
    s = str(raw_state).strip().lower()
    if s in SESSION_VALID_LIFECYCLE_STATES:
        return s
    fallback = SESSION_STATE_ALIASES.get(s, "running")
    if s not in SESSION_STATE_ALIASES:
        # 认不出的状态不抛错（存量记录里存着历史写法，抛错会让整场会话读不出来），
        # 但也不能悄没声地当 running：这里留一条痕迹，便于排查「状态为什么不对」。
        logger.warning(
            "Unknown session lifecycle state %r normalized to %r (allowed: %s)",
            raw_state,
            fallback,
            sorted(SESSION_VALID_LIFECYCLE_STATES),
        )
    return fallback


def normalize_session_origin(raw_origin: str | None, *, is_worker: bool = False) -> str:
    """Normalize raw session source string to canonical SessionOriginState enum."""
    if is_worker:
        return "worker"
    if not raw_origin:
        return "terminal"
    s = str(raw_origin).strip().lower()
    if s in SESSION_VALID_ORIGINS:
        return s
    fallback = SESSION_ORIGIN_ALIASES.get(s, "terminal")
    if s not in SESSION_ORIGIN_ALIASES:
        # 同生命周期状态：非法出身不抛错，但把回落这件事记下来。出身判定直接决定
        # 会话树挂在哪一层，静默回落成 terminal 会让人查不出「它怎么挂到这儿了」。
        logger.warning(
            "Unknown session origin %r normalized to %r (allowed: %s)",
            raw_origin,
            fallback,
            sorted(SESSION_VALID_ORIGINS),
        )
    return fallback


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
    lifecycle_state: QualityState | None = None


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

    norm_state = normalize_session_lifecycle_state(session_state)
    session_process = registry.create(
        "AgentSessionProcess",
        process_uid=f"session:{session_id}",
        state=norm_state,
    )
    assert isinstance(session_process, Process)

    origin_value = (
        "worker"
        if role_class_id == "SubtaskWorkerRole"
        else normalize_session_origin(origin, is_worker=(role_class_id == "SubtaskWorkerRole"))
    )
    origin_state = registry.create(
        "SessionOriginState",
        bearer_id=harness.ontological_id(),
        context_id=f"session:{session_id}",
        value=origin_value,
    )
    assert isinstance(origin_state, QualityState)

    lifecycle_state: QualityState | None = None
    if "SessionLifecycleState" in registry.classes:
        lifecycle_state = registry.create(
            "SessionLifecycleState",
            bearer_id=session_process.ontological_id(),
            context_id=f"session:{session_id}",
            value=norm_state,
        )
        assert isinstance(lifecycle_state, QualityState)
        g.link(session_process, "exhibits_state", lifecycle_state, replace_functional=True)

    resolved_uri = transcript_uri or f"~/.frago/sessions/{agent_family}/{session_id}/raw.jsonl"
    transcript_artifact = registry.create(
        "SessionTranscriptArtifact",
        artifact_uri=resolved_uri,
        content=f"{agent_family}:{session_id}:{norm_state}",
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
        lifecycle_state=lifecycle_state,
    )


def _session_action_contract(
    action_id: str,
    *,
    introspector: OntologyIntrospector | None = None,
    preconditions: tuple[ConditionCheck, ...] = (),
    invariants: tuple[ConditionCheck, ...] = (),
    postconditions: tuple[ConditionCheck, ...] = (),
) -> OntologicalActionContract:
    """按 ``frago.json`` 的登记造一个会话动作契约，并把可执行的判据挂上去。

    会话五动作共用这一段：签名、参数表、副作用全从 ``frago.json`` 读（唯一真源），
    这里只补那些**能当场算出真假**的判据——纯文字描述的条款留在 JSON 里供人读，
    不重复写一遍成代码。
    """
    insp = introspector if introspector is not None else OntologyIntrospector()
    return insp.build_action_contract(
        action_id,
        preconditions=preconditions,
        invariants=invariants,
        postconditions=postconditions,
    )


def build_launch_agent_session_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `launch_agent_session` contract with executable Ring 3 checks.

    契约判据与函数体的业务校验**说同一句话**：契约先跑，所以它拒掉的那一条必须带上
    调用方认得出的说法（``Unknown agent kernel`` / ``Invalid session origin`` /
    ``SubtaskWorkerRole is strictly prohibited``）。两层各写一套文案的话，同一次违规
    会因为撞上哪一层而给出两种说法，排查时先要判「这是哪一层拒的」。
    """
    return _session_action_contract(
        "launch_agent_session",
        introspector=introspector,
        preconditions=(
            ConditionCheck(
                description="session_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("session_id", "")).strip()),
            ),
            ConditionCheck(
                description="Unknown agent kernel: agent_kernel_id MUST be one of the five supported kernels ('claude-code' is accepted as the legacy spelling of 'claude').",
                predicate=lambda args: (
                    # 与函数体读同一个表达式：``service.launch_agent_session`` 取的是
                    # ``agent_kernel_id or agent_kernel``（两个名字都认，前者优先）。
                    # 这里只读 ``agent_kernel_id`` 的话，一次合法的 ``agent_kernel=`` 调用
                    # 会在契约层被误拒——而函数体本来是接受的。判据与函数体说同一句话，
                    # 是这套契约存在的意义；两层各写一套，被拒的人还要先判是哪层拒的。
                    str(args.get("agent_kernel_id") or args.get("agent_kernel") or "")
                    .strip()
                    .lower()
                    in (*SESSION_VALID_KERNELS, "claude-code")
                ),
            ),
            ConditionCheck(
                description="Invalid session origin: origin MUST be one of {'terminal', 'web', 'worker', 'schedule', 'channel'} or a recognized alias.",
                predicate=lambda args: (
                    (raw := str(args.get("origin", "")).strip().lower()) in SESSION_VALID_ORIGINS
                    or raw in SESSION_ORIGIN_ALIASES
                    or raw == ""
                ),
            ),
            ConditionCheck(
                description="SubtaskWorkerRole is strictly prohibited from spawning nested agent sessions.",
                predicate=lambda args: not (
                    args.get("caller_is_worker") is True
                    or str(args.get("caller_role") or "") in {"worker", "SubtaskWorkerRole"}
                ),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="A worker-flagged launch MUST carry the 'worker' origin (a worker is a worker regardless of who dispatched it).",
                predicate=lambda args: not (
                    args.get("is_worker") is True
                    and normalize_session_origin(str(args.get("origin") or "")) != "worker"
                ),
            ),
        ),
    )


def build_record_session_step_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `record_session_step` contract with executable Ring 3 checks."""
    return _session_action_contract(
        "record_session_step",
        introspector=introspector,
        preconditions=(
            ConditionCheck(
                description="session_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("session_id", "")).strip()),
            ),
            ConditionCheck(
                description="step_type MUST be one of {'user', 'assistant', 'tool_call', 'tool_result', 'system'}.",
                predicate=lambda args: (
                    str(args.get("step_type", "")).strip()
                    in {"user", "assistant", "tool_call", "tool_result", "system"}
                ),
            ),
        ),
    )


def build_yield_awaiting_input_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `yield_awaiting_input` contract with executable Ring 3 checks."""
    return _session_action_contract(
        "yield_awaiting_input",
        introspector=introspector,
        preconditions=(
            ConditionCheck(
                description="session_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("session_id", "")).strip()),
            ),
            ConditionCheck(
                description="waiting_reason MUST be a non-empty string (why the session is waiting is the whole point of this action).",
                predicate=lambda args: bool(str(args.get("waiting_reason", "")).strip()),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Resulting lifecycle_state MUST be 'awaiting_input'.",
                predicate=lambda ctx: getattr(ctx.get("result"), "lifecycle_state", None)
                == "awaiting_input",
            ),
        ),
    )


def build_terminate_agent_session_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `terminate_agent_session` contract with executable Ring 3 checks."""
    return _session_action_contract(
        "terminate_agent_session",
        introspector=introspector,
        preconditions=(
            ConditionCheck(
                description="session_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("session_id", "")).strip()),
            ),
            ConditionCheck(
                description="terminal_status MUST be one of {'completed', 'error', 'cancelled'}.",
                predicate=lambda args: (
                    str(args.get("terminal_status", "")).strip().lower()
                    in {"completed", "error", "cancelled"}
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Resulting lifecycle_state MUST equal the requested terminal_status.",
                predicate=lambda ctx: getattr(ctx.get("result"), "lifecycle_state", None)
                == str(ctx.get("terminal_status", "")).strip().lower(),
            ),
        ),
    )


def build_adopt_existing_session_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `adopt_existing_session` contract with executable Ring 3 checks.

    这条动作的存在是为了给「frago 没开过、但确实在跑的会话」一个**说得出口的入口**：
    从前这类会话走的是 `ensure_managed_session` 这种绕过契约的补档路径，绕过的代价是
    本体里多出一批没人审计过来历的记录。现在补档走本体登记在册的动作，前置条件写死。

    **「这条会话在不在册」不在这里判。** 契约谓词是纯函数，只看得到入参；「在册与否」
    要读本体存储，那是函数体的事（`adopt_existing_session` 里查 store）。契约只要求
    调用方**明说自己查到的结果**（``already_registered``）并保证不带关系进来。
    """
    return _session_action_contract(
        "adopt_existing_session",
        introspector=introspector,
        preconditions=(
            ConditionCheck(
                description="session_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("session_id", "")).strip()),
            ),
            ConditionCheck(
                description="Invalid session origin: origin MUST normalize to one of {'terminal', 'web', 'worker', 'schedule', 'channel'}.",
                predicate=lambda args: (
                    normalize_session_origin(str(args.get("origin") or "")) in SESSION_VALID_ORIGINS
                ),
            ),
            ConditionCheck(
                description="Adoption NEVER invents a parent relation: no dispatch/branch/handoff may be supplied.",
                predicate=lambda args: args.get("relation_kind") in (None, ""),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="An adopted AgentSessionProcess NEVER enters a terminal state at adoption time.",
                predicate=lambda args: normalize_session_lifecycle_state(
                    str(args.get("initial_state") or "running")
                )
                not in {"completed", "error", "cancelled"},
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Result MUST be a persisted SessionOntologyRecord for the adopted session.",
                predicate=lambda ctx: (
                    ctx.get("result") is not None
                    and str(getattr(ctx.get("result"), "session_id", "")) == str(ctx.get("session_id"))
                ),
            ),
        ),
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
            ConditionCheck(
                description="Turn result with terminal status in {'timeout', 'error'} MUST NOT be accepted as a completed turn.",
                predicate=lambda ctx: not (
                    isinstance(ctx.get("result"), Mapping)
                    and ctx["result"].get("status") in {"timeout", "error"}
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
    "frago.browser.open": CliCommandSpec(
        command_path="frago.browser.open",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="BrowserTabGroup",
        initiates_process_class=None,
        description="在受控浏览器标签组内打开或操控页面（受单组 5 标签上限约束）。",
    ),
    "frago.view.open": CliCommandSpec(
        command_path="frago.view.open",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="ContentViewerSurface",
        initiates_process_class=None,
        description="按本地文件或配方产物双世界标识打开内容查看器视图。",
    ),
    "frago.apps.use": CliCommandSpec(
        command_path="frago.apps.use",
        mutates_state=True,
        underlying_action_id="execute_recipe_mode",
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="BuiltinDeliveryApp",
        initiates_process_class="RecipeExecutionProcess",
        description="调用内置交付应用直接产出成品工件。",
    ),
    "frago.daemon.manage": CliCommandSpec(
        command_path="frago.daemon.manage",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="HumanPrincipal | PrimarySchedulerRole",
        target_range="RecipeModule",
        initiates_process_class="SupervisedDaemonProcess",
        description="启停或巡检常驻守护配方进程。",
    ),
    "frago.market.install": CliCommandSpec(
        command_path="frago.market.install",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="HumanPrincipal | PrimarySchedulerRole",
        target_range="RecipeModule",
        initiates_process_class="MarketInstallProcess",
        description="从配方市场检索、校验并安装配方模块到本地环境。",
    ),
    "frago.schedule.trigger": CliCommandSpec(
        command_path="frago.schedule.trigger",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="PrimarySchedulerRole | HumanPrincipal",
        target_range="ScheduleRuleSpec",
        initiates_process_class="RecipeExecutionProcess",
        description="按定时规格触发命令直跑、配方直跑或主控自然语言调度。",
    ),
    "frago.remote.dispatch": CliCommandSpec(
        command_path="frago.remote.dispatch",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="PrimarySchedulerRole | HumanPrincipal",
        target_range="RemoteFragoNode",
        initiates_process_class="RemoteTaskDispatchProcess",
        description="向远端节点主控队列投递跨机任务书并追踪状态。",
    ),
    "frago.team.sync": CliCommandSpec(
        command_path="frago.team.sync",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="TeamPeerRole | AgentKernel",
        target_range="CommunicationChannel",
        initiates_process_class="TeamSyncProcess",
        description="通过结对中继通道增量推送会话轨迹并拉取队友指令。",
    ),
    "frago.cloud.sync": CliCommandSpec(
        command_path="frago.cloud.sync",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="HumanPrincipal | AgentKernel",
        target_range="MachineRuntimeConfig",
        initiates_process_class="HomeSyncProcess",
        description="执行家目录跨设备同步与冲突消解策略。",
    ),
    "frago.run.record": CliCommandSpec(
        command_path="frago.run.record",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="DataSlot",
        initiates_process_class="RunTransactionProcess",
        description="围绕业务事务聚类领域并写入运行日志。",
    ),
    "frago.todo.update": CliCommandSpec(
        command_path="frago.todo.update",
        mutates_state=True,
        underlying_action_id="execute_state_mutating_operation",
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="DataSlot",
        initiates_process_class=None,
        description="创建或更新跨会话待办交接单。",
    ),
    "frago.book.read": CliCommandSpec(
        command_path="frago.book.read",
        mutates_state=False,
        underlying_action_id=None,
        initiator_domain="AgentKernel | HumanPrincipal",
        target_range="BookTopicDocument",
        initiates_process_class=None,
        description="只读查阅内置行为准则与操作手册正文。",
    ),
    "frago.employee.invoke": CliCommandSpec(
        command_path="frago.employee.invoke",
        mutates_state=True,
        underlying_action_id="invoke_domain_employee",
        initiator_domain="HumanPrincipal | PrimarySchedulerRole | DomainEmployeeRole | RecipeModule",
        target_range="EmployeePostResource | DomainEmployeeRole",
        initiates_process_class="AgentSessionProcess",
        description="按岗位工牌调用领域固定员工回答或执行领地内任务（系统调用契约 invoke_domain_employee）。",
    ),
    "frago.employee.govern": CliCommandSpec(
        command_path="frago.employee.govern",
        mutates_state=True,
        underlying_action_id="govern_employee_domain_assets",
        initiator_domain="DomainEmployeeRole",
        target_range="KnowledgeDomain | RecipeModule | DataSlot | ScheduleRuleSpec",
        initiates_process_class="RecipeExecutionProcess",
        description="由领域固定员工维护所属领地内的知识域、配方、数据槽位与定时任务（系统调用契约 govern_employee_domain_assets）。",
    ),
    "frago.employee.discover": CliCommandSpec(
        command_path="frago.employee.discover",
        mutates_state=False,
        underlying_action_id=None,
        initiator_domain="HumanPrincipal | PrimarySchedulerRole | DomainEmployeeRole | RecipeModule | AgentKernel",
        target_range="EmployeePostResource",
        initiates_process_class=None,
        description="通过图谱反查哪位固定员工负责指定知识域、配方或数据槽位，只读不改变状态。",
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


# ============================================================================
# Schedule Dispatch Runtime & Team Pairing Policy Runtime
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class ScheduleDispatchDecision:
    """Routing decision for a `ScheduleRuleSpec` under `DirectExecutableSchedule` axioms."""

    schedule_spec: Specification
    zero_token_direct: bool
    route: str
    trigger_event: Event


class ScheduleDispatchRuntime:
    """Evaluates `ScheduleRuleSpec` via `DirectExecutableSchedule` to route zero-token vs. PA turns."""

    def __init__(
        self,
        *,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
        graph: OntologyGraph | None = None,
    ) -> None:
        self._registry = registry
        self._graph = graph if graph is not None else OntologyGraph()
        self._direct_cls = BUILTIN_DEFINED_CLASSES["DirectExecutableSchedule"]

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    def dispatch(
        self,
        schedule_spec: Specification,
        *,
        trigger_type: str = "cron_fired",
    ) -> ScheduleDispatchDecision:
        """Classify `schedule_spec` and emit an immutable `ScheduledTriggerEvent`."""
        self._graph.register_entity(schedule_spec)
        is_direct = self._direct_cls.matches(schedule_spec, self._graph)
        route = "direct_executor" if is_direct else "primary_scheduler"
        evt = self._registry.create(
            "ScheduledTriggerEvent",
            event_type=trigger_type,
            causal_source_id=schedule_spec.ontological_id(),
            payload={
                "route": route,
                "zero_token_direct": is_direct,
            },
        )
        assert isinstance(evt, Event)
        self._graph.register_entity(evt)
        return ScheduleDispatchDecision(
            schedule_spec=schedule_spec,
            zero_token_direct=is_direct,
            route=route,
            trigger_event=evt,
        )


class TeamPolicyRuntime:
    """Evaluates incoming `SessionStepEvent` instructions under `VerifiedTeammateInstruction` and 3-tier policy."""

    RED_LINE_INTENTS: frozenset[str] = frozenset(
        {"leak_secret", "unrecoverable_delete", "bypass_hook"}
    )

    def __init__(self, graph: OntologyGraph) -> None:
        self._graph = graph
        self._teammate_cls = BUILTIN_DEFINED_CLASSES["VerifiedTeammateInstruction"]

    def evaluate_instruction(
        self,
        step_event: Event,
        *,
        intent_tier: str,
        read_only_policy: str = "do",
        change_policy: str = "ask",
    ) -> str:
        """Return `'do' | 'ask' | 'refuse'` for `step_event` based on `intent_tier` and team policy."""
        if intent_tier in self.RED_LINE_INTENTS or intent_tier == "red_line":
            return "refuse"

        is_teammate = self._teammate_cls.matches(step_event, self._graph)
        if not is_teammate:
            text = str(step_event.payload.get("text", ""))
            if text.startswith("【frago team】"):
                # Unverified spoofed teammate prefix MUST be unconditionally refused
                return "refuse"
            return "do" if intent_tier == "read_only" else "ask"

        if intent_tier == "read_only":
            return read_only_policy if read_only_policy in {"do", "ask"} else "ask"
        if intent_tier == "change":
            return change_policy if change_policy in {"do", "ask", "refuse"} else "ask"
        return "refuse"


# ============================================================================
# Mainline 4: Domain Employee Ontology Runtime (`invoke` & `govern` contracts)
# ============================================================================


def _find_active_employee_role_in_graph(
    graph: OntologyGraph,
    member_post_id: str,
) -> Role | None:
    """Return the active `DomainEmployeeRole` bound to `post:<member_post_id>` if linked to an `AgentKernel`."""
    post_uid = f"post:{member_post_id}"
    if graph.get_entity(post_uid) is None:
        return None
    for entity in graph.entities():
        if (
            isinstance(entity, Role)
            and entity.dependent_type == "DomainEmployeeRole"
            and entity.context_id == post_uid
        ):
            kernels = graph.query_sources(entity.ontological_id(), "plays_role")
            if any(isinstance(k, Actor) for k in kernels):
                return entity
    return None


def _is_asset_in_employee_territory(
    graph: OntologyGraph,
    member_post_id: str,
    asset_id: str,
) -> bool:
    """Return True if `asset_id` is governed by `post:<member_post_id>` or its `DomainEmployeeRole`."""
    post_uid = f"post:{member_post_id}"
    governed_ids = {
        e.ontological_id() for e in graph.query_targets(post_uid, "depends_on_module")
    }
    role = _find_active_employee_role_in_graph(graph, member_post_id)
    if role is not None:
        governed_ids.update(
            e.ontological_id()
            for e in graph.query_targets(role.ontological_id(), "governed_by")
        )
    if asset_id in governed_ids:
        return True
    # Also accept bare name if it resolves to domain:<id>, recipe:<id>, slot:<id>, or schedule:*:<id>@1.0.0
    for candidate in (
        f"domain:{asset_id}",
        f"recipe:{asset_id}",
        f"slot:{asset_id}",
        f"{asset_id}@1.0.0",
        f"schedule:{asset_id}@1.0.0",
        f"agent_prompt:{asset_id}@1.0.0",
        f"command:{asset_id}@1.0.0",
    ):
        if candidate in governed_ids:
            return True
    return False


def _is_valid_human_receipt(entity: object) -> bool:
    return (
        isinstance(entity, InformationEntity)
        and entity.artifact_kind == "HumanDecisionReceipt"
    )


def build_invoke_domain_employee_contract(
    graph: OntologyGraph,
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `invoke_domain_employee` kinetic contract with Ring 3 territory & role checks."""
    insp = introspector if introspector is not None else OntologyIntrospector()
    return insp.build_action_contract(
        "invoke_domain_employee",
        preconditions=(
            ConditionCheck(
                description="Target EmployeePostResource MUST exist and bind an active AgentKernel via DomainEmployeeRole.",
                predicate=lambda args: (
                    _find_active_employee_role_in_graph(
                        graph, str(args.get("member_post_id", ""))
                    )
                    is not None
                ),
            ),
            ConditionCheck(
                description="query_or_task MUST be non-empty and fall within the KnowledgeDomain or RecipeModule scope declared by EmployeePostResource.",
                predicate=lambda args: (
                    bool(str(args.get("query_or_task", "")).strip())
                    and (
                        args.get("requested_asset_id") is None
                        or _is_asset_in_employee_territory(
                            graph,
                            str(args.get("member_post_id", "")),
                            str(args.get("requested_asset_id", "")),
                        )
                    )
                ),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="DomainEmployeeRole NEVER impersonates HumanPrincipal to issue HumanDecisionReceipt.",
                predicate=lambda args: (
                    not str(args.get("query_or_task", "")).strip().startswith("【answer】")
                    and not bool(args.get("forged_human_receipt", False))
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Returns structured domain answer or execution receipt without polluting caller session context.",
                predicate=lambda ctx: (
                    isinstance(ctx.get("result"), Mapping)
                    and ctx["result"].get("status") in {"ok", "needs_input", "delegated"}
                    and bool(ctx["result"].get("session_id"))
                    and ctx["result"].get("caller_context_id")
                    == ctx.get("caller_context_id")
                    and not bool(ctx["result"].get("issued_human_decision_receipt", False))
                ),
            ),
        ),
    )


def build_govern_employee_domain_assets_contract(
    graph: OntologyGraph,
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `govern_employee_domain_assets` kinetic contract with territory boundary checks."""
    insp = introspector if introspector is not None else OntologyIntrospector()
    allowed_ops = frozenset(
        {
            "refresh_data",
            "curate_knowledge",
            "update_recipe",
            "self_alarm",
            "irreversible_delete",
        }
    )
    return insp.build_action_contract(
        "govern_employee_domain_assets",
        preconditions=(
            ConditionCheck(
                description="Initiator MUST be the active DomainEmployeeRole bound to EmployeePostResource(member_post_id).",
                predicate=lambda args: (
                    isinstance(args.get("initiator"), Role)
                    and args["initiator"].dependent_type == "DomainEmployeeRole"
                    and args["initiator"].context_id
                    == f"post:{args.get('member_post_id', '')}"
                ),
            ),
            ConditionCheck(
                description="target_asset_id MUST be registered inside the territory scope of EmployeePostResource(member_post_id), or authorized by a HumanDecisionReceipt.",
                predicate=lambda args: (
                    _is_asset_in_employee_territory(
                        graph,
                        str(args.get("member_post_id", "")),
                        str(args.get("target_asset_id", "")),
                    )
                    or _is_valid_human_receipt(args.get("authorization_source"))
                ),
            ),
            ConditionCheck(
                description="If governance_op performs irreversible_delete, a HumanDecisionReceipt from HumanPrincipal is required.",
                predicate=lambda args: (
                    str(args.get("governance_op", "")) != "irreversible_delete"
                    or _is_valid_human_receipt(args.get("authorization_source"))
                ),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="Autonomous territory maintenance op MUST be recognized and never inline secret keys.",
                predicate=lambda args: (
                    str(args.get("governance_op", "")) in allowed_ops
                    and not bool(
                        _SECRET_LEAK_PATTERN.search(str(args.get("target_asset_id", "")))
                    )
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="Target KnowledgeDomain, RecipeModule, DataSlot, or ScheduleRuleSpec is updated with status=='governed'.",
                predicate=lambda ctx: (
                    isinstance(ctx.get("result"), Mapping)
                    and ctx["result"].get("status") == "governed"
                    and ctx["result"].get("member_post_id") == ctx.get("member_post_id")
                    and ctx["result"].get("target_asset_id") == ctx.get("target_asset_id")
                ),
            ),
        ),
    )


class DomainEmployeeRuntime:
    """Ontology runtime for discovering, invoking, and governing `EmployeePostResource` & `DomainEmployeeRole`."""

    def __init__(
        self,
        *,
        graph: OntologyGraph | None = None,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
        introspector: OntologyIntrospector | None = None,
    ) -> None:
        self._graph = graph if graph is not None else OntologyGraph()
        self._registry = registry
        self._introspector = (
            introspector if introspector is not None else OntologyIntrospector()
        )
        self._invoke_contract = build_invoke_domain_employee_contract(
            self._graph, self._introspector
        )
        self._govern_contract = build_govern_employee_domain_assets_contract(
            self._graph, self._introspector
        )

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    @property
    def invoke_contract(self) -> OntologicalActionContract:
        return self._invoke_contract

    @property
    def govern_contract(self) -> OntologicalActionContract:
        return self._govern_contract

    def find_employee_role(self, member_post_id: str) -> Role | None:
        """Return the active `DomainEmployeeRole` bound to `post:<member_post_id>`."""
        return _find_active_employee_role_in_graph(self._graph, member_post_id)

    def discover_posts_for_asset(self, asset_id: str) -> list[Resource]:
        """Discover all `EmployeePostResource` nodes in the graph whose territory includes `asset_id`."""
        matched: list[Resource] = []
        for entity in self._graph.entities():
            if (
                isinstance(entity, Resource)
                and entity.resource_kind == "EmployeePostResource"
            ):
                uid = entity.ontological_id()
                post_id = uid.split("post:", 1)[1] if uid.startswith("post:") else uid
                if _is_asset_in_employee_territory(self._graph, post_id, asset_id):
                    matched.append(entity)
        return matched

    def invoke_employee(
        self,
        initiator: OntologyEntity,
        *,
        member_post_id: str,
        query_or_task: str,
        caller_context_id: str,
        requested_asset_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a domain employee under the `invoke_domain_employee` kinetic contract."""
        post_uid = f"post:{member_post_id}"
        existing_entity = self._graph.get_entity(post_uid)
        if existing_entity is not None and isinstance(existing_entity, Resource):
            target_entity: Resource = existing_entity
        else:
            # Unregistered placeholder so Ring 2 passes and Ring 3 precondition reports missing post
            created_entity = self._registry.create("EmployeePostResource", uid=post_uid)
            assert isinstance(created_entity, Resource)
            target_entity = created_entity

        @ontological_action(self._invoke_contract)
        def _run_invoke(
            initiator: OntologyEntity,
            target: Resource,
            *,
            member_post_id: str,
            query_or_task: str,
            caller_context_id: str,
            requested_asset_id: str | None = None,
        ) -> dict[str, Any]:
            role = _find_active_employee_role_in_graph(self._graph, member_post_id)
            assert role is not None
            resolved_session_id = session_id or f"emp-{member_post_id}-{hashlib.sha256(f'{caller_context_id}:{query_or_task}'.encode()).hexdigest()[:8]}"
            sess_proc = self._registry.create(
                "AgentSessionProcess",
                process_uid=f"session:{resolved_session_id}",
                state="running",
            )
            assert isinstance(sess_proc, Process)
            transcript = self._registry.create(
                "SessionTranscriptArtifact",
                artifact_uri=f"~/.frago/sessions/employee/{resolved_session_id}/raw.jsonl",
                content=f"{member_post_id}:{caller_context_id}:{query_or_task}",
            )
            assert isinstance(transcript, InformationEntity)
            step_evt = self._registry.create(
                "SessionStepEvent",
                event_type="employee_invocation",
                causal_source_id=sess_proc.ontological_id(),
                payload={
                    "member_post_id": member_post_id,
                    "caller_context_id": caller_context_id,
                    "query_or_task": query_or_task,
                },
            )
            assert isinstance(step_evt, Event)
            self._graph.link(role, "initiates", sess_proc)
            self._graph.link(sess_proc, "produces", transcript)
            self._graph.link(sess_proc, "emits", step_evt)

            governed_targets = [
                e.ontological_id()
                for e in self._graph.query_targets(target.ontological_id(), "depends_on_module")
            ]
            return {
                "status": "ok",
                "initiator_id": initiator.ontological_id(),
                "member_post_id": member_post_id,
                "post_id": target.ontological_id(),
                "role_id": role.ontological_id(),
                "kernel_id": role.bearer_id,
                "session_id": resolved_session_id,
                "caller_context_id": caller_context_id,
                "requested_asset_id": requested_asset_id,
                "governed_assets": governed_targets,
                "answer_summary": f"[{member_post_id}] processed task under {role.bearer_id}: {query_or_task}",
            }

        return _run_invoke(
            initiator,
            target_entity,
            member_post_id=member_post_id,
            query_or_task=query_or_task,
            caller_context_id=caller_context_id,
            requested_asset_id=requested_asset_id,
        )

    def govern_asset(
        self,
        initiator: OntologyEntity,
        target: OntologyEntity,
        *,
        member_post_id: str,
        asset_kind: str,
        target_asset_id: str,
        governance_op: str,
        authorization_source: OntologyEntity | None = None,
    ) -> dict[str, Any]:
        """Execute territory asset maintenance under the `govern_employee_domain_assets` kinetic contract."""

        @ontological_action(self._govern_contract)
        def _run_govern(
            initiator: OntologyEntity,
            target: OntologyEntity,
            *,
            member_post_id: str,
            asset_kind: str,
            target_asset_id: str,
            governance_op: str,
            authorization_source: OntologyEntity | None = None,
        ) -> dict[str, Any]:
            proc_uid = f"gov:{member_post_id}:{governance_op}:{hashlib.sha256(target_asset_id.encode()).hexdigest()[:8]}"
            gov_proc = self._registry.create(
                "RecipeExecutionProcess",
                process_uid=proc_uid,
                state="succeeded",
            )
            assert isinstance(gov_proc, Process)
            if isinstance(initiator, Role):
                self._graph.link(initiator, "initiates", gov_proc)
            if isinstance(target, Resource):
                self._graph.link(gov_proc, "mutates", target)
            if asset_kind == "knowledge_domain":
                entry = self._registry.create(
                    "DefKnowledgeEntry",
                    artifact_uri=f"def://{target_asset_id}/{governance_op}",
                    content=f"{member_post_id}:{governance_op}:{target_asset_id}",
                )
                assert isinstance(entry, InformationEntity)
                self._graph.link(gov_proc, "produces", entry)
            return {
                "status": "governed",
                "member_post_id": member_post_id,
                "asset_kind": asset_kind,
                "target_asset_id": target_asset_id,
                "governance_op": governance_op,
                "process_id": gov_proc.ontological_id(),
                "authorized_by": (
                    authorization_source.ontological_id()
                    if authorization_source is not None
                    else None
                ),
            }

        return _run_govern(
            initiator,
            target,
            member_post_id=member_post_id,
            asset_kind=asset_kind,
            target_asset_id=target_asset_id,
            governance_op=governance_op,
            authorization_source=authorization_source,
        )


# ============================================================================
# Mainline 5: Async Callback Delivery Action Contracts (Gate 3)
# ============================================================================


def _persisted_delivery_state(args: Mapping[str, Any]) -> str | None:
    """取调用方注入的持久态（``prior_delivery_state``），拿不到就回 None。

    这一格从前是本层自己去 ``~/.frago/sessions/async_dispatches/<job_id>.json`` 读盘
    拼出来的：落点一变，本体层与业务层的两份路径表达就会不同步，而本体层本该只认入参、
    不认业务落点。现在由调用方（``session/async_dispatch.py``）先 ``load_dispatch_job``
    读出持久态再注入。**调用方不注入 = 这一格判据不成立**，动作被拒；绝不回退到读盘，
    否则「本体层零侵入」这条隔离纪律就名存实亡。
    """
    raw = args.get("prior_delivery_state")
    if raw is None:
        return None
    state = str(raw).strip()
    return state or None


def build_record_callback_delivery_outcome_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `record_callback_delivery_outcome` contract with Ring 3 state transition checks."""
    from frago.ontology.projectors import (
        CALLBACK_DELIVERY_STATES,
        is_legal_callback_delivery_transition,
    )

    insp = introspector if introspector is not None else OntologyIntrospector()
    return insp.build_action_contract(
        "record_callback_delivery_outcome",
        preconditions=(
            ConditionCheck(
                description="job_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("job_id", "")).strip()),
            ),
            ConditionCheck(
                description="from_state and to_state MUST both be CallbackDeliveryState allowed values.",
                predicate=lambda args: (
                    args.get("from_state") in CALLBACK_DELIVERY_STATES
                    and args.get("to_state") in CALLBACK_DELIVERY_STATES
                ),
            ),
            ConditionCheck(
                description="(from_state, to_state) MUST be a legal edge: queued→delivering, delivering→delivered, delivering→queued, delivering→failed, queued→failed.",
                predicate=lambda args: is_legal_callback_delivery_transition(
                    str(args.get("from_state", "")), str(args.get("to_state", ""))
                ),
            ),
            ConditionCheck(
                description="Caller MUST inject prior_delivery_state read from the persisted dispatch job; it MUST match from_state and not be terminal (delivered/failed).",
                predicate=lambda args: (
                    (state := _persisted_delivery_state(args)) is not None
                    and state not in ("delivered", "failed")
                    and state == args.get("from_state")
                ),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="Once delivered, a CallbackDeliveryProcess NEVER transitions out.",
                predicate=lambda args: str(args.get("from_state", "")) != "delivered",
            ),
            ConditionCheck(
                description="A CallbackDeliveryProcess NEVER reaches delivered without passing through delivering.",
                predicate=lambda args: not (
                    str(args.get("to_state", "")) == "delivered"
                    and str(args.get("from_state", "")) != "delivering"
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="CallbackDeliveryProcess exhibits CallbackDeliveryState == to_state.",
                predicate=lambda ctx: ctx.get("result") == ctx.get("to_state"),
            ),
        ),
    )


def build_finalize_dispatch_job_contract(
    introspector: OntologyIntrospector | None = None,
) -> OntologicalActionContract:
    """Build the `finalize_dispatch_job` contract enforcing worker/delivery subordination rules."""
    from frago.ontology.projectors import CALLBACK_DELIVERY_STATES

    insp = introspector if introspector is not None else OntologyIntrospector()
    return insp.build_action_contract(
        "finalize_dispatch_job",
        preconditions=(
            ConditionCheck(
                description="job_id MUST be a non-empty string.",
                predicate=lambda args: bool(str(args.get("job_id", "")).strip()),
            ),
            ConditionCheck(
                description="job_status MUST be one of {'completed', 'failed'}.",
                predicate=lambda args: args.get("job_status") in {"completed", "failed"},
            ),
            ConditionCheck(
                description="delivery_state MUST be one of CallbackDeliveryState allowed values.",
                predicate=lambda args: args.get("delivery_state") in CALLBACK_DELIVERY_STATES,
            ),
            ConditionCheck(
                description="Caller MUST inject prior_delivery_state read from the persisted dispatch job; it MUST match delivery_state.",
                predicate=lambda args: (
                    (state := _persisted_delivery_state(args)) is not None
                    and state == args.get("delivery_state")
                ),
            ),
            ConditionCheck(
                description="job_status == 'completed' REQUIRES delivery_state == 'delivered' AND exit_code == 0.",
                predicate=lambda args: not (
                    args.get("job_status") == "completed"
                    and not (args.get("delivery_state") == "delivered" and args.get("exit_code") == 0)
                ),
            ),
        ),
        invariants=(
            ConditionCheck(
                description="A dispatch job is NEVER recorded as completed while its CallbackDeliveryProcess is not delivered.",
                predicate=lambda args: not (
                    args.get("job_status") == "completed" and args.get("delivery_state") != "delivered"
                ),
            ),
        ),
        postconditions=(
            ConditionCheck(
                description="The dispatch job status matches job_status.",
                predicate=lambda ctx: ctx.get("result") == ctx.get("job_status"),
            ),
        ),
    )



