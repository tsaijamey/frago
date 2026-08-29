"""What a recipe agreed its own page may ask it to do.

Reading this off the recipe rather than off the exposure entry is the whole
point of the field. ``frago recipe expose --runnable`` used to answer "may a
visitor press this button", and it answered it per page: the same recipe was
runnable on one address and not on another, and nothing in the recipe itself
said either way. So the answer moved to where the knowledge is. Whoever wrote
``mode_save`` knows whether a stranger may call it; whoever exposes the page
knows who the strangers are. Two facts, two places, and neither one has to
guess the other.

Kept apart from ``exports`` on purpose. An exported mode is read-only by
contract and is what *other modules* may ask for; a page action is allowed to
change something. A mode in both lists is a contradiction, and
``validate_metadata`` refuses it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def page_actions_of(name: str, wanted: str | None = None) -> tuple[str, ...]:
    """The modes this recipe's page may trigger. Empty tuple when it declared none.

    ``wanted`` is the mode about to be checked, and it is passed for the same
    reason ``_exports_of`` takes one: the registry is a snapshot taken at
    startup, so a declaration added afterwards is invisible until something
    happens to rescan. Being refused for an action that was declared five
    minutes ago is indistinguishable from never having declared it, and the
    person debugging it is looking at a ``recipe.md`` that plainly says
    otherwise. So a refusal costs one rescan before it is final.

    Never raises. A recipe that cannot be found declares nothing, which is the
    same answer as a recipe that declared nothing — and both mean the page gets
    no buttons.
    """
    from frago.recipes.exceptions import RecipeNotFoundError
    from frago.recipes.registry import get_registry, invalidate_registry

    def _look() -> tuple[str, ...]:
        try:
            recipe = get_registry().find(name)
        except (RecipeNotFoundError, OSError):
            return ()
        declared = getattr(recipe.metadata, "page_actions", None) or []
        return tuple(str(mode) for mode in declared if isinstance(mode, str) and mode)

    found = _look()
    if not found or (wanted is not None and wanted not in found):
        try:
            invalidate_registry()
        except OSError:
            logger.warning("could not rescan recipes before refusing an action",
                           exc_info=True)
            return found
        found = _look()
    return found
