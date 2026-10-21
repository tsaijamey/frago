#!/usr/bin/env python3
"""Cross-platform product support verification script for frago (Linux / WSL2 / macOS / Windows)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def check_cft_preinstalled() -> dict[str, object]:
    """Ensure Chrome for Testing / browsers are NOT pre-installed in the clean test environment."""
    binaries = ["chrome", "google-chrome", "chromium", "microsoft-edge", "microsoft-edge-stable"]
    found_bins = [b for b in binaries if shutil.which(b)]
    home_cft_dirs = [
        p
        for p in [
            Path.home() / ".frago" / "browsers",
            Path.home() / ".cache" / "frago" / "chrome-for-testing",
            Path.home() / ".local" / "share" / "frago" / "browsers",
        ]
        if p.exists()
    ]
    return {
        "preinstalled": bool(found_bins or home_cft_dirs),
        "found_binaries": found_bins,
        "found_cft_dirs": [str(p) for p in home_cft_dirs],
    }


def detect_runtime_kind() -> str:
    """Detect whether the current environment is windows, macos, wsl2, or linux."""
    sys_plat = sys.platform.lower()
    if sys_plat.startswith("win") or os.name == "nt":
        return "windows"
    if sys_plat == "darwin":
        return "macos"
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return "wsl2"
    proc_version = Path("/proc/version")
    if proc_version.exists():
        try:
            text = proc_version.read_text(encoding="utf-8", errors="ignore").lower()
            if "microsoft" in text or "wsl" in text:
                return "wsl2"
        except OSError:
            pass
    return "linux"


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run frago CLI via python -m frago.cli.main and return (code, stdout, stderr)."""
    cmd = [sys.executable, "-m", "frago.cli.main", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify frago runtime in target OS environment.")
    parser.add_argument(
        "--expect",
        choices=["linux", "wsl2", "macos", "windows"],
        default=None,
        help="Expected environment kind",
    )
    args = parser.parse_args()

    detected = detect_runtime_kind()
    if args.expect and detected != args.expect:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Expected environment '{args.expect}', but detected '{detected}'",
                },
                ensure_ascii=False,
            )
        )
        return 1

    ver_code, ver_out, ver_err = run_cli(["--version"])
    book_code, book_out, book_err = run_cli(["book", "--brief"])
    recipe_code, recipe_out, recipe_err = run_cli(["recipe", "list"])
    cft_state = check_cft_preinstalled()

    # In clean Docker test containers (linux / wsl2), Chrome for Testing must NOT be pre-installed
    cft_clean_ok = not cft_state["preinstalled"] if detected in ("linux", "wsl2") else True
    ok = ver_code == 0 and book_code == 0 and recipe_code == 0 and cft_clean_ok
    report = {
        "ok": ok,
        "detected_env": detected,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "home": str(Path.home()),
        "wsl_distro": os.environ.get("WSL_DISTRO_NAME"),
        "mnt_c_exists": Path("/mnt/c").exists() if detected == "wsl2" else None,
        "browser_clean_state": cft_state,
        "checks": {
            "version": {"code": ver_code, "output": ver_out or ver_err},
            "book_brief": {"code": book_code, "lines": len((book_out or "").splitlines())},
            "recipe_list": {"code": recipe_code, "lines": len((recipe_out or "").splitlines())},
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
