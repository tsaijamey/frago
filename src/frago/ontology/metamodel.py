"""Upper ontology metamodel for the frago agent OS.

Encodes the three orthogonal axes (Mereotemporality, ExistentialDependence,
DirectionOfFit), the four mutually disjoint top-level quadrants (Continuant,
Occurrent, NormativeEntity, InformationEntity), and the four meta-axioms
(Identity Criterion +I, OntoClean Rigidity +R/~R, Mutability, Temporality).

Layer: pure ontology metamodel (no I/O, no imports from cli/ or server/).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Self


class OntologyError(Exception):
    """Base exception for all ontological axiom or contract violations."""


class OntoCleanViolationError(OntologyError):
    """Raised when OntoClean rigidity (+R / ~R) or quadrant disjointness is violated."""


class IdentityCriterionError(OntologyError):
    """Raised when an entity's identity criterion (+I) is missing or malformed."""


class MutabilityViolationError(OntologyError):
    """Raised when an operation violates a superclass's mutability or state-machine axiom."""


class Mereotemporality(str, Enum):
    """Axis 1: How an entity extends across time."""

    SNAPSHOT = "wholly_present_at_snapshot"
    TEMPORAL_PARTS = "unfolds_in_time_with_temporal_parts"
    SYMBOLIC_INVARIANT = "symbolic_or_normative"


class ExistentialDependence(str, Enum):
    """Axis 2: Whether an entity requires a bearer and context to exist."""

    INDEPENDENT = "independent"
    DEPENDENT = "requires_bearer_and_context"


class DirectionOfFit(str, Enum):
    """Axis 3: Searle's intentionality direction of fit."""

    REALITY = "reality"
    WORLD_TO_MIND = "world_to_mind_directive"
    MIND_TO_WORLD = "mind_to_world_representation"


class Rigidity(str, Enum):
    """OntoClean rigidity meta-property."""

    RIGID = "+R"
    ANTI_RIGID = "~R"


class MutabilityMode(str, Enum):
    """Data-layer mutability primitive locked by each superclass."""

    STATEFUL_VERSIONED = "stateful_versioned"
    LIFECYCLE_BOUND = "lifecycle_bound"
    STATE_MACHINE = "state_machine"
    APPEND_ONLY_IMMUTABLE = "append_only_immutable"
    VERSIONED_IMMUTABLE = "versioned_immutable"
    CONTENT_ADDRESSED = "content_addressed_or_append_only"


class UpperQuadrant(str, Enum):
    """The four mutually disjoint top-level quadrants under Thing."""

    CONTINUANT = "Continuant"
    OCCURRENT = "Occurrent"
    NORMATIVE = "NormativeEntity"
    INFORMATION = "InformationEntity"


class OntologyEntity:
    """Root class (`Thing`) of the frago upper ontology.

    Enforces two structural axioms at class creation time (`__init_subclass__`):
    1. Quadrant Disjointness: A subclass may not inherit from two distinct
       top-level quadrants.
    2. OntoClean Rigidity Guardrail: An anti-rigid (`~R`) concept MUST NEVER
       serve as a superclass for a rigid (`+R`) concept.
    """

    quadrant: ClassVar[UpperQuadrant | None] = None
    rigidity: ClassVar[Rigidity | None] = None
    mutability: ClassVar[MutabilityMode | None] = None
    mereotemporality: ClassVar[Mereotemporality | None] = None
    existential_dependence: ClassVar[ExistentialDependence | None] = None
    direction_of_fit: ClassVar[DirectionOfFit | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        parent_quadrants = {
            base.quadrant
            for base in cls.__mro__[1:]
            if issubclass(base, OntologyEntity) and getattr(base, "quadrant", None) is not None
        }
        if len(parent_quadrants) > 1:
            names = ", ".join(sorted(q.value for q in parent_quadrants if q is not None))
            raise OntoCleanViolationError(
                f"Class '{cls.__name__}' violates quadrant disjointness by inheriting "
                f"from multiple disjoint upper quadrants: {names}."
            )

        own_rigidity = cls.__dict__.get("rigidity", getattr(cls, "rigidity", None))
        if own_rigidity == Rigidity.RIGID:
            for base in cls.__mro__[1:]:
                if (
                    issubclass(base, OntologyEntity)
                    and getattr(base, "rigidity", None) == Rigidity.ANTI_RIGID
                ):
                    raise OntoCleanViolationError(
                        f"Class '{cls.__name__}' is Rigid (+R) but inherits from "
                        f"Anti-Rigid (~R) superclass '{base.__name__}'. "
                        f"Anti-rigid roles/states MUST NEVER subsume rigid entities."
                    )

    def ontological_id(self) -> str:
        """Return the canonical identity (+I) of this ontological instance."""
        raise NotImplementedError


# ============================================================================
# Quadrant 1: Continuant (IndependentContinuant vs. DependentContinuant)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class Continuant(OntologyEntity):
    """Entities that are wholly present at any snapshot in time."""

    quadrant: ClassVar[UpperQuadrant | None] = UpperQuadrant.CONTINUANT
    mereotemporality: ClassVar[Mereotemporality | None] = Mereotemporality.SNAPSHOT
    direction_of_fit: ClassVar[DirectionOfFit | None] = DirectionOfFit.REALITY


@dataclass(frozen=True, kw_only=True)
class IndependentContinuant(Continuant):
    """Rigid (+R) entities with an independent global UID and versioned state."""

    rigidity: ClassVar[Rigidity | None] = Rigidity.RIGID
    existential_dependence: ClassVar[ExistentialDependence | None] = (
        ExistentialDependence.INDEPENDENT
    )
    mutability: ClassVar[MutabilityMode | None] = MutabilityMode.STATEFUL_VERSIONED

    uid: str
    version: int = 1

    def __post_init__(self) -> None:
        if not self.uid or not self.uid.strip():
            raise IdentityCriterionError(
                f"{type(self).__name__} requires a non-empty global 'uid' (+I)."
            )
        if self.version < 1:
            raise IdentityCriterionError(
                f"{type(self).__name__} version must be >= 1, got {self.version}."
            )

    def ontological_id(self) -> str:
        return self.uid

    def advance_version(self, **updates: Any) -> Self:
        """Create the next state snapshot while preserving global identity (`uid`)."""
        if "uid" in updates and updates["uid"] != self.uid:
            raise MutabilityViolationError(
                f"Cannot mutate global identity 'uid' of {type(self).__name__} "
                f"('{self.uid}' -> '{updates['uid']}')."
            )
        updates["version"] = self.version + 1
        return dataclasses.replace(self, **updates)


@dataclass(frozen=True, kw_only=True)
class Actor(IndependentContinuant):
    """Independent agentive subject (`AgentKernel`, `HumanPrincipal`)."""

    actor_kind: str


@dataclass(frozen=True, kw_only=True)
class Resource(IndependentContinuant):
    """Independent asset or runtime substrate (`AgentHarness`, `RecipeModule`, `DataSlot`)."""

    resource_kind: str


@dataclass(frozen=True, kw_only=True)
class DependentContinuant(Continuant):
    """Anti-rigid (~R) entities that existentially depend on a bearer and context.

    Passes the Remove-Context Test: when the context ends or unbinds, the
    DependentContinuant ceases to exist while its bearer (`IndependentContinuant`)
    remains intact.
    """

    rigidity: ClassVar[Rigidity | None] = Rigidity.ANTI_RIGID
    existential_dependence: ClassVar[ExistentialDependence | None] = (
        ExistentialDependence.DEPENDENT
    )
    mutability: ClassVar[MutabilityMode | None] = MutabilityMode.LIFECYCLE_BOUND

    bearer_id: str
    context_id: str
    dependent_type: str

    def __post_init__(self) -> None:
        if not self.bearer_id or not self.bearer_id.strip():
            raise IdentityCriterionError(
                f"{type(self).__name__} requires a non-empty 'bearer_id' "
                f"(must inhere in an IndependentContinuant)."
            )
        if not self.context_id or not self.context_id.strip():
            raise IdentityCriterionError(
                f"{type(self).__name__} requires a non-empty 'context_id' "
                f"(scope-bound identity)."
            )
        if not self.dependent_type or not self.dependent_type.strip():
            raise IdentityCriterionError(
                f"{type(self).__name__} requires a non-empty 'dependent_type'."
            )

    def ontological_id(self) -> str:
        return f"{self.dependent_type}:{self.bearer_id}@{self.context_id}"


@dataclass(frozen=True, kw_only=True)
class Role(DependentContinuant):
    """Context-bound role played by an Actor or Resource."""


@dataclass(frozen=True, kw_only=True)
class Capability(DependentContinuant):
    """Declarative capability surface attached to a bearer (`@export`, `@action`, probes)."""


@dataclass(frozen=True, kw_only=True)
class QualityState(DependentContinuant):
    """Context or snapshot state exhibited by a Continuant (e.g. `SecurityZoneState`)."""

    value: str

    def ontological_id(self) -> str:
        return f"{self.dependent_type}={self.value}:{self.bearer_id}@{self.context_id}"


# ============================================================================
# Quadrant 2: Occurrent (Process vs. Event)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class Occurrent(OntologyEntity):
    """Entities that unfold across time and possess temporal parts."""

    quadrant: ClassVar[UpperQuadrant | None] = UpperQuadrant.OCCURRENT
    rigidity: ClassVar[Rigidity | None] = Rigidity.RIGID
    mereotemporality: ClassVar[Mereotemporality | None] = Mereotemporality.TEMPORAL_PARTS
    existential_dependence: ClassVar[ExistentialDependence | None] = (
        ExistentialDependence.INDEPENDENT
    )
    direction_of_fit: ClassVar[DirectionOfFit | None] = DirectionOfFit.REALITY


DEFAULT_PROCESS_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "error", "cancelled", "needs_input", "timeout"}),
    "needs_input": frozenset({"running", "completed", "error", "cancelled"}),
    "completed": frozenset(),
    "error": frozenset(),
    "cancelled": frozenset(),
    "timeout": frozenset(),
}


@dataclass(frozen=True, kw_only=True)
class Process(Occurrent):
    """Interval-based dynamic occurrence governed by a state machine."""

    mutability: ClassVar[MutabilityMode | None] = MutabilityMode.STATE_MACHINE
    allowed_transitions: ClassVar[Mapping[str, frozenset[str]]] = DEFAULT_PROCESS_TRANSITIONS

    process_uid: str
    process_kind: str
    state: str = "pending"
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.process_uid or not self.process_uid.strip():
            raise IdentityCriterionError("Process requires a non-empty 'process_uid'.")
        if self.state not in self.allowed_transitions:
            raise MutabilityViolationError(
                f"Unknown process state '{self.state}' for {type(self).__name__}. "
                f"Allowed states: {sorted(self.allowed_transitions.keys())}."
            )
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise MutabilityViolationError(
                f"Process 'ended_at' ({self.ended_at}) cannot precede "
                f"'started_at' ({self.started_at})."
            )

    def ontological_id(self) -> str:
        return self.process_uid

    def transition_to(
        self,
        next_state: str,
        *,
        ended_at: datetime | None = None,
    ) -> Self:
        """Advance the process along a legal state-machine edge."""
        reachable = self.allowed_transitions.get(self.state, frozenset())
        if next_state not in reachable:
            raise MutabilityViolationError(
                f"Illegal state transition for process '{self.process_uid}': "
                f"'{self.state}' -> '{next_state}'. "
                f"Allowed from '{self.state}': {sorted(reachable)}."
            )
        terminal = len(self.allowed_transitions.get(next_state, frozenset())) == 0
        resolved_end = ended_at or (datetime.now() if terminal else self.ended_at)
        return dataclasses.replace(self, state=next_state, ended_at=resolved_end)


@dataclass(frozen=True, kw_only=True)
class Event(Occurrent):
    """Instantaneous, append-only immutable fact (`SessionStepEvent`, `HookLifecycleEvent`)."""

    mutability: ClassVar[MutabilityMode | None] = MutabilityMode.APPEND_ONLY_IMMUTABLE

    event_type: str
    causal_source_id: str
    occurred_at: datetime = field(default_factory=datetime.now)
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type or not self.event_type.strip():
            raise IdentityCriterionError("Event requires a non-empty 'event_type'.")
        if not self.causal_source_id or not self.causal_source_id.strip():
            raise IdentityCriterionError("Event requires a non-empty 'causal_source_id'.")

    def ontological_id(self) -> str:
        """Deterministic causal identity (+I): timestamp + causal_source + payload hash."""
        canonical_payload = json.dumps(self.payload, sort_keys=True, ensure_ascii=False)
        raw = f"{self.occurred_at.isoformat()}|{self.causal_source_id}|{self.event_type}|{canonical_payload}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"evt:{self.event_type}:{digest}"


# ============================================================================
# Quadrant 3: NormativeEntity (RulePolicy, Contract, Specification)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class NormativeEntity(OntologyEntity):
    """World-to-Mind directives that govern processes, roles, and actions."""

    quadrant: ClassVar[UpperQuadrant | None] = UpperQuadrant.NORMATIVE
    rigidity: ClassVar[Rigidity | None] = Rigidity.RIGID
    mutability: ClassVar[MutabilityMode | None] = MutabilityMode.VERSIONED_IMMUTABLE
    mereotemporality: ClassVar[Mereotemporality | None] = Mereotemporality.SYMBOLIC_INVARIANT
    existential_dependence: ClassVar[ExistentialDependence | None] = (
        ExistentialDependence.INDEPENDENT
    )
    direction_of_fit: ClassVar[DirectionOfFit | None] = DirectionOfFit.WORLD_TO_MIND

    norm_id: str
    semantic_version: str = "1.0.0"
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.norm_id or not self.norm_id.strip():
            raise IdentityCriterionError("NormativeEntity requires a non-empty 'norm_id'.")
        if not self.semantic_version or not self.semantic_version.strip():
            raise IdentityCriterionError(
                "NormativeEntity requires a non-empty 'semantic_version'."
            )
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise MutabilityViolationError(
                f"NormativeEntity '{self.norm_id}' valid_until ({self.valid_until}) "
                f"cannot precede valid_from ({self.valid_from})."
            )

    def ontological_id(self) -> str:
        return f"{self.norm_id}@{self.semantic_version}"

    def is_effective_at(self, moment: datetime) -> bool:
        """Check whether this normative version is active at the given timestamp."""
        if self.valid_from is not None and moment < self.valid_from:
            return False
        return not (self.valid_until is not None and moment > self.valid_until)

    def supersede(self, new_version: str, **updates: Any) -> Self:
        """Produce a new immutable version snapshot; never overwrites prior versions."""
        if new_version == self.semantic_version:
            raise MutabilityViolationError(
                f"NormativeEntity '{self.norm_id}' is versioned_immutable; "
                f"superseding requires a distinct semantic_version (got '{new_version}')."
            )
        updates["semantic_version"] = new_version
        return dataclasses.replace(self, **updates)


@dataclass(frozen=True, kw_only=True)
class RulePolicy(NormativeEntity):
    """Declarative policy or hook rule (`HookInjectionRule`, `TeamPairingSecurityPolicy`)."""

    rule_kind: str


@dataclass(frozen=True, kw_only=True)
class Contract(NormativeEntity):
    """Formal behavioral or module contract (`RecipeModuleContract`, `ActionContract`)."""

    contract_kind: str


@dataclass(frozen=True, kw_only=True)
class Specification(NormativeEntity):
    """Declarative template or specification (`RecipeSpec`, `DomainSchemaSpec`)."""

    spec_kind: str


# ============================================================================
# Quadrant 4: InformationEntity (KnowledgeArtifact, TranscriptArtifact, etc.)
# ============================================================================


def compute_content_hash(content: str | bytes) -> str:
    """Compute a canonical SHA-256 content hash for an InformationEntity."""
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, kw_only=True)
class InformationEntity(OntologyEntity):
    """Mind-to-World symbolic carriers decoupled from physical runtime actors."""

    quadrant: ClassVar[UpperQuadrant | None] = UpperQuadrant.INFORMATION
    rigidity: ClassVar[Rigidity | None] = Rigidity.RIGID
    mutability: ClassVar[MutabilityMode | None] = MutabilityMode.CONTENT_ADDRESSED
    mereotemporality: ClassVar[Mereotemporality | None] = Mereotemporality.SYMBOLIC_INVARIANT
    existential_dependence: ClassVar[ExistentialDependence | None] = (
        ExistentialDependence.INDEPENDENT
    )
    direction_of_fit: ClassVar[DirectionOfFit | None] = DirectionOfFit.MIND_TO_WORLD

    artifact_uri: str
    content_hash: str
    artifact_kind: str

    def __post_init__(self) -> None:
        if not self.artifact_uri or not self.artifact_uri.strip():
            raise IdentityCriterionError(
                "InformationEntity requires a non-empty 'artifact_uri'."
            )
        if not self.content_hash or not self.content_hash.strip():
            raise IdentityCriterionError(
                "InformationEntity requires a non-empty 'content_hash'."
            )

    def ontological_id(self) -> str:
        return f"{self.artifact_uri}#{self.content_hash[:12]}"


@dataclass(frozen=True, kw_only=True)
class KnowledgeArtifact(InformationEntity):
    """Conclusion-layer or companion knowledge document (`BookTopicDocument`, `DefKnowledgeEntry`)."""


@dataclass(frozen=True, kw_only=True)
class TranscriptArtifact(InformationEntity):
    """Process-layer JSONL session trace (`SessionTranscriptArtifact`)."""


@dataclass(frozen=True, kw_only=True)
class CoordinationArtifact(InformationEntity):
    """Cross-session handoff or human authorization receipt (`TodoHandoffArtifact`, `HumanDecisionReceipt`)."""
