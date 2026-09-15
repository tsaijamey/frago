"""What the extension backend must and must not put on the command line.

These pin two launch flags that are invisible until they are missing.
Both were found the expensive way, by losing a working browser to them.
"""
from __future__ import annotations

import pytest

from frago.browser import proxy_detect
from frago.browser.backends import extension as ext_mod


@pytest.fixture
def launched(monkeypatch, tmp_path):
    """Capture the argv the backend would launch, without launching."""
    captured: dict[str, list[str]] = {}

    class FakeProc:
        pid = 4321

    def fake_popen(args, **kwargs):
        captured["args"] = args
        return FakeProc()

    monkeypatch.setattr(ext_mod.subprocess, "Popen", fake_popen)
    # The bypass list shells out to read the OS exceptions list, and
    # ``subprocess.run`` would go through the stub above. Stub it too,
    # which also keeps these assertions off this machine's settings.
    monkeypatch.setattr(proxy_detect, "_system_bypass_entries", list)

    def run(**kwargs):
        bundle = tmp_path / "bundle"
        bundle.mkdir(exist_ok=True)
        ext_mod.launch_chrome_with_extension(
            bundle,
            user_data_dir=tmp_path / "profile",
            chrome_binary="/nonexistent/browser",
            brand="cft",
            **kwargs,
        )
        return captured["args"]

    return run


def _flag(args: list[str], name: str) -> str | None:
    for a in args:
        if a == name or a.startswith(f"{name}="):
            return a
    return None


# ── sync ────────────────────────────────────────────────────────────

def test_sync_is_disabled(launched):
    """Signing into Google would otherwise let sync evict the bridge.

    Sync takes over extension management for the profile and drops the
    command-line-loaded bridge, surfacing only as "extension not
    connected" long after the sign-in that caused it.
    """
    assert "--disable-sync" in launched()


# ── proxy ───────────────────────────────────────────────────────────

def test_proxy_flags_present_when_a_proxy_is_found(launched, monkeypatch):
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "http://127.0.0.1:7890")
    args = launched()
    assert _flag(args, "--proxy-server") == "--proxy-server=http://127.0.0.1:7890"
    assert _flag(args, "--proxy-bypass-list") is not None


def test_no_proxy_flags_when_none_is_found(launched, monkeypatch):
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "off")
    args = launched()
    assert _flag(args, "--proxy-server") is None
    assert _flag(args, "--proxy-bypass-list") is None


# ── shape of the command line ───────────────────────────────────────

def test_startup_url_stays_last(launched, monkeypatch):
    """The URL must remain the final argument, after any added flags."""
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "http://127.0.0.1:7890")
    args = launched()
    assert args[-1] == "about:blank"


def test_app_url_replaces_blank_tab(launched, monkeypatch):
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "http://127.0.0.1:7890")
    args = launched(app_url="http://127.0.0.1:8093/#/sessions")
    assert args[-1] == "--app=http://127.0.0.1:8093/#/sessions"
    assert "about:blank" not in args


def test_core_flags_survive_the_additions(launched, monkeypatch):
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "http://127.0.0.1:7890")
    args = launched()
    assert _flag(args, "--load-extension") is not None
    assert _flag(args, "--user-data-dir") is not None
    assert "--no-first-run" in args
