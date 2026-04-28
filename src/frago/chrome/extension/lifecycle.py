"""Bridge lifecycle orchestration.

One-shot ``start`` orchestration: pick browser → ensure daemon →
write manifest → launch browser → wait for bridge handshake. Used by
``frago chrome start --backend extension``.

The orchestration is **idempotent**:

- Daemon: if a healthy daemon is already running, reuse it.
- Manifest: write unconditionally (small file, content-deterministic).
- Browser: launch fresh; if profile is already locked by another Chrome
  instance, fail loud pointing the caller at ``frago chrome stop``.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import bundle_path
from .native_host import (
    SOCK_PATH, STABLE_EXTENSION_ID, install_manifest,
)


@dataclass
class BridgeStartupResult:
    """What :func:`start_extension_bridge` returns on success."""

    daemon_pid: Optional[int]            # None when reusing a pre-existing daemon
    daemon_was_already_running: bool
    browser_pid: int
    browser_path: str
    browser_brand: str
    profile_dir: str                      # str (Path serializes oddly to JSON)
    bundle_dir: str
    manifest_path: str
    extension_id: str


@dataclass
class BridgeStopResult:
    """What :func:`stop_extension_bridge` returns. Always returns successfully —
    a stop on an already-stopped bridge is not an error."""

    browser_pid: Optional[int]            # None if no browser was found
    browser_stopped: bool                  # True if we sent a kill signal
    browser_force_killed: bool             # True if SIGTERM didn't suffice
    daemon_pid: Optional[int]              # None if no daemon was found
    daemon_stopped: bool
    socket_removed: bool
    profile_dir: str


# ─────────────────────── helpers (private) ──────────────────────────


def _daemon_alive(sock_path: Path = SOCK_PATH) -> bool:
    """Return True if a daemon is listening and accepting connections."""
    if not sock_path.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(str(sock_path))
        return True
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return False
    finally:
        try: s.close()
        except OSError: pass


def _wait_socket(sock_path: Path, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sock_path.exists():
            return
        time.sleep(0.1)
    raise TimeoutError(f"daemon socket {sock_path} not created in {timeout}s")


def _wait_bridge(timeout: float) -> dict:
    """Poll system.info until the extension peer is connected."""
    # Lazy import — backend imports DaemonClient which imports protocol; the
    # orchestration module shouldn't pull them eagerly.
    from ..backends.extension import (
        ExtensionBackendError, ExtensionChromeBackend,
    )
    deadline = time.time() + timeout
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        try:
            return ExtensionChromeBackend().start()
        except (ExtensionBackendError, FileNotFoundError, ConnectionError) as e:
            last_err = e
            time.sleep(0.5)
    raise TimeoutError(f"bridge did not come online: {last_err}")


def _spawn_daemon(log_path: Optional[Path]) -> int:
    """Spawn the singleton daemon detached. Returns its PID."""
    # Stale socket from prior crash blocks bind; remove pre-launch.
    if SOCK_PATH.exists():
        try: SOCK_PATH.unlink()
        except OSError: pass
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stdio = open(log_path, "wb")
    else:
        stdio = subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, "-m", "frago.cli.main", "extension", "daemon"],
        stdout=stdio, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc.pid


def _ensure_native_host_launcher() -> Path:
    """Write the launcher Chrome will exec for native messaging.

    On Linux/macOS this is a tiny shell script. Windows uses a .bat
    plus registry — see D2 task.
    """
    frago_dir = Path.home() / ".frago" / "chrome"
    frago_dir.mkdir(parents=True, exist_ok=True)
    launcher = frago_dir / "native_host_launcher.sh"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        f"exec {sys.executable} -m frago.cli.main extension native-host\n"
    )
    launcher.chmod(0o755)
    return launcher


def _read_profile_lock_pid(profile_dir: Path) -> Optional[int]:
    """Return PID of the browser holding this profile, or None.

    Chromium writes ``SingletonLock`` as a symlink whose target name is
    ``<hostname>-<pid>``. We don't verify host (assume single-host) and
    just extract the pid.
    """
    lock = profile_dir / "SingletonLock"
    if not lock.is_symlink() and not lock.exists():
        return None
    try:
        target_name = lock.resolve(strict=False).name
        return int(target_name.rsplit("-", 1)[-1])
    except (OSError, ValueError):
        return None


def _find_daemon_pid() -> Optional[int]:
    """Locate the singleton extension daemon by cmdline scan.

    Uses pgrep on Linux/macOS. Returns the first PID found. Multiple
    daemons would be a bug elsewhere — daemon refuses second extension
    connection but doesn't refuse second daemon process binding the
    same socket; in practice the second one fails at bind time anyway.
    """
    try:
        proc = subprocess.run(
            ["pgrep", "-f", "frago.cli.main extension daemon"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        # pgrep not installed (rare). Fall back: no daemon detection.
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # Pick the first pid that isn't us (rare, but defensive).
    import os as _os
    self_pid = _os.getpid()
    for line in proc.stdout.strip().splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid != self_pid:
            return pid
    return None


def _kill_with_grace(pid: int, timeout: float = 10.0) -> tuple[bool, bool]:
    """SIGTERM, wait, SIGKILL. Returns (stopped, force_killed)."""
    import os as _os
    import signal as _sig
    try:
        _os.kill(pid, _sig.SIGTERM)
    except ProcessLookupError:
        return (True, False)  # already gone
    except PermissionError:
        return (False, False)  # not ours to kill
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _os.kill(pid, 0)
        except ProcessLookupError:
            return (True, False)
        time.sleep(0.1)
    # Still alive — escalate
    try:
        _os.kill(pid, _sig.SIGKILL)
        return (True, True)
    except ProcessLookupError:
        return (True, True)


def _profile_locked(profile_dir: Path) -> bool:
    """Detect if a Chrome instance currently holds this profile.

    Three states:
      - no lock file → not locked
      - lock pid is alive → locked (we mustn't race)
      - lock pid is dead (stale lock) → not locked (Chrome itself
        overwrites stale locks on next start; we mirror that semantics)
    """
    lock = profile_dir / "SingletonLock"
    if not lock.exists() and not lock.is_symlink():
        return False
    pid = _read_profile_lock_pid(profile_dir)
    if pid is None:
        return True  # lock present but unparseable — defensive
    import os
    try:
        os.kill(pid, 0)
        return True  # pid alive → really locked
    except ProcessLookupError:
        return False  # stale lock from a crashed/killed prior browser
    except PermissionError:
        return True  # pid exists, owned by another user → racing is unsafe
    except OSError:
        return False


# ─────────────────────────── public API ─────────────────────────────


def start_extension_bridge(
    *,
    browser: Optional[str] = None,
    chrome_binary: Optional[str] = None,
    profile_dir: Optional[Path] = None,
    bundle_dir: Optional[Path] = None,
    daemon_log: Optional[Path] = None,
    bridge_timeout: float = 30.0,
    socket_timeout: float = 5.0,
) -> BridgeStartupResult:
    """Bring up the full extension bridge — daemon, manifest, browser, handshake.

    Idempotent. Repeating with the same parameters heals partial state
    (e.g., daemon left running but browser closed).

    Args:
        browser: Brand override (``edge``, ``chromium``, ``brave``, ...).
            Required when ``chrome_binary`` is given. Otherwise the
            picker chooses and reports.
        chrome_binary: Explicit browser executable. Overrides picker.
        profile_dir: Override frago-managed profile (default
            ``~/.frago/chrome/extension-profile``).
        bundle_dir: Override bundle location (default :func:`bundle_path`).
        daemon_log: Where to redirect the daemon's stdio (default
            ``~/.frago/server/extension-daemon.log``).
        bridge_timeout: Seconds to wait for the SW to connect.
        socket_timeout: Seconds to wait for the daemon socket to appear.

    Returns:
        :class:`BridgeStartupResult` with everything the caller might
        want to log or display.

    Raises:
        RuntimeError: no compatible browser found / profile locked /
            bridge timed out.
    """
    # 1. Browser selection
    if chrome_binary:
        if not browser:
            raise RuntimeError(
                "chrome_binary specified without --browser brand; pass "
                "--browser <brand> so the manifest path resolves correctly"
            )
        binary = chrome_binary
        brand = browser
    else:
        from ..backends.extension import pick_browser_for_extension
        choice = pick_browser_for_extension()
        if not choice:
            raise RuntimeError(
                "no Chromium-class browser supports --load-extension on this "
                "system. Install Edge / Chromium / Chrome Beta+ / Brave / "
                "Vivaldi. Chrome Stable is excluded — it silently rejects "
                "--load-extension since v137."
            )
        binary = choice.path
        brand = browser or choice.brand

    # 2. Profile dir
    profile = profile_dir or (Path.home() / ".frago" / "chrome" /
                              "extension-profile")
    profile.mkdir(parents=True, exist_ok=True)
    if _profile_locked(profile):
        raise RuntimeError(
            f"profile {profile} is locked — another browser instance is "
            f"already running on it. Run `frago chrome stop --backend "
            f"extension` first, or close the browser window manually."
        )

    # 3. Bundle dir
    bundle = bundle_dir or bundle_path()
    if not (bundle / "manifest.json").exists():
        raise RuntimeError(
            f"bundle dir {bundle} has no manifest.json — frago install may "
            f"be incomplete; reinstall or pass --bundle-dir explicitly"
        )

    # 4. Daemon
    daemon_was_running = _daemon_alive()
    daemon_pid: Optional[int]
    if daemon_was_running:
        daemon_pid = None
    else:
        if daemon_log is None:
            daemon_log = (Path.home() / ".frago" / "server" /
                          "extension-daemon.log")
        daemon_pid = _spawn_daemon(daemon_log)
        _wait_socket(SOCK_PATH, timeout=socket_timeout)

    # 5. Native messaging manifest at <profile>/NativeMessagingHosts/
    launcher = _ensure_native_host_launcher()
    manifest_path = install_manifest(
        str(launcher),
        target_dir=profile / "NativeMessagingHosts",
    )

    # 6. Browser launch
    from ..backends.extension import launch_chrome_with_extension
    browser_proc = launch_chrome_with_extension(
        bundle, user_data_dir=profile, chrome_binary=binary,
    )

    # 7. Bridge handshake
    info = _wait_bridge(bridge_timeout)
    extension_id = (info.get("bridge", {}) or {}).get(
        "extensionId", STABLE_EXTENSION_ID)

    return BridgeStartupResult(
        daemon_pid=daemon_pid,
        daemon_was_already_running=daemon_was_running,
        browser_pid=browser_proc.pid,
        browser_path=binary,
        browser_brand=brand,
        profile_dir=str(profile),
        bundle_dir=str(bundle),
        manifest_path=str(manifest_path),
        extension_id=extension_id,
    )


def stop_extension_bridge(
    *,
    profile_dir: Optional[Path] = None,
    timeout: float = 10.0,
) -> BridgeStopResult:
    """Tear down the extension bridge.

    Stops the browser holding the frago-managed profile, the singleton
    daemon, and removes the daemon socket. Manifest files in
    ``<profile>/NativeMessagingHosts/`` are left in place — they're
    inert without a running daemon and useful on next start.

    Idempotent: stopping an already-stopped bridge is not an error;
    fields in the result reflect what was found.
    """
    profile = profile_dir or (Path.home() / ".frago" / "chrome" /
                              "extension-profile")

    # 1. Browser
    browser_pid = _read_profile_lock_pid(profile)
    browser_stopped = False
    browser_force_killed = False
    if browser_pid is not None:
        browser_stopped, browser_force_killed = _kill_with_grace(
            browser_pid, timeout=timeout)
        # Always wipe Singleton{Lock,Cookie,Socket}. In theory Chromium
        # cleans them on graceful exit, but in practice they sometimes
        # linger (child cleanup races, SIGKILL paths, etc.). Removing
        # them is safe since we just stopped whatever was using them,
        # and lets the next `start` pass the lock check immediately.
        for fname in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            f = profile / fname
            try:
                if f.exists() or f.is_symlink():
                    f.unlink()
            except OSError:
                pass

    # 2. Daemon
    daemon_pid = _find_daemon_pid()
    daemon_stopped = False
    if daemon_pid is not None:
        stopped, _force = _kill_with_grace(daemon_pid, timeout=timeout)
        daemon_stopped = stopped

    # 3. Socket cleanup
    socket_removed = False
    if SOCK_PATH.exists():
        try:
            SOCK_PATH.unlink()
            socket_removed = True
        except OSError:
            pass

    return BridgeStopResult(
        browser_pid=browser_pid,
        browser_stopped=browser_stopped,
        browser_force_killed=browser_force_killed,
        daemon_pid=daemon_pid,
        daemon_stopped=daemon_stopped,
        socket_removed=socket_removed,
        profile_dir=str(profile),
    )
