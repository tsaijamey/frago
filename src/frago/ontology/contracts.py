"""Kinetic layer contracts (`Parameters ⊂ Signature ⊂ Contract`) and Defined Classes.

Implements:
1. Axiom-driven dynamic classification (`DefinedClass`) — classifies instances by
   necessary and sufficient conditions (`equivalent_to`) over the ontology graph
   rather than hardcoded subclass trees.
2. Three concentric defense rings for actions (`OntologicalActionContract` and
   `@ontological_action`):
   - Ring 1 (`Parameters`): required slot names
   - Ring 2 (`Signature`): initiator domain type, target range type, input/return types
   - Ring 3 (`Contract`): preconditions, postconditions, invariants, and side effects

Layer: pure ontology metamodel (no I/O, no imports from cli/ or server/).
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

from frago.ontology.metamodel import (
    Contract,
    DependentContinuant,
    Event,
    OntologyEntity,
    OntologyError,
    QualityState,
    Resource,
    Role,
)
from frago.ontology.relations import OntologyGraph

P = ParamSpec("P")
R = TypeVar("R")


class ContractViolationError(OntologyError):
    """Base exception for kinetic action contract failures."""


class SignatureViolationError(ContractViolationError):
    """Ring 2 violation: parameter slot missing, or domain/range/type mismatch."""


class PreconditionViolationError(ContractViolationError):
    """Ring 3 violation: business precondition failed before action execution."""


class PostconditionViolationError(ContractViolationError):
    """Ring 3 violation: action finished without satisfying its promised outcome."""


class InvariantViolationError(ContractViolationError):
    """Ring 3 violation: system-wide invariant broken before or after execution."""


# ============================================================================
# Axiom-Driven Classification (Defined Classes)
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class DefinedClass:
    """An ontological class defined by necessary and sufficient conditions (`equivalent_to`)."""

    class_id: str
    base_type: type[OntologyEntity]
    predicate: Callable[[OntologyEntity, OntologyGraph], bool]
    description: str = ""

    def matches(self, entity: OntologyEntity, graph: OntologyGraph) -> bool:
        """Return True iff `entity` is an instance of `base_type` and satisfies `predicate`."""
        if not isinstance(entity, self.base_type):
            return False
        return self.predicate(entity, graph)

    def classify_all(self, graph: OntologyGraph) -> list[OntologyEntity]:
        """Return all entities in `graph` dynamically classified into this DefinedClass."""
        return [e for e in graph.entities() if self.matches(e, graph)]


def _is_trusted_owner_request(entity: OntologyEntity, graph: OntologyGraph) -> bool:
    if not isinstance(entity, Role):
        return False
    states = graph.query_targets(entity.ontological_id(), "exhibits_state")
    return any(
        isinstance(s, QualityState)
        and s.dependent_type == "SecurityZoneState"
        and s.value in {"local", "token"}
        for s in states
    )


def _is_public_exposable_recipe(entity: OntologyEntity, graph: OntologyGraph) -> bool:
    if not isinstance(entity, Resource) or entity.resource_kind != "RecipeModule":
        return False
    capabilities = graph.query_targets(entity.ontological_id(), "has_capability")
    return not any(
        isinstance(c, DependentContinuant) and c.dependent_type == "action_triggerable"
        for c in capabilities
    )


def _is_verified_teammate_instruction(
    entity: OntologyEntity,
    _graph: OntologyGraph,
) -> bool:
    if not isinstance(entity, Event) or entity.event_type != "user":
        return False
    text = str(entity.payload.get("text", ""))
    verified = bool(entity.payload.get("relay_verified", False))
    return text.startswith("【frago team】") and verified


BUILTIN_DEFINED_CLASSES: dict[str, DefinedClass] = {
    "TrustedOwnerRequest": DefinedClass(
        class_id="TrustedOwnerRequest",
        base_type=Role,
        predicate=_is_trusted_owner_request,
        description=(
            "CallerZoneRole exhibiting SecurityZoneState in {'local', 'token'}; "
            "gains owner authority without a hardcoded Owner account subclass."
        ),
    ),
    "PublicExposableRecipe": DefinedClass(
        class_id="PublicExposableRecipe",
        base_type=Resource,
        predicate=_is_public_exposable_recipe,
        description=(
            "RecipeModule with zero @action write modes, eligible for --public exposure."
        ),
    ),
    "VerifiedTeammateInstruction": DefinedClass(
        class_id="VerifiedTeammateInstruction",
        base_type=Event,
        predicate=_is_verified_teammate_instruction,
        description=(
            "User message carrying '【frago team】' prefix and passing relay verification."
        ),
    ),
}


# ============================================================================
# Three Concentric Circles: Parameters ⊂ Signature ⊂ Contract
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class ActionSignature:
    """Circle 1 (Parameters) + Circle 2 (Type & Domain/Range Signature)."""

    parameters: tuple[str, ...]
    initiator_types: tuple[type[OntologyEntity], ...] = ()
    target_types: tuple[type[OntologyEntity], ...] = ()
    input_types: Mapping[str, type[Any] | tuple[type[Any], ...]] = field(
        default_factory=dict
    )
    return_type: type[Any] | tuple[type[Any], ...] | None = None


@dataclass(frozen=True, kw_only=True)
class ConditionCheck:
    """A named predicate evaluated against bound action arguments (and result for postconditions)."""

    description: str
    predicate: Callable[[Mapping[str, Any]], bool]


@dataclass(frozen=True, kw_only=True)
class SideEffectSpec:
    """Explicit declaration of kinetic side effects for introspection and audit."""

    initiates_process: str | None = None
    mutates_targets: tuple[str, ...] = ()
    emits_events: tuple[str, ...] = ()
    produces_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class OntologicalActionContract(Contract):
    """Circle 3 (Full Ontological Contract): Signature + Pre/Post/Invariants + SideEffects."""

    contract_kind: str = "ActionContract"
    signature: ActionSignature
    preconditions: tuple[ConditionCheck, ...] = ()
    postconditions: tuple[ConditionCheck, ...] = ()
    invariants: tuple[ConditionCheck, ...] = ()
    side_effects: SideEffectSpec = field(default_factory=SideEffectSpec)

    def validate_call_arguments(self, bound_args: Mapping[str, Any]) -> None:
        """Enforce Circle 1 (Parameters) and Circle 2 (Input & Domain/Range Signature)."""
        for param_name in self.signature.parameters:
            if param_name not in bound_args:
                raise SignatureViolationError(
                    f"Action '{self.norm_id}' missing required parameter '{param_name}'."
                )

        if self.signature.initiator_types and "initiator" in bound_args:
            initiator = bound_args["initiator"]
            if not isinstance(initiator, self.signature.initiator_types):
                allowed = ", ".join(t.__name__ for t in self.signature.initiator_types)
                raise SignatureViolationError(
                    f"Action '{self.norm_id}' initiator domain violation: "
                    f"expected ({allowed}), got '{type(initiator).__name__}'."
                )

        if self.signature.target_types and "target" in bound_args:
            target = bound_args["target"]
            if not isinstance(target, self.signature.target_types):
                allowed = ", ".join(t.__name__ for t in self.signature.target_types)
                raise SignatureViolationError(
                    f"Action '{self.norm_id}' target range violation: "
                    f"expected ({allowed}), got '{type(target).__name__}'."
                )

        for field_name, expected_type in self.signature.input_types.items():
            if field_name in bound_args:
                val = bound_args[field_name]
                if not isinstance(val, expected_type):
                    raise SignatureViolationError(
                        f"Action '{self.norm_id}' parameter '{field_name}' type mismatch: "
                        f"expected {expected_type}, got {type(val).__name__}."
                    )

    def check_preconditions(self, bound_args: Mapping[str, Any]) -> None:
        """Enforce Circle 3 preconditions and pre-execution invariants."""
        for inv in self.invariants:
            if not inv.predicate(bound_args):
                raise InvariantViolationError(
                    f"Action '{self.norm_id}' pre-execution invariant violated: {inv.description}"
                )
        for pre in self.preconditions:
            if not pre.predicate(bound_args):
                raise PreconditionViolationError(
                    f"Action '{self.norm_id}' precondition violated: {pre.description}"
                )

    def check_postconditions(
        self,
        bound_args: Mapping[str, Any],
        result: Any,
    ) -> None:
        """Enforce Circle 2 return type and Circle 3 postconditions + post-execution invariants."""
        if self.signature.return_type is not None and not isinstance(
            result, self.signature.return_type
        ):
            raise SignatureViolationError(
                f"Action '{self.norm_id}' return type mismatch: "
                f"expected {self.signature.return_type}, got {type(result).__name__}."
            )

        ctx = dict(bound_args)
        ctx["result"] = result

        for post in self.postconditions:
            if not post.predicate(ctx):
                raise PostconditionViolationError(
                    f"Action '{self.norm_id}' postcondition violated: {post.description}"
                )
        for inv in self.invariants:
            if not inv.predicate(ctx):
                raise InvariantViolationError(
                    f"Action '{self.norm_id}' post-execution invariant violated: {inv.description}"
                )


def ontological_action(
    contract: OntologicalActionContract,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that binds an `OntologicalActionContract` to a callable and enforces all 3 rings."""

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        py_sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                bound = py_sig.bind(*args, **kwargs)
                bound.apply_defaults()
            except TypeError as exc:
                raise SignatureViolationError(
                    f"Action '{contract.norm_id}' parameter binding failed: {exc}"
                ) from exc

            arg_map = dict(bound.arguments)
            contract.validate_call_arguments(arg_map)
            contract.check_preconditions(arg_map)
            result = fn(*args, **kwargs)
            contract.check_postconditions(arg_map, result)
            return result

        wrapper.ontology_contract = contract  # type: ignore[attr-defined]
        return wrapper

    return decorator
