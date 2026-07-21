"""Frago server command group - Background web service management.

Provides commands to start, stop, and check status of the Frago
web service running as a background daemon process.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

# Sentinel preventing infinite recursion: the re-exec'd system frago sees it
# and skips the reinstall branch.
REINSTALL_SENTINEL_ENV = "FRAGO_REINSTALL_DONE"


def _bump_patch_version(pyproject: Path) -> str:
    """Increment the patch segment of `version = "x.y.z"` in pyproject.toml.

    Rewrites only the version line, leaving the rest of the file untouched.
    Returns the new version string. Raises ClickException when the version is
    not a plain three-segment x.y.z number.
    """
    text = pyproject.read_text(encoding="utf-8")
    pattern = re.compile(r'^(version\s*=\s*")([^"]+)(")', flags=re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise click.ClickException(f"No version line found in {pyproject}")
    current = match.group(2)
    parts = current.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise click.ClickException(
            f"Version {current!r} in {pyproject} is not a plain x.y.z number; "
            "refusing to guess."
        )
    new_version = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
    text = text[: match.start(2)] + new_version + text[match.end(2) :]
    pyproject.write_text(text, encoding="utf-8")
    return new_version


def _system_frago_path(checkout_root: Path) -> str | None:
    """Find the system-installed frago on PATH, skipping the repo venv's own.

    Under `uv run` the repo's .venv/bin is prepended to PATH, so a plain
    shutil.which("frago") would loop back into the checkout. Walk PATH entries
    and return the first frago that lives outside the source checkout.
    """
    root = checkout_root.resolve()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry) / "frago"
        if not (candidate.is_file() and os.access(candidate, os.X_OK)):
            continue
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            return str(candidate)
    return None


def _reinstall_and_exec_if_source_checkout() -> None:
    """From a source checkout: build + install the repo as the system frago, then exec it.

    The repo venv's frago must never be the server runtime. When the CLI runs
    from inside the frago source tree, bump the patch version, build a wheel,
    `uv tool install --force` it, and hand the original argv over to the
    system-installed frago via os.execv. No-op on a global/uv-tool install or
    when the reinstall sentinel is already set (we ARE the re-exec'd process).
    """
    if os.environ.get(REINSTALL_SENTINEL_ENV) == "1":
        return
    from frago.server.launch_guard import source_checkout_root

    root = source_checkout_root()
    if root is None:
        return  # already the system install — nothing to do

    new_version = _bump_patch_version(root / "pyproject.toml")
    click.echo(f"[reinstall] source checkout detected at {root}")
    click.echo(f"[reinstall] bumped version to {new_version}")

    with tempfile.TemporaryDirectory(prefix="frago-wheel-") as tmpdir:
        click.echo(f"[reinstall] building wheel ({new_version}) ...")
        build = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", tmpdir],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            raise click.ClickException(f"uv build failed:\n{build.stderr.strip()}")

        wheels = sorted(Path(tmpdir).glob("*.whl"))
        if not wheels:
            raise click.ClickException(f"uv build produced no wheel in {tmpdir}")
        wheel = wheels[-1]

        click.echo(f"[reinstall] installing {wheel.name} via uv tool install --force ...")
        install = subprocess.run(
            ["uv", "tool", "install", "--force", str(wheel)],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            raise click.ClickException(
                f"uv tool install failed:\n{install.stderr.strip()}"
            )

    system_frago = _system_frago_path(root)
    if system_frago is None:
        raise click.ClickException(
            "System frago not found on PATH after uv tool install; "
            "check that ~/.local/bin is on PATH."
        )

    args = [system_frago, *sys.argv[1:]]
    click.echo(f"[reinstall] handing over to system frago: {' '.join(args)}")
    os.environ[REINSTALL_SENTINEL_ENV] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(system_frago, args)


def _guard_sub_agent(action: str) -> None:
    """Block server stop/restart when called from a sub-agent.

    Sub-agent processes inherit FRAGO_CURRENT_RUN env var.
    Server shutdown kills all child processes (including the sub-agent itself),
    causing the task to abort without completion markers.
    """
    run_id = os.environ.get("FRAGO_CURRENT_RUN")
    if run_id:
        raise click.ClickException(
            f"sub-agent (Run {run_id}) 禁止 {action} server — "
            "server shutdown 会杀掉自身进程。"
            "如需重启，请通过 TASK_COMPLETE 回报 PA 调度执行。"
        )


def _guard_active_tasks(force: bool, action: str) -> None:
    """Block stop/restart when active tasks are running (unless --force)."""
    from frago.server.daemon import check_active_tasks, force_cleanup_active_tasks

    report = check_active_tasks()
    if not report["has_active"]:
        return

    if not force:
        click.echo(f"Cannot {action} server: active tasks are running.\n")
        click.echo(report["message"])
        click.echo(f"\nUse --force to {action} anyway (tasks will be marked FAILED).")
        raise SystemExit(1)

    # --force: cleanup before proceeding
    click.echo(f"Force {action}: cleaning up active tasks...")
    force_cleanup_active_tasks(report)
    click.echo("Active tasks cleaned up.")


@click.group("server", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.option(
    "--debug",
    is_flag=True,
    help="Run in foreground with verbose logging (instead of background daemon)",
)
@click.pass_context
def server_group(ctx: click.Context, debug: bool) -> None:
    """Manage the Frago web service.

    By default, starts the server as a background daemon process
    on port 8093. Use --debug to run in foreground mode.

    \b
    Examples:
        frago server              # Start in background
        frago server --debug      # Start in foreground with logs
        frago server stop         # Stop the running server
        frago server restart      # Restart the server
        frago server status       # Check server status

    \b
    The server binds to 127.0.0.1:8093 (localhost only for security).
    Access the GUI at: http://127.0.0.1:8093
    """
    # If no subcommand is invoked, default to starting the server
    if ctx.invoked_subcommand is None:
        ctx.invoke(start, debug=debug)


@server_group.command("start", cls=AgentFriendlyCommand)
@click.option(
    "--debug",
    is_flag=True,
    help="Run in foreground with verbose logging",
)
def start(debug: bool) -> None:
    """Start the Frago web service.

    Without --debug: Starts as background daemon, returns to prompt immediately.
    With --debug: Runs in foreground showing live logs (press Ctrl+C to stop).

    When run from inside the frago source checkout, the repo is first built
    and installed as the system frago (uv tool install --force), then the
    command is handed over to that system install.
    """
    _reinstall_and_exec_if_source_checkout()
    if debug:
        # Foreground mode with verbose logging
        _run_foreground()
    else:
        # Background daemon mode
        _run_background()


def _run_background() -> None:
    """Start server as background daemon."""
    from frago.server.daemon import start_daemon

    success, message = start_daemon()
    click.echo(message)

    if not success:
        raise SystemExit(1 if "already running" in message.lower() else 2)


def _run_foreground() -> None:
    """Start server in foreground with verbose logging."""
    from frago.server.daemon import SERVER_HOST, SERVER_PORT, is_server_running
    from frago.server.runner import run_server

    # Check if already running in background
    running, pid = is_server_running()
    if running:
        click.echo(f"Note: Background server is running (PID: {pid})")
        click.echo("Starting debug server on same port will fail if port is in use.")
        click.echo()

    click.echo("  Frago Web Service (Debug Mode)")
    click.echo("  ---------------------------------")
    click.echo(f"  Local:   http://{SERVER_HOST}:{SERVER_PORT}")
    click.echo(f"  API:     http://{SERVER_HOST}:{SERVER_PORT}/api/docs")
    click.echo()
    click.echo("  Press Ctrl+C to stop")
    click.echo()

    run_server(
        host=SERVER_HOST,
        port=SERVER_PORT,
        auto_open=False,  # Don't auto-open browser in debug mode
        auto_port=False,  # Don't find alternative port
        log_level="debug",
        reload=False,  # No reload for server command
    )


@server_group.command("stop", cls=AgentFriendlyCommand)
@click.option(
    "--force",
    is_flag=True,
    help="Force stop even if active tasks are running",
)
def stop(force: bool) -> None:
    """Stop the running Frago web service."""
    _guard_sub_agent("stop")
    _guard_active_tasks(force, "stop")
    from frago.server.daemon import stop_daemon

    success, message = stop_daemon()
    click.echo(message)

    if not success:
        raise SystemExit(1)


@server_group.command("restart", cls=AgentFriendlyCommand)
@click.option(
    "--force",
    is_flag=True,
    help="Force restart even if graceful shutdown fails",
)
def restart(force: bool) -> None:
    """Restart the Frago web service.

    Stops the running server and starts a new instance.
    If the server is not running, starts it.
    """
    _guard_sub_agent("restart")
    _guard_active_tasks(force, "restart")
    _reinstall_and_exec_if_source_checkout()
    from frago.server.daemon import restart_daemon

    success, message = restart_daemon(force=force)
    click.echo(message)

    if not success:
        raise SystemExit(1)


@server_group.command("status", cls=AgentFriendlyCommand)
def status() -> None:
    """Check if the Frago web service is running."""
    from frago.server.daemon import get_server_status

    status_info = get_server_status()

    if status_info["running"]:
        click.echo("Frago server is running")
        click.echo(f"  PID:     {status_info['pid']}")
        click.echo(f"  URL:     {status_info['url']}")
        if status_info["uptime_formatted"]:
            click.echo(f"  Uptime:  {status_info['uptime_formatted']}")
    else:
        click.echo("Frago server is not running")
        raise SystemExit(1)
