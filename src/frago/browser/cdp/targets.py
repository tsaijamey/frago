"""What counts as a browser tab among CDP targets.

``/json/list`` reports more than tabs. An extension's offscreen document is
also ``type == "page"``, it often sorts *ahead* of the real tabs, and nothing
in the entry marks it as internal. Every place that means "the tabs" has to
say so explicitly, or it will eventually act on one of these.

That mistake has been made twice on this machine, both on 2026-08-23 and both
silent:

  * The virtual desktop stage picked the frago bridge's offscreen document as
    its actor. Navigation "succeeded", scrollY stayed 0, and not one frame was
    ever produced — while commands, logs and status all read normal.
  * Browser startup cleanup kept that same document (it was first in the list),
    closed the real tab, then navigated the document to the landing page and
    destroyed it too. A headful browser with no window left is a browser with
    no window: the stage came up, reported ready, and showed a blank tab.
"""

from __future__ import annotations

NON_TAB_URL_PREFIXES = ("chrome-extension://", "devtools://", "edge-extension://")


def is_real_tab(target: dict) -> bool:
    """True when this CDP target is a browser tab, not an internal page."""
    if target.get("type") != "page":
        return False
    return not (target.get("url") or "").startswith(NON_TAB_URL_PREFIXES)
