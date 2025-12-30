#!/usr/bin/env python3
"""
Frago Agent Command - Execute non-interactive AI tasks via Claude CLI

Authentication strategy:
Based on ~/.frago/config.json configuration written by `frago init`:
1. auth_method == "official" → Use Claude CLI directly
2. auth_method == "custom" → Claude CLI uses env from ~/.claude/settings.json
3. ccr_enabled == True or --use-ccr → Use CCR proxy
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import click

from frago.compat import prepare_command_for_windows


# =============================================================================
# Configuration Loading
# =============================================================================

def get_frago_config_path() -> Path:
    """Get frago configuration file path"""
    return Path.home() / ".frago" / "config.json"


def load_frago_config() -> Optional[dict]:
    """
    Load frago configuration

    Returns:
        Configuration dict, or None if not found or corrupted
    """
    config_path = get_frago_config_path()
    if not config_path.exists():
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# =============================================================================
# Utility Functions
# =============================================================================

def find_claude_cli() -> Optional[str]:
    """
    Find claude CLI path

    Returns:
        claude executable path, or None if not found
    """
    return shutil.which("claude")


def check_ccr_auth() -> Tuple[bool, Optional[dict]]:
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
        with open(config_path, "r") as f:
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
    except (json.JSONDecodeError, IOError) as e:
        return False, {"error": f"Failed to read CCR config: {e}"}


def should_use_ccr(config: Optional[dict], force_ccr: bool = False) -> Tuple[bool, Optional[dict]]:
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


def verify_claude_working(timeout: int = 30) -> Tuple[bool, str]:
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

        return False, f"Claude CLI error: {error_msg[:200]}"

    except subprocess.TimeoutExpired:
        return False, f"Claude CLI timed out after {timeout}s"
    except FileNotFoundError:
        return False, "Claude CLI not found"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def get_available_slash_commands() -> dict:
    """
    Get all available frago slash commands

    Returns:
        Command name to description mapping, e.g. {"/frago.dev.run": "Execute AI-hosted..."}
    """
    commands = {}

    # Search paths
    search_dirs = [
        Path.cwd() / ".claude" / "commands",
        Path.home() / ".claude" / "commands",
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        # Find frago.*.md files
        for md_file in search_dir.glob("frago*.md"):
            cmd_name = "/" + md_file.stem  # frago.dev.run.md → /frago.dev.run

            if cmd_name in commands:
                continue  # Use first found

            # Try to extract description
            try:
                content = md_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    # Parse YAML frontmatter
                    second_delimiter = content.find("---", 3)
                    if second_delimiter != -1:
                        frontmatter = content[3:second_delimiter].strip()
                        # Simple description extraction
                        for line in frontmatter.split("\n"):
                            if line.startswith("description:"):
                                desc = line[12:].strip().strip('"\'')
                                commands[cmd_name] = desc
                                break
                        else:
                            commands[cmd_name] = ""
                else:
                    commands[cmd_name] = ""
            except IOError:
                commands[cmd_name] = ""

    return commands


# =============================================================================
# Agent Prompt Building
# =============================================================================

def _build_agent_prompt(user_prompt: str) -> str:
    """
    Build agent execution prompt

    Constructs a prompt that includes available slash command descriptions
    and the user's task, letting the agent determine which mode to use.

    Args:
        user_prompt: User's original prompt

    Returns:
        Complete prompt
    """
    # Get user's language preference for AI output
    from frago.server.services.config_service import ConfigService

    language = ConfigService.get_user_language()
    lang_section = (
        "\n\n## Language\n\nRespond in Chinese (中文)."
        if language == "zh"
        else ""
    )

    # Get available commands and their descriptions
    commands = get_available_slash_commands()

    # Extract key command descriptions
    command_descriptions = []
    key_commands = ["/frago.run", "/frago.do", "/frago.recipe", "/frago.test"]

    for cmd in key_commands:
        if cmd in commands:
            desc = commands[cmd]
            command_descriptions.append(f"- {cmd}: {desc}")

    commands_section = "\n".join(command_descriptions) if command_descriptions else "(No available commands)"

    commands_to_send = f"""# Frago Agent

You are an intelligent automation agent. Choose the appropriate execution mode based on the user's task intent.

## Available Slash Commands

{commands_section}

## Execution Strategy

Use Slash Commands to invoke appropriate skills based on user intent:
- **Explore/Research/Learn** → /frago.run
- **Execute/Complete/Do** → /frago.do
- **Create Recipe/Automation** → /frago.recipe
- **Test/Verify Recipe** → /frago.test
If the task is simple and clear, you can also use other tools directly without invoking the above Slash Commands.{lang_section}

---

## User Task

{user_prompt}
"""
    # Print commands_to_send
    # click.echo(commands_to_send)

    return commands_to_send


# =============================================================================
# CLI Commands
# =============================================================================

@click.command("agent")
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
    "--direct",
    is_flag=True,
    help="Execute directly, skip routing analysis"
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
    "--resume", "-r",
    type=str,
    default=None,
    help="Continue conversation in specified session (pass session_id)"
)
@click.option(
    "--source",
    type=click.Choice(["terminal", "web"], case_sensitive=False),
    default="terminal",
    help="Session source (terminal or web) for tracking origin"
)
def agent(
    prompt: tuple,
    prompt_file,
    model: Optional[str],
    timeout: int,
    use_ccr: bool,
    dry_run: bool,
    ask: bool,
    direct: bool,
    quiet: bool,
    json_status: bool,
    no_monitor: bool,
    yes: bool,
    resume: Optional[str],
    source: str
):
    """
    Intelligent Agent: Automatically choose execution mode based on user intent

    agent determines which mode to use based on task intent:
    - Explore/Research → /frago.run
    - Execute Task → /frago.do
    - Create Recipe → /frago.recipe
    - Test Recipe → /frago.test

    \b
    Examples:
      frago agent Help me find Python jobs on Upwork
      frago agent Research YouTube subtitle extraction API
      frago agent Write a recipe to extract Twitter comments
      frago agent --direct List current directory     # Skip mode determination, execute directly

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

    # Step 1: Check if claude CLI exists
    claude_path = find_claude_cli()
    if not claude_path:
        click.echo("Error: claude CLI not found", err=True)
        click.echo("Please install Claude Code first: https://claude.ai/code", err=True)
        sys.exit(1)

    click.echo(f"[OK] Claude CLI: {claude_path}")

    # Step 2: Load frago configuration
    frago_config = load_frago_config()
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
            click.echo("Starting CCR service...")
            subprocess.run(prepare_command_for_windows(["ccr", "start"]), capture_output=True, env=env)

        click.echo(f"[OK] Using CCR: http://{host}:{port}")

    # Step 4: Permission confirmation (--yes skips confirmation)
    if not ask and not dry_run and not yes:
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

    if resume:
        click.echo(f"\n[Resume] Continue in session {resume[:8]}...: {prompt_text}")
        execution_prompt = prompt_text
    elif direct:
        click.echo(f"\n[Direct] Execute directly: {prompt_text}")
        execution_prompt = prompt_text
    else:
        click.echo(f"\n[Execute] {prompt_text}")

        # Build prompt with available command descriptions, let agent determine and execute
        execution_prompt = _build_agent_prompt(prompt_text)

        # Display built prompt
        click.echo(f"\n[Prompt] Agent prompt:")
        click.echo("-" * 40)
        click.echo(execution_prompt)
        click.echo("-" * 40)

        if dry_run:
            click.echo("[Dry Run] Skip actual execution")
            return

    # Build final command - use stream-json for real-time output
    # Note: stream-json must be used with --verbose
    # Use "-p -" to read prompt from stdin, avoid Windows command line argument truncation of newlines
    cmd = ["claude", "-p", "-", "--output-format", "stream-json", "--verbose"]

    if resume:
        cmd.extend(["--resume", resume])

    if model:
        cmd.extend(["--model", model])

    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    click.echo("-" * 60)

    # Start session monitoring (if not disabled)
    monitor = None
    monitor_enabled = not no_monitor and os.environ.get("FRAGO_MONITOR_ENABLED", "1") != "0"

    if monitor_enabled:
        try:
            from frago.session.monitor import SessionMonitor

            start_time = datetime.now(timezone.utc)
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
                target_session_id=resume,  # Monitor specified session directly when resuming
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
        process.stdin.write(execution_prompt)
        process.stdin.close()

        # Parse stream-json format and display in real-time
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
        if stderr_output:
            click.echo(f"\n[stderr] {stderr_output}", err=True)

        process.wait(timeout=timeout)

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
        # Stop session monitoring
        if monitor:
            try:
                monitor.stop()
            except Exception:
                pass


# =============================================================================
# Auxiliary Command: Check Authentication Status
# =============================================================================

@click.command("agent-status")
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
        click.echo(f"  Tip: Run 'frago init' to initialize configuration")

    click.echo()

    # Check CCR status (if enabled)
    if frago_config and frago_config.get("ccr_enabled"):
        click.echo("CCR Status:")
        ok, info = check_ccr_auth()
        if ok:
            click.echo(f"  [OK] CCR available")
            click.echo(f"    Providers: {', '.join(info.get('providers', []))}")
            click.echo(f"    Running status: {'Running' if info.get('is_running') else 'Not running'}")
        else:
            click.echo("  [X] CCR not available")
            if info and info.get("error"):
                click.echo(f"    Reason: {info['error']}")
