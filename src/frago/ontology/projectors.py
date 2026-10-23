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
    AgentFivePartDecomposition,
    compute_desktop_content_id,
    decompose_agent_session,
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


@dataclass(frozen=True, kw_only=True)
class SessionRecordProjection:
    """Projected 5-part Agent decomposition plus immutable `SessionStepEvent` nodes."""

    decomposition: AgentFivePartDecomposition
    step_events: tuple[Event, ...]
    graph: OntologyGraph


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
    agent_type = str(raw_session.get("agent_type", "")).strip()
    if not session_id or not agent_type:
        raise ProjectionValidationError(
            "Session JSON must provide non-empty 'session_id' and 'agent_type'."
        )

    status = str(raw_session.get("status", "running"))
    source = str(raw_session.get("source", "terminal"))
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
    """Project a `RecipeExposurePolicy` and verify `PublicExposableRecipe` axioms when `access == 'public'`."""
    g = graph if graph is not None else OntologyGraph()
    recipe_name = str(raw_exposure.get("recipe_name", "")).strip()
    access = str(raw_exposure.get("access", "owner")).strip()
    if not recipe_name or access not in {"owner", "signed-in", "allow", "public"}:
        raise ProjectionValidationError(
            "RecipeExposurePolicy requires 'recipe_name' and valid 'access' level."
        )

    recipe_uid = f"recipe:{recipe_name}"
    recipe_ent = g.get_entity(recipe_uid)
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

    def project_session(
        self,
        raw_session: Mapping[str, Any],
        *,
        raw_steps: Sequence[Mapping[str, Any]] = (),
        is_worker: bool = False,
        profile_id: str | None = None,
    ) -> SessionRecordProjection:
        return project_session_dict(
            raw_session,
            raw_steps=raw_steps,
            is_worker=is_worker,
            profile_id=profile_id,
            registry=self._registry,
            graph=self._graph,
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

    def validate_recipe_handshakes(self) -> list[str]:
        return verify_recipe_shares_handshake(self._recipe_projections)
