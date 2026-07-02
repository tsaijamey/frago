#!/usr/bin/env python3
"""
Frago Agent Command - Execute non-interactive AI tasks via Claude CLI

Authentication strategy:
Based on ~/.frago/config.json configuration written by `frago init`:
1. auth_method == "official" → Use Claude CLI directly
2. auth_method == "custom" → Claude CLI uses env from ~/.claude/settings.json
3. ccr_enabled == True or --use-ccr → Use CCR proxy
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

import click

from frago.compat import prepare_command_for_windows

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

# =============================================================================
# Configuration Loading
# =============================================================================

def get_frago_config_path() -> Path:
    """Get frago configuration file path"""
    return Path.home() / ".frago" / "config.json"


def load_frago_config() -> dict | None:
    """
    Load frago configuration

    Returns:
        Configuration dict, or None if not found or corrupted
    """
    config_path = get_frago_config_path()
    if not config_path.exists():
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# =============================================================================
# Utility Functions
# =============================================================================

def find_agent_cli(agent_type: str = "claude") -> str | None:
    """
    Find a cli-agent executable path (parameterized; delegates to compat).

    Returns:
        agent executable path, or None if not found
    """
    from frago.compat import find_agent_cli as _compat_find_agent_cli

    return _compat_find_agent_cli(agent_type)


def find_claude_cli() -> str | None:
    """Thin backward-compatible wrapper over find_agent_cli("claude")."""
    return find_agent_cli("claude")


def _resolve_profile_env(profile_name: str) -> dict[str, str]:
    """把一个 profile 名（或 id）解析成 claude 的 ANTHROPIC_* 环境变量。

    复用 init/WebUI 同一套翻译逻辑（build_claude_env_config），保证 CLI 起的 tmux
    会话与激活 profile 写进 settings.json 的字段完全一致。tmux -e 要求值为字符串，
    故统一 str() 化（顺带把 API_TIMEOUT_MS 等 int 值转为字符串）。
    """
    from frago.init.configurator import build_claude_env_config
    from frago.init.profile_manager import load_profiles

    store = load_profiles()
    profile = next(
        (p for p in store.profiles if p.name == profile_name or p.id == profile_name),
        None,
    )
    if not profile:
        available = ", ".join(p.name for p in store.profiles) or "(none)"
        click.echo(
            f"Error: profile {profile_name!r} not found. Available: {available}",
            err=True,
        )
        sys.exit(1)

    env = build_claude_env_config(
        endpoint_type=profile.endpoint_type,
        api_key=profile.api_key,
        custom_url=profile.url if profile.endpoint_type == "custom" else None,
        default_model=profile.default_model,
        sonnet_model=profile.sonnet_model,
        haiku_model=profile.haiku_model,
    )
    return {k: str(v) for k, v in env.items()}


def _run_tmux_driver(
    prompt_text: str,
    *,
    agent_type: str,
    session_id: str | None,
    cwd: str,
    timeout: int,
    quiet: bool,
    dry_run: bool,
    no_persist: bool = False,
    env: dict[str, str] | None = None,
) -> None:
    """Drive a resident tmux TUI session via SessionLauncher (one turn).

    Phase 1: no warm pool yet — opens a fresh session, sends one turn, closes.
    The legacy claude -p backend remains the default; this path is opt-in via
    --driver tmux and shares no code with it.
    """
    from frago.agent_driver import SessionLauncher

    sid = session_id or str(uuid.uuid4())
    if not quiet:
        click.echo(f"[OK] tmux driver: agent={agent_type} session={sid}")
    if dry_run:
        click.echo("[Dry Run] Skip actual execution")
        return

    launcher = SessionLauncher()
    try:
        result = launcher.run(
            prompt_text,
            agent_type=agent_type,
            session_id=sid,
            cwd=cwd,
            env=env,
            timeout_s=float(timeout),
        )
    except KeyError:
        click.echo(f"Error: no driver registered for agent-type {agent_type!r}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo("Error: tmux not found. Please install tmux first.", err=True)
        sys.exit(1)

    # Normalize this turn into the session subsystem (Web UI / session list).
    if not no_persist:
        with contextlib.suppress(Exception):
            from frago.agent_driver.transcript import write_turn

            write_turn(sid, agent_type, cwd, prompt_text, result, source="terminal")

    if result.status == "needs_input":
        click.echo(result.text)
        click.echo("[!] Agent needs input (auth wall / permission / clarification)", err=True)
        sys.exit(2)
    if result.status == "timeout":
        click.echo(result.text)
        click.echo(f"[!] Turn timed out after {timeout}s", err=True)
        sys.exit(1)
    click.echo(result.text)


def check_ccr_auth() -> tuple[bool, dict | None]:
    """
    Check CCR (Claude Code Router) configuration

    CCR works by setting ANTHROPIC_BASE_URL to point to local proxy

    Returns:
        (is_available, config_info)
    """
    # Check if ccr command exists
    ccr_path = shutil.which("ccr")
    if not ccr_path:
        return False, None

    # Check configuration file
    config_path = Path.home() / ".claude-code-router" / "config.json"
    if not config_path.exists():
        return False, {"error": "CCR config file not found"}

    try:
        with open(config_path) as f:
            config = json.load(f)

        # Check if Provider is configured
        providers = config.get("Providers", [])
        if not providers:
            return False, {"error": "No providers configured in CCR"}

        # Check CCR service status
        try:
            result = subprocess.run(
                prepare_command_for_windows(["ccr", "status"]),
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=5
            )
            is_running = "Running" in result.stdout and "Not Running" not in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            is_running = False

        return True, {
            "type": "ccr",
            "config_path": str(config_path),
            "providers": [p.get("name") for p in providers],
            "default_route": config.get("Router", {}).get("default", "unknown"),
            "is_running": is_running,
            "host": config.get("HOST", "127.0.0.1"),
            "port": config.get("PORT", 3456),
        }
    except (OSError, json.JSONDecodeError) as e:
        return False, {"error": f"Failed to read CCR config: {e}"}


def should_use_ccr(config: dict | None, force_ccr: bool = False) -> tuple[bool, dict | None]:
    """
    Determine whether to use CCR

    Args:
        config: frago configuration
        force_ccr: Whether to force using CCR (--use-ccr flag)

    Returns:
        (use CCR, CCR config info)
    """
    # Force using CCR
    if force_ccr:
        ok, info = check_ccr_auth()
        return ok, info

    # Determine based on configuration
    if config and config.get("ccr_enabled"):
        ok, info = check_ccr_auth()
        return ok, info

    return False, None


def verify_claude_working(timeout: int = 30) -> tuple[bool, str]:
    """
    Verify Claude CLI is working by running a simple prompt

    Args:
        timeout: Timeout in seconds

    Returns:
        (is_working, error message or success message)
    """
    try:
        result = subprocess.run(
            prepare_command_for_windows(["claude", "-p", "Say 'OK'", "--output-format", "json"]),
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout
        )

        if result.returncode == 0:
            try:
                response = json.loads(result.stdout)
                if response.get("type") == "result":
                    return True, "Claude CLI is working"
            except json.JSONDecodeError:
                pass
            return True, "Claude CLI responded"

        # Parse error message
        error_msg = result.stderr or result.stdout or "Unknown error"
        if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return False, "Authentication failed - please run 'claude' and use /login"
        if "rate limit" in error_msg.lower():
            return False, "Rate limited - please wait and try again"

        return False, f"Claude CLI error: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, f"Claude CLI timed out after {timeout}s"
    except FileNotFoundError:
        return False, "Claude CLI not found"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# =============================================================================
# CLI Commands
# =============================================================================

# 动词名 → frago agent 的常驻会话子命令（实现在 drive_command）。
_AGENT_SUBCOMMANDS = frozenset({"start", "send", "peek", "ls", "stop", "attach"})
# 隐藏的默认命令名：承载原 `frago agent <prompt> [options]` 全部逻辑。
_DEFAULT_RUN_CMD = "__run__"


class AgentGroup(AgentFriendlyGroup):
    """``frago agent`` 命令组，向后兼容裸调用。

    历史上 ``frago agent`` 是单个 command，到处以
    ``frago agent "<prompt>" [--options]`` 或 ``frago agent --yes --source web
    --prompt-file ...``（PA 路径，选项在前、无位置 prompt）的形式被调用。改成 group
    后，只有当第一个 token 明确是 start/send/peek/ls/stop（或 --help）时才走子命令分发；
    其余一切（选项开头、裸 prompt、空参）原样转交隐藏的默认命令，保证旧用法零破坏。
    """

    def parse_args(self, ctx, args):
        if args and (args[0] in _AGENT_SUBCOMMANDS or args[0] in ("--help", "-h")):
            return super().parse_args(ctx, args)
        # 旧的裸 prompt / 选项在前 / 空参 → 默认命令，参数原样透传。
        return super().parse_args(ctx, [_DEFAULT_RUN_CMD, *args])


@click.group("agent", cls=AgentGroup, invoke_without_command=True)
def agent() -> None:
    """
    Intelligent Agent: Execute tasks via a cli-agent session.

    \b
    Bare-prompt usage (unchanged, backward compatible):
      frago agent Help me find Python jobs on Upwork
      frago agent "fix the login bug" --model sonnet --yes
      frago agent --yes --source web --prompt-file task.txt

    \b
    Resident tmux-session subcommands:
      frago agent start <agent_type> [--name NAME]
      frago agent send <name> "<prompt>"
      frago agent peek <name>
      frago agent ls
      frago agent stop <name>
    """


@agent.command(_DEFAULT_RUN_CMD, cls=AgentFriendlyCommand, hidden=True)
@click.argument("prompt", nargs=-1, required=False)
@click.option(
    "--prompt-file",
    type=click.File('r', encoding='utf-8'),
    default=None,
    help="Read prompt from file (use '-' for stdin)"
)
@click.option(
    "--model",
    type=str,
    default=None,
    help="Specify model (sonnet, opus, haiku or full model name)"
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    help="Execution timeout in seconds, default 600"
)
@click.option(
    "--use-ccr",
    is_flag=True,
    help="Force using CCR (Claude Code Router)"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Only show command that would be executed, don't actually run"
)
@click.option(
    "--ask",
    is_flag=True,
    help="Enable permission confirmation (skip by default)"
)
@click.option(
    "--quiet", "-q",
    is_flag=True,
    help="Quiet mode, don't show real-time monitoring status"
)
@click.option(
    "--json-status",
    is_flag=True,
    help="Output monitoring status in JSON format (for machine processing)"
)
@click.option(
    "--no-monitor",
    is_flag=True,
    help="Disable session monitoring (don't record session data)"
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="Skip permission confirmation prompt, execute directly"
)
@click.option(
    "--source",
    type=click.Choice(["terminal", "web"], case_sensitive=False),
    default="terminal",
    help="Session source (terminal or web) for tracking origin"
)
@click.option(
    "--session-id",
    type=str,
    default=None,
    help="Use specified UUID as Claude Code session ID (for Executor traceability)"
)
@click.option(
    "--resume",
    "resume_session_id",
    type=str,
    default=None,
    help="Resume an existing Claude Code session by UUID (uses claude --resume internally)."
)
@click.option(
    "--passthrough",
    is_flag=True,
    help="Pass through raw stream-json output (for Web UI or machine consumption)"
)
@click.option(
    "--endpoint",
    type=str,
    default=None,
    help="Override endpoint URL (ANTHROPIC_BASE_URL), takes precedence over profile/CCR"
)
@click.option(
    "--api-key",
    type=str,
    default=None,
    help="Override API key (ANTHROPIC_AUTH_TOKEN), takes precedence over profile/CCR"
)
@click.option(
    "--use-profile",
    type=str,
    default=None,
    help="Run with a saved API profile's endpoint/model/key (by profile name or id). "
         "Injected into the session env; --endpoint/--api-key still override it."
)
@click.option(
    "--agent-type",
    type=str,
    default="claude",
    help="Which cli-agent to drive (claude / opencode / codex). Default: claude"
)
@click.option(
    "--driver",
    type=click.Choice(["claude-p", "tmux"]),
    default="claude-p",
    help="Execution backend: claude-p (legacy headless, default) or tmux (resident TUI session)"
)
def agent_run(
    prompt: tuple,
    prompt_file,
    model: str | None,
    timeout: int,
    use_ccr: bool,
    dry_run: bool,
    ask: bool,
    quiet: bool,
    json_status: bool,
    no_monitor: bool,
    yes: bool,
    source: str,
    session_id: str | None,
    resume_session_id: str | None,
    passthrough: bool,
    endpoint: str | None,
    api_key: str | None,
    use_profile: str | None,
    agent_type: str,
    driver: str,
):
    """
    Intelligent Agent: Execute tasks via Claude Code session

    \b
    Examples:
      frago agent Help me find Python jobs on Upwork
      frago agent Research YouTube subtitle extraction API
      frago agent Write a recipe to extract Twitter comments

    \b
    Available models (--model):
      sonnet, opus, haiku or full model name
    """
    # Determine prompt source: --prompt-file has priority, otherwise use command line arguments
    if prompt_file:
        prompt_text = prompt_file.read().strip()
    elif prompt:
        prompt_text = " ".join(prompt)
    else:
        click.echo("Error: Please provide prompt (command line argument or --prompt-file)", err=True)
        sys.exit(1)

    if not prompt_text:
        click.echo("Error: prompt cannot be empty", err=True)
        sys.exit(1)

    # Resolve --use-profile into ANTHROPIC_* env once, shared by both backends.
    # CLI --endpoint/--api-key still override these below (claude-p path).
    profile_env = _resolve_profile_env(use_profile) if use_profile else {}

    # tmux backend: resident TUI session driven by SessionLauncher.
    # Legacy claude -p path stays the default and is left fully intact below.
    if driver == "tmux":
        # CCR env for the tmux session, same precedence as the claude-p path:
        # CCR < profile < (no --endpoint/--api-key here; claude-p only).
        tmux_env: dict[str, str] = {}
        use_ccr_mode, ccr_info = should_use_ccr(load_frago_config(), use_ccr)
        if use_ccr_mode:
            if not ccr_info:
                click.echo("Error: Invalid CCR configuration", err=True)
                sys.exit(1)
            host = ccr_info.get("host", "127.0.0.1")
            port = ccr_info.get("port", 3456)
            tmux_env.update({
                "ANTHROPIC_AUTH_TOKEN": "test",
                "ANTHROPIC_BASE_URL": f"http://{host}:{port}",
                "NO_PROXY": "127.0.0.1",
                "DISABLE_TELEMETRY": "true",
            })
            if not ccr_info.get("is_running"):
                if not quiet:
                    click.echo("Starting CCR service...")
                subprocess.run(prepare_command_for_windows(["ccr", "start"]), capture_output=True)
            if not quiet:
                click.echo(f"[OK] Using CCR: http://{host}:{port}")
        tmux_env.update(profile_env)
        _run_tmux_driver(
            prompt_text,
            agent_type=agent_type,
            session_id=session_id,
            cwd=os.getcwd(),
            timeout=timeout,
            quiet=quiet,
            dry_run=dry_run,
            no_persist=no_monitor,
            env=tmux_env or None,
        )
        return

    # Step 1: Check if agent CLI exists
    claude_path = find_agent_cli(agent_type)
    if not claude_path:
        click.echo(f"Error: {agent_type} CLI not found", err=True)
        click.echo("Please install Claude Code first: https://claude.ai/code", err=True)
        sys.exit(1)

    if not passthrough:
        click.echo(f"[OK] Claude CLI: {claude_path}")

    # Step 2: Load frago configuration
    frago_config = load_frago_config()
    if not passthrough:
        if frago_config:
            auth_method = frago_config.get("auth_method", "official")
            if auth_method == "official":
                click.echo("[OK] Authentication: Claude CLI native")
            else:
                click.echo("[OK] Authentication: Custom API endpoint")
        else:
            click.echo("[!] Frago config not found, using Claude CLI default authentication")
            click.echo("  Tip: Run 'frago init' to initialize configuration")

    # Step 3: Determine whether to use CCR
    env = os.environ.copy()
    use_ccr_mode, ccr_info = should_use_ccr(frago_config, use_ccr)

    if use_ccr_mode:
        if not ccr_info:
            click.echo("\nError: Invalid CCR configuration", err=True)
            sys.exit(1)

        host = ccr_info.get("host", "127.0.0.1")
        port = ccr_info.get("port", 3456)
        env["ANTHROPIC_AUTH_TOKEN"] = "test"
        env["ANTHROPIC_BASE_URL"] = f"http://{host}:{port}"
        env["NO_PROXY"] = "127.0.0.1"
        env["DISABLE_TELEMETRY"] = "true"

        if not ccr_info.get("is_running"):
            if not passthrough:
                click.echo("Starting CCR service...")
            subprocess.run(prepare_command_for_windows(["ccr", "start"]), capture_output=True, env=env)

        if not passthrough:
            click.echo(f"[OK] Using CCR: http://{host}:{port}")

    # --use-profile: inject the profile's ANTHROPIC_* into the claude env.
    # Applied after CCR so an explicit profile wins over CCR, but before the
    # --endpoint/--api-key overrides below so those still take highest priority.
    if profile_env:
        env.update(profile_env)
        # Bearer-style profiles carry the credential in ANTHROPIC_AUTH_TOKEN; only
        # clear a leftover CCR placeholder when the profile itself doesn't set one
        # (api-key-style profiles), otherwise we'd wipe the real token.
        if "ANTHROPIC_AUTH_TOKEN" not in profile_env:
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if not passthrough:
            click.echo(f"[OK] Using profile: {use_profile}")

    # CLI overrides (highest priority): --endpoint / --api-key win over profile/CCR
    if endpoint:
        env["ANTHROPIC_BASE_URL"] = endpoint
        if not passthrough:
            click.echo(f"[OK] Override endpoint: {endpoint}")
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
        # Clear AUTH_TOKEN set by CCR mode so API_KEY takes effect
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if not passthrough:
            click.echo("[OK] Override API key: (from --api-key)")

    # Step 4: Permission confirmation (--yes skips confirmation)
    # In passthrough mode, skip confirmation (Web UI handles this)
    if not ask and not dry_run and not yes and not passthrough:
        click.echo()
        click.echo("[!] Will run in --dangerously-skip-permissions mode")
        click.echo("  Claude will skip all permission confirmations and execute any operation directly")
        if not click.confirm("Confirm to continue?", default=False):
            click.echo("Cancelled")
            sys.exit(0)

    skip_permissions = not ask

    # =========================================================================
    # Single-phase execution: Let agent determine and execute directly
    # =========================================================================

    if not passthrough:
        click.echo(f"\n[Execute] {prompt_text}")
    execution_prompt = prompt_text

    if dry_run:
        click.echo("[Dry Run] Skip actual execution")
        return

    # Build final command - use stream-json for real-time output
    # Note: stream-json must be used with --verbose
    # Use "-p -" to read prompt from stdin, avoid Windows command line argument truncation of newlines
    cmd = ["claude", "-p", "-", "--output-format", "stream-json", "--verbose"]

    # In passthrough mode, enable bidirectional stream-json for Web UI
    if passthrough:
        cmd.extend([
            "--input-format", "stream-json",
            "--include-partial-messages",
            "--replay-user-messages",
        ])

    # Resume mode vs new-session mode (mutually exclusive)
    if session_id and resume_session_id:
        click.echo("Error: --session-id and --resume are mutually exclusive", err=True)
        raise click.Abort()
    if resume_session_id:
        target_session_id = resume_session_id
        cmd.extend(["--resume", resume_session_id])
    else:
        target_session_id = session_id or str(uuid.uuid4())
        cmd.extend(["--session-id", target_session_id])

    if model:
        cmd.extend(["--model", model])

    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    if not passthrough:
        click.echo("-" * 60)

    # Start session monitoring (if not disabled)
    # Note: Even in passthrough mode, monitor is needed to sync sessions to ~/.frago/sessions/
    # so watchdog can detect changes and update tasks list
    monitor = None
    monitor_enabled = not no_monitor and os.environ.get("FRAGO_MONITOR_ENABLED", "1") != "0"

    if monitor_enabled:
        try:
            from frago.session.monitor import SessionMonitor

            start_time = datetime.now()
            project_path = os.getcwd()

            from frago.session.models import SessionSource

            # Convert source string to SessionSource enum
            session_source = SessionSource.WEB if source.lower() == "web" else SessionSource.TERMINAL

            monitor = SessionMonitor(
                project_path=project_path,
                start_time=start_time,
                json_mode=json_status,
                persist=True,
                quiet=quiet,
                target_session_id=target_session_id,  # Always pin to exact session ID
                source=session_source,
            )
            monitor.start()
        except ImportError as e:
            # session module may not be installed, silently ignore
            if not quiet:
                click.echo(f"  [!] Session monitoring not enabled: {e}", err=True)
        except Exception as e:
            if not quiet:
                click.echo(f"  [!] Failed to start monitoring: {e}", err=True)

    # Execute command (real-time streaming output)
    try:
        process = subprocess.Popen(
            prepare_command_for_windows(cmd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            env=env,
            bufsize=1,
        )

        # Pass prompt via stdin (avoid Windows command line argument truncation of multi-line text)
        if passthrough:
            # In passthrough mode, send prompt as stream-json format
            stdin_payload = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": execution_prompt
                }
            }) + "\n"
        else:
            stdin_payload = execution_prompt

        # Write stdin in a background thread so stdout reading can start concurrently.
        # On Windows, pipe buffers are small and a synchronous large write blocks
        # before the reader drains — causing BrokenPipe when claude exits.
        def _write_stdin() -> None:
            try:
                process.stdin.write(stdin_payload)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        stdin_thread = threading.Thread(target=_write_stdin, daemon=True)
        stdin_thread.start()

        if passthrough:
            # Passthrough mode: output raw stream-json directly
            for line in iter(process.stdout.readline, ""):
                if line.strip():
                    sys.stdout.write(line)
                    sys.stdout.flush()
        else:
            # Normal mode: Parse stream-json format and display in real-time
            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue

                # Parse stream-json and display key information
                try:
                    event = json.loads(line)
                    event_type = event.get("type", "")

                    if event_type == "assistant":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            block_type = block.get("type")
                            if block_type == "text":
                                text = block.get("text", "")
                                if text:
                                    click.echo(text)
                            elif block_type == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_input = block.get("input", {})
                                if tool_name == "Bash":
                                    cmd_str = tool_input.get("command", "")
                                    desc = tool_input.get("description", "")
                                    click.echo(f"[Bash] {desc or cmd_str[:50]}")
                                else:
                                    click.echo(f"[{tool_name}]")
                except json.JSONDecodeError:
                    # Non-JSON lines output directly
                    if not quiet:
                        click.echo(line)

        # Read stderr
        stderr_output = process.stderr.read()
        if stderr_output and not passthrough:
            click.echo(f"\n[stderr] {stderr_output}", err=True)

        process.wait(timeout=timeout)

        if not passthrough:
            click.echo("\n" + "-" * 60)

            if process.returncode == 0:
                click.echo("[OK] Execution completed")
            else:
                # Non-zero exit code doesn't force exit, Claude CLI will adaptively handle tool errors
                click.echo(f"[!] Execution finished (exit code: {process.returncode})")

    except subprocess.TimeoutExpired:
        process.kill()
        click.echo(f"\n[X] Execution timeout ({timeout}s)", err=True)
    except KeyboardInterrupt:
        process.kill()
        click.echo("\n[X] User interrupted", err=True)
    except Exception as e:
        click.echo(f"\n[X] Execution error: {e}", err=True)
    finally:
        # Ensure stdin writer thread is reaped (daemon, but clean up eagerly)
        with contextlib.suppress(Exception):
            stdin_thread.join(timeout=1)
        # Stop session monitoring
        if monitor:
            with contextlib.suppress(Exception):
                monitor.stop()


# =============================================================================
# Auxiliary Command: Check Authentication Status
# =============================================================================

@click.command("agent-status", cls=AgentFriendlyCommand)
def agent_status():
    """
    Check Claude CLI authentication status

    Display current available authentication methods and configuration information.
    """
    click.echo("Claude CLI Authentication Status Check")
    click.echo("=" * 50)

    # Check claude CLI
    claude_path = find_claude_cli()
    if claude_path:
        click.echo(f"[OK] Claude CLI: {claude_path}")
        # Get version
        try:
            result = subprocess.run(
                prepare_command_for_windows(["claude", "--version"]),
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=5
            )
            if result.returncode == 0:
                click.echo(f"  Version: {result.stdout.strip()}")
        except Exception:
            pass
    else:
        click.echo("[X] Claude CLI: Not installed")
        return

    click.echo()

    # Load frago configuration
    click.echo("Frago Configuration:")
    frago_config = load_frago_config()
    if frago_config:
        auth_method = frago_config.get("auth_method", "official")
        ccr_enabled = frago_config.get("ccr_enabled", False)
        init_completed = frago_config.get("init_completed", False)

        click.echo(f"  Config file: {get_frago_config_path()}")
        click.echo(f"  Authentication: {'Claude CLI native' if auth_method == 'official' else 'Custom API endpoint'}")
        click.echo(f"  CCR enabled: {'Yes' if ccr_enabled else 'No'}")
        click.echo(f"  Initialization status: {'Completed' if init_completed else 'Not completed'}")
    else:
        click.echo("  [!] Config file not found")
        click.echo("  Tip: Run 'frago init' to initialize configuration")

    click.echo()

    # Check CCR status (if enabled)
    if frago_config and frago_config.get("ccr_enabled"):
        click.echo("CCR Status:")
        ok, info = check_ccr_auth()
        if ok:
            click.echo("  [OK] CCR available")
            click.echo(f"    Providers: {', '.join(info.get('providers', []))}")
            click.echo(f"    Running status: {'Running' if info.get('is_running') else 'Not running'}")
        else:
            click.echo("  [X] CCR not available")
            if info and info.get("error"):
                click.echo(f"    Reason: {info['error']}")


# =============================================================================
# frago agent attach —— 交付即核心（spec 20260627 Phase 8）
# =============================================================================
@agent.command("attach")
@click.option("--files", default=None, help='JSON array of file paths, e.g. \'["report.md","a.png"]\'.')
@click.option("--dirs", default=None, help='JSON array of directory paths, e.g. \'["out/"]\'.')
@click.option(
    "--conv-key", "conv_key", default=None,
    help="Override the conv to attach to; defaults to $FRAGO_CONV_KEY.",
)
def agent_attach(files: str | None, dirs: str | None, conv_key: str | None) -> None:
    """Register produced file artifacts onto the current conv's outbox.

    \b
    交付层在转发 agent 文本前会 drain 该 conv 的 outbox，把登记的文件作为真附件
    随回复一起送达。conv_key 默认从 ``FRAGO_CONV_KEY`` env 自解析（tmux 起会话时
    注入），命令侧 NEVER 让 agent 瞎填——``--conv-key`` 只给非 agent 调用方覆盖。

    \b
      frago agent attach --files '["report.md"]'
      frago agent attach --files '["chart.png"]' --dirs '["build/"]'
    """
    key = conv_key or os.environ.get("FRAGO_CONV_KEY")
    if not key:
        click.echo(
            "Error: no conv_key — set $FRAGO_CONV_KEY (auto-injected in agent "
            "sessions) or pass --conv-key.",
            err=True,
        )
        sys.exit(1)

    def _parse(label: str, raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            val = json.loads(raw)
        except json.JSONDecodeError as e:
            click.echo(f"Error: --{label} must be a JSON array: {e}", err=True)
            sys.exit(1)
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            click.echo(f"Error: --{label} must be a JSON array of strings.", err=True)
            sys.exit(1)
        return val

    file_list = _parse("files", files)
    dir_list = _parse("dirs", dirs)
    if not file_list and not dir_list:
        click.echo("Error: nothing to attach — pass --files and/or --dirs.", err=True)
        sys.exit(1)

    from frago.server.services import pa_outbox

    records = pa_outbox.append(key, files=file_list, dirs=dir_list)
    click.echo(f"Attached {len(records)} artifact(s) to conv {key!r}.")
    for rec in records:
        click.echo(f"  {rec['kind']}\t{rec['path']}")


# =============================================================================
# Resident-session subcommands: frago agent start/send/peek/ls/stop
# =============================================================================
# 实现在 drive_command（薄封装 agent_driver）；这里只负责把它们挂到 agent 组下。
from .drive_command import DRIVE_SUBCOMMANDS  # noqa: E402

for _subcmd in DRIVE_SUBCOMMANDS:
    agent.add_command(_subcmd)
