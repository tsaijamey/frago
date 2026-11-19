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

from frago.browser import cft_fetch as cf
from frago.browser.extension import lifecycle as lc


@pytest.fixture(autouse=True)
def _no_cft_download(request, monkeypatch):
    """没有 CfT 的机器上跑这些测试时，不许真去下载。"""
    if "fetch_cft" in request.node.name:
        return
    monkeypatch.setattr(lc, "_fetch_cft_if_missing", lambda: None)


def test_fetch_cft_downloads_when_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(cf, "installed_binary", lambda root=None: None)
    monkeypatch.setattr(cf, "ensure_cft", lambda **kw: calls.append(kw))
    lc._fetch_cft_if_missing()
    assert len(calls) == 1


def test_fetch_cft_failure_only_warns(monkeypatch, capsys):
    def _fail(**_kw):
        raise cf.CftFetchError("network", "下载 CfT 失败，直连：timed out")

    monkeypatch.setattr(cf, "installed_binary", lambda root=None: None)
    monkeypatch.setattr(cf, "ensure_cft", _fail)
    lc._fetch_cft_if_missing()
    assert "没取到 Chrome for Testing" in capsys.readouterr().err


def test_no_browser_raises():
    """When picker returns None, orchestration fails loud."""
    with patch.object(lc, "bundle_path", return_value=Path("/fake/bundle")), \
         patch("frago.browser.backends.extension.pick_browser_for_extension",
               return_value=None), \
         pytest.raises(RuntimeError, match="no Chromium-class browser"):
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
         patch("frago.browser.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")), \
         patch.object(lc, "_profile_locked", return_value=True), \
         pytest.raises(RuntimeError, match="locked"):
        lc.start_extension_bridge(profile_dir=profile)


def _locked_start(tmp_path, run_result, **kw):
    profile = tmp_path / "profile"
    profile.mkdir()
    with patch.object(lc, "bundle_path", return_value=tmp_path / "bundle"), \
         patch("frago.browser.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/x/Google Chrome for Testing",
                                       brand="cft")), \
         patch.object(lc, "_profile_locked", return_value=True), \
         patch.object(lc, "_read_profile_lock_pid", return_value=4242), \
         patch.object(lc, "_daemon_alive", return_value=True), \
         patch.object(lc.subprocess, "run", return_value=run_result) as run, \
         patch("frago.browser.backends.extension.launch_chrome_with_extension") as launch:
        result = lc.start_extension_bridge(profile_dir=profile, **kw)
    return result, run, launch, profile


def test_an_app_window_on_a_running_browser_is_handed_to_it(tmp_path):
    """The stage keeps this browser up, so "already running" is the ordinary
    case for opening a page for a person. The page goes to the running one —
    same binary, same profile, and Chromium passes the command line over."""
    result, run, launch, profile = _locked_start(
        tmp_path, MagicMock(returncode=0, stderr=b""),
        app_url="http://127.0.0.1:8093/")
    assert run.call_args[0][0] == [
        "/x/Google Chrome for Testing", f"--user-data-dir={profile}",
        "--app=http://127.0.0.1:8093/"]
    launch.assert_not_called()
    assert result.handed_to_running is True
    assert result.browser_pid == 4242


def test_a_failed_handoff_is_reported(tmp_path):
    with pytest.raises(RuntimeError, match="handing the app window"):
        _locked_start(tmp_path, MagicMock(returncode=21, stderr=b"in use"),
                      app_url="http://127.0.0.1:8093/")


def test_missing_bundle_manifest_raises(tmp_path):
    """Bundle dir without manifest.json → install probably broken."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()  # but no manifest.json inside
    profile = tmp_path / "profile"
    with patch("frago.browser.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")), \
         patch.object(lc, "_profile_locked", return_value=False), \
         pytest.raises(RuntimeError, match="manifest.json"):
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
         patch("frago.browser.backends.extension.launch_chrome_with_extension",
               return_value=fake_browser_proc), \
         patch.object(lc, "_wait_bridge",
                      return_value={"bridge": {"extensionId": "xyz"}}), \
         patch("frago.browser.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/microsoft-edge",
                                       brand="edge")):
        result = lc.start_extension_bridge(
            profile_dir=profile, bundle_dir=bundle)

    assert result.daemon_was_already_running is True
    assert result.daemon_pid is None
    assert result.browser_pid == 12345
    assert result.browser_brand == "edge"
    assert result.extension_id == "xyz"


def test_brand_without_binary_rejected():
    """A brand alone cannot choose the binary — it would only misdirect
    the profile, launching the picker's browser against another brand's
    user-data dir. Reject the combination instead of silently doing that.
    """
    with pytest.raises(RuntimeError, match="cannot pick the browser here"):
        lc.start_extension_bridge(browser="brave")


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
         patch("frago.browser.extension.lifecycle.SOCK_PATH", tmp_path / "no.sock"):
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
         patch("frago.browser.extension.lifecycle.SOCK_PATH", sock):
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
         patch("frago.browser.extension.lifecycle.SOCK_PATH",
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
         patch("frago.browser.extension.lifecycle.SOCK_PATH",
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


# ─────────────── preferences hardening (developer_mode & enable) ──────


def test_preferences_hardening_initializes_fresh_profile(tmp_path):
    """Missing Default/Preferences is initialized with developer_mode=True."""
    profile = tmp_path / "profile"
    lc._ensure_developer_mode_and_enable_extension(profile)
    prefs_file = profile / "Default" / "Preferences"
    assert prefs_file.exists()
    import json
    data = json.loads(prefs_file.read_text(encoding="utf-8"))
    assert data["extensions"]["ui"]["developer_mode"] is True


def test_preferences_hardening_preserves_unrelated_keys_and_enables_extension(tmp_path):
    """Existing Preferences & Secure Preferences keep unrelated keys while
    forcing developer_mode=True, clearing disable_reasons/ack locks, setting
    state=1, and syncing granted_permissions from manifest/active_permissions."""
    import json
    profile = tmp_path / "profile"
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True)

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"permissions": ["tabs", "sidePanel", "contextMenus"]}),
        encoding="utf-8",
    )

    ext_id = lc.STABLE_EXTENSION_ID
    (default_dir / "Preferences").write_text(
        json.dumps({
            "profile": {"name": "Work", "exited_cleanly": True},
            "extensions": {
                "ui": {"developer_mode": False},
                "settings": {
                    ext_id: {
                        "state": 0,
                        "disable_reasons": [1, 16777216],
                        "ack_prompt_count": 2,
                        "withholding_permissions": True,
                        "active_permissions": {
                            "api": ["tabs", "sidePanel", "contextMenus"],
                            "explicit_host": ["<all_urls>"],
                        },
                        "granted_permissions": {
                            "api": ["tabs"],
                        },
                    },
                    "otherextensionid0000000000000000": {
                        "state": 0,
                        "disable_reasons": [1],
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    (default_dir / "Secure Preferences").write_text(
        json.dumps({
            "extensions": {
                "settings": {
                    ext_id: {
                        "state": 0,
                        "disable_reasons": [16777216],
                        "ack_external": True,
                        "active_permissions": {"api": ["tabs", "sidePanel"]},
                        "granted_permissions": {"api": ["tabs"]},
                    }
                }
            }
        }),
        encoding="utf-8",
    )

    lc._ensure_developer_mode_and_enable_extension(
        profile, extension_id=ext_id, bundle_dir=bundle
    )

    prefs = json.loads((default_dir / "Preferences").read_text(encoding="utf-8"))
    assert prefs["profile"] == {"name": "Work", "exited_cleanly": True}
    assert prefs["extensions"]["ui"]["developer_mode"] is True
    entry = prefs["extensions"]["settings"][ext_id]
    assert entry["state"] == 1
    assert entry["disable_reasons"] == []
    assert "ack_prompt_count" not in entry
    assert entry["withholding_permissions"] is False
    assert set(entry["granted_permissions"]["api"]) >= {"tabs", "sidePanel", "contextMenus"}
    assert entry["granted_permissions"]["explicit_host"] == ["<all_urls>"]
    # Unrelated extension settings are untouched
    assert prefs["extensions"]["settings"]["otherextensionid0000000000000000"] == {
        "state": 0,
        "disable_reasons": [1],
    }

    sp = json.loads((default_dir / "Secure Preferences").read_text(encoding="utf-8"))
    assert sp["extensions"]["ui"]["developer_mode"] is True
    sp_entry = sp["extensions"]["settings"][ext_id]
    assert sp_entry["state"] == 1
    assert sp_entry["disable_reasons"] == []
    assert "ack_external" not in sp_entry
    assert set(sp_entry["granted_permissions"]["api"]) >= {"tabs", "sidePanel", "contextMenus"}


def test_preferences_hardening_recovers_from_malformed_json(tmp_path, capsys):
    """Corrupt Preferences JSON warns and reinitializes cleanly without crashing."""
    import json
    profile = tmp_path / "profile"
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True)
    (default_dir / "Preferences").write_text("{not valid json", encoding="utf-8")

    lc._ensure_developer_mode_and_enable_extension(profile)

    data = json.loads((default_dir / "Preferences").read_text(encoding="utf-8"))
    assert data["extensions"]["ui"]["developer_mode"] is True
    assert "failed to parse" in capsys.readouterr().err


def test_start_extension_bridge_hardens_preferences_before_launch(tmp_path):
    """start_extension_bridge hardens Preferences before calling launch_chrome_with_extension."""
    import json
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"permissions": ["tabs", "sidePanel", "contextMenus"]}),
        encoding="utf-8",
    )
    profile = tmp_path / "profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Secure Preferences").write_text(
        json.dumps({
            "extensions": {
                "settings": {
                    lc.STABLE_EXTENSION_ID: {
                        "state": 0,
                        "disable_reasons": [16777216],
                    }
                }
            }
        }),
        encoding="utf-8",
    )

    observed_before_launch: dict = {}

    def fake_launch(bundle_dir, user_data_dir, **_kw):
        observed_before_launch["prefs"] = json.loads(
            (user_data_dir / "Default" / "Preferences").read_text(encoding="utf-8")
        )
        observed_before_launch["secure"] = json.loads(
            (user_data_dir / "Default" / "Secure Preferences").read_text(encoding="utf-8")
        )
        return MagicMock(pid=7777)

    with patch.object(lc, "_daemon_alive", return_value=True), \
         patch.object(lc, "_profile_locked", return_value=False), \
         patch.object(lc, "_ensure_native_host_launcher",
                      return_value=Path("/tmp/fake-launcher.sh")), \
         patch.object(lc, "install_manifest",
                      return_value=Path("/tmp/manifest.json")), \
         patch("frago.browser.backends.extension.launch_chrome_with_extension",
               side_effect=fake_launch), \
         patch.object(lc, "_wait_bridge",
                      return_value={"bridge": {"extensionId": lc.STABLE_EXTENSION_ID}}), \
         patch("frago.browser.backends.extension.pick_browser_for_extension",
               return_value=MagicMock(path="/usr/bin/chromium", brand="chromium")):
        lc.start_extension_bridge(profile_dir=profile, bundle_dir=bundle)

    assert observed_before_launch["prefs"]["extensions"]["ui"]["developer_mode"] is True
    sp_ext = observed_before_launch["secure"]["extensions"]["settings"][lc.STABLE_EXTENSION_ID]
    assert sp_ext["state"] == 1
    assert sp_ext["disable_reasons"] == []


# ─────────────────────── CfT wrapper self-heal & prepare ──────────────


def test_fetch_cft_heals_existing_wrapper(monkeypatch):
    """When CfT is already installed, _fetch_cft_if_missing still runs ensure_cft_wrapper."""
    fake_bin = Path("/tmp/Google Chrome for Testing")
    healed: list[Path] = []
    hints: list[bool] = []
    monkeypatch.setattr(cf, "installed_binary", lambda root=None: fake_bin)
    monkeypatch.setattr(cf, "ensure_cft_wrapper", lambda b: healed.append(b) or True)
    monkeypatch.setattr(cf, "record_runtime_python_hint", lambda: hints.append(True))
    monkeypatch.setattr(cf, "ensure_cft", lambda **_kw: pytest.fail("should not re-fetch"))
    lc._fetch_cft_if_missing()
    assert healed == [fake_bin]
    assert hints == [True]


def test_prepare_cft_extension_launch_unlocked_hardens_prefs(tmp_path):
    """Unlocked profile gets daemon, manifest, and developer_mode hardening."""
    import json

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"permissions": ["tabs", "sidePanel"]}),
        encoding="utf-8",
    )
    profile = tmp_path / "profile"

    with patch.object(lc, "_daemon_alive", return_value=False), \
         patch.object(lc, "_spawn_daemon", return_value=5555) as spawn, \
         patch.object(lc, "_wait_socket") as wait_sock, \
         patch.object(lc, "_profile_locked", return_value=False), \
         patch.object(lc, "_ensure_native_host_launcher",
                      return_value=Path("/tmp/fake-launcher.sh")), \
         patch.object(lc, "install_manifest",
                      return_value=profile / "NativeMessagingHosts" / "com.frago.bridge.json"):
        info = lc.prepare_cft_extension_launch(profile_dir=profile, bundle_dir=bundle)

    spawn.assert_called_once()
    wait_sock.assert_called_once()
    assert info["profile_dir"] == str(profile)
    assert info["bundle_dir"] == str(bundle)
    assert info["daemon_was_already_running"] is False
    assert info["daemon_pid"] == 5555
    assert info["profile_locked"] is False
    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["extensions"]["ui"]["developer_mode"] is True


def test_prepare_cft_extension_launch_locked_skips_prefs_hardening(tmp_path):
    """Hot handoff while CfT is running skips Preferences mutation to avoid races."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    profile = tmp_path / "profile"

    with patch.object(lc, "_daemon_alive", return_value=True), \
         patch.object(lc, "_profile_locked", return_value=True), \
         patch.object(lc, "_ensure_native_host_launcher",
                      return_value=Path("/tmp/fake-launcher.sh")), \
         patch.object(lc, "install_manifest",
                      return_value=profile / "NativeMessagingHosts" / "com.frago.bridge.json"), \
         patch.object(lc, "_ensure_developer_mode_and_enable_extension",
                      side_effect=AssertionError("must not mutate locked prefs")):
        info = lc.prepare_cft_extension_launch(profile_dir=profile, bundle_dir=bundle)

    assert info["daemon_was_already_running"] is True
    assert info["daemon_pid"] is None
    assert info["profile_locked"] is True


# ─────────────── CfT default installation & initialization ────────────


def test_initialize_cft_environment_fresh_blank_profile(tmp_path, monkeypatch):
    """Fresh blank CfT profile gets vertical_tabs, developer_mode, launcher, and manifest."""
    import json

    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"permissions": ["tabs", "sidePanel"]}),
        encoding="utf-8",
    )

    info = lc.initialize_cft_environment(bundle_dir=bundle, ensure_daemon=False)
    profile = Path(info["profile_dir"])
    assert profile == fake_home / ".frago" / "profiles" / "cft" / "extension"
    assert info["prefs_initialized"] is True

    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["vertical_tabs"] == {
        "enabled": True,
        "enabled_first_time": True,
        "collapsed_state": False,
        "uncollapsed_width": 240,
    }
    assert prefs["extensions"]["ui"]["developer_mode"] is True

    launcher = fake_home / ".frago" / "chrome" / "native_host_launcher.sh"
    assert launcher.exists()
    manifest = json.loads(
        (profile / "NativeMessagingHosts" / "com.frago.bridge.json").read_text(encoding="utf-8")
    )
    assert manifest["path"] == str(launcher)
    assert (fake_home / ".frago" / "chrome" / "python_path").exists()


def test_initialize_cft_environment_upgrade_idempotency_preserves_custom_prefs_and_cookies(tmp_path, monkeypatch):
    """Upgrading / re-running initialization preserves cookies, custom vertical_tabs, and unrelated prefs."""
    import json

    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    profile = fake_home / ".frago" / "profiles" / "cft" / "extension"
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True)
    cookies = default_dir / "Cookies"
    cookies.write_bytes(b"SQLite-user-cookies-payload")

    # User explicitly disabled vertical tabs and customized width.
    (default_dir / "Preferences").write_text(
        json.dumps({
            "profile": {"name": "Daily"},
            "vertical_tabs": {
                "enabled": False,
                "collapsed_state": True,
                "uncollapsed_width": 320,
            },
        }),
        encoding="utf-8",
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")

    lc.initialize_cft_environment(bundle_dir=bundle, ensure_daemon=False)
    lc.initialize_cft_environment(bundle_dir=bundle, ensure_daemon=False)

    assert cookies.read_bytes() == b"SQLite-user-cookies-payload"
    prefs = json.loads((default_dir / "Preferences").read_text(encoding="utf-8"))
    assert prefs["profile"] == {"name": "Daily"}
    assert prefs["vertical_tabs"]["enabled"] is False
    assert prefs["vertical_tabs"]["collapsed_state"] is True
    assert prefs["vertical_tabs"]["uncollapsed_width"] == 320
    assert prefs["vertical_tabs"]["enabled_first_time"] is True
    assert prefs["extensions"]["ui"]["developer_mode"] is True


def test_initialize_cft_environment_seeds_missing_vertical_tabs_enabled(tmp_path):
    """Profile with vertical_tabs missing 'enabled' gets enabled=True seeded."""
    import json

    profile = tmp_path / "profile"
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True)
    (default_dir / "Preferences").write_text(
        json.dumps({
            "vertical_tabs": {
                "collapsed_state": False,
                "uncollapsed_width": 240,
            }
        }),
        encoding="utf-8",
    )

    lc.initialize_cft_environment(profile_dir=profile, ensure_daemon=False)
    prefs = json.loads((default_dir / "Preferences").read_text(encoding="utf-8"))
    assert prefs["vertical_tabs"]["enabled"] is True
    assert prefs["vertical_tabs"]["enabled_first_time"] is True
    assert prefs["vertical_tabs"]["collapsed_state"] is False
    assert prefs["vertical_tabs"]["uncollapsed_width"] == 240


def test_prepare_cft_extension_launch_seeds_vertical_tabs(tmp_path):
    """Bare .app launch also seeds vertical_tabs.enabled=True when profile is unlocked."""
    import json

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    profile = tmp_path / "profile"

    with patch.object(lc, "_daemon_alive", return_value=True), \
         patch.object(lc, "_profile_locked", return_value=False), \
         patch.object(lc, "_ensure_native_host_launcher",
                      return_value=Path("/tmp/fake-launcher.sh")), \
         patch.object(lc, "install_manifest",
                      return_value=profile / "NativeMessagingHosts" / "com.frago.bridge.json"):
        lc.prepare_cft_extension_launch(profile_dir=profile, bundle_dir=bundle)

    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["vertical_tabs"]["enabled"] is True


def test_ensure_cft_default_setup_end_to_end(tmp_path, monkeypatch):
    """ensure_cft_default_setup wraps existing CfT, initializes profile, and is idempotent."""
    import json
    import sys

    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    if sys.platform == "darwin":
        app = fake_home / ".frago" / "tools" / "chrome-for-testing" / "chrome-mac-arm64" / "Google Chrome for Testing.app"
        macos = app / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        (app / "Contents" / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<plist version="1.0"><dict>'
            '<key>CFBundleExecutable</key><string>Google Chrome for Testing</string>'
            '<key>CFBundleIdentifier</key><string>com.google.chrome.for.testing</string>'
            '<key>CFBundlePackageType</key><string>APPL</string>'
            '</dict></plist>',
            encoding="utf-8",
        )
        binary = macos / "Google Chrome for Testing"
        binary.write_text("#!/bin/sh\necho 'Google Chrome for Testing 153.0.8010.52'\n", encoding="utf-8")
        binary.chmod(0o755)
        monkeypatch.setattr(cf, "installed_binary", lambda root=None: binary)
    else:
        monkeypatch.setattr(cf, "installed_binary", lambda root=None: None)

    first = lc.ensure_cft_default_setup(fetch_if_missing=False, ensure_daemon=False)
    second = lc.ensure_cft_default_setup(fetch_if_missing=False, ensure_daemon=False)

    if sys.platform == "darwin":
        assert first["wrapper_updated"] is True
        assert second["wrapper_updated"] is False

    profile = fake_home / ".frago" / "profiles" / "cft" / "extension"
    prefs = json.loads((profile / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs["vertical_tabs"]["enabled"] is True
    assert prefs["extensions"]["ui"]["developer_mode"] is True


def test_init_command_invokes_browser_environment_initialization(tmp_path, monkeypatch):
    """frago init --skip-deps --non-interactive initializes default CfT profile."""
    from click.testing import CliRunner

    from frago.cli import init_command as ic

    called: list[bool] = []

    def _fake_setup(*, fetch_if_missing=False, ensure_daemon=False, progress=None):
        called.append(fetch_if_missing)
        return {
            "profile_dir": str(tmp_path / "cft" / "extension"),
            "wrapper_updated": False,
        }

    monkeypatch.setattr("frago.browser.extension.lifecycle.ensure_cft_default_setup", _fake_setup)
    monkeypatch.setattr(ic, "config_exists", lambda: False)
    monkeypatch.setattr(ic, "save_config", lambda _cfg: None)

    runner = CliRunner()
    result = runner.invoke(ic.init, ["--skip-deps", "--non-interactive"])
    assert result.exit_code == 0, result.output
    assert called == [False]
    assert "Browser profile initialized" in result.output


def test_browser_install_command_initializes_cft_profile(tmp_path, monkeypatch):
    """frago browser install reports initialized profile, manifest, and wrapper status."""
    import json

    from click.testing import CliRunner

    from frago.cli.browser_commands import install_cft

    fake_bin = tmp_path / "Google Chrome for Testing"
    fake_bin.write_text("#!/usr/bin/env bash\n# frago-cft-wrapper v1\n", encoding="utf-8")

    monkeypatch.setattr("frago.browser.cft_fetch.ensure_cft", lambda **_kw: fake_bin)
    monkeypatch.setattr(
        "frago.browser.extension.lifecycle.initialize_cft_environment",
        lambda **_kw: {
            "profile_dir": str(tmp_path / "profile"),
            "manifest_path": str(tmp_path / "profile" / "NativeMessagingHosts" / "com.frago.bridge.json"),
            "prefs_initialized": True,
        },
    )

    runner = CliRunner()
    result = runner.invoke(install_cft, [])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["wrapper_installed"] is True
    assert payload["prefs_initialized"] is True
    assert payload["profile_dir"].endswith("profile")
