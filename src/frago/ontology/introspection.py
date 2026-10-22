"""Ontology schema loader, integrity validator, and full-graph introspector.

Exposes the fourth litmus test of a true operational ontology:
Full-graph self-explanation (`Introspection`). AI agents, CLI tools, and the
Harness can query:
1. Which orthogonal quadrant and rigidity axiom govern any domain concept.
2. Which existing Python modules map to which ontological classes.
3. Which kinetic action contracts an initiator (`Actor` or `Role`) may invoke
   against a target (`Resource`), along with their preconditions and side effects.

Layer: pure ontology metamodel (reads only the package-internal `frago.json`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from frago.ontology.contracts import (
    ActionSignature,
    ConditionCheck,
    OntologicalActionContract,
    SideEffectSpec,
)
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
    Rigidity,
    Role,
    RulePolicy,
    Specification,
    UpperQuadrant,
)

ONTOLOGY_SCHEMA_PATH = Path(__file__).parent / "frago.json"


class SchemaIntegrityError(OntologyError):
    """Raised when `frago.json` violates structural or OntoClean rules."""


def load_ontology_schema(schema_path: Path | None = None) -> dict[str, Any]:
    """Load the JSON ontology definition from disk."""
    target = schema_path if schema_path is not None else ONTOLOGY_SCHEMA_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SchemaIntegrityError("Root of frago.json must be a JSON object.")
    return data


class OntologyIntrospector:
    """Self-explanation and validation engine over `frago.json`."""

    def __init__(self, schema: dict[str, Any] | None = None) -> None:
        self._schema: dict[str, Any] = (
            schema if schema is not None else load_ontology_schema()
        )

    @property
    def schema(self) -> dict[str, Any]:
        return self._schema

    def validate_schema_integrity(self) -> list[str]:
        """Verify structural completeness and OntoClean axioms across the JSON schema.

        Returns a list of violation messages (empty list means 100% valid).
        """
        problems: list[str] = []

        required_top_keys = (
            "orthogonal_axes",
            "upper_ontology",
            "relation_signatures",
            "domain_classes",
            "defined_classes",
            "kinetic_action_contracts",
        )
        for key in required_top_keys:
            if key not in self._schema:
                problems.append(f"Missing required top-level key: '{key}'.")

        if problems:
            return problems

        upper = self._schema["upper_ontology"]
        expected_quadrants = {q.value for q in UpperQuadrant}
        thing_subs = set(upper.get("Thing", {}).get("subclasses", []))
        if thing_subs != expected_quadrants:
            problems.append(
                f"Thing.subclasses ({sorted(thing_subs)}) must match the 4 orthogonal "
                f"quadrants ({sorted(expected_quadrants)})."
            )

        domain_groups: dict[str, list[dict[str, Any]]] = self._schema["domain_classes"]
        seen_class_ids: set[str] = set()

        for group_path, classes in domain_groups.items():
            parts = group_path.split(".")
            root_quadrant = parts[0]
            if root_quadrant not in expected_quadrants:
                problems.append(
                    f"Domain group '{group_path}' does not start with a valid quadrant."
                )

            is_dependent_branch = "DependentContinuant" in parts
            for cls_def in classes:
                cid = cls_def.get("class_id", "")
                if not cid:
                    problems.append(f"Unnamed class in group '{group_path}'.")
                    continue
                if cid in seen_class_ids:
                    problems.append(f"Duplicate class_id '{cid}' in domain_classes.")
                seen_class_ids.add(cid)

                rigidity = cls_def.get("rigidity")
                if is_dependent_branch and rigidity != Rigidity.ANTI_RIGID.value:
                    problems.append(
                        f"Class '{cid}' under DependentContinuant must have "
                        f"rigidity '~R', got '{rigidity}'."
                    )
                if (
                    "IndependentContinuant" in parts
                    and rigidity != Rigidity.RIGID.value
                ):
                    problems.append(
                        f"Class '{cid}' under IndependentContinuant must have "
                        f"rigidity '+R', got '{rigidity}'."
                    )

        for action in self._schema["kinetic_action_contracts"]:
            aid = action.get("action_id", "<unnamed>")
            for ring_key in ("parameters", "signature", "contract"):
                if ring_key not in action:
                    problems.append(
                        f"Action contract '{aid}' missing concentric ring '{ring_key}'."
                    )
            contract_block = action.get("contract", {})
            for clause in ("preconditions", "postconditions", "invariants", "side_effects"):
                if clause not in contract_block:
                    problems.append(
                        f"Action contract '{aid}' missing contract clause '{clause}'."
                    )

        return problems

    def list_quadrants(self) -> list[str]:
        """Return the four orthogonal top-level quadrant names."""
        return list(self._schema["upper_ontology"]["Thing"]["subclasses"])

    def get_domain_class(self, class_id: str) -> dict[str, Any] | None:
        """Look up a specific domain class definition by `class_id`, enriched with `hierarchy_path`."""
        for group_path, classes in self._schema.get("domain_classes", {}).items():
            for cls_def in classes:
                if cls_def.get("class_id") == class_id:
                    enriched = dict(cls_def)
                    enriched["hierarchy_path"] = group_path
                    return enriched
        return None

    def find_classes_by_quadrant(self, quadrant: str) -> list[dict[str, Any]]:
        """Return all domain classes belonging to a given top-level quadrant."""
        results: list[dict[str, Any]] = []
        for group_path, classes in self._schema.get("domain_classes", {}).items():
            if group_path == quadrant or group_path.startswith(f"{quadrant}."):
                for cls_def in classes:
                    enriched = dict(cls_def)
                    enriched["hierarchy_path"] = group_path
                    results.append(enriched)
        return results

    def find_classes_by_code_path(self, path_fragment: str) -> list[dict[str, Any]]:
        """Find all ontological classes mapped to a given repository file or module path."""
        results: list[dict[str, Any]] = []
        for group_path, classes in self._schema.get("domain_classes", {}).items():
            for cls_def in classes:
                locations: list[str] = cls_def.get("current_code_locations", [])
                if any(path_fragment in loc for loc in locations):
                    enriched = dict(cls_def)
                    enriched["hierarchy_path"] = group_path
                    results.append(enriched)
        return results

    def get_allowed_actions_for(
        self,
        initiator_class_id: str,
        target_class_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query kinetic action contracts that `initiator_class_id` is permitted to initiate."""
        initiator_info = self.get_domain_class(initiator_class_id)
        initiator_tokens = {initiator_class_id}
        if initiator_info is not None:
            initiator_tokens.update(initiator_info["hierarchy_path"].split("."))

        target_tokens: set[str] = set()
        if target_class_id is not None:
            target_tokens.add(target_class_id)
            target_info = self.get_domain_class(target_class_id)
            if target_info is not None:
                target_tokens.update(target_info["hierarchy_path"].split("."))

        matched: list[dict[str, Any]] = []
        for action in self._schema.get("kinetic_action_contracts", []):
            sig = action.get("signature", {})
            allowed_initiators = {
                tok.strip() for tok in sig.get("initiator_domain", "").split("|") if tok.strip()
            }
            if not (initiator_tokens & allowed_initiators):
                continue

            if target_class_id is not None:
                allowed_targets = {
                    tok.strip() for tok in sig.get("target_range", "").split("|") if tok.strip()
                }
                if not (target_tokens & allowed_targets):
                    continue

            matched.append(action)

        return matched

    def explain_entity_relations(
        self,
        class_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return outgoing and incoming first-class relations applicable to `class_id`."""
        info = self.get_domain_class(class_id)
        if info is None:
            raise OntologyError(f"Unknown domain class_id: '{class_id}'.")

        lineage_tokens = set(info["hierarchy_path"].split(".")) | {class_id}
        outgoing: list[dict[str, Any]] = []
        incoming: list[dict[str, Any]] = []

        for pred, rel_def in self._schema.get("relation_signatures", {}).items():
            domain_tokens = {
                t.strip() for t in rel_def.get("domain", "").split("|") if t.strip()
            }
            range_tokens = {
                t.strip() for t in rel_def.get("range", "").split("|") if t.strip()
            }
            entry = {"predicate": pred, **rel_def}
            if lineage_tokens & domain_tokens:
                outgoing.append(entry)
            if lineage_tokens & range_tokens:
                incoming.append(entry)

        return {"outgoing": outgoing, "incoming": incoming}

    def create_quality_state(
        self,
        class_id: str,
        *,
        bearer_id: str,
        context_id: str,
        value: str,
    ) -> QualityState:
        """Instantiate a `QualityState` validated against `allowed_values` in `frago.json`."""
        from frago.ontology.registry import DomainClassRegistry

        reg = DomainClassRegistry(self._schema)
        info = self.get_domain_class(class_id)
        if info is None or info["hierarchy_path"] != "Continuant.DependentContinuant.QualityState":
            raise SchemaIntegrityError(
                f"'{class_id}' is not registered under Continuant.DependentContinuant.QualityState in frago.json."
            )
        entity = reg.create(
            class_id,
            bearer_id=bearer_id,
            context_id=context_id,
            value=value,
        )
        return cast(QualityState, entity)

    def create_process(
        self,
        class_id: str,
        *,
        process_uid: str,
        state: str | None = None,
    ) -> Process:
        """Instantiate a `Process` whose allowed states are governed by `frago.json`."""
        from frago.ontology.registry import DomainClassRegistry

        reg = DomainClassRegistry(self._schema)
        info = self.get_domain_class(class_id)
        if info is None or info["hierarchy_path"] != "Occurrent.Process":
            raise SchemaIntegrityError(
                f"'{class_id}' is not registered under Occurrent.Process in frago.json."
            )
        entity = reg.create(class_id, process_uid=process_uid, state=state)
        return cast(Process, entity)

    def instantiate_domain_entity(
        self,
        class_id: str,
        **kwargs: Any,
    ) -> OntologyEntity:
        """Construct a strongly-typed `OntologyEntity` instance driven by `frago.json`."""
        from frago.ontology.registry import DomainClassRegistry

        reg = DomainClassRegistry(self._schema)
        return reg.create(class_id, **kwargs)

    def build_action_contract(
        self,
        action_id: str,
        *,
        preconditions: tuple[ConditionCheck, ...] = (),
        postconditions: tuple[ConditionCheck, ...] = (),
        invariants: tuple[ConditionCheck, ...] = (),
    ) -> OntologicalActionContract:
        """Build an `OntologicalActionContract` directly from `frago.json`."""
        matched = next(
            (
                a
                for a in self._schema.get("kinetic_action_contracts", [])
                if a.get("action_id") == action_id
            ),
            None,
        )
        if matched is None:
            raise SchemaIntegrityError(
                f"Unknown action_id '{action_id}' in frago.json kinetic_action_contracts."
            )

        sig_block: Mapping[str, Any] = matched["signature"]
        initiator_types = self._resolve_contract_types(str(sig_block["initiator_domain"]))
        target_types = self._resolve_contract_types(str(sig_block["target_range"]))
        fx_block: Mapping[str, Any] = matched["contract"].get("side_effects", {})

        return OntologicalActionContract(
            norm_id=action_id,
            signature=ActionSignature(
                parameters=tuple(str(p) for p in matched["parameters"]),
                initiator_types=initiator_types,
                target_types=target_types,
            ),
            preconditions=preconditions,
            postconditions=postconditions,
            invariants=invariants,
            side_effects=SideEffectSpec(
                initiates_process=fx_block.get("initiates"),
                mutates_targets=tuple(fx_block.get("mutates", [])),
                emits_events=tuple(fx_block.get("emits", [])),
                produces_artifacts=tuple(fx_block.get("produces", [])),
            ),
        )

    def _resolve_contract_types(
        self,
        expr: str,
    ) -> tuple[type[OntologyEntity], ...]:
        branch_map: dict[str, type[OntologyEntity]] = {
            "Actor": Actor,
            "Resource": Resource,
            "Role": Role,
            "Capability": Capability,
            "QualityState": QualityState,
            "Process": Process,
            "Event": Event,
            "NormativeEntity": NormativeEntity,
            "RulePolicy": RulePolicy,
            "Contract": Contract,
            "Specification": Specification,
            "InformationEntity": InformationEntity,
        }
        resolved: list[type[OntologyEntity]] = []
        for token in (t.strip() for t in expr.split("|") if t.strip()):
            if token in branch_map:
                if branch_map[token] not in resolved:
                    resolved.append(branch_map[token])
                continue
            info = self.get_domain_class(token)
            if info is not None:
                leaf = info["hierarchy_path"].split(".")[-1]
                mapped = branch_map.get(leaf, OntologyEntity)
                if mapped not in resolved:
                    resolved.append(mapped)
        return tuple(resolved)
