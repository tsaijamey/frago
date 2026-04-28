"""CLI: ``frago extension`` — manage the browser extension bridge.

This module is the **frago side** of the bridge: daemon, native-host
relay, and the manifest installer that wires Chrome's native messaging
to frago's host process. The Chrome extension itself is an independent
project (``src/frago/_resources/extension_bundle/``) distributed via Chrome Web Store
and is **not** referenced from here.

Subcommands (P1):
    daemon        — long-running singleton multiplexer
    native-host   — relay stdio ↔ daemon (spawned by Chrome)
    install       — write native messaging manifest to Chrome's path
    status        — ping the daemon / bridge

For sideloading the unpacked bundle during extension development, use
``scripts/dev_launch_extension.py`` instead — that's a dev tool, not
part of the agent OS surface.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from ..chrome.extension import native_host as nh


_DEPRECATION_SHOWN = False

# MVP commands that were temporarily aliased under `frago extension`
# during P1; they now live on `frago chrome <cmd> --backend extension`
# and emit a deprecation notice when invoked via the legacy path.
_MVP_ALIASES = {"navigate", "exec-js", "get-content", "click", "screenshot"}


def _warn_if_mvp_alias(subcommand: str) -> None:
    """Emit deprecation notice for `frago extension <mvp-cmd>` usage."""
    global _DEPRECATION_SHOWN
    if _DEPRECATION_SHOWN or subcommand not in _MVP_ALIASES:
        return
    _DEPRECATION_SHOWN = True
    click.echo(
        f"[DEPRECATED] `frago extension {subcommand}` will be removed in P2. "
        f"Use `frago chrome {subcommand} --backend extension` instead.",
        err=True,
    )


@click.group(name="extension")
@click.pass_context
def extension_group(ctx):
    """Browser extension bridge management.

    P1.5: the MVP 6 commands (navigate/exec-js/get-content/click/
    screenshot) are now available on ``frago chrome`` via
    ``--backend extension``. These aliases remain for backwards
    compatibility and emit a deprecation notice when used.
    """
    sub = ctx.invoked_subcommand or ""
    _warn_if_mvp_alias(sub)


@extension_group.command("daemon")
@click.option("--sock", type=click.Path(path_type=Path), default=None)
def daemon_cmd(sock):
    """Run the native messaging daemon (singleton)."""
    sock_path = sock or nh.SOCK_PATH
    try:
        asyncio.run(nh.run_daemon(sock_path))
    except KeyboardInterrupt:
        pass


@extension_group.command("native-host")
@click.option("--sock", type=click.Path(path_type=Path), default=None)
def native_host_cmd(sock):
    """Stdio relay invoked by Chrome. Not meant to be run manually."""
    sock_path = sock or nh.SOCK_PATH
    try:
        asyncio.run(nh.run_relay(sock_path))
    except Exception as e:
        sys.stderr.write(f"[frago-extension-relay] error: {e}\n")
        sys.exit(1)


@extension_group.command("install")
@click.argument("extension_id", required=False)
@click.option("--executable", default=None,
              help="Absolute path to the native-host launcher. "
                   "Defaults to a wrapper script under ~/.frago/chrome/.")
@click.option("--browser", "-b", default=None,
              help="Target browser brand (edge, chromium, chrome, brave, "
                   "vivaldi, edge-beta, chrome-beta, chrome-dev, chrome-canary). "
                   "If unset, picks the highest-priority installed Chromium-class "
                   "browser. Determines which browser's NativeMessagingHosts/ "
                   "dir gets the manifest.")
@click.option("--target-dir", type=click.Path(path_type=Path), default=None,
              help="Override manifest install directory (advanced — typically "
                   "<user-data-dir>/NativeMessagingHosts/ when launching the "
                   "browser with --user-data-dir).")
def install_cmd(extension_id, executable, browser, target_dir):
    """Install the native messaging manifest.

    Picks the best-fit Chromium-class browser unless ``--browser`` is set,
    and writes the manifest into that browser's per-user
    ``NativeMessagingHosts/`` dir. Cross-OS aware (Linux + macOS).
    Windows is not yet supported (it uses registry-based registration).

    Defaults to the stable extension ID derived from the pinned pubkey
    that the published extension ships with. Override by passing an
    explicit ID (e.g. when sideloading a dev build whose key differs).
    """
    if not extension_id:
        extension_id = nh.STABLE_EXTENSION_ID
    frago_dir = Path.home() / ".frago" / "chrome"
    frago_dir.mkdir(parents=True, exist_ok=True)
    if not executable:
        # Generate a tiny launcher that invokes `frago extension native-host`.
        launcher = frago_dir / "native_host_launcher.sh"
        python_exe = sys.executable
        launcher.write_text(
            "#!/usr/bin/env bash\n"
            f"exec {python_exe} -m frago.cli.main extension native-host\n"
        )
        launcher.chmod(0o755)
        executable = str(launcher)

    # Resolve brand when caller didn't specify and didn't override target_dir.
    chosen_brand = browser
    if target_dir is None and chosen_brand is None:
        from ..chrome.backends.extension import pick_browser_for_extension
        choice = pick_browser_for_extension()
        if not choice:
            raise click.UsageError(
                "no Chromium-class browser detected; pass --browser <brand> "
                "or install Edge / Chromium / Chrome Beta+ / Brave / Vivaldi."
            )
        chosen_brand = choice.brand

    try:
        manifest_path = nh.install_manifest(
            executable, extension_id,
            target_dir=target_dir,
            brand=chosen_brand or "edge",
        )
    except (NotImplementedError, ValueError) as e:
        raise click.UsageError(str(e))

    click.echo(json.dumps({
        "manifest": str(manifest_path),
        "executable": executable,
        "extension_id": extension_id,
        "brand": chosen_brand,
    }, indent=2))


@extension_group.command("status")
def status_cmd():
    """Ping the daemon + bridge."""
    from ..chrome.backends.extension import ExtensionChromeBackend, ExtensionBackendError
    try:
        info = ExtensionChromeBackend().start()
        click.echo(json.dumps(info, indent=2, default=str))
    except ExtensionBackendError as e:
        click.echo(json.dumps({"ok": False, "code": e.code,
                               "error": str(e)}), err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo(json.dumps({"ok": False,
                               "error": "daemon not running; "
                               "start with `frago extension daemon`"}),
                   err=True)
        sys.exit(1)


# ═════════════════ MVP 6 commands via extension backend ═════════════════


def _be():
    from ..chrome.backends.extension import ExtensionChromeBackend
    return ExtensionChromeBackend()


def _dump(result):
    from dataclasses import asdict, is_dataclass
    return json.dumps(asdict(result) if is_dataclass(result) else result,
                      indent=2, ensure_ascii=False, default=str)


@extension_group.command("navigate")
@click.argument("url")
@click.option("--group", "-g", required=True)
@click.option("--timeout", type=float, default=15.0)
def navigate_cmd(url, group, timeout):
    click.echo(_dump(_be().navigate(url, group, timeout=timeout)))


@extension_group.command("exec-js")
@click.argument("script")
@click.option("--group", "-g", required=True)
def exec_js_cmd(script, group):
    click.echo(_dump(_be().exec_js(script, group)))


@extension_group.command("get-content")
@click.option("--group", "-g", required=True)
@click.option("--selector", default=None)
def get_content_cmd(group, selector):
    r = _be().get_content(group, selector=selector)
    click.echo(_dump(r))


@extension_group.command("click")
@click.argument("selector")
@click.option("--group", "-g", required=True)
def click_cmd(selector, group):
    click.echo(_dump(_be().click(selector, group)))


@extension_group.command("screenshot")
@click.argument("output", required=False, default=None)
@click.option("--group", "-g", required=True)
def screenshot_cmd(output, group):
    r = _be().screenshot(group, output=output)
    out = {"path": r.path, "tab_id": r.tab_id,
           "png_len": len(r.png_base64 or "")}
    click.echo(json.dumps(out, indent=2))
