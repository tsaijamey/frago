"""BrowserViewer - Display content in the browser.

Replaces pywebview-based ViewerWindow with browser integration.
Uses the frago server for content serving and CDP for browser control.
"""

import time
from pathlib import Path
from typing import Literal, Optional

from frago.server.services.viewer_service import ViewerService


# Server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8093


class BrowserViewer:
    """Browser-based content viewer.

    Displays content by:
    1. Preparing content via ViewerService
    2. Ensuring frago server is running
    3. Ensuring the browser is running
    4. Opening a new tab with the content URL
    """

    def __init__(
        self,
        content: str | Path,
        mode: Literal["auto", "present", "doc"] = "auto",
        theme: str = "github-dark",
        title: Optional[str] = None,
        anchor: Optional[str] = None,
    ):
        """Initialize the browser viewer.

        Args:
            content: File path or raw content string
            mode: Display mode - "auto", "present" (reveal.js), or "doc" (scrollable)
            theme: Code highlighting theme
            title: Content title (defaults to filename or "frago view")
            anchor: Optional anchor ID to scroll to after page load
        """
        self.content = content
        self.mode = mode
        self.theme = theme
        self.title = title
        self.anchor = anchor

    def show(self) -> str:
        """Display the content in the browser.

        Returns:
            The URL opened in the browser
        """
        # 1. Prepare content
        content_id = ViewerService.prepare_content(
            content=self.content,
            mode=self.mode,
            theme=self.theme,
            title=self.title,
        )

        # 2. Ensure frago server is running
        self._ensure_server_running()

        # 3. Build URL
        url = f"http://{SERVER_HOST}:{SERVER_PORT}/viewer/content/{content_id}/index.html"
        if self.anchor:
            url = f"{url}#{self.anchor}"

        # 4. Ensure the browser is running and open new tab
        self._open_in_browser(url)

        return url

    def _ensure_server_running(self) -> None:
        """Ensure frago server is running, start if not."""
        from frago.server.daemon import is_server_running, start_daemon

        running, _ = is_server_running()
        if not running:
            success, message = start_daemon()
            if not success:
                raise RuntimeError(f"Failed to start frago server: {message}")
            # Wait a moment for server to be ready
            time.sleep(0.5)

    def _ensure_browser_running(self) -> None:
        """Ensure the browser is running with CDP enabled."""
        from frago.browser.cdp.launcher import ChromeLauncher

        launcher = ChromeLauncher()
        status = launcher.get_status()

        if not status.get("running"):
            launcher.launch(kill_existing=False)
            # Wait for the browser to be ready
            launcher.wait_for_cdp(timeout=10)

    def _open_in_browser(self, url: str) -> None:
        """Open URL in a new browser tab.

        Args:
            url: URL to open
        """
        self._ensure_browser_running()

        from frago.browser.cdp import CDPSession

        session = CDPSession()
        try:
            session.connect()
            # Create new tab with the URL
            session.target.create_target(url)
        finally:
            session.disconnect()


#: Pages under /app/ that are not a recipe's and keep their own window: the
#: virtual desktop is a stage of its own, not something to squeeze beside the menu.
_NOT_EMBEDDED = frozenset({"agent_os"})

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def recipe_page_of(url: str) -> tuple[str, str | None, str] | None:
    """If ``url`` is a recipe page on this machine's frago, which one.

    Returns ``(recipe name, slot or None, server origin)``, or None for anything
    else — another host, a built-in page, a sub-path, or a query string carrying
    more than ``key``: the WebUI can only address a page by name and slot, and
    dropping the rest would open a different page than the one asked for.
    """
    import re
    from urllib.parse import parse_qsl, unquote, urlsplit

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.hostname not in _LOCAL_HOSTS:
        return None
    match = re.fullmatch(r"/app/([^/]+)/?", parts.path)
    if not match:
        return None
    name = unquote(match.group(1))
    if name in _NOT_EMBEDDED:
        return None
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key != "key" for key, _ in query):
        return None
    slot = query[-1][1] if query else None
    return name, slot or None, f"{parts.scheme}://{parts.netloc}"


def webui_url_for(origin: str, name: str, slot: str | None) -> str:
    """The WebUI address that shows this recipe page on the right of the menu."""
    from urllib.parse import quote

    tail = quote(name, safe="")
    if slot and slot != "default":
        tail += "/" + quote(slot, safe="")
    return f"{origin}/#/app/{tail}"


def _show_in_open_webui(origin: str, name: str, slot: str | None) -> bool:
    """Ask a WebUI that is already open to switch to this page. True if one did."""
    import asyncio
    import json
    import urllib.request

    from frago.server.security import read_token

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        # On an event loop thread. If it is the server's own, the call below
        # would wait on the very loop it is blocking; go straight to the browser.
        return False

    body = json.dumps({"slot": slot}).encode("utf-8")
    req = urllib.request.Request(
        f"{origin}/api/recipe-apps/{name}/show",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = read_token()
    if token:
        req.add_header("X-Frago-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return bool(json.loads(resp.read() or b"{}").get("delivered"))
    except Exception:
        return False


def open_url(url: str) -> bool:
    """Open a page for a person to read. Returns whether it reached them.

    A recipe page on this machine is shown **inside the WebUI**, pinned under
    recipes and rendered on the right, not in a browser tab of its own. A
    WebUI that is already open is asked first and switches to the page; with
    none open, the default browser is handed the WebUI's address for that page,
    so it still lands in the WebUI. Running a recipe ten times therefore no
    longer leaves ten tabs behind.

    Everything else goes to the OS default browser, not the CDP-controlled
    Chrome that ``frago browser`` drives: the page is for a person, and opening
    it here keeps the agent's browser free. Same seam ``frago recipe open``,
    the runner's ``open_url`` and ``self.open_page()`` all use, so they behave
    the same.

    Must not be called on the server's event loop thread: asking the open WebUI
    is an HTTP call back into that same server.

    Returns False rather than raising when no browser is available. The caller
    is a recipe that has already done its work and published its page; failing
    to open a window is worth a warning, not a failed run.
    """
    import webbrowser

    page = recipe_page_of(url)
    if page is not None:
        name, slot, origin = page
        if _show_in_open_webui(origin, name, slot):
            return True
        url = webui_url_for(origin, name, slot)

    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def show_content(
    content: str | Path,
    mode: Literal["auto", "present", "doc"] = "auto",
    theme: str = "github-dark",
    title: Optional[str] = None,
    anchor: Optional[str] = None,
) -> str:
    """Convenience function to show content in the browser.

    Args:
        content: File path or raw content string
        mode: Display mode - "auto", "present", or "doc"
        theme: Code highlighting theme
        title: Content title
        anchor: Optional anchor ID to scroll to

    Returns:
        The URL opened in the browser
    """
    viewer = BrowserViewer(
        content=content,
        mode=mode,
        theme=theme,
        title=title,
        anchor=anchor,
    )
    return viewer.show()
