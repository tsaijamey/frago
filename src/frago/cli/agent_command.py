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


def _find_profile(profile_name: str):
    """按名字或 id 找一条 profile；找不到打可读错误并非零退出。

    ``--use-profile`` 两者都收（名精确、id 也精确），这里只做这一件事——翻译到各家
    由 driver 负责，翻译到内核由 :func:`_resolve_profile_id` 负责。
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
    return profile


def _resolve_profile_id(profile_name: str) -> str:
    """把一个 profile 名（或 id）翻成内核要的连接 id。

    内核按 **id** 取连接（``frago-core --as-profile <id>``），与 ``--use-profile``
    收的名字不是一回事：配方里写的是 ``火山-GLM5.3`` 这样的现名，内核只认 ``profiles.json``
    里的 ``id``。名字到 id 的翻译只有这一处。
    """
    return _find_profile(profile_name).id


def _resolve_profile_env(profile_name: str, agent_type: str) -> dict[str, str]:
    """把一个 profile 名（或 id）交给目标 agent 的 driver 翻成会话环境变量。

    翻译规则住在 driver 里（claude 产出 ``ANTHROPIC_*``，opencode 产出
    ``OPENCODE_CONFIG_CONTENT``），这里只负责按名字找到 profile 并派活。

    driver 没有实现 ``profile_env`` 时返回空字典——本轮照跑，NEVER 因此报错，**但会
    在 stderr 上说明这一句话没生效**。人明确要求跑在某个模型上、结果跑在另一个模型上，
    这件事必须当场看得见——静默吞掉会让他拿着一份不知道出自哪个模型的结果。profile
    缺这一家要的协议通道时（codex 只认 Responses），driver 抛 ValueError，这里停下。
    """
    profile = _find_profile(profile_name)
    return _profile_env_via_driver(profile, agent_type, label=f"--use-profile {profile_name!r}")


def _profile_env_via_driver(profile, agent_type: str, *, label: str) -> dict[str, str]:
    """把一条已找到的 profile 交给目标 agent 的 driver 翻成会话环境变量。

    ``label`` 是这句话在人眼里的出处（``--use-profile X`` 还是设置里绑给 worker 的那
    条连接）——翻译不生效时要指名道姓地说是哪一句没生效，否则人只知道结果不对、
    不知道该去改哪里。
    """
    from frago.agent_driver.driver import load_driver

    try:
        driver = load_driver(agent_type)
    except KeyError:
        # 这个 agent_type 没有 driver（内核就是这一类：它不挂 tmux，注册表里没有它）。
        # 与"driver 没实现 profile_env"同一条下坡路——说清这一句没生效，别抛 KeyError
        # 顶穿成一个契约外的 traceback。
        driver = None
    if driver is None or driver.profile_env is None:
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
    tmux_name: str | None,
    duration_ms: int,
    human_note: str | None,
    json_out: bool,
) -> None:
    """发射一次停机结果并按契约退出。

    ``--json`` 时 stdout 只有那一个 JSON 对象，人类文案（含答案之外的一切提示）
    一律走 stderr，调用方直接 ``json.loads(stdout)`` 即可，无需解析人类文案。

    ``tmux_name`` 为 None 表示这一轮不在 tmux 里（内核后端没有 tmux 会话），payload 里
    照实写 ``null``——NEVER 编一个会话名出来。
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


def _worker_child_id(sid: str, *, agent_type: str, native_session_id: bool) -> str | None:
    """这场 worker 在**清单上那一行的编号**；认不出来返回 None。

    编号怎么认只写在 :func:`frago.agent_driver.driver.listed_session_id` 那一处，这里不再
    抄一份。

    agy 不在这条路上记：它的编号由 agy driver 认领时当场记（那时绑定表还在、conversation
    id 才拿得到，见 :func:`frago.session.session_origin.record_attributed_dispatch`）。
    这里跑在会话已经收场之后，绑定表那时已经清了，查也查不到；再记一遍是同一条账写两次。
    """
    if agent_type == "agy":
        return None
    from frago.agent_driver.driver import listed_session_id

    return listed_session_id(agent_type, sid, native_session_id=native_session_id)


def _record_worker_launch(
    *,
    sid: str,
    agent_type: str,
    cwd: str,
    prompt_text: str,
    native_session_id: bool,
) -> None:
    """把这次派活记进账本，供左栏把 worker 折到派活的那一场下面。

    记的是**子会话在清单上那一行的编号**（见 :func:`_worker_child_id`），不是 frago 自己
    那个把手。这里认不出编号的那几家不记——它们由各自的 driver 在认领到编号的那一刻记。
    """
    with contextlib.suppress(Exception):
        child = _worker_child_id(sid, agent_type=agent_type, native_session_id=native_session_id)
        if child is None:
            return
        from frago.session.session_origin import record_dispatch

        record_dispatch(child, agent_type=agent_type, cwd=cwd, prompt_head=prompt_text)


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


def _run_kernel(
    prompt_text: str,
    *,
    agent_type: str,
    session_id: str | None,
    cwd: str,
    timeout: int,
    quiet: bool,
    dry_run: bool,
    json_out: bool,
    profile_id: str | None,
    model: str | None,
    env: dict[str, str] | None,
) -> None:
    """把一轮交给 frago 自己的内核跑（不挂 tmux）。

    与 :func:`_run_tmux_driver` 共用同一份停机契约（``_EXIT_CODES`` 四态），区别只在后端：
    内核是"交一件事、跑完就退"的进程（见 :mod:`frago.agent_driver.kernel_backend`），
    没有 pane 可读、也没有可续的常驻会话，所以：

    - **不落 ``write_turn``。** 内核自己把这一轮写进 ``~/.frago/coreagent/sessions/``，
      会话清单与记录流读的就是那份（见 ``session.record_reader``）。会话子系统里也没有
      CoreAgent 这家的 adapter（``session.monitor._adapters`` 只有三家），再写一遍会落成
      一份对不上任何记录的影子。
    - **记账的编号原样用。** 内核这一场编号就是 frago 现发的（``core_`` 前缀），落盘的就是
      它，不需要像三家 CLI 那样再派生一次（见 :func:`_worker_child_id`）。不记的话，主会话
      派出去的内核 worker 在左栏一个都挂不上——它们全散在主干上。
    """
    from frago.agent_driver import kernel_backend

    sid = session_id or kernel_backend.new_session_id()
    if not quiet:
        click.echo(f"[OK] kernel driver: session={sid}", err=json_out)
    if dry_run:
        # 与 tmux 那条同一条规矩：没真跑过一轮就 NEVER 伪造一份停机摘要。
        click.echo("[Dry Run] Skip actual execution", err=json_out)
        return

    # 名册：内核 worker 没有 tmux 会话，登记的是**内核那个进程号**——`frago agent ls`
    # 据此判活、`stop` 据此收走（见 drive_command._is_alive）。外壳进程被外部杀掉时
    # finally 不执行，名册那条会留下——那正是我们要的：跑飞的孤儿仍可按名字收走。
    from .drive_command import deregister_transient_worker, register_transient_worker

    registered = False

    def _on_spawn(pid: int) -> None:
        nonlocal registered
        register_transient_worker(
            name=sid, agent_type=agent_type, tmux_name=None, cwd=cwd, pid=pid
        )
        registered = True
        # **记账在这一刻，不在跑完之后。** 内核 worker 可能跑上几分钟到几十分钟，账要等
        # 这一轮结束才写的话，它在左栏整段时间里都是一张散在主干上的卡片——人看到的正是
        # "父子关系不对"。这一刻这一场确实起来了：进程在，记录文件由内核自己写，左栏马上
        # 就会摆出它那一行。进程都没起来（Popen 抛错）时这个回调不会被叫，也就不会留下
        # 一张点不开的卡片——原先放在 run 之后想守的就是这一条，挪到这里同样守得住。
        _record_worker_launch(
            sid=sid,
            agent_type=agent_type,
            cwd=cwd,
            prompt_text=prompt_text,
            native_session_id=False,
        )

    try:
        turn = kernel_backend.run_turn(
            prompt_text,
            session_id=sid,
            cwd=cwd,
            profile_id=profile_id,
            model=model,
            timeout_s=float(timeout) if timeout > 0 else None,
            env=env,
            on_spawn=_on_spawn,
        )
    finally:
        # run_turn 无论正常返回还是抛错，内核进程都已收场；此刻把名册里临时登记的那条
        # 抹掉，别让 `ls` 留下死条目。
        if registered:
            deregister_transient_worker(sid)

    # 记账不在这里——已经挪到 `_on_spawn`，进程起来的那一刻就写（见那里的注释）。放在这
    # 里的话，账要等整轮跑完才落，worker 在跑的这几分钟里在左栏是一张散在主干上的卡片。

    notes = {
        "needs_input": f"[!] CoreAgent 要人介入（认证墙 / 连接没配好）：{turn.text[:300]}",
        "timeout": f"[!] Turn timed out after {timeout}s",
        "error": f"[!] CoreAgent 那一轮没跑成：{turn.text[:300]}",
    }
    _emit_and_exit(
        status=turn.status,
        text=turn.text,
        session_id=sid,
        tmux_name=None,
        duration_ms=turn.duration_ms,
        human_note=notes.get(turn.status),
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

# 动词名 → frago agent 的常驻会话子命令（实现在 drive_command）及身份自查子命令。
_AGENT_SUBCOMMANDS = frozenset({"start", "send", "peek", "ls", "stop", "attach", "self", "whoami"})
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
    Resident tmux-session & self-inspection subcommands:
      frago agent self [--signature | --name | --json]
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
    #
    # 选定那个只是一份**偏好**：它指向的内核本机没装时退回自带内核，并把"换过了"说在
    # stderr 上（判据见 frago.init.agent_core，与页面那条同源）。
    if not agent_type:
        if worker_connection is not None and worker_connection.agent_type:
            agent_type = worker_connection.agent_type
        else:
            from frago.init.agent_core import resolve_agent_core
            from frago.init.config_manager import get_agent_core

            agent_type, core_note = resolve_agent_core(get_agent_core())
            if core_note:
                click.echo(f"[!] {core_note}", err=True)

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

    # profile → "这一轮跑哪条连接"，两条后端各收各的形状：
    #   三家 CLI（tmux 后端）→ driver 翻译出来的会话环境变量（ANTHROPIC_* 等），
    #   内核（kernel 后端）→ ``--as-profile <id>``，它读 profiles.json、不认 ANTHROPIC_*。
    # 判据在后端（runs_on_kernel），两条路二选一，NEVER 两边都塞——塞了内核也读不到，
    # 结果是"点名要某个模型"静默失效。
    from frago.agent_driver.driver import runs_on_kernel

    on_kernel = runs_on_kernel(agent_type)
    kernel_profile_id: str | None = None
    if on_kernel:
        if use_profile:
            kernel_profile_id = _resolve_profile_id(use_profile)
        elif worker_connection is not None and worker_connection.api_key:
            # 端点型连接才有内核能用的东西。厂商 CLI 型走的是它自己的账号，内核没法拿它
            # 当一条 Anthropic 线，故不给 id、让它退回自己那条默认连接。
            kernel_profile_id = worker_connection.id
        profile_env: dict[str, str] = {}
    elif use_profile:
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

    if on_kernel and use_ccr_mode:
        # CCR 是把 ANTHROPIC_BASE_URL 指到本地代理；内核不读 ANTHROPIC_*，起不了作用。
        click.echo(
            "[!] 内核不走 CCR：--use-ccr 这一轮不生效，跑在内核自己挑的那条连接上。",
            err=True,
        )
    if on_kernel and (endpoint or api_key):
        # 同上：--endpoint/--api-key 落的是 ANTHROPIC_*，内核一个字都不读。
        click.echo(
            "[!] 内核不读 --endpoint/--api-key：要换连接请用 --use-profile（它按 id 交给内核）。",
            err=True,
        )

    # 只认启动开关、不认 ANTHROPIC_MODEL 的内核从这里拿模型；认环境变量
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
        # 授权头会盖掉密钥头（claude 认 AUTH_TOKEN 优先），置空它才能让显式 key 生效。
        # 置空而不是删键：tmux ``-e`` 只覆盖给到的键，删掉就等于放行会话环境里继承来的
        # 旧值——tmux 会话继承服务端那份全局环境，里面可能烤着上一条 profile 的凭据。
        # CCR 模式塞的那把 "test" 也在这里一并被盖掉。
        tmux_env["ANTHROPIC_AUTH_TOKEN"] = ""
    if model:
        tmux_env["ANTHROPIC_MODEL"] = model
    # 子会话必须自知是 worker，阻断 worker 再拉 worker 的角色递归（见 CLAUDE.md 任务执行模式）。
    tmux_env["FRAGO_AGENT_ROLE"] = "worker"

    # 后端分派：内核（不挂 tmux）与三家 CLI（挂 tmux）各走各的执行路径，共用同一份
    # 停机契约（_EXIT_CODES）。判据只有 runs_on_kernel 一处。
    if on_kernel:
        if tmux_target:
            # 内核没有 TUI 可借住：--tmux-target 是"在别人的 tmux 会话里看着它干活"，
            # 内核根本没这个外观。说清而不是静默略过。
            click.echo(
                f"[!] 内核不借住 tmux 会话：--tmux-target {tmux_target} 这一轮不生效。",
                err=True,
            )
        if no_monitor:
            click.echo("[!] --no-monitor 对内核无意义：它自己写记录，这条忽略。", err=True)
        _run_kernel(
            prompt_text,
            agent_type=agent_type,
            session_id=resume_session_id or session_id,
            cwd=os.getcwd(),
            timeout=timeout,
            quiet=quiet,
            dry_run=dry_run,
            json_out=json_out,
            profile_id=kernel_profile_id,
            model=model,
            env=tmux_env or None,
        )
        return

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
# frago agent self —— 自查当前所处的 CLI Agent 身份与提交签名
# =============================================================================
def _run_agent_self(*, signature: bool, display_name: bool, json_output: bool) -> None:
    from frago.session.self_id import resolve_self_agent

    found = resolve_self_agent()
    if found is None:
        from .agent_friendly import BusinessError

        raise BusinessError(
            "cannot resolve current CLI agent — no CLI agent process ancestor "
            "or session environment variable found",
            'export FRAGO_CLI_AGENT="claude"  # declare explicitly (claude/codex/opencode/agy/coreagent)',
            "frago agent self --json",
        )

    if json_output:
        click.echo(json.dumps(found.to_dict(), ensure_ascii=False, indent=2))
        return
    if signature:
        click.echo(found.generated_with)
        return
    if display_name:
        click.echo(found.display_name)
        return
    click.echo(found.agent_type)


@agent.command("self", cls=AgentFriendlyCommand)
@click.option(
    "--signature",
    is_flag=True,
    help="Print the commit 'Generated with [...]' signature line for this CLI agent",
)
@click.option(
    "--name",
    "display_name",
    is_flag=True,
    help="Print the human-readable display name of this CLI agent (e.g. Claude Code, Codex CLI)",
)
@click.option("--json", "json_output", is_flag=True, help="Output full identity and signature in JSON format")
def agent_self(signature: bool, display_name: bool, json_output: bool) -> None:
    """Identify which CLI agent is executing the current command.

    \b
    Examples:
      frago agent self              # e.g. claude / codex / opencode / agy / coreagent
      frago agent self --name       # e.g. Claude Code / Codex CLI / opencode / Antigravity CLI
      frago agent self --signature  # e.g. 🤖 Generated with [Claude Code](https://claude.com/claude-code)
      frago agent self --json       # full JSON (agent_type, display_name, url, generated_with, source, session_id)
    """
    _run_agent_self(signature=signature, display_name=display_name, json_output=json_output)


@agent.command("whoami", cls=AgentFriendlyCommand, hidden=True)
@click.option("--signature", is_flag=True)
@click.option("--name", "display_name", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def agent_whoami(signature: bool, display_name: bool, json_output: bool) -> None:
    """Hidden alias for `frago agent self`."""
    _run_agent_self(signature=signature, display_name=display_name, json_output=json_output)


# =============================================================================
# Resident-session subcommands: frago agent start/send/peek/ls/stop
# =============================================================================
# 实现在 drive_command（薄封装 agent_driver）；这里只负责把它们挂到 agent 组下。
from .drive_command import DRIVE_SUBCOMMANDS  # noqa: E402

for _subcmd in DRIVE_SUBCOMMANDS:
    agent.add_command(_subcmd)
