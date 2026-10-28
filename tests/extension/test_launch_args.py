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

def test_no_cli_proxy_flags_so_extension_options_page_owns_proxy(launched, monkeypatch):
    """Command-line --proxy-server locks out chrome.proxy.settings in MV3.

    Proxy and bypass domains are configured exclusively in the extension's
    Options page (options/options.html): filling an address enables proxy,
    leaving it empty keeps everything inactive.
    """
    monkeypatch.setenv("FRAGO_BROWSER_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    args = launched()
    assert _flag(args, "--proxy-server") is None
    assert _flag(args, "--proxy-bypass-list") is None


def test_extension_bundle_declares_options_page_and_proxy_permission():
    """Options page and proxy permission must be wired in manifest.json."""
    import json

    from frago.browser.extension import bundle_path

    bundle = bundle_path()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert "proxy" in manifest["permissions"]
    assert manifest.get("options_page") == "options/options.html"
    assert manifest.get("version") == "0.3.3"
    assert manifest["background"]["service_worker"] == "background/service-worker-v14.js"

    options_html = (bundle / "options" / "options.html").read_text(encoding="utf-8")
    options_js = (bundle / "options" / "options.js").read_text(encoding="utf-8")
    assert 'id="proxy-url"' in options_html
    assert 'id="bypass-domains"' in options_html
    assert 'src="options.js"' in options_html
    assert "white-space: nowrap" in options_html
    assert 'type="checkbox"' not in options_html, "no proxy toggle switch allowed"
    assert "frago.proxy.save" in options_js


def test_service_worker_proxy_address_only_semantics():
    """Verify via Node that empty proxyUrl clears proxy and non-empty activates fixed_servers."""
    import json
    import shutil
    import subprocess

    from frago.browser.extension import bundle_path

    if not shutil.which("node"):
        pytest.skip("node not installed")

    sw_path = bundle_path() / "background" / "service-worker-v14.js"
    script = f"""
    const fs = require("fs");
    const vm = require("vm");
    const code = fs.readFileSync({json.dumps(str(sw_path))}, "utf8");
    const calls = [];
    const store = {{}};
    const noopEvent = {{ addListener: () => {{}} }};
    const sandbox = {{
        console,
        URL,
        Set,
        Map,
        Date,
        Math,
        Number,
        String,
        Array,
        Object,
        Promise,
        setTimeout: () => 0,
        clearTimeout: () => {{}},
        setInterval: () => 0,
        clearInterval: () => {{}},
        self: {{ addEventListener: () => {{}} }},
        chrome: {{
            runtime: {{
                id: "test-id",
                connectNative: () => ({{ onMessage: noopEvent, onDisconnect: noopEvent }}),
                onMessage: noopEvent,
                onStartup: noopEvent,
                onInstalled: noopEvent,
            }},
            storage: {{
                session: {{ get: async () => ({{}}), set: async () => ({{}}), remove: async () => ({{}}) }},
                local: {{
                    get: async (k) => ({{ [k]: store[k] }}),
                    set: async (obj) => Object.assign(store, obj),
                }},
            }},
            tabs: {{
                onCreated: noopEvent,
                onUpdated: noopEvent,
                onRemoved: noopEvent,
                onActivated: noopEvent,
                query: async () => [],
            }},
            tabGroups: {{
                onRemoved: noopEvent,
                onUpdated: noopEvent,
            }},
            debugger: {{
                onDetach: noopEvent,
                onEvent: noopEvent,
            }},
            alarms: {{
                create: () => {{}},
                onAlarm: noopEvent,
            }},
            proxy: {{
                settings: {{
                    clear: async (arg) => calls.push({{ op: "clear", arg }}),
                    set: async (arg) => calls.push({{ op: "set", arg }}),
                }},
            }},
        }},
    }};
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);
    (async () => {{
        await new Promise((r) => setImmediate(r));
        calls.length = 0;
        const emptyRes = await sandbox.applyProxySettings({{ proxyUrl: "", bypassDomains: ["*.lenovo.com"] }});
        const setRes = await sandbox.applyProxySettings({{ proxyUrl: "127.0.0.1:7890", bypassDomains: ["*.lenovo.com", "ccopyright.com.cn"] }});
        console.log(JSON.stringify({{ calls, emptyRes, setRes }}));
    }})();
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    # 1. Empty address -> clear proxy, nothing active even if bypassDomains has items
    assert out["emptyRes"]["active"] is False
    assert out["emptyRes"]["effectiveBypass"] == []
    assert out["calls"][0] == {"op": "clear", "arg": {"scope": "regular"}}

    # 2. Non-empty address -> set fixed_servers with singleProxy + merged bypassList
    assert out["setRes"]["active"] is True
    assert out["setRes"]["proxyUrl"] == "http://127.0.0.1:7890"
    assert "*.lenovo.com" in out["setRes"]["effectiveBypass"]
    assert "ccopyright.com.cn" in out["setRes"]["effectiveBypass"]
    assert "10.0.0.0/8" in out["setRes"]["effectiveBypass"]
    assert out["calls"][1]["op"] == "set"
    assert out["calls"][1]["arg"]["value"]["mode"] == "fixed_servers"
    assert out["calls"][1]["arg"]["value"]["rules"]["singleProxy"] == {
        "scheme": "http",
        "host": "127.0.0.1",
        "port": 7890,
    }


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


# ── Linux AppArmor userns sandbox fallback ──────────────────────────

def test_no_sandbox_omitted_when_sandbox_is_usable(launched, monkeypatch):
    monkeypatch.setattr(ext_mod, "linux_needs_no_sandbox", lambda _b: False)
    args = launched()
    assert "--no-sandbox" not in args
    assert "--test-type" not in args


def test_no_sandbox_added_when_linux_sandbox_blocked(launched, monkeypatch):
    monkeypatch.setattr(ext_mod, "linux_needs_no_sandbox", lambda _b: True)
    args = launched()
    assert "--no-sandbox" in args
    assert "--disable-setuid-sandbox" in args
    assert "--test-type" in args
    assert args[-1] == "about:blank"


def test_linux_needs_no_sandbox_probes_binary(monkeypatch, tmp_path):
    fake_bin = tmp_path / "chrome"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)

    monkeypatch.setattr(ext_mod._platform, "system", lambda: "Linux")
    monkeypatch.delenv("FRAGO_NO_SANDBOX", raising=False)
    monkeypatch.setattr(ext_mod, "_apparmor_restricts_userns", lambda: True)

    class ProcResult:
        def __init__(self, returncode: int, stderr: str) -> None:
            self.returncode = returncode
            self.stderr = stderr
            self.stdout = ""

    # Case 1: AppArmor profile allows userns -> probe exits 0 -> False
    monkeypatch.setattr(
        ext_mod.subprocess,
        "run",
        lambda *a, **k: ProcResult(0, ""),
    )
    assert ext_mod.linux_needs_no_sandbox(fake_bin) is False

    # Case 2: AppArmor blocks userns -> probe exits 133 with No usable sandbox -> True
    monkeypatch.setattr(
        ext_mod.subprocess,
        "run",
        lambda *a, **k: ProcResult(
            133,
            "FATAL:content/browser/zygote_host/zygote_host_impl_linux.cc:130] No usable sandbox!",
        ),
    )
    assert ext_mod.linux_needs_no_sandbox(fake_bin) is True

