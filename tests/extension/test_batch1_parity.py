"""P2 Batch 1 parity tests.

Covers the 14 commands added in Batch 1:
  stop, status, list-tabs, switch-tab, close-tab,
  groups, group-info, group-close, group-cleanup, reset,
  scroll, scroll-to, zoom, get-title.

Real browser parity remains blocked on the Chrome --load-extension policy
(see outputs/e2e_p2b1/chrome_plan_a.log for Plan A attempt). These tests
verify:

1. Both backends expose the Batch 1 methods with matching signatures.
2. ExtensionChromeBackend serializes each Batch 1 call to the expected
   JSON-RPC method name + params, and decodes the response shape used by
   the CLI dispatch layer.
3. `frago chrome --backend extension <batch1-cmd>` routes to the
   extension backend (not the CDP CLI callback).
"""
from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from click.testing import CliRunner

from frago.chrome.backends.base import ChromeBackend
from frago.chrome.backends.cdp import CDPChromeBackend
from frago.chrome.backends.extension import ExtensionChromeBackend
from frago.cli import chrome_commands as cc


BATCH1_METHODS = [
    "stop", "status", "list_tabs", "switch_tab", "close_tab",
    "list_groups", "group_info", "group_close", "group_cleanup", "reset",
    "scroll", "scroll_to", "zoom", "get_title",
]


# ─────────────────────── 1. shared surface ───────────────────────

def test_both_backends_implement_batch1():
    for cls in (CDPChromeBackend, ExtensionChromeBackend):
        assert issubclass(cls, ChromeBackend)
        missing = [m for m in BATCH1_METHODS if not callable(getattr(cls, m, None))]
        assert not missing, f"{cls.__name__} missing: {missing}"


def test_batch1_signatures_align():
    # Pure no-arg methods first.
    for m in ("stop", "status", "list_tabs", "list_groups", "group_cleanup"):
        cdp_sig = inspect.signature(getattr(CDPChromeBackend, m))
        ext_sig = inspect.signature(getattr(ExtensionChromeBackend, m))
        cdp_params = [p for p in cdp_sig.parameters if p != "self"]
        ext_params = [p for p in ext_sig.parameters if p != "self"]
        assert cdp_params == ext_params, f"{m}: cdp={cdp_params} ext={ext_params}"
    # Parametric ones.
    for m in ("switch_tab", "close_tab", "group_info", "group_close",
              "reset", "scroll", "scroll_to", "zoom", "get_title"):
        cdp_sig = inspect.signature(getattr(CDPChromeBackend, m))
        ext_sig = inspect.signature(getattr(ExtensionChromeBackend, m))
        cdp_params = [p for p in cdp_sig.parameters if p != "self"]
        ext_params = [p for p in ext_sig.parameters if p != "self"]
        assert cdp_params == ext_params, f"{m}: cdp={cdp_params} ext={ext_params}"


# ─────────────────────── 2. extension RPC framing ───────────────────────

class _RpcRecorder:
    """Stand-in for ExtensionChromeBackend._rpc — records (method, params)."""
    def __init__(self, responses: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.responses = responses or {}

    def __call__(self, method: str, params: dict) -> Any:
        self.calls.append((method, params))
        return self.responses.get(method, {})


def _ext_with_rpc(rec: _RpcRecorder) -> ExtensionChromeBackend:
    be = ExtensionChromeBackend()
    be._rpc = rec  # type: ignore[assignment]
    return be


@pytest.mark.parametrize("call, expected_method, expected_params", [
    # (callable_fn, rpc_method, rpc_params)
    (lambda be: be.status(), "system.info", {}),
    (lambda be: be.list_tabs(), "tabs.list", {}),
    (lambda be: be.switch_tab(42), "tabs.switch", {"tab_id": 42}),
    (lambda be: be.switch_tab("42"), "tabs.switch", {"tab_id": 42}),
    (lambda be: be.close_tab(7), "tabs.close", {"tab_id": 7}),
    (lambda be: be.list_groups(), "groups.list", {}),
    (lambda be: be.group_info("research"), "groups.info", {"name": "research"}),
    (lambda be: be.group_close("research"), "groups.close", {"name": "research"}),
    (lambda be: be.group_cleanup(), "groups.cleanup", {}),
    (lambda be: be.reset(None), "tabs.reset", {"group": None}),
    (lambda be: be.reset("g1"), "tabs.reset", {"group": "g1"}),
    (lambda be: be.scroll(500, "g1"),
     "page.scroll", {"distance": 500, "group": "g1"}),
    (lambda be: be.scroll_to("g1", selector="h1"),
     "page.scroll_to",
     {"group": "g1", "selector": "h1", "text": None, "block": "center"}),
    (lambda be: be.scroll_to("g1", text="Hello", block="start"),
     "page.scroll_to",
     {"group": "g1", "selector": None, "text": "Hello", "block": "start"}),
    (lambda be: be.zoom(1.25, "g1"),
     "page.zoom", {"factor": 1.25, "group": "g1"}),
    (lambda be: be.get_title("g1"), "page.get_title", {"group": "g1"}),
])
def test_extension_rpc_framing(call, expected_method, expected_params):
    rec = _RpcRecorder(responses={
        "tabs.list": {"tabs": []},
        "groups.list": {"groups": {}},
        "page.get_title": {"title": "T"},
    })
    be = _ext_with_rpc(rec)
    call(be)
    assert rec.calls, f"no RPC call made for {expected_method}"
    method, params = rec.calls[-1]
    assert method == expected_method
    assert params == expected_params


def test_extension_stop_is_no_op_diagnostic():
    # stop() MUST NOT issue any RPC — extension does not own Chrome.
    rec = _RpcRecorder()
    be = _ext_with_rpc(rec)
    r = be.stop()
    assert rec.calls == []
    assert r["backend"] == "extension"
    assert r["stopped"] is False


def test_extension_scroll_to_requires_selector_or_text():
    rec = _RpcRecorder()
    be = _ext_with_rpc(rec)
    with pytest.raises(ValueError):
        be.scroll_to("g1")


def test_extension_get_title_unwraps_dict():
    rec = _RpcRecorder(responses={"page.get_title": {"title": "hello"}})
    be = _ext_with_rpc(rec)
    assert be.get_title("g1") == "hello"


# ─────────────────── 3. CLI --backend extension routing ───────────────────

class _FakeBackend:
    def __init__(self):
        self.calls: list[tuple] = []

    def stop(self):
        self.calls.append(("stop",))
        return {"stopped": False, "backend": "fake"}

    def status(self):
        self.calls.append(("status",))
        return {"ok": True}

    def list_tabs(self):
        self.calls.append(("list_tabs",))
        return [{"id": "abc", "title": "t", "url": "u", "index": 0}]

    def switch_tab(self, tab_id):
        self.calls.append(("switch_tab", tab_id))
        return {"tab_id": tab_id}

    def close_tab(self, tab_id):
        self.calls.append(("close_tab", tab_id))
        return {"tab_id": tab_id, "closed": True}

    def list_groups(self):
        self.calls.append(("list_groups",))
        return {"g1": {"tabs": 1}}

    def group_info(self, name):
        self.calls.append(("group_info", name))
        return {"name": name}

    def group_close(self, name):
        self.calls.append(("group_close", name))
        return {"name": name, "closed": True}

    def group_cleanup(self):
        self.calls.append(("group_cleanup",))
        return {"removed": 0}

    def reset(self, group=None):
        self.calls.append(("reset", group))
        return {"group": group, "closed": []}

    def scroll(self, distance, group):
        self.calls.append(("scroll", distance, group))
        return {"scrolled": distance}

    def scroll_to(self, group, *, selector=None, text=None, block="center"):
        self.calls.append(("scroll_to", group, selector, text, block))
        return {"success": True}

    def zoom(self, factor, group):
        self.calls.append(("zoom", factor, group))
        return {"factor": factor}

    def get_title(self, group):
        self.calls.append(("get_title", group))
        return "Hello"


@pytest.fixture
def fake_ext(monkeypatch):
    fb = _FakeBackend()
    monkeypatch.setattr(cc, "_ext_backend", lambda: fb)
    return fb


def _run(*args, env_overrides=None):
    # Clear run-context env vars so --group requirement is honored and
    # reset() sees a None group by default.
    env = {"FRAGO_CURRENT_RUN": "", "FRAGO_CHROME_BACKEND": ""}
    if env_overrides:
        env.update(env_overrides)
    return CliRunner().invoke(cc.chrome_group, list(args), env=env)


def test_cli_backend_ext_routes_stop(fake_ext, monkeypatch):
    """`frago chrome stop --backend extension` goes through the lifecycle
    orchestrator (F task), not directly through ExtensionChromeBackend.stop().
    Mock the orchestrator to avoid touching real processes."""
    from frago.chrome.extension import lifecycle as lc

    fake_result = lc.BridgeStopResult(
        browser_pid=None, browser_stopped=False, browser_force_killed=False,
        daemon_pid=None, daemon_stopped=False, socket_removed=False,
        profile_dir="/tmp/p",
    )
    captured: list[dict] = []
    monkeypatch.setattr(lc, "stop_extension_bridge",
                        lambda **kw: (captured.append(kw) or fake_result))

    r = _run("--backend", "extension", "stop")
    assert r.exit_code == 0, r.output
    assert captured == [{}], "stop_extension_bridge was not called"


def test_cli_backend_ext_routes_status(fake_ext):
    r = _run("--backend", "extension", "status")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("status",)


def test_cli_backend_ext_routes_list_tabs(fake_ext):
    r = _run("--backend", "extension", "list-tabs")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("list_tabs",)
    assert '"tabs"' in r.output


def test_cli_backend_ext_routes_switch_tab(fake_ext):
    r = _run("--backend", "extension", "switch-tab", "42")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("switch_tab", "42")


def test_cli_backend_ext_routes_close_tab(fake_ext):
    r = _run("--backend", "extension", "close-tab", "7")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("close_tab", "7")


def test_cli_backend_ext_routes_groups(fake_ext):
    r = _run("--backend", "extension", "groups")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("list_groups",)


def test_cli_backend_ext_routes_group_info(fake_ext):
    r = _run("--backend", "extension", "group-info", "research")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("group_info", "research")


def test_cli_backend_ext_routes_group_close(fake_ext):
    r = _run("--backend", "extension", "group-close", "research")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("group_close", "research")


def test_cli_backend_ext_routes_group_cleanup(fake_ext):
    r = _run("--backend", "extension", "group-cleanup")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("group_cleanup",)


def test_cli_backend_ext_routes_reset_global(fake_ext):
    r = _run("--backend", "extension", "reset")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("reset", None)


def test_cli_backend_ext_routes_scroll(fake_ext):
    r = _run("--backend", "extension", "scroll", "500", "--group", "g1")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("scroll", 500, "g1")


def test_cli_backend_ext_routes_scroll_to(fake_ext):
    r = _run("--backend", "extension", "scroll-to", "h1", "--group", "g1")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0][:3] == ("scroll_to", "g1", "h1")


def test_cli_backend_ext_routes_zoom(fake_ext):
    r = _run("--backend", "extension", "zoom", "1.25", "--group", "g1")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("zoom", 1.25, "g1")


def test_cli_backend_ext_routes_get_title(fake_ext):
    r = _run("--backend", "extension", "get-title", "--group", "g1")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("get_title", "g1")


# ─────────────────── 4. --backend extension error paths ───────────────────

def test_ext_scroll_without_group_errors(fake_ext):
    r = _run("--backend", "extension", "scroll", "100")
    assert r.exit_code != 0
    assert "group" in r.output.lower()


def test_ext_zoom_without_group_errors(fake_ext):
    r = _run("--backend", "extension", "zoom", "1.5")
    assert r.exit_code != 0
    assert "group" in r.output.lower()


def test_ext_switch_tab_requires_tab_id():
    # Click will fail argument parsing before our dispatcher is reached.
    r = _run("--backend", "extension", "switch-tab")
    assert r.exit_code != 0


# ─────────────────── 5. backward compat: CDP path intact ───────────────────

def test_cdp_path_unchanged_for_batch1(monkeypatch):
    """Without --backend extension, Batch 1 cmds still use the CDP CLI
    callback (which internally uses TabGroupManager / requests), not the
    extension backend.
    """
    fb = _FakeBackend()
    monkeypatch.setattr(cc, "_ext_backend", lambda: fb)

    # Invoke without --backend: should NOT hit the fake extension backend.
    # The CDP callback may fail because no Chrome is running, but what we
    # assert is that _ext_backend() is not called.
    r = _run("list-tabs")
    # Regardless of exit code (CDP may error out without Chrome), the
    # extension path must not have been hit.
    assert fb.calls == [], f"CDP path leaked into extension backend: {fb.calls}"
