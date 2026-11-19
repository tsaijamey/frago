"""Bridge lifecycle orchestration.

One-shot ``start`` orchestration: pick browser → ensure daemon →
write manifest → launch browser → wait for bridge handshake. Used by
``frago browser start --backend extension``.

The orchestration is **idempotent**:

- Daemon: if a healthy daemon is already running, reuse it.
- Manifest: write unconditionally (small file, content-deterministic).
- Browser: launch fresh; if profile is already locked by another Chrome
  instance, fail loud pointing the caller at ``frago browser stop`` —
  unless an app window was asked for, which is handed to the running
  instance instead.
"""
from __future__ import annotations

import contextlib
import copy
import json
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import bundle_path
from .native_host import (
    SOCK_PATH,
    STABLE_EXTENSION_ID,
    install_manifest,
)


@dataclass
class BridgeStartupResult:
    """What :func:`start_extension_bridge` returns on success."""

    daemon_pid: int | None            # None when reusing a pre-existing daemon
    daemon_was_already_running: bool
    browser_pid: int
    browser_path: str
    browser_brand: str
    profile_dir: str                      # str (Path serializes oddly to JSON)
    bundle_dir: str
    manifest_path: str
    extension_id: str
    #: True when the browser was already up and only an app window was handed
    #: to it — nothing was launched, the bridge is whatever it already was.
    handed_to_running: bool = False


@dataclass
class BridgeStopResult:
    """What :func:`stop_extension_bridge` returns. Always returns successfully —
    a stop on an already-stopped bridge is not an error."""

    browser_pid: int | None            # None if no browser was found
    browser_stopped: bool                  # True if we sent a kill signal
    browser_force_killed: bool             # True if SIGTERM didn't suffice
    daemon_pid: int | None              # None if no daemon was found
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
        with contextlib.suppress(OSError):
            s.close()


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
        ExtensionBackendError,
        ExtensionChromeBackend,
    )
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            return ExtensionChromeBackend().start()
        except (ExtensionBackendError, FileNotFoundError, ConnectionError) as e:
            last_err = e
            time.sleep(0.5)
    raise TimeoutError(f"bridge did not come online: {last_err}")


def _spawn_daemon(log_path: Path | None) -> int:
    """Spawn the singleton daemon detached. Returns its PID."""
    # Stale socket from prior crash blocks bind; remove pre-launch.
    if SOCK_PATH.exists():
        with contextlib.suppress(OSError):
            SOCK_PATH.unlink()
    with contextlib.ExitStack() as stack:
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            stdio: Any = stack.enter_context(open(log_path, "wb"))
        else:
            stdio = subprocess.DEVNULL
        proc = subprocess.Popen(
            [sys.executable, "-m", "frago.cli.main", "extension", "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=stdio,
            stderr=subprocess.STDOUT,
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


def _read_profile_lock_pid(profile_dir: Path) -> int | None:
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


def _find_daemon_pid() -> int | None:
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


def _read_bundle_permissions(bundle_dir: Path | None) -> list[str] | None:
    """Read manifest ``permissions`` list from ``bundle_dir`` if available."""
    if bundle_dir is None:
        return None
    manifest_file = bundle_dir / "manifest.json"
    if not manifest_file.exists():
        return None
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    perms = manifest.get("permissions")
    if not isinstance(perms, list):
        return None
    return [p for p in perms if isinstance(p, str)]


def _harden_extension_prefs_dict(
    prefs: dict[str, Any],
    extension_id: str,
    *,
    manifest_permissions: list[str] | None = None,
) -> bool:
    """Ensure developer mode is enabled and clear any disable/escalation locks.

    Returns True when ``prefs`` was mutated in place.
    """
    changed = False

    extensions = prefs.get("extensions")
    if not isinstance(extensions, dict):
        extensions = {}
        prefs["extensions"] = extensions
        changed = True

    ui = extensions.get("ui")
    if not isinstance(ui, dict):
        ui = {}
        extensions["ui"] = ui
        changed = True
    if ui.get("developer_mode") is not True:
        ui["developer_mode"] = True
        changed = True

    settings = extensions.get("settings")
    if isinstance(settings, dict) and isinstance(settings.get(extension_id), dict):
        entry = settings[extension_id]
        if entry.get("state") != 1:
            entry["state"] = 1
            changed = True
        if entry.get("disable_reasons"):
            entry["disable_reasons"] = []
            changed = True
        for lock_key in ("ack_prompt_count", "ack_external"):
            if lock_key in entry:
                entry.pop(lock_key, None)
                changed = True
        if entry.get("withholding_permissions") is True:
            entry["withholding_permissions"] = False
            changed = True

        active_perms = entry.get("active_permissions")
        granted_perms = entry.get("granted_permissions")
        if isinstance(active_perms, dict):
            if not isinstance(granted_perms, dict):
                entry["granted_permissions"] = copy.deepcopy(active_perms)
                changed = True
            else:
                for perm_group in (
                    "api",
                    "explicit_host",
                    "manifest_permissions",
                    "scriptable_host",
                ):
                    active_list = active_perms.get(perm_group)
                    if not isinstance(active_list, list):
                        continue
                    cur_list = granted_perms.get(perm_group)
                    if not isinstance(cur_list, list):
                        granted_perms[perm_group] = list(active_list)
                        changed = True
                    else:
                        merged = list(cur_list)
                        for item in active_list:
                            if item not in merged:
                                merged.append(item)
                                changed = True
                        if merged != cur_list:
                            granted_perms[perm_group] = merged

        if manifest_permissions:
            for bucket_name in ("active_permissions", "granted_permissions"):
                bucket = entry.get(bucket_name)
                if isinstance(bucket, dict) and isinstance(bucket.get("api"), list):
                    cur_api = bucket["api"]
                    merged_api = list(cur_api)
                    for perm in manifest_permissions:
                        if perm not in merged_api:
                            merged_api.append(perm)
                            changed = True
                    if merged_api != cur_api:
                        bucket["api"] = merged_api

    return changed


DEFAULT_CFT_VERTICAL_TABS: dict[str, Any] = {
    "enabled": True,
    "enabled_first_time": True,
    "collapsed_state": False,
    "uncollapsed_width": 240,
}


def _seed_cft_vertical_tabs_dict(prefs: dict[str, Any]) -> bool:
    """Seed out-of-the-box CfT vertical tabs defaults without overwriting user choices."""
    vt = prefs.get("vertical_tabs")
    if not isinstance(vt, dict):
        prefs["vertical_tabs"] = copy.deepcopy(DEFAULT_CFT_VERTICAL_TABS)
        return True
    changed = False
    for key, default_val in DEFAULT_CFT_VERTICAL_TABS.items():
        if key not in vt:
            vt[key] = default_val
            changed = True
    return changed


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(f".{path.name}.frago-tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _ensure_developer_mode_and_enable_extension(
    profile_dir: Path,
    *,
    extension_id: str = STABLE_EXTENSION_ID,
    bundle_dir: Path | None = None,
    seed_vertical_tabs: bool = False,
) -> None:
    """Harden ``Default/Preferences`` (and ``Default/Secure Preferences`` if present)
    before launching Chromium so unpacked extension upgrades or refreshes never
    leave ``frago bridge`` disabled with "开启开发者模式即可使用此扩展程序".

    When ``seed_vertical_tabs`` is True (for Frago's managed CfT extension profile),
    also seeds ``vertical_tabs`` defaults if not explicitly set by the user.

    Must only be called while the profile is unlocked (no live browser process).
    """
    default_dir = profile_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    manifest_perms = _read_bundle_permissions(bundle_dir)

    prefs_path = default_dir / "Preferences"
    prefs_existed = prefs_path.exists()
    prefs: dict[str, Any] = {}
    if prefs_existed:
        try:
            loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prefs = loaded
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"warning: failed to parse {prefs_path}, reinitializing extension "
                f"preferences cleanly: {exc}",
                file=sys.stderr,
            )
            prefs = {}
    prefs_changed = _harden_extension_prefs_dict(
        prefs, extension_id, manifest_permissions=manifest_perms
    )
    if seed_vertical_tabs:
        prefs_changed = _seed_cft_vertical_tabs_dict(prefs) or prefs_changed
    if prefs_changed or not prefs_existed:
        _write_json_atomic(prefs_path, prefs)

    secure_prefs_path = default_dir / "Secure Preferences"
    if secure_prefs_path.exists():
        try:
            loaded_secure = json.loads(secure_prefs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"warning: failed to parse {secure_prefs_path}, skipping secure "
                f"preferences hardening: {exc}",
                file=sys.stderr,
            )
            return
        if isinstance(loaded_secure, dict) and _harden_extension_prefs_dict(
            loaded_secure, extension_id, manifest_permissions=manifest_perms
        ):
            _write_json_atomic(secure_prefs_path, loaded_secure)


def _fetch_cft_if_missing() -> None:
    """没有 CfT 就先取一份，并确保透明启动包装器处于自愈就绪状态。

    取不到只提醒不中断：挑浏览器会退回用户自己装的那些，这台机器照样能用，
    但人得知道此刻驱动的不是 frago 自带的那份、以及为什么。
    """
    from ..cft_fetch import (
        CftFetchError,
        ensure_cft,
        ensure_cft_wrapper,
        installed_binary,
        record_runtime_python_hint,
    )

    if (found := installed_binary()) is not None:
        try:
            ensure_cft_wrapper(found)
        except CftFetchError as e:
            print(f"warning: 更新 CfT 透明启动包装器失败：{e}", file=sys.stderr)
        record_runtime_python_hint()
        return
    try:
        ensure_cft(progress=lambda msg: print(f"[cft] {msg}", file=sys.stderr))
    except CftFetchError as e:
        print(f"warning: 没取到 Chrome for Testing，退回本机已装的浏览器：{e}",
              file=sys.stderr)


#: Seconds the second launch may take to hand its page over. Measured at well
#: under one; a running instance that does not answer makes Chromium wait
#: about twenty before it gives up and says the profile is in use.
HANDOFF_TIMEOUT = 30.0


def _hand_app_window_to_running(
    binary: str, brand: str, profile: Path, bundle_dir: Path | None, app_url: str,
) -> BridgeStartupResult:
    """The browser is already up on this profile: have it open the app window.

    Launching the same binary on the same profile does not start a second
    browser. Chromium finds the running one through the profile's singleton
    socket, passes the command line over, and exits — the running browser opens
    ``app_url`` as an app window. So "already running" is the ordinary case for
    anything that opens a page for a person (the agent_os stage keeps this
    browser up), not an error to report: refusing it meant every such request
    failed whenever the browser was open, which is most of the time.

    Only for ``app_url``. A plain ``start`` on a locked profile still refuses:
    what it asks for is a fresh bridge, and a second launch would not give it
    one.
    """
    try:
        done = subprocess.run(
            [binary, f"--user-data-dir={profile}", f"--app={app_url}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=HANDOFF_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"the browser already running on {profile} did not take the app "
            f"window within {HANDOFF_TIMEOUT:.0f}s — it may be hung; "
            f"`frago browser stop` and retry"
        ) from e
    if done.returncode != 0:
        tail = (done.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError(
            f"handing the app window to the browser already running on "
            f"{profile} failed (exit {done.returncode}): {tail}"
        )
    return BridgeStartupResult(
        daemon_pid=None,
        daemon_was_already_running=_daemon_alive(),
        browser_pid=_read_profile_lock_pid(profile) or 0,
        browser_path=binary,
        browser_brand=brand,
        profile_dir=str(profile),
        bundle_dir=str(bundle_dir or bundle_path()),
        manifest_path=str(profile / "NativeMessagingHosts"),
        extension_id=STABLE_EXTENSION_ID,
        handed_to_running=True,
    )


# ─────────────────────────── public API ─────────────────────────────


def start_extension_bridge(
    *,
    browser: str | None = None,
    chrome_binary: str | None = None,
    profile_dir: Path | None = None,
    bundle_dir: Path | None = None,
    daemon_log: Path | None = None,
    bridge_timeout: float = 30.0,
    socket_timeout: float = 5.0,
    reseed_profile: bool = False,
    app_url: str | None = None,
) -> BridgeStartupResult:
    """Bring up the full extension bridge — daemon, manifest, browser, handshake.

    Idempotent. Repeating with the same parameters heals partial state
    (e.g., daemon left running but browser closed).

    Args:
        browser: Brand of ``chrome_binary`` (``edge``, ``chromium``,
            ``brave``, ...), used to resolve the manifest/profile path.
            Required when ``chrome_binary`` is given, and rejected
            without it — on its own it cannot choose the binary, it
            would only misdirect the profile.
        chrome_binary: Explicit browser executable. Overrides picker.
        profile_dir: Override the profile (default: the browser's own
            system user-data directory — the real profile, no copy).
        bundle_dir: Override bundle location (default :func:`bundle_path`).
        daemon_log: Where to redirect the daemon's stdio (default
            ``~/.frago/server/extension-daemon.log``).
        bridge_timeout: Seconds to wait for the SW to connect.
        socket_timeout: Seconds to wait for the daemon socket to appear.
        reseed_profile: Obsolete (the backend drives the browser's own
            profile — there is nothing to re-seed). Ignored with a
            warning.
        app_url: Open this page as a borderless app window instead of a
            blank tab.

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
        if browser:
            raise RuntimeError(
                f"--browser {browser!r} cannot pick the browser here: the "
                f"picker decides which binary launches, so this would only "
                f"redirect the profile directory and drive the launched "
                f"browser against {browser!r}'s profile. Drop --browser and "
                f"let the picker choose (`frago browser check` lists what is "
                f"available), or pass an explicit binary together with its "
                f"brand."
            )
        from ..backends.extension import pick_browser_for_extension
        _fetch_cft_if_missing()
        choice = pick_browser_for_extension()
        if not choice:
            raise RuntimeError(
                "no Chromium-class browser supports --load-extension on this "
                "system. Let frago fetch its own Chrome for Testing, or "
                "install Edge / Chromium / Chrome Beta+ / Brave / Vivaldi. "
                "Chrome Stable is excluded — it silently rejects "
                "--load-extension since v137."
            )
        binary = choice.path
        brand = choice.brand

    # 2. Profile dir — the browser's own system profile. The extension
    # backend drives the real browser directly; no isolated copy.
    from ..backends.extension import extension_profile_dir
    profile = profile_dir or extension_profile_dir(brand)
    profile.mkdir(parents=True, exist_ok=True)
    if _profile_locked(profile) and app_url:
        return _hand_app_window_to_running(binary, brand, profile, bundle_dir, app_url)
    if _profile_locked(profile):
        raise RuntimeError(
            f"profile {profile} is locked — another browser instance is "
            f"already running on it. Run `frago browser stop` first, or "
            f"close the browser window manually."
        )
    if reseed_profile:
        # Obsolete: there is no frago-owned copy to wipe anymore, and
        # deleting the real browser profile would destroy user data.
        print("warning: --reseed-profile is obsolete — the extension "
              "backend drives the browser's own profile; flag ignored",
              file=sys.stderr)

    # 3. Bundle dir
    bundle = bundle_dir or bundle_path()
    if not (bundle / "manifest.json").exists():
        raise RuntimeError(
            f"bundle dir {bundle} has no manifest.json — frago install may "
            f"be incomplete; reinstall or pass --bundle-dir explicitly"
        )

    daemon_was_running, daemon_pid, manifest_path = _ensure_bridge_runtime_env(
        profile,
        bundle,
        daemon_log=daemon_log,
        socket_timeout=socket_timeout,
        harden_prefs=True,
        seed_vertical_tabs=(brand == "cft"),
    )

    # 6. Browser launch
    from ..backends.extension import launch_chrome_with_extension
    browser_proc = launch_chrome_with_extension(
        bundle, user_data_dir=profile, chrome_binary=binary, brand=brand,
        app_url=app_url,
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


def _ensure_bridge_runtime_env(
    profile: Path,
    bundle: Path | None,
    *,
    daemon_log: Path | None = None,
    socket_timeout: float = 5.0,
    harden_prefs: bool = True,
    seed_vertical_tabs: bool = False,
    ensure_daemon: bool = True,
) -> tuple[bool, int | None, Path]:
    """Ensure optional daemon, native host launcher, manifest, and prefs hardening."""
    daemon_was_running = _daemon_alive()
    daemon_pid: int | None = None
    if ensure_daemon and not daemon_was_running:
        if daemon_log is None:
            daemon_log = (Path.home() / ".frago" / "server" /
                          "extension-daemon.log")
        daemon_pid = _spawn_daemon(daemon_log)
        _wait_socket(SOCK_PATH, timeout=socket_timeout)

    launcher = _ensure_native_host_launcher()
    manifest_path = install_manifest(
        str(launcher),
        target_dir=profile / "NativeMessagingHosts",
    )

    if harden_prefs:
        _ensure_developer_mode_and_enable_extension(
            profile,
            extension_id=STABLE_EXTENSION_ID,
            bundle_dir=bundle,
            seed_vertical_tabs=seed_vertical_tabs,
        )

    return daemon_was_running, daemon_pid, manifest_path


def initialize_cft_environment(
    *,
    profile_dir: Path | None = None,
    bundle_dir: Path | None = None,
    daemon_log: Path | None = None,
    ensure_daemon: bool = False,
    socket_timeout: float = 5.0,
) -> dict[str, Any]:
    """Initialize Frago's managed CfT extension profile and bridge registration.

    Called during installation/initialization (``frago browser install``,
    ``frago init``, ``frago server`` startup, and ``cft_fetch.ensure_cft``) so
    freshly installed users get vertical tabs, developer mode, Native Messaging
    manifest, and launcher script out of the box without waiting for the first
    automation command.

    Idempotent and non-destructive on upgrades:
    - Skips mutating ``Default/Preferences`` if the profile is currently locked.
    - Preserves user cookies, login state, and explicit ``vertical_tabs`` settings.
    """
    from ..backends.extension import extension_profile_dir
    from ..cft_fetch import record_runtime_python_hint

    profile = profile_dir or extension_profile_dir("cft")
    profile.mkdir(parents=True, exist_ok=True)
    if profile_dir is None:
        record_runtime_python_hint()

    bundle = bundle_dir or bundle_path()
    active_bundle = bundle if (bundle / "manifest.json").exists() else None
    locked = _profile_locked(profile)
    daemon_was_running, daemon_pid, manifest_path = _ensure_bridge_runtime_env(
        profile,
        active_bundle,
        daemon_log=daemon_log,
        socket_timeout=socket_timeout,
        harden_prefs=not locked,
        seed_vertical_tabs=True,
        ensure_daemon=ensure_daemon,
    )
    return {
        "profile_dir": str(profile),
        "bundle_dir": str(bundle),
        "launcher_path": str(Path.home() / ".frago" / "chrome" / "native_host_launcher.sh"),
        "manifest_path": str(manifest_path),
        "prefs_initialized": not locked,
        "profile_locked": locked,
        "daemon_running": daemon_was_running or (daemon_pid is not None),
        "daemon_was_already_running": daemon_was_running,
        "daemon_pid": daemon_pid,
    }


def ensure_cft_default_setup(
    *,
    fetch_if_missing: bool = False,
    ensure_daemon: bool = False,
    progress=None,
) -> dict[str, Any]:
    """Ensure CfT binary wrapper (if installed or requested) and CfT profile defaults.

    Initialization order:
    1. Download/extract CfT (when ``fetch_if_missing=True``) or locate existing CfT.
    2. Install/update macOS ``.app`` transparent wrapper & ad-hoc codesign (with rollback).
    3. Initialize ``~/.frago/profiles/cft/extension`` (vertical tabs, developer mode,
       extension permissions) + ``NativeMessagingHosts/com.frago.bridge.json`` +
       ``native_host_launcher.sh`` + optional ``frago extension daemon``.
    """
    from ..cft_fetch import (
        ensure_cft,
        ensure_cft_wrapper,
        installed_binary,
        record_runtime_python_hint,
    )

    wrapper_updated = False
    binary_path: Path | None = None
    if fetch_if_missing:
        binary_path = ensure_cft(progress=progress)
        wrapper_updated = _is_cft_wrapper_present(binary_path)
    elif (found := installed_binary()) is not None:
        binary_path = found
        wrapper_updated = ensure_cft_wrapper(found)
        record_runtime_python_hint()

    env_info = initialize_cft_environment(ensure_daemon=ensure_daemon)
    return {
        **env_info,
        "binary": str(binary_path) if binary_path else None,
        "wrapper_updated": wrapper_updated,
    }


def _is_cft_wrapper_present(binary: Path) -> bool:
    from ..cft_fetch import _is_cft_wrapper

    return _is_cft_wrapper(binary)


def prepare_cft_extension_launch(
    *,
    profile_dir: Path | None = None,
    bundle_dir: Path | None = None,
    daemon_log: Path | None = None,
    socket_timeout: float = 5.0,
) -> dict[str, Any]:
    """Prepare extension bridge environment for a bare CfT app launch.

    Invoked by the macOS ``Google Chrome for Testing.app`` transparent
    launcher wrapper when the user starts CfT via Dock / Finder / Spotlight /
    ``open -a`` without explicit ``--user-data-dir=``.

    - Ensures ``frago extension daemon`` is running.
    - Writes ``NativeMessagingHosts/com.frago.bridge.json``.
    - Hardens ``Default/Preferences`` (developer mode + vertical_tabs defaults +
      extension enable) **only when the profile is unlocked** so a hot handoff
      to a running instance never races with Chromium's preference writes.
    - Resolves and returns ``profile_dir`` and the current ``bundle_dir``.
    """
    from ..backends.extension import extension_profile_dir
    from ..cft_fetch import record_runtime_python_hint

    profile = profile_dir or extension_profile_dir("cft")
    profile.mkdir(parents=True, exist_ok=True)
    if profile_dir is None:
        record_runtime_python_hint()

    bundle = bundle_dir or bundle_path()
    if not (bundle / "manifest.json").exists():
        raise RuntimeError(
            f"bundle dir {bundle} has no manifest.json — frago install may "
            f"be incomplete; reinstall or pass --bundle-dir explicitly"
        )

    locked = _profile_locked(profile)
    daemon_was_running, daemon_pid, manifest_path = _ensure_bridge_runtime_env(
        profile,
        bundle,
        daemon_log=daemon_log,
        socket_timeout=socket_timeout,
        harden_prefs=not locked,
        seed_vertical_tabs=True,
        ensure_daemon=True,
    )
    return {
        "profile_dir": str(profile),
        "bundle_dir": str(bundle),
        "manifest_path": str(manifest_path),
        "daemon_was_already_running": daemon_was_running,
        "daemon_pid": daemon_pid,
        "profile_locked": locked,
    }


def stop_extension_bridge(
    *,
    profile_dir: Path | None = None,
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
    if profile_dir is not None:
        profile = profile_dir
    else:
        # No brand context at stop time — re-run the deterministic picker
        # to land on the same system profile `start` used. Older frago
        # versions launched on frago-managed copies; keep those as
        # fallbacks so a browser started pre-upgrade can still be stopped.
        from ..backends.extension import (
            extension_profile_dir,
            pick_browser_for_extension,
        )
        legacy = [Path.home() / ".frago" / "chrome" / "extension-profile"]
        choice = pick_browser_for_extension()
        candidates = list(legacy)
        if choice:
            legacy_shared = (Path.home() / ".frago" / "profiles" /
                             choice.brand / "9222")
            candidates = [extension_profile_dir(choice.brand),
                          legacy_shared, *legacy]
        profile = next(
            (p for p in candidates if _read_profile_lock_pid(p) is not None),
            candidates[0],
        )

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
