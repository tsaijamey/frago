#!/usr/bin/env python3
"""
Chrome CDP Launcher V2
使用AppleScript确保窗口尺寸准确设置为1280x960
"""

import os
import sys
import subprocess
import time
import signal
import psutil
import requests
from pathlib import Path


class ChromeCDPLauncher:
    def __init__(self):
        self.chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        self.profile_dir = Path("/Users/chagee/Repos/AuViMa/chrome_profile")
        self.debugging_port = 9222
        self.width = 1280
        self.height = 960
        self.chrome_process = None
        
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
    
    def set_window_with_applescript(self):
        """使用AppleScript设置Chrome窗口大小"""
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
    
    def launch(self):
        """启动Chrome"""
        self.kill_existing_chrome()
        
        if not os.path.exists(self.chrome_path):
            print("错误: 未找到Chrome浏览器")
            sys.exit(1)
        
        if not self.profile_dir.exists():
            print(f"错误: 配置文件目录不存在: {self.profile_dir}")
            sys.exit(1)
        
        # 使用最简单的参数启动
        cmd = [
            self.chrome_path,
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={self.debugging_port}"
        ]
        
        print("启动Chrome浏览器...")
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
        
        # 使用AppleScript设置窗口大小
        self.set_window_with_applescript()
        
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
        
        def signal_handler(signum, frame):
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