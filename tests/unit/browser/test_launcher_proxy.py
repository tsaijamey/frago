"""Unit tests for ChromeLauncher.launch() automatic local proxy injection."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import frago.browser.cdp.launcher as launcher_mod
from frago.browser import proxy_detect
from frago.browser.cdp.browser_detection import BrowserType
from frago.browser.cdp.launcher import ChromeLauncher


@pytest.fixture
def captured_launch(monkeypatch, tmp_path):
    """Stub out process spawning and filesystem side-effects in ChromeLauncher.launch()."""
    captured_cmds: list[list[str]] = []

    def fake_resolve(self, browser):
        return BrowserType.CHROME, "/fake/chrome"

    def fake_popen(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return MagicMock()

    monkeypatch.setattr(ChromeLauncher, "_resolve_browser", fake_resolve)
    monkeypatch.setattr(ChromeLauncher, "_wait_port_free", lambda self, *a, **k: True)
    monkeypatch.setattr(ChromeLauncher, "_migrate_legacy_profile", lambda self, *a, **k: None)
    monkeypatch.setattr(ChromeLauncher, "_init_profile_dir", lambda self: None)
    monkeypatch.setattr(ChromeLauncher, "wait_for_cdp", lambda self, *a, **k: False)
    monkeypatch.setattr(launcher_mod, "kill_existing_chrome", lambda port: 0)
    monkeypatch.setattr(launcher_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(launcher_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(proxy_detect, "_system_bypass_entries", list)

    for var in (
        "FRAGO_BROWSER_PROXY",
        "FRAGO_BROWSER_PROXY_BYPASS",
        "no_proxy",
        "NO_PROXY",
        *proxy_detect._PROXY_ENV_VARS,
    ):
        monkeypatch.delenv(var, raising=False)

    return tmp_path, captured_cmds


def test_launch_injects_proxy_and_bypass_when_local_proxy_detected(
    monkeypatch, captured_launch
):
    """When detect_local_proxy() finds a local proxy, --proxy-server and --proxy-bypass-list are injected."""
    tmp_path, captured_cmds = captured_launch
    monkeypatch.setattr(
        launcher_mod, "detect_local_proxy", lambda: "http://127.0.0.1:7890"
    )

    launcher = ChromeLauncher(
        headless=True, port=9222, profile_dir=tmp_path / "profile"
    )
    launcher.launch(kill_existing=False)

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "--proxy-server=http://127.0.0.1:7890" in cmd

    bypass_flags = [arg for arg in cmd if arg.startswith("--proxy-bypass-list=")]
    assert len(bypass_flags) == 1
    bypass_entries = bypass_flags[0].split("=", 1)[1].split(";")
    for required in ("127.0.0.1", "localhost", "::1", "<local>", "10.0.0.0/8", "192.168.0.0/16"):
        assert required in bypass_entries


def test_launch_skips_proxy_when_frago_browser_proxy_off(
    monkeypatch, captured_launch
):
    """When FRAGO_BROWSER_PROXY=off (detect_local_proxy() returns None), no --proxy-server is injected."""
    tmp_path, captured_cmds = captured_launch
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "off")
    monkeypatch.setattr(
        proxy_detect, "_speaks_http_proxy", lambda host, port, timeout: True
    )

    launcher = ChromeLauncher(
        headless=True, port=9222, profile_dir=tmp_path / "profile"
    )
    launcher.launch(kill_existing=False)

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert not any(arg.startswith("--proxy-server") for arg in cmd)
    assert not any(arg.startswith("--proxy-bypass-list") for arg in cmd)


@pytest.mark.parametrize(
    "existing_flag",
    [
        "--proxy-server=http://127.0.0.1:8888",
        "--no-proxy-server",
    ],
)
def test_launch_preserves_existing_proxy_flag_in_extra_args(
    monkeypatch, captured_launch, existing_flag: str
):
    """When extra_args already includes --proxy-server=... or --no-proxy-server, do not inject again."""
    tmp_path, captured_cmds = captured_launch
    monkeypatch.setattr(
        launcher_mod, "detect_local_proxy", lambda: "http://127.0.0.1:7890"
    )

    launcher = ChromeLauncher(
        headless=True,
        port=9222,
        profile_dir=tmp_path / "profile",
        extra_args=[existing_flag],
    )
    launcher.launch(kill_existing=False)

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert existing_flag in cmd
    proxy_flags = [
        arg
        for arg in cmd
        if arg in ("--no-proxy-server", "--proxy-server")
        or arg.startswith("--proxy-server=")
    ]
    assert proxy_flags == [existing_flag]


def test_launch_method_extra_args_also_prevent_duplicate_injection(
    monkeypatch, captured_launch
):
    """Passing --proxy-server or --no-proxy-server to launch(extra_args=...) is also idempotent."""
    tmp_path, captured_cmds = captured_launch
    monkeypatch.setattr(
        launcher_mod, "detect_local_proxy", lambda: "http://127.0.0.1:7890"
    )

    launcher = ChromeLauncher(
        headless=True, port=9222, profile_dir=tmp_path / "profile"
    )
    launcher.launch(
        kill_existing=False,
        extra_args=["--proxy-server=http://127.0.0.1:9999"],
    )

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    proxy_flags = [
        arg
        for arg in cmd
        if arg in ("--no-proxy-server", "--proxy-server")
        or arg.startswith("--proxy-server=")
    ]
    assert proxy_flags == ["--proxy-server=http://127.0.0.1:9999"]

