#!/usr/bin/env python3
"""
Chrome CDP Launcher - Chromium-based browser launch management

Provides browser launch, stop, and management functionality for Chrome, Edge, and Chromium.
Supports headless and void modes.
"""

import os
import platform
import shutil
import subprocess
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from frago.chrome.cdp.browser_detection import (
    BrowserType,
    find_browser,
    get_default_browser,
)
from frago.chrome.cdp.process import kill_existing_chrome
from frago.chrome.cdp.transport import cdp_get, cdp_ws_connect
from frago.chrome.profile_seed import seed_profile_from_system, system_profile_dir

# frago profile directory names (legacy flat layout).
# Kept only to locate old directories for lazy migration; the new layout
# derives paths from BrowserType.value + port (see _profile_dir_for).
FRAGO_PROFILE_NAMES: dict[BrowserType, str] = {
    BrowserType.CHROME: "chrome_profile",
    BrowserType.EDGE: "edge_profile",
    BrowserType.CHROMIUM: "chromium_profile",
}

# New nested layout root: ~/.frago/profiles/<browser>/<port>/
NEW_PROFILE_ROOT = Path.home() / ".frago" / "profiles"

# Default CDP debugging port; always explicit in the new layout path.
DEFAULT_CDP_PORT = 9222

# Cross-platform migration lock lives at the layout root.
_MIGRATE_LOCK = NEW_PROFILE_ROOT / ".migrate.lock"


class ChromeLauncher:
    """Chromium-based browser CDP launcher (supports Chrome, Edge, Chromium)"""

    def __init__(
        self,
        headless: bool = False,
        void: bool = False,
        app_mode: bool = False,
        kiosk_mode: bool = False,
        app_url: str | None = None,
        port: int = 9222,
        width: int = 1280,
        height: int = 960,
        window_x: int | None = None,
        window_y: int | None = None,
        profile_dir: Path | None = None,
        browser: str | None = None,
    ):
        self.system = platform.system()

        # Determine browser type and path
        self.browser_type, self.browser_path = self._resolve_browser(browser)

        self.debugging_port = port
        self.width = width
        self.height = height
        self.window_x = window_x
        self.window_y = window_y
        self.headless = headless
        self.void = void
        self.app_mode = app_mode
        self.kiosk_mode = kiosk_mode
        self.app_url = app_url
        self.browser_process: subprocess.Popen | None = None

        # Validate app/kiosk mode parameters
        if (self.app_mode or self.kiosk_mode) and not self.app_url:
            raise ValueError("app_mode/kiosk_mode requires app_url to be specified")

        # Validate mode exclusivity
        if self.app_mode and self.kiosk_mode:
            raise ValueError("app_mode and kiosk_mode cannot be used together")

        if (self.app_mode or self.kiosk_mode) and (self.headless or self.void):
            raise ValueError("app_mode/kiosk_mode cannot be used with headless or void mode")

        # Profile directory: use specified one first, otherwise use default location
        if profile_dir:
            # User-supplied path bypasses the layout entirely; no migration.
            self.profile_dir = Path(profile_dir)
        else:
            # New nested layout: ~/.frago/profiles/<browser>/<port>/ — port is
            # always explicit (default 9222 included), eliminating the old
            # naming asymmetry. Migration of a legacy flat directory happens in
            # launch(), after any old browser process is killed — merely
            # constructing a launcher (stop/status paths) must never move a
            # profile a live browser is still writing to.
            self.profile_dir = NEW_PROFILE_ROOT / self.browser_type.value / str(port)
        self._default_layout = profile_dir is None

    def _resolve_browser(self, browser: str | None) -> tuple[BrowserType, str | None]:
        """
        Resolve browser type and path based on user preference.

        Args:
            browser: User-specified browser name (chrome/edge/chromium) or None for auto-detect

        Returns:
            Tuple of (BrowserType, path)
        """
        if browser:
            # User specified a browser
            try:
                browser_type = BrowserType(browser.lower())
            except ValueError:
                # Invalid browser name, fall back to auto-detect
                return get_default_browser(self.system)

            path = find_browser(browser_type, self.system)
            return browser_type, path
        else:
            # Auto-detect: try Chrome > Edge > Chromium
            return get_default_browser(self.system)

    # Keep chrome_path as alias for backward compatibility
    @property
    def chrome_path(self) -> str | None:
        return self.browser_path

    @chrome_path.setter
    def chrome_path(self, value: str | None) -> None:
        self.browser_path = value

    # Keep chrome_process as alias for backward compatibility
    @property
    def chrome_process(self) -> subprocess.Popen | None:
        return self.browser_process

    @chrome_process.setter
    def chrome_process(self, value: subprocess.Popen | None) -> None:
        self.browser_process = value

    # _find_chrome is deprecated, use find_browser() module function instead
    def _find_chrome(self) -> str | None:
        """Deprecated: use find_browser() instead"""
        _, path = get_default_browser(self.system)
        return path

    def _get_system_profile_dir(self) -> Path | None:
        """Get system default browser user data directory based on browser type"""
        return system_profile_dir(self.browser_type.value, self.system)

    def _legacy_profile_dir(self, browser_type: BrowserType, port: int) -> Path | None:
        """Return the legacy flat directory to migrate from, if it exists.

        Legacy names: ``<browser>_profile`` (default port 9222, no suffix) and
        ``<browser>_profile_<port>`` (other ports). The default-port name has no
        suffix, so it cannot be split on the literal ``_<port>`` pattern — it is
        special-cased to the default port.
        """
        name = FRAGO_PROFILE_NAMES.get(browser_type)
        if name is None:
            return None
        if port == DEFAULT_CDP_PORT:
            candidate = Path.home() / ".frago" / name
        else:
            candidate = Path.home() / ".frago" / f"{name}_{port}"
        return candidate if candidate.exists() else None

    @contextmanager
    def _migration_lock(self):
        """Cross-platform advisory lock serializing the legacy migration step.

        Unix uses ``fcntl``; Windows uses ``msvcrt``. Both guard the same lock
        file so concurrent launches of the same target directory don't race.
        """
        _MIGRATE_LOCK.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_MIGRATE_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            if self.system == "Windows":
                import msvcrt

                # LK_NBLCK = 0x01: non-blocking lock; bail instead of spinning.
                try:
                    msvcrt.locking(fd, 1, 1)
                except OSError as err:
                    raise RuntimeError(
                        "another frago process is migrating the browser profile"
                    ) from err
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as err:
                    raise RuntimeError(
                        "another frago process is migrating the browser profile"
                    ) from err
            yield
        finally:
            with suppress(OSError):
                os.close(fd)

    def _migrate_legacy_profile(
        self, browser_type: BrowserType, port: int, profile_dir: Path
    ) -> None:
        """Lazily move a legacy flat profile into the new nested layout.

        Only runs when the legacy directory exists and the new one does not.
        ``shutil.move`` renames in place on the same filesystem (O(1) inode
        move, never touching the 7.2G of login state) and transparently falls
        back to copy+delete across filesystems. A successful move prints one
        line so the user knows their data moved.

        Skipped when something is still listening on the CDP port: a live
        browser may be writing to the legacy directory, and moving it out from
        under a running process would split the profile.
        """
        legacy_dir = self._legacy_profile_dir(browser_type, port)
        # Nothing to migrate: either already migrated (target has real data),
        # or never existed. A target with no files anywhere in its tree is a
        # leftover mkdir (possibly with empty subdirs), handled under the lock.
        if legacy_dir is None or self._has_profile_data(profile_dir):
            return

        if self._port_in_use(port):
            print(
                f"[frago] skipping profile migration: port {port} is in use, "
                f"{legacy_dir} may still be open in a running browser"
            )
            return

        with self._migration_lock():
            # Re-check under the lock: another process may have migrated first.
            # A target without profile data (leftover mkdir, possibly with
            # empty subdirs) doesn't count as migrated — remove it, or
            # shutil.move would nest the legacy dir inside it instead of
            # replacing it.
            if profile_dir.exists():
                if self._has_profile_data(profile_dir):
                    return
                shutil.rmtree(profile_dir)
            if not legacy_dir.exists():
                return
            profile_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(legacy_dir), str(profile_dir))
            except OSError:
                # A cross-filesystem move that fails midway leaves a partial
                # destination; remove it so the next launch can retry instead
                # of silently adopting an incomplete profile.
                if profile_dir.exists():
                    shutil.rmtree(profile_dir, ignore_errors=True)
                raise
            print(
                f"[frago] migrated legacy profile {legacy_dir} → {profile_dir}"
            )

    @staticmethod
    def _has_profile_data(profile_dir: Path) -> bool:
        """True when the directory tree contains at least one file.

        Empty directories (including nested empty ones like a bare Default/)
        are launch leftovers, not a migrated profile.
        """
        if not profile_dir.exists():
            return False
        return any(p.is_file() for p in profile_dir.rglob("*"))

    @classmethod
    def _wait_port_free(cls, port: int, timeout: float = 15.0) -> bool:
        """Wait (bounded) for the CDP port to stop accepting connections.

        Returns True when the port is free, False when it is still busy after
        the timeout (migration then skips via its own port guard).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not cls._port_in_use(port):
                return True
            time.sleep(0.5)
        return not cls._port_in_use(port)

    @staticmethod
    def _port_in_use(port: int) -> bool:
        """Best-effort check whether something is listening on the CDP port."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def _init_profile_dir(self) -> None:
        """Initialize Chrome profile directory by syncing from system profile.

        Only copies from system profile on first initialization (when Default/
        directory doesn't exist yet). Subsequent launches preserve the frago
        profile as-is, keeping login sessions and cookies intact.
        """
        seed_profile_from_system(self.profile_dir, self._get_system_profile_dir())

        # Set Chrome preferences to disable various UI prompts
        self._set_chrome_preferences()

    def _set_chrome_preferences(self) -> None:
        """Set Chrome preferences to disable various UI prompts"""
        import json

        prefs_file = self.profile_dir / "Default" / "Preferences"
        prefs_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing preferences if file exists
        if prefs_file.exists():
            try:
                with open(prefs_file, encoding="utf-8") as f:
                    prefs = json.load(f)
            except Exception:
                prefs = {}
        else:
            prefs = {}

        # Disable translate
        if "translate" not in prefs:
            prefs["translate"] = {}
        prefs["translate"]["enabled"] = False

        # Disable password manager prompt
        if "profile" not in prefs:
            prefs["profile"] = {}
        prefs["profile"]["password_manager_enabled"] = False

        # Mark exit as clean to prevent "Restore pages?" prompt
        prefs["profile"]["exit_type"] = "Normal"
        prefs["profile"]["exited_cleanly"] = True

        # Disable session restore prompt ("Chrome didn't shut down correctly")
        if "session" not in prefs:
            prefs["session"] = {}
        prefs["session"]["restore_on_startup"] = 4  # 4 = open specific pages (empty)

        # Disable "Make Chrome your default browser" prompt
        if "browser" not in prefs:
            prefs["browser"] = {}
        prefs["browser"]["check_default_browser"] = False

        # Write preferences back
        try:
            with open(prefs_file, "w", encoding="utf-8") as f:
                json.dump(prefs, f, indent=2)
        except Exception:
            # Non-critical, Chrome will use defaults
            pass

    def wait_for_cdp(self, timeout: int = 10) -> bool:
        """Wait for CDP interface to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = cdp_get(
                    f"http://localhost:{self.debugging_port}/json/version", timeout=1
                )
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def inject_stealth_scripts(self) -> bool:
        """Inject anti-detection scripts to all new pages"""
        try:
            # Find stealth.js file
            stealth_js_path = (
                Path(__file__).parent / "stealth.js"
            )  # src/frago/chrome/cdp/stealth.js
            if not stealth_js_path.exists():
                return False

            with open(stealth_js_path, encoding="utf-8") as f:
                stealth_script = f.read()

            # Get first tab
            response = cdp_get(
                f"http://localhost:{self.debugging_port}/json", timeout=2
            )
            targets = response.json()

            if not targets:
                return False

            ws_url = targets[0]["webSocketDebuggerUrl"]

            import json

            ws = cdp_ws_connect(ws_url)

            # Inject stealth script
            message = {
                "id": 1,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": stealth_script},
            }
            ws.send(json.dumps(message))
            ws.recv()

            # Inject viewport border script — static 2px border, no animation
            viewport_border_script = """
            (function() {
                function showViewportBorder() {
                    if (!document.body) {
                        setTimeout(showViewportBorder, 50);
                        return;
                    }
                    if (document.getElementById('__frago_viewport_border__')) return;

                    var border = document.createElement('div');
                    border.id = '__frago_viewport_border__';
                    border.style.cssText = '\\
                        position: fixed;\\
                        top: 0; left: 0; right: 0; bottom: 0;\\
                        pointer-events: none;\\
                        z-index: 2147483647;\\
                        box-sizing: border-box;\\
                        border: 2px solid rgba(80, 200, 120, 0.6);\\
                    ';
                    document.body.appendChild(border);

                    var label = document.createElement('div');
                    label.id = '__frago_auto_label__';
                    label.textContent = 'Controlled by frago';
                    label.style.cssText = '\\
                        position: fixed;\\
                        top: 8px;\\
                        left: 50%;\\
                        transform: translateX(-50%);\\
                        padding: 4px 12px;\\
                        background: rgba(0,0,0,0.7);\\
                        color: #fff;\\
                        font-size: 12px;\\
                        font-weight: 500;\\
                        border-radius: 16px;\\
                        pointer-events: none;\\
                        z-index: 2147483647;\\
                    ';
                    document.body.appendChild(label);
                }
                showViewportBorder();
            })();
            """
            message = {
                "id": 2,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": viewport_border_script},
            }
            ws.send(json.dumps(message))
            ws.recv()

            ws.close()

            return True

        except Exception:
            return False

    def launch(self, kill_existing: bool = True) -> bool:
        """
        Launch Chrome browser

        Args:
            kill_existing: Whether to close existing CDP Chrome processes first

        Returns:
            bool: Whether successfully launched and ready
        """
        if kill_existing:
            kill_existing_chrome(self.debugging_port)

        if not self.chrome_path:
            return False

        # Move a legacy flat profile into the nested layout now that any old
        # browser process on this port has been killed. A browser with a large
        # profile can take a while to release the port after terminate(), so
        # wait (bounded) for it to free before the migration's port guard runs
        # — otherwise the guard skips migration and _init_profile_dir would
        # build a fresh profile, silently forfeiting the legacy login state.
        # User-supplied --profile-dir bypasses the layout and never migrates.
        if self._default_layout:
            self._wait_port_free(self.debugging_port, timeout=15.0)
            self._migrate_legacy_profile(
                self.browser_type, self.debugging_port, self.profile_dir
            )

        # Initialize profile directory
        self._init_profile_dir()

        # Chrome launch arguments
        # Note: profile_dir is a Path object, needs explicit string conversion to avoid Windows path issues
        cmd = [
            self.chrome_path,
            f"--user-data-dir={str(self.profile_dir)}",
            f"--remote-debugging-port={self.debugging_port}",
            "--remote-allow-origins=*",
            "--disable-dev-shm-usage",
            # Disable first-run experience
            "--no-first-run",
            "--no-default-browser-check",
            # Disable translate prompts and infobars for cleaner UI
            "--disable-translate",
            "--disable-features=Translate,TranslateUI",
            # Disable all infobars (banners/prompts at the top)
            "--disable-infobars",
            # Set language to avoid auto-detection
            "--lang=zh-CN",
        ]

        # Stealth anti-detection arguments (only for automation, not for app/kiosk mode)
        # App/kiosk mode is typically used for local UI (e.g., interactive recipes),
        # which doesn't need webdriver detection evasion
        if not self.app_mode and not self.kiosk_mode:
            cmd.append("--disable-blink-features=AutomationControlled")

        # Disable sandbox in Docker or when running as root (Linux only)
        # Root user without sandbox causes Chrome to refuse to start
        if os.environ.get("FRAGO_NO_SANDBOX") or (
            self.system == "Linux" and os.geteuid() == 0
        ):
            cmd.extend(["--no-sandbox", "--disable-setuid-sandbox"])

        # Set User-Agent based on system
        if self.system == "Darwin":
            user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        elif self.system == "Windows":
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        else:
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

        cmd.append(f"--user-agent={user_agent}")

        # Kiosk mode (fullscreen, no browser UI)
        if self.kiosk_mode:
            cmd.append("--kiosk")
            cmd.append(self.app_url)

        # App mode (borderless window)
        elif self.app_mode:
            cmd.append(f"--app={self.app_url}")
            cmd.append(f"--window-size={self.width},{self.height}")

            if self.window_x is not None and self.window_y is not None:
                cmd.append(f"--window-position={self.window_x},{self.window_y}")

        # Headless mode
        elif self.headless:
            cmd.extend(
                [
                    "--headless=new",
                    "--disable-gpu",
                    f"--window-size={self.width},{self.height}",
                ]
            )
        # Void mode: move window off screen
        elif self.void:
            cmd.append("--window-position=-32000,-32000")

        # Launch Chrome
        # stdin=DEVNULL prevents subprocess from waiting for input, which causes blocking on Windows
        self.chrome_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )

        # Wait for launch
        time.sleep(2)

        # Wait for CDP ready
        if self.wait_for_cdp():
            # Inject stealth scripts
            self.inject_stealth_scripts()

            # Initialize tabs: clean slate for new session (not in app/kiosk mode)
            if not self.app_mode and not self.kiosk_mode:
                self._initialize_tabs()
                # Reconcile stale tab groups after cleanup
                self._reconcile_tab_groups()

            # Force window size for app mode (Chrome ignores --window-size for remembered windows)
            if self.app_mode:
                self._set_window_bounds()

            return True

        return False

    def _set_window_bounds(self) -> bool:
        """Set window bounds via CDP to enforce size for app mode windows.

        Chrome remembers previous window positions for app mode and ignores
        --window-size parameter. This method uses CDP to force the correct size.
        """
        try:
            import json

            # Get browser websocket URL
            response = cdp_get(
                f"http://localhost:{self.debugging_port}/json/version", timeout=2
            )
            if response.status_code != 200:
                return False

            ws_url = response.json().get("webSocketDebuggerUrl")
            if not ws_url:
                return False

            ws = cdp_ws_connect(ws_url, timeout=5)

            # Get target list to find the window
            targets_response = cdp_get(
                f"http://localhost:{self.debugging_port}/json", timeout=2
            )
            if targets_response.status_code != 200 or not targets_response.json():
                ws.close()
                return False

            target_id = targets_response.json()[0].get("id")
            if not target_id:
                ws.close()
                return False

            # Get window ID for target
            ws.send(json.dumps({
                "id": 1,
                "method": "Browser.getWindowForTarget",
                "params": {"targetId": target_id}
            }))
            result = json.loads(ws.recv())
            window_id = result.get("result", {}).get("windowId")

            if not window_id:
                ws.close()
                return False

            # Calculate centered position
            # Try to get screen size, fallback to not specifying position
            screen_width, screen_height = 1920, 1080  # defaults
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                root.destroy()
            except Exception:
                pass

            left = (screen_width - self.width) // 2
            top = (screen_height - self.height) // 2

            # Set window bounds
            ws.send(json.dumps({
                "id": 2,
                "method": "Browser.setWindowBounds",
                "params": {
                    "windowId": window_id,
                    "bounds": {
                        "left": left,
                        "top": top,
                        "width": self.width,
                        "height": self.height,
                        "windowState": "normal"
                    }
                }
            }))
            ws.recv()
            ws.close()
            return True

        except Exception:
            return False

    # Server port for landing page URL (matches frago server default)
    LANDING_PAGE_SERVER_PORT = 8093
    LANDING_PAGE_URL = f"http://127.0.0.1:{LANDING_PAGE_SERVER_PORT}/chrome/dashboard"

    def _initialize_tabs(self) -> None:
        """Close all existing tabs except one and navigate it to the landing page.

        Assumes a new task session is starting — gives a clean browser state.
        After this method, only 1 tab remains with the landing page loaded.
        """
        try:
            import json as _json

            resp = cdp_get(
                f"http://localhost:{self.debugging_port}/json/list", timeout=5
            )
            all_targets = resp.json()
            page_tabs = [t for t in all_targets if t.get("type") == "page"]

            if not page_tabs:
                return

            # Close all tabs except the first one
            for tab in page_tabs[1:]:
                with suppress(Exception):
                    cdp_get(
                        f"http://localhost:{self.debugging_port}/json/close/{tab['id']}",
                        timeout=2,
                    )

            # Navigate the remaining tab to the landing page
            kept_tab = page_tabs[0]
            ws_url = kept_tab.get("webSocketDebuggerUrl")
            if not ws_url:
                return

            # Check if frago server is running before navigating to dashboard
            try:
                cdp_get(self.LANDING_PAGE_URL, timeout=1)
            except Exception:
                return  # Server not running, leave tab as-is

            ws = cdp_ws_connect(ws_url, timeout=5)
            ws.send(_json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": self.LANDING_PAGE_URL},
            }))
            ws.recv()
            ws.close()

        except Exception:
            pass  # Best-effort — don't block startup

    def _reconcile_tab_groups(self) -> None:
        """Reconcile tab group state and close orphan tabs at startup.

        1. Remove stale group entries whose tabs no longer exist.
        2. Close orphan tabs — tabs that are not the landing page, not
           tracked by any group, and not managed by TabManager.
        """
        try:
            from .tab_group_manager import TabGroupManager
            from .tab_manager import TabManager

            tgm = TabGroupManager(port=self.debugging_port)
            tgm.reconcile()

            # Collect all target_ids still tracked by groups
            grouped_ids: set[str] = set()
            for group in tgm.list_groups().values():
                grouped_ids.update(group.tabs.keys())

            # Collect TabManager-tracked target_ids
            tm = TabManager(port=self.debugging_port)
            tm.reconcile()
            managed_ids: set[str] = {
                entry.tab_id for entry in tm.get_tracked_tabs()
            }

            # Fetch live tabs and close orphans
            resp = cdp_get(
                f"http://localhost:{self.debugging_port}/json/list", timeout=5
            )
            for t in resp.json():
                if t.get("type") != "page":
                    continue
                tid = t.get("id", "")
                url = t.get("url", "")
                title = t.get("title", "")
                # Keep: landing page, grouped tabs, managed tabs, data URLs
                if "/chrome/dashboard" in url or title == "frago":
                    continue
                if url.startswith("data:text/html"):
                    continue
                if tid in grouped_ids:
                    continue
                if tid in managed_ids:
                    continue
                # Orphan — close it
                with suppress(Exception):
                    cdp_get(
                        f"http://localhost:{self.debugging_port}/json/close/{tid}",
                        timeout=2,
                    )
        except Exception:
            pass  # Best-effort — don't block startup

    def _inject_landing_page(self) -> bool:
        """Create a dedicated landing page tab served by the frago server.

        Opens ``http://127.0.0.1:8093/chrome/dashboard`` in a new tab.
        The page polls ``/chrome/dashboard/state`` for live tab group updates.
        """
        try:
            import json as _json

            # Check if frago server is running
            try:
                cdp_get(self.LANDING_PAGE_URL, timeout=1)
            except Exception:
                return False  # Server not running, skip landing page

            # Check if landing page already exists
            response = cdp_get(
                f"http://localhost:{self.debugging_port}/json", timeout=2
            )
            targets = response.json()
            for t in targets:
                if t.get("type") == "page":
                    url = t.get("url", "")
                    title = t.get("title", "")
                    if "/chrome/dashboard" in url or title == "frago":
                        return True  # Already have a landing page

            # Get a WS URL to issue Target.createTarget
            ws_url = None
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    ws_url = t["webSocketDebuggerUrl"]
                    break

            if not ws_url:
                ver = cdp_get(
                    f"http://localhost:{self.debugging_port}/json/version", timeout=2
                ).json()
                ws_url = ver.get("webSocketDebuggerUrl")
                if not ws_url:
                    return False

            ws = cdp_ws_connect(ws_url, timeout=5)

            # Create a new tab with the landing page
            ws.send(_json.dumps({
                "id": 100,
                "method": "Target.createTarget",
                "params": {"url": self.LANDING_PAGE_URL},
            }))
            result = _json.loads(ws.recv())
            target_id = result.get("result", {}).get("targetId")

            # Bring landing page tab to front
            if target_id:
                ws.send(_json.dumps({
                    "id": 101,
                    "method": "Target.activateTarget",
                    "params": {"targetId": target_id},
                }))
                ws.recv()

            ws.close()
            return True

        except Exception:
            return False

    def stop(self) -> None:
        """Stop Chrome process"""
        if self.chrome_process:
            self.chrome_process.terminate()
            try:
                self.chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.chrome_process.kill()
            self.chrome_process = None

    def get_status(self) -> dict:
        """Get Chrome status information"""
        try:
            response = cdp_get(
                f"http://localhost:{self.debugging_port}/json/version", timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "running": True,
                    "browser": data.get("Browser", "unknown"),
                    "protocol_version": data.get("Protocol-Version", "unknown"),
                    "webkit_version": data.get("WebKit-Version", "unknown"),
                    "user_agent": data.get("User-Agent", "unknown"),
                }
        except Exception:
            pass

        return {"running": False}
