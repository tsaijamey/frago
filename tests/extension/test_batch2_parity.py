"""P2 Batch 2 parity tests — backend-agnostic local ops.

Covers the 2 commands added in Batch 2 (wait, detect). Both are local
operations (time.sleep, PATH scan) and share a single ABC-level
implementation; the "alignment" here is surface uniformity:

1. Both backends expose wait/detect with matching signatures.
2. Neither backend issues any JSON-RPC round-trip for these calls.
3. `frago chrome --backend extension <batch2-cmd>` routes to the
   extension backend (same dispatch layer as MVP + Batch 1).
4. The 6 visual-effect commands remain CDP-only and are documented as
   deferred to P3.1.
"""
from __future__ import annotations

import inspect
import time
from typing import Any

import pytest
from click.testing import CliRunner

from frago.chrome.backends.base import ChromeBackend
from frago.chrome.backends.cdp import CDPChromeBackend
from frago.chrome.backends.extension import ExtensionChromeBackend
from frago.cli import chrome_commands as cc


BATCH2_METHODS = ["wait", "detect"]
P3_1_DEFERRED = {"highlight", "pointer", "spotlight", "annotate",
                 "underline", "clear-effects"}


# ─────────────────────── 1. shared surface ───────────────────────

def test_both_backends_implement_batch2():
    for cls in (CDPChromeBackend, ExtensionChromeBackend):
        assert issubclass(cls, ChromeBackend)
        missing = [m for m in BATCH2_METHODS
                   if not callable(getattr(cls, m, None))]
        assert not missing, f"{cls.__name__} missing: {missing}"


def test_batch2_signatures_align():
    for m in BATCH2_METHODS:
        cdp_sig = inspect.signature(getattr(CDPChromeBackend, m))
        ext_sig = inspect.signature(getattr(ExtensionChromeBackend, m))
        cdp_params = [p for p in cdp_sig.parameters if p != "self"]
        ext_params = [p for p in ext_sig.parameters if p != "self"]
        assert cdp_params == ext_params, \
            f"{m}: cdp={cdp_params} ext={ext_params}"


def test_batch2_inherits_from_abc():
    """wait/detect live on the ABC, not overridden, so behavior is
    guaranteed identical across backends."""
    for m in BATCH2_METHODS:
        assert getattr(CDPChromeBackend, m) is getattr(ChromeBackend, m)
        assert getattr(ExtensionChromeBackend, m) is getattr(ChromeBackend, m)


# ─────────────── 2. no RPC / no-network local semantics ───────────────

class _RpcRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method: str, params: dict) -> Any:
        self.calls.append((method, params))
        return {}


def test_extension_wait_issues_no_rpc(monkeypatch):
    rec = _RpcRecorder()
    be = ExtensionChromeBackend()
    be._rpc = rec  # type: ignore[assignment]
    sleep_called = {}
    monkeypatch.setattr(time, "sleep",
                        lambda s: sleep_called.setdefault("s", s))
    r = be.wait(0.1)
    assert rec.calls == []
    assert r == {"waited": 0.1}
    assert sleep_called["s"] == 0.1


def test_extension_detect_issues_no_rpc(monkeypatch):
    rec = _RpcRecorder()
    be = ExtensionChromeBackend()
    be._rpc = rec  # type: ignore[assignment]
    from frago.chrome.cdp.commands.chrome import BrowserType
    fake = {BrowserType.CHROME: "/usr/bin/google-chrome",
            BrowserType.EDGE: None,
            BrowserType.CHROMIUM: None}
    monkeypatch.setattr(
        "frago.chrome.backends.base.detect_available_browsers"
        if False else "frago.chrome.cdp.commands.chrome.detect_available_browsers",
        lambda: fake)
    r = be.detect()
    assert rec.calls == []
    assert r["default"] == "chrome"
    assert r["found"] == {"chrome": "/usr/bin/google-chrome"}


def test_cdp_wait_is_local(monkeypatch):
    sleep_called = {}
    monkeypatch.setattr(time, "sleep",
                        lambda s: sleep_called.setdefault("s", s))
    be = CDPChromeBackend()
    r = be.wait(0.2)
    assert r == {"waited": 0.2}
    assert sleep_called["s"] == 0.2


def test_cdp_detect_is_local(monkeypatch):
    from frago.chrome.cdp.commands.chrome import BrowserType
    monkeypatch.setattr(
        "frago.chrome.cdp.commands.chrome.detect_available_browsers",
        lambda: {BrowserType.CHROME: None, BrowserType.EDGE: None,
                 BrowserType.CHROMIUM: None})
    be = CDPChromeBackend()
    r = be.detect()
    assert r["default"] is None
    assert r["found"] == {}


def test_both_backends_produce_same_detect_result(monkeypatch):
    from frago.chrome.cdp.commands.chrome import BrowserType
    fake = {BrowserType.CHROME: "/x/chrome",
            BrowserType.EDGE: "/x/edge",
            BrowserType.CHROMIUM: None}
    monkeypatch.setattr(
        "frago.chrome.cdp.commands.chrome.detect_available_browsers",
        lambda: fake)
    assert CDPChromeBackend().detect() == ExtensionChromeBackend().detect()


# ─────────────────── 3. CLI --backend extension routing ───────────────────

class _FakeBackend:
    """Records Batch 2 dispatch to verify CLI routing hits extension."""
    def __init__(self):
        self.calls: list[tuple] = []

    def wait(self, seconds):
        self.calls.append(("wait", seconds))
        return {"waited": seconds}

    def detect(self):
        self.calls.append(("detect",))
        return {"found": {}, "default": None, "all": {}}


@pytest.fixture
def fake_ext(monkeypatch):
    fb = _FakeBackend()
    monkeypatch.setattr(cc, "_ext_backend", lambda: fb)
    return fb


def _run(*args, env_overrides=None):
    env = {"FRAGO_CURRENT_RUN": "", "FRAGO_CHROME_BACKEND": ""}
    if env_overrides:
        env.update(env_overrides)
    return CliRunner().invoke(cc.chrome_group, list(args), env=env)


def test_cli_backend_ext_routes_wait(fake_ext):
    r = _run("--backend", "extension", "wait", "0.01")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("wait", 0.01)
    assert '"waited"' in r.output


def test_cli_backend_ext_routes_detect(fake_ext):
    r = _run("--backend", "extension", "detect")
    assert r.exit_code == 0, r.output
    assert fake_ext.calls[0] == ("detect",)
    assert '"found"' in r.output


# ─────────────── 4. CDP path unchanged for Batch 2 ───────────────

def test_cdp_wait_cli_does_not_touch_extension(monkeypatch):
    """Default backend (no --backend) must not route wait to extension."""
    fb = _FakeBackend()
    monkeypatch.setattr(cc, "_ext_backend", lambda: fb)
    # Don't assert exit code (no Chrome running); only that extension
    # backend was never invoked.
    _run("wait", "0.01")
    assert fb.calls == []


def test_cdp_detect_cli_does_not_touch_extension(monkeypatch):
    fb = _FakeBackend()
    monkeypatch.setattr(cc, "_ext_backend", lambda: fb)
    r = _run("detect")
    # detect has no Chrome dependency — should always succeed on CDP path.
    assert r.exit_code == 0, r.output
    assert fb.calls == []


# ─────────────── 5. Visual effects deferred to P3.1 (documentation) ──

@pytest.mark.parametrize("cmd", sorted(P3_1_DEFERRED))
def test_visual_effects_not_in_extension_dispatch(cmd):
    """P3.1 boundary: these commands must not appear in MVP/Batch1/Batch2
    dispatch. If they're added, test must be updated to reflect the new
    phase ownership."""
    assert cmd not in cc.MVP_COMMANDS
    assert cmd not in cc.BATCH1_COMMANDS
    assert cmd not in cc.BATCH2_COMMANDS


def test_extension_dispatch_supports_visual_effects(monkeypatch):
    """Visual effects are routed through the extension backend (I task).

    (This test originally asserted rejection — pre-I, visuals were CDP-only.
    After I, the dispatch routes to ExtensionChromeBackend.highlight which
    does an RPC. We mock the backend so the test doesn't need a daemon.)
    """
    import frago.cli.chrome_commands as _cc

    calls: list[tuple] = []

    class FakeBackend:
        def highlight(self, selector, group, **kw):
            calls.append(("highlight", selector, group, kw))
            return {"matched": 1}

    monkeypatch.setattr(_cc, "_ext_backend", lambda: FakeBackend())

    _cc._dispatch_extension(
        "highlight",
        {"group": "g", "selector": "#x", "color": "red", "width": 2,
         "life_time": 5, "longlife": False},
    )
    assert calls and calls[0][0] == "highlight"


# ─────────────── 6. Batch 2 appears in backend-option help ───────────

def test_backend_help_mentions_batch2():
    r = CliRunner().invoke(cc.chrome_group, ["--help"])
    assert r.exit_code == 0
    assert "wait" in r.output and "detect" in r.output
    # I task: visual effects are now in the supported list.
    out_lower = r.output.lower()
    for v in ("highlight", "pointer", "spotlight", "annotate",
              "underline", "clear-effects"):
        assert v in out_lower, f"backend help should mention '{v}'"
