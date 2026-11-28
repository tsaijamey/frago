"""Cross-platform transport, Windows fallback, and no-AF_UNIX tests.

Verifies the full extension bridge stack when ``socket.AF_UNIX`` and/or
``asyncio.start_unix_server`` / ``open_unix_connection`` are unavailable
(matching real Windows Python runtimes) without requiring a Windows host:

1. Capability detection and automatic Loopback TCP fallback.
2. Loopback TCP listen/connect, 256-bit token auth (accept valid, reject
   missing/wrong), HTTP/DNS-rebinding probe rejection, non-loopback hijack
   rejection.
3. Liveness probing (authenticated ping), stale endpoint cleanup, port-reuse
   false-positive prevention, and extension reconnect.
4. Real end-to-end roundtrip: DaemonClient <-> Loopback TCP <-> Daemon <->
   Loopback TCP <-> run_relay (stdio pipes) <-> mock Chrome extension.
5. Windows Native Messaging launcher (.cmd), HKCU registry registration via
   winreg, detached subprocess kwargs, SIGKILL-free stop, and
   initialize_cft_environment under simulated Windows + missing AF_UNIX.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from frago.browser.backends import extension as ext_backend
from frago.browser.extension import lifecycle as lc
from frago.browser.extension import native_host as nh
from frago.browser.extension import transport as tr
from frago.browser.extension.protocol import encode_frame, read_frame_async, read_frame_sync
from frago.cli.extension_commands import extension_group


def _simulate_windows_no_af_unix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a Windows Python runtime lacking AF_UNIX and asyncio UDS APIs."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)
    monkeypatch.delattr(asyncio, "start_unix_server", raising=False)
    monkeypatch.delattr(asyncio, "open_unix_connection", raising=False)


class _FakeWinreg:
    """In-memory stand-in for Windows stdlib ``winreg``."""

    HKEY_CURRENT_USER = object()
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[tuple[object, str, str], tuple[int, str]] = {}

    class _KeyCtx:
        def __init__(self, root: object, subkey: str) -> None:
            self.root = root
            self.subkey = subkey

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    def CreateKey(self, root: object, subkey: str):
        return self._KeyCtx(root, subkey)

    def SetValueEx(self, key: _KeyCtx, name: str, _reserved: int, reg_type: int, value: str) -> None:
        self.values[(key.root, key.subkey, name)] = (reg_type, value)


# ─────────────────────── 1. Capability detection ───────────────────────


def test_capability_fallback_when_af_unix_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv(tr.TRANSPORT_ENV_VAR, raising=False)
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)

    assert tr.supports_asyncio_unix_sockets() is False
    assert tr.resolve_transport_mode() == "tcp"
    assert tr.should_use_unix_socket() is False
    # _daemon_alive must never raise AttributeError when socket.AF_UNIX is absent
    assert lc._daemon_alive(tmp_path / "extension.sock") is False


def test_capability_fallback_on_win32_even_if_af_unix_attr_exists(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(tr.TRANSPORT_ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    assert tr.supports_asyncio_unix_sockets() is False
    assert tr.resolve_transport_mode() == "tcp"


def test_capability_fallback_when_asyncio_unix_apis_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(tr.TRANSPORT_ENV_VAR, raising=False)
    monkeypatch.delattr(asyncio, "start_unix_server", raising=False)

    assert tr.supports_asyncio_unix_sockets() is False
    assert tr.resolve_transport_mode() == "tcp"


def test_env_override_forces_tcp(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(tr.TRANSPORT_ENV_VAR, "tcp")
    assert tr.resolve_transport_mode() == "tcp"
    assert tr.should_use_unix_socket() is False


# ─────────────── 2. Loopback TCP listen, auth & security ───────────────


@pytest.mark.asyncio
async def test_loopback_tcp_listen_auth_and_reject_invalid_peers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"

    token = tr.generate_auth_token()
    daemon = nh.Daemon(auth_token=token)
    handle = await tr.start_bridge_server(daemon.handle_conn, anchor, auth_token=token)

    try:
        assert handle.endpoint.transport == "tcp"
        assert handle.endpoint.host == "127.0.0.1"
        assert handle.endpoint.port and handle.endpoint.port > 0
        assert handle.endpoint.token == token
        # Log description must never expose the secret token
        assert token not in handle.describe()
        assert handle.meta_path.exists()

        # Liveness probe succeeds via authenticated ping (run in worker thread so
        # the in-process asyncio server loop can accept and answer the ping).
        assert await asyncio.to_thread(tr.probe_bridge_endpoint, anchor) is True
        assert await asyncio.to_thread(lc._daemon_alive, anchor) is True

        # 2a. Missing token is silently closed
        r_no, w_no = await asyncio.open_connection("127.0.0.1", handle.endpoint.port)
        w_no.write(encode_frame({"role": "client"}))
        await w_no.drain()
        assert await asyncio.wait_for(read_frame_async(r_no), timeout=2.0) is None
        w_no.close()

        # 2b. Wrong token is silently closed
        r_bad, w_bad = await asyncio.open_connection("127.0.0.1", handle.endpoint.port)
        w_bad.write(encode_frame({"role": "client", "token": "wrong-token-value"}))
        await w_bad.drain()
        assert await asyncio.wait_for(read_frame_async(r_bad), timeout=2.0) is None
        w_bad.close()

        # 2c. Cross-site HTTP / DNS rebinding probe is rejected immediately
        r_http, w_http = await asyncio.open_connection("127.0.0.1", handle.endpoint.port)
        w_http.write(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        await w_http.drain()
        assert await asyncio.wait_for(read_frame_async(r_http), timeout=2.0) is None
        w_http.close()

        # 2d. Valid token via open_bridge_connection is accepted (returns EXTENSION_NOT_READY
        # because no extension peer is attached yet, proving auth passed).
        client = nh.DaemonClient(anchor)
        resp = await client.call_async("system.info", {}, timeout=2.0)
        assert resp["error"]["code"] == nh.RPC_ERROR_CODES["EXTENSION_NOT_READY"]
        await client.close_async()
    finally:
        handle.server.close()
        await handle.server.wait_closed()
        handle.close_cleanup()

    assert not handle.meta_path.exists()
    assert tr.probe_bridge_endpoint(anchor) is False


def test_reject_tampered_non_loopback_metadata(tmp_path: Path):
    anchor = tmp_path / "extension.sock"
    meta = tr.endpoint_meta_path(anchor)
    meta.write_text(
        json.dumps(
            {
                "version": 1,
                "transport": "tcp",
                "host": "192.168.1.99",
                "port": 12345,
                "token": "a" * 32,
                "pid": os.getpid(),
            }
        ),
        encoding="utf-8",
    )
    assert tr.read_endpoint_metadata(anchor) is None
    with pytest.raises(FileNotFoundError):
        tr.resolve_endpoint(anchor)


# ───────── 3. Stale cleanup, port-reuse guard & reconnect ──────────


@pytest.mark.asyncio
async def test_stale_endpoint_cleanup_and_port_reuse_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"
    meta = tr.endpoint_meta_path(anchor)

    # Start an unrelated TCP listener on 127.0.0.1:0 that immediately closes
    # connections without speaking the authenticated ping protocol.
    async def _foreign_handler(_r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        w.write(b"NOT_FRAGO\n")
        await w.drain()
        w.close()

    foreign = await asyncio.start_server(_foreign_handler, "127.0.0.1", 0)
    foreign_port = int(foreign.sockets[0].getsockname()[1])
    try:
        meta.write_text(
            json.dumps(
                {
                    "version": 1,
                    "transport": "tcp",
                    "host": "127.0.0.1",
                    "port": foreign_port,
                    "token": "x" * 32,
                    "pid": 999999,
                }
            ),
            encoding="utf-8",
        )
        # Must NOT misidentify an unrelated process on a reused port as alive daemon.
        assert await asyncio.to_thread(tr.probe_bridge_endpoint, anchor) is False
    finally:
        foreign.close()
        await foreign.wait_closed()

    # Stale socket + metadata files must be cleaned automatically on fresh server start.
    anchor.write_text("stale", encoding="utf-8")
    token = tr.generate_auth_token()
    daemon = nh.Daemon(auth_token=token)
    handle = await tr.start_bridge_server(daemon.handle_conn, anchor, auth_token=token)
    try:
        assert not anchor.exists()  # stale .sock wiped in tcp mode
        assert await asyncio.to_thread(tr.probe_bridge_endpoint, anchor) is True
        assert handle.endpoint.port != foreign_port
    finally:
        handle.server.close()
        await handle.server.wait_closed()
        handle.close_cleanup()


@pytest.mark.asyncio
async def test_close_cleanup_does_not_clobber_newer_daemon_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"
    token = tr.generate_auth_token()
    daemon = nh.Daemon(auth_token=token)
    handle = await tr.start_bridge_server(daemon.handle_conn, anchor, auth_token=token)
    try:
        # Simulate another newer daemon taking over the descriptor file.
        meta_data = json.loads(handle.meta_path.read_text(encoding="utf-8"))
        meta_data["pid"] = os.getpid() + 12345
        handle.meta_path.write_text(json.dumps(meta_data), encoding="utf-8")
    finally:
        handle.server.close()
        await handle.server.wait_closed()
        handle.close_cleanup()

    # Newer daemon's metadata must remain untouched.
    assert handle.meta_path.exists()
    tr.cleanup_bridge_endpoint(anchor)


@pytest.mark.asyncio
async def test_extension_disconnect_and_reconnect_over_loopback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"
    token = tr.generate_auth_token()
    daemon = nh.Daemon(auth_token=token)
    handle = await tr.start_bridge_server(daemon.handle_conn, anchor, auth_token=token)

    async def _run_mock_ext(tag: str) -> None:
        r, w = await tr.open_bridge_connection(anchor, role="extension")
        msg = await read_frame_async(r)
        assert msg is not None
        w.write(encode_frame({"jsonrpc": "2.0", "id": msg["id"], "result": {"tag": tag}}))
        await w.drain()
        w.close()
        with contextlib.suppress(Exception):
            await w.wait_closed()

    try:
        # First connection
        t1 = asyncio.create_task(_run_mock_ext("first"))
        await asyncio.sleep(0.05)
        c1 = nh.DaemonClient(anchor)
        resp1 = await c1.call_async("system.info", {}, timeout=3.0)
        assert resp1["result"]["tag"] == "first"
        await c1.close_async()
        await asyncio.wait_for(t1, timeout=2.0)

        # Wait briefly so daemon clears previous extension slot, then reconnect
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(_run_mock_ext("reconnected"))
        await asyncio.sleep(0.05)
        c2 = nh.DaemonClient(anchor)
        resp2 = await c2.call_async("system.info", {}, timeout=3.0)
        assert resp2["result"]["tag"] == "reconnected"
        await c2.close_async()
        await asyncio.wait_for(t2, timeout=2.0)
    finally:
        handle.server.close()
        await handle.server.wait_closed()
        handle.close_cleanup()


# ────── 4. Full E2E: DaemonClient <-> Daemon <-> run_relay (stdio) ──────


@pytest.mark.asyncio
async def test_e2e_daemon_relay_client_roundtrip_without_af_unix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """End-to-end test over Loopback TCP with real run_daemon + run_relay + DaemonClient."""
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"

    # Pipe pair simulating Chrome Native Messaging stdio:
    # chrome_to_relay: test writes frames -> relay reads sys.stdin.buffer
    # relay_to_chrome: relay writes sys.stdout.buffer -> test reads frames
    c2r_r_fd, c2r_w_fd = os.pipe()
    r2c_r_fd, r2c_w_fd = os.pipe()

    c2r_reader = os.fdopen(c2r_r_fd, "rb", buffering=0)
    c2r_writer = os.fdopen(c2r_w_fd, "wb", buffering=0)
    r2c_reader = os.fdopen(r2c_r_fd, "rb", buffering=0)
    r2c_writer = os.fdopen(r2c_w_fd, "wb", buffering=0)

    fake_stdin = types.SimpleNamespace(buffer=c2r_reader, fileno=c2r_reader.fileno)
    fake_stdout = types.SimpleNamespace(buffer=r2c_writer, fileno=r2c_writer.fileno)
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    daemon_task = asyncio.create_task(nh.run_daemon(anchor))
    try:
        # Wait until daemon endpoint is live (probe in worker thread so loop serves ping)
        for _ in range(50):
            if await asyncio.to_thread(tr.probe_bridge_endpoint, anchor, 0.2):
                break
            await asyncio.sleep(0.05)
        assert await asyncio.to_thread(tr.probe_bridge_endpoint, anchor) is True

        relay_task = asyncio.create_task(nh.run_relay(anchor))
        await asyncio.sleep(0.08)

        # Simulate Chrome extension reading one request from relay stdout and replying on relay stdin
        loop = asyncio.get_running_loop()

        def _chrome_extension_side() -> dict:
            req = read_frame_sync(r2c_reader)
            assert req is not None
            reply = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "ok": True,
                    "method": req["method"],
                    "url": req["params"]["url"],
                },
            }
            c2r_writer.write(encode_frame(reply))
            c2r_writer.flush()
            c2r_writer.close()  # Signal EOF to cleanly stop relay
            return req

        ext_fut = loop.run_in_executor(None, _chrome_extension_side)

        client = nh.DaemonClient(anchor)
        try:
            resp = await client.call_async(
                "tab.navigate",
                {"url": "https://example.com", "group": "win-e2e"},
                timeout=5.0,
            )
        finally:
            await client.close_async()

        forwarded = await asyncio.wait_for(ext_fut, timeout=3.0)
        assert forwarded["method"] == "tab.navigate"
        assert resp["result"] == {
            "ok": True,
            "method": "tab.navigate",
            "url": "https://example.com",
        }
        await asyncio.wait_for(relay_task, timeout=3.0)
    finally:
        daemon_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await daemon_task
        for f in (c2r_reader, c2r_writer, r2c_reader, r2c_writer):
            with contextlib.suppress(Exception):
                f.close()

    # Daemon shutdown cleans up its own endpoint metadata
    assert not tr.endpoint_meta_path(anchor).exists()


# ─────── 5. Windows Native Messaging, launcher & lifecycle ───────


def test_windows_launcher_registry_and_cft_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _simulate_windows_no_af_unix(monkeypatch)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    fake_winreg = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Python312\python.exe")

    # default_manifest_dir must work on Windows without NotImplementedError
    cft_dir = nh.default_manifest_dir("cft")
    assert cft_dir == fake_home / ".frago" / "profiles" / "cft" / "extension" / "NativeMessagingHosts"
    assert nh.default_manifest_dir("edge").name == "NativeMessagingHosts"

    # Full initialize_cft_environment must succeed cleanly with ensure_daemon=False
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "frago", "version": "0.4.0", "permissions": []}),
        encoding="utf-8",
    )

    info = lc.initialize_cft_environment(bundle_dir=bundle, ensure_daemon=False)
    launcher = Path(info["launcher_path"])
    assert launcher.name == "native_host_launcher.cmd"
    assert launcher.exists()
    launcher_raw = launcher.read_bytes()
    assert launcher_raw.startswith(b"@echo off\r\nchcp 65001 >nul\r\n")
    assert (
        b'"C:\\Program Files\\Python312\\python.exe" -m frago.cli.main extension native-host\r\n'
        in launcher_raw
    )
    assert b"%*" not in launcher_raw

    manifest_path = Path(info["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["path"] == str(launcher)
    assert manifest["name"] == nh.HOST_NAME

    # Verify HKCU registry entries written for Chrome/CfT and Chromium
    expected_val = (fake_winreg.REG_SZ, str(manifest_path.resolve()))
    assert fake_winreg.values[
        (fake_winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\NativeMessagingHosts\com.frago.bridge", "")
    ] == expected_val
    assert fake_winreg.values[
        (fake_winreg.HKEY_CURRENT_USER, r"Software\Chromium\NativeMessagingHosts\com.frago.bridge", "")
    ] == expected_val


def test_windows_launcher_utf8_chinese_path_and_percent_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P1-1: .cmd launcher switches to UTF-8 codepage silently and escapes %."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", r"C:\Users\张三\100%dev\Python312\python.exe")

    launcher = tr.ensure_native_host_launcher(base_dir=tmp_path)
    assert launcher.name == "native_host_launcher.cmd"
    raw = launcher.read_bytes()
    expected = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        '"C:\\Users\\张三\\100%%dev\\Python312\\python.exe" -m frago.cli.main extension native-host\r\n'
    ).encode()
    assert raw == expected
    assert b"%*" not in raw


def test_native_host_cli_accepts_chrome_windows_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P0-1: Click native-host command tolerates Chrome's origin + --parent-window args."""
    called_socks: list[Path] = []

    async def _fake_run_relay(sock_path: Path = nh.SOCK_PATH) -> None:
        called_socks.append(sock_path)

    monkeypatch.setattr(nh, "run_relay", _fake_run_relay)

    runner = CliRunner()
    res = runner.invoke(
        extension_group,
        [
            "native-host",
            "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
            "--parent-window=12345",
        ],
    )
    assert res.exit_code == 0, res.output
    assert called_socks == [nh.SOCK_PATH]

    # Explicit --sock still works alongside Chrome's extra native messaging args.
    custom_sock = tmp_path / "custom.sock"
    called_socks.clear()
    res2 = runner.invoke(
        extension_group,
        [
            "native-host",
            "--sock",
            str(custom_sock),
            "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
            "--parent-window=67890",
        ],
    )
    assert res2.exit_code == 0, res2.output
    assert called_socks == [custom_sock]


def test_windows_detached_subprocess_kwargs(monkeypatch: pytest.MonkeyPatch):
    """P1-2: hide_window=True hides daemon console; hide_window=False keeps GUI visible."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    class _FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    monkeypatch.setattr(subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)

    # Default (hide_window=True): background daemon hides console window.
    kw_hidden = tr.detached_subprocess_kwargs()
    assert "start_new_session" not in kw_hidden
    assert "creationflags" in kw_hidden
    assert kw_hidden["creationflags"] & 0x08000000  # CREATE_NO_WINDOW
    assert kw_hidden["creationflags"] & 0x00000008  # DETACHED_PROCESS
    assert "startupinfo" in kw_hidden
    assert kw_hidden["startupinfo"].dwFlags & 0x00000001
    assert kw_hidden["startupinfo"].wShowWindow == 0

    # hide_window=False: headful GUI browser never receives CREATE_NO_WINDOW or SW_HIDE.
    kw_gui = tr.detached_subprocess_kwargs(hide_window=False)
    assert "start_new_session" not in kw_gui
    assert "startupinfo" not in kw_gui
    assert kw_gui["creationflags"] == (0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    assert not (kw_gui["creationflags"] & 0x08000000)  # no CREATE_NO_WINDOW


def test_launch_chrome_with_extension_does_not_hide_window_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P1-2: launch_chrome_with_extension passes hide_window=False on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    class _FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    monkeypatch.setattr(subprocess, "STARTUPINFO", _FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)

    captured: dict[str, object] = {}

    def _fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(pid=4321)

    monkeypatch.setattr(ext_backend.subprocess, "Popen", _fake_popen)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    profile = tmp_path / "profile"

    proc = ext_backend.launch_chrome_with_extension(
        bundle_dir=bundle,
        user_data_dir=profile,
        chrome_binary=r"C:\chrome\chrome.exe",
        brand="cft",
    )
    assert proc.pid == 4321
    kw = captured["kwargs"]
    assert isinstance(kw, dict)
    assert "startupinfo" not in kw
    assert "start_new_session" not in kw
    assert kw["creationflags"] == (0x00000008 | 0x00000200)
    assert not (kw["creationflags"] & 0x08000000)


def test_kill_with_grace_without_sigkill_uses_taskkill(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delattr(signal, "SIGKILL", raising=False)
    alive = {"flag": True}
    monkeypatch.setattr(lc, "is_pid_alive", lambda _pid: alive["flag"])

    calls: list[list[str]] = []

    def _fake_run(cmd, **_kw):
        calls.append(list(cmd))
        alive["flag"] = False
        return types.SimpleNamespace(returncode=0)

    with patch("os.kill"), patch.object(lc.subprocess, "run", side_effect=_fake_run):
        stopped, forced = lc._kill_with_grace(4242, timeout=0.05)

    assert stopped is True
    assert forced is True
    assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_configure_stdio_binary_mode_invokes_msvcrt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "win32")
    recorded: list[tuple[int, int]] = []
    fake_msvcrt = types.SimpleNamespace(setmode=lambda fd, mode: recorded.append((fd, mode)))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(fileno=lambda: 10))
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(fileno=lambda: 11))

    tr.configure_stdio_binary_mode()
    o_binary = getattr(os, "O_BINARY", 0x8000)
    assert recorded == [(10, o_binary), (11, o_binary)]


def test_read_frame_sync_rejects_oversized_and_malformed():
    # Oversized header ("GET " = 542 MiB > 64 MiB)
    assert read_frame_sync(io.BytesIO(b"GET / HTTP/1.1")) is None
    # Zero length header
    assert read_frame_sync(io.BytesIO(b"\x00\x00\x00\x00")) is None
    # Invalid JSON payload
    bad_payload = b"not-json"
    assert read_frame_sync(io.BytesIO(len(bad_payload).to_bytes(4, "little") + bad_payload)) is None


# ─────────────── 6. P2 hardening: fd safety, server cleanup, handshake timeout ───────────────


def test_atomic_write_json_does_not_double_close_fd_on_write_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P2: Once os.fdopen() takes ownership of fd, write failures must not call os.close(fd)."""
    target = tmp_path / "endpoint.json"
    real_fdopen = os.fdopen
    real_close = os.close
    explicit_close_calls: list[int] = []

    class _FailingStream:
        def __init__(self, inner) -> None:
            self._inner = inner

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self._inner.close()
            return False

        def write(self, _data: bytes) -> int:
            raise OSError("simulated disk write failure")

        def flush(self) -> None:
            pass

    def _wrapped_fdopen(fd: int, mode: str = "r", *args, **kwargs):
        return _FailingStream(real_fdopen(fd, mode, *args, **kwargs))

    def _spy_close(fd: int) -> None:
        explicit_close_calls.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "fdopen", _wrapped_fdopen)
    monkeypatch.setattr(os, "close", _spy_close)

    with pytest.raises(OSError, match="simulated disk write failure"):
        tr._atomic_write_json(target, {"ok": True})

    # fd was owned and closed by _FailingStream.__exit__; os.close must never be called on it.
    assert explicit_close_calls == []
    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_start_bridge_server_closes_socket_when_metadata_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P2: Bound TCP listener must be closed if _atomic_write_json raises."""
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"

    bound_servers: list[asyncio.AbstractServer] = []
    real_start_server = asyncio.start_server

    async def _spy_start_server(*args, **kwargs):
        srv = await real_start_server(*args, **kwargs)
        bound_servers.append(srv)
        return srv

    monkeypatch.setattr(asyncio, "start_server", _spy_start_server)
    monkeypatch.setattr(
        tr,
        "_atomic_write_json",
        lambda _path, _payload: (_ for _ in ()).throw(OSError("metadata write failed")),
    )

    daemon = nh.Daemon(auth_token=tr.generate_auth_token())
    with pytest.raises(OSError, match="metadata write failed"):
        await tr.start_bridge_server(daemon.handle_conn, anchor)

    assert len(bound_servers) == 1
    assert bound_servers[0].is_serving() is False


@pytest.mark.asyncio
async def test_daemon_tcp_handshake_timeout_closes_stalled_peer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P2: Loopback TCP mode closes peers that stall without sending the hello frame."""
    _simulate_windows_no_af_unix(monkeypatch)
    anchor = tmp_path / "extension.sock"
    token = tr.generate_auth_token()
    daemon = nh.Daemon(auth_token=token, handshake_timeout=0.15)
    handle = await tr.start_bridge_server(daemon.handle_conn, anchor, auth_token=token)

    try:
        assert handle.endpoint.port is not None
        reader, writer = await asyncio.open_connection("127.0.0.1", handle.endpoint.port)
        try:
            # Peer intentionally sends nothing; daemon must close connection after timeout.
            data = await asyncio.wait_for(reader.read(16), timeout=2.0)
            assert data == b""
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
    finally:
        handle.server.close()
        await handle.server.wait_closed()
        handle.close_cleanup()
