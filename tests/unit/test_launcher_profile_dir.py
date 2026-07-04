"""Tests for ChromeLauncher profile directory derivation and legacy migration.

HOME is isolated via the ``mock_home`` fixture (monkeypatches ``Path.home``
to a tmp dir), so no test ever touches the real ~/.frago.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.chrome.cdp.launcher import ChromeLauncher


@pytest.fixture
def isolated_launcher(mock_home):
    """Patch browser resolution so ChromeLauncher() never probes the system.

    ``_resolve_browser`` would otherwise call ``find_browser`` /
    ``get_default_browser`` (which search the real filesystem for a browser
    binary). We stub it to return a fake BrowserType + path, leaving the
    profile-dir derivation logic under test untouched.

    ``NEW_PROFILE_ROOT`` / ``_MIGRATE_LOCK`` are module-level constants bound
    at import time (when ``Path.home()`` was still the real home), so they are
    re-pointed at the isolated home here to keep tests off the real ~/.frago.
    """
    import frago.chrome.cdp.launcher as launcher_mod
    from frago.chrome.cdp.browser_detection import BrowserType

    def _fake_resolve(browser):
        # Mirror the browser→BrowserType mapping; default to chrome.
        bt = BrowserType(browser) if browser else BrowserType.CHROME
        return bt, f"/fake/{bt.value}"

    isolated_root = Path.home() / ".frago" / "profiles"
    with (
        patch.object(ChromeLauncher, "_resolve_browser", side_effect=_fake_resolve),
        patch.object(launcher_mod, "NEW_PROFILE_ROOT", isolated_root),
        patch.object(launcher_mod, "_MIGRATE_LOCK", isolated_root / ".migrate.lock"),
        patch.object(ChromeLauncher, "_port_in_use", return_value=False),
    ):
        yield mock_home


def _migrate(launcher: ChromeLauncher) -> None:
    """Run the migration step the way launch() does (after killing old procs)."""
    launcher._migrate_legacy_profile(
        launcher.browser_type, launcher.debugging_port, launcher.profile_dir
    )


@pytest.mark.usefixtures("isolated_launcher")
def test_default_port_explicit_9222():
    """Default port 9222 is always explicit in the path (no suffix-free name)."""
    launcher = ChromeLauncher(port=9222, browser="chrome")
    assert launcher.profile_dir == Path.home() / ".frago" / "profiles" / "chrome" / "9222"


@pytest.mark.usefixtures("isolated_launcher")
def test_non_default_port_in_path():
    """Non-default ports get their own directory under profiles/<browser>/."""
    launcher = ChromeLauncher(port=9333, browser="chrome")
    assert launcher.profile_dir == Path.home() / ".frago" / "profiles" / "chrome" / "9333"


@pytest.mark.usefixtures("isolated_launcher")
def test_browser_segments_path():
    """Browser type segments the path; edge gets profiles/edge/<port>."""
    launcher = ChromeLauncher(port=9222, browser="edge")
    assert launcher.profile_dir == Path.home() / ".frago" / "profiles" / "edge" / "9222"


@pytest.mark.usefixtures("isolated_launcher")
def test_profile_dir_override_bypasses_layout(tmp_path):
    """An explicit --profile-dir bypasses the nested layout entirely."""
    custom = tmp_path / "my-custom-profile"
    launcher = ChromeLauncher(port=9222, browser="chrome", profile_dir=custom)
    assert launcher.profile_dir == custom
    assert launcher._default_layout is False


@pytest.mark.usefixtures("isolated_launcher")
def test_constructor_never_migrates():
    """Constructing a launcher (stop/status paths) must not move a legacy
    profile — a live browser may still be writing to it."""
    frago = Path.home() / ".frago"
    legacy = frago / "chrome_profile"
    legacy.mkdir(parents=True)
    (legacy / "Default").mkdir()

    ChromeLauncher(port=9222, browser="chrome")

    assert legacy.exists()
    assert not (frago / "profiles" / "chrome" / "9222").exists()


@pytest.mark.usefixtures("isolated_launcher")
def test_legacy_default_port_migrated(capsys):
    """Legacy suffix-free chrome_profile (default port) is moved to profiles/chrome/9222."""
    frago = Path.home() / ".frago"
    legacy = frago / "chrome_profile"
    legacy.mkdir(parents=True)
    (legacy / "Default").mkdir()
    (legacy / "Default" / "Cookies").write_text("session-data")

    launcher = ChromeLauncher(port=9222, browser="chrome")
    _migrate(launcher)

    new_dir = frago / "profiles" / "chrome" / "9222"
    assert launcher.profile_dir == new_dir
    assert new_dir.exists()
    assert (new_dir / "Default" / "Cookies").read_text() == "session-data"
    assert not legacy.exists()  # moved, not copied
    assert "migrated legacy profile" in capsys.readouterr().out


@pytest.mark.usefixtures("isolated_launcher")
def test_legacy_non_default_port_migrated():
    """Legacy chrome_profile_9333 is moved to profiles/chrome/9333."""
    frago = Path.home() / ".frago"
    legacy = frago / "chrome_profile_9333"
    legacy.mkdir(parents=True)
    (legacy / "Default").mkdir()

    launcher = ChromeLauncher(port=9333, browser="chrome")
    _migrate(launcher)

    new_dir = frago / "profiles" / "chrome" / "9333"
    assert launcher.profile_dir == new_dir
    assert new_dir.exists()
    assert not legacy.exists()


@pytest.mark.usefixtures("isolated_launcher")
def test_already_migrated_skips(capsys):
    """When the new layout already exists, no migration runs (no print, no move)."""
    frago = Path.home() / ".frago"
    new_dir = frago / "profiles" / "chrome" / "9222"
    (new_dir / "Default").mkdir(parents=True)
    (new_dir / "Default" / "Cookies").write_text("migrated-data")

    # Legacy also present, but should be left alone since new already exists.
    legacy = frago / "chrome_profile"
    legacy.mkdir()
    (legacy / "Default").mkdir()

    launcher = ChromeLauncher(port=9222, browser="chrome")
    _migrate(launcher)

    assert launcher.profile_dir == new_dir
    assert legacy.exists()  # untouched
    assert "migrated legacy profile" not in capsys.readouterr().out


@pytest.mark.usefixtures("isolated_launcher")
def test_no_legacy_no_migration(capsys):
    """Fresh install (no legacy dir) just derives the new layout, no migration print."""
    launcher = ChromeLauncher(port=9222, browser="chrome")
    _migrate(launcher)
    assert launcher.profile_dir == Path.home() / ".frago" / "profiles" / "chrome" / "9222"
    assert "migrated legacy profile" not in capsys.readouterr().out


@pytest.mark.usefixtures("isolated_launcher")
def test_port_in_use_skips_migration(capsys):
    """A live listener on the CDP port blocks migration — the legacy dir may
    still be open in a running browser."""
    frago = Path.home() / ".frago"
    legacy = frago / "chrome_profile"
    legacy.mkdir(parents=True)
    (legacy / "Default").mkdir()

    launcher = ChromeLauncher(port=9222, browser="chrome")
    # The fixture stubs _port_in_use to False; flip it to simulate a live
    # browser still listening on the CDP port.
    with patch.object(ChromeLauncher, "_port_in_use", return_value=True):
        _migrate(launcher)

    assert legacy.exists()  # untouched
    assert not launcher.profile_dir.exists()
    assert "skipping profile migration" in capsys.readouterr().out


@pytest.mark.skipif(
    not hasattr(__import__("os"), "fork"), reason="fcntl lock test is Unix-only"
)
@pytest.mark.usefixtures("isolated_launcher")
def test_lock_contention_raises():
    """A held migration lock makes the second migrator bail with RuntimeError."""
    import fcntl

    import frago.chrome.cdp.launcher as launcher_mod

    frago = Path.home() / ".frago"
    legacy = frago / "chrome_profile"
    legacy.mkdir(parents=True)
    (legacy / "Default").mkdir()

    launcher = ChromeLauncher(port=9222, browser="chrome")
    lock_path = launcher_mod._MIGRATE_LOCK
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="migrating the browser profile"):
            _migrate(launcher)

    # Legacy dir untouched; retry after release succeeds.
    assert legacy.exists()
    _migrate(launcher)
    assert not legacy.exists()
    assert launcher.profile_dir.exists()


@pytest.mark.usefixtures("isolated_launcher")
def test_empty_target_dir_does_not_block_migration(capsys):
    """A leftover empty target dir (stray mkdir) is not "already migrated" —
    it is removed and the legacy profile still moves in."""
    frago = Path.home() / ".frago"
    legacy = frago / "chrome_profile"
    legacy.mkdir(parents=True)
    (legacy / "Default").mkdir()

    new_dir = frago / "profiles" / "chrome" / "9222"
    (new_dir / "Default").mkdir(parents=True)  # leftover tree with no files

    launcher = ChromeLauncher(port=9222, browser="chrome")
    _migrate(launcher)

    assert (new_dir / "Default").exists()
    assert not legacy.exists()
    assert "migrated legacy profile" in capsys.readouterr().out
