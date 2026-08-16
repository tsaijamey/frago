"""The CDP browser's landing page: one address, one predicate.

`frago browser -b cdp start` opens a dashboard tab and every cleanup path in
the codebase must recognise it, or the next sweep closes the very tab the
launcher just opened.

Both facts used to be copy-pasted: two modules each defined their own
``LANDING_PAGE_URL``, and eight places hand-wrote
``"/chrome/dashboard" in url or title == "frago"``. When the command group was
renamed ``chrome`` -> ``browser`` (2026-08), the server route moved to
``/browser/dashboard`` and none of those ten copies followed.

Nothing broke loudly, which is why it survived: the web UI answers every
unknown path with its own shell at HTTP 200, so the stale address kept
returning a page titled ``frago``. The tab looked right and its state poll
silently received HTML instead of JSON, so the dashboard simply never updated.
Discovered 2026-08-10 by comparing byte counts — ``/``,
``/chrome/dashboard``, ``/chrome/dashboard/state`` and a deliberately bogus
path all returned exactly 5198 bytes.

So: one address here, one predicate here, and the predicate keeps answering
true for the old path — a browser started before this fix is still running,
and its landing tab must not be mistaken for an orphan and closed.
"""

# Matches the frago server default.
LANDING_PAGE_SERVER_PORT = 8093
LANDING_PAGE_PATH = "/browser/dashboard"
LANDING_PAGE_URL = (
    f"http://127.0.0.1:{LANDING_PAGE_SERVER_PORT}{LANDING_PAGE_PATH}"
)

# Pre-rename address. Recognised, never opened.
LEGACY_LANDING_PAGE_PATHS = ("/chrome/dashboard",)

# The landing page sets this title. Kept as a second signal because the tab is
# also identified before its URL settles.
LANDING_PAGE_TITLE = "frago"


def is_landing_page(url: str | None, title: str | None = None) -> bool:
    """Is this tab the CDP browser's own landing page?

    Callers use it to decide "leave this tab alone". Deliberately generous:
    mistaking the landing page for an orphan closes a tab frago itself opened,
    while the opposite error only leaves one extra tab open.
    """
    url = url or ""
    if LANDING_PAGE_PATH in url:
        return True
    if any(path in url for path in LEGACY_LANDING_PAGE_PATHS):
        return True
    return (title or "") == LANDING_PAGE_TITLE
