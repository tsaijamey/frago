"""start_extension_bridge orchestration tests.

Most paths in lifecycle.py spawn real OS processes (daemon, browser),
which is integration territory. These tests focus on the **decision
logic**: which branch is taken when, how errors propagate, idempotency
of the daemon-detection step.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.chrome.extension import lifecycle as lc


def test_no_browser_raises():
    """When picker returns None, orchestration fails loud."""
    with patch.object(lc, "bundle_path", return_value=Path("/fake/bundle")), \
         patch("frago.chrome.backends.extension.pick_browser_for_extension",
               return_value=None):
        with pytest.raises(RuntimeError, match="no Chromium-class browser"):
            lc.start_extension_bridge()


def test_chrome_binary_without_brand_raises():
    """Caller passing a binary must also pass the brand for manifest path."""
    with pytest.raises(RuntimeError, match="without --browser brand"):
        lc.start_extension_bridge(chrome_binary="/usr/local/bin/edge-custom")


def test_profile_lock_blocks_start(tmp_path):
    """If profile dir has a live SingletonLock, fail loud pointing at stop."""
    profile = tmp_path / "profile"
    profile.mkdir()
    with patch.object(lc, "bundle_path", return_value=tmp_path / "bundle"), \
         patch("frago.chrome.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")), \
         patch.object(lc, "_profile_locked", return_value=True):
        with pytest.raises(RuntimeError, match="locked"):
            lc.start_extension_bridge(profile_dir=profile)


def test_missing_bundle_manifest_raises(tmp_path):
    """Bundle dir without manifest.json → install probably broken."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()  # but no manifest.json inside
    profile = tmp_path / "profile"
    with patch("frago.chrome.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")), \
         patch.object(lc, "_profile_locked", return_value=False):
        with pytest.raises(RuntimeError, match="manifest.json"):
            lc.start_extension_bridge(profile_dir=profile, bundle_dir=bundle)


def test_idempotent_daemon_reuse(tmp_path):
    """When daemon is already alive, skip spawn and pass daemon_pid=None."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}")
    profile = tmp_path / "profile"

    fake_browser_proc = MagicMock(pid=12345)

    with patch.object(lc, "_daemon_alive", return_value=True), \
         patch.object(lc, "_spawn_daemon",
                      side_effect=AssertionError("must not spawn")), \
         patch.object(lc, "_profile_locked", return_value=False), \
         patch.object(lc, "_ensure_native_host_launcher",
                      return_value=Path("/tmp/fake-launcher.sh")), \
         patch.object(lc, "install_manifest",
                      return_value=Path("/tmp/manifest.json")), \
         patch("frago.chrome.backends.extension.launch_chrome_with_extension",
               return_value=fake_browser_proc), \
         patch.object(lc, "_wait_bridge",
                      return_value={"bridge": {"extensionId": "xyz"}}), \
         patch("frago.chrome.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")):
        result = lc.start_extension_bridge(
            profile_dir=profile, bundle_dir=bundle)

    assert result.daemon_was_already_running is True
    assert result.daemon_pid is None
    assert result.browser_pid == 12345
    assert result.browser_brand == "edge"
    assert result.extension_id == "xyz"


def test_brand_override_wins_over_picker(tmp_path):
    """Caller's --browser brand overrides what picker would have chosen."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}")
    profile = tmp_path / "profile"
    fake_browser_proc = MagicMock(pid=999)

    with patch.object(lc, "_daemon_alive", return_value=True), \
         patch.object(lc, "_profile_locked", return_value=False), \
         patch.object(lc, "_ensure_native_host_launcher",
                      return_value=Path("/tmp/launcher.sh")), \
         patch.object(lc, "install_manifest",
                      return_value=Path("/tmp/m.json")), \
         patch("frago.chrome.backends.extension.launch_chrome_with_extension",
               return_value=fake_browser_proc), \
         patch.object(lc, "_wait_bridge",
                      return_value={"bridge": {"extensionId": "xyz"}}), \
         patch("frago.chrome.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")):
        result = lc.start_extension_bridge(
            browser="brave", profile_dir=profile, bundle_dir=bundle,
        )
    # Picker still ran (returned edge), but caller's brand override stuck.
    assert result.browser_brand == "brave"


def test_profile_locked_helper_with_no_lock(tmp_path):
    """SingletonLock absent → _profile_locked returns False."""
    profile = tmp_path / "profile"
    profile.mkdir()
    assert lc._profile_locked(profile) is False


def test_daemon_alive_helper_no_socket(tmp_path):
    """Missing socket file → _daemon_alive returns False without raising."""
    fake_sock = tmp_path / "no-such-socket.sock"
    assert lc._daemon_alive(fake_sock) is False


# ─────────────────────── stop_extension_bridge ───────────────────────


def test_stop_when_nothing_running(tmp_path):
    """Stopping an empty bridge is a no-op success — fields reflect 'nothing found'."""
    profile = tmp_path / "profile"
    profile.mkdir()
    with patch.object(lc, "_find_daemon_pid", return_value=None), \
         patch("frago.chrome.extension.lifecycle.SOCK_PATH", tmp_path / "no.sock"):
        result = lc.stop_extension_bridge(profile_dir=profile)
    assert result.browser_pid is None
    assert result.browser_stopped is False
    assert result.daemon_pid is None
    assert result.daemon_stopped is False
    assert result.socket_removed is False


def test_stop_kills_browser_and_daemon(tmp_path):
    """Full happy path: lock pid + daemon pid → both signaled."""
    profile = tmp_path / "profile"
    profile.mkdir()
    sock = tmp_path / "ext.sock"
    sock.write_text("")  # ensure socket-removal path runs

    kills: list[int] = []
    def fake_kill_with_grace(pid, timeout=10.0):
        kills.append(pid)
        return (True, False)

    with patch.object(lc, "_read_profile_lock_pid", return_value=4321), \
         patch.object(lc, "_find_daemon_pid", return_value=1234), \
         patch.object(lc, "_kill_with_grace", side_effect=fake_kill_with_grace), \
         patch("frago.chrome.extension.lifecycle.SOCK_PATH", sock):
        result = lc.stop_extension_bridge(profile_dir=profile)
    assert kills == [4321, 1234]
    assert result.browser_pid == 4321
    assert result.browser_stopped is True
    assert result.daemon_pid == 1234
    assert result.daemon_stopped is True
    assert result.socket_removed is True
    assert not sock.exists()


def test_stop_cleans_singleton_lock(tmp_path):
    """SingletonLock + variants are wiped after stop, even on graceful exit."""
    profile = tmp_path / "profile"
    profile.mkdir()
    # Create lingering Singleton* artifacts
    (profile / "SingletonLock").symlink_to("host-99999")
    (profile / "SingletonCookie").symlink_to("anything")
    (profile / "SingletonSocket").symlink_to("anything-else")

    with patch.object(lc, "_read_profile_lock_pid", return_value=99999), \
         patch.object(lc, "_kill_with_grace", return_value=(True, False)), \
         patch.object(lc, "_find_daemon_pid", return_value=None), \
         patch("frago.chrome.extension.lifecycle.SOCK_PATH",
               tmp_path / "no-sock"):
        lc.stop_extension_bridge(profile_dir=profile)
    assert not (profile / "SingletonLock").exists()
    assert not (profile / "SingletonLock").is_symlink()
    assert not (profile / "SingletonCookie").is_symlink()
    assert not (profile / "SingletonSocket").is_symlink()


def test_stop_then_start_cycle_unblocks_lock(tmp_path):
    """After stop wipes lock, _profile_locked sees clean profile again."""
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("host-99999")

    # Stop simulates browser exit + lock cleanup
    with patch.object(lc, "_read_profile_lock_pid", return_value=99999), \
         patch.object(lc, "_kill_with_grace", return_value=(True, False)), \
         patch.object(lc, "_find_daemon_pid", return_value=None), \
         patch("frago.chrome.extension.lifecycle.SOCK_PATH",
               tmp_path / "no-sock"):
        lc.stop_extension_bridge(profile_dir=profile)

    # _profile_locked must now report False so a fresh start succeeds
    assert lc._profile_locked(profile) is False


def test_profile_locked_treats_dead_pid_as_stale():
    """Stale lock (pid dead) is NOT considered locked."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp)
        # Pick a PID that's overwhelmingly likely to be dead.
        (profile / "SingletonLock").symlink_to("host-2147483647")
        assert lc._profile_locked(profile) is False
