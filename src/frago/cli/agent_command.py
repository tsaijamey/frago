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


def _resolve_profile_env(profile_name: str, agent_type: str) -> dict[str, str]:
    """把一个 profile 名（或 id）交给目标 agent 的 driver 翻成会话环境变量。

    翻译规则住在 driver 里（claude 产出 ``ANTHROPIC_*``，opencode 产出
    ``OPENCODE_CONFIG_CONTENT``），这里只负责按名字找到 profile 并派活。

    driver 没有实现 ``profile_env`` 时返回空字典——本轮照跑，NEVER 因此报错，**但会
    在 stderr 上说明这一句话没生效**。人明确要求跑在某个模型上、结果跑在另一个模型上，
    这件事必须当场看得见——静默吞掉会让他拿着一份不知道出自哪个模型的结果。profile
    缺这一家要的协议通道时（codex 只认 Responses），driver 抛 ValueError，这里停下。
    """
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

    return _profile_env_via_driver(profile, agent_type, label=f"--use-profile {profile_name!r}")


def _profile_env_via_driver(profile, agent_type: str, *, label: str) -> dict[str, str]:
    """把一条已找到的 profile 交给目标 agent 的 driver 翻成会话环境变量。

    ``label`` 是这句话在人眼里的出处（``--use-profile X`` 还是设置里绑给 worker 的那
    条连接）——翻译不生效时要指名道姓地说是哪一句没生效，否则人只知道结果不对、
    不知道该去改哪里。
    """
    from frago.agent_driver.driver import load_driver

    driver = load_driver(agent_type)
    if driver.profile_env is None:
        click.echo(
            f"[!] {agent_type} 不支持 frago profile：{label} 这一轮不生效，"
            f"会话跑在 {agent_type} 自己配置的模型上。",
            err=True,
        )
        return {}
    try:
        return driver.profile_env(profile)
    except ValueError as e:
        # 这条 profile 没有这一家要的协议通道（codex 要 Responses）。人点名要跑在它上面，
        # 退回 agent 自己的模型等于换了个模型答题，所以当场停下说清缺什么。
        click.echo(f"Error: {label} 用不到 {agent_type} 上：{e}", err=True)
        sys.exit(1)


def _worker_bound_connection():
    """设置里绑给 worker 角色的那条连接，没绑（或绑的是官方订阅）时返回 None.

    绑定只在这里被读一次，且只作用于本次要开的这一场会话——它 NEVER 写进任何 agent
    的常驻配置，所以人自己敲 claude 起的会话不受影响。这正是 worker 与主 agent 的
    区别：主 agent 那条是写进配置的，worker 这条是每次开会话时现读的。
    """
    from frago.init.profile_manager import KIND_OFFICIAL, WORKER_ROLE, role_connection

    connection = role_connection(WORKER_ROLE)
    return None if connection.kind == KIND_OFFICIAL else connection


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


def _parent_session_id() -> str | None:
    """派这次活的是哪一场会话。认不出来返回 None。

    主 agent 是在自己的会话里敲的这条命令，它自己的会话编号就在环境里
    （``FRAGO_SESSION_ID`` / ``CLAUDE_CODE_SESSION_ID``）。**只认环境里明说的那个**：
    ``resolve_self`` 还有一条按"当前目录最近写入的记录"推断的兜底，同一个目录下开着
    两场会话时会挑错——把 worker 挂到一场毫无关系的会话下面，比不挂糟得多。
    """
    with contextlib.suppress(Exception):
        from frago.session.self_id import resolve_self

        me = resolve_self()
        if me is not None and me.certain:
            return me.session_id
    return None


def _record_worker_launch(
    *,
    sid: str,
    agent_type: str,
    cwd: str,
    prompt_text: str,
    native_session_id: bool,
) -> None:
    """把这次派活记进账本，供左栏把 worker 折到派活的那一场下面。

    记的是**子会话在目标 agent 那边的真实编号**，不是 frago 自己那个把手——清单上摆的
    是前者。claude 那家的编号由 frago 的编号派生而来，派生规则问 driver 要（NEVER 在这里
    抄一份）；其余几家的真实编号要等 agent 起来之后才认领得到，这里还不知道，故不记——
    宁可少认几场，也不往账本里写一个对不上任何会话的编号。
    """
    if agent_type != "claude":
        return
    with contextlib.suppress(Exception):
        from frago.agent_driver.drivers.claude import session_id_for
        from frago.session.session_origin import record_relation

        # 会话关系账里种类写明是「派活」：同一本账还记着人起的分支，那一种子会话算人开的。
        record_relation(
            kind="dispatch",
            child_session_id=session_id_for(sid, native=native_session_id),
            parent_session_id=_parent_session_id(),
            agent_type=agent_type,
            cwd=cwd,
            prompt_head=prompt_text,
        )


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
    model: str | None = None,
    native_session_id: bool = False,
    json_out: bool = False,
    source: str = "terminal",
    tmux_target: str | None = None,
) -> None:
    """Drive a resident tmux TUI session via SessionLauncher (one turn).

    tmux 是唯一后端（spec 20260607 Phase 5，旧 headless 后端已整体退场）。无 warm pool：
    开新会话、投一轮、关闭。停机时按 ``_EXIT_CODES`` 退出。

    ``timeout<=0`` = 这一轮不设墙钟上限（缺省）。长任务不该被一个拍脑袋的秒数腰斩：
    到点判死时 worker 往往还在干活，主控却拿到一个 timeout 就散了，那一轮的产出既
    没交付也没人回收。停机仍由 agent 自己说了算——答完 / 需要真人 / 会话死掉。
    """
    from frago.agent_driver import SessionLauncher
    from frago.agent_driver.tmux_session import tmux_name_for

    sid = session_id or str(uuid.uuid4())
    tmux_name = tmux_target or tmux_name_for(sid)
    if not quiet:
        where = f" in {tmux_target}" if tmux_target else ""
        click.echo(f"[OK] tmux driver: agent={agent_type} session={sid}{where}", err=json_out)
    if dry_run:
        # 诊断用途，没真跑过任何一轮 → NEVER 伪造一份停机摘要，只报到 stderr 后正常退出。
        click.echo("[Dry Run] Skip actual execution", err=json_out)
        return

    # 自有新会话（非借住别人的 tmux）才登记名册：一次性 worker 也该被 `frago agent ls`
    # 看见、按名字停掉。外壳进程被外部杀掉时 finally 不执行，名册里那条会留下——那正是
    # 我们要的：跑飞的孤儿仍可按名字收走（见 frago book agent-worker-driving）。
    own_session = tmux_target is None
    if own_session:
        from .drive_command import register_transient_worker

        register_transient_worker(
            name=sid, agent_type=agent_type, tmux_name=tmux_name, cwd=cwd
        )

    launcher = SessionLauncher()
    try:
        result = launcher.run(
            prompt_text,
            agent_type=agent_type,
            session_id=sid,
            cwd=cwd,
            env=env,
            model=model,
            native_session_id=native_session_id,
            timeout_s=float(timeout) if timeout > 0 else None,
            tmux_target=tmux_target,
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
    finally:
        # launcher.run 无论正常返回还是抛错，会话都已在它的 finally 里关掉；此刻把名册里
        # 临时登记的那条抹掉，别让 `ls` 留下死条目。Shell 被 SIGKILL 时这一步不会执行，
        # 名册条目得以保留——孤儿因此仍可被 `stop` 收走。
        if own_session:
            from .drive_command import deregister_transient_worker

            deregister_transient_worker(sid)

    # 这一场确实起来了（哪怕这一轮超时或要人介入，会话本身是在的），记一笔它是谁
    # 派出去的。放在 run 之后：起都没起来的会话记进账本，只会让清单上多一行点不开的卡片。
    _record_worker_launch(
        sid=sid,
        agent_type=agent_type,
        cwd=cwd,
        prompt_text=prompt_text,
        native_session_id=native_session_id,
    )

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
    default=0,
    help="Wall-clock cap for this turn, in seconds. Default 0 = no cap: wait until "
         "the turn actually finishes (or the agent needs a human, or the session dies). "
         "Pass a positive number only if you want the turn cut off at that mark."
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
    default=None,
    help="Run this one turn on a specific cli-agent (claude / opencode / codex). "
         "Omit to use the core selected in the WebUI wizard (claude when unset)."
)
@click.option(
    "--tmux-target",
    type=str,
    default=None,
    help="Run the agent inside this EXISTING tmux session instead of a fresh one "
         "(e.g. frago-stage, the virtual desktop's terminal, so a person can watch it "
         "work). The session must be showing an idle shell. When the turn ends the "
         "agent is asked to quit; the session itself is never killed."
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
    agent_type: str | None,
    tmux_target: str | None,
):
    """
    Intelligent Agent: Execute one task turn in a resident tmux cli-agent session.

    \b
    Examples:
      frago agent Help me find Python jobs on Upwork
      frago agent "fix the login bug" --model sonnet
      frago agent "summarize this" --json
      frago agent "quick check" --timeout 300   # opt into a wall-clock cap

    \b
    A turn has no time cap by default — it runs until the agent is done, needs a
    human, or its session dies. `--timeout N` opts into cutting it off at N seconds.

    \b
    Exit codes (also reported as "status" under --json):
      0 ok           answered; the answer is on stdout
      1 timeout      only with an explicit --timeout: the cap fired; session still
                     alive, continue with `frago agent send`
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

    # 显式 --use-profile 是"这一轮跑哪条连接"，没给就看设置里绑给 worker 的那一条。
    # 绑定只在这一层生效：它决定这一场会话的内核、模型与端点，写不到任何常驻配置里。
    worker_connection = None if use_profile else _worker_bound_connection()

    # --agent-type 是"这一次破例用谁"；其次是 worker 那条连接自带的内核（厂商 CLI 型
    # 连接的内核就是它本身，换模型也只能在它自己身上换）；最后才是界面上选定的内核。
    if not agent_type:
        if worker_connection is not None and worker_connection.agent_type:
            agent_type = worker_connection.agent_type
        else:
            from frago.init.config_manager import get_agent_core

            agent_type = get_agent_core()

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

    # --use-profile 解析出的变量盖过 CCR，但让位于下面的显式 CLI 覆盖。翻译由目标
    # agent 的 driver 负责，故要把 agent_type 一起递进去。
    if use_profile:
        profile_env = _resolve_profile_env(use_profile, agent_type)
    elif worker_connection is not None and worker_connection.api_key:
        # 端点型连接才有可注入的东西。厂商 CLI 型走的是它自己的账号，没有 frago
        # 能递给它的密钥，模型另经启动开关（见下面的 launch_model）。
        profile_env = _profile_env_via_driver(
            worker_connection, agent_type, label=f"worker 绑定的连接 {worker_connection.name!r}"
        )
    else:
        profile_env = {}
    tmux_env.update(profile_env)

    # 只认启动开关、不认 ANTHROPIC_MODEL 的内核（codebuddy）从这里拿模型；认环境变量
    # 的内核忽略它，模型仍从下面的 ANTHROPIC_MODEL 走，两条路不会打架。
    launch_model = model or (worker_connection.default_model if worker_connection else None)

    if worker_connection is not None and not quiet:
        where = f"{worker_connection.name} on {agent_type}"
        if launch_model:
            where += f" ({launch_model})"
        click.echo(f"[OK] worker connection: {where}", err=json_out)

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
        model=launch_model,
        json_out=json_out,
        source=source,
        tmux_target=tmux_target,
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
