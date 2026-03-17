"""Primary Agent service — manages the lifecycle of frago's PID 1 agent.

The Primary Agent is a persistent Claude Code session that acts as frago's
main process. It receives external messages, decides how to handle them,
and manages task context. Its existence does not depend on any specific
feature (ingestion, web UI, etc.) — it is always available when the server
is running, just like PID 1 in a traditional OS.

Any component that needs to communicate with the Primary Agent uses
PrimaryAgentService.get_session_id() to get the session, then delivers
messages via AgentService.continue_task().

The heartbeat mechanism gives the Primary Agent time-awareness and
environmental perception, enabling autonomous behavior beyond passive
message consumption.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Heartbeat defaults (overridable via config.json primary_agent.heartbeat)
HEARTBEAT_DEFAULTS = {
    "enabled": True,
    "interval_seconds": 300,       # 5 minutes
    "initial_delay_seconds": 30,   # wait after server startup
}

# Primary Agent system prompt — defines its role as frago's main process agent.
# Core behavioral rules live in ~/.claude/commands/frago/ and CLAUDE.md,
# not in this prompt. This only establishes the initial role context.
PRIMARY_AGENT_SYSTEM_PROMPT = """\
你是 frago agent OS 的主进程 agent（Primary Agent）。

## 职责

1. 接收来自各个 channel（邮件、消息等）的任务请求
2. 判断每个请求是新任务还是已有任务的补充信息
3. 选择执行策略并执行
4. 管理任务上下文，跟踪执行状态

## 工具

- `frago agent "prompt"` — 启动子 agent 执行复杂任务
- `frago recipe run <name> --params '{...}'` — 直接执行 recipe
- `frago reply --channel <name> --params '{...}'` — 向来源 channel 回复消息
- 任何 shell 命令

## 执行策略

收到消息后，按以下优先级选择策略：

1. **补充信息** — 如果消息是对已有任务的补充（参考近期任务列表），将信息关联到该任务继续处理
2. **需要澄清** — 如果消息意图不明确或缺少关键信息，用 `frago reply` 向来源 channel 追问
3. **直接回答** — 简单查询、状态查询、信息检索类任务，直接执行并用 `frago reply` 回复结果
4. **Recipe 匹配** — 如果任务匹配已有 recipe（用 `frago recipe list` 查看），直接调用 recipe
5. **子 agent** — 复杂任务、需要多步骤执行的任务，启动子 agent

## 回复规范

执行完成后，始终通过 `frago reply` 将结果发回来源 channel。reply 的 params 遵循以下格式：
```json
{
  "status": "completed|failed",
  "result_summary": "执行结果摘要",
  "reply_context": {"原始消息中的 reply_context 原样传回"},
  "error": "如果失败，错误信息"
}
```

## 心跳

你会定期收到心跳消息（以"--- 心跳"开头），附带当前环境状态。
心跳是你感知时间流逝和环境变化的方式。

收到心跳时：
- 如果没有需要处理的事情，直接回复 "idle"（节省 token）
- 如果发现待处理任务积压，主动跟进
- 如果距上次向用户汇报超过一定时间，考虑发送状态摘要
- 你有完全的自主权决定做什么
"""

CONFIG_FILE = Path.home() / ".frago" / "config.json"


class PrimaryAgentService:
    """Manages the Primary Agent session lifecycle.

    Singleton — use get_instance() to access. The session is created once
    at server startup and reused across restarts via config persistence.
    """

    _instance: "PrimaryAgentService | None" = None
    _session_id: str | None = None

    def __init__(self) -> None:
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_stop = asyncio.Event()
        self._heartbeat_seq: int = 0
        self._last_external_message_at: float | None = None
        self._server_start_time: float = time.monotonic()

    @classmethod
    def get_instance(cls) -> "PrimaryAgentService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> None:
        """Ensure the Primary Agent session exists.

        Called during server startup (lifespan). Creates a new session if
        none exists or the stored one is invalid. Then starts the heartbeat.
        """
        session_id = self._read_session_id()
        if session_id and self._session_is_valid(session_id):
            self._session_id = session_id
            logger.info("Primary Agent session restored: %s", session_id[:8])
            await self._start_heartbeat()
            return

        # Create a new session via attached mode to capture the real
        # Claude session_id (start_task returns frago's internal UUID,
        # not the Claude session_id that --resume needs).
        logger.info("Creating new Primary Agent session")
        from frago.server.services.agent_service import AgentService

        result = await AgentService.start_task_attached(
            prompt=PRIMARY_AGENT_SYSTEM_PROMPT,
            project_path=str(Path.home()),
        )
        if result.get("status") != "ok":
            raise RuntimeError(
                f"Failed to create Primary Agent session: {result.get('error')}"
            )

        internal_id = result["internal_id"]
        claude_session_id = await self._wait_for_session_id(internal_id)

        self._session_id = claude_session_id
        self._save_session_id(claude_session_id)
        logger.info("Primary Agent session created: %s", claude_session_id[:8])
        await self._start_heartbeat()

    async def stop(self) -> None:
        """Stop the heartbeat. Called during server shutdown."""
        await self._stop_heartbeat()

    def get_session_id(self) -> str | None:
        """Return the current Primary Agent session_id, or None if not initialized."""
        return self._session_id

    def record_external_message(self) -> None:
        """Record that an external message was delivered to the Primary Agent."""
        self._last_external_message_at = time.monotonic()

    # -- heartbeat --

    def _load_heartbeat_config(self) -> dict:
        """Load heartbeat config from config.json, falling back to defaults."""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                user_config = raw.get("primary_agent", {}).get("heartbeat", {})
                merged = {**HEARTBEAT_DEFAULTS, **user_config}
                return merged
        except (json.JSONDecodeError, OSError):
            pass
        return dict(HEARTBEAT_DEFAULTS)

    async def _start_heartbeat(self) -> None:
        """Start the heartbeat loop if enabled."""
        config = self._load_heartbeat_config()
        if not config.get("enabled", True):
            logger.info("Primary Agent heartbeat disabled by config")
            return

        self._heartbeat_stop.clear()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                interval=config["interval_seconds"],
                initial_delay=config["initial_delay_seconds"],
            )
        )
        logger.info(
            "Primary Agent heartbeat started (interval=%ds)",
            config["interval_seconds"],
        )

    async def _stop_heartbeat(self) -> None:
        """Stop the heartbeat loop."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            return
        self._heartbeat_stop.set()
        self._heartbeat_task.cancel()
        try:
            await self._heartbeat_task
        except asyncio.CancelledError:
            pass
        self._heartbeat_task = None
        logger.info("Primary Agent heartbeat stopped")

    async def _heartbeat_loop(
        self, interval: int, initial_delay: int
    ) -> None:
        """Main heartbeat loop."""
        await asyncio.sleep(initial_delay)

        while not self._heartbeat_stop.is_set():
            try:
                await self._send_heartbeat()
            except Exception:
                logger.exception("Heartbeat delivery failed")

            try:
                await asyncio.wait_for(
                    self._heartbeat_stop.wait(), timeout=interval
                )
                break  # stop was requested
            except asyncio.TimeoutError:
                continue

    async def _send_heartbeat(self) -> None:
        """Send a single heartbeat message to the Primary Agent."""
        if not self._session_id:
            return

        message = self._format_heartbeat()
        from frago.server.services.agent_service import AgentService

        AgentService.continue_task(self._session_id, message)
        self._heartbeat_seq += 1
        logger.debug("Heartbeat [%d] sent to session %s", self._heartbeat_seq, self._session_id[:8])

    def _format_heartbeat(self) -> str:
        """Build the heartbeat message with environment context."""
        now = datetime.now(timezone.utc)
        uptime_seconds = int(time.monotonic() - self._server_start_time)
        uptime_str = self._format_duration(uptime_seconds)

        elapsed_str = "首次心跳" if self._heartbeat_seq == 0 else f"{self._format_duration(self._load_heartbeat_config()['interval_seconds'])}"

        if self._last_external_message_at is not None:
            since_external = int(
                time.monotonic() - self._last_external_message_at
            )
            since_external_str = self._format_duration(since_external)
        else:
            since_external_str = "尚未收到外部消息"

        # Gather task context (best-effort, don't fail if store unavailable)
        pending_summary, recent_summary = self._gather_task_context()

        return (
            f"--- 心跳 [{self._heartbeat_seq}] ---\n"
            f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"距上次心跳: {elapsed_str}\n"
            f"距上次外部消息: {since_external_str}\n"
            f"\n"
            f"环境状态:\n"
            f"- server 运行: {uptime_str}\n"
            f"{pending_summary}"
            f"{recent_summary}"
            f"\n"
            f"如果没有需要处理的事情，回复 idle。"
        )

    def _gather_task_context(self) -> tuple[str, str]:
        """Gather pending and recent task summaries. Returns (pending, recent)."""
        try:
            from frago.server.services.ingestion.store import TaskStore
            from frago.server.services.ingestion.models import TaskStatus

            store = TaskStore()
            pending = store.get_by_status(TaskStatus.PENDING)
            recent = store.get_recent(limit=5)

            pending_lines = ""
            if pending:
                pending_lines = f"- 待处理任务: {len(pending)} 个\n"
                for t in pending[:5]:
                    pending_lines += f"  - [{t.channel}] {t.prompt[:60]}\n"
            else:
                pending_lines = "- 待处理任务: 0 个\n"

            recent_lines = ""
            completed = [t for t in recent if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
            if completed:
                recent_lines = f"- 最近完成: {len(completed)} 个\n"
                for t in completed[:3]:
                    recent_lines += f"  - [{t.status.value}] {t.prompt[:60]}\n"

            return pending_lines, recent_lines
        except Exception:
            return "- 任务状态: 不可用\n", ""

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds}秒"
        if seconds < 3600:
            return f"{seconds // 60}分钟"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}小时{minutes}分钟"
        return f"{hours}小时"

    # -- persistence --

    @staticmethod
    def _read_session_id() -> str | None:
        if not CONFIG_FILE.exists():
            return None
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            pa = raw.get("primary_agent")
            if not isinstance(pa, dict):
                return None
            return pa.get("session_id")
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _save_session_id(session_id: str) -> None:
        try:
            raw: dict = {}
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

            if not isinstance(raw.get("primary_agent"), dict):
                raw["primary_agent"] = {}
            raw["primary_agent"]["session_id"] = session_id

            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to save primary agent session_id: %s", e)

    # -- validation --

    @staticmethod
    def _session_is_valid(session_id: str) -> bool:
        """Basic validity check for a Claude session_id."""
        if not session_id or len(session_id) < 8:
            return False

        # Check for evidence of past sessions
        logs_dir = Path.home() / ".frago" / "logs"
        prefix = session_id[:8]
        for pattern in (f"agent-resume-{prefix}.log", f"agent-{prefix}.log"):
            if (logs_dir / pattern).exists():
                return True

        # Accept plausible IDs and let continue_task fail gracefully
        return True

    @staticmethod
    async def _wait_for_session_id(
        internal_id: str, timeout: float = 30.0
    ) -> str:
        """Wait for AgentSession to resolve the real Claude session_id."""
        from frago.server.services.agent_service import AgentService

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = AgentService.get_attached_session_info(internal_id)
            if info and info.get("session_id"):
                return info["session_id"]
            await asyncio.sleep(0.5)

        raise RuntimeError(
            f"Timed out waiting for Claude session_id (internal_id={internal_id})"
        )
