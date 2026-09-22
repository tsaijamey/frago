"""Frago server command group - Background web service management.

Provides commands to start, stop, and check status of the Frago
web service running as a background daemon process.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

# Sentinel preventing infinite recursion: the re-exec'd system frago sees it
# and skips the reinstall branch. It is meant for that one process only and is
# removed as soon as it is read, so the server does not inherit it.
REINSTALL_SENTINEL_ENV = "FRAGO_REINSTALL_DONE"

# Windows raises this when Code Integrity refuses to load an image — in practice,
# Smart App Control rejecting an unsigned binary with no cloud reputation.
WINDOWS_APP_CONTROL_ERROR = 4551


def _repo_version(pyproject: Path) -> str:
    """Read `version = "x.y.z"` out of pyproject.toml. Raises when absent."""
    text = pyproject.read_text(encoding="utf-8")
    pattern = re.compile(r'^(version\s*=\s*")([^"]+)(")', flags=re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise click.ClickException(f"No version line found in {pyproject}")
    return match.group(2)


def _local_stamp(root: Path) -> str:
    """Which commit this build came from, whether it carries uncommitted work,
    and when it was made.

    The commit is what lets the publish side answer "is the copy running on this
    machine the one being released". The timestamp is what keeps two builds of
    the same commit from being indistinguishable — the release number used to
    carry that job, by counting up. Falls back to a bare timestamp when git
    cannot answer, because an unidentifiable build is still better than an
    empty segment.
    """

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True
            )
        except OSError:
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    when = time.strftime("%Y%m%dT%H%M%S")
    sha = git("rev-parse", "--short=12", "HEAD")
    if not sha:
        return when
    dirty = ".dirty" if git("status", "--porcelain") else ""
    return f"g{sha}{dirty}.{when}"


def _local_build_version(root: Path) -> str:
    """The version to build this machine's copy under: the repo's release number
    plus a local segment.

    This used to increment the patch segment and write it back into
    pyproject.toml. That gave one number two writers — the release path publishes
    whatever the repo says, while every local deploy pushed the number up a
    notch — so the two drifted apart while the code stayed identical: PyPI
    holding `a`, this machine running `a+1`, both built from the same commit.

    Now the release number is never touched here. A local build only appends
    after the `+`: which commit it came from, whether the tree was dirty, when
    it was made. The release number stays a promise made to the outside, and
    only the release action moves it; the local segment answers "where did this
    copy on my machine come from".

    PyPI refuses local version segments outright, so a local build cannot be
    published even by mistake. The two can never collide.
    """
    base = _repo_version(root / "pyproject.toml").split("+", 1)[0]
    return f"{base}+local.{_local_stamp(root)}"


# What the wheel is built from, relative to the checkout root.
_WHEEL_COPY_PATHS = ("src/frago", "README.md", "LICENSE", "pyproject.toml")

# The fallback when git cannot answer: copy the tree, skipping by directory name.
# ``client`` alone is 599M of node_modules; carrying it would make every restart
# pay for a copy the build then throws away.
_WHEEL_COPY_SKIP = ("client", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache")


def _wheel_source_files(root: Path) -> list[str]:
    """The files this build packs, relative to the checkout root.

    Ask git rather than carrying a skip list: a list is an approximation of
    "what belongs in the repo", and the approximation is what goes wrong. The
    hand-written version skipped node_modules and caches but not gitignored
    ``*.log`` files, so those reached the wheel built from the copy while the
    real build left them out — the local install was not the same artifact.
    Hatchling builds from git's answer, so taking the same answer makes the two
    wheels hold the same files, differing only in the version string.

    Empty list when git cannot answer (not a repo, no git on PATH); the caller
    then falls back to copying the tree.
    """
    try:
        done = subprocess.run(
            [
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                *_WHEEL_COPY_PATHS,
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if done.returncode != 0:
        return []
    return [line for line in done.stdout.splitlines() if line]


def _build_wheel_with_local_version(root: Path, version: str, out_dir: Path) -> Path:
    """Build the wheel under ``version`` from a throwaway copy of the checkout.

    The copy exists so the version can be rewritten without touching the
    checkout. Writing it in place and restoring afterwards would be shorter, but
    a build killed halfway leaves a version line in pyproject.toml that no one
    meant to commit — which is the very thing this is meant to end.

    Hatchling's include/exclude patterns are path-relative and still apply, so
    the copy builds the same wheel.
    """
    project = Path(tempfile.mkdtemp(prefix="frago-build-"))
    try:
        files = _wheel_source_files(root)
        if files:
            for relative in files:
                source = root / relative
                if not source.exists():  # deleted in the working tree
                    continue
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        else:
            shutil.copy2(root / "pyproject.toml", project / "pyproject.toml")
            for name in ("README.md", "LICENSE"):
                if (root / name).exists():
                    shutil.copy2(root / name, project / name)
            shutil.copytree(
                root / "src" / "frago",
                project / "src" / "frago",
                ignore=shutil.ignore_patterns(*_WHEEL_COPY_SKIP),
            )

        pyproject = project / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        rewritten = re.sub(
            r'^(version\s*=\s*")([^"]+)(")',
            lambda m: f"{m.group(1)}{version}{m.group(3)}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if rewritten == text:
            raise click.ClickException(f"No version line found in {pyproject}")
        pyproject.write_text(rewritten, encoding="utf-8")

        build = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(project)],
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            raise click.ClickException(f"uv build failed:\n{build.stderr.strip()}")

        wheels = sorted(Path(out_dir).glob("*.whl"))
        if not wheels:
            raise click.ClickException(f"uv build produced no wheel in {out_dir}")
        return wheels[-1]
    finally:
        shutil.rmtree(project, ignore_errors=True)


def _is_inside(path: Path, root: Path) -> bool:
    """True when ``path`` lies within ``root``, comparing the way the OS does.

    ``normcase`` is what makes this correct on Windows, where ``C:\\Users`` and
    ``c:\\users`` name the same directory but compare unequal as strings.
    """
    try:
        resolved = Path(os.path.normcase(str(path.resolve(strict=False))))
        resolved.relative_to(Path(os.path.normcase(str(root))))
    except ValueError:
        return False
    return True


def _system_frago_path(checkout_root: Path) -> str | None:
    """Find the system-installed frago on PATH, skipping the repo venv's own.

    Under `uv run` the repo's venv bin directory is prepended to PATH, so a
    plain ``shutil.which("frago")`` would loop back into the checkout. Drop
    every PATH entry inside the checkout first, then let ``shutil.which`` do the
    lookup — it applies PATHEXT, which is what finds ``frago.exe`` on Windows
    where a bare ``frago`` file never exists.
    """
    root = checkout_root.resolve()
    outside = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and not _is_inside(Path(entry), root)
    ]
    found = shutil.which("frago", path=os.pathsep.join(outside))
    # shutil.which prepends the current directory on Windows; a hit there could
    # still be the checkout's own.
    if found is None or _is_inside(Path(found), root):
        return None
    if os.name == "nt":
        # which() spells the suffix the way PATHEXT does, so a file stored as
        # frago.exe comes back as frago.EXE. Same file, but it is the string we
        # echo and hand to the child, so restore what is actually on disk.
        # POSIX is left alone: resolving there would follow a symlink and change
        # which binary runs.
        return str(Path(found).resolve())
    return found


def _handover_failed(target: str, version: str, exc: OSError) -> click.ClickException:
    """Explain a handover that could not start, and say what is already done.

    By this point the build and the install have succeeded — only launching the
    new binary failed. Saying so keeps the reader from re-running the whole
    thing and bumping the version again for nothing.
    """
    done = f"frago {version} is installed; only the handover failed."
    if getattr(exc, "winerror", None) != WINDOWS_APP_CONTROL_ERROR:
        return click.ClickException(f"Could not run {target}: {exc}\n{done}")
    return click.ClickException(
        f"Windows Smart App Control blocked {target}.\n{done}\n"
        "It admits only signed or cloud-reputable binaries, and every reinstall "
        "mints a fresh unsigned launcher that can never earn reputation, so "
        "this recurs on every restart. Turn it off under Windows Security > "
        "App & browser control > Smart App Control — Windows presents that "
        "switch as permanent and may refuse to re-enable it without a reset.\n"
        "Blocks are logged in Event Viewer under "
        "Microsoft-Windows-CodeIntegrity/Operational."
    )


def _reinstall_and_exec_if_source_checkout() -> None:
    """From a source checkout: build + install the repo as the system frago, then exec it.

    The repo venv's frago must never be the server runtime. When the CLI runs
    from inside the frago source tree, build a wheel under a local version
    segment, `uv tool install --force` it, and hand the original argv over to
    the system-installed frago — by ``os.execv`` where that exists, as a child
    process whose status we adopt on Windows where it does not. No-op on a
    global/uv-tool install or when the reinstall sentinel is already set (we ARE
    the re-exec'd process).

    The build reads the checkout but never writes it: the version line lives in
    a throwaway copy, so the working tree is left exactly as it was found.

    The sentinel is dropped the moment it is read. Left in place, the server
    inherits it, tmux inherits it from the server, and every agent session in
    tmux inherits it from tmux — so a ``uv run frago server restart`` typed in
    one of those sessions mistakes itself for the re-exec'd process, skips the
    reinstall, and restarts the old installed code.
    """
    if os.environ.pop(REINSTALL_SENTINEL_ENV, None) == "1":
        return
    from frago.server.launch_guard import source_checkout_root

    root = source_checkout_root()
    if root is None:
        return  # already the system install — nothing to do

    new_version = _local_build_version(root)
    click.echo(f"[reinstall] source checkout detected at {root}")
    click.echo(
        f"[reinstall] building local version {new_version} "
        f"(the release number in pyproject.toml stays put)"
    )

    with tempfile.TemporaryDirectory(prefix="frago-wheel-") as tmpdir:
        click.echo(f"[reinstall] building wheel ({new_version}) ...")
        wheel = _build_wheel_with_local_version(root, new_version, Path(tmpdir))

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
            "System frago not found on PATH after uv tool install. "
            "Run 'uv tool update-shell' and open a new shell so the uv tool bin "
            "directory (~/.local/bin) is on PATH."
        )

    args = [system_frago, *sys.argv[1:]]
    click.echo(f"[reinstall] handing over to system frago: {' '.join(args)}")
    os.environ[REINSTALL_SENTINEL_ENV] = "1"
    _drop_checkout_venv_from_path(root)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        # Windows has no exec. os.execv there spawns a child and terminates the
        # caller, so the shell takes back the prompt while the handover is still
        # running and its exit status is lost. Run it as a child and mirror the
        # status instead, which is what a real exec would have given the caller.
        try:
            completed = subprocess.run(args)
        except OSError as exc:
            raise _handover_failed(system_frago, new_version, exc) from exc
        sys.exit(completed.returncode)
    try:
        os.execv(system_frago, args)
    except OSError as exc:
        raise _handover_failed(system_frago, new_version, exc) from exc


def _drop_checkout_venv_from_path(root: Path) -> None:
    """Stop the checkout's virtualenv from following the server around.

    ``uv run frago server start`` puts the checkout's venv bin directory first
    on PATH — ``.venv/bin`` on POSIX, ``.venv\\Scripts`` on Windows. That is how
    uv runs a project command, and it is what makes the build-and-install step
    above possible. Replacing the process does not reset the environment, so
    without this the server keeps that entry, and so does every recipe it
    spawns.

    The consequence is not obvious from the symptom. A recipe that shells out to
    plain ``frago`` resolves it to the checkout copy, which refuses to run
    anything but ``server`` — so the recipe fails with "Refusing to run: this
    frago comes from the source checkout" while everything about the server
    itself looks fine. It cost the virtual desktop's supervisor a full cycle of
    silent failures before the reason showed up in a log line.

    Only the checkout's own venv is removed. ``VIRTUAL_ENV`` goes with it: a
    stale pointer to an environment no longer on PATH misleads anything that
    reads it to decide which interpreter to use.
    """
    # Both layout names, so the check does not depend on which platform created
    # the venv; the one that does not exist simply never matches.
    venv_bins = {
        os.path.normcase(str((root / ".venv" / name).resolve(strict=False)))
        for name in ("bin", "Scripts")
    }
    entries = os.environ.get("PATH", "").split(os.pathsep)
    kept = [
        e
        for e in entries
        if e
        and os.path.normcase(str(Path(e).resolve(strict=False))) not in venv_bins
    ]
    if len(kept) != len(entries):
        os.environ["PATH"] = os.pathsep.join(kept)
        click.echo("[reinstall] dropped checkout venv from PATH for the server")
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env and _is_inside(Path(virtual_env), root):
        os.environ.pop("VIRTUAL_ENV", None)


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


@server_group.command("token", cls=AgentFriendlyCommand)
@click.option("--rotate", is_flag=True, help="Discard the current token and mint a new one")
def token(rotate: bool) -> None:
    """Print the token that admits non-local callers to this server.

    Calls arriving from this machine never need it — the local CLI, the desktop
    client and recipes are trusted by virtue of being here. Anything reaching
    the server from elsewhere (another frago over a tunnel, a browser on another
    host) must send it as `Authorization: Bearer <token>`.

    \b
    Examples:
        frago server token                # print it (creates it on first run)
        frago server token --rotate       # invalidate every remote that has it
    """
    from frago.server.security import ensure_token, rotate_token, token_path

    value = rotate_token() if rotate else ensure_token()
    click.echo(value)
    if rotate:
        click.echo("Rotated. Every remote holding the old token is now locked out.", err=True)
    click.echo(f"Stored in {token_path()}", err=True)
    # Said here because this is what people read. The same warning is in the
    # deployment doc, but by then the token is already in a chat window.
    click.echo(
        "This token opens /api/file, /api/agent and /api/recipes/<n>/run — holding it "
        "is equivalent to running commands as this user. Treat it like an SSH key.",
        err=True,
    )


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

        from frago.server.security import deployment_warning

        warning = deployment_warning()
        if warning:
            click.echo()
            click.echo(click.style(warning, fg="yellow"), err=True)
    else:
        click.echo("Frago server is not running")
        raise SystemExit(1)
