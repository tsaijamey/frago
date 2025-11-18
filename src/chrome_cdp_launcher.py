#!/usr/bin/env python3
"""
Chrome CDP Launcher - 跨平台版本
支持macOS和Linux，自动查找Chrome并初始化profile
"""

import os
import sys
import subprocess
import time
import signal
import psutil
import requests
import shutil
import platform
from pathlib import Path


class ChromeCDPLauncher:
    def __init__(self):
        self.system = platform.system()
        self.chrome_path = self._find_chrome()
        self.project_root = Path(__file__).parent.parent
        self.profile_dir = self.project_root / "chrome_profile"
        self.debugging_port = 9222
        self.width = 1280
        self.height = 960
        self.chrome_process = None

        # 初始化profile目录
        self._init_profile_dir()

    def _find_chrome(self):
        """跨平台查找Chrome浏览器"""
        if self.system == "Darwin":  # macOS
            possible_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium"
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
                shutil.which("chromium")
            ]
        else:
            raise OSError(f"不支持的操作系统: {self.system}")

        # 过滤None值并查找第一个存在的路径
        for path in filter(None, possible_paths):
            if os.path.exists(path):
                print(f"找到Chrome: {path}")
                return path

        return None

    def _get_system_profile_dir(self):
        """获取系统默认的Chrome用户数据目录"""
        home = Path.home()

        if self.system == "Darwin":  # macOS
            possible_dirs = [
                home / "Library/Application Support/Google/Chrome",
                home / "Library/Application Support/Chromium"
            ]
        elif self.system == "Linux":
            possible_dirs = [
                home / ".config/google-chrome",
                home / ".config/chromium"
            ]
        else:
            return None

        for dir_path in possible_dirs:
            if dir_path.exists():
                return dir_path

        return None

    def _init_profile_dir(self):
        """初始化项目Chrome profile目录

        如果chrome_profile不存在，从系统默认位置复制必要的用户数据
        """
        if self.profile_dir.exists():
            print(f"使用现有profile目录: {self.profile_dir}")
            return

        print(f"初始化profile目录: {self.profile_dir}")
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # 查找系统默认profile
        system_profile = self._get_system_profile_dir()
        if not system_profile:
            print("未找到系统Chrome配置，使用空profile")
            return

        print(f"从系统profile复制数据: {system_profile}")

        # 只复制必要的文件和目录，避免复制大型缓存
        items_to_copy = [
            "Default/Bookmarks",           # 书签
            "Default/Preferences",         # 偏好设置
            "Default/Extensions",          # 扩展
            "Default/Cookies",             # Cookies
            "Default/History",             # 历史记录
            "Default/Favicons",            # 网站图标
            "Local State",                 # 本地状态
        ]

        copied_count = 0
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
                    copied_count += 1
            except Exception as e:
                # 非关键文件复制失败不中断
                print(f"  跳过 {item}: {e}")

        print(f"已复制 {copied_count}/{len(items_to_copy)} 项配置数据")
        
    def kill_existing_chrome(self):
        """关闭现有的Chrome CDP实例"""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'Google Chrome' in str(cmdline) and '--remote-debugging-port' in str(cmdline):
                    print(f"终止现有Chrome进程 PID: {proc.info['pid']}")
                    proc.terminate()
                    proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass
    
    def wait_for_cdp(self, timeout=10):
        """等待CDP接口就绪"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"http://localhost:{self.debugging_port}/json/version", timeout=1)
                if response.status_code == 200:
                    return True
            except:
                pass
            time.sleep(0.5)
        return False
    
    def set_window_size(self):
        """设置Chrome窗口大小（跨平台）"""
        if self.system == "Darwin":  # macOS
            return self._set_window_macos()
        elif self.system == "Linux":
            return self._set_window_linux()
        return False

    def _set_window_macos(self):
        """使用AppleScript设置Chrome窗口大小 (macOS)"""
        applescript = f'''
        tell application "Google Chrome"
            set bounds of front window to {{20, 20, {20 + self.width}, {20 + self.height}}}
        end tell
        '''
        try:
            subprocess.run(['osascript', '-e', applescript], check=True, capture_output=True)
            print(f"窗口已调整为 {self.width}x{self.height}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"AppleScript执行失败: {e}")
            return False

    def _set_window_linux(self):
        """使用wmctrl设置Chrome窗口大小 (Linux)"""
        try:
            # 尝试使用wmctrl（如果安装）
            if shutil.which("wmctrl"):
                # 查找Chrome窗口
                time.sleep(1)  # 等待窗口创建
                subprocess.run([
                    'wmctrl', '-r', 'Google Chrome', '-e',
                    f'0,20,20,{self.width},{self.height}'
                ], check=False)
                print(f"窗口已调整为 {self.width}x{self.height} (wmctrl)")
                return True
            else:
                print("提示: 安装wmctrl可以自动调整窗口大小 (sudo apt install wmctrl)")
                print(f"请手动调整Chrome窗口为 {self.width}x{self.height}")
                return False
        except Exception as e:
            print(f"窗口调整失败: {e}")
            return False
    
    def launch(self):
        """启动Chrome"""
        self.kill_existing_chrome()

        if not self.chrome_path:
            print("错误: 未找到Chrome浏览器")
            print("请安装Google Chrome或Chromium浏览器")
            sys.exit(1)

        if not self.profile_dir.exists():
            print(f"错误: 配置文件目录不存在: {self.profile_dir}")
            sys.exit(1)

        # Chrome启动参数
        cmd = [
            self.chrome_path,
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={self.debugging_port}",
            "--remote-allow-origins=*"  # 允许所有来源的WebSocket连接
        ]

        print("启动Chrome浏览器...")
        print(f"操作系统: {self.system}")
        print(f"Chrome路径: {self.chrome_path}")
        print(f"用户数据目录: {self.profile_dir}")
        print(f"远程调试端口: {self.debugging_port}")
        print(f"目标窗口尺寸: {self.width}x{self.height}")

        # 启动Chrome
        self.chrome_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 等待Chrome启动
        time.sleep(3)

        # 设置窗口大小（跨平台）
        self.set_window_size()

        # 等待CDP就绪
        if self.wait_for_cdp():
            print(f"Chrome CDP已就绪，监听端口: {self.debugging_port}")
        else:
            print("警告: Chrome CDP未能在预期时间内就绪")

        return self.chrome_process
    
    def keep_alive(self):
        """保持Chrome运行"""
        if not self.chrome_process:
            print("Chrome进程未启动")
            return
        
        print("\nChrome正在运行中...")
        print("按 Ctrl+C 退出\n")
        
        def signal_handler(_signum, _frame):
            print("\n正在关闭Chrome...")
            if self.chrome_process:
                self.chrome_process.terminate()
                self.chrome_process.wait()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            # 持续检查进程状态
            while True:
                if self.chrome_process.poll() is not None:
                    print("Chrome进程已退出")
                    break
                    
                # 每30秒输出一次状态
                time.sleep(30)
                try:
                    response = requests.get(f"http://localhost:{self.debugging_port}/json/version", timeout=1)
                    if response.status_code == 200:
                        print(f"[{time.strftime('%H:%M:%S')}] Chrome CDP运行正常")
                except:
                    print(f"[{time.strftime('%H:%M:%S')}] Chrome CDP无响应")
                    
        except KeyboardInterrupt:
            pass
        finally:
            if self.chrome_process:
                self.chrome_process.terminate()
                self.chrome_process.wait()


def main():
    launcher = ChromeCDPLauncher()
    launcher.launch()
    launcher.keep_alive()


if __name__ == "__main__":
    main()