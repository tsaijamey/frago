#!/usr/bin/env python3
"""
Chrome process management - kill existing CDP browser instances.
"""

import time

import psutil


def kill_existing_chrome(debugging_port: int) -> int:
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
                f"--remote-debugging-port={debugging_port}" in cmdline_str
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
