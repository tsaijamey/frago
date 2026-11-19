"""Tests for the `frago browser` CLI group (spec 20260629-arch-refactor-cli, Phase 5).

browser_commands is the largest CLI surface and previously had zero coverage.
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
from frago.cli.browser_commands import browser_group


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

def test_browser_group_help(runner):
    result = runner.invoke(browser_group, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Browser automation" in result.output


@pytest.mark.parametrize("name", sorted(browser_group.commands.keys()))
def test_subcommand_help_parses(runner, name):
    result = runner.invoke(browser_group, [name, "--help"])
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
    assert expected <= set(browser_group.commands.keys())


# ───────────────────────── Thin-shell wiring: delegate to lower layer ──────────

def test_get_title_delegates_to_session(runner, monkeypatch):
    session = MagicMock()
    session.get_title.return_value = "Hello World"
    _patch_session(monkeypatch, session)

    result = runner.invoke(browser_group, ["-b", "cdp", "get-title", "--group", "research"])

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

    result = runner.invoke(browser_group, ["-b", "cdp", "status"])

    assert result.exit_code == 0, result.output
    session.status.health_check.assert_called_once_with()
    assert "CDP connection OK" in result.output
    assert "Chrome/120" in result.output


def test_status_unhealthy_exits_nonzero(runner, monkeypatch):
    session = MagicMock()
    session.status.health_check.return_value = False
    _patch_session(monkeypatch, session)

    result = runner.invoke(browser_group, ["-b", "cdp", "status"])

    assert result.exit_code != 0
    assert "CDP connection failed" in result.output


def test_detect_delegates_to_browser_detection(runner, monkeypatch):
    import frago.browser.cdp.browser_detection as bd

    monkeypatch.setattr(
        bd, "detect_available_browsers",
        lambda: {bd.BrowserType.CHROME: "/usr/bin/google-chrome"},
    )

    result = runner.invoke(browser_group, ["-b", "cdp", "detect"])

    assert result.exit_code == 0, result.output
    assert "/usr/bin/google-chrome" in result.output


def test_detect_no_browsers(runner, monkeypatch):
    import frago.browser.cdp.browser_detection as bd

    monkeypatch.setattr(bd, "detect_available_browsers", lambda: {})

    result = runner.invoke(browser_group, ["-b", "cdp", "detect"])

    assert result.exit_code == 0, result.output
    assert "No supported browsers found" in result.output


# ───────────────────────── Layer-1 agent-friendly: unknown subcommand ──────────

def test_unknown_subcommand_suggests_alternatives(runner):
    result = runner.invoke(browser_group, ["navigat"])  # typo for navigate
    assert result.exit_code != 0
    assert "navigate" in result.output
    assert "Available commands" in result.output


# ───────────────────────── exec-js file mode parity & boundaries ─────────────

def _mock_extension_backend(monkeypatch):
    import frago.cli.browser_commands as bc
    from frago.browser.backends.base import ExecResult

    calls: list[tuple[str, str]] = []

    class FakeExtensionBackend:
        def exec_js(self, script: str, group: str) -> ExecResult:
            calls.append((script, group))
            return ExecResult(value={"ok": True, "script": script})

    monkeypatch.setattr(bc, "_ext_backend", lambda: FakeExtensionBackend())
    return calls


@pytest.mark.parametrize("filename,content", [
    ("script.js", "// 中文注释\n1 + 1"),
    ("module.mjs", "(() => 42)()"),
])
def test_exec_js_extension_reads_existing_file(runner, monkeypatch, tmp_path, filename, content):
    import json

    script_file = tmp_path / filename
    script_file.write_text(content, encoding="utf-8")
    calls = _mock_extension_backend(monkeypatch)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", str(script_file), "--return-value"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(content, "research")]
    payload = json.loads(result.output)
    assert payload["value"]["script"] == content


def test_exec_js_extension_reads_relative_dot_slash_file(runner, monkeypatch, tmp_path):
    script_file = tmp_path / "script.js"
    script_file.write_text("1 + 1", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    calls = _mock_extension_backend(monkeypatch)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", "./script.js", "--return-value"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("1 + 1", "research")]


@pytest.mark.parametrize("expr", [
    "1+1",
    "document.title",
    "location.href.endsWith('.js')",
    "location.pathname.endsWith('.mjs')",
    "const f = 'a.js'; f",
    "a + b.js",
])
def test_exec_js_extension_preserves_inline_expressions(runner, monkeypatch, expr):
    calls = _mock_extension_backend(monkeypatch)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", expr, "--return-value"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(expr, "research")]


@pytest.mark.parametrize("missing_path", [
    "./missing.js",
    "../missing.js",
    "/tmp/nonexistent_exec_js_1010.js",
    "missing.js",
    "sub/missing.mjs",
    "./sub/missing.mjs",
])
def test_exec_js_extension_missing_js_file_fails_clearly(runner, monkeypatch, tmp_path, missing_path):
    import json

    monkeypatch.chdir(tmp_path)
    calls = _mock_extension_backend(monkeypatch)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", missing_path, "--return-value"],
    )

    assert result.exit_code != 0
    assert calls == []
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["code"] == "script-file-not-found"
    assert missing_path in payload["error"]
    assert "frago browser start" not in result.output


def test_exec_js_extension_directory_named_js_fails_clearly(runner, monkeypatch, tmp_path):
    import json

    dir_path = tmp_path / "folder.js"
    dir_path.mkdir()
    calls = _mock_extension_backend(monkeypatch)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", str(dir_path)],
    )

    assert result.exit_code != 0
    assert calls == []
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["code"] == "script-path-is-directory"


def test_exec_js_extension_permission_error_not_misclassified(runner, monkeypatch, tmp_path):
    import builtins
    import json

    script_file = tmp_path / "locked.js"
    script_file.write_text("1 + 1", encoding="utf-8")
    calls = _mock_extension_backend(monkeypatch)

    real_open = builtins.open

    def deny_open(file, *args, **kwargs):
        if str(file) == str(script_file):
            raise PermissionError("operation not permitted")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny_open)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", str(script_file)],
    )

    assert result.exit_code != 0
    assert calls == []
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["code"] == "script-file-permission-denied"


def test_exec_js_extension_invalid_utf8_reports_encoding_error(runner, monkeypatch, tmp_path):
    import json

    script_file = tmp_path / "binary.js"
    script_file.write_bytes(b"\xff\xfe\x00\x01")
    calls = _mock_extension_backend(monkeypatch)

    result = runner.invoke(
        browser_group,
        ["exec-js", "--group", "research", str(script_file)],
    )

    assert result.exit_code != 0
    assert calls == []
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["code"] == "script-file-encoding-error"


def test_exec_js_cdp_reads_existing_file_and_rejects_missing(runner, monkeypatch, tmp_path):
    script_file = tmp_path / "cdp_script.js"
    script_file.write_text("1 + 2", encoding="utf-8")

    session = MagicMock()
    session.evaluate.return_value = 3
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(commands, "_touch_active_tab", lambda *_a, **_k: None)
    monkeypatch.setattr(commands, "_do_perception", lambda *_a, **_k: None)

    obj = {"HOST": "127.0.0.1", "PORT": 9222, "DEBUG": False}

    ok_res = runner.invoke(
        browser_group,
        ["-b", "cdp", "exec-js", "--group", "research", str(script_file), "--return-value"],
        obj=obj,
    )
    assert ok_res.exit_code == 0, ok_res.output
    session.evaluate.assert_called_once_with("1 + 2", return_by_value=True)

    session.evaluate.reset_mock()
    inline_res = runner.invoke(
        browser_group,
        ["-b", "cdp", "exec-js", "--group", "research", "location.href.endsWith('.js')", "--return-value"],
        obj=obj,
    )
    assert inline_res.exit_code == 0, inline_res.output
    session.evaluate.assert_called_once_with("location.href.endsWith('.js')", return_by_value=True)

    session.evaluate.reset_mock()
    monkeypatch.chdir(tmp_path)
    missing_res = runner.invoke(
        browser_group,
        ["-b", "cdp", "exec-js", "--group", "research", "./missing.mjs", "--return-value"],
        obj=obj,
    )
    assert missing_res.exit_code != 0
    session.evaluate.assert_not_called()
    assert "JavaScript file not found: ./missing.mjs" in missing_res.output


def test_extension_subcommand_exec_js_shares_file_resolution(runner, monkeypatch, tmp_path):
    import json

    import frago.cli.extension_commands as ec
    from frago.browser.backends.base import ExecResult

    calls: list[tuple[str, str]] = []

    class FakeBackend:
        def exec_js(self, script: str, group: str) -> ExecResult:
            calls.append((script, group))
            return ExecResult(value=2)

    monkeypatch.setattr(ec, "_be", lambda: FakeBackend())

    script_file = tmp_path / "ext_script.js"
    script_file.write_text("1 + 1", encoding="utf-8")

    ok_res = runner.invoke(ec.extension_group, ["exec-js", "--group", "g", str(script_file)])
    assert ok_res.exit_code == 0, ok_res.output
    assert calls == [("1 + 1", "g")]

    calls.clear()
    missing_res = runner.invoke(ec.extension_group, ["exec-js", "--group", "g", "./missing.js"])
    assert missing_res.exit_code != 0
    assert calls == []
    payload = json.loads(missing_res.output)
    assert payload["code"] == "script-file-not-found"
