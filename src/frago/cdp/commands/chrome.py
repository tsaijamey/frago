#!/usr/bin/env python3
"""
Chrome CDP Launcher - Chrome 浏览器启动管理

提供 Chrome 浏览器的启动、停止和管理功能，支持 headless 和 void 模式。
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
    """Chrome CDP 启动器"""

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

        # Profile 目录：优先使用指定的，否则使用默认位置
        if profile_dir:
            self.profile_dir = Path(profile_dir)
        elif use_port_suffix:
            # 非默认端口时，使用带端口号的目录名避免冲突
            self.profile_dir = Path.home() / ".frago" / f"chrome_profile_{port}"
        else:
            # 默认使用 ~/.frago/chrome_profile
            self.profile_dir = Path.home() / ".frago" / "chrome_profile"

    def _find_chrome(self) -> Optional[str]:
        """跨平台查找 Chrome 浏览器"""
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
            # Windows 常见 Chrome 安装路径
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
            program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")

            possible_paths = [
                # 用户安装（最常见）
                os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
                # 系统安装
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                # Chromium
                os.path.join(local_app_data, "Chromium", "Application", "chrome.exe"),
                # 通过 PATH 查找
                shutil.which("chrome"),
                shutil.which("chrome.exe"),
            ]
        else:
            return None

        for path in filter(None, possible_paths):
            if os.path.exists(path):
                return path

        return None

    def _get_system_profile_dir(self) -> Optional[Path]:
        """获取系统默认的 Chrome 用户数据目录"""
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
        """初始化 Chrome profile 目录"""
        if self.profile_dir.exists():
            return

        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # 查找系统默认 profile
        system_profile = self._get_system_profile_dir()
        if not system_profile:
            return

        # 只复制必要的文件和目录
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
                # 非关键文件复制失败不中断
                pass

    def kill_existing_chrome(self) -> int:
        """关闭现有的 Chrome CDP 实例，返回关闭的进程数"""
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
            time.sleep(1)  # 等待进程完全退出

        return killed_count

    def wait_for_cdp(self, timeout: int = 10) -> bool:
        """等待 CDP 接口就绪"""
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
        """注入反检测脚本到所有新页面"""
        try:
            # 查找 stealth.js 文件
            stealth_js_path = (
                Path(__file__).parent.parent / "stealth.js"
            )  # src/frago/cdp/stealth.js
            if not stealth_js_path.exists():
                return False

            with open(stealth_js_path, "r", encoding="utf-8") as f:
                stealth_script = f.read()

            # 获取第一个标签页
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

            message = {
                "id": 1,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {"source": stealth_script},
            }

            ws.send(json.dumps(message))
            ws.recv()
            ws.close()

            return True

        except Exception:
            return False

    def launch(self, kill_existing: bool = True) -> bool:
        """
        启动 Chrome 浏览器

        Args:
            kill_existing: 是否先关闭已有的 CDP Chrome 进程

        Returns:
            bool: 是否成功启动并就绪
        """
        if kill_existing:
            self.kill_existing_chrome()

        if not self.chrome_path:
            return False

        # 初始化 profile 目录
        self._init_profile_dir()

        # Chrome 启动参数
        cmd = [
            self.chrome_path,
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={self.debugging_port}",
            "--remote-allow-origins=*",
            # Stealth 反检测参数
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]

        # 根据系统设置 User-Agent
        if self.system == "Darwin":
            user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        elif self.system == "Windows":
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        else:
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        cmd.append(f"--user-agent={user_agent}")

        # Headless 模式
        if self.headless:
            cmd.extend(
                [
                    "--headless=new",
                    "--disable-gpu",
                    f"--window-size={self.width},{self.height}",
                ]
            )
        # Void 模式：窗口移到屏幕外
        elif self.void:
            # Wayland 不支持窗口位置控制，强制使用 XWayland
            if self.system == "Linux" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
                cmd.append("--ozone-platform=x11")
            cmd.append("--window-position=-32000,-32000")

        # 启动 Chrome
        self.chrome_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # 等待启动
        time.sleep(2)

        # 等待 CDP 就绪
        if self.wait_for_cdp():
            # 注入 stealth 脚本
            self.inject_stealth_scripts()
            return True

        return False

    def stop(self) -> None:
        """停止 Chrome 进程"""
        if self.chrome_process:
            self.chrome_process.terminate()
            try:
                self.chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.chrome_process.kill()
            self.chrome_process = None

    def get_status(self) -> dict:
        """获取 Chrome 状态信息"""
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
