"""CLI Chat Mode — REPL for direct conversation with PA via HTTP + WebSocket."""

import json
import logging
import os
import sys
import threading
from datetime import datetime
from uuid import uuid4

import requests
import websocket
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML

logger = logging.getLogger(__name__)

RENDER_RULES: dict[str, tuple[str, str]] = {
    "pa_ingestion": ("2", "[收到] {prompt:.60}"),
    "pa_decision": ("36", "[PA] {action}: {description:.60}"),
    "pa_agent_launched": ("33", "[执行] {description}"),
    "pa_agent_exited": ("32", "[完成] {description} ({duration}s)"),
    "pa_reply": ("0", "agent> {reply_text}"),
}


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _get_base_url() -> str:
    from frago.server.daemon import get_server_host, get_server_port
    return f"http://{get_server_host()}:{get_server_port()}"


def auth_headers(token: str | None) -> dict[str, str]:
    """Headers that admit a non-local caller. Empty when talking to this machine."""
    return {"Authorization": f"Bearer {token}"} if token else {}


class _DefaultDict(dict):
    """Dict that returns empty string for missing keys."""
    def __missing__(self, key: str) -> str:
        return ""


def _render_event(event: dict) -> None:
    """Render a timeline event to terminal with ANSI colors."""
    raw = event.get("raw_data", {})
    event_type = event.get("event_type", "")

    # pa_decision with action=reply is redundant — pa_reply renders the actual text
    if event_type == "pa_decision" and raw.get("action") == "reply":
        return

    rule = RENDER_RULES.get(event_type)
    if not rule:
        return
    color_code, fmt = rule
    # Flatten nested 'details' dict so {description} etc. are accessible
    details = raw.get("details", {})
    data = _DefaultDict({**raw, **details, **event})
    try:
        text = fmt.format_map(data)
    except (KeyError, ValueError):
        text = str(raw)

    # Right-align timestamp on the first line
    ts = datetime.now().strftime("%H:%M:%S")
    first_line, *rest = text.split("\n")
    width = _term_width()
    visible_len = len(first_line)
    pad = max(1, width - visible_len - len(ts))
    ts_dim = f"\033[2m{ts}\033[0m"

    if color_code != "0":
        first_out = f"\033[{color_code}m{first_line}\033[0m{' ' * pad}{ts_dim}"
    else:
        first_out = f"{first_line}{' ' * pad}{ts_dim}"

    sys.stdout.write(first_out + "\n")
    for line in rest:
        if color_code != "0":
            sys.stdout.write(f"\033[{color_code}m{line}\033[0m\n")
        else:
            sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def _check_server(base_url: str, headers: dict[str, str] | None = None) -> bool:
    try:
        resp = requests.get(f"{base_url}/api/status", headers=headers or {}, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _check_pa(base_url: str, headers: dict[str, str] | None = None) -> bool:
    try:
        resp = requests.get(f"{base_url}/api/status", headers=headers or {}, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def stream_session_events(
    base_url: str,
    sent_msg_ids: set[str],
    stop_event: threading.Event,
    on_event,
    headers: dict[str, str] | None = None,
) -> None:
    """Feed this CLI session's own PA events to `on_event`, reconnecting as needed.

    PA broadcasts everything it does to every listener, so the filtering here is
    what makes one CLI session see only its own conversation: a message is ours
    if we sent its msg_id, and any task PA spawns while handling one of our
    messages is ours too (tracked through task_id, because later events in a run
    carry the task rather than the message).

    Split out from the renderer so a non-interactive caller — `frago remote
    send`, which needs the reply as a value rather than as coloured output — can
    reuse the same matching rather than re-deriving it.
    """
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    # A browser cannot set headers on a WS handshake, but this is a CLI; the
    # header form keeps the token out of the server's access log.
    ws_headers = [f"{k}: {v}" for k, v in (headers or {}).items()]
    task_ids: set[str] = set()

    while not stop_event.is_set():
        try:
            ws = websocket.WebSocket()
            ws.settimeout(1.0)
            ws.connect(ws_url, header=ws_headers)

            while not stop_event.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except (websocket.WebSocketConnectionClosedException, ConnectionError):
                    break

                if not raw:
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") != "timeline_event":
                    continue

                event = msg.get("event", {})
                raw_data = event.get("raw_data", {})
                event_type = event.get("event_type", "")
                msg_id = raw_data.get("msg_id", "") or event.get("msg_id", "")
                task_id = raw_data.get("task_id", "") or event.get("task_id", "")

                if msg_id in sent_msg_ids and task_id:
                    task_ids.add(task_id)

                id_match = msg_id in sent_msg_ids or task_id in task_ids
                related = (
                    (event_type == "pa_ingestion" and msg_id in sent_msg_ids)
                    or (event_type == "pa_reply" and raw_data.get("channel") == "cli" and id_match)
                    or (event_type in ("pa_decision", "pa_agent_launched", "pa_agent_exited") and id_match)
                )

                if related:
                    on_event(event_type, raw_data, event)

            ws.close()
        except Exception:
            if stop_event.is_set():
                break
            stop_event.wait(2)


def _ws_listener(
    base_url: str,
    sent_msg_ids: set[str],
    stop_event: threading.Event,
    reply_event: threading.Event,
    headers: dict[str, str] | None = None,
) -> None:
    """Render this session's PA events to the terminal until told to stop."""

    def on_event(event_type: str, raw_data: dict, event: dict) -> None:
        _render_event(event)
        # Release prompt after: reply arrived, or run/resume dispatched
        if (
            event_type == "pa_reply"
            or (event_type == "pa_decision" and raw_data.get("action") in ("run", "resume", "schedule"))
        ):
            reply_event.set()

    stream_session_events(base_url, sent_msg_ids, stop_event, on_event, headers)


def send_message(
    base_url: str,
    prompt: str,
    session_id: str,
    headers: dict[str, str] | None = None,
) -> str | None:
    """Hand PA a message. Returns its msg_id, or None if it could not be queued."""
    try:
        resp = requests.post(
            f"{base_url}/api/pa/chat",
            json={"prompt": prompt, "cli_session_id": session_id},
            headers=headers or {},
            timeout=15,
        )
        if resp.status_code == 401:
            sys.stderr.write("被拒绝（401）：token 无效或缺失。\n")
            return None
        if resp.status_code == 503:
            sys.stderr.write("PA 未运行，消息未发送。\n")
            return None
        resp.raise_for_status()
        return resp.json().get("msg_id")
    except requests.HTTPError as e:
        sys.stderr.write(f"发送失败: {e}\n")
        return None
    except Exception as e:
        sys.stderr.write(f"发送失败: {e}\n")
        return None


# Kept under the old private name: other call sites in this module use it.
_send_message = send_message


def start_chat(base_url: str | None = None, headers: dict[str, str] | None = None) -> None:
    """Entry point for CLI chat mode.

    `base_url`/`headers` default to this machine's own server. `frago remote
    chat` passes another frago's address and its token, which is the only
    difference between talking to your own PA and talking to one on a server.
    """
    base_url = base_url or _get_base_url()
    headers = headers or {}

    if not _check_server(base_url, headers):
        sys.stderr.write(
            f"连不上 {base_url}（server 未运行、地址错、或 token 不对）\n"
        )
        return

    if not _check_pa(base_url, headers):
        sys.stderr.write("PA 未运行。\n")
        return

    session_id = f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    sent_msg_ids: set[str] = set()
    stop_event = threading.Event()
    reply_event = threading.Event()

    # Banner — dark green (256-color 28). Only for interactive TTY;
    # pipe-captured stdout on Windows would mojibake the box/block chars.
    g = "\033[38;5;28m"
    r = "\033[0m"
    d = "\033[2m"
    if sys.stdout.isatty():
        sys.stdout.write(
            f"\n"
            f"  {g}───────────────────────────────{r}\n"
            f"   {g}█▀▀ █▀▄ ▄▀█ █▀▀ █▀█   █▀█ █▀{r}\n"
            f"   {g}█▀  █▀▄ █▀█ █▄█ █▄█   █▄█ ▄█{r}\n"
            f"  {g}───────────────────────────────{r}\n"
            f"\n"
            f"  {d}agent OS — AI agent 的操作系统{r}\n"
            f"  {d}https://github.com/tsaijamey/frago{r}\n"
            f"\n"
            f"  {d}session{r} {session_id}\n"
            f"  {d}输入消息与 PA 对话，exit/quit 退出{r}\n\n"
        )
    else:
        sys.stdout.write(f"\nfrago chat — session {session_id}\n\n")

    ws_thread = threading.Thread(
        target=_ws_listener,
        args=(base_url, sent_msg_ids, stop_event, reply_event, headers),
        daemon=True,
    )
    ws_thread.start()

    prompt_session: PromptSession[str] = PromptSession()
    ctrl_c_count = 0
    try:
        while True:
            try:
                line = prompt_session.prompt(HTML("<b>you&gt;</b> "))
            except EOFError:
                break
            except KeyboardInterrupt:
                ctrl_c_count += 1
                if ctrl_c_count >= 2:
                    break
                sys.stdout.write("再按一次 Ctrl+C 退出。\n")
                continue

            ctrl_c_count = 0
            line = line.strip()
            if not line:
                continue
            if line in ("exit", "quit"):
                break

            # Move cursor up to the input line, re-render with right-aligned timestamp
            ts = datetime.now().strftime("%H:%M:%S")
            prompt_text = f"you> {line}"
            width = _term_width()
            pad = max(1, width - len(prompt_text) - len(ts))
            sys.stdout.write(f"\033[A\r\033[Kyou> {line}{' ' * pad}\033[2m{ts}\033[0m\n")
            sys.stdout.flush()

            msg_id = send_message(base_url, line, session_id, headers)
            if msg_id:
                sent_msg_ids.add(msg_id)
                reply_event.clear()
                reply_event.wait(timeout=120)
    finally:
        stop_event.set()
        ws_thread.join(timeout=3)
        sys.stdout.write("\n")
