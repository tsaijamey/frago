#!/usr/bin/env python3
"""
Frago Agent Command - Execute AI tasks in a resident tmux cli-agent session.

tmux 是唯一后端（spec 20260607 Phase 5）：每次调用开一个常驻 TUI 会话、投一轮、
按停机态退出。凭据经 ``new-session -e`` 注入会话环境。

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
import uuid
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


# 停机态 → 退出码契约（spec 20260607 Phase 7）。调用方 Agent 靠它判断下一步，
# NEVER 改动既有映射：ok 已答完；timeout 会话仍活可 `frago agent send` 续；
# needs_input 撞上认证墙/权限门/澄清门，须真人介入；error 是 driver/tmux 层失败。
_EXIT_CODES: dict[str, int] = {"ok": 0, "timeout": 1, "needs_input": 2, "error": 3}


def _emit_and_exit(
    *,
    status: str,
    text: str,
    session_id: str,
    tmux_name: str,
    duration_ms: int,
    human_note: str | None,
    json_out: bool,
) -> None:
    """发射一次停机结果并按契约退出。

    ``--json`` 时 stdout 只有那一个 JSON 对象，人类文案（含答案之外的一切提示）
    一律走 stderr，调用方直接 ``json.loads(stdout)`` 即可，无需解析人类文案。
    """
    exit_code = _EXIT_CODES[status]
    if json_out:
        payload = {
            "status": status,
            "exit_code": exit_code,
            "session_id": session_id,
            "tmux_name": tmux_name,
            "text": text,
            "duration_ms": duration_ms,
        }
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif text:
        click.echo(text)
    if human_note:
        click.echo(human_note, err=True)
    sys.exit(exit_code)


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
    native_session_id: bool = False,
    json_out: bool = False,
    source: str = "terminal",
) -> None:
    """Drive a resident tmux TUI session via SessionLauncher (one turn).

    tmux 是唯一后端（spec 20260607 Phase 5，旧 headless 后端已整体退场）。无 warm pool：
    开新会话、投一轮、关闭。停机时按 ``_EXIT_CODES`` 退出。
    """
    from frago.agent_driver import SessionLauncher
    from frago.agent_driver.tmux_session import tmux_name_for

    sid = session_id or str(uuid.uuid4())
    tmux_name = tmux_name_for(sid)
    if not quiet:
        click.echo(f"[OK] tmux driver: agent={agent_type} session={sid}", err=json_out)
    if dry_run:
        # 诊断用途，没真跑过任何一轮 → NEVER 伪造一份停机摘要，只报到 stderr 后正常退出。
        click.echo("[Dry Run] Skip actual execution", err=json_out)
        return

    launcher = SessionLauncher()
    try:
        result = launcher.run(
            prompt_text,
            agent_type=agent_type,
            session_id=sid,
            cwd=cwd,
            env=env,
            native_session_id=native_session_id,
            timeout_s=float(timeout),
        )
    except KeyError:
        _emit_and_exit(
            status="error", text="", session_id=sid, tmux_name=tmux_name,
            duration_ms=0, json_out=json_out,
            human_note=f"Error: no driver registered for agent-type {agent_type!r}",
        )
        return
    except FileNotFoundError:
        _emit_and_exit(
            status="error", text="", session_id=sid, tmux_name=tmux_name,
            duration_ms=0, json_out=json_out,
            human_note="Error: tmux not found. Please install tmux first.",
        )
        return
    except Exception as exc:
        # driver/tmux 层的任何其它失败（如 TmuxStartupError：会话起了但等不到就绪
        # 信号）同属 error=3。机器契约要求「必定落在四态之一」，故此处兜底，
        # NEVER 让 traceback 顶穿成一个契约外的退出码。
        _emit_and_exit(
            status="error", text="", session_id=sid, tmux_name=tmux_name,
            duration_ms=0, json_out=json_out,
            human_note=f"Error: agent driver failed: {exc}",
        )
        return

    # Normalize this turn into the session subsystem (Web UI / session list).
    if not no_persist:
        with contextlib.suppress(Exception):
            from frago.agent_driver.transcript import write_turn

            write_turn(sid, agent_type, cwd, prompt_text, result, source=source)

    notes = {
        "needs_input": "[!] Agent needs input (auth wall / permission / clarification)",
        "timeout": f"[!] Turn timed out after {timeout}s",
        "error": "[!] Agent driver reported an error",
    }
    _emit_and_exit(
        status=result.status,
        text=result.text,
        session_id=sid,
        tmux_name=tmux_name,
        duration_ms=result.duration_ms,
        human_note=notes.get(result.status),
        json_out=json_out,
    )


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
    ``frago agent "<prompt>" [--options]`` 或 ``frago agent --source web
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
      frago agent "fix the login bug" --model sonnet
      frago agent --source web --prompt-file task.txt
      frago agent "summarize this" --json      # machine-readable shutdown summary

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
    "--quiet", "-q",
    is_flag=True,
    help="Quiet mode, don't show real-time monitoring status"
)
@click.option(
    "--no-monitor",
    is_flag=True,
    help="Disable session monitoring (don't record session data)"
)
@click.option(
    "--json", "json_out",
    is_flag=True,
    help="Emit a machine-readable shutdown summary on stdout (status / exit_code / "
         "session_id / tmux_name / text / duration_ms). Human notes go to stderr."
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    hidden=True,
    help="DEPRECATED no-op, accepted and ignored. It only ever answered the "
         "permission gate of the retired headless backend."
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
def agent_run(
    prompt: tuple,
    prompt_file,
    model: str | None,
    timeout: int,
    use_ccr: bool,
    dry_run: bool,
    quiet: bool,
    no_monitor: bool,
    json_out: bool,
    yes: bool,  # noqa: ARG001 — deprecated no-op, accepted so legacy callers don't break
    source: str,
    session_id: str | None,
    resume_session_id: str | None,
    endpoint: str | None,
    api_key: str | None,
    use_profile: str | None,
    agent_type: str,
):
    """
    Intelligent Agent: Execute one task turn in a resident tmux cli-agent session.

    \b
    Examples:
      frago agent Help me find Python jobs on Upwork
      frago agent "fix the login bug" --model sonnet
      frago agent "summarize this" --json --timeout 300

    \b
    Exit codes (also reported as "status" under --json):
      0 ok           answered; the answer is on stdout
      1 timeout      turn timed out; session still alive, continue with `frago agent send`
      2 needs_input  auth wall / permission gate / clarification — needs a human
      3 error        driver or tmux layer failed

    \b
    Available models (--model):
      sonnet, opus, haiku or full model name

    \b
    Note: this command always launches the cli-agent with --dangerously-skip-permissions
    (hardcoded in each driver's launch_command); there is no CLI switch to restore the
    permission gate.
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

    # --session-id / --resume 互斥：一个是让 driver 派生的 frago 侧标识，一个是原样
    # 续接的 agent 真实会话 id，同时给出无法判定该走哪条。
    if session_id and resume_session_id:
        click.echo("Error: --session-id and --resume are mutually exclusive", err=True)
        raise click.Abort()

    # 会话 env 的优先级：CCR < profile < CLI(--endpoint/--api-key/--model)。
    # 全部经 new-session -e 注入 tmux 会话。
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
                click.echo("Starting CCR service...", err=json_out)
            subprocess.run(prepare_command_for_windows(["ccr", "start"]), capture_output=True)
        if not quiet:
            click.echo(f"[OK] Using CCR: http://{host}:{port}", err=json_out)

    # --use-profile 解析出的 ANTHROPIC_* 盖过 CCR，但让位于下面的显式 CLI 覆盖。
    profile_env = _resolve_profile_env(use_profile) if use_profile else {}
    tmux_env.update(profile_env)

    # CLI 覆盖（最高优先级）。--model 走 ANTHROPIC_MODEL——profile 本就用该变量表达
    # 模型覆盖，同源同义。
    if endpoint:
        tmux_env["ANTHROPIC_BASE_URL"] = endpoint
    if api_key:
        tmux_env["ANTHROPIC_API_KEY"] = api_key
        # CCR 模式塞的 AUTH_TOKEN 会盖掉 API_KEY，清掉它才能让显式 key 生效。
        tmux_env.pop("ANTHROPIC_AUTH_TOKEN", None)
    if model:
        tmux_env["ANTHROPIC_MODEL"] = model
    # 子会话必须自知是 worker，阻断 worker 再拉 worker 的角色递归（见 CLAUDE.md 任务执行模式）。
    tmux_env["FRAGO_AGENT_ROLE"] = "worker"

    # --resume <uuid> 的语义 = 用真实 id 续接既有会话，即 driver 侧的
    # session_id=<uuid> + native_session_id=True（claude driver 据此走
    # `--resume <id>` 原样带真实 id，不做 uuid5 派生）。
    _run_tmux_driver(
        prompt_text,
        agent_type=agent_type,
        session_id=resume_session_id or session_id,
        native_session_id=bool(resume_session_id),
        cwd=os.getcwd(),
        timeout=timeout,
        quiet=quiet,
        dry_run=dry_run,
        no_persist=no_monitor,
        env=tmux_env or None,
        json_out=json_out,
        source=source,
    )


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
