"""Agent task execution service.

Provides functionality for starting and continuing agent tasks.
Supports both detached (fire-and-forget) and attached (streaming) modes.
"""

import asyncio
import contextlib
import logging
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.subprocess_utils import run_subprocess_background
from frago.server.websocket import manager

logger = logging.getLogger(__name__)


_attached_pool: Any | None = None


def _get_attached_pool() -> Any:
    """Lazily build the resident-session pool shared by attached sessions.

    Lazy rather than module-level so importing this service never costs a pool
    (and so tests can inject their own via ``AgentSession(pool=...)``).
    """
    global _attached_pool
    if _attached_pool is None:
        from frago.agent_driver.pool import WarmSessionPool

        _attached_pool = WarmSessionPool()
    return _attached_pool


class UnknownAgentCore(RuntimeError):
    """这个内核名这条路上没人认得：既不在驱动注册表里，也不是跑在 frago 内核里的那一家。"""


def assemble_prompt(prefix_provider: Callable[[], str] | None, message: str) -> str:
    """把会话绑定的前缀拼在这一次的话前面（没有前缀就原样返回）。

    每次（重）起都重新求值，动态状态（PA 的 bootstrap 那类）才是当下的。空消息只回前缀。
    两条后端共用一处：这是"这一场的第一句话"的形状，两边各写一份迟早长得不一样。
    """
    if prefix_provider is None:
        return message
    prefix = prefix_provider()
    if not message:
        return prefix
    return f"{prefix}\n\n{message}"


async def _emit_text_delta(internal_id: str, session_id: str | None, text: str) -> None:
    """一个正文块：配对的 done=False / done=True，前端那条 delta 处理器认的就是这一对。"""
    for done in (False, True):
        await manager.broadcast({
            "type": "agent_text_delta",
            "internal_id": internal_id,
            "session_id": session_id,
            "content": "" if done else text,
            "done": done,
        })


async def _emit_tool_executing(
    internal_id: str,
    session_id: str | None,
    tool_call_id: str,
    tool_name: str,
    parameters: Any,
) -> None:
    """一次工具调用开跑。两条后端喂进来的参数形状不同，发出去的事件一字不变。"""
    await manager.broadcast({
        "type": "agent_tool_executing",
        "internal_id": internal_id,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "parameters": parameters or {},
    })


async def _emit_tool_result(
    internal_id: str,
    session_id: str | None,
    tool_call_id: str,
    tool_name: str,
    success: bool,
    content: str,
) -> None:
    """一次工具调用的回执。"""
    await manager.broadcast({
        "type": "agent_tool_result",
        "internal_id": internal_id,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "success": success,
        "content": content,
    })


def resolve_agent_type(agent_type: str | None) -> str:
    """Which core actually runs a turn: explicit argument, else the configured
    preference, else the built-in core.

    Both start paths (detached and attached) go through this, so the core
    picked in the WebUI wizard governs every server-started session the same
    way it governs a bare `frago agent` on the command line.

    那份偏好只是偏好：它指向的内核本机没装时退回自带内核（判据见
    :func:`frago.init.agent_core.resolve_agent_core`，与命令行那条同源）。

    **这里只答"按偏好该用谁"，不答"这条后端接不接得住"。** 接得住接不住是后端自己的
    事：detached 那条把活交给 `frago agent`，那里自带内核走内核后端、其余几家走各自的
    driver，偏好里每个合法取值都接得住；attached 那条有两个后端，挑哪一个见
    :func:`resolve_attached_agent_type`。
    """
    if agent_type:
        return agent_type
    from frago.init.agent_core import resolve_agent_core
    from frago.init.config_manager import get_agent_core

    resolved, _note = resolve_agent_core(get_agent_core())
    return resolved


def resolve_attached_agent_type(agent_type: str | None) -> str:
    """attached 那条路这一轮实际用哪个内核。

    偏好怎么解析与 detached 同源（:func:`resolve_agent_type`）。这里多答的是**这条后端
    接不接得住**：注册表里那几家（claude / codex / opencode / agy）是"挂在 tmux 里
    的交互程序"，走常驻会话池；跑在 frago 自己内核里的那一家（CoreAgent）没有可挂的 TUI
    （判据见 :func:`frago.agent_driver.driver.runs_on_kernel`），走它自己的内核后端
    （:class:`KernelAgentSession`）。两条都接得住，所以偏好里的每个合法取值在这条路上都
    走得通——缺省那个正是自带内核。

    名字两处都不认（显式点名一个不存在的东西）时抛 :class:`UnknownAgentCore`，由调用方
    说明白，NEVER 让进程池去抛那个只有开发者读得懂的 KeyError。
    """
    resolved = resolve_agent_type(agent_type)

    from frago.agent_driver.driver import registered_drivers, runs_on_kernel

    drivers = registered_drivers()
    if runs_on_kernel(resolved) or resolved in drivers:
        return resolved

    from frago.init.agent_core import built_in_core

    known = ", ".join([*drivers, built_in_core()])
    raise UnknownAgentCore(
        f"没有叫 {resolved!r} 的客户端（这一条路认得的是：{known}）。"
    )


def _resolve_frago_cmd() -> list[str]:
    """Return the base command used to invoke frago from the server process.

    Preference order:
      1. ``frago`` in the same venv as the running server — the system
         uv-tool install's own entry point (most reliable when the daemon's
         PATH doesn't include the tool bin dir — common on Windows and under
         systemd).
      2. Bare ``frago`` resolved via PATH. Never ``uv run frago``: the server
         runtime is always the system install, and ``uv run`` from a repo cwd
         would silently switch back to checkout code.

    Callers append the subcommand and arguments (e.g. ``+ ["agent", ...]``).
    """
    venv_dir = Path(sys.executable).parent
    frago_in_venv = shutil.which("frago", path=str(venv_dir))
    if frago_in_venv:
        return [frago_in_venv]
    return ["frago"]


class AgentSession:
    """Manages a single attached agent session backed by a resident tmux session.

    Phase 6 (spec 20260607): the turn runs inside a resident tmux TUI acquired
    from ``WarmSessionPool`` — the same mechanism PA already uses
    (``pa_tmux_runner.py``) — and the WebSocket event stream is driven by
    tailing the agent's transcript via ``TranscriptStreamer`` instead of
    parsing the retired headless backend's JSON stream off stdout. The emitted
    event names and field shapes are unchanged, so the frontend needs no
    changes; only the granularity coarsens from token deltas to content blocks.

    The session is resident: unlike the old subprocess model, ``send_message``
    reuses the live TUI (which keeps its own conversational context) instead of
    killing and respawning a fresh child.
    """

    def __init__(
        self,
        internal_id: str,
        project_path: str,
        *,
        prefix_provider: Callable[[], str] | None = None,
        agent_type: str | None = None,
        pool: Any | None = None,
        turn_timeout_s: float | None = None,
    ):
        self.internal_id = internal_id
        self.project_path = project_path
        # None = "whatever the configured core preference says" (the built-in
        # core if unset). Resolved here so `self.agent_type` is always a
        # concrete name this attached path can drive — this class only serves
        # the tmux-pool end of it; the kernel end is KernelAgentSession.
        self.agent_type = resolve_attached_agent_type(agent_type)
        self._pool = pool
        self._turn_timeout_s = turn_timeout_s
        self._tmux_session: Any | None = None
        self._streamer: Any | None = None
        self._attached = False
        self._running = False
        self._claude_session_id: str | None = None
        # One turn at a time per resident session: two concurrent send() calls
        # would interleave keystrokes into the same TUI and garble both turns.
        self._turn_lock = asyncio.Lock()
        # tool_use id → tool name, harvested from assistant records so a later
        # tool_result record (which carries only the id) can name its tool.
        self._pending_tool_calls: dict[str, dict[str, Any]] = {}
        # Optional callback for capturing complete assistant messages
        self._on_assistant_message: Any | None = None  # Callable[[str], None]
        # Session-bound prompt prefix (e.g., PA system prompt + bootstrap).
        # Invoked on every (re)start so identity/context survives a restart.
        # None for plain agent sessions.
        self._prefix_provider = prefix_provider

    def _assemble_prompt(self, message: str) -> str:
        """Prepend session-bound prefix to the caller-supplied message.

        Called on every (re)start. When ``prefix_provider`` is set the prefix
        is re-evaluated each time so dynamic state (e.g. PA bootstrap) is
        always current. Empty message returns the prefix alone.
        """
        return assemble_prompt(self._prefix_provider, message)

    def _get_pool(self) -> Any:
        """The resident-session pool this attached session draws from.

        Defaults to the module-level pool shared by all attached sessions, so
        a reconnecting console reuses its warm TUI instead of cold-starting.
        """
        if self._pool is None:
            self._pool = _get_attached_pool()
        return self._pool

    async def _ensure_session(self) -> Any:
        """Acquire (or reuse) this session's resident tmux TUI + its streamer.

        Acquisition is blocking (tmux + readiness polling), so it runs in a
        worker thread. The streamer is created once per attached session and
        anchored to the transcript tail *before* the first prompt: a resumed
        session's transcript already holds its whole history, and replaying
        that as "new" would dump the entire past conversation at the frontend.
        """
        if self._tmux_session is not None and self._tmux_session.is_alive():
            return self._tmux_session

        # No FRAGO_PA marker here: this path now only ever serves WebUI
        # "new session", which must behave exactly like typing `claude` in a
        # terminal — including the SessionStart / PreToolUse hook injections.
        # The marker dates from when PA itself came through here (see the
        # 2026-05-03 validator analysis); PA has since moved to
        # pa_tmux_runner.py, which acquires its own session and never set it.
        pool = self._get_pool()
        session = await asyncio.to_thread(
            pool.acquire,
            self.agent_type,
            self.internal_id,
            self.project_path,
        )
        self._tmux_session = session

        if self._streamer is None:
            from frago.agent_driver.streamer import TranscriptStreamer

            driver = session.driver
            source_fn = driver.transcript_source
            source = source_fn(session) if source_fn is not None else None
            if source is None:
                # This agent exposes no record source (codex today): the turn
                # still runs, it just streams no incremental events.
                logger.info(
                    "Agent %r exposes no transcript source — attached session %s "
                    "will run without incremental streaming",
                    self.agent_type, self.internal_id,
                )
            else:
                self._streamer = TranscriptStreamer(source)
                await asyncio.to_thread(self._streamer.seek_to_end)
        return session

    async def start(self, prompt: str) -> None:
        """Start a turn in attached mode on the resident tmux session.

        Per-turn user content comes from ``prompt``; any session-bound prefix
        (PA system prompt + bootstrap, etc.) is supplied by ``prefix_provider``
        and re-attached on every (re)start.
        """
        await self._ensure_session()
        self._attached = True
        await self._run_turn(self._assemble_prompt(prompt))

    async def send_message(self, message: str) -> None:
        """Send a follow-up message into the live resident session.

        Unlike the old subprocess model (which killed and respawned the child
        on every message, losing Claude-side context), the TUI stays alive and
        keeps its own conversational memory, so the raw message is enough — no
        prefix re-attachment and no session-id reset.
        """
        await manager.broadcast({
            "type": "agent_user_message",
            "internal_id": self.internal_id,
            "session_id": self._claude_session_id,
            "content": message,
        })
        await self._ensure_session()
        await self._run_turn(message)

    async def _run_turn(self, text: str) -> None:
        """Feed one turn and stream its transcript records until it completes.

        The turn's end is decided by the driver's own completion probe inside
        ``TmuxAgentSession.send`` (authoritative: it reads the transcript's
        stop_reason). ``turn_timeout_s`` defaults to None — no wall-clock cap:
        a turn that legitimately runs for an hour must not be declared finished
        at some fixed mark while the agent is still working (the UI would show
        "completed" over a session that keeps producing). Callers that need a
        cap pass a positive number. The streamer
        runs alongside and is drained once more after the turn returns so the
        final records aren't lost to the poll interval.
        """
        async with self._turn_lock:
            self._running = True
            session = self._tmux_session
            stream_task: asyncio.Task | None = None
            if self._streamer is not None:
                stream_task = asyncio.create_task(self._streamer.run(self._emit_record))
            try:
                await asyncio.to_thread(
                    session.send, text, timeout_s=self._turn_timeout_s
                )
            except Exception as e:
                logger.error("Attached turn failed: %s", e, exc_info=True)
            finally:
                if stream_task is not None:
                    stream_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stream_task
                if self._streamer is not None:
                    with contextlib.suppress(Exception):
                        await self._streamer.drain(self._emit_record)
                self._running = False
                await manager.broadcast({
                    "type": "agent_session_status",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "status": "completed",
                })

    async def _resolve_session_id(self) -> None:
        """Announce the agent-native session id once the record source knows it.

        Which id that is, and when it becomes knowable, is the driver's business:
        claude derives it from the transcript filename, opencode from the session
        it claimed in its database. Asking the source keeps this agent-agnostic.
        """
        if self._claude_session_id is not None or self._streamer is None:
            return
        native_id = self._streamer.native_session_id
        if native_id is None:
            return
        self._claude_session_id = native_id
        logger.info(f"Agent session ID resolved: {self._claude_session_id}")
        await manager.broadcast({
            "type": "agent_session_resolved",
            "internal_id": self.internal_id,
            "session_id": self._claude_session_id,
        })

    async def _emit_record(self, record: Any) -> None:
        """Map one normalized transcript record onto the existing WS events.

        Event names and field shapes are unchanged from the headless-backend era —
        the frontend is untouched. The only difference: text arrives as whole
        content blocks rather than token deltas, and ``parameters`` is taken
        straight from the record's complete ``tool_use.input`` instead of being
        reassembled from ``input_json_delta`` fragments.
        """
        await self._resolve_session_id()

        role = record.role or record.record_type

        if role == "assistant":
            text = record.content_text
            if text:
                await _emit_text_delta(self.internal_id, self._claude_session_id, text)
                if self._on_assistant_message:
                    with contextlib.suppress(Exception):
                        self._on_assistant_message(text)

            for block in record.tool_calls:
                tool_call_id = block.get("id", "")
                tool_name = block.get("name", "")
                self._pending_tool_calls[tool_call_id] = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "timestamp": datetime.now().isoformat(),
                }
                await _emit_tool_executing(
                    self.internal_id,
                    self._claude_session_id,
                    tool_call_id,
                    tool_name,
                    block.get("input") or {},
                )
            return

        # User records carry tool results; their plain text is the echo of the
        # prompt we just sent, which the frontend already rendered itself.
        for block in record.tool_results:
            tool_use_id = block.get("tool_use_id", "")
            tool_call = self._pending_tool_calls.pop(tool_use_id, None)
            await _emit_tool_result(
                self.internal_id,
                self._claude_session_id,
                tool_use_id,
                tool_call["name"] if tool_call else "",
                not block.get("is_error", False),
                str(block.get("content", "")),
            )

    async def stop(self) -> None:
        """Stop the attached session and release its resident tmux session."""
        self._running = False
        pool = self._get_pool()
        with contextlib.suppress(Exception):
            await asyncio.to_thread(pool.evict, self.internal_id)
        self._tmux_session = None
        logger.info(f"Attached agent session {self.internal_id} stopped")

    @property
    def is_attached(self) -> bool:
        return self._attached

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def claude_session_id(self) -> str | None:
        return self._claude_session_id


#: 内核会话记录流的轮询间隔（秒）。与工作台读记录那条同一个量级。
_KERNEL_RECORD_POLL_S = 0.3

#: 一次取多少条记录。内核一轮的记录条数远小于分页上限，一拍取一批就够。
_KERNEL_RECORD_BATCH = 200


class KernelAgentSession:
    """attached 那条路上跑自带内核的一场会话（CoreAgent）。

    **为什么与 :class:`AgentSession` 并列，而不是塞进它。** 那一条的每个动作都是屏语义：
    从常驻会话池取一个挂在 tmux 里的交互程序、把话敲进它的输入框、读它自己的记录文件。
    CoreAgent 是"交一件事、跑完就退"的进程，没有屏可读，塞进那套契约等于在非屏进程上假装
    有屏。两条后端各写一个类，**对外的形状相同**——``internal_id``、``start``、
    ``send_message``、``stop`` 外加那几条属性，所以 ``AgentService`` 那三个入口一个字都
    不用分岔。

    投喂与读记录都复用既有出口，本类既不自己起进程也不自己解析记录：

    - 投喂走 :func:`frago.server.services.coreagent_runner.send`：常驻进程 + 按会话排队，
      上下文留在内核进程自己那边，与工作台「新建会话」起 CoreAgent 走的是同一条。
    - 读记录走 :func:`frago.session.record_reader.read_records`：与工作台同一个来源、同一份
      翻译层。会话编号在这里现发（``core_`` 前缀），所以这条路上没有"等认领"的空窗。
    """

    def __init__(
        self,
        internal_id: str,
        project_path: str,
        *,
        agent_type: str,
        prefix_provider: Callable[[], str] | None = None,
    ):
        from frago.server.services import coreagent_runner

        self.internal_id = internal_id
        self.project_path = project_path
        self.agent_type = agent_type
        # 编号由发起方现发，这是内核那一侧的既有做法（见 coreagent_runner.new_session_id）：
        # 现发才能在会话跑起来之前就把它归好家，页面也当场知道这一场叫什么。
        self.session_id = coreagent_runner.new_session_id()
        self._prefix_provider = prefix_provider
        self._attached = False
        self._running = False
        # 记录流读到第几条了（下一批从它取起）。这一场是新开的，记录文件从空开始。
        self._seq = 0
        # 一轮一次：两句话同时进来会在同一根 stdin 上交错。
        self._turn_lock = asyncio.Lock()

    def _assemble_prompt(self, message: str) -> str:
        return assemble_prompt(self._prefix_provider, message)

    async def start(self, prompt: str) -> None:
        """跑这一场的第一轮。编号当场就有，先告诉页面，再交活。"""
        self._attached = True
        await manager.broadcast({
            "type": "agent_session_resolved",
            "internal_id": self.internal_id,
            "session_id": self.session_id,
        })
        await self._run_turn(self._assemble_prompt(prompt))

    async def send_message(self, message: str) -> None:
        """接着这一场说下一句。上下文由内核那个常驻进程自己留着。"""
        await manager.broadcast({
            "type": "agent_user_message",
            "internal_id": self.internal_id,
            "session_id": self.session_id,
            "content": message,
        })
        await self._run_turn(message)

    async def _run_turn(self, text: str) -> None:
        """把这一轮交给内核，同时把它的记录流发出去。

        一轮的终点以 :func:`coreagent_runner.send` 交出来的结论为准（它读的是内核自己打在
        stdout 上的 ``result``）。那个调用是"到点先回在跑"、不是上限，所以回来之后还要看
        这一场是不是仍在跑——把还在跑的一场报成完成，页面就不再等了。
        """
        from frago.server.services import coreagent_runner

        async with self._turn_lock:
            self._running = True
            stream_task = asyncio.create_task(self._stream_records())
            try:
                await asyncio.to_thread(
                    coreagent_runner.send,
                    self.session_id,
                    text,
                    cwd=self.project_path,
                    wait_s=coreagent_runner.TURN_TIMEOUT_S,
                )
                while await asyncio.to_thread(coreagent_runner.busy, self.session_id):
                    await asyncio.sleep(1.0)
            except Exception as e:
                # 失败得早的那几种（内核不在、没给内核配连接）在会话记录里一个字都没写下
                # 来，页面除了这句话没有别的线索。照实发出去，别让它静默。
                logger.error("Attached kernel turn failed: %s", e, exc_info=True)
                await _emit_text_delta(self.internal_id, self.session_id, str(e))
            finally:
                stream_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
                with contextlib.suppress(Exception):
                    await self._drain_records()
                self._running = False
                await manager.broadcast({
                    "type": "agent_session_status",
                    "internal_id": self.internal_id,
                    "session_id": self.session_id,
                    "status": "completed",
                })

    async def _stream_records(self) -> None:
        """按拍读出新增记录并发射，直到被 cancel。

        来源尚不可用（记录文件还没生成）时读出来是空列表，下一拍再来——与另一条后端的
        记录来源同一条纪律：NEVER 因为一次读空就放弃。
        """
        while True:
            await self._drain_records()
            await asyncio.sleep(_KERNEL_RECORD_POLL_S)

    async def _drain_records(self) -> None:
        from frago.session import record_reader

        try:
            records = await asyncio.to_thread(
                record_reader.read_records,
                self.session_id,
                self._seq,
                _KERNEL_RECORD_BATCH,
            )
        except Exception:  # noqa: BLE001 — 读盘的任何失败只该丢掉这一拍
            logger.debug("读内核会话记录失败，下一拍再来", exc_info=True)
            return
        for record in records:
            await self._emit_unified(record)
            self._seq = record.seq + 1

    async def _emit_unified(self, record: Any) -> None:
        """把一条统一记录映射到与另一条后端相同的那几个事件上。

        只发界面认得的三种形态（正文、工具调用、工具结果）。用量刻度、上下文压缩、轮次
        边界那些不发——那不是丢信息，这条通道本来只承载"正文 + 工具"这两样，另一条后端
        发出去的也只有这两样。
        """
        payload = record.payload
        if record.kind == "agent.say":
            text = str(payload.get("text") or "")
            if text:
                await _emit_text_delta(self.internal_id, self.session_id, text)
        elif record.kind == "tool.call":
            await _emit_tool_executing(
                self.internal_id,
                self.session_id,
                str(payload.get("call_id") or ""),
                str(payload.get("tool_name") or ""),
                payload.get("args") or {},
            )
        elif record.kind == "tool.result":
            await _emit_tool_result(
                self.internal_id,
                self.session_id,
                str(payload.get("call_id") or ""),
                str(payload.get("tool_name") or ""),
                payload.get("status") == "ok",
                str(payload.get("body") or ""),
            )

    async def stop(self) -> None:
        """停下这一场：内核那边那个常驻进程也一并收掉。"""
        from frago.server.services import coreagent_runner

        self._running = False
        with contextlib.suppress(Exception):
            await asyncio.to_thread(coreagent_runner.stop, self.session_id)
        logger.info(f"Attached kernel session {self.internal_id} stopped")

    @property
    def is_attached(self) -> bool:
        return self._attached

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def claude_session_id(self) -> str | None:
        # 这一场的编号当场就有（见 __init__），不存在"等认领"的空窗。
        return self.session_id


def build_attached_session(
    internal_id: str,
    cwd: str,
    *,
    prefix_provider: Callable[[], str] | None = None,
    agent_type: str | None = None,
) -> AgentSession | KernelAgentSession:
    """按这一轮的解析结果挑后端：注册表里那几家挂 tmux，自带内核走内核后端。"""
    from frago.agent_driver.driver import runs_on_kernel

    resolved = resolve_attached_agent_type(agent_type)
    if runs_on_kernel(resolved):
        return KernelAgentSession(
            internal_id, cwd, agent_type=resolved, prefix_provider=prefix_provider
        )
    return AgentSession(
        internal_id, cwd, prefix_provider=prefix_provider, agent_type=resolved
    )


class AgentService:
    """Service for agent task execution.

    Supports both detached (fire-and-forget) and attached (streaming) modes.
    """

    # Attached sessions registry (in-memory, lost on server restart).
    # 两条后端都登记在这里，对外形状相同（见 build_attached_session）。
    _attached_sessions: dict[str, AgentSession | KernelAgentSession] = {}

    @staticmethod
    def start_task(
        prompt: str,
        project_path: str | None = None,
        env_extra: dict[str, str] | None = None,
        claude_session_id: str | None = None,
        agent_type: str | None = None,
    ) -> dict[str, Any]:
        """Start agent task.

        Executes `frago agent {prompt}` command in background.
        Returns immediately after task starts.

        Args:
            prompt: Task description/prompt.
            project_path: Optional project path context.
            env_extra: Additional environment variables for the subprocess.
            claude_session_id: Pre-generated UUID for Claude Code session traceability.
            agent_type: Which cli-agent core to drive. None falls back to the
                configured core preference (claude when unset).

        Returns:
            Dictionary with status, task_id, pid, claude_session_id, and message or error.
        """
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        task_id = str(uuid.uuid4())
        claude_session_id = claude_session_id or str(uuid.uuid4())
        agent_type = resolve_agent_type(agent_type)

        try:
            # Prepare log directory
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-{task_id}.log"

            # Use temp file to pass prompt (Windows compatibility)
            prompt_file = log_dir / f"prompt-{task_id}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Build command (uses venv-aware frago lookup so daemons without
            # .venv on PATH still find the right binary)
            cmd = _resolve_frago_cmd() + [
                "agent", "--source", "web",
                "--agent-type", agent_type,
                "--session-id", claude_session_id,
                "--prompt-file", str(prompt_file),
            ]

            # Start process in background with correct cwd
            cwd = project_path or str(Path.home())
            env = None
            if env_extra:
                from frago.server.services.subprocess_utils import get_utf8_env
                env = get_utf8_env()
                env.update(env_extra)
            with open(log_file, "w", encoding="utf-8") as f:
                process = run_subprocess_background(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=cwd,
                    env=env,
                )

            title = prompt

            return {
                "status": "ok",
                "id": task_id,
                "pid": process.pid,
                "claude_session_id": claude_session_id,
                "title": title,
                "project_path": project_path,
                "agent_type": agent_type,
                "started_at": datetime.now().isoformat(),
                "message": f"Task started: {title}",
            }

        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago command not found, please ensure it's properly installed",
            }
        except Exception as e:
            logger.error("Failed to start agent task: %s", e)
            return {
                "status": "error",
                "error": f"Failed to start task: {str(e)}",
            }

    @classmethod
    async def start_task_attached(
        cls,
        prompt: str,
        project_path: str | None = None,
        *,
        prefix_provider: Callable[[], str] | None = None,
        agent_type: str | None = None,
    ) -> dict[str, Any]:
        """Start agent task in attached mode with real-time streaming.

        Args:
            prompt: Task description/prompt.
            project_path: Optional project path context.
            prefix_provider: Optional zero-arg callable returning a prompt
                prefix re-evaluated on every (re)start. Use this to bind
                a long-lived role (e.g. PA system prompt + bootstrap) to
                the session — survives restarts triggered by send_message.
            agent_type: Which cli-agent core to drive. None falls back to the
                configured core preference; either way the name is then resolved
                to one this attached backend can drive (see
                :func:`resolve_attached_agent_type`).

        Returns:
            Dictionary with internal_id, status, and project_path.
        """
        # Empty `prompt` is allowed only when a prefix_provider is bound —
        # the prefix becomes the entire initial message.
        if (not prompt or not prompt.strip()) and prefix_provider is None:
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        internal_id = str(uuid.uuid4())
        cwd = project_path or str(Path.home())

        try:
            # 构造放进来一起兜：挑内核这一步就会拒（名字两处都不认得时抛
            # ``UnknownAgentCore``），放在 try 外面会让那句说明变成一条裸的 500。
            session = build_attached_session(
                internal_id,
                cwd,
                prefix_provider=prefix_provider,
                agent_type=agent_type,
            )
            await session.start(prompt)
            cls._attached_sessions[internal_id] = session

            return {
                "status": "ok",
                "session_id": None,  # Real Claude session ID comes via WebSocket
                "internal_id": internal_id,
                "project_path": cwd,
            }
        except Exception as e:
            logger.error("Failed to start attached agent task: %s", e)
            return {"status": "error", "error": f"Failed to start task: {str(e)}"}

    @classmethod
    async def send_message_attached(cls, internal_id: str, message: str) -> dict[str, Any]:
        """Send a continuation message to an attached session.

        Args:
            internal_id: Internal session ID.
            message: User message.

        Returns:
            Status dictionary.
        """
        session = cls._attached_sessions.get(internal_id)
        if not session:
            return {"status": "error", "error": f"Attached session {internal_id} not found"}

        try:
            await session.send_message(message)
            return {"status": "ok"}
        except Exception as e:
            logger.error("Failed to send message to attached session: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    async def stop_attached(cls, internal_id: str) -> dict[str, Any]:
        """Stop an attached session.

        Args:
            internal_id: Internal session ID.

        Returns:
            Status dictionary.
        """
        session = cls._attached_sessions.pop(internal_id, None)
        if not session:
            return {"status": "error", "error": f"Attached session {internal_id} not found"}

        try:
            await session.stop()
            return {"status": "ok"}
        except Exception as e:
            logger.error("Failed to stop attached session: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def get_attached_session_info(cls, internal_id: str) -> dict[str, Any] | None:
        """Get info about an attached session.

        Args:
            internal_id: Internal session ID.

        Returns:
            Session info dictionary or None if not found.
        """
        session = cls._attached_sessions.get(internal_id)
        if not session:
            return None

        return {
            "internal_id": session.internal_id,
            "session_id": session.claude_session_id,
            "project_path": session.project_path,
            "attached": session.is_attached,
            "running": session.is_running,
        }

