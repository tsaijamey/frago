"""Mock-extension e2e smoke.

Google Chrome Stable (≥137) silently ignores ``--load-extension`` for
unpacked extensions, which blocks an end-to-end run against a real
browser on this host (see ``e2e_demo.py``'s chrome.log: the Chrome
message is ``--disable-extensions-except is not allowed in Google
Chrome, ignoring``). This mock substitutes the browser half of the
bridge: a coroutine that connects to the daemon as ``role=extension``
and answers each of the MVP JSON-RPC methods.

What this verifies:

    daemon ← socket → client (ExtensionChromeBackend)
                       ↕ mux + id demux
                      mock extension (stand-in for the SW)

    * start / system.info
    * tab.navigate
    * dom.get_content
    * dom.click
    * visual.screenshot (bytes round-trip → file)
    * dom.exec_js (eval)

Real-browser e2e is re-runnable via ``e2e_demo.py`` on Chromium or
Chrome Canary (no unpacked-load restriction). The code is identical.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from frago.chrome.extension.native_host import (
    SOCK_PATH, STABLE_EXTENSION_ID, encode_frame, read_frame_async,
)
from frago.chrome.backends.extension import ExtensionChromeBackend


REPO_ROOT = Path(__file__).resolve().parents[3]

# A minimal 1x1 red PNG, base64-encoded.
RED_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def mock_extension(sock_path: Path, stop_event: asyncio.Event) -> None:
    """Connect to the daemon as the extension side and answer MVP methods."""
    reader, writer = await asyncio.open_unix_connection(str(sock_path))
    writer.write(encode_frame({"role": "extension"}))
    await writer.drain()
    try:
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(read_frame_async(reader),
                                             timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                break
            method = msg.get("method")
            mid = msg.get("id")
            params = msg.get("params") or {}
            result = _dispatch(method, params)
            if isinstance(result, dict) and "__error__" in result:
                resp = {"jsonrpc": "2.0", "id": mid, "error": result["__error__"]}
            else:
                resp = {"jsonrpc": "2.0", "id": mid, "result": result}
            writer.write(encode_frame(resp))
            await writer.drain()
    finally:
        writer.close()


def _dispatch(method: str, params: dict):
    if method == "system.info":
        return {"extensionId": STABLE_EXTENSION_ID,
                "manifest": {"name": "frago bridge (mock)",
                             "version": "0.1.0"}}
    if method == "tab.navigate":
        return {"tab_id": 42, "url": params.get("url", ""),
                "title": "Example Domain"}
    if method == "dom.exec_js":
        script = params.get("script", "")
        try:
            value = eval(script, {"__builtins__": {}}, {})
        except Exception as e:
            return {"__error__": {"code": -32004, "message": str(e)}}
        return {"value": value}
    if method == "dom.get_content":
        return {"text": "Example Domain mock content",
                "html": "<html><body><h1>Example</h1></body></html>",
                "title": "Example Domain",
                "url": "https://example.com/"}
    if method == "dom.click":
        if not params.get("selector"):
            return {"__error__": {"code": -32602, "message": "selector required"}}
        return {"success": True}
    if method == "visual.screenshot":
        return {"tab_id": 42, "png_base64": RED_PNG_B64,
                "output": params.get("output")}
    return {"__error__": {"code": -32601, "message": f"method not found: {method}"}}


async def _run(out_dir: Path) -> int:
    # 1. Spawn daemon
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()
    daemon_log = out_dir / "daemon.log"
    daemon_proc = subprocess.Popen(
        [sys.executable, "-m", "frago.cli.main", "extension", "daemon"],
        stdout=open(daemon_log, "wb"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        # Wait for socket.
        deadline = time.time() + 5.0
        while time.time() < deadline and not SOCK_PATH.exists():
            await asyncio.sleep(0.1)
        if not SOCK_PATH.exists():
            raise RuntimeError("daemon socket not created")

        stop = asyncio.Event()
        ext_task = asyncio.create_task(mock_extension(SOCK_PATH, stop))
        # Give the mock extension a tick to send its hello frame.
        await asyncio.sleep(0.3)

        # Run backend calls in a worker thread so the sync DaemonClient
        # doesn't fight the mock extension's loop.
        steps: dict = {}

        def blocking_calls() -> dict:
            be = ExtensionChromeBackend(timeout=5.0)
            info = be.start()
            steps["start"] = info
            nav = be.navigate("https://example.com", group="mock")
            steps["navigate"] = {"tab_id": nav.tab_id,
                                 "url": nav.url, "title": nav.title}
            content = be.get_content(group="mock")
            steps["get_content"] = {"title": content.title,
                                    "text_preview": content.text[:80]}
            clk = be.click("a", group="mock")
            steps["click"] = {"success": clk.success}
            shot_path = out_dir / "mock_screenshot.png"
            shot = be.screenshot(group="mock", output=str(shot_path))
            steps["screenshot"] = {"path": shot.path,
                                   "png_bytes_on_disk": shot_path.stat().st_size}
            js = be.exec_js("1 + 2 * 3", group="mock")
            steps["exec_js"] = {"value": js.value}
            return steps

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, blocking_calls)

        stop.set()
        await asyncio.wait_for(ext_task, timeout=3.0)

        # Assertions (fail loud).
        assert steps["navigate"]["title"] == "Example Domain", steps
        assert "Example Domain" in steps["get_content"]["text_preview"]
        assert steps["click"]["success"] is True
        assert steps["screenshot"]["png_bytes_on_disk"] > 0
        assert steps["exec_js"]["value"] == 7

        log = out_dir / "mock_e2e_log.json"
        log.write_text(json.dumps({
            "extension_id": STABLE_EXTENSION_ID,
            "ok": True,
            "steps": steps,
        }, indent=2, default=str))
        print(f"[mock-e2e] OK — log: {log}")
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
        "FRAGO_E2E_OUT", str(REPO_ROOT / "outputs" / "e2e_mock")))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_run(out_dir))


if __name__ == "__main__":
    sys.exit(main())
