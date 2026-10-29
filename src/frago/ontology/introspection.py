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

import copy
import json
from collections.abc import Mapping, Sequence
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
USER_ONTOLOGY_DIR = Path.home() / ".frago" / "ontology"


class SchemaIntegrityError(OntologyError):
    """Raised when `frago.json` or a user overlay violates structural or OntoClean rules."""


def _collect_user_overlay_files(user_dir: Path | None) -> list[Path]:
    """Discover user ontology overlay JSON files under `~/.frago/ontology/`.

    Loads `user-ontology.json` first (if present) and then `domains/*.json` in
    sorted order. Ignores any legacy backup named `frago.json` so an old repo
    snapshot does not shadow the package-shipped builtin schema.
    """
    if user_dir is None or not user_dir.exists() or not user_dir.is_dir():
        return []

    files: list[Path] = []
    main_overlay = user_dir / "user-ontology.json"
    if main_overlay.is_file():
        files.append(main_overlay)

    domains_dir = user_dir / "domains"
    if domains_dir.is_dir():
        files.extend(sorted(p for p in domains_dir.glob("*.json") if p.is_file()))

    for extra in sorted(user_dir.glob("*.json")):
        if extra.name not in {"frago.json", "user-ontology.json"} and extra.is_file():
            files.append(extra)

    return files


def merge_user_ontology_overlay(
    base_schema: Mapping[str, Any],
    overlay: Mapping[str, Any],
    *,
    source_label: str = "userdir",
) -> dict[str, Any]:
    """Overlay user-defined ontology classes, relations, and action contracts onto the builtin base.

    Conflict & protection rules (modeled after `hook-rules` builtin + userdir merge):
    1. Immutable upper axioms (`orthogonal_axes`, `upper_ontology`) are locked by builtin;
       any attempt to alter or override them in a user overlay raises `SchemaIntegrityError`.
    2. Builtin `domain_classes` have locked `hierarchy_path` and `rigidity`: a user overlay
       may add new domain classes (tagged with `source=source_label`) or extend metadata on an
       existing class within the same `hierarchy_path` and `rigidity`, but cannot move a
       builtin class to another quadrant/superclass or flip its `+R`/`~R` rigidity.
    3. `relation_signatures`, `defined_classes`, and `kinetic_action_contracts` merge by key
       (`predicate`, `class_id`, `action_id`), where user entries append or override by ID
       and are validated by `OntologyIntrospector.validate_schema_integrity()`.
    """
    for locked_key in ("orthogonal_axes", "upper_ontology"):
        if locked_key in overlay and overlay[locked_key] != base_schema.get(locked_key):
            raise SchemaIntegrityError(
                f"User ontology overlay ({source_label}) cannot modify locked upper-ontology "
                f"key '{locked_key}'."
            )

    merged: dict[str, Any] = copy.deepcopy(dict(base_schema))

    # Tag builtin classes if not already tagged
    builtin_index: dict[str, tuple[str, dict[str, Any]]] = {}
    for group_path, class_list in merged.get("domain_classes", {}).items():
        for cls_def in class_list:
            cls_def.setdefault("source", "builtin")
            cid = str(cls_def.get("class_id", ""))
            if cid:
                builtin_index[cid] = (group_path, cls_def)

    overlay_domains = overlay.get("domain_classes", {})
    if not isinstance(overlay_domains, Mapping):
        raise SchemaIntegrityError(
            f"User ontology overlay ({source_label}) 'domain_classes' must be a JSON object."
        )

    for group_path, user_classes in overlay_domains.items():
        if not isinstance(user_classes, Sequence):
            raise SchemaIntegrityError(
                f"User ontology overlay ({source_label}) group '{group_path}' must be a list."
            )
        target_list = merged.setdefault("domain_classes", {}).setdefault(group_path, [])
        for raw_cls in user_classes:
            if not isinstance(raw_cls, Mapping):
                raise SchemaIntegrityError(
                    f"Each entry in '{group_path}' ({source_label}) must be a JSON object."
                )
            cid = str(raw_cls.get("class_id", "")).strip()
            if not cid:
                raise SchemaIntegrityError(
                    f"Unnamed class in '{group_path}' from overlay ({source_label})."
                )
            user_cls = dict(raw_cls)
            user_cls.setdefault("source", source_label)

            if cid in builtin_index:
                orig_group, orig_def = builtin_index[cid]
                if orig_group != group_path:
                    raise SchemaIntegrityError(
                        f"User overlay ({source_label}) cannot move class '{cid}' from "
                        f"'{orig_group}' to '{group_path}'."
                    )
                if (
                    "rigidity" in user_cls
                    and user_cls["rigidity"] != orig_def.get("rigidity")
                ):
                    raise SchemaIntegrityError(
                        f"User overlay ({source_label}) cannot change rigidity of class "
                        f"'{cid}' ('{orig_def.get('rigidity')}' -> '{user_cls['rigidity']}')."
                    )
                merged_cls = {**orig_def, **user_cls, "source": user_cls["source"]}
                for idx, existing in enumerate(target_list):
                    if existing.get("class_id") == cid:
                        target_list[idx] = merged_cls
                        break
                builtin_index[cid] = (group_path, merged_cls)
            else:
                target_list.append(user_cls)
                builtin_index[cid] = (group_path, user_cls)

    overlay_rels = overlay.get("relation_signatures", {})
    if isinstance(overlay_rels, Mapping):
        merged_rels = merged.setdefault("relation_signatures", {})
        for pred, rel_spec in overlay_rels.items():
            if isinstance(rel_spec, Mapping):
                merged_rels[str(pred)] = {**rel_spec, "source": source_label}

    overlay_defined = overlay.get("defined_classes", {})
    if isinstance(overlay_defined, Mapping):
        merged_def = merged.setdefault("defined_classes", {})
        for def_id, def_spec in overlay_defined.items():
            if isinstance(def_spec, Mapping):
                merged_def[str(def_id)] = {**def_spec, "source": source_label}

    overlay_contracts = overlay.get("kinetic_action_contracts", [])
    if isinstance(overlay_contracts, Sequence):
        contract_list: list[dict[str, Any]] = merged.setdefault(
            "kinetic_action_contracts", []
        )
        index_by_action = {
            str(item.get("action_id", "")): i for i, item in enumerate(contract_list)
        }
        for raw_action in overlay_contracts:
            if not isinstance(raw_action, Mapping):
                raise SchemaIntegrityError(
                    f"Action contract in overlay ({source_label}) must be a JSON object."
                )
            act_dict = {**raw_action, "source": raw_action.get("source", source_label)}
            aid = str(act_dict.get("action_id", "")).strip()
            if aid in index_by_action:
                contract_list[index_by_action[aid]] = act_dict
            else:
                index_by_action[aid] = len(contract_list)
                contract_list.append(act_dict)

    return merged


def load_ontology_schema(
    schema_path: Path | None = None,
    *,
    user_ontology_dir: Path | None = USER_ONTOLOGY_DIR,
    include_user_overlay: bool = True,
) -> dict[str, Any]:
    """Load the builtin JSON ontology definition and overlay `~/.frago/ontology/*.json`."""
    target = schema_path if schema_path is not None else ONTOLOGY_SCHEMA_PATH
    raw_data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise SchemaIntegrityError("Root of frago.json must be a JSON object.")
    data: dict[str, Any] = raw_data

    for class_list in data.get("domain_classes", {}).values():
        if isinstance(class_list, list):
            for cls_def in class_list:
                if isinstance(cls_def, dict):
                    cls_def.setdefault("source", "builtin")

    if include_user_overlay and schema_path is None:
        for overlay_file in _collect_user_overlay_files(user_ontology_dir):
            raw_overlay = json.loads(overlay_file.read_text(encoding="utf-8"))
            if not isinstance(raw_overlay, dict):
                raise SchemaIntegrityError(
                    f"User ontology overlay '{overlay_file}' must be a JSON object."
                )
            data = merge_user_ontology_overlay(
                data,
                raw_overlay,
                source_label=f"userdir:{overlay_file.name}",
            )

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
