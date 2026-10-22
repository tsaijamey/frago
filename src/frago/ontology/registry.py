"""Schema-driven dynamic domain class compiler and registry (`DomainClassRegistry`).

Transforms `src/frago/ontology/frago.json` from a passive descriptive catalog into
the active, authoritative class factory for all 63 domain concepts across the four
orthogonal quadrants (`Continuant`, `Occurrent`, `NormativeEntity`, `InformationEntity`).

Every domain class declared in `frago.json` is compiled into a strongly-typed Python
subclass of its upper-ontology base class (`Actor`, `Resource`, `Role`, `Capability`,
`QualityState`, `Process`, `Event`, `RulePolicy`, `Contract`, `Specification`,
`InformationEntity`) and automatically passes through:
1. `OntologyEntity.__init_subclass__` (OntoClean rigidity `+R`/`~R` and quadrant disjointness).
2. Domain-specific `allowed_values` validation on `QualityState` subclasses.
3. Domain-specific state-machine `states` validation on `Process` subclasses.
4. Domain-specific `bearer_type` and `context_type` metadata on `Role` and `Capability` subclasses.

Layer: pure ontology metamodel (reads only `frago.json`; zero imports from business packages).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from frago.ontology.introspection import SchemaIntegrityError, load_ontology_schema
from frago.ontology.metamodel import (
     DEFAULT_PROCESS_TRANSITIONS,
    Actor,
    Capability,
    Contract,
    Event,
    InformationEntity,
    MutabilityViolationError,
    OntologyEntity,
    Process,
    QualityState,
    Resource,
    Rigidity,
    Role,
    RulePolicy,
    Specification,
    compute_content_hash,
)

_HIERARCHY_BASE_MAP: dict[str, type[OntologyEntity]] = {
    "Continuant.IndependentContinuant.Actor": Actor,
    "Continuant.IndependentContinuant.Resource": Resource,
    "Continuant.DependentContinuant.Role": Role,
    "Continuant.DependentContinuant.Capability": Capability,
    "Continuant.DependentContinuant.QualityState": QualityState,
    "Occurrent.Process": Process,
    "Occurrent.Event": Event,
    "NormativeEntity.RulePolicy": RulePolicy,
    "NormativeEntity.Contract": Contract,
    "NormativeEntity.Specification": Specification,
    "InformationEntity": InformationEntity,
}


def _parse_pipe_tokens(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(tok.strip() for tok in raw.split("|") if tok.strip())


def _build_state_transitions(states: list[str]) -> Mapping[str, frozenset[str]]:
    """Build a domain state-machine transition map from the schema's ordered `states` list."""
    all_states = frozenset(states)
    return {state: all_states - {state} for state in states}


class DomainClassRegistry:
    """Compiles and caches Python `OntologyEntity` subclasses for every class in `frago.json`."""

    def __init__(self, schema: Mapping[str, Any] | None = None) -> None:
        self._schema: Mapping[str, Any] = (
            schema if schema is not None else load_ontology_schema()
        )
        self._classes: dict[str, type[OntologyEntity]] = {}
        self._specs: dict[str, dict[str, Any]] = {}
        self._compile_all()

    @property
    def classes(self) -> dict[str, type[OntologyEntity]]:
        """Return a snapshot mapping `class_id -> compiled Python subclass`."""
        return dict(self._classes)

    def get_class(self, class_id: str) -> type[OntologyEntity]:
        """Look up the compiled Python subclass for `class_id`."""
        if class_id not in self._classes:
            raise SchemaIntegrityError(
                f"Unknown domain class_id '{class_id}' in DomainClassRegistry."
            )
        return self._classes[class_id]

    def get_spec(self, class_id: str) -> dict[str, Any]:
        """Return the raw JSON specification dictionary for `class_id`."""
        if class_id not in self._specs:
            raise SchemaIntegrityError(
                f"Unknown domain class_id '{class_id}' in DomainClassRegistry."
            )
        return dict(self._specs[class_id])

    def create(self, class_id: str, **kwargs: Any) -> OntologyEntity:
        """Instantiate a compiled domain class by `class_id` with schema-validated defaults."""
        cls = self.get_class(class_id)
        spec = self._specs[class_id]
        hpath = spec["hierarchy_path"]

        if hpath == "Continuant.IndependentContinuant.Actor":
            return cls(
                uid=str(kwargs["uid"]),
                actor_kind=class_id,
                version=int(kwargs.get("version", 1)),
            )  # type: ignore[call-arg]

        if hpath == "Continuant.IndependentContinuant.Resource":
            return cls(
                uid=str(kwargs["uid"]),
                resource_kind=class_id,
                version=int(kwargs.get("version", 1)),
            )  # type: ignore[call-arg]

        if hpath in {
            "Continuant.DependentContinuant.Role",
            "Continuant.DependentContinuant.Capability",
        }:
            return cls(
                bearer_id=str(kwargs["bearer_id"]),
                context_id=str(kwargs["context_id"]),
                dependent_type=class_id,
            )  # type: ignore[call-arg]

        if hpath == "Continuant.DependentContinuant.QualityState":
            return cls(
                bearer_id=str(kwargs["bearer_id"]),
                context_id=str(kwargs["context_id"]),
                dependent_type=class_id,
                value=str(kwargs["value"]),
            )  # type: ignore[call-arg]

        if hpath == "Occurrent.Process":
            schema_states: list[str] | None = spec.get("states")
            default_state = schema_states[0] if schema_states else "pending"
            state_val = str(kwargs.get("state") or default_state)
            init_kwargs: dict[str, Any] = {
                "process_uid": str(kwargs["process_uid"]),
                "process_kind": class_id,
                "state": state_val,
            }
            if "started_at" in kwargs:
                init_kwargs["started_at"] = kwargs["started_at"]
            if "ended_at" in kwargs:
                init_kwargs["ended_at"] = kwargs["ended_at"]
            return cls(**init_kwargs)

        if hpath == "Occurrent.Event":
            init_kwargs = {
                "event_type": str(kwargs.get("event_type", class_id)),
                "causal_source_id": str(kwargs["causal_source_id"]),
                "payload": kwargs.get("payload", {}),
            }
            if "occurred_at" in kwargs:
                init_kwargs["occurred_at"] = kwargs["occurred_at"]
            return cls(**init_kwargs)

        if hpath == "NormativeEntity.RulePolicy":
            return cls(
                norm_id=str(kwargs.get("norm_id", class_id)),
                semantic_version=str(kwargs.get("semantic_version", "1.0.0")),
                rule_kind=class_id,
                valid_from=kwargs.get("valid_from"),
                valid_until=kwargs.get("valid_until"),
            )  # type: ignore[call-arg]

        if hpath == "NormativeEntity.Contract":
            return cls(
                norm_id=str(kwargs.get("norm_id", class_id)),
                semantic_version=str(kwargs.get("semantic_version", "1.0.0")),
                contract_kind=class_id,
                valid_from=kwargs.get("valid_from"),
                valid_until=kwargs.get("valid_until"),
            )  # type: ignore[call-arg]

        if hpath == "NormativeEntity.Specification":
            return cls(
                norm_id=str(kwargs.get("norm_id", class_id)),
                semantic_version=str(kwargs.get("semantic_version", "1.0.0")),
                spec_kind=class_id,
                valid_from=kwargs.get("valid_from"),
                valid_until=kwargs.get("valid_until"),
            )  # type: ignore[call-arg]

        if hpath == "InformationEntity":
            content = kwargs.get("content", "")
            chash = str(kwargs.get("content_hash") or compute_content_hash(content))
            return cls(
                artifact_uri=str(kwargs["artifact_uri"]),
                content_hash=chash,
                artifact_kind=class_id,
            )  # type: ignore[call-arg]

        raise SchemaIntegrityError(f"Unsupported hierarchy_path '{hpath}' for '{class_id}'.")

    def _compile_all(self) -> None:
        domain_groups: Mapping[str, list[dict[str, Any]]] = self._schema.get(
            "domain_classes", {}
        )
        for group_path, class_defs in domain_groups.items():
            if group_path not in _HIERARCHY_BASE_MAP:
                raise SchemaIntegrityError(
                    f"Unknown hierarchy_path '{group_path}' in frago.json domain_classes."
                )
            base_cls = _HIERARCHY_BASE_MAP[group_path]
            for raw_spec in class_defs:
                cid = str(raw_spec["class_id"])
                enriched_spec = dict(raw_spec)
                enriched_spec["hierarchy_path"] = group_path
                self._specs[cid] = enriched_spec
                self._classes[cid] = self._compile_single_class(
                    cid, base_cls, enriched_spec
                )

    def _compile_single_class(
        self,
        class_id: str,
        base_cls: type[OntologyEntity],
        spec: dict[str, Any],
    ) -> type[OntologyEntity]:
        rigidity_str = str(spec.get("rigidity", "+R"))
        rigidity_enum = Rigidity(rigidity_str)
        allowed_values_raw: list[str] | None = spec.get("allowed_values")
        allowed_values_tuple: tuple[str, ...] | None = (
            tuple(allowed_values_raw) if allowed_values_raw is not None else None
        )
        schema_states: list[str] | None = spec.get("states")
        transitions = (
            _build_state_transitions(schema_states)
            if schema_states
            else DEFAULT_PROCESS_TRANSITIONS
        )

        namespace: dict[str, Any] = {
            "__doc__": str(spec.get("description", "")),
            "rigidity": rigidity_enum,
            "domain_class_id": class_id,
            "pillar": str(spec.get("pillar", "")),
            "hierarchy_path": str(spec["hierarchy_path"]),
            "current_code_locations": tuple(spec.get("current_code_locations", [])),
            "bearer_types": _parse_pipe_tokens(spec.get("bearer_type")),
            "context_types": _parse_pipe_tokens(spec.get("context_type")),
            "allowed_values": allowed_values_tuple,
        }

        if issubclass(base_cls, Process):
            namespace["allowed_transitions"] = transitions

        if issubclass(base_cls, QualityState) and allowed_values_tuple is not None:
            allowed_set = frozenset(allowed_values_tuple)

            def _qs_post_init(self: QualityState) -> None:
                QualityState.__post_init__(self)
                if self.value not in allowed_set:
                    raise MutabilityViolationError(
                        f"QualityState '{class_id}' value '{self.value}' is not in "
                        f"allowed_values {list(allowed_values_tuple)} from frago.json."
                    )

            namespace["__post_init__"] = _qs_post_init

        compiled = type(class_id, (base_cls,), namespace)
        assert issubclass(compiled, OntologyEntity)
        return compiled


DEFAULT_DOMAIN_REGISTRY = DomainClassRegistry()
