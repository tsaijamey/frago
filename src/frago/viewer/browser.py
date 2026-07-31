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
