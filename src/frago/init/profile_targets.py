"""Which agent CLIs an activated profile can be applied to.

Activating a profile used to mean one thing only: writing it into Claude Code's
settings. That was invisible to the person doing it — the button said
"activate", and they had no way to tell that their other two CLIs were still
running whatever they were running before. Activation now names its targets.

A target is offerable when both halves hold:

- **supported** — its driver knows how to write a frago profile into that CLI's
  own config. codex is the one that never will: frago profiles are Anthropic
  protocol endpoints and codex's custom providers speak OpenAI's responses
  protocol, so there is no honest translation. The driver carries the reason and
  it is shown rather than hidden, because a checkbox that is simply missing
  reads as an oversight.
- **installed** — the executable is actually on this machine. Writing a config
  file for a CLI nobody has does nothing except leave a file behind.

The apply/revert knowledge itself lives in each driver, next to that CLI's other
quirks; this module only decides who gets asked and in what order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from frago.init.profile_manager import APIProfile

# Order is the order the UI lists them in. claude first: it is the target
# activation has always meant, and the default when a caller names none.
AGENT_TARGETS: tuple[str, ...] = ("claude", "opencode", "codex")

DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude Code",
    "opencode": "opencode",
    "codex": "Codex CLI",
}

# What activation meant before targets existed. Callers that name no targets
# (the CLI, older API clients, re-applying an edited profile) keep getting
# exactly the old behavior.
DEFAULT_TARGETS: tuple[str, ...] = ("claude",)


@dataclass(frozen=True)
class TargetStatus:
    """One agent CLI's standing as an activation target."""

    agent_type: str
    display_name: str
    supported: bool
    installed: bool
    path: Optional[str]
    unsupported_reason: Optional[str]

    @property
    def selectable(self) -> bool:
        return self.supported and self.installed


def _driver(agent_type: str):
    from frago.agent_driver.driver import load_driver

    return load_driver(agent_type)


def _installed_path(agent_type: str) -> Optional[str]:
    from frago.compat import find_agent_cli

    return find_agent_cli(agent_type)


def target_status(agent_type: str) -> TargetStatus:
    """One target's supported / installed standing, with the reason if not."""
    driver = _driver(agent_type)
    path = _installed_path(agent_type)
    return TargetStatus(
        agent_type=agent_type,
        display_name=DISPLAY_NAMES.get(agent_type, agent_type),
        supported=driver.profile_apply is not None,
        installed=path is not None,
        path=path,
        unsupported_reason=(
            None if driver.profile_apply is not None else driver.profile_unsupported_reason
        ),
    )


def list_targets() -> list[TargetStatus]:
    """Every known agent CLI, offerable or not, in display order."""
    return [target_status(agent_type) for agent_type in AGENT_TARGETS]


def selectable_targets() -> list[str]:
    """The agent types that can actually be activated to right now."""
    return [status.agent_type for status in list_targets() if status.selectable]


def resolve_targets(requested: Optional[Sequence[str]]) -> list[str]:
    """Validate a requested target list, or fall back to the historical default.

    ``None`` means the caller has no opinion, and gets what activation has
    always done: Claude Code, without an installed check. That check is skipped
    deliberately — writing settings.json for a claude that is not on PATH is
    what frago did for its whole life, and failing there would break profile
    switching for anyone whose claude lives somewhere the search misses.

    An explicit list is held to both halves, and each rejection says which half
    failed, because "opencode cannot be activated" is not actionable and
    "opencode is not installed on this machine" is.

    Raises:
        ValueError: With a message meant to be shown to the user as-is.
    """
    if requested is None:
        return list(DEFAULT_TARGETS)

    # Duplicates are the caller being sloppy, not an error; order follows the
    # display order so the stored list is comparable between activations.
    asked = {t.strip() for t in requested if t and t.strip()}
    if not asked:
        raise ValueError("Pick at least one agent CLI to activate this profile on")

    unknown = sorted(asked - set(AGENT_TARGETS))
    if unknown:
        known = ", ".join(AGENT_TARGETS)
        raise ValueError(f"Unknown agent CLI {unknown[0]!r} (expected one of: {known})")

    for agent_type in AGENT_TARGETS:
        if agent_type not in asked:
            continue
        status = target_status(agent_type)
        if not status.supported:
            reason = status.unsupported_reason or "no translation for frago profiles"
            raise ValueError(f"{status.display_name} cannot use frago profiles: {reason}")
        if not status.installed:
            raise ValueError(
                f"{status.display_name} is not installed on this machine — "
                "install it first, or leave it unchecked"
            )

    return [t for t in AGENT_TARGETS if t in asked]


def apply_profile(profile: "APIProfile", targets: Sequence[str]) -> None:
    """Write this profile into each target's own config.

    A target whose driver cannot apply is skipped rather than raising: the
    caller has already been through ``resolve_targets`` for anything the person
    chose, and the remaining path here is frago re-applying its own stored
    target list after that CLI stopped being supported.
    """
    for agent_type in targets:
        apply = _driver(agent_type).profile_apply
        if apply is not None:
            apply(profile)


def revert_targets(targets: Sequence[str]) -> None:
    """Undo activation on each target, restoring what was there before frago.

    Reverting is best-effort per target: one CLI's config being unwritable must
    not leave the others stuck in a half-activated state, so a failure is
    carried and re-raised only after every target has had its turn.
    """
    first_error: Optional[Exception] = None
    for agent_type in targets:
        try:
            revert = _driver(agent_type).profile_revert
        except KeyError:
            # An agent type recorded by an older/newer build that this one does
            # not know. Nothing to revert, and nothing worth failing over.
            continue
        if revert is None:
            continue
        try:
            revert()
        except Exception as e:  # noqa: BLE001 - re-raised below
            first_error = first_error or e
    if first_error is not None:
        raise first_error
