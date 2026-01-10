#!/usr/bin/env python3
"""
Chrome CDP Launcher - Chrome browser launch management

Provides Chrome browser launch, stop, and management functionality, supports headless and void modes.
"""

import os
import sys
import subprocess
import time
import signal
import platform
import shutil
from pathlib import Path
from typing import Optional

import psutil
import requests


class ChromeLauncher:
    """Chrome CDP launcher"""

    def __init__(
        self,
        headless: bool = False,
        void: bool = False,
        port: int = 9222,
        width: int = 1280,
        height: int = 960,
        profile_dir: Optional[Path] = None,
        use_port_suffix: bool = False,
    ):
        self.system = platform.system()
        self.chrome_path = self._find_chrome()
        self.debugging_port = port
        self.width = width
        self.height = height
        self.headless = headless
        self.void = void
        self.chrome_process: Optional[subprocess.Popen] = None

        # Profile directory: use specified one first, otherwise use default location
        if profile_dir:
            self.profile_dir = Path(profile_dir)
        elif use_port_suffix:
            # For non-default ports, use directory name with port number to avoid conflicts
            self.profile_dir = Path.home() / ".frago" / f"chrome_profile_{port}"
        else:
            # Default use ~/.frago/chrome_profile
            self.profile_dir = Path.home() / ".frago" / "chrome_profile"

    def _find_chrome(self) -> Optional[str]:
        """Cross-platform Chrome browser finder"""
        if self.system == "Darwin":  # macOS
            possible_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        elif self.system == "Linux":
            possible_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
                "/snap/bin/chromium",
                shutil.which("google-chrome"),
                shutil.which("google-chrome-stable"),
                shutil.which("chromium-browser"),
                shutil.which("chromium"),
            ]
        elif self.system == "Windows":
            # Common Chrome installation paths on Windows
            local_app_data = os.environ.get("LOCALAPPDATA")
            program_files = os.environ.get("PROGRAMFILES") or "C:\\Program Files"
            program_files_x86 = os.environ.get("PROGRAMFILES(X86)") or "C:\\Program Files (x86)"

            possible_paths = []

            # User installation (most common) - only when LOCALAPPDATA exists
            if local_app_data:
                possible_paths.append(
                    os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe")
                )
                possible_paths.append(
                    os.path.join(local_app_data, "Chromium", "Application", "chrome.exe")
                )

            # System installation
            possible_paths.extend([
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            ])

            # Find via PATH
            possible_paths.extend([
                shutil.which("chrome"),
                shutil.which("chrome.exe"),
            ])
        else:
            return None

        for path in filter(None, possible_paths):
            if os.path.exists(path):
                return path

        return None

    def _get_system_profile_dir(self) -> Optional[Path]:
        """Get system default Chrome user data directory"""
        home = Path.home()

        if self.system == "Darwin":  # macOS
            possible_dirs = [
                home / "Library/Application Support/Google/Chrome",
                home / "Library/Application Support/Chromium",
            ]
        elif self.system == "Linux":
            possible_dirs = [
                home / ".config/google-chrome",
                home / ".config/chromium",
            ]
        elif self.system == "Windows":
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                possible_dirs = [
                    Path(local_app_data) / "Google" / "Chrome" / "User Data",
                    Path(local_app_data) / "Chromium" / "User Data",
                ]
            else:
                return None
        else:
            return None

        for dir_path in possible_dirs:
            if dir_path.exists():
                return dir_path

        return None

    def _init_profile_dir(self) -> None:
        """Initialize Chrome profile directory"""
        if self.profile_dir.exists():
            return

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # Find system default profile
        system_profile = self._get_system_profile_dir()
        if not system_profile:
            return

        # Only copy necessary files and directories
        items_to_copy = [
            "Default/Bookmarks",
            "Default/Preferences",
            "Default/Extensions",
            "Default/Cookies",
            "Default/History",
            "Default/Favicons",
            "Local State",
        ]

        for item in items_to_copy:
            src = system_profile / item
            dst = self.profile_dir / item

            try:
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
            except Exception:
                # Non-critical file copy failure doesn't interrupt execution
                pass

    def kill_existing_chrome(self) -> int:
        """Close existing Chrome CDP instances, return number of processes closed"""
        killed_count = 0
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline", [])
                if not cmdline:
                    continue

                cmdline_str = " ".join(cmdline)
                is_chrome = "chrome" in proc.info.get("name", "").lower()
                has_cdp_port = (
                    f"--remote-debugging-port={self.debugging_port}" in cmdline_str
                )

                if is_chrome and has_cdp_port:
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
                                    inset 0 0 15px 5px rgba(255, 180, 0, 0.6),\\
                                    inset 0 0 35px 12px rgba(255, 180, 0, 0.35),\\
                                    inset 0 0 55px 20px rgba(255, 180, 0, 0.15);\\
                            }\\
                            50% {\\
                                box-shadow:\\
                                    inset 0 0 25px 10px rgba(255, 180, 0, 0.75),\\
                                    inset 0 0 50px 20px rgba(255, 180, 0, 0.45),\\
                                    inset 0 0 80px 35px rgba(255, 180, 0, 0.2);\\
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
            # Stealth anti-detection arguments
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]

        # Set User-Agent based on system
        if self.system == "Darwin":
            user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        elif self.system == "Windows":
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        else:
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        cmd.append(f"--user-agent={user_agent}")

        # Headless mode
        if self.headless:
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
            return True

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
