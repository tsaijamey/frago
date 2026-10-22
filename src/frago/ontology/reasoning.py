"""Graph JSONL snapshot persistence, SPARQL-style path query engine, and multi-hop causal lineage tracer.

Extends `src/frago/ontology/` with three cross-session reasoning capabilities:
1. **JSONL Graph Snapshot Serialization & Cross-Session Replay**:
   - Deterministic export (`serialize_graph_jsonl`) and lossless import (`deserialize_graph_jsonl`)
     of all 4 upper quadrants (`Continuant`, `Occurrent`, `NormativeEntity`, `InformationEntity`)
     and `RelationFact` edges, re-validating OntoClean rigidity, domain/range, and algebraic
     invariants upon load.
   - Multi-session graph merging (`merge_graph_snapshots`) for combining primary scheduler,
     subtask worker, and recipe execution snapshots into a unified operational graph.
2. **SPARQL-Style Declarative Triple Pattern & Property Path Query Engine**:
   - Variable bindings (`?var`), sequence paths (`plays_role/initiates/produces`),
     transitive closures (`depends_on_module+`, `depends_on_module*`), inverse predicates
     (`produced_by`, `initiated_by`, `borne_by`), domain class filters, and `DefinedClass`
     axiom filters.
3. **Multi-Hop Causal Lineage & Forward Impact Tracer**:
   - Backward provenance (`trace_causal_lineage`): traces any artifact, event, or mutated
     resource across sessions back to its originating `Process`, `Role`, `Actor`, `Resource`
     harness, and governing `NormativeEntity`.
   - Forward impact (`trace_forward_impact`): computes all downstream processes, events,
     mutated resources, artifacts, and dependent modules reachable from a given source.

Layer: pure ontology metamodel & reasoning engine (zero imports from business modules).
"""

from __future__ import annotations

import dataclasses
import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from frago.ontology.contracts import BUILTIN_DEFINED_CLASSES, DefinedClass
from frago.ontology.metamodel import (
    Actor,
    Capability,
    Contract,
    Event,
    InformationEntity,
    NormativeEntity,
    OntologyEntity,
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


class ReasoningError(OntologyError):
    """Raised when graph snapshot deserialization or path query syntax is invalid."""


def _entity_domain_class_id(entity: OntologyEntity) -> str:
    """Resolve the canonical `class_id` (from `frago.json`) or metamodel class name."""
    cid = getattr(entity, "domain_class_id", None)
    if isinstance(cid, str) and cid:
        return cid
    for attr in (
        "actor_kind",
        "resource_kind",
        "dependent_type",
        "process_kind",
        "rule_kind",
        "contract_kind",
        "spec_kind",
        "artifact_kind",
    ):
        val = getattr(entity, attr, None)
        if isinstance(val, str) and val:
            return val
    return type(entity).__name__


def _entity_matches_type_name(entity: OntologyEntity, expected_type: str) -> bool:
    """Check whether `entity` matches a domain `class_id` or upper-ontology class name."""
    if _entity_domain_class_id(entity) == expected_type:
        return True
    return any(base.__name__ == expected_type for base in type(entity).__mro__)


# ============================================================================
# 1. JSONL Graph Snapshot Serialization & Cross-Session Replay
# ============================================================================


def serialize_entity_record(entity: OntologyEntity) -> dict[str, Any]:
    """Serialize an `OntologyEntity` into a JSON-compatible dictionary record."""
    class_id = _entity_domain_class_id(entity)
    quadrant = entity.quadrant.value if entity.quadrant is not None else "Unknown"
    raw_fields: dict[str, Any] = {}

    if isinstance(entity, Actor):
        raw_fields = {
            "base": "Actor",
            "uid": entity.uid,
            "actor_kind": entity.actor_kind,
            "version": entity.version,
        }
    elif isinstance(entity, Resource):
        raw_fields = {
            "base": "Resource",
            "uid": entity.uid,
            "resource_kind": entity.resource_kind,
            "version": entity.version,
        }
    elif isinstance(entity, QualityState):
        raw_fields = {
            "base": "QualityState",
            "bearer_id": entity.bearer_id,
            "context_id": entity.context_id,
            "dependent_type": entity.dependent_type,
            "value": entity.value,
        }
    elif isinstance(entity, Role):
        raw_fields = {
            "base": "Role",
            "bearer_id": entity.bearer_id,
            "context_id": entity.context_id,
            "dependent_type": entity.dependent_type,
        }
    elif isinstance(entity, Capability):
        raw_fields = {
            "base": "Capability",
            "bearer_id": entity.bearer_id,
            "context_id": entity.context_id,
            "dependent_type": entity.dependent_type,
        }
    elif isinstance(entity, Process):
        raw_fields = {
            "base": "Process",
            "process_uid": entity.process_uid,
            "process_kind": entity.process_kind,
            "state": entity.state,
            "started_at": entity.started_at.isoformat(),
            "ended_at": entity.ended_at.isoformat() if entity.ended_at else None,
        }
    elif isinstance(entity, Event):
        raw_fields = {
            "base": "Event",
            "event_type": entity.event_type,
            "causal_source_id": entity.causal_source_id,
            "occurred_at": entity.occurred_at.isoformat(),
            "payload": dict(entity.payload),
        }
    elif isinstance(entity, RulePolicy):
        raw_fields = {
            "base": "RulePolicy",
            "norm_id": entity.norm_id,
            "semantic_version": entity.semantic_version,
            "rule_kind": entity.rule_kind,
            "valid_from": entity.valid_from.isoformat() if entity.valid_from else None,
            "valid_until": entity.valid_until.isoformat() if entity.valid_until else None,
        }
    elif isinstance(entity, Contract):
        raw_fields = {
            "base": "Contract",
            "norm_id": entity.norm_id,
            "semantic_version": entity.semantic_version,
            "contract_kind": entity.contract_kind,
            "valid_from": entity.valid_from.isoformat() if entity.valid_from else None,
            "valid_until": entity.valid_until.isoformat() if entity.valid_until else None,
        }
    elif isinstance(entity, Specification):
        raw_fields = {
            "base": "Specification",
            "norm_id": entity.norm_id,
            "semantic_version": entity.semantic_version,
            "spec_kind": entity.spec_kind,
            "valid_from": entity.valid_from.isoformat() if entity.valid_from else None,
            "valid_until": entity.valid_until.isoformat() if entity.valid_until else None,
        }
    elif isinstance(entity, InformationEntity):
        raw_fields = {
            "base": "InformationEntity",
            "artifact_uri": entity.artifact_uri,
            "content_hash": entity.content_hash,
            "artifact_kind": entity.artifact_kind,
        }
    else:
        raise ReasoningError(f"Unsupported entity type for JSONL serialization: {type(entity).__name__}")

    return {
        "kind": "entity",
        "class_id": class_id,
        "quadrant": quadrant,
        "ontological_id": entity.ontological_id(),
        "fields": raw_fields,
    }


def deserialize_entity_record(
    record: Mapping[str, Any],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
) -> OntologyEntity:
    """Reconstruct an `OntologyEntity` from a serialized JSONL entity record."""
    if record.get("kind") != "entity":
        raise ReasoningError(f"Expected record kind=='entity', got {record.get('kind')!r}.")

    class_id = str(record.get("class_id", ""))
    fields: Mapping[str, Any] = record.get("fields", {})
    base_name = str(fields.get("base", ""))
    known_classes = registry.classes

    if class_id in known_classes:
        kwargs = dict(fields)
        kwargs.pop("base", None)
        for dt_key in ("started_at", "ended_at", "occurred_at", "valid_from", "valid_until"):
            if dt_key in kwargs and kwargs[dt_key] is not None:
                kwargs[dt_key] = datetime.fromisoformat(str(kwargs[dt_key]))
            elif dt_key in kwargs and kwargs[dt_key] is None:
                kwargs.pop(dt_key)
        return registry.create(class_id, **kwargs)

    # Fallback for generic upper-ontology instances not named in domain_classes
    if base_name == "Actor":
        return Actor(
            uid=str(fields["uid"]),
            actor_kind=str(fields["actor_kind"]),
            version=int(fields.get("version", 1)),
        )
    if base_name == "Resource":
        return Resource(
            uid=str(fields["uid"]),
            resource_kind=str(fields["resource_kind"]),
            version=int(fields.get("version", 1)),
        )
    if base_name == "QualityState":
        return QualityState(
            bearer_id=str(fields["bearer_id"]),
            context_id=str(fields["context_id"]),
            dependent_type=str(fields["dependent_type"]),
            value=str(fields["value"]),
        )
    if base_name == "Role":
        return Role(
            bearer_id=str(fields["bearer_id"]),
            context_id=str(fields["context_id"]),
            dependent_type=str(fields["dependent_type"]),
        )
    if base_name == "Capability":
        return Capability(
            bearer_id=str(fields["bearer_id"]),
            context_id=str(fields["context_id"]),
            dependent_type=str(fields["dependent_type"]),
        )
    if base_name == "Process":
        return Process(
            process_uid=str(fields["process_uid"]),
            process_kind=str(fields["process_kind"]),
            state=str(fields.get("state", "pending")),
            started_at=datetime.fromisoformat(str(fields["started_at"])),
            ended_at=(
                datetime.fromisoformat(str(fields["ended_at"]))
                if fields.get("ended_at")
                else None
            ),
        )
    if base_name == "Event":
        return Event(
            event_type=str(fields["event_type"]),
            causal_source_id=str(fields["causal_source_id"]),
            occurred_at=datetime.fromisoformat(str(fields["occurred_at"])),
            payload=dict(fields.get("payload", {})),
        )
    if base_name == "RulePolicy":
        return RulePolicy(
            norm_id=str(fields["norm_id"]),
            semantic_version=str(fields.get("semantic_version", "1.0.0")),
            rule_kind=str(fields["rule_kind"]),
        )
    if base_name == "Contract":
        return Contract(
            norm_id=str(fields["norm_id"]),
            semantic_version=str(fields.get("semantic_version", "1.0.0")),
            contract_kind=str(fields["contract_kind"]),
        )
    if base_name == "Specification":
        return Specification(
            norm_id=str(fields["norm_id"]),
            semantic_version=str(fields.get("semantic_version", "1.0.0")),
            spec_kind=str(fields["spec_kind"]),
        )
    if base_name == "InformationEntity":
        return InformationEntity(
            artifact_uri=str(fields["artifact_uri"]),
            content_hash=str(fields["content_hash"]),
            artifact_kind=str(fields["artifact_kind"]),
        )

    raise ReasoningError(f"Cannot deserialize entity with base={base_name!r}, class_id={class_id!r}.")


def serialize_graph_jsonl(graph: OntologyGraph) -> str:
    """Serialize all entities and relation facts in `graph` to deterministic JSONL."""
    lines: list[str] = []
    for entity in graph.entities():
        rec = serialize_entity_record(entity)
        lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True))

    for fact in graph.facts():
        fact_rec = {
            "kind": "fact",
            "source_id": fact.source_id,
            "predicate": fact.predicate,
            "target_id": fact.target_id,
            "asserted_at": fact.asserted_at.isoformat(),
        }
        lines.append(json.dumps(fact_rec, ensure_ascii=False, sort_keys=True))

    return "\n".join(lines)


def deserialize_graph_jsonl(
    jsonl_text: str,
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
    target_graph: OntologyGraph | None = None,
    replace_functional: bool = True,
) -> OntologyGraph:
    """Deserialize JSONL snapshot lines into an `OntologyGraph` with full guardrail validation."""
    graph = target_graph if target_graph is not None else OntologyGraph()
    pending_facts: list[dict[str, Any]] = []

    for raw_line in jsonl_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReasoningError(f"Malformed JSONL line in ontology snapshot: {exc}") from exc

        if not isinstance(record, Mapping):
            raise ReasoningError("Each JSONL snapshot line must be a JSON object.")

        kind = record.get("kind")
        if kind == "entity":
            entity = deserialize_entity_record(record, registry=registry)
            graph.register_entity(entity)
        elif kind == "fact":
            pending_facts.append(dict(record))
        else:
            raise ReasoningError(f"Unknown JSONL snapshot record kind: {kind!r}.")

    for fact_rec in pending_facts:
        src_id = str(fact_rec["source_id"])
        pred = str(fact_rec["predicate"])
        tgt_id = str(fact_rec["target_id"])
        src_entity = graph.get_entity(src_id)
        tgt_entity = graph.get_entity(tgt_id)
        if src_entity is None:
            raise ReasoningError(f"Fact references unregistered source_id '{src_id}'.")
        if tgt_entity is None:
            raise ReasoningError(f"Fact references unregistered target_id '{tgt_id}'.")

        created = graph.link(
            src_entity,
            pred,
            tgt_entity,
            replace_functional=replace_functional,
        )
        if "asserted_at" in fact_rec and fact_rec["asserted_at"]:
            ts = datetime.fromisoformat(str(fact_rec["asserted_at"]))
            # Preserve original assertion timestamp if provided
            idx = graph._facts.index(created)
            graph._facts[idx] = dataclasses.replace(created, asserted_at=ts)

    return graph


def merge_graph_snapshots(
    snapshots_jsonl: Sequence[str],
    *,
    registry: DomainClassRegistry = DEFAULT_DOMAIN_REGISTRY,
) -> OntologyGraph:
    """Merge multiple session JSONL snapshots into a unified cross-session `OntologyGraph`."""
    merged = OntologyGraph()
    for snap in snapshots_jsonl:
        deserialize_graph_jsonl(
            snap,
            registry=registry,
            target_graph=merged,
            replace_functional=True,
        )
    return merged


# ============================================================================
# 2. SPARQL-Style Triple Pattern & Property Path Query Engine
# ============================================================================


@dataclass(frozen=True)
class TriplePattern:
    """A SPARQL-style pattern `(subject, predicate_path, object_)` where `?var` denotes a variable.

    `predicate_path` supports:
    - Single predicate or inverse predicate: `"plays_role"`, `"borne_by"`, `"produces"`
    - Transitive 1-or-more path: `"depends_on_module+"`
    - Reflexive-transitive 0-or-more path: `"depends_on_module*"`
    - Sequence path chaining steps with `/`: `"plays_role/initiates/produces"`
    """

    subject: str
    predicate_path: str
    object_: str


@dataclass(frozen=True, kw_only=True)
class SparqlQuery:
    """Structured declarative query over an `OntologyGraph`."""

    where: tuple[TriplePattern, ...]
    select: tuple[str, ...] = ()
    type_constraints: Mapping[str, str] = field(default_factory=dict)
    defined_class_constraints: Mapping[str, str] = field(default_factory=dict)
    filter_predicate: Callable[[Mapping[str, OntologyEntity]], bool] | None = None


@dataclass(frozen=True, kw_only=True)
class CausalHop:
    """A single directed step along a causal provenance or impact chain."""

    source_id: str
    source_class_id: str
    relation: str
    target_id: str
    target_class_id: str


@dataclass(frozen=True, kw_only=True)
class CausalLineageReport:
    """Complete multi-hop causal provenance report for a target entity."""

    focal_entity: OntologyEntity
    hops: tuple[CausalHop, ...]
    root_actors: tuple[Actor, ...]
    active_roles: tuple[Role, ...]
    harnesses_and_resources: tuple[Resource, ...]
    governing_norms: tuple[NormativeEntity, ...]
    processes: tuple[Process, ...]


class OntologyReasoner:
    """SPARQL-style path query evaluator and multi-hop causal lineage reasoner."""

    def __init__(
        self,
        graph: OntologyGraph,
        *,
        defined_classes: Mapping[str, DefinedClass] | None = None,
    ) -> None:
        self._graph = graph
        self._defined_classes: Mapping[str, DefinedClass] = (
            defined_classes if defined_classes is not None else BUILTIN_DEFINED_CLASSES
        )

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    def evaluate_path(
        self,
        start_id: str,
        predicate_path: str,
    ) -> list[OntologyEntity]:
        """Evaluate a SPARQL-style property path (`p`, `p+`, `p*`, or `p1/p2/...`) from `start_id`."""
        steps = [s.strip() for s in predicate_path.split("/") if s.strip()]
        if not steps:
            raise ReasoningError("Property path cannot be empty.")

        current_ids: list[str] = [start_id]
        for step in steps:
            next_ids: list[str] = []
            seen_next: set[str] = set()
            for cid in current_ids:
                for target_entity in self._evaluate_single_step(cid, step):
                    tid = target_entity.ontological_id()
                    if tid not in seen_next:
                        seen_next.add(tid)
                        next_ids.append(tid)
            current_ids = next_ids

        return [
            ent
            for oid in current_ids
            if (ent := self._graph.get_entity(oid)) is not None
        ]

    def query(
        self,
        sparql: SparqlQuery,
    ) -> list[dict[str, OntologyEntity]]:
        """Execute a `SparqlQuery` and return all matching variable bindings."""
        bindings_list: list[dict[str, OntologyEntity]] = [{}]

        for pattern in sparql.where:
            next_bindings: list[dict[str, OntologyEntity]] = []
            for env in bindings_list:
                for cand_env in self._match_pattern(pattern, env):
                    if self._satisfies_partial_constraints(
                        cand_env,
                        sparql.type_constraints,
                        sparql.defined_class_constraints,
                    ):
                        next_bindings.append(cand_env)
            bindings_list = next_bindings

        results: list[dict[str, OntologyEntity]] = []
        for env in bindings_list:
            if sparql.filter_predicate is not None and not sparql.filter_predicate(env):
                continue
            if sparql.select:
                projected = {k: env[k] for k in sparql.select if k in env}
                results.append(projected)
            else:
                results.append(dict(env))
        return results

    def trace_causal_lineage(
        self,
        target_id: str,
        *,
        max_depth: int = 8,
    ) -> CausalLineageReport:
        """Trace multi-hop backward causal provenance from `target_id` to root actors, roles, harnesses, and norms."""
        focal = self._graph.get_entity(target_id)
        if focal is None:
            raise ReasoningError(f"Unknown target entity '{target_id}' in OntologyGraph.")

        backward_predicates = (
            "produced_by",
            "emitted_by",
            "mutated_by",
            "initiated_by",
            "borne_by",
            "hosted_on_harness",
            "governed_by",
            "state_of",
            "capability_of",
        )

        hops: list[CausalHop] = []
        visited_entities: dict[str, OntologyEntity] = {target_id: focal}
        queue: deque[tuple[str, int]] = deque([(target_id, 0)])
        seen_edges: set[tuple[str, str, str]] = set()

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            curr_ent = self._graph.get_entity(curr_id)
            if curr_ent is None:
                continue

            # Explicit causal_source_id link on Event instances
            if isinstance(curr_ent, Event):
                cs_ent = self._graph.get_entity(curr_ent.causal_source_id)
                if cs_ent is not None:
                    edge_key = (curr_id, "causal_source", cs_ent.ontological_id())
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        hops.append(
                            CausalHop(
                                source_id=curr_id,
                                source_class_id=_entity_domain_class_id(curr_ent),
                                relation="causal_source",
                                target_id=cs_ent.ontological_id(),
                                target_class_id=_entity_domain_class_id(cs_ent),
                            )
                        )
                    if cs_ent.ontological_id() not in visited_entities:
                        visited_entities[cs_ent.ontological_id()] = cs_ent
                        queue.append((cs_ent.ontological_id(), depth + 1))

            for pred in backward_predicates:
                for neighbor in self._graph.query_targets(
                    curr_id, pred, include_transitive=False
                ):
                    nid = neighbor.ontological_id()
                    edge_key = (curr_id, pred, nid)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        hops.append(
                            CausalHop(
                                source_id=curr_id,
                                source_class_id=_entity_domain_class_id(curr_ent),
                                relation=pred,
                                target_id=nid,
                                target_class_id=_entity_domain_class_id(neighbor),
                            )
                        )
                    if nid not in visited_entities:
                        visited_entities[nid] = neighbor
                        queue.append((nid, depth + 1))

        all_discovered = [
            e for oid, e in visited_entities.items() if oid != target_id or isinstance(focal, Actor)
        ]
        return CausalLineageReport(
            focal_entity=focal,
            hops=tuple(hops),
            root_actors=tuple(e for e in all_discovered if isinstance(e, Actor)),
            active_roles=tuple(e for e in all_discovered if isinstance(e, Role)),
            harnesses_and_resources=tuple(
                e for e in all_discovered if isinstance(e, Resource)
            ),
            governing_norms=tuple(
                e for e in all_discovered if isinstance(e, NormativeEntity)
            ),
            processes=tuple(e for e in all_discovered if isinstance(e, Process)),
        )

    def trace_forward_impact(
        self,
        source_id: str,
        *,
        max_depth: int = 8,
    ) -> list[CausalHop]:
        """Trace multi-hop forward impact from `source_id` across roles, processes, events, artifacts, and dependents."""
        start_ent = self._graph.get_entity(source_id)
        if start_ent is None:
            raise ReasoningError(f"Unknown source entity '{source_id}' in OntologyGraph.")

        forward_predicates = (
            "plays_role",
            "initiates",
            "mutates",
            "emits",
            "produces",
            "governs",
            "depended_on_by",
            "hosts_actor",
        )

        hops: list[CausalHop] = []
        visited: set[str] = {source_id}
        queue: deque[tuple[str, int]] = deque([(source_id, 0)])
        seen_edges: set[tuple[str, str, str]] = set()

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            curr_ent = self._graph.get_entity(curr_id)
            if curr_ent is None:
                continue

            for pred in forward_predicates:
                for neighbor in self._graph.query_targets(
                    curr_id, pred, include_transitive=False
                ):
                    nid = neighbor.ontological_id()
                    edge_key = (curr_id, pred, nid)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        hops.append(
                            CausalHop(
                                source_id=curr_id,
                                source_class_id=_entity_domain_class_id(curr_ent),
                                relation=pred,
                                target_id=nid,
                                target_class_id=_entity_domain_class_id(neighbor),
                            )
                        )
                    if nid not in visited:
                        visited.add(nid)
                        queue.append((nid, depth + 1))

        return hops

    def _evaluate_single_step(
        self,
        start_id: str,
        step_expr: str,
    ) -> list[OntologyEntity]:
        if step_expr.endswith("+"):
            pred = step_expr[:-1]
            return self._closure_targets(start_id, pred, include_self=False)
        if step_expr.endswith("*"):
            pred = step_expr[:-1]
            return self._closure_targets(start_id, pred, include_self=True)
        return self._graph.query_targets(start_id, step_expr, include_transitive=False)

    def _closure_targets(
        self,
        start_id: str,
        predicate_or_inverse: str,
        *,
        include_self: bool,
    ) -> list[OntologyEntity]:
        results: list[OntologyEntity] = []
        seen: set[str] = set()
        if include_self:
            self_ent = self._graph.get_entity(start_id)
            if self_ent is not None:
                seen.add(start_id)
                results.append(self_ent)

        queue: deque[str] = deque([start_id])
        while queue:
            curr = queue.popleft()
            for neighbor in self._graph.query_targets(
                curr, predicate_or_inverse, include_transitive=False
            ):
                nid = neighbor.ontological_id()
                if nid not in seen:
                    seen.add(nid)
                    results.append(neighbor)
                    queue.append(nid)
        return results

    def _match_pattern(
        self,
        pattern: TriplePattern,
        env: Mapping[str, OntologyEntity],
    ) -> list[dict[str, OntologyEntity]]:
        subj_is_var = pattern.subject.startswith("?")
        obj_is_var = pattern.object_.startswith("?")

        if subj_is_var and pattern.subject in env:
            subject_candidates = [env[pattern.subject]]
        elif subj_is_var:
            subject_candidates = self._graph.entities()
        else:
            ent = self._graph.get_entity(pattern.subject)
            subject_candidates = [ent] if ent is not None else []

        matched_envs: list[dict[str, OntologyEntity]] = []
        for subj_ent in subject_candidates:
            targets = self.evaluate_path(
                subj_ent.ontological_id(),
                pattern.predicate_path,
            )
            for tgt_ent in targets:
                if obj_is_var and pattern.object_ in env:
                    if env[pattern.object_].ontological_id() != tgt_ent.ontological_id():
                        continue
                elif not obj_is_var and tgt_ent.ontological_id() != pattern.object_:
                    continue

                new_env = dict(env)
                if subj_is_var:
                    new_env[pattern.subject] = subj_ent
                if obj_is_var:
                    new_env[pattern.object_] = tgt_ent
                matched_envs.append(new_env)

        return matched_envs

    def _satisfies_partial_constraints(
        self,
        env: Mapping[str, OntologyEntity],
        type_constraints: Mapping[str, str],
        defined_class_constraints: Mapping[str, str],
    ) -> bool:
        for var_name, expected_type in type_constraints.items():
            if var_name in env and not _entity_matches_type_name(
                env[var_name], expected_type
            ):
                return False

        for var_name, def_cls_id in defined_class_constraints.items():
            if var_name in env:
                if def_cls_id not in self._defined_classes:
                    raise ReasoningError(f"Unknown DefinedClass '{def_cls_id}'.")
                def_cls = self._defined_classes[def_cls_id]
                if not def_cls.matches(env[var_name], self._graph):
                    return False

        return True
