"""ChromeBackend abstract base class.

P1 defines only the 6 MVP methods; P2 expands to full 33-command parity.

All results are plain dataclasses for wire/JSON stability. Backends MAY
return subclasses with backend-specific extras, but recipes should treat
the base fields as authoritative.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class NavigateResult:
    tab_id: int | str
    url: str
    title: str


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
    path: Optional[str] = None
    png_base64: Optional[str] = None
    tab_id: int | str | None = None


class ChromeBackend(ABC):
    """Abstract browser backend. P1 = 6 MVP methods."""

    name: str = "abstract"

    @abstractmethod
    def start(self) -> dict:
        """Ensure browser + bridge are running. Returns diagnostic info."""

    @abstractmethod
    def navigate(self, url: str, group: str, *,
                 timeout: float = 15.0) -> NavigateResult: ...

    @abstractmethod
    def exec_js(self, script: str, group: str) -> ExecResult: ...

    @abstractmethod
    def get_content(self, group: str, *,
                    selector: Optional[str] = None) -> ContentResult: ...

    @abstractmethod
    def click(self, selector: str, group: str) -> ClickResult: ...

    @abstractmethod
    def screenshot(self, group: str, *,
                   output: Optional[str] = None) -> ScreenshotResult: ...

    # ─── P2 Batch 1: tab management + simple element ops ─────────────

    def stop(self) -> dict:
        """Stop the browser (CDP) or disconnect bridge (extension)."""
        raise NotImplementedError

    def status(self) -> dict:
        """Health check; returns backend-specific diagnostic dict."""
        raise NotImplementedError

    def list_tabs(self) -> list[dict]:
        """All open page tabs: [{id, title, url, index}]."""
        raise NotImplementedError

    def switch_tab(self, tab_id: str) -> dict:
        """Bring the given tab to front."""
        raise NotImplementedError

    def close_tab(self, tab_id: str) -> dict:
        """Close the given tab."""
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

    def reset(self, group: Optional[str] = None) -> dict:
        """Close all tabs (or one group's tabs) except the landing page."""
        raise NotImplementedError

    def scroll(self, distance: int, group: str) -> dict:
        """Scroll by pixels. Positive=down."""
        raise NotImplementedError

    def scroll_to(self, group: str, *, selector: Optional[str] = None,
                  text: Optional[str] = None, block: str = "center") -> dict:
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
        from ..cdp.commands.chrome import BrowserType, detect_available_browsers
        browsers = detect_available_browsers()
        found = {bt.value: path for bt, path in browsers.items() if path}
        default = None
        for bt in (BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM):
            if browsers.get(bt):
                default = bt.value
                break
        return {"found": found, "default": default,
                "all": {bt.value: browsers.get(bt) for bt in
                        (BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM)}}

    # Generic low-level escape hatch; backends may override.
    def send_command(self, method: str, params: dict) -> Any:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support raw commands")

    def close(self) -> None:
        """Release resources. Default no-op."""
