"""Automatic environment / path switcher for frago-support container."""

import os
import sys

MODE_FILE = "/var/run/frago-service/mode"

if os.path.exists(MODE_FILE):
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as _f:
            _mode = _f.read().strip()
        if _mode == "source":
            _src = "/workspace/src"
            if _src not in sys.path:
                sys.path.insert(0, _src)
    except Exception:
        pass
