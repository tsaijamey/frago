"""Unit tests for first-launch profile seeding (frago.chrome.profile_seed).

Simulates a system browser profile in a temp directory and asserts the
copy semantics both backends rely on: Local State + Default/ copied,
cache directories excluded, second call is a no-op.
"""
from pathlib import Path

from frago.chrome.profile_seed import (
    seed_profile_from_system,
    system_profile_dir,
)


def _make_system_profile(root: Path) -> Path:
    sys_profile = root / "system-profile"
    default = sys_profile / "Default"
    default.mkdir(parents=True)
    (sys_profile / "Local State").write_text('{"browser": {}}')
    (default / "Login Data").write_text("sqlite-login-data")
    (default / "Cookies").write_text("sqlite-cookies")
    (default / "Bookmarks").write_text('{"roots": {}}')
    (default / "Preferences").write_text("{}")
    # Excluded bulk/cache content
    (default / "Cache").mkdir()
    (default / "Cache" / "data_0").write_text("x" * 10)
    (default / "Code Cache").mkdir()
    (default / "Code Cache" / "js").mkdir()
    (default / "Service Worker").mkdir()
    (default / "Service Worker" / "Database").mkdir()
    (default / "LOCK").write_text("")
    (default / "debug.log").write_text("noise")
    return sys_profile


def test_first_seed_copies_login_state(tmp_path):
    sys_profile = _make_system_profile(tmp_path)
    profile = tmp_path / "extension-profile"

    assert seed_profile_from_system(profile, sys_profile) is True

    assert (profile / "Local State").exists()
    assert (profile / "Default" / "Login Data").read_text() == "sqlite-login-data"
    assert (profile / "Default" / "Cookies").exists()
    assert (profile / "Default" / "Bookmarks").exists()


def test_seed_excludes_cache_dirs_and_lock_files(tmp_path):
    sys_profile = _make_system_profile(tmp_path)
    profile = tmp_path / "extension-profile"

    seed_profile_from_system(profile, sys_profile)

    default = profile / "Default"
    assert not (default / "Cache").exists()
    assert not (default / "Code Cache").exists()
    assert not (default / "Service Worker").exists()
    assert not (default / "LOCK").exists()
    assert not (default / "debug.log").exists()


def test_second_call_skips_initialized_profile(tmp_path):
    sys_profile = _make_system_profile(tmp_path)
    profile = tmp_path / "extension-profile"

    seed_profile_from_system(profile, sys_profile)
    # Simulate the managed profile diverging after first launch
    (profile / "Default" / "Login Data").write_text("frago-side-state")
    (sys_profile / "Default" / "Login Data").write_text("newer-system-state")

    assert seed_profile_from_system(profile, sys_profile) is False
    assert (profile / "Default" / "Login Data").read_text() == "frago-side-state"


def test_existing_default_blocks_seed_even_when_empty_profile_state(tmp_path):
    # Browser-created bare Default/ (the pre-fix blank extension-profile
    # situation) must NOT be overwritten silently — reseed is explicit.
    sys_profile = _make_system_profile(tmp_path)
    profile = tmp_path / "extension-profile"
    (profile / "Default").mkdir(parents=True)

    assert seed_profile_from_system(profile, sys_profile) is False
    assert not (profile / "Default" / "Login Data").exists()


def test_no_system_profile_is_noop(tmp_path):
    profile = tmp_path / "extension-profile"
    assert seed_profile_from_system(profile, None) is False
    assert profile.exists()
    assert not (profile / "Default").exists()


def test_system_profile_dir_resolves_known_brands(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    edge_dir = fake_home / "Library" / "Application Support" / "Microsoft Edge"
    edge_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))

    assert system_profile_dir("edge", "Darwin") == edge_dir
    # Installed-but-never-run / not-installed brands resolve to None
    assert system_profile_dir("brave", "Darwin") is None
    assert system_profile_dir("unknown-brand", "Darwin") is None
