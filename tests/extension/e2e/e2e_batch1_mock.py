"""Batch 1 mock e2e smoke.

Same daemon/client/mock-extension topology as :mod:`e2e_mock`, but
exercises the 14 Batch 1 JSON-RPC methods added in P2 B1:

    tabs.list, tabs.switch, tabs.close, tabs.reset,
    groups.list, groups.info, groups.close, groups.cleanup,
    page.scroll, page.scroll_to, page.zoom, page.get_title,
    system.info (status), system.ping (stop is no-op — no RPC).

Real-browser parity is still blocked by the Chrome Stable
``--load-extension`` policy (see ``outputs/e2e_p2b1/chrome_plan_a.log``),
so this mock covers the SW-adjacent half.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from frago.chrome.extension.native_host import (
    SOCK_PATH, STABLE_EXTENSION_ID, encode_frame, read_frame_async,
)
from frago.chrome.backends.extension import ExtensionChromeBackend


REPO_ROOT = Path(__file__).resolve().parents[3]


def _dispatch(method: str, params: dict):
    if method == "system.info":
        return {"extensionId": STABLE_EXTENSION_ID,
                "manifest": {"name": "frago bridge (mock-b1)", "version": "0.1.0"}}
    if method == "tabs.list":
        return {"tabs": [
            {"index": 0, "id": 11, "title": "one", "url": "https://a.example/",
             "active": True, "windowId": 1},
            {"index": 1, "id": 22, "title": "two", "url": "https://b.example/",
             "active": False, "windowId": 1},
        ]}
    if method == "tabs.switch":
        tid = params.get("tab_id")
        return {"tab_id": tid, "title": f"tab{tid}", "url": "about:blank"}
    if method == "tabs.close":
        return {"tab_id": params.get("tab_id"), "closed": True}
    if method == "tabs.reset":
        return {"group": params.get("group"), "closed": [11]}
    if method == "groups.list":
        return {"groups": {"g1": {"tab_id": 11, "tabs": 1}}}
    if method == "groups.info":
        return {"name": params["name"], "tab_id": 11,
                "url": "https://a.example/", "title": "one", "tabs": 1}
    if method == "groups.close":
        return {"name": params["name"], "closed": True, "tab_id": 11}
    if method == "groups.cleanup":
        return {"removed": 0}
    if method == "page.scroll":
        return {"scrolled": params.get("distance", 0)}
    if method == "page.scroll_to":
        return {"success": True}
    if method == "page.zoom":
        return {"tab_id": 11, "factor": params.get("factor", 1.0)}
    if method == "page.get_title":
        return {"tab_id": 11, "title": "MockTitle"}
    return {"__error__": {"code": -32601, "message": f"method not found: {method}"}}


async def mock_extension(sock_path: Path, stop_event: asyncio.Event) -> None:
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    writer.write(encode_frame({"role": "extension"})); await writer.drain()
    try:
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(read_frame_async(reader),
                                             timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                break
            method = msg.get("method"); mid = msg.get("id")
            params = msg.get("params") or {}
            result = _dispatch(method, params)
            if isinstance(result, dict) and "__error__" in result:
                resp = {"jsonrpc": "2.0", "id": mid, "error": result["__error__"]}
            else:
                resp = {"jsonrpc": "2.0", "id": mid, "result": result}
            writer.write(encode_frame(resp)); await writer.drain()
    finally:
        writer.close()


async def _run(out_dir: Path) -> int:
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()
    daemon_log = out_dir / "daemon.log"
    daemon_proc = subprocess.Popen(
        [sys.executable, "-m", "frago.cli.main", "extension", "daemon"],
        stdout=open(daemon_log, "wb"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not SOCK_PATH.exists():
            await asyncio.sleep(0.1)
        if not SOCK_PATH.exists():
            raise RuntimeError("daemon socket not created")

        stop = asyncio.Event()
        ext_task = asyncio.create_task(mock_extension(SOCK_PATH, stop))
        await asyncio.sleep(0.3)

        steps: dict = {}

        def blocking_calls():
            be = ExtensionChromeBackend(timeout=5.0)
            steps["status"] = be.status()
            steps["stop"] = be.stop()   # no RPC — diagnostic only
            steps["list_tabs"] = be.list_tabs()
            steps["switch_tab"] = be.switch_tab(22)
            steps["close_tab"] = be.close_tab(22)
            steps["list_groups"] = be.list_groups()
            steps["group_info"] = be.group_info("g1")
            steps["group_close"] = be.group_close("g1")
            steps["group_cleanup"] = be.group_cleanup()
            steps["reset"] = be.reset(None)
            steps["scroll"] = be.scroll(500, "g1")
            steps["scroll_to"] = be.scroll_to("g1", selector="h1")
            steps["zoom"] = be.zoom(1.25, "g1")
            steps["get_title"] = be.get_title("g1")
            return steps

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, blocking_calls)

        stop.set()
        await asyncio.wait_for(ext_task, timeout=3.0)

        # Spot-check assertions.
        assert steps["status"]["ok"] is True
        assert steps["stop"]["stopped"] is False
        assert len(steps["list_tabs"]) == 2
        assert steps["switch_tab"]["tab_id"] == 22
        assert steps["close_tab"]["closed"] is True
        assert "g1" in steps["list_groups"]
        assert steps["group_info"]["tab_id"] == 11
        assert steps["group_close"]["closed"] is True
        assert steps["group_cleanup"]["removed"] == 0
        assert steps["reset"]["closed"] == [11]
        assert steps["scroll"]["scrolled"] == 500
        assert steps["scroll_to"]["success"] is True
        assert steps["zoom"]["factor"] == 1.25
        assert steps["get_title"] == "MockTitle"

        log = out_dir / "mock_e2e_batch1_log.json"
        log.write_text(json.dumps({
            "extension_id": STABLE_EXTENSION_ID,
            "ok": True,
            "steps": steps,
        }, indent=2, default=str))
        print(f"[mock-e2e-b1] OK — log: {log}")
        return 0
    finally:
        try:
            os.killpg(os.getpgid(daemon_proc.pid), 15)
        except Exception:
            pass


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get(
        "FRAGO_E2E_OUT", str(REPO_ROOT / "outputs" / "e2e_mock_b1")))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_run(out_dir))


if __name__ == "__main__":
    sys.exit(main())
