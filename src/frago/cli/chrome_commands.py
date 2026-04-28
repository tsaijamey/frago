"""chrome command group - Chromium-based browser CDP automation

Supports Chrome, Edge, and Chromium browsers via Chrome DevTools Protocol.

Includes:
  - Lifecycle: start, stop, status, detect
  - Tab management: list-tabs, switch-tab, close-tab
  - Page operations: navigate, scroll, scroll-to, zoom, wait
  - Element interaction: click, exec-js, get-title, get-content
  - Visual effects: screenshot, highlight, pointer, spotlight, annotate, underline, clear-effects
"""

import functools
import os

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup
from .commands import (
    annotate,
    chrome_reset,
    chrome_start,
    chrome_stop,
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
def detect_browsers():
    """
    Detect available browsers on the system

    Shows which Chromium-based browsers are installed and their paths.
    Supports Chrome, Edge, and Chromium.

    \b
    Examples:
      frago chrome detect
    """
    from ..chrome.cdp.commands.chrome import BrowserType, detect_available_browsers

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


@click.group(name="chrome", cls=AgentFriendlyGroup)
@click.option(
    "--backend", "-b",
    type=click.Choice(["cdp", "extension"], case_sensitive=False),
    default=None,
    help="Browser backend. Defaults to env FRAGO_CHROME_BACKEND or 'cdp'. "
         "Extension backend supports MVP 6 (navigate, exec-js, get-content, "
         "click, screenshot, start) + Batch 1 (stop, status, list-tabs, "
         "switch-tab, close-tab, groups, group-info, group-close, "
         "group-cleanup, reset, scroll, scroll-to, zoom, get-title) + "
         "Batch 2 (wait, detect — local ops, identical across backends) "
         "+ Visual effects (highlight, pointer, spotlight, annotate, "
         "underline, clear-effects).",
)
@click.pass_context
def chrome_group(ctx, backend):
    """
    Chrome CDP browser automation

    Control browser through Chrome DevTools Protocol.

    \b
    Subcommand categories:
      Lifecycle:     start, stop, status
      Tab management: list-tabs, switch-tab, close-tab
      Page operations: navigate, scroll, scroll-to, zoom, wait
      Element interaction: click, exec-js, get-title, get-content
      Visual effects: screenshot, highlight, pointer, spotlight, ...

    \b
    Examples:
      frago chrome start                    # Start Chrome
      frago chrome navigate https://... --group research  # Navigate
      frago chrome get-content --group research            # Get content
      frago chrome click --group research "#button"        # Click
      frago chrome groups                                  # List groups
    """
    chosen = (backend or os.environ.get("FRAGO_CHROME_BACKEND") or "cdp").lower()
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj["BACKEND"] = chosen


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
    from ..chrome.backends.extension import ExtensionChromeBackend
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
        from ..chrome.extension.lifecycle import (
            BridgeStartupResult, start_extension_bridge,
        )
        from dataclasses import asdict

        # CDP's --browser option uses "auto" to mean "let frago pick";
        # extension picker uses None for the same intent. Translate.
        # Also: CDP-only options (headless, port, void, profile_dir, ...)
        # are silently ignored — extension backend manages its own profile
        # and doesn't need a debugging port.
        brand = kwargs.get("browser")
        if brand in (None, "", "auto"):
            brand = None

        try:
            result: BridgeStartupResult = start_extension_bridge(browser=brand)
        except (RuntimeError, TimeoutError) as e:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
            raise click.exceptions.Exit(1)
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
    # ─── Batch 1 ────────────────────────────────────────────────────
    elif name == "stop":
        # Mirror of `start`: tear down browser + daemon + socket.
        # CDP-only kwargs (--port etc.) are silently ignored.
        from ..chrome.extension.lifecycle import (
            BridgeStopResult, stop_extension_bridge,
        )
        from dataclasses import asdict
        try:
            stop_result: BridgeStopResult = stop_extension_bridge()
        except Exception as e:
            click.echo(json.dumps({"ok": False, "error": str(e)}), err=True)
            raise click.exceptions.Exit(1)
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
        r = be.detect()
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


def _wrap_mvp(cmd, name: str):
    """Wrap a click command so --backend extension reroutes to extension."""
    orig = cmd.callback

    @functools.wraps(orig)
    @click.pass_context
    def wrapped(ctx, *args, **kwargs):
        backend = (ctx.obj or {}).get("BACKEND", "cdp")
        if backend == "extension":
            return _dispatch_extension(name, kwargs)
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
chrome_group.add_command(_wrap_mvp(chrome_start, "start"), name="start")
chrome_group.add_command(_wrap_mvp(chrome_stop, "stop"), name="stop")
chrome_group.add_command(_wrap_mvp(status, "status"), name="status")
chrome_group.add_command(_wrap_mvp(detect_browsers, "detect"), name="detect")

# Tab management
chrome_group.add_command(_wrap_mvp(list_tabs, "list-tabs"), name="list-tabs")
chrome_group.add_command(_wrap_mvp(switch_tab, "switch-tab"), name="switch-tab")
chrome_group.add_command(_wrap_mvp(close_tab, "close-tab"), name="close-tab")

# Page operations
chrome_group.add_command(_wrap_mvp(navigate, "navigate"), name="navigate")
chrome_group.add_command(_wrap_mvp(scroll, "scroll"), name="scroll")
chrome_group.add_command(_wrap_mvp(scroll_to, "scroll-to"), name="scroll-to")
chrome_group.add_command(_wrap_mvp(zoom, "zoom"), name="zoom")
chrome_group.add_command(_wrap_mvp(wait, "wait"), name="wait")

# Element interaction
chrome_group.add_command(_wrap_mvp(click_element, "click"), name="click")
chrome_group.add_command(_wrap_mvp(execute_javascript, "exec-js"), name="exec-js")
chrome_group.add_command(_wrap_mvp(get_title, "get-title"), name="get-title")
chrome_group.add_command(_wrap_mvp(get_content, "get-content"), name="get-content")

# Tab groups
chrome_group.add_command(_wrap_mvp(tab_groups, "groups"), name="groups")
chrome_group.add_command(_wrap_mvp(tab_group_info, "group-info"), name="group-info")
chrome_group.add_command(_wrap_mvp(tab_group_close, "group-close"), name="group-close")
chrome_group.add_command(_wrap_mvp(tab_group_cleanup, "group-cleanup"),
                         name="group-cleanup")
chrome_group.add_command(_wrap_mvp(chrome_reset, "reset"), name="reset")

# Visual effects
chrome_group.add_command(_wrap_mvp(screenshot, "screenshot"), name="screenshot")
chrome_group.add_command(_wrap_mvp(highlight, "highlight"), name="highlight")
chrome_group.add_command(_wrap_mvp(pointer, "pointer"), name="pointer")
chrome_group.add_command(_wrap_mvp(spotlight, "spotlight"), name="spotlight")
chrome_group.add_command(_wrap_mvp(annotate, "annotate"), name="annotate")
chrome_group.add_command(_wrap_mvp(underline, "underline"), name="underline")
chrome_group.add_command(_wrap_mvp(clear_effects, "clear-effects"), name="clear-effects")
