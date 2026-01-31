#!/usr/bin/env python3
"""
Chrome CDP Launcher - Chromium-based browser launch management

Provides browser launch, stop, and management functionality for Chrome, Edge, and Chromium.
Supports headless and void modes.
"""

import os
import sys
import subprocess
import time
import signal
import platform
import shutil
from enum import Enum
from pathlib import Path
from typing import Optional

import psutil
import requests


class BrowserType(Enum):
    """Supported browser types (all Chromium-based for CDP compatibility)"""
    CHROME = "chrome"
    EDGE = "edge"
    CHROMIUM = "chromium"


# Commands to try with shutil.which (highest priority)
BROWSER_COMMANDS: dict[BrowserType, list[str]] = {
    BrowserType.CHROME: ["google-chrome", "google-chrome-stable", "chrome"],
    BrowserType.EDGE: ["microsoft-edge", "microsoft-edge-stable", "msedge"],
    BrowserType.CHROMIUM: ["chromium", "chromium-browser"],
}

# Platform-specific default paths (fallback)
PLATFORM_PATHS: dict[str, dict[BrowserType, list[str]]] = {
    "Darwin": {  # macOS
        BrowserType.CHROME: [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ],
        BrowserType.EDGE: [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ],
        BrowserType.CHROMIUM: [
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
    },
    "Linux": {
        BrowserType.CHROME: [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ],
        BrowserType.EDGE: [
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
            "/opt/microsoft/msedge/msedge",
        ],
        BrowserType.CHROMIUM: [
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ],
    },
    "Windows": {
        BrowserType.CHROME: [
            "${LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe",
            "${PROGRAMFILES}\\Google\\Chrome\\Application\\chrome.exe",
            "${PROGRAMFILES(X86)}\\Google\\Chrome\\Application\\chrome.exe",
        ],
        BrowserType.EDGE: [
            "${PROGRAMFILES(X86)}\\Microsoft\\Edge\\Application\\msedge.exe",
            "${PROGRAMFILES}\\Microsoft\\Edge\\Application\\msedge.exe",
            "${LOCALAPPDATA}\\Microsoft\\Edge\\Application\\msedge.exe",
        ],
        BrowserType.CHROMIUM: [
            "${LOCALAPPDATA}\\Chromium\\Application\\chrome.exe",
        ],
    },
}

# Windows registry paths for browser detection
REGISTRY_PATHS: dict[BrowserType, list[tuple[int, str]]] = {
    # Values are (HKEY constant, subkey path)
    # HKEY_LOCAL_MACHINE = 0x80000002, HKEY_CURRENT_USER = 0x80000001
    BrowserType.CHROME: [
        (0x80000002, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        (0x80000001, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
    ],
    BrowserType.EDGE: [
        (0x80000002, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        (0x80000001, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
    ],
    BrowserType.CHROMIUM: [],  # Chromium typically doesn't register in App Paths
}

# System profile directories (for syncing bookmarks, extensions, etc.)
SYSTEM_PROFILE_DIRS: dict[str, dict[BrowserType, list[str]]] = {
    "Darwin": {
        BrowserType.CHROME: ["~/Library/Application Support/Google/Chrome"],
        BrowserType.EDGE: ["~/Library/Application Support/Microsoft Edge"],
        BrowserType.CHROMIUM: ["~/Library/Application Support/Chromium"],
    },
    "Linux": {
        BrowserType.CHROME: ["~/.config/google-chrome"],
        BrowserType.EDGE: ["~/.config/microsoft-edge"],
        BrowserType.CHROMIUM: ["~/.config/chromium"],
    },
    "Windows": {
        BrowserType.CHROME: ["${LOCALAPPDATA}\\Google\\Chrome\\User Data"],
        BrowserType.EDGE: ["${LOCALAPPDATA}\\Microsoft\\Edge\\User Data"],
        BrowserType.CHROMIUM: ["${LOCALAPPDATA}\\Chromium\\User Data"],
    },
}

# frago profile directory names
FRAGO_PROFILE_NAMES: dict[BrowserType, str] = {
    BrowserType.CHROME: "chrome_profile",
    BrowserType.EDGE: "edge_profile",
    BrowserType.CHROMIUM: "chromium_profile",
}


def _find_browser_from_registry(browser_type: BrowserType) -> Optional[str]:
    """Query Windows registry for browser installation path"""
    if platform.system() != "Windows":
        return None

    try:
        import winreg
    except ImportError:
        return None

    for hkey, subkey in REGISTRY_PATHS.get(browser_type, []):
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                path, _ = winreg.QueryValueEx(key, "")  # Default value
                if path and os.path.exists(path):
                    return path
        except (FileNotFoundError, OSError, PermissionError):
            continue

    return None


def find_browser(browser_type: BrowserType, system: Optional[str] = None) -> Optional[str]:
    """
    Find browser executable using three-layer detection strategy:
    1. shutil.which - User's PATH (highest priority, respects custom installations)
    2. Platform default paths - Standard installation locations
    3. Windows registry - For non-standard installations (Windows only)

    Args:
        browser_type: The type of browser to find
        system: Operating system name (defaults to platform.system())

    Returns:
        Path to browser executable, or None if not found
    """
    if system is None:
        system = platform.system()

    # Layer 1: PATH environment variable (respects user customization)
    for cmd in BROWSER_COMMANDS.get(browser_type, []):
        if path := shutil.which(cmd):
            return path

    # Layer 2: Platform default paths
    for path in PLATFORM_PATHS.get(system, {}).get(browser_type, []):
        expanded = os.path.expandvars(path)
        if os.path.exists(expanded):
            return expanded

    # Layer 3: Windows registry query (last resort for non-standard installations)
    if system == "Windows":
        if path := _find_browser_from_registry(browser_type):
            return path

    return None


def detect_available_browsers(system: Optional[str] = None) -> dict[BrowserType, Optional[str]]:
    """
    Detect all available browsers on the system.

    Returns:
        Dictionary mapping BrowserType to executable path (or None if not found)
    """
    return {
        browser_type: find_browser(browser_type, system)
        for browser_type in BrowserType
    }


def get_default_browser(system: Optional[str] = None) -> tuple[Optional[BrowserType], Optional[str]]:
    """
    Get the default browser (first available in priority order: Chrome > Edge > Chromium).

    Returns:
        Tuple of (BrowserType, path) or (None, None) if no browser found
    """
    for browser_type in [BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM]:
        if path := find_browser(browser_type, system):
            return browser_type, path
    return None, None


class ChromeLauncher:
    """Chromium-based browser CDP launcher (supports Chrome, Edge, Chromium)"""

    def __init__(
        self,
        headless: bool = False,
        void: bool = False,
        app_mode: bool = False,
        kiosk_mode: bool = False,
        app_url: Optional[str] = None,
        port: int = 9222,
        width: int = 1280,
        height: int = 960,
        window_x: Optional[int] = None,
        window_y: Optional[int] = None,
        profile_dir: Optional[Path] = None,
        use_port_suffix: bool = False,
        browser: Optional[str] = None,
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
        self.browser_process: Optional[subprocess.Popen] = None

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
            self.profile_dir = Path(profile_dir)
        else:
            profile_name = FRAGO_PROFILE_NAMES.get(self.browser_type, "chrome_profile")
            if use_port_suffix:
                # For non-default ports, use directory name with port number to avoid conflicts
                self.profile_dir = Path.home() / ".frago" / f"{profile_name}_{port}"
            else:
                # Default use ~/.frago/<browser>_profile
                self.profile_dir = Path.home() / ".frago" / profile_name

    def _resolve_browser(self, browser: Optional[str]) -> tuple[BrowserType, Optional[str]]:
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
    def chrome_path(self) -> Optional[str]:
        return self.browser_path

    @chrome_path.setter
    def chrome_path(self, value: Optional[str]) -> None:
        self.browser_path = value

    # Keep chrome_process as alias for backward compatibility
    @property
    def chrome_process(self) -> Optional[subprocess.Popen]:
        return self.browser_process

    @chrome_process.setter
    def chrome_process(self, value: Optional[subprocess.Popen]) -> None:
        self.browser_process = value

    # _find_chrome is deprecated, use find_browser() module function instead
    def _find_chrome(self) -> Optional[str]:
        """Deprecated: use find_browser() instead"""
        _, path = get_default_browser(self.system)
        return path

    def _get_system_profile_dir(self) -> Optional[Path]:
        """Get system default browser user data directory based on browser type"""
        # Get profile paths for current browser type
        profile_paths = SYSTEM_PROFILE_DIRS.get(self.system, {}).get(self.browser_type, [])

        for path_str in profile_paths:
            # Expand ~ and environment variables
            expanded = os.path.expandvars(os.path.expanduser(path_str))
            path = Path(expanded)
            if path.exists():
                return path

        return None

    def _init_profile_dir(self) -> None:
        """Initialize Chrome profile directory by syncing from system profile"""
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # Always sync from system profile on each launch
        system_profile = self._get_system_profile_dir()
        if system_profile:
            # Copy Local State file
            local_state_src = system_profile / "Local State"
            local_state_dst = self.profile_dir / "Local State"
            if local_state_src.exists():
                try:
                    shutil.copy2(local_state_src, local_state_dst)
                except Exception:
                    pass

            # Copy entire Default directory (excluding cache directories)
            # This preserves Google account login state and all user data
            default_src = system_profile / "Default"
            default_dst = self.profile_dir / "Default"

            # Directories to exclude (cache, logs, locks)
            exclude_dirs = {
                "Cache",
                "Code Cache",
                "GPUCache",
                "DawnGraphiteCache",
                "DawnWebGPUCache",
                "Service Worker",  # Can be large and regenerates
                "File System",  # Can be large
                "blob_storage",  # Can be large
            }
            exclude_files = {
                "LOCK",
                "LOG",
                "LOG.old",
            }

            def ignore_patterns(directory: str, files: list[str]) -> list[str]:
                """Return list of files/dirs to ignore during copy"""
                ignored = []
                for f in files:
                    if f in exclude_dirs or f in exclude_files:
                        ignored.append(f)
                    elif f.endswith(".log") or f.endswith(".lock"):
                        ignored.append(f)
                return ignored

            if default_src.exists():
                try:
                    if default_dst.exists():
                        shutil.rmtree(default_dst)
                    shutil.copytree(default_src, default_dst, ignore=ignore_patterns)
                except Exception:
                    # Non-critical: continue with existing profile or empty one
                    pass

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
                with open(prefs_file, "r", encoding="utf-8") as f:
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

    def kill_existing_chrome(self) -> int:
        """Close existing Chromium-based browser CDP instances, return number of processes closed"""
        killed_count = 0
        # Match any Chromium-based browser process names
        browser_names = {"chrome", "chromium", "msedge", "edge", "microsoft-edge"}

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline", [])
                if not cmdline:
                    continue

                cmdline_str = " ".join(cmdline)
                proc_name = proc.info.get("name", "").lower()

                # Check if this is a Chromium-based browser
                is_browser = any(name in proc_name for name in browser_names)
                has_cdp_port = (
                    f"--remote-debugging-port={self.debugging_port}" in cmdline_str
                )

                if is_browser and has_cdp_port:
                    proc.terminate()
                    proc.wait(timeout=3)
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass

        if killed_count > 0:
            time.sleep(1)  # Wait for processes to fully exit

        return killed_count

    def wait_for_cdp(self, timeout: int = 10) -> bool:
        """Wait for CDP interface to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
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
                Path(__file__).parent.parent / "stealth.js"
            )  # src/frago/cdp/stealth.js
            if not stealth_js_path.exists():
                return False

            with open(stealth_js_path, "r", encoding="utf-8") as f:
                stealth_script = f.read()

            # Get first tab
            response = requests.get(
                f"http://localhost:{self.debugging_port}/json", timeout=2
            )
            targets = response.json()

            if not targets:
                return False

            ws_url = targets[0]["webSocketDebuggerUrl"]

            import websocket
            import json

            ws = websocket.create_connection(ws_url)

            # Inject stealth script
            message = {
                "id": 1,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": stealth_script},
            }
            ws.send(json.dumps(message))
            ws.recv()

            # Inject viewport border script
            viewport_border_script = """
            (function() {
                function showViewportBorder() {
                    if (!document.body) {
                        setTimeout(showViewportBorder, 50);
                        return;
                    }
                    if (document.getElementById('__frago_viewport_border__')) return;

                    var style = document.createElement('style');
                    style.id = '__frago_border_style__';
                    style.textContent = '\\
                        @keyframes __frago_breathe__ {\\
                            0%, 100% {\\
                                box-shadow:\\
                                    inset 0 0 20px 8px rgba(80, 200, 120, 0.6),\\
                                    inset 0 0 40px 15px rgba(80, 200, 120, 0.3),\\
                                    inset 0 0 60px 25px rgba(80, 200, 120, 0.1);\\
                            }\\
                            50% {\\
                                box-shadow:\\
                                    inset 0 0 30px 12px rgba(80, 200, 120, 0.8),\\
                                    inset 0 0 60px 25px rgba(80, 200, 120, 0.5),\\
                                    inset 0 0 90px 40px rgba(80, 200, 120, 0.2);\\
                            }\\
                        }\\
                    ';
                    (document.head || document.body).appendChild(style);

                    var border = document.createElement('div');
                    border.id = '__frago_viewport_border__';
                    border.style.cssText = '\\
                        position: fixed;\\
                        top: 0; left: 0; right: 0; bottom: 0;\\
                        pointer-events: none;\\
                        z-index: 2147483647;\\
                        box-sizing: border-box;\\
                        animation: __frago_breathe__ 3s ease-in-out infinite;\\
                    ';
                    document.body.appendChild(border);
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
            self.kill_existing_chrome()

        if not self.chrome_path:
            return False

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
            user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        elif self.system == "Windows":
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        else:
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        cmd.append(f"--user-agent={user_agent}")

        # Kiosk mode (fullscreen, no browser UI)
        if self.kiosk_mode:
            cmd.append(f"--kiosk")
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
            # Wayland doesn't support window position control, force use XWayland
            if self.system == "Linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
                cmd.append("--ozone-platform=x11")
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
            import websocket

            # Get browser websocket URL
            response = requests.get(
                f"http://localhost:{self.debugging_port}/json/version", timeout=2
            )
            if response.status_code != 200:
                return False

            ws_url = response.json().get("webSocketDebuggerUrl")
            if not ws_url:
                return False

            ws = websocket.create_connection(ws_url, timeout=5)

            # Get target list to find the window
            targets_response = requests.get(
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
            response = requests.get(
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
