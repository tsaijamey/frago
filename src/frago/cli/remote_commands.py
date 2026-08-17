"""Tell another frago what to do.

A frago on a server is not a headless copy of the local one — it is a second
agent, with its own machine, its own hook rules, its own def knowledge and its
own browser. The useful relationship between the two is therefore not RPC. The
local frago says *what needs to happen*; the remote one decides *how it happens
on that machine*, because it is the only one that knows what is installed there,
what is already running, and where things go.

That is exactly the shape of PA's intake queue, which already exists: a message
goes in, PA reads it with the server's own context loaded, decides, launches
whatever worker it needs, and replies. `frago chat` has been driving that queue
over HTTP+WebSocket all along — against localhost. This module points the same
two calls at another host and attaches a token.

    frago remote add box --url http://127.0.0.1:18093 --token <token>
    frago remote send box "把 weekly_report 跑一遍并发布页面"
    frago remote chat box

Recommended transport is an SSH tunnel (`ssh -L 18093:127.0.0.1:8093 box`),
which leaves nothing about the control plane exposed to the internet. The token
is still required over the tunnel: it is what stops another account on either
box from steering the agent.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

REMOTES_PATH = Path.home() / ".frago" / "remotes.json"


def _remotes_path() -> Path:
    override = os.environ.get("FRAGO_REMOTES_FILE")
    return Path(override).expanduser() if override else REMOTES_PATH


def _load() -> dict[str, dict[str, Any]]:
    path = _remotes_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save(remotes: dict[str, dict[str, Any]]) -> None:
    """Persist the remote list. 0600 from creation — it holds tokens."""
    path = _remotes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(remotes, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def _is_local_url(url: str) -> bool:
    """Whether this address stays on the machine (an SSH tunnel endpoint does)."""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _resolve(name: str) -> dict[str, Any]:
    remote = _load().get(name)
    if remote is None:
        known = ", ".join(sorted(_load())) or "none configured"
        raise click.ClickException(f"Unknown remote '{name}' (known: {known})")
    return remote


def _target(name: str) -> tuple[str, dict[str, str]]:
    from .chat import auth_headers

    remote = _resolve(name)
    return remote["url"].rstrip("/"), auth_headers(remote.get("token"))


@click.group(name="remote", cls=AgentFriendlyGroup)
def remote_group() -> None:
    """Drive another frago — usually one deployed on a server."""


def _read_token(given: str | None) -> str:
    """Get the remote's token without putting it in the process table.

    A token on the command line is visible to every other account on the machine
    for as long as the process lives (`ps -ww`, `/proc/<pid>/cmdline`) and then
    sits in the shell history for months. Since this token is equivalent to code
    execution on the remote, three quieter routes come first; `--token <value>`
    stays because scripts use it, and because refusing it would only push people
    to `echo` it into a file.
    """
    if given == "-":
        return sys.stdin.read().strip()
    if given:
        return given
    from_env = os.environ.get("FRAGO_REMOTE_TOKEN")
    if from_env:
        return from_env.strip()
    return click.prompt("Token", hide_input=True).strip()


@remote_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("name")
@click.option("--url", required=True, help="Base URL, e.g. http://127.0.0.1:18093 over an SSH tunnel")
@click.option(
    "--token",
    default=None,
    help=(
        "That server's token (`frago server token` there). Omit to be prompted; "
        "pass `-` to read stdin; or set FRAGO_REMOTE_TOKEN. Passing it inline "
        "exposes it to `ps` and shell history."
    ),
)
def remote_add(name: str, url: str, token: str | None) -> None:
    """Remember a frago you can send work to.

    \b
    Examples:
        frago remote add box --url http://127.0.0.1:18093        # prompts for the token
        ssh box frago server token | frago remote add box --url ... --token -
    """
    token = _read_token(token)
    if not token:
        raise click.ClickException("No token given")

    if url.startswith("http://") and not _is_local_url(url):
        click.echo(
            f"Warning: {url} is plain HTTP to a non-local address — the token and every "
            "brief you send cross the network in the clear. Use an SSH tunnel "
            "(ssh -L 18093:127.0.0.1:8093 <host>) or https://.",
            err=True,
        )

    remotes = _load()
    remotes[name] = {
        "url": url.rstrip("/"),
        "token": token,
        "added": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _save(remotes)
    click.echo(f"✓ remote '{name}' → {url}")


@remote_group.command(name="remove", cls=AgentFriendlyCommand)
@click.argument("name")
def remote_remove(name: str) -> None:
    """Forget a remote."""
    remotes = _load()
    if remotes.pop(name, None) is None:
        raise click.ClickException(f"Unknown remote '{name}'")
    _save(remotes)
    click.echo(f"✓ removed '{name}'")


@remote_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def remote_list(output_format: str) -> None:
    """List configured remotes. Tokens are never printed."""
    remotes = _load()
    if output_format == "json":
        click.echo(json.dumps(
            {"remotes": [{"name": n, "url": r.get("url"), "added": r.get("added")}
                         for n, r in sorted(remotes.items())]},
            ensure_ascii=False, indent=2,
        ))
        return
    if not remotes:
        click.echo("No remotes. Add one with: frago remote add <name> --url <url> --token <token>")
        return
    for name, remote in sorted(remotes.items()):
        click.echo(f"{name:<20} {remote.get('url', '?')}")


@remote_group.command(name="status", cls=AgentFriendlyCommand)
@click.argument("name")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def remote_status(name: str, output_format: str) -> None:
    """Check that a remote is up and that our token is accepted."""
    import requests

    base_url, headers = _target(name)
    try:
        resp = requests.get(f"{base_url}/api/status", headers=headers, timeout=10)
    except Exception as e:
        result = {"reachable": False, "error": str(e)}
    else:
        result = {
            "reachable": resp.status_code == 200,
            "http_status": resp.status_code,
            "authorized": resp.status_code != 401,
        }
        if resp.status_code == 200:
            with contextlib.suppress(ValueError):
                result["status"] = resp.json()

    if output_format == "json":
        click.echo(json.dumps({"remote": name, "url": base_url, **result}, ensure_ascii=False, indent=2))
    elif result.get("reachable"):
        click.echo(f"{name} ({base_url}): up")
    elif result.get("http_status") == 401:
        click.echo(f"{name} ({base_url}): reachable but token rejected", err=True)
        sys.exit(1)
    else:
        click.echo(f"{name} ({base_url}): unreachable — {result.get('error', result.get('http_status'))}", err=True)
        sys.exit(1)


@remote_group.command(name="send", cls=AgentFriendlyCommand)
@click.argument("name")
@click.argument("prompt", required=False)
@click.option("--prompt-file", type=click.Path(exists=True, dir_okay=False), help="Read the brief from a file")
@click.option("--timeout", default=600, show_default=True, help="Seconds to wait for the remote PA's reply")
@click.option("--no-wait", is_flag=True, help="Queue the message and exit without waiting")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def remote_send(
    name: str,
    prompt: str | None,
    prompt_file: str | None,
    timeout: int,
    no_wait: bool,
    output_format: str,
) -> None:
    """Send one brief to a remote frago's PA and wait for its reply.

    The brief is a task description, not a command: the remote PA reads it with
    that machine's own knowledge loaded and decides how to carry it out there.
    Say what you want to be true, and any constraint that matters (which recipe,
    where the output goes, whether to publish the page).

    \b
    Examples:
        frago remote send box "跑 weekly_report，产出发布到 /app/weekly_report"
        frago remote send box --prompt-file brief.md --json
        frago remote send box "开始长任务" --no-wait
    """
    from .chat import send_message, stream_session_events

    if prompt_file:
        prompt = Path(prompt_file).read_text(encoding="utf-8")
    if not prompt or not prompt.strip():
        raise click.ClickException("Nothing to send: give a PROMPT or --prompt-file")

    base_url, headers = _target(name)
    session_id = f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"

    started = datetime.now()
    msg_id = send_message(base_url, prompt, session_id, headers)
    if not msg_id:
        raise click.ClickException(f"Remote '{name}' did not accept the message")

    if no_wait:
        payload = {"status": "queued", "remote": name, "msg_id": msg_id, "session_id": session_id}
        click.echo(json.dumps(payload, ensure_ascii=False) if output_format == "json"
                   else f"queued on {name}: {msg_id}")
        return

    # Wait on the same event stream `frago chat` renders, but keep the reply as
    # a value: the caller here is usually another agent, and it needs the text.
    sent = {msg_id}
    stop_event = threading.Event()
    done = threading.Event()
    reply: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []

    def on_event(event_type: str, raw_data: dict, _event: dict) -> None:
        details = raw_data.get("details") or {}
        trace.append({
            "event": event_type,
            "description": details.get("description") or raw_data.get("action") or "",
        })
        if event_type == "pa_reply":
            reply["text"] = raw_data.get("reply_text", "")
            done.set()

    thread = threading.Thread(
        target=stream_session_events,
        args=(base_url, sent, stop_event, on_event, headers),
        daemon=True,
    )
    thread.start()
    try:
        arrived = done.wait(timeout=timeout)
    finally:
        stop_event.set()
        thread.join(timeout=3)

    duration_ms = int((datetime.now() - started).total_seconds() * 1000)
    status = "ok" if arrived else "timeout"

    if output_format == "json":
        click.echo(json.dumps({
            "status": status,
            "remote": name,
            "msg_id": msg_id,
            "session_id": session_id,
            "reply": reply.get("text", ""),
            "trace": trace,
            "duration_ms": duration_ms,
        }, ensure_ascii=False, indent=2))
    elif arrived:
        click.echo(reply.get("text", ""))
    else:
        click.echo(
            f"No reply within {timeout}s. The remote may still be working; "
            f"pick it up with: frago remote chat {name}",
            err=True,
        )

    if not arrived:
        sys.exit(1)


@remote_group.command(name="chat", cls=AgentFriendlyCommand)
@click.argument("name")
def remote_chat(name: str) -> None:
    """Open an interactive conversation with a remote frago's PA."""
    from .chat import start_chat

    base_url, headers = _target(name)
    start_chat(base_url=base_url, headers=headers)
