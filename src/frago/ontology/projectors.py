"""Zero-intrusion shadow projectors for real on-disk JSON structures across the 5 pillars.

Projects raw dictionaries (as loaded from disk in `sessions/`, `agent_os`, `recipes/`,
`hook/`, and `todo/`) directly into an `OntologyGraph` using `DomainClassRegistry`,
without importing any business subsystem modules:

1. **Pillar 1 (Session Companion — `project_hook_rules_dict`)**:
   Projects `builtin-rules.json` / `hook-rules.json` (`version`, `rules[*]`) into
   `HookInjectionRule` (`RulePolicy`) and `BookTopicDocument` (`InformationEntity`),
   binding rules to governed `AgentSessionProcess` instances.
2. **Pillar 2 (Hand & Eye — `project_desktop_instance_dict`)**:
   Projects `agent_os` instance registry JSON (`IDENTITY_FIELDS`: `id`, `content_id`,
   `desktop_url`, `clips_dir`, `tmux_session`, `created_at`; `RUNTIME_FIELDS`: `pid`,
   `port`, `status`, `started_at`, `heartbeat_at`, `desired`) into `VirtualDesktopStage`
   (`Resource`) and `DesktopInstanceRuntimeState` (`QualityState`), verifying that
   `content_id == sha256(id)[:12]`.
3. **Pillar 3 (Memory & Recall — `project_session_dict` & `project_todo_dict`)**:
   Projects `MonitoredSession` + `SessionStep` JSON dicts into the 5-part Agent ontology
   plus `SessionStepEvent` nodes, and projects `~/.frago/todo/<id>.json` (`TODO_SCHEMA`)
   into `TodoHandoffArtifact` linked via `produces` to every session in `todo["sessions"]`
   (while enforcing that `status == "dropped"` requires a non-empty `drop_reason`).
4. **Pillar 4 (Recipes — `project_recipe_metadata_dict` & `verify_recipe_shares_handshake`)**:
   Projects `RecipeMetadata` frontmatter (`name`, `version`, `dependencies`,
   `reads_common`, `shares`, `uses_commands`, `uses_frago_cli`, `daemon`, `modes`)
   into `RecipeModule`, `RecipeModuleContract`, `RecipeModeCapability`,
   `ExternalCommandCapability`, and transitive `depends_on_module` edges, and verifies
   bidirectional `reads_common` <-> `shares` handshakes.
5. **Pillar 5 (Boundaries & Cross-Pillar Orchestration — `FivePillarShadowProjector`)**:
   Unifies all five pillars into a single operational `OntologyGraph` for cross-session
   SPARQL path queries, `DefinedClass` inference, and multi-hop causal provenance.

Layer: pure ontology shadow projector (imports only `frago.ontology.*` and Python stdlib).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from frago.ontology.contracts import BUILTIN_DEFINED_CLASSES
from frago.ontology.metamodel import (
    Actor,
    Capability,
    Contract,
    Event,
    IdentityCriterionError,
    InformationEntity,
    MutabilityViolationError,
    OntologyError,
    Process,
    QualityState,
    Resource,
    Role,
    RulePolicy,
    Specification,
)
from frago.ontology.registry import DEFAULT_DOMAIN_REGISTRY, DomainClassRegistry
from frago.ontology.relations import OntologyGraph
from frago.ontology.runtime import (
    SESSION_VALID_KERNELS,
    AgentFivePartDecomposition,
    compute_desktop_content_id,
    decompose_agent_session,
    normalize_session_lifecycle_state,
    normalize_session_origin,
)

BROWSER_MAX_TABS_PER_GROUP: int = 5
DESKTOP_IDENTITY_FIELDS: tuple[str, ...] = (
    "id",
    "content_id",
    "desktop_url",
    "clips_dir",
    "tmux_session",
    "created_at",
)
DESKTOP_RUNTIME_FIELDS: tuple[str, ...] = (
    "pid",
    "port",
    "status",
    "started_at",
    "heartbeat_at",
)
TODO_VALID_STATUSES: frozenset[str] = frozenset({"todo", "doing", "done", "dropped"})

CAPABILITY_NATIVE: str = "native"
CAPABILITY_ADAPTED: str = "adapted"
CAPABILITY_FALLBACK: str = "fallback"
CAPABILITY_UNSUPPORTED: str = "unsupported"

AGENT_ORTHOGONAL_FACETS: tuple[str, ...] = (
    "identity_probe",
    "lifecycle_action",
    "transcript_sync",
    "awaiting_input_probe",
    "busy_probe",
    "context_watermark",
    "hook_injection",
)

AGENT_CAPABILITY_MATRIX: dict[str, dict[str, str]] = {
    "claude": {
        "identity_probe": CAPABILITY_NATIVE,
        "lifecycle_action": CAPABILITY_NATIVE,
        "transcript_sync": CAPABILITY_NATIVE,
        "awaiting_input_probe": CAPABILITY_ADAPTED,
        "busy_probe": CAPABILITY_NATIVE,
        "context_watermark": CAPABILITY_NATIVE,
        "hook_injection": CAPABILITY_NATIVE,
    },
    "agy": {
        "identity_probe": CAPABILITY_NATIVE,
        "lifecycle_action": CAPABILITY_NATIVE,
        "transcript_sync": CAPABILITY_ADAPTED,
        "awaiting_input_probe": CAPABILITY_FALLBACK,
        "busy_probe": CAPABILITY_ADAPTED,
        "context_watermark": CAPABILITY_ADAPTED,
        "hook_injection": CAPABILITY_ADAPTED,
    },
    "opencode": {
        "identity_probe": CAPABILITY_NATIVE,
        "lifecycle_action": CAPABILITY_NATIVE,
        "transcript_sync": CAPABILITY_NATIVE,
        "awaiting_input_probe": CAPABILITY_FALLBACK,
        "busy_probe": CAPABILITY_FALLBACK,
        "context_watermark": CAPABILITY_ADAPTED,
        "hook_injection": CAPABILITY_ADAPTED,
    },
    "codex": {
        "identity_probe": CAPABILITY_NATIVE,
        "lifecycle_action": CAPABILITY_NATIVE,
        "transcript_sync": CAPABILITY_ADAPTED,
        "awaiting_input_probe": CAPABILITY_FALLBACK,
        "busy_probe": CAPABILITY_FALLBACK,
        "context_watermark": CAPABILITY_ADAPTED,
        "hook_injection": CAPABILITY_UNSUPPORTED,
    },
    "coreagent": {
        "identity_probe": CAPABILITY_NATIVE,
        "lifecycle_action": CAPABILITY_NATIVE,
        "transcript_sync": CAPABILITY_NATIVE,
        "awaiting_input_probe": CAPABILITY_UNSUPPORTED,
        "busy_probe": CAPABILITY_NATIVE,
        "context_watermark": CAPABILITY_NATIVE,
        "hook_injection": CAPABILITY_NATIVE,
    },
}

AGENT_KERNEL_METADATA: dict[str, dict[str, Any]] = {
    "claude": {
        "name": "claude",
        "display_name": "Claude Code",
        "execution_mode": "tmux_tui",
        "runs_in_tmux": True,
        "supports_resume": True,
        "supports_branch": True,
        "supports_for_you": True,
        "capability_tier": "tier1",
        "profile_mode": "file_and_env",
        "capabilities": AGENT_CAPABILITY_MATRIX["claude"],
    },
    "agy": {
        "name": "agy",
        "display_name": "Antigravity",
        "execution_mode": "tmux_tui",
        "runs_in_tmux": True,
        "supports_resume": True,
        "supports_branch": False,
        "supports_for_you": True,
        "capability_tier": "tier2",
        "profile_mode": "file_and_env",
        "capabilities": AGENT_CAPABILITY_MATRIX["agy"],
    },
    "opencode": {
        "name": "opencode",
        "display_name": "OpenCode",
        "execution_mode": "tmux_tui",
        "runs_in_tmux": True,
        "supports_resume": True,
        "supports_branch": False,
        "supports_for_you": True,
        "capability_tier": "tier2",
        "profile_mode": "file_and_env",
        "capabilities": AGENT_CAPABILITY_MATRIX["opencode"],
    },
    "codex": {
        "name": "codex",
        "display_name": "Codex CLI",
        "execution_mode": "tmux_tui",
        "runs_in_tmux": True,
        "supports_resume": True,
        "supports_branch": False,
        "supports_for_you": True,
        "capability_tier": "tier2",
        "profile_mode": "file_and_env",
        "capabilities": AGENT_CAPABILITY_MATRIX["codex"],
    },
    "coreagent": {
        "name": "coreagent",
        "display_name": "CoreAgent",
        "execution_mode": "headless_kernel",
        "runs_in_tmux": False,
        "supports_resume": False,
        "supports_branch": False,
        "supports_for_you": False,
        "capability_tier": "tier1",
        "profile_mode": "native_kernel",
        "capabilities": AGENT_CAPABILITY_MATRIX["coreagent"],
    },
}


def list_agent_kernels() -> tuple[str, ...]:
    """Return all declared AgentKernel identifiers in ontological order."""
    return tuple(AGENT_KERNEL_METADATA.keys())


def get_agent_kernel_metadata(kernel: str) -> dict[str, Any]:
    """Return full execution mode, UI features and capability matrix metadata for an agent kernel."""
    normalized = kernel.strip().lower()
    meta = AGENT_KERNEL_METADATA.get(normalized)
    if meta is not None:
        return dict(meta)
    return {
        "name": normalized,
        "display_name": normalized,
        "execution_mode": "unknown",
        "runs_in_tmux": True,
        "supports_resume": False,
        "supports_branch": False,
        "supports_for_you": False,
        "capability_tier": "unsupported",
        "profile_mode": "unsupported",
        "capabilities": dict.fromkeys(AGENT_ORTHOGONAL_FACETS, CAPABILITY_UNSUPPORTED),
    }


def runs_in_tmux(kernel: str) -> bool:
    """Return True if the kernel executes within a tmux interactive TUI session."""
    return bool(get_agent_kernel_metadata(kernel).get("runs_in_tmux", True))


def supports_profile_binding(kernel: str) -> bool:
    """Return True if the kernel supports profile configuration binding."""
    mode = str(get_agent_kernel_metadata(kernel).get("profile_mode", ""))
    return mode in ("file_and_env", "env_only", "session_env", "native_flag")


def supports_for_you(kernel: str) -> bool:
    """Return True if the kernel can expose awaiting-input status to For you view."""
    return bool(get_agent_kernel_metadata(kernel).get("supports_for_you", False))


def get_agent_capability_level(agent_kernel: str, facet: str) -> str:
    """Return the four-level capability declaration ('native' | 'adapted' | 'fallback' | 'unsupported')."""
    normalized = agent_kernel.strip().lower()
    kernel_caps = AGENT_CAPABILITY_MATRIX.get(normalized)
    if kernel_caps is None:
        return CAPABILITY_UNSUPPORTED
    return kernel_caps.get(facet, CAPABILITY_UNSUPPORTED)


@dataclass(frozen=True, kw_only=True)
class AgentKernelProjection:
    """Projected ontological `AgentKernel` actor and its declared capability matrix."""

    kernel: Actor
    capabilities: Mapping[str, str]
    graph: OntologyGraph


def project_agent_kernel_dict(
    raw_kernel: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> AgentKernelProjection:
    """Project an AgentKernel dictionary into `AgentKernel` (Actor) and linked `Capability` entities."""
    g = graph if graph is not None else OntologyGraph()
    raw_name = str(
        raw_kernel.get("name")
        or raw_kernel.get("agent_kernel")
        or raw_kernel.get("kernel")
        or raw_kernel.get("family")
        or ""
    ).strip()
    if not raw_name:
        raise ProjectionValidationError("AgentKernel JSON requires a non-empty kernel name.")

    kernel_name = raw_name.lower()
    if kernel_name not in AGENT_CAPABILITY_MATRIX:
        raise ProjectionValidationError(
            f"Unknown agent kernel '{raw_name}'. Allowed kernels: {sorted(AGENT_CAPABILITY_MATRIX.keys())}."
        )

    kernel_uid = f"kernel:{kernel_name}"
    existing_kernel = g.get_entity(kernel_uid)
    if isinstance(existing_kernel, Actor):
        kernel = existing_kernel
    else:
        created_kernel = registry.create("AgentKernel", uid=kernel_uid)
        assert isinstance(created_kernel, Actor)
        kernel = created_kernel
        g.register_entity(kernel)

    caps_map = AGENT_CAPABILITY_MATRIX[kernel_name]
    for facet, level in caps_map.items():
        cap = Capability(
            bearer_id=kernel.ontological_id(),
            context_id=f"facet:{facet}:{level}",
            dependent_type=facet,
        )
        g.link(kernel, "has_capability", cap)

    return AgentKernelProjection(
        kernel=kernel,
        capabilities=caps_map,
        graph=g,
    )


class ProjectionValidationError(OntologyError):
    """Raised when an on-disk JSON dictionary violates ontological projection constraints."""


# ============================================================================
# Pillar 1: Session Companion (`builtin-rules.json` / `hook-rules.json`)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class HookRulesProjection:
    """Projected ontological entities from a hook rules JSON configuration."""

    rules: tuple[RulePolicy, ...]
    referenced_books: tuple[InformationEntity, ...]
    graph: OntologyGraph


def project_hook_rules_dict(
    raw_hook_config: Mapping[str, Any],
    *,
    governed_session_ids: Sequence[str] = (),
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> HookRulesProjection:
    """Project `builtin-rules.json` or `hook-rules.json` into `HookInjectionRule` and `BookTopicDocument`."""
    g = graph if graph is not None else OntologyGraph()
    raw_rules = raw_hook_config.get("rules")
    if not isinstance(raw_rules, Sequence):
        raise ProjectionValidationError("Hook config JSON must contain a 'rules' list.")

    projected_rules: list[RulePolicy] = []
    projected_books: list[InformationEntity] = []
    version_str = f"{raw_hook_config.get('version', 1)}.0.0"

    for item in raw_rules:
        if not isinstance(item, Mapping) or not item.get("id"):
            raise ProjectionValidationError("Each hook rule must be an object with a non-empty 'id'.")
        rule_id = str(item["id"])
        rule_entity = registry.create(
            "HookInjectionRule",
            norm_id=f"hook:{rule_id}",
            semantic_version=version_str,
        )
        assert isinstance(rule_entity, RulePolicy)
        g.register_entity(rule_entity)
        projected_rules.append(rule_entity)

        action = item.get("action", {})
        if isinstance(action, Mapping):
            cmd = action.get("command")
            if isinstance(cmd, Sequence) and len(cmd) >= 2 and cmd[0] == "book":
                book_slug = str(cmd[1]).lstrip("-")
                book_doc = registry.create(
                    "BookTopicDocument",
                    artifact_uri=f"book://{book_slug}",
                    content=f"{rule_id}:{book_slug}",
                )
                assert isinstance(book_doc, InformationEntity)
                g.register_entity(book_doc)
                projected_books.append(book_doc)

        for sess_id in governed_session_ids:
            proc_uid = sess_id if sess_id.startswith("session:") else f"session:{sess_id}"
            sess_ent = g.get_entity(proc_uid)
            if isinstance(sess_ent, Process):
                g.link(sess_ent, "governed_by", rule_entity)

    return HookRulesProjection(
        rules=tuple(projected_rules),
        referenced_books=tuple(projected_books),
        graph=g,
    )


# ============================================================================
# Pillar 2: Hand & Eye (`agent_os` Instance Registry JSON)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class DesktopInstanceProjection:
    """Projected `VirtualDesktopStage` identity and `DesktopInstanceRuntimeState` from registry JSON."""

    instance_id: str
    content_id: str
    stage: Resource
    runtime_state: QualityState
    desired: str
    graph: OntologyGraph


def project_desktop_instance_dict(
    raw_instance: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> DesktopInstanceProjection:
    """Project an `agent_os` instance registry JSON dict into `VirtualDesktopStage` + `DesktopInstanceRuntimeState`."""
    g = graph if graph is not None else OntologyGraph()

    missing_id_fields = [f for f in DESKTOP_IDENTITY_FIELDS if f not in raw_instance]
    if missing_id_fields:
        raise ProjectionValidationError(
            f"Desktop instance JSON missing identity fields: {missing_id_fields}."
        )
    missing_rt_fields = [f for f in DESKTOP_RUNTIME_FIELDS if f not in raw_instance]
    if missing_rt_fields:
        raise ProjectionValidationError(
            f"Desktop instance JSON missing runtime fields: {missing_rt_fields}."
        )

    instance_id = str(raw_instance["id"])
    actual_content_id = str(raw_instance["content_id"])
    expected_content_id = compute_desktop_content_id(instance_id)
    if actual_content_id != expected_content_id:
        raise IdentityCriterionError(
            f"Desktop instance '{instance_id}' content_id mismatch: expected "
            f"sha256('{instance_id}')[:12]=='{expected_content_id}', got '{actual_content_id}'."
        )

    stage_uid = f"desktop:{instance_id}#{actual_content_id}"
    existing = g.get_entity(stage_uid)
    if isinstance(existing, Resource):
        stage = existing
    else:
        created = registry.create("VirtualDesktopStage", uid=stage_uid)
        assert isinstance(created, Resource)
        stage = created

    status_val = str(raw_instance["status"])
    started_at_ctx = str(raw_instance.get("started_at") or "boot:0")
    runtime_state = registry.create(
        "DesktopInstanceRuntimeState",
        bearer_id=stage.ontological_id(),
        context_id=f"boot:{started_at_ctx}",
        value=status_val,
    )
    assert isinstance(runtime_state, QualityState)
    g.link(stage, "exhibits_state", runtime_state, replace_functional=True)

    desired = str(raw_instance.get("desired", status_val))
    return DesktopInstanceProjection(
        instance_id=instance_id,
        content_id=actual_content_id,
        stage=stage,
        runtime_state=runtime_state,
        desired=desired,
        graph=g,
    )


# ============================================================================
# Pillar 3: Memory & Recall (`MonitoredSession`, `SessionStep`, and `Todo` JSON)
# ============================================================================


#: 五个内核的名字只在本体层留一份定义（`runtime.py`），这里从那里导入。
#: 从前两份各写一遍（内容相同），加第六个内核时必然漏改一处，本模块这一份已删。


@dataclass(frozen=True, kw_only=True)
class SessionRecordProjection:
    """Projected 5-part Agent decomposition plus immutable `SessionStepEvent` nodes."""

    decomposition: AgentFivePartDecomposition
    step_events: tuple[Event, ...]
    graph: OntologyGraph

    @property
    def session_process(self) -> Process:
        return self.decomposition.session_process

    @property
    def lifecycle_state(self) -> QualityState | None:
        return self.decomposition.lifecycle_state

    @property
    def origin_state(self) -> QualityState:
        return self.decomposition.origin_state

    @property
    def role(self) -> Role:
        return self.decomposition.role

    @property
    def kernel(self) -> Actor:
        return self.decomposition.kernel

    @property
    def transcript_artifact(self) -> InformationEntity:
        return self.decomposition.transcript_artifact


SessionProcessProjection = SessionRecordProjection


def project_session_dict(
    raw_session: Mapping[str, Any],
    *,
    raw_steps: Sequence[Mapping[str, Any]] = (),
    is_worker: bool = False,
    profile_id: str | None = None,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> SessionRecordProjection:
    """Project a `MonitoredSession` dict and optional `SessionStep` dicts into an `OntologyGraph`."""
    g = graph if graph is not None else OntologyGraph()

    session_id = str(raw_session.get("session_id", "")).strip()
    raw_agent_type = raw_session.get("agent_type") or raw_session.get("agent_family") or ""
    agent_type = str(raw_agent_type).strip().lower()
    if not session_id or not agent_type:
        raise ProjectionValidationError(
            "Session JSON must provide non-empty 'session_id' and 'agent_type'."
        )
    if agent_type not in SESSION_VALID_KERNELS:
        raise ProjectionValidationError(
            f"Unknown agent kernel '{agent_type}'. Allowed kernels: {sorted(SESSION_VALID_KERNELS)}."
        )

    raw_status = raw_session.get("status")
    status = normalize_session_lifecycle_state(str(raw_status) if raw_status is not None else "running")
    raw_source = raw_session.get("source")
    source = normalize_session_origin(
        str(raw_source) if raw_source is not None else "terminal",
        is_worker=is_worker,
    )
    role_cls = "SubtaskWorkerRole" if is_worker else "PrimarySchedulerRole"
    transcript_uri = str(
        raw_session.get("source_jsonl")
        or raw_session.get("source_file")
        or f"~/.frago/sessions/{agent_type}/{session_id}/raw.jsonl"
    )

    decomp = decompose_agent_session(
        agent_family=agent_type,
        session_id=session_id,
        role_class_id=role_cls,
        session_state=status,
        origin=source,
        profile_id=profile_id,
        transcript_uri=transcript_uri,
        registry=registry,
        graph=g,
    )

    step_events: list[Event] = []
    for raw_step in raw_steps:
        step_type = str(raw_step.get("type", "system"))
        raw_ts = raw_step.get("timestamp")
        occurred_at = (
            datetime.fromisoformat(str(raw_ts))
            if isinstance(raw_ts, str)
            else (raw_ts if isinstance(raw_ts, datetime) else datetime.now())
        )
        evt = registry.create(
            "SessionStepEvent",
            event_type=step_type,
            causal_source_id=decomp.session_process.ontological_id(),
            occurred_at=occurred_at,
            payload={
                "step_id": int(raw_step.get("step_id", 1)),
                "raw_uuid": str(raw_step.get("raw_uuid", "")),
                "tool_name": raw_step.get("tool_name"),
            },
        )
        assert isinstance(evt, Event)
        g.link(decomp.session_process, "emits", evt)
        step_events.append(evt)

    return SessionRecordProjection(
        decomposition=decomp,
        step_events=tuple(step_events),
        graph=g,
    )


def project_session_process_dict(
    raw_session: Mapping[str, Any],
    *,
    raw_steps: Sequence[Mapping[str, Any]] = (),
    is_worker: bool = False,
    profile_id: str | None = None,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> SessionRecordProjection:
    """Project a session dictionary into an ontological process graph (canonical entrypoint)."""
    return project_session_dict(
        raw_session,
        raw_steps=raw_steps,
        is_worker=is_worker,
        profile_id=profile_id,
        registry=registry,
        graph=graph,
    )


# ============================================================================
# Pillar 3b: Async Callback Delivery (`~/.frago/sessions/async_dispatches/<job_id>.json`)
# ============================================================================

CALLBACK_DELIVERY_STATES: tuple[str, ...] = ("queued", "delivering", "delivered", "failed")
CALLBACK_DELIVERY_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"delivering", "failed"}),
    "delivering": frozenset({"delivered", "queued", "failed"}),
    "delivered": frozenset(),
    "failed": frozenset(),
}
"""Legal callback-delivery transitions.

``queued → delivering → delivered`` is the only road to ``delivered``; a failed injection
goes ``delivering → queued`` (put back at the head of the queue); ``failed`` is reachable
from ``queued`` or ``delivering`` once retries are exhausted or the target is unreachable.
``delivered`` and ``failed`` are terminal. The registry's generic state table is a full
mesh, so the narrower contract is pinned here.
"""


def is_legal_callback_delivery_transition(from_state: str, to_state: str) -> bool:
    """Whether ``from_state → to_state`` is allowed for a `CallbackDeliveryProcess`."""
    return to_state in CALLBACK_DELIVERY_TRANSITIONS.get(from_state, frozenset())


def infer_callback_delivery_state(raw_job: Mapping[str, Any]) -> str | None:
    """Read the delivery state from a dispatch ledger dict.

    New ledgers carry ``delivery_state``. Legacy ledgers (before delivery was modelled)
    only have ``status``, whose ``completed`` historically meant "worker ok and callback
    sent": map it to ``delivered``; ``failed`` to ``failed``; anything still in flight
    (``pending`` / ``running`` / ``delivering``) to ``queued``. ``superseded`` jobs never
    deliver and are not projected (returns None).
    """
    explicit = raw_job.get("delivery_state")
    if explicit:
        value = str(explicit).strip().lower()
        if value not in CALLBACK_DELIVERY_STATES:
            raise ProjectionValidationError(
                f"Unknown callback delivery_state '{value}'. Allowed: {list(CALLBACK_DELIVERY_STATES)}."
            )
        return value
    status = str(raw_job.get("status") or "").strip().lower()
    if status == "completed":
        return "delivered"
    if status == "failed":
        return "failed"
    if status in {"pending", "running", "delivering"}:
        return "queued"
    return None


@dataclass(frozen=True, kw_only=True)
class CallbackDeliveryProjection:
    """Projected `CallbackDeliveryProcess` (+R, keyed by job_id) and its `CallbackDeliveryState` (~R)."""

    job_id: str
    caller_session_id: str
    worker_session_id: str | None
    process: Process
    state: QualityState
    worker_succeeded: bool | None
    graph: OntologyGraph


def project_callback_delivery_dict(
    raw_job: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> CallbackDeliveryProjection:
    """Project an async dispatch ledger dict into `CallbackDeliveryProcess` + `CallbackDeliveryState`.

    Worker outcome (``exit_code``) and delivery outcome are kept apart: ``worker_succeeded``
    comes from ``exit_code`` only, the state node from ``delivery_state`` only. A ledger whose
    ``status`` says ``completed`` while delivery is not ``delivered`` violates the
    dispatch-status subordination rule and is rejected.
    """
    g = graph if graph is not None else OntologyGraph()

    job_id = str(raw_job.get("job_id") or "").strip()
    caller = str(raw_job.get("caller_session_id") or "").strip()
    if not job_id or not caller:
        raise ProjectionValidationError(
            "Dispatch JSON must provide non-empty 'job_id' and 'caller_session_id'."
        )
    delivery_state = infer_callback_delivery_state(raw_job)
    if delivery_state is None:
        raise ProjectionValidationError(
            f"Dispatch job '{job_id}' (status={raw_job.get('status')!r}) has no callback delivery to project."
        )
    if str(raw_job.get("status") or "") == "completed" and delivery_state != "delivered":
        raise ProjectionValidationError(
            f"Dispatch job '{job_id}' is 'completed' but callback delivery is '{delivery_state}'; "
            "completed requires delivered."
        )

    process_uid = f"callback-delivery:{job_id}"
    existing = g.get_entity(process_uid)
    if isinstance(existing, Process):
        process = existing
    else:
        created = registry.create(
            "CallbackDeliveryProcess", process_uid=process_uid, state=delivery_state
        )
        assert isinstance(created, Process)
        process = created

    state = registry.create(
        "CallbackDeliveryState",
        bearer_id=process.ontological_id(),
        context_id=f"caller:{caller}",
        value=delivery_state,
    )
    assert isinstance(state, QualityState)
    g.link(process, "exhibits_state", state, replace_functional=True)

    caller_uid = f"session:{caller}"
    caller_proc = g.get_entity(caller_uid)
    if not isinstance(caller_proc, Process):
        caller_proc = registry.create("AgentSessionProcess", process_uid=caller_uid)
        assert isinstance(caller_proc, Process)
    g.link(process, "delivers_to_session", caller_proc)

    raw_exit = raw_job.get("exit_code")
    worker_succeeded: bool | None
    if raw_exit is None:
        worker_succeeded = None
    else:
        try:
            worker_succeeded = int(raw_exit) == 0
        except (TypeError, ValueError):
            worker_succeeded = False
    worker_sid = str(raw_job.get("target_session_id") or "").strip() or None

    if worker_sid:
        worker_uid = f"session:{worker_sid}"
        worker_proc = g.get_entity(worker_uid)
        if not isinstance(worker_proc, Process):
            worker_proc = registry.create("AgentSessionProcess", process_uid=worker_uid)
            assert isinstance(worker_proc, Process)
        g.link(process, "dispatched_from_worker", worker_proc)

    return CallbackDeliveryProjection(
        job_id=job_id,
        caller_session_id=caller,
        worker_session_id=worker_sid,
        process=process,
        state=state,
        worker_succeeded=worker_succeeded,
        graph=g,
    )


def project_todo_dict(
    raw_todo: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> InformationEntity:
    """Project a `~/.frago/todo/<id>.json` dict into a `TodoHandoffArtifact` and link its sessions."""
    g = graph if graph is not None else OntologyGraph()

    todo_id = str(raw_todo.get("id", "")).strip()
    title = str(raw_todo.get("title", "")).strip()
    if not todo_id or not title:
        raise ProjectionValidationError("Todo JSON requires non-empty 'id' and 'title'.")

    status = str(raw_todo.get("status", "todo"))
    if status not in TODO_VALID_STATUSES:
        raise MutabilityViolationError(
            f"Todo '{todo_id}' has invalid status '{status}' (expected one of {sorted(TODO_VALID_STATUSES)})."
        )

    drop_reason = raw_todo.get("drop_reason")
    if status == "dropped" and (not drop_reason or not str(drop_reason).strip()):
        raise MutabilityViolationError(
            f"Todo '{todo_id}' has status=='dropped' but is missing a required 'drop_reason'."
        )

    artifact = registry.create(
        "TodoHandoffArtifact",
        artifact_uri=f"todo://{todo_id}",
        content=f"{todo_id}:{title}:{status}:{raw_todo.get('updated', '')}",
    )
    assert isinstance(artifact, InformationEntity)
    g.register_entity(artifact)

    sessions = raw_todo.get("sessions", [])
    if isinstance(sessions, Sequence):
        for sid in sessions:
            proc_uid = f"session:{sid}"
            proc_ent = g.get_entity(proc_uid)
            if isinstance(proc_ent, Process):
                g.link(proc_ent, "produces", artifact)

    return artifact


# ============================================================================
# Pillar 4: Recipes (`RecipeMetadata` Dict & Bidirectional `shares` Handshake)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class RecipeProjection:
    """Projected ontological entities for a single `RecipeMetadata` dictionary."""

    recipe: Resource
    contract: Contract
    mode_capabilities: tuple[Capability, ...]
    external_command_capabilities: tuple[Capability, ...]
    reads_common: tuple[str, ...]
    shares: str
    graph: OntologyGraph


def project_recipe_metadata_dict(
    raw_recipe: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> RecipeProjection:
    """Project a `RecipeMetadata` dictionary into `RecipeModule`, `RecipeModuleContract`, and capabilities."""
    g = graph if graph is not None else OntologyGraph()

    name = str(raw_recipe.get("name", "")).strip()
    if not name:
        raise ProjectionValidationError("Recipe metadata JSON requires a non-empty 'name'.")
    version = str(raw_recipe.get("version", "1.0.0"))

    recipe_res = registry.create("RecipeModule", uid=f"recipe:{name}")
    assert isinstance(recipe_res, Resource)
    g.register_entity(recipe_res)

    recipe_contract = registry.create(
        "RecipeModuleContract",
        norm_id=f"recipe_contract:{name}",
        semantic_version=version,
    )
    assert isinstance(recipe_contract, Contract)
    g.register_entity(recipe_contract)

    mode_caps: list[Capability] = []
    modes_map = raw_recipe.get("modes", {})
    if isinstance(modes_map, Mapping):
        for mode_name, level in modes_map.items():
            cap = registry.create(
                "RecipeModeCapability",
                bearer_id=recipe_res.ontological_id(),
                context_id=f"mode:{mode_name}:{level}",
            )
            assert isinstance(cap, Capability)
            g.link(recipe_res, "has_capability", cap)
            mode_caps.append(cap)
            if level == "action_triggerable":
                # Also attach a canonical action_triggerable marker capability for PublicExposableRecipe check
                marker_cap = Capability(
                    bearer_id=recipe_res.ontological_id(),
                    context_id=f"mode:{mode_name}",
                    dependent_type="action_triggerable",
                )
                g.link(recipe_res, "has_capability", marker_cap)

    ext_caps: list[Capability] = []
    uses_commands = raw_recipe.get("uses_commands", [])
    if isinstance(uses_commands, Sequence):
        for cmd_name in uses_commands:
            ecap = registry.create(
                "ExternalCommandCapability",
                bearer_id=recipe_res.ontological_id(),
                context_id=f"cmd:{cmd_name}",
            )
            assert isinstance(ecap, Capability)
            g.link(recipe_res, "has_capability", ecap)
            ext_caps.append(ecap)

    if bool(raw_recipe.get("uses_frago_cli", False)):
        fcap = registry.create(
            "ExternalCommandCapability",
            bearer_id=recipe_res.ontological_id(),
            context_id="cli:frago",
        )
        assert isinstance(fcap, Capability)
        g.link(recipe_res, "has_capability", fcap)
        ext_caps.append(fcap)

    reads_common = tuple(str(r) for r in raw_recipe.get("reads_common", []))
    dependencies = tuple(str(d) for d in raw_recipe.get("dependencies", []))
    for upstream_name in (*dependencies, *reads_common):
        upstream_uid = f"recipe:{upstream_name}"
        upstream_ent = g.get_entity(upstream_uid)
        if upstream_ent is None:
            upstream_ent = registry.create("RecipeModule", uid=upstream_uid)
        g.link(recipe_res, "depends_on_module", upstream_ent)

    return RecipeProjection(
        recipe=recipe_res,
        contract=recipe_contract,
        mode_capabilities=tuple(mode_caps),
        external_command_capabilities=tuple(ext_caps),
        reads_common=reads_common,
        shares=str(raw_recipe.get("shares", "")).strip(),
        graph=g,
    )


def verify_recipe_shares_handshake(
    projections: Sequence[RecipeProjection],
) -> list[str]:
    """Verify that every target in `reads_common` declares a non-empty `shares` subpath."""
    by_name: dict[str, RecipeProjection] = {
        p.recipe.ontological_id().removeprefix("recipe:"): p for p in projections
    }
    violations: list[str] = []
    for proj in projections:
        consumer_name = proj.recipe.ontological_id().removeprefix("recipe:")
        for target_name in proj.reads_common:
            target_proj = by_name.get(target_name)
            if target_proj is None:
                violations.append(
                    f"Recipe '{consumer_name}' declares reads_common '{target_name}', which is not registered."
                )
            elif not target_proj.shares:
                violations.append(
                    f"Recipe '{consumer_name}' reads_common '{target_name}', but '{target_name}' declares empty shares."
                )
    return violations


# ============================================================================
# Extended Subsystem Projectors (Browser, Viewer, Recall, Exposure, Schedule, Team)
# ============================================================================


def project_browser_tab_group_dict(
    raw_group: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> Resource:
    """Project a controlled browser tab-group JSON dict into `BrowserTabGroup`, enforcing the 5-tab limit."""
    g = graph if graph is not None else OntologyGraph()
    group_name = str(raw_group.get("group_name", "")).strip()
    if not group_name:
        raise ProjectionValidationError("BrowserTabGroup JSON requires non-empty 'group_name'.")

    tabs = raw_group.get("tabs", [])
    if not isinstance(tabs, Sequence):
        raise ProjectionValidationError("BrowserTabGroup 'tabs' must be a sequence.")
    if len(tabs) > BROWSER_MAX_TABS_PER_GROUP:
        raise ProjectionValidationError(
            f"BrowserTabGroup '{group_name}' has {len(tabs)} tabs, exceeding max limit {BROWSER_MAX_TABS_PER_GROUP}."
        )

    group_res = registry.create("BrowserTabGroup", uid=f"browser_group:{group_name}")
    assert isinstance(group_res, Resource)
    g.register_entity(group_res)
    return group_res


def project_viewer_surface_dict(
    raw_view: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> Resource:
    """Project a dual-world `frago view` surface (`file` vs `recipe`) into `ContentViewerSurface`."""
    g = graph if graph is not None else OntologyGraph()
    world = str(raw_view.get("world", "file")).strip()
    content_id = str(raw_view.get("content_id", "")).strip()
    if world not in {"file", "recipe"} or not content_id:
        raise ProjectionValidationError(
            "ContentViewerSurface requires 'world' in {'file', 'recipe'} and non-empty 'content_id'."
        )
    surface = registry.create(
        "ContentViewerSurface",
        uid=f"viewer:{world}:{content_id}",
    )
    assert isinstance(surface, Resource)
    g.register_entity(surface)
    return surface


@dataclass(frozen=True, kw_only=True)
class DefDomainProjection:
    """Projected `KnowledgeDomain` resource and its `DefKnowledgeEntry` artifacts."""

    domain: Resource
    entries: tuple[InformationEntity, ...]
    graph: OntologyGraph


def project_def_knowledge_dict(
    raw_domain: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> DefDomainProjection:
    """Project a `frago def` domain and structured knowledge entries into `KnowledgeDomain` and `DefKnowledgeEntry`."""
    g = graph if graph is not None else OntologyGraph()
    domain_name = str(raw_domain.get("domain", "")).strip()
    if not domain_name:
        raise ProjectionValidationError("Def knowledge JSON requires a non-empty 'domain'.")

    domain_res = registry.create("KnowledgeDomain", uid=f"domain:{domain_name}")
    assert isinstance(domain_res, Resource)
    g.register_entity(domain_res)

    entries: list[InformationEntity] = []
    raw_entries = raw_domain.get("entries", [])
    if isinstance(raw_entries, Sequence):
        for item in raw_entries:
            if not isinstance(item, Mapping) or not item.get("doc_name"):
                raise ProjectionValidationError("Each def entry requires a non-empty 'doc_name'.")
            doc_name = str(item["doc_name"])
            entry_ent = registry.create(
                "DefKnowledgeEntry",
                artifact_uri=f"def://{domain_name}/{doc_name}",
                content=str(item.get("summary") or item.get("content") or doc_name),
            )
            assert isinstance(entry_ent, InformationEntity)
            g.register_entity(entry_ent)
            entries.append(entry_ent)

    return DefDomainProjection(
        domain=domain_res,
        entries=tuple(entries),
        graph=g,
    )


def project_data_slot_dict(
    raw_slot: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> tuple[Resource, InformationEntity | None]:
    """Project a `DataSlot` path and optional `ContextRecallIndex` into the ontology graph."""
    g = graph if graph is not None else OntologyGraph()
    slot_path = str(raw_slot.get("canonical_slot_path", "")).strip()
    if not slot_path:
        raise ProjectionValidationError("DataSlot JSON requires 'canonical_slot_path'.")

    slot_res = registry.create("DataSlot", uid=f"slot:{slot_path}")
    assert isinstance(slot_res, Resource)
    g.register_entity(slot_res)

    recall_index: InformationEntity | None = None
    subject_slug = str(raw_slot.get("subject_slug", "")).strip()
    if subject_slug:
        idx = registry.create(
            "ContextRecallIndex",
            artifact_uri=f"context://{subject_slug}",
            content=f"{subject_slug}->{slot_path}",
        )
        assert isinstance(idx, InformationEntity)
        g.register_entity(idx)
        recall_index = idx

    return slot_res, recall_index


def project_run_transaction_dict(
    raw_run: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> Process:
    """Project a `frago run` transaction into `RunTransactionProcess` governed by `RunDomainDictSpec`."""
    g = graph if graph is not None else OntologyGraph()
    run_id = str(raw_run.get("run_id", "")).strip()
    canonical_domain = str(raw_run.get("canonical_domain", "")).strip()
    if not run_id or not canonical_domain:
        raise ProjectionValidationError(
            "RunTransaction JSON requires non-empty 'run_id' and 'canonical_domain'."
        )

    proc = registry.create(
        "RunTransactionProcess",
        process_uid=f"run:{run_id}",
        state=str(raw_run.get("state", "running")),
    )
    assert isinstance(proc, Process)
    spec = registry.create(
        "RunDomainDictSpec",
        norm_id=f"run_dict:{canonical_domain}",
    )
    assert isinstance(spec, Specification)
    g.link(proc, "governed_by", spec)

    slot_path = str(raw_run.get("data_slot_path", "")).strip()
    if slot_path:
        slot_uid = f"slot:{slot_path}"
        slot_ent = g.get_entity(slot_uid)
        if not isinstance(slot_ent, Resource):
            slot_ent = registry.create("DataSlot", uid=slot_uid)
            assert isinstance(slot_ent, Resource)
        g.link(proc, "mutates", slot_ent)

    return proc


def project_token_usage_dict(
    raw_usage: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> InformationEntity:
    """Project a token usage calendar entry into `TokenUsageLedger`."""
    g = graph if graph is not None else OntologyGraph()
    date_str = str(raw_usage.get("date", "")).strip()
    agent_family = str(raw_usage.get("agent_family", "")).strip()
    model_name = str(raw_usage.get("model", "")).strip()
    if not date_str or not agent_family or not model_name:
        raise ProjectionValidationError(
            "TokenUsageLedger JSON requires 'date', 'agent_family', and 'model'."
        )
    ledger = registry.create(
        "TokenUsageLedger",
        artifact_uri=f"ledger://{date_str}/{agent_family}/{model_name}",
        content=f"{date_str}:{agent_family}:{model_name}:{raw_usage.get('tokens', 0)}",
    )
    assert isinstance(ledger, InformationEntity)
    g.register_entity(ledger)
    return ledger


def project_recipe_exposure_dict(
    raw_exposure: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> RulePolicy:
    """Project a `RecipeExposurePolicy` and verify `PublicExposableRecipe` axioms when `access == 'public'`.

    The axiom has two clauses, and both are about what an **anonymous reader can
    reach**. Both facts live outside this layer — which may import only the
    standard library and `frago.ontology.*` — so the caller states them:

    * ``unargued_anon_write`` — whether an anonymous caller can reach a write
      through this recipe that **nobody argued for**. Not "the recipe marks an
      ``@action``": a page action is reachable only by the owner now that the
      anonymous zone admits GET and HEAD and those reach `@export` only. Every
      anonymous entrance has to be registered by name in
      `frago.server.security._ANON_POST`, with its reason beside it, and a
      decision is not what this class exists to refuse.
    * ``page_calls_api_from_public_page`` — whether the page fetches
      ``api/<mode>`` in a way the anonymous zone refuses, which is the failure
      ``frago recipe expose --public`` refuses up front.

    Leaving either out means false, which lets a caller project a recipe it
    knows nothing about without claiming anything about it. What the defaults
    must not do is *infer* from the recipe's own declaration — that inference is
    the disagreement with reality this function used to produce for
    `frago_home`, where the recipe marks `@action submit_request`, is published
    `--public`, and both are true.

    A recipe that is not in the graph is not judged: there is nothing to attach
    a capability to, and refusing here would turn "the caller did not project
    the recipe first" into a security verdict.
    """
    from frago.ontology.contracts import (
        ACTION_TRIGGERABLE_CAPABILITY,
        PUBLIC_PAGE_CALLS_BACKEND_CAPABILITY,
    )

    g = graph if graph is not None else OntologyGraph()
    recipe_name = str(raw_exposure.get("recipe_name", "")).strip()
    access = str(raw_exposure.get("access", "owner")).strip()
    if not recipe_name or access not in {"owner", "signed-in", "allow", "public"}:
        raise ProjectionValidationError(
            "RecipeExposurePolicy requires 'recipe_name' and valid 'access' level."
        )

    recipe_uid = f"recipe:{recipe_name}"
    recipe_ent = g.get_entity(recipe_uid)

    # Stated as capabilities, so the axiom reads one shape whether the caller
    # passed the fact in or the recipe already carried it. Built directly rather
    # than through the registry: these two markers are not domain classes in
    # `frago.json` — they are the vocabulary this axiom is written in, and
    # `registry.create` instantiates a declared class by name.
    if recipe_ent is not None:
        if bool(raw_exposure.get("unargued_anon_write", False)):
            g.link(
                recipe_ent,
                "has_capability",
                Capability(
                    bearer_id=recipe_ent.ontological_id(),
                    context_id=f"recipe:{recipe_name}",
                    dependent_type=ACTION_TRIGGERABLE_CAPABILITY,
                ),
            )
        if bool(raw_exposure.get("page_calls_api_from_public_page", False)):
            g.link(
                recipe_ent,
                "has_capability",
                Capability(
                    bearer_id=recipe_ent.ontological_id(),
                    context_id=f"page:{recipe_name}",
                    dependent_type=PUBLIC_PAGE_CALLS_BACKEND_CAPABILITY,
                ),
            )

    if access == "public" and recipe_ent is not None:
        pub_cls = BUILTIN_DEFINED_CLASSES["PublicExposableRecipe"]
        if not pub_cls.matches(recipe_ent, g):
            raise ProjectionValidationError(
                f"Recipe '{recipe_name}' does not satisfy PublicExposableRecipe axioms and cannot be exposed as 'public'."
            )

    policy = registry.create(
        "RecipeExposurePolicy",
        norm_id=f"exposure:{recipe_name}:{access}",
    )
    assert isinstance(policy, RulePolicy)
    g.register_entity(policy)
    return policy


def project_schedule_rule_dict(
    raw_schedule: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> Specification:
    """Project a `frago schedule` entry into `ScheduleRuleSpec` with `target_kind` metadata."""
    g = graph if graph is not None else OntologyGraph()
    rule_id = str(raw_schedule.get("id", "")).strip()
    target_kind = str(raw_schedule.get("target_kind", "")).strip()
    if not rule_id or target_kind not in {"command", "recipe", "agent_prompt"}:
        raise ProjectionValidationError(
            "ScheduleRuleSpec requires non-empty 'id' and 'target_kind' in {'command', 'recipe', 'agent_prompt'}."
        )

    spec = registry.create(
        "ScheduleRuleSpec",
        norm_id=f"{target_kind}:{rule_id}",
    )
    assert isinstance(spec, Specification)
    g.register_entity(spec)
    return spec


@dataclass(frozen=True, kw_only=True)
class TeamPairingProjection:
    """Projected `HumanPrincipal`, `TeamPeerRole`, and `TeamPairingSecurityPolicy`."""

    principal: Actor
    peer_role: Role
    policy: RulePolicy
    graph: OntologyGraph


@dataclass(frozen=True, kw_only=True)
class EmployeePostProjection:
    """Projected `EmployeePostResource`, `DomainEmployeeRole`, `AgentKernel`, and governed domain/recipe/schedule assets."""

    post: Resource
    employee_role: Role
    kernel: Actor
    domains: tuple[Resource, ...]
    recipes: tuple[Resource, ...]
    data_slots: tuple[Resource, ...]
    schedules: tuple[Specification, ...]
    active_sessions: tuple[Process, ...]
    graph: OntologyGraph


def project_employee_post_dict(
    raw_post: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> EmployeePostProjection:
    """Project a proactive fixed employee post dictionary into `EmployeePostResource`, `DomainEmployeeRole`, and its 5-branch edges.

    Models the 5 branches of a proactive domain employee:
    1. Manage KnowledgeDomain (`depends_on_module` from `EmployeePostResource` to `KnowledgeDomain`).
    2. Manage RecipeModule & DataSlot (`depends_on_module` from `EmployeePostResource` to `RecipeModule` and `DataSlot`).
    3. Receive sessions (`initiates` from `DomainEmployeeRole` to `AgentSessionProcess`).
    4. Invokable by contract (`governed_by` linking `DomainEmployeeRole` to `ScheduleRuleSpec` or normative specs).
    5. Bound to an interchangeable `AgentKernel` via `plays_role`.
    """
    g = graph if graph is not None else OntologyGraph()
    post_id = str(raw_post.get("member_post_id", "")).strip()
    agent_kernel_name = str(raw_post.get("agent_kernel", "")).strip()
    if not post_id:
        raise ProjectionValidationError(
            "EmployeePost JSON requires a non-empty 'member_post_id'."
        )

    kernel_spec = registry.get_spec("AgentKernel")
    allowed_kernels = set(kernel_spec.get("allowed_values") or ())
    if not agent_kernel_name or (
        allowed_kernels and agent_kernel_name not in allowed_kernels
    ):
        raise ProjectionValidationError(
            f"EmployeePost JSON requires 'agent_kernel' in {sorted(allowed_kernels)}, got '{agent_kernel_name}'."
        )

    post_uid = post_id if post_id.startswith("post:") else f"post:{post_id}"
    post_res = registry.create("EmployeePostResource", uid=post_uid)
    assert isinstance(post_res, Resource)
    g.register_entity(post_res)

    kernel_uid = f"kernel:{agent_kernel_name}"
    existing_kernel = g.get_entity(kernel_uid)
    if isinstance(existing_kernel, Actor):
        kernel = existing_kernel
    else:
        created_kernel = registry.create("AgentKernel", uid=kernel_uid)
        assert isinstance(created_kernel, Actor)
        kernel = created_kernel

    emp_role = registry.create(
        "DomainEmployeeRole",
        bearer_id=kernel.ontological_id(),
        context_id=post_res.ontological_id(),
    )
    assert isinstance(emp_role, Role)
    g.link(kernel, "plays_role", emp_role)

    # Branch 1: Manage KnowledgeDomain
    raw_domains = raw_post.get("knowledge_domains", [])
    if not isinstance(raw_domains, Sequence) or isinstance(raw_domains, (str, bytes)):
        raise ProjectionValidationError(
            "EmployeePost 'knowledge_domains' must be a list of domain names."
        )
    domains: list[Resource] = []
    for d_name in raw_domains:
        clean_domain = str(d_name).strip()
        if not clean_domain:
            continue
        dom_uid = (
            clean_domain
            if clean_domain.startswith("domain:")
            else f"domain:{clean_domain}"
        )
        existing_dom = g.get_entity(dom_uid)
        if isinstance(existing_dom, Resource):
            dom_res = existing_dom
        else:
            created_dom = registry.create("KnowledgeDomain", uid=dom_uid)
            assert isinstance(created_dom, Resource)
            dom_res = created_dom
        g.link(post_res, "depends_on_module", dom_res)
        domains.append(dom_res)

    # Branch 2: Manage related RecipeModule & DataSlot
    raw_recipes = raw_post.get("recipes", [])
    if not isinstance(raw_recipes, Sequence) or isinstance(raw_recipes, (str, bytes)):
        raise ProjectionValidationError(
            "EmployeePost 'recipes' must be a list of recipe names."
        )
    recipes: list[Resource] = []
    for r_name in raw_recipes:
        clean_recipe = str(r_name).strip()
        if not clean_recipe:
            continue
        rec_uid = (
            clean_recipe
            if clean_recipe.startswith("recipe:")
            else f"recipe:{clean_recipe}"
        )
        existing_rec = g.get_entity(rec_uid)
        if isinstance(existing_rec, Resource):
            rec_res = existing_rec
        else:
            created_rec = registry.create("RecipeModule", uid=rec_uid)
            assert isinstance(created_rec, Resource)
            rec_res = created_rec
        g.link(post_res, "depends_on_module", rec_res)
        recipes.append(rec_res)

    raw_slots = raw_post.get("data_slots", [])
    if not isinstance(raw_slots, Sequence) or isinstance(raw_slots, (str, bytes)):
        raise ProjectionValidationError(
            "EmployeePost 'data_slots' must be a list of canonical slot paths."
        )
    data_slots: list[Resource] = []
    for s_path in raw_slots:
        clean_slot = str(s_path).strip()
        if not clean_slot:
            continue
        slot_uid = (
            clean_slot if clean_slot.startswith("slot:") else f"slot:{clean_slot}"
        )
        existing_slot = g.get_entity(slot_uid)
        if isinstance(existing_slot, Resource):
            slot_res = existing_slot
        else:
            created_slot = registry.create("DataSlot", uid=slot_uid)
            assert isinstance(created_slot, Resource)
            slot_res = created_slot
        g.link(post_res, "depends_on_module", slot_res)
        data_slots.append(slot_res)

    # Branch 3: Receive sessions
    raw_sessions = raw_post.get("active_session_ids", [])
    if not isinstance(raw_sessions, Sequence) or isinstance(raw_sessions, (str, bytes)):
        raise ProjectionValidationError(
            "EmployeePost 'active_session_ids' must be a list of session IDs."
        )
    active_sessions: list[Process] = []
    for s_id in raw_sessions:
        clean_sess = str(s_id).strip()
        if not clean_sess:
            continue
        sess_uid = (
            clean_sess
            if clean_sess.startswith("session:")
            else f"session:{clean_sess}"
        )
        existing_sess = g.get_entity(sess_uid)
        if isinstance(existing_sess, Process):
            sess_proc = existing_sess
        else:
            created_sess = registry.create(
                "AgentSessionProcess",
                process_uid=sess_uid,
                state="running",
            )
            assert isinstance(created_sess, Process)
            sess_proc = created_sess
        g.link(emp_role, "initiates", sess_proc)
        active_sessions.append(sess_proc)

    # Branch 5 (more): Governed by / invokes ScheduleRuleSpec
    raw_schedules = raw_post.get("schedule_ids", [])
    if not isinstance(raw_schedules, Sequence) or isinstance(raw_schedules, (str, bytes)):
        raise ProjectionValidationError(
            "EmployeePost 'schedule_ids' must be a list of schedule rule IDs."
        )
    schedules: list[Specification] = []
    for sched_id in raw_schedules:
        clean_sched = str(sched_id).strip()
        if not clean_sched:
            continue
        norm_id = (
            clean_sched
            if ":" in clean_sched
            else f"agent_prompt:{clean_sched}"
        )
        existing_sched = g.get_entity(f"{norm_id}@1.0.0")
        if isinstance(existing_sched, Specification):
            sched_spec = existing_sched
        else:
            created_sched = registry.create("ScheduleRuleSpec", norm_id=norm_id)
            assert isinstance(created_sched, Specification)
            sched_spec = created_sched
        g.link(emp_role, "governed_by", sched_spec)
        schedules.append(sched_spec)

    return EmployeePostProjection(
        post=post_res,
        employee_role=emp_role,
        kernel=kernel,
        domains=tuple(domains),
        recipes=tuple(recipes),
        data_slots=tuple(data_slots),
        schedules=tuple(schedules),
        active_sessions=tuple(active_sessions),
        graph=g,
    )


def project_team_pairing_dict(
    raw_team: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    graph: OntologyGraph | None = None,
) -> TeamPairingProjection:
    """Project a `frago team` pairing state dictionary into `HumanPrincipal`, `TeamPeerRole`, and `TeamPairingSecurityPolicy`."""
    g = graph if graph is not None else OntologyGraph()
    team_code = str(raw_team.get("team_code", "")).strip()
    member_uuid = str(raw_team.get("member_uuid", "")).strip()
    side = str(raw_team.get("side", "A")).strip()
    if not team_code or not member_uuid or side not in {"A", "B"}:
        raise ProjectionValidationError(
            "Team pairing JSON requires 'team_code', 'member_uuid', and 'side' in {'A', 'B'}."
        )

    principal = registry.create("HumanPrincipal", uid=f"principal:{member_uuid}")
    assert isinstance(principal, Actor)
    peer_role = registry.create(
        "TeamPeerRole",
        bearer_id=principal.ontological_id(),
        context_id=f"team:{team_code}:side_{side}",
    )
    assert isinstance(peer_role, Role)
    policy = registry.create(
        "TeamPairingSecurityPolicy",
        norm_id=f"team_policy:{team_code}",
    )
    assert isinstance(policy, RulePolicy)

    g.link(principal, "plays_role", peer_role)
    g.link(peer_role, "governed_by", policy)
    return TeamPairingProjection(
        principal=principal,
        peer_role=peer_role,
        policy=policy,
        graph=g,
    )


# ============================================================================
# Pillar 5: Unified Five-Pillar Shadow Projector
# ============================================================================


class FivePillarShadowProjector:
    """Zero-intrusion orchestrator that projects raw JSON dictionaries from all 5 pillars into one `OntologyGraph`."""

    def __init__(
        self,
        *,
        registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
        graph: OntologyGraph | None = None,
    ) -> None:
        self._registry = registry
        self._graph = graph if graph is not None else OntologyGraph()
        self._recipe_projections: list[RecipeProjection] = []

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    def project_session_process(
        self,
        raw_session: Mapping[str, Any],
        *,
        raw_steps: Sequence[Mapping[str, Any]] = (),
        is_worker: bool = False,
        profile_id: str | None = None,
    ) -> SessionRecordProjection:
        return project_session_process_dict(
            raw_session,
            raw_steps=raw_steps,
            is_worker=is_worker,
            profile_id=profile_id,
            registry=self._registry,
            graph=self._graph,
        )

    def project_callback_delivery(
        self, raw_job: Mapping[str, Any]
    ) -> CallbackDeliveryProjection:
        return project_callback_delivery_dict(
            raw_job, registry=self._registry, graph=self._graph
        )

    def project_session(
        self,
        raw_session: Mapping[str, Any],
        *,
        raw_steps: Sequence[Mapping[str, Any]] = (),
        is_worker: bool = False,
        profile_id: str | None = None,
    ) -> SessionRecordProjection:
        return self.project_session_process(
            raw_session,
            raw_steps=raw_steps,
            is_worker=is_worker,
            profile_id=profile_id,
        )

    def project_hook_rules(
        self,
        raw_hook_config: Mapping[str, Any],
        *,
        governed_session_ids: Sequence[str] = (),
    ) -> HookRulesProjection:
        return project_hook_rules_dict(
            raw_hook_config,
            governed_session_ids=governed_session_ids,
            registry=self._registry,
            graph=self._graph,
        )

    def project_desktop_instance(
        self,
        raw_instance: Mapping[str, Any],
    ) -> DesktopInstanceProjection:
        return project_desktop_instance_dict(
            raw_instance,
            registry=self._registry,
            graph=self._graph,
        )

    def project_browser_tab_group(
        self,
        raw_group: Mapping[str, Any],
    ) -> Resource:
        return project_browser_tab_group_dict(
            raw_group,
            registry=self._registry,
            graph=self._graph,
        )

    def project_viewer_surface(
        self,
        raw_view: Mapping[str, Any],
    ) -> Resource:
        return project_viewer_surface_dict(
            raw_view,
            registry=self._registry,
            graph=self._graph,
        )

    def project_def_knowledge(
        self,
        raw_domain: Mapping[str, Any],
    ) -> DefDomainProjection:
        return project_def_knowledge_dict(
            raw_domain,
            registry=self._registry,
            graph=self._graph,
        )

    def project_data_slot(
        self,
        raw_slot: Mapping[str, Any],
    ) -> tuple[Resource, InformationEntity | None]:
        return project_data_slot_dict(
            raw_slot,
            registry=self._registry,
            graph=self._graph,
        )

    def project_run_transaction(
        self,
        raw_run: Mapping[str, Any],
    ) -> Process:
        return project_run_transaction_dict(
            raw_run,
            registry=self._registry,
            graph=self._graph,
        )

    def project_token_usage(
        self,
        raw_usage: Mapping[str, Any],
    ) -> InformationEntity:
        return project_token_usage_dict(
            raw_usage,
            registry=self._registry,
            graph=self._graph,
        )

    def project_todo(
        self,
        raw_todo: Mapping[str, Any],
    ) -> InformationEntity:
        return project_todo_dict(
            raw_todo,
            registry=self._registry,
            graph=self._graph,
        )

    def project_recipe(
        self,
        raw_recipe: Mapping[str, Any],
    ) -> RecipeProjection:
        proj = project_recipe_metadata_dict(
            raw_recipe,
            registry=self._registry,
            graph=self._graph,
        )
        self._recipe_projections.append(proj)
        return proj

    def project_recipe_exposure(
        self,
        raw_exposure: Mapping[str, Any],
    ) -> RulePolicy:
        return project_recipe_exposure_dict(
            raw_exposure,
            registry=self._registry,
            graph=self._graph,
        )

    def project_schedule_rule(
        self,
        raw_schedule: Mapping[str, Any],
    ) -> Specification:
        return project_schedule_rule_dict(
            raw_schedule,
            registry=self._registry,
            graph=self._graph,
        )

    def project_team_pairing(
        self,
        raw_team: Mapping[str, Any],
    ) -> TeamPairingProjection:
        return project_team_pairing_dict(
            raw_team,
            registry=self._registry,
            graph=self._graph,
        )

    def project_employee_post(
        self,
        raw_post: Mapping[str, Any],
    ) -> EmployeePostProjection:
        return project_employee_post_dict(
            raw_post,
            registry=self._registry,
            graph=self._graph,
        )

    def project_agent_kernel(
        self,
        raw_kernel: Mapping[str, Any],
    ) -> AgentKernelProjection:
        return project_agent_kernel_dict(
            raw_kernel,
            registry=self._registry,
            graph=self._graph,
        )

    def validate_recipe_handshakes(self) -> list[str]:
        return verify_recipe_shares_handshake(self._recipe_projections)
