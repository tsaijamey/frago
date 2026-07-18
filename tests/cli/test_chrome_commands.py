"""Tests for the `frago chrome` CLI group (spec 20260629-arch-refactor-cli, Phase 5).

chrome_commands is the largest CLI surface and previously had zero coverage.
These tests pin two things the refactor must not break:

  1. Command面冻结 — every registered subcommand still parses and renders its
     ``--help`` (the agent/script contract).
  2. Thin-shell wiring — the command shells delegate to the lower layer
     (``create_session`` / browser detection) rather than carrying business
     logic inline. The lower layer is mocked so no real browser is needed.

Mocking strategy: ``create_session`` is patched with a fake context manager
yielding a ``MagicMock`` session, and the run-log side-effect is silenced so
nothing touches disk.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import frago.cli.commands as commands
from frago.cli.chrome_commands import chrome_group


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _silence_run_log(monkeypatch):
    """_print_msg writes to the run log as a side effect — keep tests off disk."""
    monkeypatch.setattr(
        commands.run_log_adapter, "write_run_log", lambda *_a, **_k: None
    )


def _patch_session(monkeypatch, session: MagicMock) -> None:
    """Patch commands.create_session to yield the given fake session."""

    @contextmanager
    def fake_create_session(*_a, **_k):
        yield session

    monkeypatch.setattr(commands, "create_session", fake_create_session)
    # Landing-page guard pokes the real session API; neutralize it.
    monkeypatch.setattr(commands, "_check_landing_page_protection", lambda *_a, **_k: None)


# ───────────────────────── Command面冻结: parse + help ─────────────────────────

def test_chrome_group_help(runner):
    result = runner.invoke(chrome_group, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Chrome" in result.output


@pytest.mark.parametrize("name", sorted(chrome_group.commands.keys()))
def test_subcommand_help_parses(runner, name):
    result = runner.invoke(chrome_group, [name, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_expected_subcommands_registered():
    # A representative slice of the frozen command surface.
    expected = {
        "start", "stop", "status", "detect",
        "navigate", "scroll", "scroll-to", "zoom", "wait",
        "click", "exec-js", "get-title", "get-content",
        "list-tabs", "switch-tab", "close-tab",
        "groups", "group-info", "group-close", "group-cleanup", "reset",
        "screenshot", "highlight", "pointer", "spotlight", "annotate",
        "underline", "clear-effects",
    }
    assert expected <= set(chrome_group.commands.keys())


# ───────────────────────── Thin-shell wiring: delegate to lower layer ──────────

def test_get_title_delegates_to_session(runner, monkeypatch):
    session = MagicMock()
    session.get_title.return_value = "Hello World"
    _patch_session(monkeypatch, session)

    result = runner.invoke(chrome_group, ["get-title", "--group", "research"])

    assert result.exit_code == 0, result.output
    session.get_title.assert_called_once_with()
    assert "Hello World" in result.output


def test_status_delegates_to_session(runner, monkeypatch):
    session = MagicMock()
    session.status.health_check.return_value = True
    session.status.check_chrome_status.return_value = {
        "Browser": "Chrome/120",
        "Protocol-Version": "1.3",
        "WebKit-Version": "537.36",
    }
    _patch_session(monkeypatch, session)

    result = runner.invoke(chrome_group, ["status"])

    assert result.exit_code == 0, result.output
    session.status.health_check.assert_called_once_with()
    assert "CDP connection OK" in result.output
    assert "Chrome/120" in result.output


def test_status_unhealthy_exits_nonzero(runner, monkeypatch):
    session = MagicMock()
    session.status.health_check.return_value = False
    _patch_session(monkeypatch, session)

    result = runner.invoke(chrome_group, ["status"])

    assert result.exit_code != 0
    assert "CDP connection failed" in result.output


def test_detect_delegates_to_browser_detection(runner, monkeypatch):
    import frago.chrome.cdp.browser_detection as bd

    monkeypatch.setattr(
        bd, "detect_available_browsers",
        lambda: {bd.BrowserType.CHROME: "/usr/bin/google-chrome"},
    )

    result = runner.invoke(chrome_group, ["detect"])

    assert result.exit_code == 0, result.output
    assert "/usr/bin/google-chrome" in result.output


def test_detect_no_browsers(runner, monkeypatch):
    import frago.chrome.cdp.browser_detection as bd

    monkeypatch.setattr(bd, "detect_available_browsers", lambda: {})

    result = runner.invoke(chrome_group, ["detect"])

    assert result.exit_code == 0, result.output
    assert "No supported browsers found" in result.output


# ───────────────────────── Layer-1 agent-friendly: unknown subcommand ──────────

def test_unknown_subcommand_suggests_alternatives(runner):
    result = runner.invoke(chrome_group, ["navigat"])  # typo for navigate
    assert result.exit_code != 0
    assert "navigate" in result.output
    assert "Available commands" in result.output
