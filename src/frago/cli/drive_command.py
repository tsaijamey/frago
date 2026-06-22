"""frago agent start/send/peek/ls/stop —— ad-hoc 常驻 tmux 会话的薄 CLI veneer。

这些动词作为 ``frago agent`` 的子命令注册（见 agent_command.py），动词名不含
``drive`` 前缀；本模块只承载实现，归属由 agent_command 决定。

这是对 agent_driver（AgentSessionDriver / TmuxAgentSession / WarmSessionPool /
load_recipe）的薄封装，NEVER 新造 tmux 驱动机制。

跨进程定位：WarmSessionPool 是进程内的，CLI 每次是独立进程。tmux 会话本身跨进程
存活（``frago-agent-<name>``），再配一个轻量 sidecar（``~/.frago/drive/<name>.json``
存 agent_type / tmux_name / pid / cwd）就能让 send/peek/ls/stop 跨进程定位会话。
alive 直接问 tmux has-session。

负反馈是灵魂：用错给"怎么用对"的指引而非空输出或裸异常。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from frago.agent_driver import WarmSessionPool, load_recipe
from frago.agent_driver.recipe import AgentRecipe
from frago.agent_driver.tmux_session import (
    TmuxAgentSession,
    TmuxRunner,
    _default_runner,
)

# ── 注入点：测试以 fake runner / tmp drive dir 替换真实 tmux 调用 ──────────────


def make_runner() -> TmuxRunner | None:
    """返回驱动 tmux 用的 runner。生产返回 None（走真实 tmux）；测试 monkeypatch。"""
    return None


def _drive_dir() -> Path:
    """sidecar 注册表目录。可经 ``FRAGO_DRIVE_DIR`` 覆盖（测试用）。"""
    override = os.environ.get("FRAGO_DRIVE_DIR")
    base = Path(override) if override else Path.home() / ".frago" / "drive"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ── sidecar 注册表 ─────────────────────────────────────────────────────────


@dataclass
class DriveEntry:
    name: str
    agent_type: str
    tmux_name: str
    pid: int
    cwd: str

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "agent_type": self.agent_type,
            "tmux_name": self.tmux_name,
            "pid": self.pid,
            "cwd": self.cwd,
        }


def _sidecar_path(name: str) -> Path:
    return _drive_dir() / f"{name}.json"


def _write_entry(entry: DriveEntry) -> None:
    _sidecar_path(entry.name).write_text(
        json.dumps(entry.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_entry(name: str) -> DriveEntry | None:
    path = _sidecar_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DriveEntry(
            name=data["name"],
            agent_type=data["agent_type"],
            tmux_name=data["tmux_name"],
            pid=int(data["pid"]),
            cwd=data["cwd"],
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def _all_entries() -> list[DriveEntry]:
    out: list[DriveEntry] = []
    for path in sorted(_drive_dir().glob("*.json")):
        entry = _read_entry(path.stem)
        if entry is not None:
            out.append(entry)
    return out


# ── tmux 辅助 ──────────────────────────────────────────────────────────────


def _is_alive(tmux_name: str, runner: TmuxRunner | None) -> bool:
    run = runner or _default_runner
    try:
        run(["tmux", "has-session", "-t", tmux_name])
        return True
    except Exception:
        return False


def _known_agent_types() -> list[str]:
    import frago.agent_driver.recipes  # noqa: F401  触发各 recipe 自注册
    from frago.agent_driver.recipe import _REGISTRY

    return sorted(_REGISTRY)


def _bind_session(
    entry: DriveEntry, recipe: AgentRecipe, runner: TmuxRunner | None
) -> TmuxAgentSession:
    """绑定到一个已存活的 tmux 会话，复用 TmuxAgentSession 原语（不再 open）。"""
    return TmuxAgentSession(
        session_id=entry.name, recipe=recipe, cwd=entry.cwd, runner=runner
    )


def _echo_active_sessions() -> None:
    """负反馈：打印当前活会话清单，等价于 ``drive ls`` 的核心输出。"""
    runner = make_runner()
    entries = _all_entries()
    if not entries:
        click.echo("  (no active drive sessions)", err=True)
        return
    click.echo("  Active drive sessions:", err=True)
    for entry in entries:
        alive = "alive" if _is_alive(entry.tmux_name, runner) else "dead"
        click.echo(
            f"    {entry.name}\t{entry.agent_type}\tpid={entry.pid}\t{alive}",
            err=True,
        )


def _resolve_or_die(name: str) -> DriveEntry:
    """取 sidecar；不存在则报错 + 打印活会话清单后退出。"""
    entry = _read_entry(name)
    if entry is None:
        click.echo(f"Error: no drive session named {name!r}.", err=True)
        _echo_active_sessions()
        sys.exit(1)
    return entry


# ── 子命令（挂到 frago agent 下，见 agent_command.AGENT_SUBCOMMANDS）─────────


@click.command("start")
@click.argument("agent_type")
@click.option("--name", default=None, help="Session name (default: agent_type, auto-suffixed if taken).")
def drive_start(agent_type: str, name: str | None) -> None:
    """Start a resident session and wait until the recipe's ready_signal fires."""
    # agent_type 无 recipe → 列出已注册 agent_type（负反馈）。
    try:
        load_recipe(agent_type)
    except KeyError:
        click.echo(f"Error: no recipe registered for agent_type {agent_type!r}.", err=True)
        click.echo(f"  Known agent types: {', '.join(_known_agent_types()) or '<none>'}", err=True)
        sys.exit(1)

    resolved = name or agent_type
    if _read_entry(resolved) is not None:
        # 自增后缀避免覆盖已有会话。
        idx = 2
        while _read_entry(f"{resolved}-{idx}") is not None:
            idx += 1
        resolved = f"{resolved}-{idx}"

    cwd = os.getcwd()
    runner = make_runner()
    pool = WarmSessionPool(runner=runner)
    try:
        session = pool.acquire(agent_type, resolved, cwd)
    except FileNotFoundError:
        click.echo("Error: tmux not found. Please install tmux first (e.g. brew install tmux).", err=True)
        sys.exit(1)

    _write_entry(
        DriveEntry(
            name=resolved,
            agent_type=agent_type,
            tmux_name=session.tmux_name,
            pid=os.getpid(),
            cwd=cwd,
        )
    )
    # 进程退出后 tmux 会话保活（不 shutdown pool）。
    click.echo(resolved)


@click.command("send")
@click.argument("name")
@click.argument("prompt")
@click.option("--timeout", type=float, default=120.0, help="Seconds to wait for the turn to finish.")
def drive_send(name: str, prompt: str, timeout: float) -> None:
    """Feed one turn to a live session and print the extracted answer (kept alive)."""
    entry = _resolve_or_die(name)
    runner = make_runner()

    if not _is_alive(entry.tmux_name, runner):
        click.echo(f"Error: drive session {name!r} is no longer alive.", err=True)
        _echo_active_sessions()
        sys.exit(1)

    recipe = load_recipe(entry.agent_type)
    session = _bind_session(entry, recipe, runner)

    # 会话尚未 ready 就 send → 提示启动中 + 末屏（负反馈）。
    pane = session.capture_pane()
    if not recipe.ready_signal.matches(pane):
        click.echo(f"[!] Session {name!r} is still starting up — not ready for input yet.", err=True)
        click.echo("--- current pane ---", err=True)
        click.echo(pane, err=True)
        sys.exit(1)

    result = session.send(prompt, timeout_s=timeout)

    # 等不到 done_signal 超时 → 报 timeout + 末屏 + 提示接管（负反馈）。
    if result.status == "timeout":
        click.echo(result.text)
        click.echo(f"[!] Turn timed out after {timeout}s.", err=True)
        click.echo("--- current pane ---", err=True)
        click.echo(session.capture_pane(), err=True)
        click.echo(
            f"  Tip: inspect with `frago agent peek {name}` "
            f"or attach via `tmux attach -t {entry.tmux_name}`.",
            err=True,
        )
        sys.exit(1)

    click.echo(result.text)


@click.command("peek")
@click.argument("name")
def drive_peek(name: str) -> None:
    """Capture and print the session's current pane."""
    entry = _resolve_or_die(name)
    runner = make_runner()
    recipe = load_recipe(entry.agent_type)
    session = _bind_session(entry, recipe, runner)
    click.echo(session.capture_pane())


@click.command("ls")
def drive_ls() -> None:
    """List active drive sessions (name / agent_type / pid / alive)."""
    runner = make_runner()
    entries = _all_entries()
    if not entries:
        click.echo("(no active drive sessions)")
        return
    click.echo("NAME\tAGENT_TYPE\tPID\tALIVE")
    for entry in entries:
        alive = "alive" if _is_alive(entry.tmux_name, runner) else "dead"
        click.echo(f"{entry.name}\t{entry.agent_type}\t{entry.pid}\t{alive}")


@click.command("stop")
@click.argument("name")
def drive_stop(name: str) -> None:
    """Kill a session and remove its sidecar entry."""
    entry = _resolve_or_die(name)
    runner = make_runner()
    recipe = load_recipe(entry.agent_type)
    session = _bind_session(entry, recipe, runner)
    with contextlib.suppress(Exception):
        session.close()
    _sidecar_path(name).unlink(missing_ok=True)
    click.echo(f"Stopped {name!r}.")


# 暴露给 agent_command：挂到 `frago agent` 下的 5 个子命令（动词名见各 command）。
DRIVE_SUBCOMMANDS = [drive_start, drive_send, drive_peek, drive_ls, drive_stop]
