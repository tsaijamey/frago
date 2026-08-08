"""ChromeBackend abstract base class.

P1 defines only the 6 MVP methods; P2 expands to full 33-command parity.

All results are plain dataclasses for wire/JSON stability. Backends MAY
return subclasses with backend-specific extras, but recipes should treat
the base fields as authoritative.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# A group may hold at most this many tabs. Past it, opening another one
# fails and names the tabs already there — the agent decides what to drop.
# Silently evicting the oldest is worse than any error: the agent goes on
# believing a page is open and the next command lands somewhere else.
MAX_TABS_PER_GROUP = 5

# Total silence — no command, no tab activation, no scrolling inside the
# pages — that closes a group on its own.
GROUP_IDLE_SECONDS = 30 * 60


@dataclass
class NavigateResult:
    tab_id: int | str
    url: str
    title: str
    group: str | None = None
    opened_new: bool = False
    tabs_in_group: int | None = None
    tab_limit: int = MAX_TABS_PER_GROUP


@dataclass
class ExecResult:
    value: Any


@dataclass
class ContentResult:
    text: str
    html: str
    title: str = ""
    url: str = ""


@dataclass
class ClickResult:
    success: bool


@dataclass
class ScreenshotResult:
    path: str | None = None
    png_base64: str | None = None
    tab_id: int | str | None = None


class ChromeBackend(ABC):
    """Abstract browser backend. P1 = 6 MVP methods."""

    name: str = "abstract"

    @abstractmethod
    def start(self) -> dict:
        """Ensure browser + bridge are running. Returns diagnostic info."""

    @abstractmethod
    def navigate(self, url: str, group: str, *,
                 timeout: float = 15.0,
                 new: bool = False) -> NavigateResult:
        """Open ``url`` inside ``group``.

        Without ``new`` the group's current tab — the last one navigated
        or switched to, not whatever tab the browser happens to be
        showing — is reused. With ``new`` a second tab joins the group,
        up to :data:`MAX_TABS_PER_GROUP`; past that the call fails and
        lists the tabs already open so the caller can pick one to close.
        """

    @abstractmethod
    def exec_js(self, script: str, group: str) -> ExecResult: ...

    @abstractmethod
    def get_content(self, group: str, *,
                    selector: str | None = None) -> ContentResult: ...

    @abstractmethod
    def click(self, selector: str, group: str) -> ClickResult: ...

    @abstractmethod
    def screenshot(self, group: str, *,
                   output: str | None = None) -> ScreenshotResult: ...

    # ─── P2 Batch 1: tab management + simple element ops ─────────────

    def stop(self) -> dict:
        """Stop the browser (CDP) or disconnect bridge (extension)."""
        raise NotImplementedError

    def status(self) -> dict:
        """Health check; returns backend-specific diagnostic dict."""
        raise NotImplementedError

    def list_tabs(self, group: str) -> dict:
        """The tabs of one group — never the whole browser.

        Returns ``{group, tabs, current, count, limit}``. Other groups'
        pages, and the person's own pages, are none of this group's
        business.
        """
        raise NotImplementedError

    def switch_tab(self, group: str, tab_id: str, *,
                   activate: bool = False) -> dict:
        """Point the group at one of its own tabs.

        This changes which tab subsequent commands act on. It does not
        change what is on screen unless ``activate`` is passed — the
        person may be looking at something else entirely.
        """
        raise NotImplementedError

    def close_tab(self, group: str, tab_id: str) -> dict:
        """Close one of the group's own tabs."""
        raise NotImplementedError

    def list_groups(self) -> dict:
        """All tab groups keyed by name, each with tab count + metadata."""
        raise NotImplementedError

    def group_info(self, name: str) -> dict:
        """Detailed info for one group; empty dict if missing."""
        raise NotImplementedError

    def group_close(self, name: str) -> dict:
        """Close the group and all its tabs."""
        raise NotImplementedError

    def group_cleanup(self) -> dict:
        """Remove groups whose tabs no longer exist."""
        raise NotImplementedError

    def reset(self, group: str | None = None) -> dict:
        """Close all tabs (or one group's tabs) except the landing page."""
        raise NotImplementedError

    def scroll(self, distance: int, group: str, *,
               activate: bool = False) -> dict:
        """Scroll by pixels. Positive=down.

        Reports the *measured* movement (``scrolled``), plus ``y`` /
        ``max_y`` / ``at_bottom`` / ``hidden``, so "the page could not
        move" is never reported as a successful scroll. The browser's
        visible state is left alone unless ``activate`` is passed: only
        then may a backend bring the target tab to front (inside its own
        window) when the page renders nothing while hidden.
        """
        raise NotImplementedError

    def scroll_to(self, group: str, *, selector: str | None = None,
                  text: str | None = None, block: str = "center",
                  activate: bool = False) -> dict:
        """Scroll element into view by selector or text."""
        raise NotImplementedError

    def zoom(self, factor: float, group: str) -> dict:
        """Set page zoom factor."""
        raise NotImplementedError

    def get_title(self, group: str) -> str:
        """Get page title."""
        raise NotImplementedError

    # ─── P2 Batch 2: backend-agnostic local ops ──────────────────────
    #
    # wait/detect are pure local operations (time.sleep, PATH scan) and
    # do not cross the browser boundary. They are included in the
    # backend surface for API uniformity — every CLI command now maps
    # to a backend method — but implementations are identical across
    # backends and deliberately skip any RPC round-trip. Visual effects
    # (highlight/pointer/spotlight/annotate/underline/clear-effects)
    # remain CDP-only for P2 and will land alongside the humanize
    # subsystem in P3.1.

    def wait(self, seconds: float) -> dict:
        """Sleep for N seconds. Local-only; no RPC."""
        import time
        time.sleep(float(seconds))
        return {"waited": float(seconds)}

    def detect(self) -> dict:
        """Scan PATH for Chromium-family browsers. Local-only; no RPC."""
        from ..cdp.browser_detection import (
            BROWSER_PRIORITY,
            detect_available_browsers,
        )
        browsers = detect_available_browsers()
        found = {bt.value: path for bt, path in browsers.items() if path}
        default = next((bt.value for bt in BROWSER_PRIORITY
                        if browsers.get(bt)), None)
        return {"found": found, "default": default,
                "priority": [bt.value for bt in BROWSER_PRIORITY],
                "all": {bt.value: browsers.get(bt)
                        for bt in BROWSER_PRIORITY}}

    # Generic low-level escape hatch; backends may override.
    def send_command(self, method: str, params: dict) -> Any:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support raw commands")

    def close(self) -> None:  # noqa: B027 — intentional default no-op, not abstract
        """Release resources. Default no-op."""
