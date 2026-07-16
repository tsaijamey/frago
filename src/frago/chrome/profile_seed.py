"""First-launch profile seeding shared by the CDP and extension backends.

A frago-managed profile starts life as a copy of the user's system
browser profile (login sessions, saved passwords, cookies, bookmarks),
then evolves independently. Seeding happens only when the managed
profile has no ``Default/`` directory yet; later launches never touch
it again, so the frago profile keeps its own accumulated state.
"""
from __future__ import annotations

import os
import platform
import shutil
from contextlib import suppress
from pathlib import Path

# System user-data directories per (OS, brand). Brand strings cover both
# backends: CDP's BrowserType.value ("chrome" / "edge" / "chromium") and
# the extension picker's BrowserChoice.brand ("edge-beta", "brave", ...).
SYSTEM_PROFILE_DIRS_BY_BRAND: dict[str, dict[str, list[str]]] = {
    "Darwin": {
        "chrome":        ["~/Library/Application Support/Google/Chrome"],
        "chrome-beta":   ["~/Library/Application Support/Google/Chrome Beta"],
        "chrome-dev":    ["~/Library/Application Support/Google/Chrome Dev"],
        "chrome-canary": ["~/Library/Application Support/Google/Chrome Canary"],
        "edge":          ["~/Library/Application Support/Microsoft Edge"],
        "edge-beta":     ["~/Library/Application Support/Microsoft Edge Beta"],
        "edge-dev":      ["~/Library/Application Support/Microsoft Edge Dev"],
        "chromium":      ["~/Library/Application Support/Chromium"],
        "brave":         ["~/Library/Application Support/BraveSoftware/Brave-Browser"],
        "vivaldi":       ["~/Library/Application Support/Vivaldi"],
    },
    "Linux": {
        "chrome":        ["~/.config/google-chrome"],
        "chrome-beta":   ["~/.config/google-chrome-beta"],
        "chrome-dev":    ["~/.config/google-chrome-unstable"],
        "chrome-canary": ["~/.config/google-chrome-unstable"],
        "edge":          ["~/.config/microsoft-edge"],
        "edge-beta":     ["~/.config/microsoft-edge-beta"],
        "edge-dev":      ["~/.config/microsoft-edge-dev"],
        "chromium":      ["~/.config/chromium"],
        "brave":         ["~/.config/BraveSoftware/Brave-Browser"],
        "vivaldi":       ["~/.config/vivaldi"],
    },
    "Windows": {
        "chrome":        ["${LOCALAPPDATA}\\Google\\Chrome\\User Data"],
        "chrome-beta":   ["${LOCALAPPDATA}\\Google\\Chrome Beta\\User Data"],
        "chrome-dev":    ["${LOCALAPPDATA}\\Google\\Chrome Dev\\User Data"],
        "chrome-canary": ["${LOCALAPPDATA}\\Google\\Chrome SxS\\User Data"],
        "edge":          ["${LOCALAPPDATA}\\Microsoft\\Edge\\User Data"],
        "edge-beta":     ["${LOCALAPPDATA}\\Microsoft\\Edge Beta\\User Data"],
        "edge-dev":      ["${LOCALAPPDATA}\\Microsoft\\Edge Dev\\User Data"],
        "chromium":      ["${LOCALAPPDATA}\\Chromium\\User Data"],
        "brave":         ["${LOCALAPPDATA}\\BraveSoftware\\Brave-Browser\\User Data"],
        "vivaldi":       ["${LOCALAPPDATA}\\Vivaldi\\User Data"],
    },
}

# Regenerable bulk directories: copying them wastes time/disk and some
# hold live locks (Service Worker DBs) while the system browser runs.
EXCLUDE_DIRS = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "Service Worker",
    "File System",
    "blob_storage",
}
EXCLUDE_FILES = {
    "LOCK",
    "LOG",
    "LOG.old",
}


def system_profile_dir(brand: str, system: str | None = None) -> Path | None:
    """Locate the system user-data directory for a browser brand.

    Returns None when the brand is unknown on this OS or the directory
    does not exist (browser installed but never run, or not installed).
    """
    sys_name = system or platform.system()
    for path_str in SYSTEM_PROFILE_DIRS_BY_BRAND.get(sys_name, {}).get(brand, []):
        path = Path(os.path.expandvars(os.path.expanduser(path_str)))
        if path.exists():
            return path
    return None


def seed_profile_from_system(profile_dir: Path,
                             system_profile: Path | None) -> bool:
    """Copy ``Local State`` + ``Default/`` from the system profile once.

    No-op (returns False) when the managed profile already has a
    ``Default/`` directory — the profile is considered initialized and
    must keep its own state — or when no system profile is available.
    Copy failures are non-critical: the browser starts with a fresh
    profile instead.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    default_dst = profile_dir / "Default"
    if default_dst.exists():
        return False
    if system_profile is None:
        return False

    seeded = False

    local_state_src = system_profile / "Local State"
    if local_state_src.exists():
        with suppress(Exception):
            shutil.copy2(local_state_src, profile_dir / "Local State")
            seeded = True

    def ignore_patterns(_directory: str, files: list[str]) -> list[str]:
        return [
            f for f in files
            if f in EXCLUDE_DIRS or f in EXCLUDE_FILES
            or f.endswith(".log") or f.endswith(".lock")
        ]

    default_src = system_profile / "Default"
    if default_src.exists():
        with suppress(Exception):
            shutil.copytree(default_src, default_dst, ignore=ignore_patterns)
            seeded = True

    return seeded
