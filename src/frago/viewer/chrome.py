"""ChromeViewer - Display content in Chrome browser.

Replaces pywebview-based ViewerWindow with Chrome browser integration.
Uses the frago server for content serving and CDP for Chrome control.
"""

import time
from pathlib import Path
from typing import Literal, Optional

from frago.server.services.viewer_service import ViewerService


# Server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8093


class ChromeViewer:
    """Chrome-based content viewer.

    Displays content by:
    1. Preparing content via ViewerService
    2. Ensuring frago server is running
    3. Ensuring Chrome is running
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
        """Initialize the Chrome viewer.

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
        """Display the content in Chrome browser.

        Returns:
            The URL opened in Chrome
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

        # 4. Ensure Chrome is running and open new tab
        self._open_in_chrome(url)

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

    def _ensure_chrome_running(self) -> None:
        """Ensure Chrome is running with CDP enabled."""
        from frago.cdp.commands.chrome import ChromeLauncher

        launcher = ChromeLauncher()
        status = launcher.get_status()

        if not status.get("running"):
            launcher.launch(kill_existing=False)
            # Wait for Chrome to be ready
            launcher.wait_for_cdp(timeout=10)

    def _open_in_chrome(self, url: str) -> None:
        """Open URL in a new Chrome tab.

        Args:
            url: URL to open
        """
        self._ensure_chrome_running()

        from frago.cdp import CDPSession

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
    """Convenience function to show content in Chrome.

    Args:
        content: File path or raw content string
        mode: Display mode - "auto", "present", or "doc"
        theme: Code highlighting theme
        title: Content title
        anchor: Optional anchor ID to scroll to

    Returns:
        The URL opened in Chrome
    """
    viewer = ChromeViewer(
        content=content,
        mode=mode,
        theme=theme,
        title=title,
        anchor=anchor,
    )
    return viewer.show()
