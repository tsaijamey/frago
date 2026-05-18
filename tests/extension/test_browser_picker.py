"""pick_browser_for_extension / list_browsers_for_extension unit tests.

These mock out filesystem and shutil.which so behavior is deterministic
across CI environments without depending on which browsers are actually
installed.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from frago.chrome.backends.extension import (
    BrowserChoice,
    list_browsers_for_extension,
    pick_browser_for_extension,
)


def test_picker_prefers_edge_over_chromium_when_both_present():
    """Edge ranks above chromium even when both binaries exist on disk."""
    def fake_exists(p):
        return str(p) in {"/usr/bin/microsoft-edge", "/usr/bin/chromium"}

    with patch("frago.chrome.backends.extension._platform.system",
               return_value="Linux"), \
         patch("pathlib.Path.exists", autospec=True,
               side_effect=lambda self: fake_exists(self)):
        result = pick_browser_for_extension()
    assert result == BrowserChoice("/usr/bin/microsoft-edge", "edge")


def test_picker_returns_none_when_nothing_installed():
    with patch("frago.chrome.backends.extension._platform.system",
               return_value="Linux"), \
         patch("pathlib.Path.exists", autospec=True,
               side_effect=lambda self: False), \
         patch("frago.chrome.backends.extension.shutil.which",
               return_value=None):
        assert pick_browser_for_extension() is None


def test_picker_falls_back_to_path_lookup():
    with patch("frago.chrome.backends.extension._platform.system",
               return_value="Linux"), \
         patch("pathlib.Path.exists", autospec=True,
               side_effect=lambda self: False):
        # PATH has only chromium-browser
        def fake_which(name):
            return "/opt/chromium/chromium-browser" if name == "chromium-browser" else None
        with patch("frago.chrome.backends.extension.shutil.which",
                   side_effect=fake_which):
            result = pick_browser_for_extension()
    assert result == BrowserChoice("/opt/chromium/chromium-browser", "chromium")


def test_chrome_stable_paths_not_in_candidates():
    """Chrome Stable binaries must NOT be picked even if installed."""
    from frago.chrome.backends import extension as ext_mod
    all_paths = (
        [p for p, _ in ext_mod._BROWSER_CANDIDATES_LINUX]
        + [p for p, _ in ext_mod._BROWSER_CANDIDATES_MACOS]
        + [p for p, _ in ext_mod._BROWSER_CANDIDATES_WINDOWS]
        + [c for c, _ in ext_mod._PATH_FALLBACKS]
    )
    chrome_stable_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "google-chrome",
        "google-chrome-stable",
        "chrome",  # Windows PATH alias
    ]
    for forbidden in chrome_stable_paths:
        assert forbidden not in all_paths, (
            f"Chrome Stable binary {forbidden!r} must not be in extension picker — "
            f"it silently rejects --load-extension since v137"
        )


def test_list_browsers_dedupes_by_path():
    """list_browsers_for_extension returns distinct paths."""
    with patch("frago.chrome.backends.extension._platform.system",
               return_value="Linux"), \
         patch("pathlib.Path.exists", autospec=True,
               side_effect=lambda self: str(self) in {
                   "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"
               }), \
         patch("frago.chrome.backends.extension.shutil.which",
               return_value=None):
        results = list_browsers_for_extension()
    paths = [c.path for c in results]
    assert len(paths) == len(set(paths)), f"duplicates: {paths}"
    assert "/usr/bin/microsoft-edge" in paths
    assert "/usr/bin/microsoft-edge-stable" in paths


def test_picker_handles_unknown_os():
    """On unsupported OS, picker tries PATH only and returns None gracefully."""
    with patch("frago.chrome.backends.extension._platform.system",
               return_value="FreeBSD"), \
         patch("frago.chrome.backends.extension.shutil.which",
               return_value=None):
        assert pick_browser_for_extension() is None
