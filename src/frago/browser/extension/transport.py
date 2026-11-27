"""Cross-platform IPC transport abstraction for the browser extension bridge.

Centralizes all OS and socket capability differences so that the daemon,
native-messaging relay, CLI clients, and lifecycle orchestration speak a single
transport contract:

* **POSIX (macOS / Linux)** when ``socket.AF_UNIX`` and ``asyncio`` Unix socket
  APIs are available: listens on a ``0o600`` Unix domain socket at the logical
  endpoint anchor (default ``~/.frago/chrome/extension.sock``) and writes a
  companion runtime endpoint descriptor (``extension.endpoint.json``) with its
  PID for reliable lifecycle management. Backward compatible with peers or
  tests that connect directly to ``extension.sock`` without reading the
  descriptor.
* **Windows (and any Python runtime lacking ``AF_UNIX`` / ``asyncio`` Unix
  socket support, or when ``FRAGO_EXTENSION_TRANSPORT=tcp`` is set)**: binds an
  ephemeral ``127.0.0.1:0`` loopback TCP port protected by a 256-bit
  cryptographic session token (``secrets.token_urlsafe(32)``), atomically
  writes the descriptor file under the user's private ``~/.frago/chrome/``
  directory, and authenticates every peer on the initial framed ``hello``
  handshake via constant-time comparison.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import secrets
import shlex
import socket
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .protocol import encode_frame, read_frame_sync

ENDPOINT_VERSION = 1
LOOPBACK_HOST = "127.0.0.1"
TRANSPORT_ENV_VAR = "FRAGO_EXTENSION_TRANSPORT"

TransportMode = Literal["unix", "tcp"]
ClientConnectedCB = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


@dataclass(frozen=True)
class BridgeEndpoint:
    """Resolved runtime IPC endpoint for the extension bridge daemon."""

    transport: TransportMode
    sock_path: Path | None = None
    host: str | None = None
    port: int | None = None
    token: str | None = None
    pid: int | None = None

    def describe(self) -> str:
        """Human-readable endpoint description (never exposes auth token)."""
        if self.transport == "unix":
            return f"unix://{self.sock_path}"
        return f"tcp://{self.host}:{self.port}"


@dataclass
class BridgeServerHandle:
    """Active daemon listener handle + cleanup ownership."""

    server: asyncio.AbstractServer
    endpoint: BridgeEndpoint
    anchor: Path
    meta_path: Path

    def describe(self) -> str:
        return self.endpoint.describe()

    def close_cleanup(self) -> None:
        """Remove endpoint artifacts owned by this server instance."""
        my_pid = self.endpoint.pid
        current = read_endpoint_metadata(self.anchor)
        # Only unlink shared artifacts if they still belong to this server PID
        # (protects a newer daemon instance from being wiped during shutdown race).
        if current is not None and my_pid is not None and current.pid not in (None, my_pid):
            return
        with contextlib.suppress(OSError):
            if self.meta_path.exists():
                self.meta_path.unlink()
        if self.endpoint.transport == "unix" and self.endpoint.sock_path is not None:
            with contextlib.suppress(OSError):
                if self.endpoint.sock_path.exists():
                    self.endpoint.sock_path.unlink()


def endpoint_meta_path(anchor: Path) -> Path:
    """Companion runtime endpoint descriptor path derived from ``anchor``."""
    if anchor.suffix:
        return anchor.with_suffix(".endpoint.json")
    return anchor.parent / f"{anchor.name}.endpoint.json"


def supports_asyncio_unix_sockets() -> bool:
    """Return True iff the current OS and Python runtime support async UDS."""
    return (
        sys.platform != "win32"
        and hasattr(socket, "AF_UNIX")
        and hasattr(asyncio, "start_unix_server")
        and hasattr(asyncio, "open_unix_connection")
    )


def resolve_transport_mode() -> TransportMode:
    """Select the active bridge IPC transport mode for this runtime."""
    override = os.environ.get(TRANSPORT_ENV_VAR, "").strip().lower()
    if override == "tcp":
        return "tcp"
    if override == "unix" and supports_asyncio_unix_sockets():
        return "unix"
    return "unix" if supports_asyncio_unix_sockets() else "tcp"


def should_use_unix_socket() -> bool:
    """Return True when the bridge should listen/connect via Unix domain socket."""
    return resolve_transport_mode() == "unix"


def generate_auth_token() -> str:
    """Generate a fresh 256-bit URL-safe session token for loopback TCP auth."""
    return secrets.token_urlsafe(32)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write ``payload`` as UTF-8 JSON with owner-only POSIX mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    raw = json.dumps(payload, indent=2).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(str(tmp_path), flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
        except Exception:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        if sys.platform != "win32":
            with contextlib.suppress(OSError):
                os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            if tmp_path.exists():
                tmp_path.unlink()
        raise


def read_endpoint_metadata(anchor: Path) -> BridgeEndpoint | None:
    """Parse the companion endpoint descriptor if present and structurally valid."""
    meta_path = endpoint_meta_path(anchor)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    transport = data.get("transport")
    pid = data.get("pid")
    if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
        pid = None

    if transport == "tcp":
        host = data.get("host")
        port = data.get("port")
        token = data.get("token")
        # Strictly restrict to IPv4 loopback to prevent SSRF / hijack via tampered metadata.
        if host != LOOPBACK_HOST:
            return None
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            return None
        if not isinstance(token, str) or len(token) < 16:
            return None
        return BridgeEndpoint(
            transport="tcp",
            host=host,
            port=port,
            token=token,
            pid=pid,
        )

    if transport == "unix":
        raw_path = data.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        return BridgeEndpoint(
            transport="unix",
            sock_path=Path(raw_path),
            pid=pid,
        )

    return None


def resolve_endpoint(anchor: Path) -> BridgeEndpoint:
    """Resolve the active endpoint for ``anchor`` or raise ``FileNotFoundError``."""
    ep = read_endpoint_metadata(anchor)
    if ep is not None:
        if ep.transport == "tcp":
            return ep
        if ep.transport == "unix":
            if supports_asyncio_unix_sockets() and ep.sock_path is not None and ep.sock_path.exists():
                return ep
            raise FileNotFoundError(f"bridge unix socket unavailable: {ep.sock_path}")

    # Backward compatibility: direct UDS without companion metadata (e.g. legacy
    # daemon or unit tests calling asyncio.start_unix_server directly).
    if anchor.exists() and supports_asyncio_unix_sockets():
        return BridgeEndpoint(transport="unix", sock_path=anchor)

    raise FileNotFoundError(f"bridge endpoint not found: {anchor}")


def cleanup_bridge_endpoint(anchor: Path) -> bool:
    """Remove any socket file and/or endpoint descriptor associated with ``anchor``.

    Returns True if at least one artifact was removed.
    """
    removed = False
    for path in (anchor, endpoint_meta_path(anchor)):
        if path.exists() or path.is_symlink():
            try:
                path.unlink()
                removed = True
            except OSError:
                pass
    return removed


def is_pid_alive(pid: int) -> bool:
    """Cross-platform check for whether a process with ``pid`` is still running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong(0)
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return int(exit_code.value) == STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def read_endpoint_pid(anchor: Path) -> int | None:
    """Return the daemon PID recorded in the endpoint descriptor if alive."""
    ep = read_endpoint_metadata(anchor)
    if ep is None or ep.pid is None:
        return None
    if ep.pid == os.getpid():
        return None
    return ep.pid if is_pid_alive(ep.pid) else None


def _probe_unix_socket(sock_path: Path, timeout: float) -> bool:
    if not sock_path.exists():
        return False
    af_unix = getattr(socket, "AF_UNIX", None)
    if af_unix is None or sys.platform == "win32":
        return False
    s = socket.socket(af_unix, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_path))
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            s.close()


def _probe_tcp_endpoint(ep: BridgeEndpoint, timeout: float) -> bool:
    if ep.host != LOOPBACK_HOST or ep.port is None or not ep.token:
        return False
    try:
        with socket.create_connection((ep.host, ep.port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(encode_frame({"role": "ping", "token": ep.token}))
            with sock.makefile("rb") as stream:
                resp = read_frame_sync(stream)
            return isinstance(resp, dict) and resp.get("ok") is True
    except OSError:
        return False


def probe_bridge_endpoint(anchor: Path, timeout: float = 0.5) -> bool:
    """Return True if a live extension bridge daemon is accepting connections."""
    ep = read_endpoint_metadata(anchor)
    if ep is not None:
        if ep.transport == "tcp":
            return _probe_tcp_endpoint(ep, timeout)
        if ep.transport == "unix" and ep.sock_path is not None:
            return _probe_unix_socket(ep.sock_path, timeout)
        return False
    # Legacy fallback when only a bare unix socket file exists.
    return _probe_unix_socket(anchor, timeout)


async def start_bridge_server(
    client_connected_cb: ClientConnectedCB,
    anchor: Path,
    *,
    auth_token: str | None = None,
    mode: TransportMode | None = None,
) -> BridgeServerHandle:
    """Bind and start the extension bridge server using the resolved transport.

    Cleans up stale endpoint artifacts from previous crashed daemons before
    binding. In ``tcp`` mode, ``auth_token`` must be supplied (or generated) and
    is written to the companion descriptor file with owner-only permissions.
    """
    chosen_mode = mode or resolve_transport_mode()
    anchor.parent.mkdir(parents=True, exist_ok=True)
    meta_path = endpoint_meta_path(anchor)

    # Remove stale artifacts left by a prior crash.
    cleanup_bridge_endpoint(anchor)

    if chosen_mode == "unix":
        server = await asyncio.start_unix_server(client_connected_cb, path=str(anchor))
        with contextlib.suppress(OSError):
            os.chmod(anchor, 0o600)
        ep = BridgeEndpoint(transport="unix", sock_path=anchor, pid=os.getpid())
        _atomic_write_json(
            meta_path,
            {
                "version": ENDPOINT_VERSION,
                "transport": "unix",
                "path": str(anchor),
                "pid": os.getpid(),
            },
        )
        return BridgeServerHandle(
            server=server,
            endpoint=ep,
            anchor=anchor,
            meta_path=meta_path,
        )

    token = auth_token or generate_auth_token()
    server = await asyncio.start_server(client_connected_cb, host=LOOPBACK_HOST, port=0)
    sockets = server.sockets
    if not sockets:
        server.close()
        await server.wait_closed()
        raise OSError("failed to bind loopback TCP socket for extension daemon")
    port = int(sockets[0].getsockname()[1])
    ep = BridgeEndpoint(
        transport="tcp",
        host=LOOPBACK_HOST,
        port=port,
        token=token,
        pid=os.getpid(),
    )
    _atomic_write_json(
        meta_path,
        {
            "version": ENDPOINT_VERSION,
            "transport": "tcp",
            "host": LOOPBACK_HOST,
            "port": port,
            "token": token,
            "pid": os.getpid(),
        },
    )
    return BridgeServerHandle(
        server=server,
        endpoint=ep,
        anchor=anchor,
        meta_path=meta_path,
    )


async def open_bridge_connection(
    anchor: Path,
    *,
    role: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to the extension daemon and send the initial framed ``hello``."""
    ep = resolve_endpoint(anchor)
    if ep.transport == "unix":
        assert ep.sock_path is not None
        reader, writer = await asyncio.open_unix_connection(str(ep.sock_path))
    else:
        assert ep.host is not None and ep.port is not None
        reader, writer = await asyncio.open_connection(ep.host, ep.port)

    hello: dict[str, Any] = {"role": role}
    if ep.token:
        hello["token"] = ep.token
    writer.write(encode_frame(hello))
    await writer.drain()
    return reader, writer


def native_host_launcher_path(base_dir: Path | None = None) -> Path:
    """Return the platform-appropriate native messaging launcher script path."""
    frago_dir = base_dir or (Path.home() / ".frago" / "chrome")
    name = "native_host_launcher.cmd" if sys.platform == "win32" else "native_host_launcher.sh"
    return frago_dir / name


def ensure_native_host_launcher(base_dir: Path | None = None) -> Path:
    """Write the native-messaging launcher Chrome/CfT spawns for ``com.frago.bridge``.

    POSIX: executable bash script ``native_host_launcher.sh``.
    Windows: batch launcher ``native_host_launcher.cmd`` quoting ``sys.executable``
    so paths containing spaces (e.g. ``C:\\Program Files\\Python312\\python.exe``)
    execute cleanly under Chrome's ``CreateProcess``.
    """
    launcher = native_host_launcher_path(base_dir)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        content = (
            "@echo off\r\n"
            f'"{sys.executable}" -m frago.cli.main extension native-host %*\r\n'
        )
        with open(launcher, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    else:
        py_cmd = shlex.quote(sys.executable)
        launcher.write_text(
            "#!/usr/bin/env bash\n"
            f"exec {py_cmd} -m frago.cli.main extension native-host\n",
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            launcher.chmod(0o755)
    return launcher


def configure_stdio_binary_mode() -> None:
    """Switch stdin/stdout to binary mode on Windows for Chrome native messaging.

    Prevents Windows C-runtime text translation (``\\n`` <-> ``\\r\\n`` and
    Ctrl-Z / ``0x1A`` EOF) from corrupting the 4-byte length-prefixed framing.
    """
    if sys.platform != "win32":
        return
    try:
        import msvcrt  # type: ignore[import-not-found]
    except ImportError:
        return
    o_binary = getattr(os, "O_BINARY", 0x8000)
    for stream in (sys.stdin, sys.stdout):
        with contextlib.suppress(OSError, AttributeError, io.UnsupportedOperation):
            msvcrt.setmode(stream.fileno(), o_binary)


def detached_subprocess_kwargs() -> dict[str, Any]:
    """Return cross-platform ``subprocess.Popen`` kwargs for detached processes."""
    if sys.platform == "win32":
        from frago.compat import get_windows_subprocess_kwargs

        kwargs = get_windows_subprocess_kwargs(detach=True)
        if kwargs:
            return kwargs
        # Fallback when sys.platform is monkeypatched to win32 during tests on POSIX.
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        return {"creationflags": CREATE_NO_WINDOW | DETACHED_PROCESS}
    return {"start_new_session": True}
