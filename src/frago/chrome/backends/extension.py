"""Extension-backed ChromeBackend.

Sends JSON-RPC commands over the native messaging daemon's unix socket.
The daemon must already be running (``frago extension daemon``) and the
browser must have the frago bridge extension loaded and connected.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from ..extension.native_host import DaemonClient, SOCK_PATH
from ..extension.protocol import RPC_ERROR_CODES
from .base import (
    ChromeBackend, ClickResult, ContentResult, ExecResult,
    NavigateResult, ScreenshotResult,
)


class ExtensionBackendError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.data = data


class ExtensionChromeBackend(ChromeBackend):
    name = "extension"

    def __init__(self, *, sock_path: Optional[Path] = None,
                 timeout: float = 30.0) -> None:
        self.sock_path = sock_path or SOCK_PATH
        self.timeout = timeout
        self._client: Optional[DaemonClient] = None

    def _rpc(self, method: str, params: dict) -> Any:
        client = DaemonClient(self.sock_path)
        try:
            resp = client.call(method, params, timeout=self.timeout)
        finally:
            client.close()
        if "error" in resp and resp["error"] is not None:
            err = resp["error"]
            raise ExtensionBackendError(err.get("code", -32000),
                                        err.get("message", ""),
                                        err.get("data"))
        return resp.get("result")

    # --- ChromeBackend -------------------------------------------------

    def start(self) -> dict:
        """Ping the bridge. Does NOT launch Chrome (that's a CLI concern).

        MVP P1 decision: browser launching is done separately — the
        extension cannot start Chrome itself. Callers should either
        (a) launch Chrome manually with ``--load-extension=<bundle>`` or
        (b) use ``frago extension launch`` (see CLI).
        """
        info = self._rpc("system.info", {})
        return {"backend": "extension", "bridge": info}

    def navigate(self, url: str, group: str, *,
                 timeout: float = 15.0) -> NavigateResult:
        r = self._rpc("tab.navigate",
                      {"url": url, "group": group,
                       "timeout": int(timeout * 1000)})
        return NavigateResult(tab_id=r["tab_id"], url=r["url"], title=r["title"])

    def exec_js(self, script: str, group: str) -> ExecResult:
        r = self._rpc("dom.exec_js", {"script": script, "group": group})
        return ExecResult(value=r.get("value"))

    def get_content(self, group: str, *,
                    selector: Optional[str] = None) -> ContentResult:
        r = self._rpc("dom.get_content",
                      {"group": group, "selector": selector})
        return ContentResult(
            text=r.get("text", ""), html=r.get("html", ""),
            title=r.get("title", ""), url=r.get("url", ""),
        )

    def click(self, selector: str, group: str) -> ClickResult:
        r = self._rpc("dom.click", {"selector": selector, "group": group})
        return ClickResult(success=bool(r.get("success")))

    def screenshot(self, group: str, *,
                   output: Optional[str] = None) -> ScreenshotResult:
        r = self._rpc("visual.screenshot", {"group": group, "output": output})
        b64 = r.get("png_base64")
        path = None
        if output and b64:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(base64.b64decode(b64))
            path = output
        return ScreenshotResult(path=path, png_base64=b64,
                                tab_id=r.get("tab_id"))

    # ─── Batch 1: tab management ─────────────────────────────────────

    def stop(self) -> dict:
        """Extension backend does not manage Chrome lifecycle.

        The daemon and extension stay up regardless; ``stop`` is
        documented as a CDP-only concept. Return a diagnostic dict so
        callers can detect the no-op explicitly.
        """
        return {"backend": "extension", "stopped": False,
                "note": "extension backend does not own Chrome process; "
                        "close Chrome manually or use `frago extension "
                        "daemon stop` to stop the bridge"}

    def status(self) -> dict:
        info = self._rpc("system.info", {})
        return {"backend": "extension", "ok": True, "bridge": info}

    def list_tabs(self) -> list[dict]:
        r = self._rpc("tabs.list", {})
        return list(r.get("tabs", []))

    def switch_tab(self, tab_id: str) -> dict:
        return self._rpc("tabs.switch", {"tab_id": _coerce_tab_id(tab_id)})

    def close_tab(self, tab_id: str) -> dict:
        return self._rpc("tabs.close", {"tab_id": _coerce_tab_id(tab_id)})

    def list_groups(self) -> dict:
        r = self._rpc("groups.list", {})
        return r.get("groups", {})

    def group_info(self, name: str) -> dict:
        return self._rpc("groups.info", {"name": name})

    def group_close(self, name: str) -> dict:
        return self._rpc("groups.close", {"name": name})

    def group_cleanup(self) -> dict:
        return self._rpc("groups.cleanup", {})

    def reset(self, group: Optional[str] = None) -> dict:
        return self._rpc("tabs.reset", {"group": group})

    def scroll(self, distance: int, group: str) -> dict:
        return self._rpc("page.scroll",
                         {"distance": int(distance), "group": group})

    def scroll_to(self, group: str, *, selector: Optional[str] = None,
                  text: Optional[str] = None,
                  block: str = "center") -> dict:
        if not selector and not text:
            raise ValueError("scroll_to: selector or text required")
        return self._rpc("page.scroll_to",
                         {"group": group, "selector": selector,
                          "text": text, "block": block})

    def zoom(self, factor: float, group: str) -> dict:
        return self._rpc("page.zoom",
                         {"factor": float(factor), "group": group})

    def get_title(self, group: str) -> str:
        r = self._rpc("page.get_title", {"group": group})
        return r.get("title", "") if isinstance(r, dict) else str(r)

    # ─── Visual effects (P3.1 / I) ─────────────────────────────────

    def highlight(self, selector: str, group: str, *,
                  color: str = "magenta", border_width: int = 3,
                  lifetime: int = 0) -> dict:
        return self._rpc("visual.highlight", {
            "selector": selector, "group": group, "color": color,
            "border_width": border_width, "lifetime": lifetime})

    def pointer(self, selector: str, group: str, *,
                lifetime: int = 0) -> dict:
        return self._rpc("visual.pointer", {
            "selector": selector, "group": group, "lifetime": lifetime})

    def spotlight(self, selector: str, group: str, *,
                  lifetime: int = 0) -> dict:
        return self._rpc("visual.spotlight", {
            "selector": selector, "group": group, "lifetime": lifetime})

    def annotate(self, selector: str, text: str, group: str, *,
                 position: str = "top", lifetime: int = 0) -> dict:
        return self._rpc("visual.annotate", {
            "selector": selector, "text": text, "group": group,
            "position": position, "lifetime": lifetime})

    def underline(self, selector: str, group: str, *,
                  color: str = "magenta", width: int = 3,
                  duration: int = 1000) -> dict:
        return self._rpc("visual.underline", {
            "selector": selector, "group": group, "color": color,
            "width": width, "duration": duration})

    def clear_effects(self, group: str) -> dict:
        return self._rpc("visual.clear_effects", {"group": group})

    def detect_anti_bot(self, group: str) -> dict:
        """Probe the current page for anti-bot challenge presence.

        Returns a dict with at minimum ``{"challenge": bool, "title": str,
        "url": str}``. When ``challenge`` is True, additional keys:

        - ``type``: ``"interactive"`` | ``"invisible_or_static"`` | ``"blocked"``
        - ``needs_human``: True only for ``interactive`` (CAPTCHA widgets
          require trusted user gestures — agents must NOT click).
        - ``detector``: which heuristic fired (``selector``, ``title``,
          ``cf-ray``, ``body-captcha-text``, ``body-blocked-text``).

        Recipe layer's recommended response:

        - ``challenge=False`` → proceed
        - ``type=interactive`` → pause + notify human, do **not** auto-click
        - ``type=invisible_or_static`` → wait 5-15s and re-probe (JS
          challenges typically self-resolve)
        - ``type=blocked`` → fail loud; the call needs different IP /
          cooldown / different account, not retry

        Detection is heuristic and lossy — extension-only (no CDP analog).
        """
        return self._rpc("detect.anti_bot", {"group": group})

    def send_command(self, method: str, params: dict) -> Any:
        return self._rpc(method, params)


def _coerce_tab_id(tab_id: Any) -> Any:
    """Extension uses integer Chrome tab IDs; CDP uses hex strings.

    If the caller passes a numeric-looking string, coerce; otherwise
    pass through so the RPC returns a clear error.
    """
    if isinstance(tab_id, int):
        return tab_id
    if isinstance(tab_id, str) and tab_id.isdigit():
        return int(tab_id)
    return tab_id


# ═════════════════════════ Browser detection ═════════════════════════
#
# Extension mode requires a Chromium-class browser whose stable channel
# still honors ``--load-extension``. Chrome Stable is **intentionally
# excluded**: since v137 it silently refuses --load-extension on user
# profiles (anti-sideload hardening, same family as Chrome 127's
# --remote-debugging-port block on default profiles).
#
# Priority within OS reflects "most likely already installed" + "least
# friction to ask user to install" trade-off:
#   Edge Stable > Chromium > Chrome Beta/Dev/Canary > Brave > Vivaldi


import platform as _platform
from typing import NamedTuple


class BrowserChoice(NamedTuple):
    path: str   # absolute binary path
    brand: str  # "edge" | "edge-beta" | "edge-dev" | "chromium" | "chrome-beta"
                # | "chrome-dev" | "chrome-canary" | "brave" | "vivaldi"


_BROWSER_CANDIDATES_LINUX: list[tuple[str, str]] = [
    ("/usr/bin/microsoft-edge",            "edge"),
    ("/usr/bin/microsoft-edge-stable",     "edge"),
    ("/usr/bin/microsoft-edge-beta",       "edge-beta"),
    ("/usr/bin/microsoft-edge-dev",        "edge-dev"),
    ("/usr/bin/chromium",                  "chromium"),
    ("/usr/bin/chromium-browser",          "chromium"),
    ("/snap/bin/chromium",                 "chromium"),
    ("/usr/bin/google-chrome-beta",        "chrome-beta"),
    ("/usr/bin/google-chrome-dev",         "chrome-dev"),
    ("/usr/bin/google-chrome-unstable",    "chrome-canary"),
    ("/usr/bin/brave-browser",             "brave"),
    ("/usr/bin/brave-browser-stable",      "brave"),
    ("/usr/bin/vivaldi",                   "vivaldi"),
    ("/usr/bin/vivaldi-stable",            "vivaldi"),
]

_BROWSER_CANDIDATES_MACOS: list[tuple[str, str]] = [
    ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",          "edge"),
    ("/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta", "edge-beta"),
    ("/Applications/Microsoft Edge Dev.app/Contents/MacOS/Microsoft Edge Dev",  "edge-dev"),
    ("/Applications/Chromium.app/Contents/MacOS/Chromium",                       "chromium"),
    ("/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",   "chrome-beta"),
    ("/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",     "chrome-dev"),
    ("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary", "chrome-canary"),
    ("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",             "brave"),
    ("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",                          "vivaldi"),
]

_BROWSER_CANDIDATES_WINDOWS: list[tuple[str, str]] = [
    # Edge — comes pre-installed on modern Windows, both Program Files variants
    (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",       "edge"),
    (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",             "edge"),
    (r"C:\Program Files (x86)\Microsoft\Edge Beta\Application\msedge.exe",  "edge-beta"),
    (r"C:\Program Files\Microsoft\Edge Beta\Application\msedge.exe",        "edge-beta"),
    (r"C:\Program Files (x86)\Microsoft\Edge Dev\Application\msedge.exe",   "edge-dev"),
    (r"C:\Program Files\Microsoft\Edge Dev\Application\msedge.exe",         "edge-dev"),
    # Chromium (rare on Windows; users self-install)
    (r"C:\Program Files\Chromium\Application\chrome.exe",                    "chromium"),
    # Chrome Beta/Dev/Canary (Canary lives under user AppData)
    (r"C:\Program Files (x86)\Google\Chrome Beta\Application\chrome.exe",   "chrome-beta"),
    (r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",         "chrome-beta"),
    (r"C:\Program Files (x86)\Google\Chrome Dev\Application\chrome.exe",    "chrome-dev"),
    (r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe",          "chrome-dev"),
    # Brave
    (r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe", "brave"),
    (r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",       "brave"),
    # Vivaldi
    (r"C:\Program Files\Vivaldi\Application\vivaldi.exe",                    "vivaldi"),
]

# PATH-name fallbacks (Linux/macOS mostly). Used after absolute-path
# scan misses — handles user-installed binaries in non-canonical places.
_PATH_FALLBACKS: list[tuple[str, str]] = [
    ("microsoft-edge",          "edge"),
    ("microsoft-edge-stable",   "edge"),
    ("microsoft-edge-beta",     "edge-beta"),
    ("microsoft-edge-dev",      "edge-dev"),
    ("chromium",                "chromium"),
    ("chromium-browser",        "chromium"),
    ("google-chrome-beta",      "chrome-beta"),
    ("google-chrome-dev",       "chrome-dev"),
    ("google-chrome-unstable",  "chrome-canary"),
    ("brave-browser",           "brave"),
    ("brave",                   "brave"),
    ("vivaldi",                 "vivaldi"),
    ("vivaldi-stable",          "vivaldi"),
]


def _windows_user_paths() -> list[tuple[str, str]]:
    """Chrome Canary lives under %LOCALAPPDATA%; resolve dynamically."""
    import os
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return []
    return [
        (str(Path(localappdata) / "Google" / "Chrome SxS" / "Application" / "chrome.exe"),
         "chrome-canary"),
    ]


def pick_browser_for_extension() -> Optional[BrowserChoice]:
    """Find the highest-priority Chromium-class browser usable for extension mode.

    Returns ``None`` if no compatible browser is installed.

    Skips Chrome Stable on purpose: it silently ignores ``--load-extension``
    since v137. Callers that pass ``chrome_binary=`` explicitly bypass
    this picker and may get Chrome Stable, but it will fail at runtime.
    """
    system = _platform.system()
    if system == "Linux":
        candidates = _BROWSER_CANDIDATES_LINUX
    elif system == "Darwin":
        candidates = _BROWSER_CANDIDATES_MACOS
    elif system == "Windows":
        candidates = _BROWSER_CANDIDATES_WINDOWS + _windows_user_paths()
    else:
        candidates = []

    for path, brand in candidates:
        if Path(path).exists():
            return BrowserChoice(path=path, brand=brand)

    for cmd, brand in _PATH_FALLBACKS:
        found = shutil.which(cmd)
        if found:
            return BrowserChoice(path=found, brand=brand)

    return None


def list_browsers_for_extension() -> list[BrowserChoice]:
    """Return all installed Chromium-class browsers usable for extension mode.

    Useful for diagnostic CLI output. Order follows the picker's priority,
    deduped by absolute path.
    """
    system = _platform.system()
    if system == "Linux":
        candidates = _BROWSER_CANDIDATES_LINUX
    elif system == "Darwin":
        candidates = _BROWSER_CANDIDATES_MACOS
    elif system == "Windows":
        candidates = _BROWSER_CANDIDATES_WINDOWS + _windows_user_paths()
    else:
        candidates = []

    seen: set[str] = set()
    out: list[BrowserChoice] = []
    for path, brand in candidates:
        if Path(path).exists() and path not in seen:
            seen.add(path)
            out.append(BrowserChoice(path=path, brand=brand))
    for cmd, brand in _PATH_FALLBACKS:
        found = shutil.which(cmd)
        if found and found not in seen:
            seen.add(found)
            out.append(BrowserChoice(path=found, brand=brand))
    return out


# ═════════════════════════ Browser launcher ═════════════════════════


def launch_chrome_with_extension(bundle_dir: Path,
                                 user_data_dir: Optional[Path] = None,
                                 chrome_binary: Optional[str] = None,
                                 log_path: Optional[Path] = None,
                                 ) -> subprocess.Popen:
    """Launch Chrome with the unpacked bundle loaded.

    This is the ``start`` command for the extension backend. Chrome is
    detached so it survives the CLI process exit.

    Browser selection: caller may pass ``chrome_binary`` to override.
    Otherwise :func:`pick_browser_for_extension` picks the best-fit
    Chromium-class browser. Chrome Stable is excluded by default because
    its --load-extension flag is policy-blocked.
    """
    if chrome_binary:
        binary = chrome_binary
    else:
        choice = pick_browser_for_extension()
        if not choice:
            raise RuntimeError(
                "no Chromium-class browser supports --load-extension on this "
                "system. Install Edge / Chromium / Chrome Beta+ / Brave / "
                "Vivaldi. Chrome Stable is not usable: it silently ignores "
                "--load-extension since v137."
            )
        binary = choice.path
    udd = user_data_dir or (Path.home() / ".frago" / "chrome" / "extension-profile")
    udd.mkdir(parents=True, exist_ok=True)
    args = [
        binary,
        f"--user-data-dir={udd}",
        f"--load-extension={bundle_dir}",
        f"--disable-extensions-except={bundle_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--enable-logging=stderr",
        # Opening a real URL on startup triggers the content script, which
        # pings the service worker and forces it to wake up and connect to
        # the native host. Without this, MV3 SWs may stay dormant.
        "about:blank",
    ]
    stdio = subprocess.DEVNULL
    if log_path:
        stdio = open(log_path, "wb")
    return subprocess.Popen(args, stdout=stdio, stderr=stdio,
                            start_new_session=True)
