"""default_manifest_dir / install_manifest cross-OS tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from frago.browser.extension import native_host as nh


def test_default_manifest_dir_linux_edge():
    with patch("platform.system", return_value="Linux"):
        p = nh.default_manifest_dir("edge")
    assert p.name == "NativeMessagingHosts"
    assert "microsoft-edge" in str(p)
    assert ".config" in str(p)


def test_default_manifest_dir_linux_chromium():
    with patch("platform.system", return_value="Linux"):
        p = nh.default_manifest_dir("chromium")
    assert "chromium" in str(p) and "NativeMessagingHosts" in str(p)


def test_default_manifest_dir_linux_brave():
    with patch("platform.system", return_value="Linux"):
        p = nh.default_manifest_dir("brave")
    # Brave's profile root has a multi-segment path
    assert "BraveSoftware/Brave-Browser/NativeMessagingHosts" in str(p)


def test_default_manifest_dir_macos_edge():
    with patch("platform.system", return_value="Darwin"):
        p = nh.default_manifest_dir("edge")
    s = str(p)
    assert "Library/Application Support/Microsoft Edge/NativeMessagingHosts" in s


def test_default_manifest_dir_macos_chromium():
    with patch("platform.system", return_value="Darwin"):
        p = nh.default_manifest_dir("chromium")
    assert "Library/Application Support/Chromium/NativeMessagingHosts" in str(p)


def test_default_manifest_dir_windows_returns_user_dir():
    with patch("platform.system", return_value="Windows"):
        p = nh.default_manifest_dir("edge")
    assert p.name == "NativeMessagingHosts"
    assert "edge" in str(p).lower()
    assert ".frago" in str(p)


def test_install_manifest_windows_registers_hkcu(tmp_path):
    """On Windows, install_manifest writes the manifest JSON and registers HKCU."""
    target = tmp_path / "win-nmh"
    with patch("platform.system", return_value="Windows"), patch.object(
        nh, "_register_windows_native_host"
    ) as mock_reg:
        result = nh.install_manifest(
            r"C:\Users\demo\.frago\chrome\native_host.cmd",
            extension_id="abc",
            brand="chrome",
            target_dir=target,
        )
    assert result == target / f"{nh.HOST_NAME}.json"
    assert result.exists()
    mock_reg.assert_called_once_with(result, brand="chrome")


def test_default_manifest_dir_unknown_brand_raises():
    with patch("platform.system", return_value="Linux"), pytest.raises(
        ValueError, match="unknown browser brand"
    ):
        nh.default_manifest_dir("safari")


def test_install_manifest_uses_brand_when_no_target_dir(tmp_path):
    """When target_dir omitted, install_manifest derives from brand × OS."""
    custom = tmp_path / "fake-edge" / "NativeMessagingHosts"
    with patch.object(nh, "default_manifest_dir",
                      return_value=custom) as mock_default:
        result = nh.install_manifest("/tmp/fake_launcher.sh",
                                     extension_id="abc",
                                     brand="edge")
    mock_default.assert_called_once_with("edge")
    assert result == custom / f"{nh.HOST_NAME}.json"
    assert result.exists()
    import json
    content = json.loads(result.read_text())
    assert content["name"] == nh.HOST_NAME
    assert content["path"] == "/tmp/fake_launcher.sh"
    assert content["allowed_origins"] == ["chrome-extension://abc/"]


def test_install_manifest_target_dir_wins_over_brand(tmp_path):
    """Explicit target_dir bypasses brand-based default lookup."""
    target = tmp_path / "udd" / "NativeMessagingHosts"
    with patch.object(nh, "default_manifest_dir",
                      side_effect=AssertionError("must not be called")):
        result = nh.install_manifest("/tmp/launcher.sh",
                                     target_dir=target,
                                     brand="edge")  # brand should be ignored
    assert result == target / f"{nh.HOST_NAME}.json"
    assert result.exists()


def test_chrome_manifest_dir_legacy_alias():
    """Backward-compat: chrome_manifest_dir == default_manifest_dir('chrome')."""
    with patch("platform.system", return_value="Linux"):
        legacy = nh.chrome_manifest_dir()
        new = nh.default_manifest_dir("chrome")
    assert legacy == new
