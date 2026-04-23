"""Small recipe lookup helpers used by callers that don't want the full
`RecipeRegistry` surface — CLI channel commands, server settings endpoints,
and the init channel wizard.

Kept minimal: just names, and a "does this name exist?" check.
"""

from __future__ import annotations


def list_recipe_names() -> list[str]:
    """Return sorted recipe names across all configured search paths.

    Returns [] on any failure (registry import, filesystem errors, etc.) so
    callers can proceed to a "no recipes available" branch without having to
    wrap the call in try/except themselves.
    """
    try:
        from frago.recipes.registry import get_registry

        return sorted(r.metadata.name for r in get_registry().list_all())
    except Exception:
        return []


def validate_recipe_exists(name: str) -> None:
    """Raise ValueError if `name` is not among the installed recipes.

    Callers (CLI `frago channel add`, server PUT /api/settings/task-ingestion,
    init wizard) run this before persisting a channel config so the user sees
    the error at save time rather than later when the ingestion scheduler
    tries to run the recipe.
    """
    names = list_recipe_names()
    if name not in names:
        raise ValueError(
            f"Recipe '{name}' not found under ~/.frago/recipes/ "
            f"(checked {len(names)} installed recipes)"
        )
