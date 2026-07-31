"""browser command group - browser automation via extension bridge

Supports Edge, Chrome, Chromium, Brave, and Vivaldi browsers.
Default: Edge via extension bridge (Chrome Stable excluded, v137+
anti-sideload hardening blocks --load-extension).

Includes:
  - Lifecycle: start, stop, status, detect
  - Tab management: list-tabs, switch-tab, close-tab
  - Page operations: navigate, scroll, scroll-to, zoom, wait
  - Element interaction: click, exec-js, get-title, get-content
  - Visual effects: screenshot, highlight, pointer, spotlight, annotate, underline, clear-effects
"""

import functools
import os
from pathlib import Path

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup
from .commands import (
    annotate,
    browser_reset,
    browser_start,
    browser_stop,
    clear_effects,
    click_element,
    close_tab,
    execute_javascript,
    get_content,
    get_title,
    highlight,
    list_tabs,
    navigate,
    pointer,
    screenshot,
    scroll,
    scroll_to,
    spotlight,
    status,
    switch_tab,
    tab_group_cleanup,
    tab_group_close,
    tab_group_info,
    tab_groups,
    underline,
    wait,
    zoom,
)


@click.command('detect', cls=AgentFriendlyCommand)
@click.option('--group', '-g', default=None,
              help='Probe the group\'s current page for anti-bot challenges '
                   '(Cloudflare / captcha / block pages). Extension backend '
                   'only. Without --group, detects installed browsers.')
def detect_browsers(group):
    """
    Detect available browsers, or probe a page for anti-bot challenges

    Without --group: shows which Chromium-based browsers are installed
    and their paths (Chrome, Edge, Chromium).

    With --group (extension backend only): probes the group's current
    page for anti-bot challenges and returns structured JSON
    ({"challenge": bool, "type": ..., "needs_human": ...}).

    \b
    Examples:
      frago browser detect
      frago browser -b extension detect --group research
    """
    if group:
        raise click.UsageError(
            "anti-bot probe (--group) is only supported by the extension "
            "backend. Use: frago browser -b extension detect --group " + group)
    from ..browser.cdp.browser_detection import BrowserType, detect_available_browsers

    browsers = detect_available_browsers()

    click.echo("Available browsers:")
    click.echo()

    found_any = False
    for browser_type in [BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM]:
        path = browsers.get(browser_type)
        name = browser_type.value.title()

        if path:
            click.echo(f"  {name:10} ✓  {path}")
            found_any = True
        else:
            click.echo(f"  {name:10} ✗  not found")

    click.echo()

    if found_any:
        # Show which would be selected by default
        default_type = None
        for bt in [BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM]:
            if browsers.get(bt):
                default_type = bt
                break

        if default_type:
            click.echo(f"Default: {default_type.value} (first available)")
    else:
        click.echo("No supported browsers found.")
        click.echo("Please install Chrome, Edge, or Chromium.")


@click.group(name="browser", cls=AgentFriendlyGroup)
@click.option(
    "--backend", "-b",
    type=click.Choice(["cdp", "extension"], case_sensitive=False),
    default=None,
    help="Browser backend. Defaults to env FRAGO_BROWSER_BACKEND or "
         "'extension' (browser extension + native messaging, drives the "
         "browser's own profile). 'cdp' is retained for legacy flows and "
         "must be selected explicitly.",
)
@click.pass_context
def browser_group(ctx, backend):
    """
    Browser automation

    Control the browser through the frago extension bridge (default
    backend), using the browser's own real profile. CDP remains
    available via an explicit -b cdp.

    \b
    Subcommand categories:
      Lifecycle:     start, stop, status
      Tab management: list-tabs, switch-tab, close-tab
      Page operations: navigate, scroll, scroll-to, zoom, wait
      Element interaction: click, exec-js, get-title, get-content
      Visual effects: screenshot, highlight, pointer, spotlight, ...

    \b
    Examples:
      frago browser start                              # Start browser
      frago browser navigate https://... --group r     # Navigate
      frago browser get-content --group r              # Get content
      frago browser click --group r "#button"          # Click
      frago browser groups                             # List groups
    """
    chosen = (backend or os.environ.get("FRAGO_BROWSER_BACKEND") or "extension").lower()
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj["BACKEND"] = chosen

    # Single registration point for the end-of-process expired-group
    # fallback sweep (runs after the command's output is done).
    from .commands import _register_expiry_sweep
    _register_expiry_sweep(
        ctx.obj.get("HOST", "127.0.0.1"), ctx.obj.get("PORT", 9222)
    )


# ─────────────── Backend dispatch shim for MVP 6 commands ───────────────
#
# When --backend extension is in effect, reroute MVP commands to the
# extension backend (the same implementation used by `frago extension
# <cmd>`). All other commands continue to go through CDP; selecting
# --backend extension on a non-MVP command is a no-op (falls through to
# CDP so existing behavior is preserved).
MVP_COMMANDS = {"navigate", "exec-js", "get-content", "click",
                "screenshot", "start"}

# P2 Batch 1 — tab management + simple element operations.
# These also honor --backend extension (dispatched in _dispatch_extension).
BATCH1_COMMANDS = {"stop", "status", "list-tabs", "switch-tab", "close-tab",
                   "groups", "group-info", "group-close", "group-cleanup",
                   "reset", "scroll", "scroll-to", "zoom", "get-title"}

# P2 Batch 2 — backend-agnostic local ops. Surface-only alignment:
# both backends inherit identical ABC implementations (time.sleep /
# PATH scan).
BATCH2_COMMANDS = {"wait", "detect"}

# P3.1 / I — visual effects on the page. CDP and extension both inject
# the same JS (DOM manipulation, no CDP-specific protocol calls), so
# the dispatch shape mirrors MVP: --backend extension → SW RPC; default
# CDP → original handler in commands.py uses cdp/session directly.
VISUAL_COMMANDS = {"highlight", "pointer", "spotlight", "annotate",
                   "underline", "clear-effects"}


def _ext_backend():
    from ..browser.backends.extension import ExtensionChromeBackend
    return ExtensionChromeBackend()


def _dispatch_extension(name: str, kwargs: dict) -> None:
    """Run the MVP command against the extension backend and echo JSON."""
    import json
    from dataclasses import asdict, is_dataclass
    be = _ext_backend()
    group = kwargs.get("group") or os.environ.get("FRAGO_CURRENT_RUN")
    # Management-class commands don't need a group.
    NO_GROUP = {"start", "stop", "status", "list-tabs", "switch-tab",
                "close-tab", "groups", "group-info", "group-close",
                "group-cleanup", "reset", "wait", "detect"}
    if name == "start":
        # Full bridge bring-up: pick browser, ensure daemon, install
        # manifest, launch browser, wait for handshake.
        from dataclasses import asdict

        from ..browser.extension.lifecycle import (
            BridgeStartupResult,
            start_extension_bridge,
        )

        # CDP's --browser option uses "auto" to mean "let frago pick";
        # extension picker uses None for the same intent. Translate.
        # Also: CDP-only options (headless, port, void, profile_dir, ...)
        # are silently ignored — extension backend manages its own profile
        # and doesn't need a debugging port.
        brand = kwargs.get("browser")
        if brand in (None, "", "auto"):
            brand = None
        if brand is not None:
            raise click.UsageError(
                f"--browser {brand} has no effect on this backend and is "
                f"unsafe: the browser that launches is chosen automatically, "
                f"and --browser would only point the profile directory at "
                f"{brand}, driving the launched browser against {brand}'s "
                f"profile. Run `frago browser start` with no options; use "
                f"`frago browser check` to see which browsers are available."
            )

        try:
            result: BridgeStartupResult = start_extension_bridge(
                browser=brand,
                reseed_profile=bool(kwargs.get("reseed_profile")),
            )
        except (RuntimeError, TimeoutError) as e:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
            raise click.exceptions.Exit(1) from e
        click.echo(json.dumps(asdict(result), indent=2, default=str))
        return
    if name not in NO_GROUP and not group:
        raise click.UsageError("--group/-g required (no FRAGO_CURRENT_RUN)")
    if name == "navigate":
        r = be.navigate(kwargs["url"], group,
                        timeout=float(kwargs.get("load_timeout") or
                                      kwargs.get("timeout") or 15.0))
    elif name == "exec-js":
        r = be.exec_js(kwargs["script"], group)
    elif name == "get-content":
        r = be.get_content(group, selector=kwargs.get("selector"))
    elif name == "click":
        r = be.click(kwargs["selector"], group)
    elif name == "screenshot":
        r = be.screenshot(group, output=kwargs.get("output_file") or
                          kwargs.get("output"))
        # With an output path the PNG is already on disk — echoing the
        # base64 payload too would dump hundreds of KB into stdout (and
        # into an agent's context). Emit a small summary instead.
        if r.path:
            from pathlib import Path as _Path
            click.echo(json.dumps({
                "path": r.path,
                "bytes": _Path(r.path).stat().st_size,
                "tab_id": r.tab_id,
            }, indent=2, ensure_ascii=False))
            return
    # ─── Batch 1 ────────────────────────────────────────────────────
    elif name == "stop":
        # Mirror of `start`: tear down browser + daemon + socket.
        # CDP-only kwargs (--port etc.) are silently ignored.
        from dataclasses import asdict

        from ..browser.extension.lifecycle import (
            BridgeStopResult,
            stop_extension_bridge,
        )
        try:
            stop_result: BridgeStopResult = stop_extension_bridge()
        except Exception as e:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
            raise click.exceptions.Exit(1) from e
        click.echo(json.dumps(asdict(stop_result), indent=2, default=str))
        return
    elif name == "status":
        r = be.status()
    elif name == "list-tabs":
        r = {"tabs": be.list_tabs()}
    elif name == "switch-tab":
        r = be.switch_tab(kwargs["tab_id"])
    elif name == "close-tab":
        r = be.close_tab(kwargs["tab_id"])
    elif name == "groups":
        r = {"groups": be.list_groups()}
    elif name == "group-info":
        r = be.group_info(kwargs["group_name"])
    elif name == "group-close":
        r = be.group_close(kwargs["group_name"])
    elif name == "group-cleanup":
        r = be.group_cleanup()
    elif name == "reset":
        r = be.reset(group or None)
    elif name == "scroll":
        if not group:
            raise click.UsageError("--group required")
        r = be.scroll(int(kwargs["distance"]), group)
    elif name == "scroll-to":
        if not group:
            raise click.UsageError("--group required")
        r = be.scroll_to(group, selector=kwargs.get("selector"),
                         text=kwargs.get("text"),
                         block=kwargs.get("block") or "center")
    elif name == "zoom":
        if not group:
            raise click.UsageError("--group required")
        r = be.zoom(float(kwargs["factor"]), group)
    elif name == "get-title":
        if not group:
            raise click.UsageError("--group required")
        r = {"title": be.get_title(group)}
    # ─── Batch 2 (backend-agnostic local) ────────────────────────────
    elif name == "wait":
        r = be.wait(float(kwargs["seconds"]))
    elif name == "detect":
        # --group switches semantics: anti-bot probe of the group's
        # current page (extension-only). Without --group, keep the
        # browser-detection meaning shared with CDP. Deliberately no
        # FRAGO_CURRENT_RUN fallback — the probe must be explicit.
        probe_group = kwargs.get("group")
        r = be.detect_anti_bot(probe_group) if probe_group else be.detect()
    # ─── Visual effects (I) ──────────────────────────────────────────
    # Convert CLI's (life_time seconds, longlife flag) to lifetime ms.
    elif name in VISUAL_COMMANDS:
        if not group:
            raise click.UsageError("--group required")
        longlife = bool(kwargs.get("longlife"))
        lifetime_ms = 0 if longlife else int(kwargs.get("life_time", 5)) * 1000
        if name == "highlight":
            r = be.highlight(kwargs["selector"], group,
                             color=kwargs.get("color", "magenta"),
                             border_width=int(kwargs.get("width", 3)),
                             lifetime=lifetime_ms)
        elif name == "pointer":
            r = be.pointer(kwargs["selector"], group, lifetime=lifetime_ms)
        elif name == "spotlight":
            r = be.spotlight(kwargs["selector"], group, lifetime=lifetime_ms)
        elif name == "annotate":
            r = be.annotate(kwargs["selector"], kwargs["text"], group,
                            position=kwargs.get("position", "top"),
                            lifetime=lifetime_ms)
        elif name == "underline":
            # underline takes selector OR text — extension impl currently
            # only handles selector. If only text given, error out clearly.
            if not kwargs.get("selector"):
                raise click.UsageError(
                    "extension backend's underline requires --selector "
                    "(text-only matching is CDP-only for now)")
            r = be.underline(kwargs["selector"], group,
                             color=kwargs.get("color", "magenta"),
                             width=int(kwargs.get("width", 3)),
                             duration=int(kwargs.get("duration", 1000)))
        elif name == "clear-effects":
            r = be.clear_effects(group)
        else:
            raise click.UsageError(f"unhandled visual command: {name}")
    else:
        raise click.UsageError(f"backend=extension: {name} unsupported")
    click.echo(json.dumps(asdict(r) if is_dataclass(r) else r,
                          indent=2, default=str, ensure_ascii=False))


def _dispatch_extension_safe(name: str, kwargs: dict) -> None:
    """Dispatch to the extension backend, converting transport-layer
    failures (bridge down, socket missing) into structured JSON errors
    instead of raw tracebacks. Single choke point — individual commands
    stay try/except-free."""
    import json

    from ..browser.backends.extension import ExtensionBackendError
    try:
        return _dispatch_extension(name, kwargs)
    except ExtensionBackendError as e:
        err = {"ok": False, "code": e.code, "error": str(e),
               "hint": "run: frago browser start"}
    except FileNotFoundError as e:
        err = {"ok": False, "code": "socket-not-found",
               "error": f"bridge socket not found: {e}",
               "hint": "run: frago browser start"}
    except (ConnectionRefusedError, ConnectionResetError, TimeoutError) as e:
        err = {"ok": False, "code": "bridge-unreachable",
               "error": f"{type(e).__name__}: {e}",
               "hint": "run: frago browser start"}
    click.echo(json.dumps(err, indent=2, ensure_ascii=False))
    raise click.exceptions.Exit(1)


def _wrap_mvp(cmd, name: str):
    """Wrap a click command so --backend extension reroutes to extension."""
    orig = cmd.callback

    @functools.wraps(orig)
    @click.pass_context
    def wrapped(ctx, *args, **kwargs):
        backend = (ctx.obj or {}).get("BACKEND", "extension")
        if backend == "extension":
            return _dispatch_extension_safe(name, kwargs)
        # orig is the existing click callback. When it was decorated with
        # @click.pass_context, orig is a new_func that pulls ctx via
        # get_current_context() itself; passing ctx explicitly here would
        # collide with the first declared positional argument (e.g. `url`).
        # When it has no pass_context, orig is the bare callback and never
        # wants ctx. In both cases the right thing is to forward kwargs.
        return orig(*args, **kwargs)

    cmd.callback = wrapped
    return cmd


# Lifecycle
browser_group.add_command(_wrap_mvp(browser_start, "start"), name="start")
browser_group.add_command(_wrap_mvp(browser_stop, "stop"), name="stop")
browser_group.add_command(_wrap_mvp(status, "status"), name="status")
browser_group.add_command(_wrap_mvp(detect_browsers, "detect"), name="detect")

# check is a pure diagnostic — no backend dispatch needed
@browser_group.command(name="check", cls=AgentFriendlyCommand)
def check_browsers():
    """Check which browsers are available and their status for frago automation.

    \b
    Columns:
      BROWSER   — browser name and brand
      AVAILABLE — ✓ installed, ✗ not found
      BACKEND   — extension (ext), CDP (cdp), or both
      RUNNING   — whether the browser process is currently running

    \b
    Example:
      frago browser check
    """
    import platform as _platform
    import subprocess

    system = _platform.system()

    # ── Process check helper ────────────────────────────────────────
    def _is_running(proc_names: list[str]) -> bool:
        for name in proc_names:
            try:
                if system in ("Darwin", "Linux"):
                    r = subprocess.run(
                        ["pgrep", "-f", name], capture_output=True, text=True, timeout=3)
                    if r.returncode == 0 and r.stdout.strip():
                        return True
                elif system == "Windows":
                    r = subprocess.run(
                        ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                        capture_output=True, text=True, timeout=5)
                    if name.lower() in r.stdout.lower():
                        return True
            except Exception:
                pass
        return False

    # ── Backend support ─────────────────────────────────────────────
    from ..browser.backends.extension import list_browsers_for_extension
    from ..browser.cdp.browser_detection import BrowserType
    from ..browser.cdp.browser_detection import detect_available_browsers as cdp_available

    cdp_map = cdp_available()
    ext_list = list_browsers_for_extension()

    # ── Browser catalogue ───────────────────────────────────────────
    _CHROME_STABLE_PATH = _CHROME_BETA_PATH = _CHROME_DEV_PATH = ""
    _CHROME_CANARY_PATH = _EDGE_PATH = _EDGE_BETA_PATH = _EDGE_DEV_PATH = ""
    _CHROMIUM_PATH = _BRAVE_PATH = _VIVALDI_PATH = ""

    for bc in ext_list:
        if bc.brand == "chrome-beta":
            _CHROME_BETA_PATH = bc.path
        elif bc.brand == "chrome-dev":
            _CHROME_DEV_PATH = bc.path
        elif bc.brand == "chrome-canary":
            _CHROME_CANARY_PATH = bc.path
        elif bc.brand == "edge":
            _EDGE_PATH = bc.path
        elif bc.brand == "edge-beta":
            _EDGE_BETA_PATH = bc.path
        elif bc.brand == "edge-dev":
            _EDGE_DEV_PATH = bc.path
        elif bc.brand == "chromium":
            _CHROMIUM_PATH = bc.path
        elif bc.brand == "brave":
            _BRAVE_PATH = bc.path
        elif bc.brand == "vivaldi":
            _VIVALDI_PATH = bc.path

    # Chrome Stable is excluded from extension list, check CDP
    chrome_cdp = cdp_map.get(BrowserType.CHROME)
    if chrome_cdp:
        _CHROME_STABLE_PATH = chrome_cdp

    # Extension detection misses Edge/Chromium if only CDP found them
    if not _EDGE_PATH and cdp_map.get(BrowserType.EDGE):
        _EDGE_PATH = cdp_map[BrowserType.EDGE]
    if not _CHROMIUM_PATH and cdp_map.get(BrowserType.CHROMIUM):
        _CHROMIUM_PATH = cdp_map[BrowserType.CHROMIUM]

    # ── Build rows ──────────────────────────────────────────────────
    rows: list[dict] = []

    def _add(name: str, path: str, ext_ok: bool, cdp_ok: bool,
             proc_names: list[str]):
        if path:
            available = "✓"
            running = "✓" if _is_running(proc_names) else "—"
            backends = []
            if ext_ok:
                backends.append("ext")
            if cdp_ok:
                backends.append("cdp")
            backend = "/".join(backends)
        else:
            available = "✗"
            running = "—"
            backends = []
            if ext_ok:
                backends.append("ext")
            if cdp_ok:
                backends.append("cdp")
            backend = "/".join(backends) if backends else "—"
        rows.append({
            "browser": name,
            "available": available,
            "backend": backend,
            "running": running,
        })

    # Format: (display_name, path, ext_ok, cdp_ok, proc_names)
    _add("Chrome",          _CHROME_STABLE_PATH, False, True,  ["Google Chrome", "chrome.exe"])
    _add("Chrome Beta",     _CHROME_BETA_PATH,   True,  True,  ["Google Chrome Beta", "chrome.exe"])
    _add("Chrome Dev",      _CHROME_DEV_PATH,    True,  True,  ["Google Chrome Dev", "chrome.exe"])
    _add("Chrome Canary",   _CHROME_CANARY_PATH, True,  True,  ["Google Chrome Canary", "chrome.exe"])
    _add("Edge",            _EDGE_PATH,          True,  True,  ["Microsoft Edge", "msedge.exe"])
    _add("Edge Beta",       _EDGE_BETA_PATH,     True,  True,  ["Microsoft Edge Beta", "msedge.exe"])
    _add("Edge Dev",        _EDGE_DEV_PATH,      True,  True,  ["Microsoft Edge Dev", "msedge.exe"])
    _add("Chromium",        _CHROMIUM_PATH,      True,  True,  ["Chromium", "chrome.exe"])
    _add("Brave",           _BRAVE_PATH,         True,  True,  ["Brave Browser", "brave.exe"])
    _add("Vivaldi",         _VIVALDI_PATH,       True,  True,  ["Vivaldi", "vivaldi.exe"])

    # ── Format table ────────────────────────────────────────────────
    bw = max(len(r["browser"]) for r in rows) + 2
    aw = 10
    be = 8
    rw = 8

    header = f"{'BROWSER':<{bw}} {'AVAILABLE':<{aw}} {'BACKEND':<{be}} {'RUNNING':<{rw}}"
    sep = f"{'─'*bw} {'─'*aw} {'─'*be} {'─'*rw}"

    lines = [header, sep]
    for r in rows:
        lines.append(
            f"{r['browser']:<{bw}} "
            f"{r['available']:<{aw}} "
            f"{r['backend']:<{be}} "
            f"{r['running']:<{rw}}"
        )

    # Determine default
    from ..browser.backends.extension import pick_browser_for_extension
    default_choice = pick_browser_for_extension()
    if default_choice:
        lines.append("")
        lines.append(f"Default: {default_choice.brand} ({default_choice.path})")

    click.echo("\n".join(lines))

# Tab management
browser_group.add_command(_wrap_mvp(list_tabs, "list-tabs"), name="list-tabs")
browser_group.add_command(_wrap_mvp(switch_tab, "switch-tab"), name="switch-tab")
browser_group.add_command(_wrap_mvp(close_tab, "close-tab"), name="close-tab")

# Page operations
browser_group.add_command(_wrap_mvp(navigate, "navigate"), name="navigate")
browser_group.add_command(_wrap_mvp(scroll, "scroll"), name="scroll")
browser_group.add_command(_wrap_mvp(scroll_to, "scroll-to"), name="scroll-to")
browser_group.add_command(_wrap_mvp(zoom, "zoom"), name="zoom")
browser_group.add_command(_wrap_mvp(wait, "wait"), name="wait")

# Element interaction
browser_group.add_command(_wrap_mvp(click_element, "click"), name="click")
browser_group.add_command(_wrap_mvp(execute_javascript, "exec-js"), name="exec-js")
browser_group.add_command(_wrap_mvp(get_title, "get-title"), name="get-title")
browser_group.add_command(_wrap_mvp(get_content, "get-content"), name="get-content")

# Tab groups
browser_group.add_command(_wrap_mvp(tab_groups, "groups"), name="groups")
browser_group.add_command(_wrap_mvp(tab_group_info, "group-info"), name="group-info")
browser_group.add_command(_wrap_mvp(tab_group_close, "group-close"), name="group-close")
browser_group.add_command(_wrap_mvp(tab_group_cleanup, "group-cleanup"),
                         name="group-cleanup")
browser_group.add_command(_wrap_mvp(browser_reset, "reset"), name="reset")

# Visual effects
browser_group.add_command(_wrap_mvp(screenshot, "screenshot"), name="screenshot")
browser_group.add_command(_wrap_mvp(highlight, "highlight"), name="highlight")
browser_group.add_command(_wrap_mvp(pointer, "pointer"), name="pointer")
browser_group.add_command(_wrap_mvp(spotlight, "spotlight"), name="spotlight")
browser_group.add_command(_wrap_mvp(annotate, "annotate"), name="annotate")
browser_group.add_command(_wrap_mvp(underline, "underline"), name="underline")
browser_group.add_command(_wrap_mvp(clear_effects, "clear-effects"), name="clear-effects")


# ─────────────── capture（P4）：extension 后端专属 ───────────────
#
# 录制/帧流发生在扩展驱动的浏览器里（debugger + tabCapture 权限），
# 不拉起任何新浏览器实例、不产生任何新 profile。
#
# 【已开发，暂不启用】实现完整并实测通过（见 ExtensionChromeBackend.record_tab），
# 但当前 agent_os 走 CDP 后端采集画面，这条入口不投入使用。
# 命令注册已注释：`frago browser record-tab` 会得到 click 的 "No such command"
# 标准错误，与其它未注册命令表现一致，不做半可用状态。
# 启用方式：取消下面 @browser_group.command 一行的注释。
# @browser_group.command(name="record-tab")
@click.argument("output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--group", "-g", default=None, help="tab group（缺省读 FRAGO_CURRENT_RUN）")
@click.option("--tab-id", type=int, default=None, help="直接指定 tabId")
@click.option("--duration", "-d", type=float, default=10.0,
              help="录制时长（秒），默认 10")
@click.pass_context
def record_tab(ctx, output: Path, group, tab_id, duration):
    """把一个 tab 录成 webm（扩展 tabCapture，零新实例零新 profile）。"""
    import json as _json

    if (ctx.obj or {}).get("BACKEND") == "cdp":
        raise click.ClickException("record-tab 只在 extension 后端可用")
    group = group or os.environ.get("FRAGO_CURRENT_RUN")
    if not group and tab_id is None:
        raise click.ClickException("需要 --group 或 --tab-id")
    from ..browser.backends.extension import ExtensionChromeBackend
    be = ExtensionChromeBackend()
    result = be.record_tab(output.expanduser().resolve(), group=group,
                           tab_id=tab_id, duration=duration)
    click.echo(_json.dumps(result, ensure_ascii=False))
