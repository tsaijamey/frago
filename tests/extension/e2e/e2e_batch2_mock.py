"""Batch 2 mock e2e smoke.

Batch 2 (wait, detect) is backend-agnostic — both backends share a
single ABC-level implementation that does not cross the browser
boundary. This script therefore skips the daemon/mock-extension
topology used by Batch 1 and instead:

1. Exercises wait/detect on both CDPChromeBackend and
   ExtensionChromeBackend directly.
2. Verifies identical results across the two backends.
3. Writes a structured log mirroring the Batch 1 mock output.

Run:
    uv run python tests/extension/e2e/e2e_batch2_mock.py

Output:
    ~/.frago/projects/.../outputs/e2e_mock_b2/mock_e2e_batch2_log.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from frago.chrome.backends.cdp import CDPChromeBackend
from frago.chrome.backends.extension import ExtensionChromeBackend


def _default_out_dir() -> Path:
    override = os.environ.get("FRAGO_B2_MOCK_OUT")
    if override:
        return Path(override)
    run_dir = os.environ.get("FRAGO_CURRENT_RUN_DIR")
    if run_dir:
        return Path(run_dir) / "outputs" / "e2e_mock_b2"
    root = Path.home() / ".frago" / "projects" / \
        "20260425-write-spec-for-browser-extension-replacing-cdp-in-frago" / \
        "outputs" / "e2e_mock_b2"
    return root


def run() -> int:
    out_dir = _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "mock_e2e_batch2_log.json"

    cdp = CDPChromeBackend()
    ext = ExtensionChromeBackend()

    events: list[dict] = []

    # ── wait: 0.05s on each backend, ensure both return shape-matched
    for name, be in (("cdp", cdp), ("extension", ext)):
        t0 = time.monotonic()
        r = be.wait(0.05)
        dt = time.monotonic() - t0
        events.append({"backend": name, "command": "wait",
                       "input": {"seconds": 0.05},
                       "output": r, "elapsed_s": round(dt, 4)})
        assert r == {"waited": 0.05}, r
        assert dt >= 0.04, f"{name}: wait returned too fast"

    # ── detect: both backends must return identical payload
    cdp_d = cdp.detect()
    ext_d = ext.detect()
    events.append({"backend": "cdp", "command": "detect",
                   "input": {}, "output": cdp_d})
    events.append({"backend": "extension", "command": "detect",
                   "input": {}, "output": ext_d})
    assert cdp_d == ext_d, \
        f"detect parity violated: cdp={cdp_d!r} ext={ext_d!r}"
    assert "found" in cdp_d and "default" in cdp_d

    summary = {
        "run_id": "p2b2-mock",
        "phase": "P2 Batch 2",
        "commands": ["wait", "detect"],
        "deferred_to_p3_1": ["highlight", "pointer", "spotlight",
                             "annotate", "underline", "clear-effects"],
        "parity_ok": True,
        "events": events,
    }
    log_path.write_text(json.dumps(summary, indent=2, default=str,
                                   ensure_ascii=False))
    print(f"[mock-e2e-b2] OK — log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
