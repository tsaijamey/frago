"""Dev-only: sideload the bundled frago-bridge extension into a fresh Chrome.

This script is **not** part of the agent OS surface. It exists for
people debugging the extension during development. End users do not run
this — they get the bundle as part of the frago install and use the
unified `frago chrome start --backend extension` command.

Usage:
    uv run python scripts/dev_launch_extension.py
    uv run python scripts/dev_launch_extension.py --bundle /custom/path
    uv run python scripts/dev_launch_extension.py --user-data-dir /tmp/profile

Pair with the daemon so the bridge actually comes up:
    Terminal 1:  uv run frago extension daemon
    Terminal 2:  uv run python scripts/dev_launch_extension.py
                 # then read the extension ID from chrome://extensions
                 uv run frago extension install <extension_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bundle", type=Path, default=None,
                    help="Unpacked bundle dir. Default: the bundle that "
                         "ships with frago (resolved via importlib.resources).")
    ap.add_argument("--user-data-dir", type=Path, default=None,
                    help="Chrome profile dir. "
                         "Default: ~/.frago/chrome/extension-profile")
    args = ap.parse_args()

    # Lazy import: keeps this script standalone-runnable even if the
    # frago package isn't installed system-wide (assuming PYTHONPATH or
    # `uv run` is doing the right thing).
    from frago.chrome.extension import bundle_path
    from frago.chrome.backends.extension import launch_chrome_with_extension

    bundle = args.bundle or bundle_path()
    if not (bundle / "manifest.json").exists():
        print(f"error: no manifest.json under {bundle}", file=sys.stderr)
        return 2

    proc = launch_chrome_with_extension(bundle, args.user_data_dir)
    print(json.dumps({"pid": proc.pid, "bundle": str(bundle)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
