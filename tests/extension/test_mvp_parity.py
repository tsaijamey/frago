"""P1 MVP parity tests.

Real parity (cdp backend vs extension backend against a real browser) is
deferred — it requires a full Chrome + bundle load + manifest install
chain that we can't build in unit tests. What we validate here:

1. Protocol framing (encode/decode round-trip).
2. Daemon multiplexing: CLI client <-> daemon <-> mock extension.
3. Both backends (CDP + Extension) implement the same 6 MVP methods.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from frago.chrome.extension import protocol
from frago.chrome.extension.native_host import (
    Daemon, encode_frame, read_frame_async,
)
from frago.chrome.backends.base import ChromeBackend
from frago.chrome.backends.cdp import CDPChromeBackend
from frago.chrome.backends.extension import ExtensionChromeBackend


# ─────────────────────────── 1. protocol ───────────────────────────

def test_frame_roundtrip():
    msg = {"jsonrpc": "2.0", "id": "x", "method": "tab.navigate",
           "params": {"url": "https://example.com", "group": "t"}}
    frame = encode_frame(msg)
    assert len(frame) > 4
    length = int.from_bytes(frame[:4], "little")
    assert length == len(frame) - 4


def test_rpc_dataclasses_serialize():
    req = protocol.RpcRequest(method="foo", params={"a": 1}, id="r1")
    assert req.to_json() == {"jsonrpc": "2.0", "id": "r1",
                             "method": "foo", "params": {"a": 1}}
    err = protocol.RpcError(code=-32004, message="boom")
    resp = protocol.RpcResponse(id="r1", error=err)
    j = resp.to_json()
    assert j["error"]["code"] == -32004
    assert "result" not in j


# ────────────────────────── 2. daemon mux ──────────────────────────

@pytest.mark.asyncio
async def test_daemon_roundtrip(tmp_path):
    sock = tmp_path / "t.sock"
    daemon = Daemon()
    server = await asyncio.start_unix_server(daemon.handle_conn,
                                             path=str(sock))

    async def mock_extension_once():
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(encode_frame({"role": "extension"}))
        await writer.drain()
        # Handle exactly one request then exit cleanly.
        msg = await read_frame_async(reader)
        resp = {"jsonrpc": "2.0", "id": msg["id"],
                "result": {"echo": msg["params"]}}
        writer.write(encode_frame(resp))
        await writer.drain()
        writer.close()

    async def client_request():
        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(encode_frame({"role": "client"}))
        await writer.drain()
        req = {"jsonrpc": "2.0", "id": "c1",
               "method": "tab.navigate",
               "params": {"url": "https://example.com", "group": "t"}}
        writer.write(encode_frame(req))
        await writer.drain()
        resp = await read_frame_async(reader)
        writer.close()
        return resp

    try:
        ext_task = asyncio.create_task(mock_extension_once())
        # Yield so the extension connects first.
        await asyncio.sleep(0.1)
        resp = await asyncio.wait_for(client_request(), timeout=5.0)
        assert resp is not None
        assert resp["id"] == "c1"
        assert resp["result"]["echo"]["url"] == "https://example.com"
        await asyncio.wait_for(ext_task, timeout=2.0)
    finally:
        server.close()
        await server.wait_closed()


# ────────────────── 3. Both backends implement MVP ──────────────────

def test_both_backends_implement_mvp():
    mvp = {"start", "navigate", "exec_js", "get_content", "click", "screenshot"}
    for cls in (CDPChromeBackend, ExtensionChromeBackend):
        assert issubclass(cls, ChromeBackend), cls
        impls = {name for name, _ in inspect.getmembers(cls, inspect.isfunction)}
        missing = mvp - impls
        assert not missing, f"{cls.__name__} missing MVP methods: {missing}"


def test_extension_backend_signatures_match_cdp():
    """Both backends accept compatible call shapes for MVP methods."""
    for method in ("navigate", "exec_js", "get_content", "click", "screenshot"):
        cdp_sig = inspect.signature(getattr(CDPChromeBackend, method))
        ext_sig = inspect.signature(getattr(ExtensionChromeBackend, method))
        cdp_params = [p for p in cdp_sig.parameters if p != "self"]
        ext_params = [p for p in ext_sig.parameters if p != "self"]
        assert cdp_params == ext_params, \
            f"{method}: cdp={cdp_params} ext={ext_params}"


# ────────────────── 4. `frago chrome --backend` wiring ──────────────────

def test_chrome_group_exposes_backend_flag():
    """--backend option is registered on the chrome group itself."""
    from frago.cli.chrome_commands import chrome_group
    opts = {p.name for p in chrome_group.params}
    assert "backend" in opts, f"chrome group params: {opts}"


def test_chrome_backend_extension_routes_to_extension_backend(monkeypatch):
    """`frago chrome --backend extension <mvp-cmd>` dispatches to extension backend.

    For most commands this means calling FakeBackend methods directly.
    For ``start`` the dispatch goes through the orchestration function
    :func:`start_extension_bridge` (E task) which spawns daemon + browser,
    so we mock that instead.
    """
    from click.testing import CliRunner
    from frago.cli import chrome_commands as cc
    from frago.chrome.extension import lifecycle as lc

    calls: list[tuple] = []

    class FakeBackend:
        def navigate(self, url, group, *, timeout=15.0):
            calls.append(("navigate", url, group))
            from frago.chrome.backends.base import NavigateResult
            return NavigateResult(tab_id=1, url=url, title="T")

    fake_startup = lc.BridgeStartupResult(
        daemon_pid=42, daemon_was_already_running=False,
        browser_pid=99, browser_path="/usr/bin/microsoft-edge",
        browser_brand="edge", profile_dir="/tmp/p",
        bundle_dir="/tmp/b", manifest_path="/tmp/m.json",
        extension_id="abc",
    )

    monkeypatch.setattr(cc, "_ext_backend", lambda: FakeBackend())
    monkeypatch.setattr(lc, "start_extension_bridge",
                        lambda **kwargs: (calls.append(("start", kwargs))
                                          or fake_startup))

    runner = CliRunner()
    r = runner.invoke(cc.chrome_group, ["--backend", "extension", "start"])
    assert r.exit_code == 0, r.output
    assert calls[0][0] == "start", calls

    calls.clear()
    r = runner.invoke(cc.chrome_group, ["--backend", "extension",
                                        "navigate", "https://x",
                                        "--group", "t"])
    assert r.exit_code == 0, r.output
    assert calls[0][:2] == ("navigate", "https://x"), calls
