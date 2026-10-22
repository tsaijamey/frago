"""First-class relation signatures, domain/range guardrails, and algebraic reasoning.

Unlike ER foreign keys or OOP one-way references, ontological relations here carry:
1. Explicit Domain and Range type constraints checked before any edge is added.
2. Inverse relation resolution (`plays_role` <-> `borne_by`, `initiates` <-> `initiated_by`).
3. Algebraic axioms (`asymmetric`, `irreflexive`, `transitive`, `functional`)
   enforced at graph mutation time and exploited during query traversal.

Layer: pure ontology metamodel (no I/O, no imports from cli/ or server/).
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from frago.ontology.metamodel import (
    Actor,
    Capability,
    Continuant,
    DependentContinuant,
    Event,
    IndependentContinuant,
    InformationEntity,
    NormativeEntity,
    Occurrent,
    OntologyEntity,
    OntologyError,
    Process,
    QualityState,
    Resource,
    Role,
)


class RelationError(OntologyError):
    """Base error for ontological relation violations."""


class DomainRangeViolationError(RelationError):
    """Raised when a relation's source or target violates its Domain or Range signature."""


class AlgebraicAxiomViolationError(RelationError):
    """Raised when adding a relation edge violates irreflexive, asymmetric, or functional axioms."""


class AlgebraicProperty(str, Enum):
    """Formal algebraic properties of first-class binary relations."""

    ASYMMETRIC = "asymmetric"
    SYMMETRIC = "symmetric"
    TRANSITIVE = "transitive"
    IRREFLEXIVE = "irreflexive"
    FUNCTIONAL = "functional"


@dataclass(frozen=True, kw_only=True)
class RelationSignature:
    """Formal specification of a binary ontological relation."""

    predicate: str
    domain_types: tuple[type[OntologyEntity], ...]
    range_types: tuple[type[OntologyEntity], ...]
    inverse: str
    algebraic_properties: frozenset[AlgebraicProperty] = field(default_factory=frozenset)
    description: str = ""


@dataclass(frozen=True, kw_only=True)
class RelationFact:
    """An immutable asserted edge in the ontology graph."""

    source_id: str
    predicate: str
    target_id: str
    asserted_at: datetime = field(default_factory=datetime.now)


_UPPER_TYPE_MAP: dict[str, type[OntologyEntity]] = {
    "OntologyEntity": OntologyEntity,
    "Continuant": Continuant,
    "IndependentContinuant": IndependentContinuant,
    "DependentContinuant": DependentContinuant,
    "Actor": Actor,
    "Resource": Resource,
    "Role": Role,
    "Capability": Capability,
    "QualityState": QualityState,
    "Occurrent": Occurrent,
    "Process": Process,
    "Event": Event,
    "NormativeEntity": NormativeEntity,
    "InformationEntity": InformationEntity,
}


def _resolve_type_expr(expr: str) -> tuple[type[OntologyEntity], ...]:
    tokens = [tok.strip() for tok in expr.split("|") if tok.strip()]
    resolved: list[type[OntologyEntity]] = []
    for tok in tokens:
        if tok not in _UPPER_TYPE_MAP:
            raise RelationError(f"Unknown upper ontology type '{tok}' in relation signature.")
        resolved.append(_UPPER_TYPE_MAP[tok])
    return tuple(resolved)


def build_relations_from_schema(
    schema: Mapping[str, Any] | None = None,
) -> dict[str, RelationSignature]:
    """Construct first-class `RelationSignature` objects directly from `frago.json`."""
    if schema is None:
        schema_path = Path(__file__).parent / "frago.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    raw_sigs: Mapping[str, Any] = schema.get("relation_signatures", {})
    built: dict[str, RelationSignature] = {}
    for predicate, spec in raw_sigs.items():
        props = frozenset(
            AlgebraicProperty(p) for p in spec.get("algebraic_properties", [])
        )
        built[predicate] = RelationSignature(
            predicate=predicate,
            domain_types=_resolve_type_expr(str(spec["domain"])),
            range_types=_resolve_type_expr(str(spec["range"])),
            inverse=str(spec["inverse"]),
            algebraic_properties=props,
            description=str(spec.get("description", "")),
        )
    return built


STANDARD_RELATIONS: dict[str, RelationSignature] = build_relations_from_schema()


class OntologyGraph:
    """In-memory operational ontology graph with domain/range and algebraic guards."""

    def __init__(
        self,
        relations: dict[str, RelationSignature] | None = None,
    ) -> None:
        self._signatures: dict[str, RelationSignature] = dict(
            relations if relations is not None else STANDARD_RELATIONS
        )
        self._inverse_to_primary: dict[str, str] = {
            sig.inverse: sig.predicate for sig in self._signatures.values()
        }
        self._entities: dict[str, OntologyEntity] = {}
        self._facts: list[RelationFact] = []

    @property
    def signatures(self) -> dict[str, RelationSignature]:
        return dict(self._signatures)

    def register_signature(self, signature: RelationSignature) -> None:
        """Register a custom first-class relation signature."""
        self._signatures[signature.predicate] = signature
        self._inverse_to_primary[signature.inverse] = signature.predicate

    def register_entity(self, entity: OntologyEntity) -> str:
        """Register or update an entity snapshot in the graph."""
        oid = entity.ontological_id()
        self._entities[oid] = entity
        return oid

    def get_entity(self, ontological_id: str) -> OntologyEntity | None:
        return self._entities.get(ontological_id)

    def entities(self) -> list[OntologyEntity]:
        return list(self._entities.values())

    def facts(self) -> list[RelationFact]:
        return list(self._facts)

    def to_jsonl(self) -> str:
        """Serialize this `OntologyGraph` into deterministic JSONL snapshot lines."""
        from frago.ontology.reasoning import serialize_graph_jsonl

        return serialize_graph_jsonl(self)

    @classmethod
    def from_jsonl(cls, jsonl_text: str) -> OntologyGraph:
        """Reconstruct an `OntologyGraph` from JSONL snapshot lines with full guardrail checks."""
        from frago.ontology.reasoning import deserialize_graph_jsonl

        return deserialize_graph_jsonl(jsonl_text)

    def link(
        self,
        source: OntologyEntity,
        predicate: str,
        target: OntologyEntity,
        *,
        replace_functional: bool = False,
    ) -> RelationFact:
        """Assert `(source, predicate, target)` after verifying all formal guardrails."""
        if predicate not in self._signatures:
            raise RelationError(f"Unregistered relation predicate: '{predicate}'.")

        sig = self._signatures[predicate]
        if not isinstance(source, sig.domain_types):
            expected_domain = ", ".join(t.__name__ for t in sig.domain_types)
            raise DomainRangeViolationError(
                f"Relation '{predicate}' domain violation: source '{type(source).__name__}' "
                f"is not an instance of ({expected_domain})."
            )
        if not isinstance(target, sig.range_types):
            expected_range = ", ".join(t.__name__ for t in sig.range_types)
            raise DomainRangeViolationError(
                f"Relation '{predicate}' range violation: target '{type(target).__name__}' "
                f"is not an instance of ({expected_range})."
            )

        if predicate in {"plays_role", "has_capability", "exhibits_state"}:
            bearer_types: tuple[str, ...] = getattr(target, "bearer_types", ())
            if bearer_types:
                source_tokens = {
                    type(source).__name__,
                    getattr(source, "domain_class_id", ""),
                    getattr(source, "actor_kind", ""),
                    getattr(source, "resource_kind", ""),
                } - {""}
                if not (source_tokens & set(bearer_types)):
                    raise DomainRangeViolationError(
                        f"Relation '{predicate}' bearer_type violation: target "
                        f"'{type(target).__name__}' requires bearer in {list(bearer_types)}, "
                        f"got '{ sorted(source_tokens) }'."
                    )

        source_id = self.register_entity(source)
        target_id = self.register_entity(target)

        props = sig.algebraic_properties

        if AlgebraicProperty.IRREFLEXIVE in props and source_id == target_id:
            raise AlgebraicAxiomViolationError(
                f"Relation '{predicate}' is irreflexive: '{source_id}' cannot link to itself."
            )

        if AlgebraicProperty.ASYMMETRIC in props and self._has_direct_edge(
            target_id, predicate, source_id
        ):
            raise AlgebraicAxiomViolationError(
                f"Relation '{predicate}' is asymmetric: reverse edge "
                f"('{target_id}' -> '{source_id}') already exists."
            )

        if (
            AlgebraicProperty.TRANSITIVE in props
            and AlgebraicProperty.IRREFLEXIVE in props
            and target_id in self._reachable_targets(target_id, predicate)
            or (
                AlgebraicProperty.TRANSITIVE in props
                and AlgebraicProperty.IRREFLEXIVE in props
                and source_id in self._reachable_targets(target_id, predicate)
            )
        ):
            raise AlgebraicAxiomViolationError(
                f"Relation '{predicate}' is transitive + irreflexive (strict DAG): "
                f"adding '{source_id}' -> '{target_id}' would create a dependency cycle."
            )

        if AlgebraicProperty.FUNCTIONAL in props:
            existing = [
                f
                for f in self._facts
                if f.source_id == source_id and f.predicate == predicate
            ]
            if existing:
                if existing[0].target_id == target_id:
                    return existing[0]
                if not replace_functional:
                    raise AlgebraicAxiomViolationError(
                        f"Relation '{predicate}' is functional: '{source_id}' already "
                        f"links to '{existing[0].target_id}' (cannot also link to '{target_id}')."
                    )
                self._facts = [
                    f
                    for f in self._facts
                    if not (f.source_id == source_id and f.predicate == predicate)
                ]

        for f in self._facts:
            if (
                f.source_id == source_id
                and f.predicate == predicate
                and f.target_id == target_id
            ):
                return f

        fact = RelationFact(
            source_id=source_id,
            predicate=predicate,
            target_id=target_id,
        )
        self._facts.append(fact)
        return fact

    def unlink(self, source_id: str, predicate: str, target_id: str) -> bool:
        """Remove a specific relation edge (e.g., when unmounting a context Role)."""
        before = len(self._facts)
        self._facts = [
            f
            for f in self._facts
            if not (
                f.source_id == source_id
                and f.predicate == predicate
                and f.target_id == target_id
            )
        ]
        return len(self._facts) < before

    def query_targets(
        self,
        source_id: str,
        predicate_or_inverse: str,
        *,
        include_transitive: bool = True,
    ) -> list[OntologyEntity]:
        """Query related target entities via primary predicate, inverse predicate, and transitive closure."""
        if predicate_or_inverse in self._signatures:
            sig = self._signatures[predicate_or_inverse]
            is_transitive = (
                include_transitive
                and AlgebraicProperty.TRANSITIVE in sig.algebraic_properties
            )
            if is_transitive:
                target_ids = self._reachable_targets(source_id, predicate_or_inverse)
            else:
                target_ids = [
                    f.target_id
                    for f in self._facts
                    if f.source_id == source_id and f.predicate == predicate_or_inverse
                ]
            return [self._entities[tid] for tid in target_ids if tid in self._entities]

        if predicate_or_inverse in self._inverse_to_primary:
            primary = self._inverse_to_primary[predicate_or_inverse]
            sig = self._signatures[primary]
            is_transitive = (
                include_transitive
                and AlgebraicProperty.TRANSITIVE in sig.algebraic_properties
            )
            if is_transitive:
                source_ids = self._reachable_sources(source_id, primary)
            else:
                source_ids = [
                    f.source_id
                    for f in self._facts
                    if f.target_id == source_id and f.predicate == primary
                ]
            return [self._entities[sid] for sid in source_ids if sid in self._entities]

        raise RelationError(
            f"Unknown predicate or inverse relation: '{predicate_or_inverse}'."
        )

    def _has_direct_edge(self, source_id: str, predicate: str, target_id: str) -> bool:
        return any(
            f.source_id == source_id
            and f.predicate == predicate
            and f.target_id == target_id
            for f in self._facts
        )

    def _reachable_targets(self, start_id: str, predicate: str) -> list[str]:
        visited: list[str] = []
        seen: set[str] = set()
        queue: deque[str] = deque([start_id])
        while queue:
            curr = queue.popleft()
            for f in self._facts:
                if f.source_id == curr and f.predicate == predicate and f.target_id not in seen:
                    seen.add(f.target_id)
                    visited.append(f.target_id)
                    queue.append(f.target_id)
        return visited

    def _reachable_sources(self, target_id: str, predicate: str) -> list[str]:
        visited: list[str] = []
        seen: set[str] = set()
        queue: deque[str] = deque([target_id])
        while queue:
            curr = queue.popleft()
            for f in self._facts:
                if f.target_id == curr and f.predicate == predicate and f.source_id not in seen:
                    seen.add(f.source_id)
                    visited.append(f.source_id)
                    queue.append(f.source_id)
        return visited
