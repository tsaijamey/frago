"""Native messaging host + daemon.

Two roles, chosen by CLI flag:

* ``frago extension daemon`` — long-running singleton. Listens on a unix
  socket at ``~/.frago/chrome/extension.sock``. Multiplexes between two
  kinds of peers:
    - exactly one *extension peer* (the relay child of Chrome);
    - any number of *client peers* (CLI invocations that want to send
      commands to the extension).

* ``frago extension native-host`` — short-lived relay. Spawned by Chrome
  via the native messaging manifest. Reads stdio frames from Chrome, writes
  them to the daemon over uds, and pipes daemon → stdio back.

A request from a CLI client is routed to the extension with a fresh id;
the response is routed back to the originating client. Events pushed by
the extension (id=None) are broadcast to all client peers.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from pathlib import Path
from typing import Optional

from .protocol import (
    RPC_ERROR_CODES,
    encode_frame,
    read_frame_async,
)


SOCK_PATH = Path.home() / ".frago" / "chrome" / "extension.sock"


# ═══════════════════════════ Daemon ═══════════════════════════════


class Daemon:
    """Singleton multiplexer between extension stdio relay and CLI clients."""

    def __init__(self) -> None:
        self._extension_writer: Optional[asyncio.StreamWriter] = None
        self._extension_ready = asyncio.Event()
        # pending[id_from_extension] = (client_writer, original_client_id)
        self._pending: dict[str, tuple[asyncio.StreamWriter, Optional[str]]] = {}
        self._clients: set[asyncio.StreamWriter] = set()
        self._next_id = 0

    def _alloc_id(self) -> str:
        self._next_id += 1
        return f"d-{self._next_id}"

    async def handle_conn(self, reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter) -> None:
        # First frame must be a hello identifying the role.
        hello = await read_frame_async(reader)
        if hello is None:
            writer.close()
            return
        role = hello.get("role")
        if role == "extension":
            await self._handle_extension(reader, writer)
        else:
            await self._handle_client(reader, writer)

    async def _handle_extension(self, reader: asyncio.StreamReader,
                                writer: asyncio.StreamWriter) -> None:
        if self._extension_writer is not None:
            # Silently drop. Writing an error frame back over the relay
            # would surface as a port message in the SW and trip its
            # onDisconnect cascade. The duplicate connection happens
            # naturally during MV3 SW lifecycle storms; tolerate it.
            sys.stderr.write("[daemon] duplicate extension conn, dropping silently\n")
            sys.stderr.flush()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        self._extension_writer = writer
        self._extension_ready.set()
        try:
            while True:
                msg = await read_frame_async(reader)
                if msg is None:
                    break
                await self._route_from_extension(msg)
        finally:
            self._extension_writer = None
            self._extension_ready.clear()
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        self._clients.add(writer)
        try:
            while True:
                msg = await read_frame_async(reader)
                if msg is None:
                    break
                await self._route_from_client(msg, writer)
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    async def _route_from_client(self, msg: dict,
                                 client: asyncio.StreamWriter) -> None:
        # Client → extension. Rewrite id for fan-in demux, record mapping.
        if self._extension_writer is None:
            err = {"jsonrpc": "2.0", "id": msg.get("id"),
                   "error": {"code": RPC_ERROR_CODES["EXTENSION_NOT_READY"],
                             "message": "extension not connected"}}
            client.write(encode_frame(err))
            await client.drain()
            return
        original_id = msg.get("id")
        daemon_id = self._alloc_id()
        out = dict(msg)
        out["id"] = daemon_id
        self._pending[daemon_id] = (client, original_id)
        self._extension_writer.write(encode_frame(out))
        await self._extension_writer.drain()

    async def _route_from_extension(self, msg: dict) -> None:
        mid = msg.get("id")
        if mid is None:
            # Event broadcast.
            frame = encode_frame(msg)
            dead: list = []
            for c in self._clients:
                try:
                    c.write(frame)
                    await c.drain()
                except Exception:
                    dead.append(c)
            for c in dead:
                self._clients.discard(c)
            return
        entry = self._pending.pop(mid, None)
        if entry is None:
            return
        client, original_id = entry
        out = dict(msg)
        out["id"] = original_id
        try:
            client.write(encode_frame(out))
            await client.drain()
        except Exception:
            pass


async def run_daemon(sock_path: Path = SOCK_PATH) -> None:
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()
    daemon = Daemon()
    server = await asyncio.start_unix_server(daemon.handle_conn,
                                             path=str(sock_path))
    os.chmod(sock_path, 0o600)
    sys.stderr.write(f"[frago-extension-daemon] listening on {sock_path}\n")
    sys.stderr.flush()
    async with server:
        await server.serve_forever()


# ═══════════════════════════ Relay ═══════════════════════════════


def _read_stdio_frame() -> Optional[dict]:
    header = sys.stdin.buffer.read(4)
    if not header or len(header) < 4:
        return None
    (length,) = struct.unpack("<I", header)
    body = sys.stdin.buffer.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


def _write_stdio_frame(obj: dict) -> None:
    sys.stdout.buffer.write(encode_frame(obj))
    sys.stdout.buffer.flush()


async def run_relay(sock_path: Path = SOCK_PATH) -> None:
    """Relay stdio ↔ unix socket for the Chrome-spawned native host."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
    except Exception as e:
        sys.stderr.write(f"[relay] cannot connect daemon at {sock_path}: {e!r}\n")
        sys.stderr.flush()
        raise
    writer.write(encode_frame({"role": "extension"}))
    await writer.drain()

    loop = asyncio.get_running_loop()

    async def stdio_to_uds() -> None:
        while True:
            msg = await loop.run_in_executor(None, _read_stdio_frame)
            if msg is None:
                writer.close()
                return
            writer.write(encode_frame(msg))
            await writer.drain()

    async def uds_to_stdio() -> None:
        while True:
            msg = await read_frame_async(reader)
            if msg is None:
                return
            await loop.run_in_executor(None, _write_stdio_frame, msg)

    await asyncio.gather(stdio_to_uds(), uds_to_stdio(),
                         return_exceptions=True)


# ═══════════════════════════ Client ═══════════════════════════════


class DaemonClient:
    """Sync-ish client for CLI-side use. One client per process is fine."""

    def __init__(self, sock_path: Path = SOCK_PATH) -> None:
        self.sock_path = sock_path
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._next_id = 0

    async def _connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self.sock_path))
        # Hello as client.
        self._writer.write(encode_frame({"role": "client"}))
        await self._writer.drain()

    async def call_async(self, method: str, params: dict,
                         timeout: float = 30.0) -> dict:
        if self._writer is None:
            await self._connect()
        assert self._writer is not None and self._reader is not None
        self._next_id += 1
        mid = f"c-{self._next_id}"
        req = {"jsonrpc": "2.0", "id": mid,
               "method": method, "params": params}
        self._writer.write(encode_frame(req))
        await self._writer.drain()
        while True:
            msg = await asyncio.wait_for(read_frame_async(self._reader),
                                         timeout=timeout)
            if msg is None:
                raise RuntimeError("daemon closed connection")
            if msg.get("id") == mid:
                return msg
            # else: event or stale; ignore.

    def call(self, method: str, params: dict,
             timeout: float = 30.0) -> dict:
        async def _once():
            try:
                return await self.call_async(method, params, timeout)
            finally:
                if self._writer is not None:
                    self._writer.close()
                    try:
                        await self._writer.wait_closed()
                    except Exception:
                        pass
                    self._writer = None
                    self._reader = None
        return asyncio.run(_once())

    async def close_async(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            self._reader = None

    def close(self) -> None:
        # call() already closes the writer in its own loop; this is a no-op.
        self._writer = None
        self._reader = None


# ═══════════════════════ Manifest installer ═══════════════════════════


HOST_NAME = "com.frago.bridge"

# Stable extension ID derived from the RSA pubkey pinned in
# src/frago/_resources/extension_bundle/manifest.json. See scripts/generate_extension_id.py
# and src/frago/_resources/extension_bundle/keys/README.md.
STABLE_EXTENSION_ID = "eajjhcepifleiifebabkjmhampcephfp"


def manifest_dict(executable: str, allowed_origins: list[str]) -> dict:
    return {
        "name": HOST_NAME,
        "description": "frago native messaging bridge",
        "path": executable,
        "type": "stdio",
        "allowed_origins": allowed_origins,
    }


# Per-brand native-messaging manifest roots. Each entry is the path
# *up to but not including* the trailing ``NativeMessagingHosts``
# segment — Chromium derives the manifest dir as ``<user-data-dir>/
# NativeMessagingHosts/`` where ``<user-data-dir>`` defaults to these
# brand-specific locations. With ``--user-data-dir=<custom>`` overridden
# (frago's normal mode), the manifest follows the override, not these
# defaults — see install_manifest's ``target_dir`` argument.
_MANIFEST_ROOTS_LINUX = {
    "edge":          "~/.config/microsoft-edge",
    "edge-beta":     "~/.config/microsoft-edge-beta",
    "edge-dev":      "~/.config/microsoft-edge-dev",
    "chromium":      "~/.config/chromium",
    "chrome":        "~/.config/google-chrome",
    "chrome-beta":   "~/.config/google-chrome-beta",
    "chrome-dev":    "~/.config/google-chrome-dev",
    "chrome-canary": "~/.config/google-chrome-unstable",
    "brave":         "~/.config/BraveSoftware/Brave-Browser",
    "vivaldi":       "~/.config/vivaldi",
}

_MANIFEST_ROOTS_MACOS = {
    "edge":          "~/Library/Application Support/Microsoft Edge",
    "edge-beta":     "~/Library/Application Support/Microsoft Edge Beta",
    "edge-dev":      "~/Library/Application Support/Microsoft Edge Dev",
    "chromium":      "~/Library/Application Support/Chromium",
    "chrome":        "~/Library/Application Support/Google/Chrome",
    "chrome-beta":   "~/Library/Application Support/Google/Chrome Beta",
    "chrome-dev":    "~/Library/Application Support/Google/Chrome Dev",
    "chrome-canary": "~/Library/Application Support/Google/Chrome Canary",
    "brave":         "~/Library/Application Support/BraveSoftware/Brave-Browser",
    "vivaldi":       "~/Library/Application Support/Vivaldi",
}


def default_manifest_dir(brand: str = "edge") -> Path:
    """Per-user native-messaging manifest dir for a Chromium brand.

    Returns ``<brand-default-profile-root>/NativeMessagingHosts/``.
    Cross-OS for Linux/macOS. Windows uses registry-based registration
    (not implemented yet — D2 task); raises NotImplementedError there.

    For frago's isolated-profile model the caller passes
    ``--user-data-dir`` to the browser and should write the manifest
    into ``<udd>/NativeMessagingHosts/`` instead — see
    :func:`install_manifest`'s ``target_dir`` argument.
    """
    import platform as _pl
    system = _pl.system()
    if system == "Linux":
        roots = _MANIFEST_ROOTS_LINUX
    elif system == "Darwin":
        roots = _MANIFEST_ROOTS_MACOS
    elif system == "Windows":
        raise NotImplementedError(
            "Windows native messaging manifests are registered via the "
            "HKCU registry, not the filesystem. See D2 task."
        )
    else:
        raise NotImplementedError(f"unsupported OS: {system}")
    if brand not in roots:
        raise ValueError(
            f"unknown browser brand: {brand!r}; known: {sorted(roots)}"
        )
    return Path(roots[brand]).expanduser() / "NativeMessagingHosts"


def chrome_manifest_dir() -> Path:
    """[deprecated] Returns Chrome Stable's manifest dir on Linux.

    Kept for backward compatibility. New code should use
    :func:`default_manifest_dir` with an explicit brand argument.
    """
    return default_manifest_dir("chrome")


def install_manifest(executable: str,
                     extension_id: str = STABLE_EXTENSION_ID,
                     target_dir: Optional[Path] = None,
                     brand: str = "edge") -> Path:
    """Write the native-messaging host manifest.

    Args:
        executable: Absolute path to the host launcher (the script Chrome
            will spawn when the extension calls connectNative).
        extension_id: Pinned extension ID; only this extension is allowed
            to connect to the host.
        target_dir: Where to drop ``com.frago.bridge.json``. If None,
            falls back to ``default_manifest_dir(brand)`` — pass an
            explicit ``<udd>/NativeMessagingHosts/`` when running with
            ``--user-data-dir`` overridden (frago's normal mode).
        brand: Browser brand for the default-dir lookup. Ignored if
            ``target_dir`` is given. See :func:`default_manifest_dir`.

    Returns the absolute path of the written manifest file.
    """
    if target_dir is None:
        target_dir = default_manifest_dir(brand)
    target_dir.mkdir(parents=True, exist_ok=True)
    allowed = [f"chrome-extension://{extension_id}/"]
    path = target_dir / f"{HOST_NAME}.json"
    path.write_text(json.dumps(manifest_dict(executable, allowed), indent=2))
    return path
