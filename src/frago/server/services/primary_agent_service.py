"""Primary Agent service — manages the lifecycle of frago's PID 1 agent.

The Primary Agent is a persistent Claude Code session that acts as frago's
scheduler. It receives structured heartbeats, outputs JSON decisions, and
delegates execution to sub-agents working within Run instances.

Key design properties:
- Logically immortal: scheduling continuity across server restarts
- Physically bounded: session rotation prevents context O(n²) growth
- Heartbeat layered: code-level checks first (0 token), LLM only when needed
- Execution isolated: sub-agent work happens in Run containers, never in PA session

Any component that needs to communicate with the Primary Agent uses
PrimaryAgentService — it manages the attached session, heartbeat loop,
result collection, and Run lifecycle.
"""

import asyncio
import contextlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"
CONFIG_FILE = FRAGO_HOME / "config.json"

# Heartbeat defaults (overridable via config.json primary_agent.heartbeat)
HEARTBEAT_DEFAULTS = {
    "enabled": True,
    "interval_seconds": 300,       # 5 minutes
    "initial_delay_seconds": 30,   # wait after server startup
}

# Rotation thresholds
ROTATION_TURN_THRESHOLD = 30
ROTATION_TOKEN_THRESHOLD = 50000

# Task timeout default (seconds)
DEFAULT_TASK_TIMEOUT = 600

# Primary Agent system prompt — JSON output protocol for scheduler role.
PRIMARY_AGENT_SYSTEM_PROMPT = """\
你是 frago agent OS 的主进程调度器（Primary Agent）。

## 角色

你只做调度决策，不执行任务。你的输出是 JSON 决策数组，由 PrimaryAgentSvc 解析执行。

## 输出格式

每次响应**只输出纯 JSON 数组**，不包含任何解释性文字、markdown 或代码块。

可用的 action 类型：

```
[
  {"action": "reply", "task_id": "...", "channel": "...", "reply_params": {"text": "直接回复内容"}},
  {"action": "run", "task_id": "...", "description": "...", "prompt": "...", "related_runs": ["..."]},
  {"action": "recipe", "task_id": "...", "recipe_name": "...", "params": {}},
  {"action": "update", "task_id": "...", "result_summary": "...", "status": "completed"}
]
```

- `reply`: 直接回复来源 channel。reply_params.text 是发给用户的原文，自然表达，不要套模板
- `run`: 创建 Run 实例并启动子 agent 执行需要多步操作的复杂任务
- `recipe`: 直接执行 recipe（无需 Run 的轻量操作）
- `update`: 更新任务状态（status 可选: completed/failed）

空闲时输出: `[]`

## 调度路由

核心判断：**这个任务是否需要使用 frago 基础设施来完成？**

用 **reply** 的场景（仅限这些）：
- 打招呼、闲聊（"你好"、"你是谁"）
- 一句话能答完的事实性问题（"今天几号"）

用 **run** 的场景（默认选择）：
- 需要思考、分析、总结、对比、创作
- 需要查资料、访问外部系统
- 需要生成文件、PPT、报告、代码
- 用户的指令超过一句话，或有明确的交付物要求
- 你不确定该用 reply 还是 run → 用 run

子 agent 在 Run 中拥有完整的 frago 工具链（浏览器、recipe、文件系统、代码执行），能力远超你作为调度器的纯文本输出。把实际工作交给子 agent。

用 **recipe** 的场景：
- 任务恰好匹配已有 recipe 且不需要额外判断

## 示例

闲聊 → reply:
[{"action":"reply","task_id":"t1","channel":"feishu","reply_params":{"text":"在呢，有什么事？"}},{"action":"update","task_id":"t1","status":"completed","result_summary":"闲聊"}]

分析任务 → run（子 agent 会使用 frago 工具链完成）:
[{"action":"run","task_id":"t2","description":"对比 frago 与 OpenClaw 并制作 PPT","prompt":"用户要求：对比 frago 和 OpenClaw 的定位区别，制作一份精美科幻风格的 PPT，描绘 frago 是什么、使命、与 OpenClaw 的区别。请使用 frago 的浏览器和文件工具完成研究和制作。"}]

无待处理事项:
[]

## 回复风格

- 像正常人说话，不要套模板
- 简短直接
- 回复语言跟随用户的语言
"""


class PrimaryAgentService:
    """Manages the Primary Agent lifecycle: attached session + heartbeat + Run dispatch.

    Singleton — use get_instance() to access.
    """

    _instance: "PrimaryAgentService | None" = None

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._pa_session: Any | None = None  # AgentSession instance
        self._pa_internal_id: str | None = None

        # Heartbeat
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_stop = asyncio.Event()
        self._heartbeat_seq: int = 0

        # State tracking
        self._server_start_time: float = time.monotonic()
        self._busy: bool = False
        self._last_external_message_at: float | None = None

        # Rotation counters
        self._total_turns: int = 0
        self._accumulated_tokens: int = 0
        self._rotation_count: int = 0

        # JSON parse failure counter
        self._consecutive_json_failures: int = 0

        # Non-blocking PA communication state
        self._pa_output_buffer: str = ""
        self._pa_input_len: int = 0
        self._pa_waiting: bool = False

    @classmethod
    def get_instance(cls) -> "PrimaryAgentService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- lifecycle --

    async def initialize(self) -> None:
        """Initialize PA: create attached session and start heartbeat loop."""
        await self._create_pa_session()
        await self._start_heartbeat()

    async def stop(self) -> None:
        """Stop heartbeat and PA session. Called during server shutdown."""
        await self._stop_heartbeat()
        if self._pa_session:
            try:
                await self._pa_session.stop()
            except Exception:
                logger.debug("PA session stop error", exc_info=True)
            self._pa_session = None

    def get_session_id(self) -> str | None:
        """Return the current PA session_id, or None if not initialized."""
        return self._session_id

    def set_busy(self, busy: bool) -> None:
        """Set busy state. Prevents heartbeat during external processing."""
        self._busy = busy

    def record_external_message(self) -> None:
        """Record that an external message was delivered."""
        self._last_external_message_at = time.monotonic()

    # -- PA session management --

    async def _create_pa_session(self) -> None:
        """Create a new attached PA session with bootstrap context."""
        from frago.server.services.agent_service import AgentService

        bootstrap = self._build_bootstrap_prompt()
        prompt = PRIMARY_AGENT_SYSTEM_PROMPT + "\n\n" + bootstrap

        result = await AgentService.start_task_attached(
            prompt=prompt,
            project_path=str(Path.home()),
        )
        if result.get("status") != "ok":
            raise RuntimeError(
                f"Failed to create PA session: {result.get('error')}"
            )

        self._pa_internal_id = result["internal_id"]
        self._pa_session = AgentService._attached_sessions.get(self._pa_internal_id)

        # Register output callback to capture PA's assistant messages
        if self._pa_session:
            self._pa_session._on_assistant_message = self._on_pa_message

        # Wait for Claude session_id resolution
        self._session_id = await self._wait_for_session_id(self._pa_internal_id)
        self._save_session_id(self._session_id)
        logger.info("PA session created: %s", self._session_id[:8])

    async def rotate_session(self) -> None:
        """Create a new session, rebuild from external state."""
        logger.info(
            "PA session rotation (turns=%d, tokens=%d, rotation_count=%d)",
            self._total_turns, self._accumulated_tokens, self._rotation_count,
        )

        # Stop old session
        if self._pa_session:
            try:
                await self._pa_session.stop()
            except Exception:
                logger.debug("Old PA session stop error", exc_info=True)
            self._pa_session = None

        # Remove from attached sessions registry
        if self._pa_internal_id:
            from frago.server.services.agent_service import AgentService
            AgentService._attached_sessions.pop(self._pa_internal_id, None)

        # Create new session with bootstrap
        await self._create_pa_session()

        # Reset counters
        self._total_turns = 0
        self._accumulated_tokens = 0
        self._rotation_count += 1
        self._consecutive_json_failures = 0

    def _build_bootstrap_prompt(self) -> str:
        """Build bootstrap context from Run system + TaskStore."""
        sections = []
        now = datetime.now(UTC)
        sections.append(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        if self._rotation_count > 0:
            sections.append(f"这是第 {self._rotation_count + 1} 个 PA session（前一个因 rotation 退役）。")

        # Active runs
        try:
            from frago.run.manager import RunManager
            from frago.run.models import RunStatus
            manager = RunManager(PROJECTS_DIR)
            active_runs = manager.list_runs(status=RunStatus.ACTIVE)
            if active_runs:
                lines = [f"活跃 Run ({len(active_runs)} 个):"]
                for r in active_runs[:10]:
                    lines.append(f"  - {r['run_id']}: {r['theme_description'][:60]}")
                sections.append("\n".join(lines))
            else:
                sections.append("活跃 Run: 0 个")
        except Exception:
            sections.append("活跃 Run: 不可用")

        # Pending tasks
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            pending = store.get_by_status(TaskStatus.PENDING)
            if pending:
                lines = [f"待处理任务 ({len(pending)} 个):"]
                for t in pending[:10]:
                    lines.append(f"  - [{t.id[:8]}] ({t.channel}) {t.prompt[:60]}")
                sections.append("\n".join(lines))
            else:
                sections.append("待处理任务: 0 个")

            # Recent completed
            recent = store.get_recent(limit=10)
            completed = [t for t in recent if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
            if completed:
                lines = [f"最近完成 ({len(completed)} 个):"]
                for t in completed[:5]:
                    lines.append(f"  - [{t.status.value}] {t.prompt[:60]}")
                sections.append("\n".join(lines))
        except Exception:
            sections.append("任务状态: 不可用")

        # Run mutex
        try:
            from frago.run.context import ContextManager
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            current_run_id = ctx_mgr.get_current_run_id()
            if current_run_id:
                sections.append(f"当前执行中 Run: {current_run_id}")
            else:
                sections.append("当前执行中 Run: 无（空闲）")
        except Exception:
            sections.append("Run 锁状态: 不可用")

        # Agent self-knowledge index
        try:
            knowledge_file = Path(__file__).parent / "agent_knowledge.json"
            knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
            sections.append("frago 系统索引:\n" + json.dumps(knowledge, ensure_ascii=False, indent=2))
        except Exception:
            pass

        return "\n\n".join(sections)

    # -- heartbeat --

    def _load_heartbeat_config(self) -> dict:
        """Load heartbeat config from config.json, falling back to defaults."""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                user_config = raw.get("primary_agent", {}).get("heartbeat", {})
                return {**HEARTBEAT_DEFAULTS, **user_config}
        except (json.JSONDecodeError, OSError):
            pass
        return dict(HEARTBEAT_DEFAULTS)

    async def _start_heartbeat(self) -> None:
        """Start the heartbeat loop if enabled."""
        config = self._load_heartbeat_config()
        if not config.get("enabled", True):
            logger.info("PA heartbeat disabled by config")
            return

        self._heartbeat_stop.clear()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                interval=config["interval_seconds"],
                initial_delay=config["initial_delay_seconds"],
            )
        )
        logger.info("PA heartbeat started (interval=%ds)", config["interval_seconds"])

    async def _stop_heartbeat(self) -> None:
        """Stop the heartbeat loop."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            return
        self._heartbeat_stop.set()
        self._heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat_task
        self._heartbeat_task = None
        logger.info("PA heartbeat stopped")

    async def _heartbeat_loop(self, interval: int, initial_delay: int) -> None:
        """Main heartbeat loop."""
        logger.info("Heartbeat loop: waiting %ds initial delay", initial_delay)
        await asyncio.sleep(initial_delay)
        logger.info("Heartbeat loop: starting main loop")
        while not self._heartbeat_stop.is_set():
            try:
                await self._send_heartbeat()
            except Exception:
                logger.exception("Heartbeat failed")
            try:
                await asyncio.wait_for(
                    self._heartbeat_stop.wait(), timeout=interval
                )
                break
            except TimeoutError:
                continue

    async def _send_heartbeat(self) -> None:
        """Layered heartbeat: code checks first, LLM only when needed.

        Non-blocking design:
        - If PA is currently processing (_pa_waiting), skip and check next tick
        - If PA finished since last tick, process its output first
        - Then do code-layer checks and optionally send new message to PA
        """
        logger.info("Heartbeat [%d]: tick (waiting=%s)", self._heartbeat_seq, self._pa_waiting)
        if self._busy:
            logger.debug("Heartbeat skipped: PA is busy")
            return

        if not self._pa_session or not self._session_id:
            logger.debug("Heartbeat skipped: no PA session")
            return

        # ⓪ If PA was processing, check if it's done
        if self._pa_waiting:
            if self._pa_session.is_running:
                # Still processing, skip this tick
                logger.debug("Heartbeat [%d]: PA still processing, skip", self._heartbeat_seq)
                return
            # PA finished — process its output
            self._pa_waiting = False
            self._total_turns += 1
            estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
            self._accumulated_tokens += estimated_tokens
            if self._pa_output_buffer.strip():
                logger.info("Heartbeat [%d]: processing PA response (%d chars)", self._heartbeat_seq, len(self._pa_output_buffer))
                await self._handle_pa_output(self._pa_output_buffer.strip())
            self._pa_output_buffer = ""

        # ① Code layer: collect results from Run system (0 tokens)
        collected = await self._check_results()

        # ② Code layer: rotation check (0 tokens)
        if self._should_rotate():
            await self.rotate_session()
            return

        # ③ Code layer: decide if LLM is needed (0 tokens)
        has_pending = self._has_pending_tasks()
        has_timeout = self._has_overtime_dispatched()
        has_new_results = len(collected) > 0

        if not (has_pending or has_timeout or has_new_results):
            self._heartbeat_seq += 1
            logger.debug("Heartbeat [%d]: idle (no LLM needed)", self._heartbeat_seq)
            return

        # ④ Has work → send to PA session (non-blocking)
        message = self._format_heartbeat_message(collected)
        await self._send_to_pa(message)
        self._heartbeat_seq += 1

    def _on_pa_message(self, text: str) -> None:
        """Callback invoked by AgentSession when PA produces a complete text block."""
        self._pa_output_buffer += text

    async def _send_to_pa(self, message: str) -> None:
        """Send message to PA via attached session. Non-blocking: returns immediately.

        Output is collected via _on_pa_message callback. The next heartbeat
        tick will check if PA is done and process the accumulated output.
        """
        if not self._pa_session:
            logger.warning("Cannot send to PA: no session")
            return

        # Reset output buffer
        self._pa_output_buffer = ""
        self._pa_input_len = len(message)

        try:
            await self._pa_session.send_message(message)
            self._pa_waiting = True
            logger.info("Heartbeat [%d]: sent message to PA (%d chars)", self._heartbeat_seq, len(message))
        except RuntimeError as e:
            logger.error("Failed to send to PA: %s", e)
            await self.rotate_session()

    # -- PA output handling --

    async def _handle_pa_output(self, output_text: str) -> None:
        """Parse PA's JSON output and route decisions to Run/Recipe/Reply."""
        # Strip markdown code block wrappers if present
        text = output_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        try:
            decisions = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("PA output is not valid JSON: %s", text[:200])
            self._consecutive_json_failures += 1
            if self._consecutive_json_failures >= 3:
                logger.error("3 consecutive JSON failures, rotating session")
                await self.rotate_session()
            return

        self._consecutive_json_failures = 0

        if not isinstance(decisions, list):
            logger.warning("PA output is not a JSON array: %s", type(decisions))
            return

        if not decisions:
            logger.debug("PA returned empty decisions (idle)")
            return

        for d in decisions:
            if not isinstance(d, dict):
                continue
            action = d.get("action")
            try:
                if action == "run":
                    await self._dispatch_run(d)
                elif action == "recipe":
                    await self._dispatch_recipe(d)
                elif action == "reply":
                    await self._execute_reply(d)
                elif action == "update":
                    self._update_task(d)
                else:
                    logger.warning("Unknown PA action: %s", action)
            except Exception:
                logger.exception("Failed to execute PA decision: %s", d)

    # -- Run dispatch --

    async def _dispatch_run(self, decision: dict) -> None:
        """PA decided action:'run' → create Run instance → launch sub-agent."""
        task_id = decision.get("task_id")
        description = decision.get("description", "")
        prompt = decision.get("prompt", "")
        related_runs = decision.get("related_runs", [])

        if not prompt:
            logger.warning("run decision missing prompt, skipping")
            return

        # Check Run mutex
        from frago.run.context import ContextManager
        from frago.run.exceptions import ContextAlreadySetError
        ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
        if ctx_mgr.get_current_run_id():
            logger.info("Run lock active, task %s stays pending", task_id)
            return

        # Create Run instance
        from frago.run.manager import RunManager
        from frago.run.constants import THEME_DESCRIPTION_MAX_LEN as THEME_DESC_MAX
        manager = RunManager(PROJECTS_DIR)
        run = manager.create_run(description[:THEME_DESC_MAX] if description else prompt[:THEME_DESC_MAX])
        run_id = run.run_id
        logger.info("Created Run %s for task %s", run_id, task_id)

        # Set mutex
        try:
            ctx_mgr.set_current_run(run_id, run.theme_description)
        except ContextAlreadySetError:
            logger.warning("Run lock race condition, skipping dispatch")
            return

        # Update TaskStore
        if task_id:
            try:
                from frago.server.services.ingestion.models import TaskStatus
                from frago.server.services.ingestion.store import TaskStore
                store = TaskStore()
                store.update_status(
                    task_id, TaskStatus.EXECUTING, session_id=run_id
                )
            except Exception:
                logger.debug("Failed to update TaskStore for %s", task_id, exc_info=True)

        # Build sub-agent prompt
        agent_prompt = self._build_sub_agent_prompt(
            task_id=task_id,
            task_prompt=prompt,
            run_id=run_id,
            related_runs=related_runs,
        )

        # Launch sub-agent in Run context
        from frago.server.services.agent_service import AgentService
        result = AgentService.start_task(
            prompt=agent_prompt,
            project_path=str(Path.home()),
            env_extra={"FRAGO_CURRENT_RUN": run_id},
        )
        if result.get("status") != "ok":
            logger.error("Failed to start sub-agent: %s", result.get("error"))
            # Release lock on failure
            ctx_mgr.release_context()
        else:
            logger.info("Sub-agent launched for Run %s (agent_id=%s)", run_id, result.get("id", "?")[:8])
            pid = result.get("pid")
            if pid:
                asyncio.create_task(self._monitor_sub_agent(run_id, task_id, pid))

    async def _monitor_sub_agent(self, run_id: str, task_id: Optional[str], pid: int) -> None:
        """Watch sub-agent process; write TASK_FAILED if it exits without a completion marker."""
        import os

        # Poll until process exits
        while True:
            try:
                os.kill(pid, 0)
                await asyncio.sleep(5)
            except (ProcessLookupError, PermissionError):
                break

        # Check last N log entries for completion marker
        log_file = PROJECTS_DIR / run_id / "logs" / "execution.jsonl"
        has_completion = False
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-20:]):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("step") in ("TASK_COMPLETE", "TASK_FAILED"):
                    has_completion = True
                    break
        except Exception:
            pass

        if not has_completion:
            logger.warning("Run %s: sub-agent (PID %d) exited without completion marker — writing TASK_FAILED", run_id, pid)
            try:
                from frago.run.logger import RunLogger
                from frago.run.models import ActionType, ExecutionMethod, LogEntry, LogStatus
                run_log = RunLogger(PROJECTS_DIR / run_id)
                run_log.write_log(LogEntry(
                    timestamp=datetime.now(UTC),
                    step="TASK_FAILED",
                    status=LogStatus.ERROR,
                    action_type=ActionType.OTHER,
                    execution_method=ExecutionMethod.ANALYSIS,
                    data={"error": "Sub-agent exited without logging TASK_COMPLETE or TASK_FAILED"},
                ))
            except Exception:
                logger.error("Failed to write fallback TASK_FAILED for Run %s", run_id, exc_info=True)

    async def _dispatch_recipe(self, decision: dict) -> None:
        """PA decided action:'recipe' → execute recipe directly."""
        recipe_name = decision.get("recipe_name")
        params = decision.get("params", {})
        task_id = decision.get("task_id")

        if not recipe_name:
            logger.warning("recipe decision missing recipe_name")
            return

        from frago.recipes.runner import RecipeRunner
        runner = RecipeRunner()

        try:
            result = await asyncio.to_thread(runner.run, recipe_name, params=params)
            logger.info("Recipe %s result: success=%s", recipe_name, result.get("success"))

            if task_id:
                try:
                    from frago.server.services.ingestion.models import TaskStatus
                    from frago.server.services.ingestion.store import TaskStore
                    store = TaskStore()
                    status = TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED
                    summary = str(result.get("data", ""))[:200] if result.get("success") else result.get("error", "")
                    store.update_status(task_id, status, result_summary=summary)
                except Exception:
                    logger.debug("Failed to update TaskStore", exc_info=True)
        except Exception:
            logger.exception("Recipe %s execution failed", recipe_name)

    async def _execute_reply(self, decision: dict) -> None:
        """PA decided action:'reply' → call notify recipe.

        Merges PA's reply_params with the full reply_context from TaskStore,
        since PA only sees truncated task summaries and may not have complete
        addressing info (to, subject, in_reply_to, chat_id, etc.).
        """
        channel = decision.get("channel")
        reply_params = decision.get("reply_params", {})
        task_id = decision.get("task_id")

        if not channel:
            logger.warning("reply decision missing channel")
            return

        # Enrich reply_params with full reply_context from TaskStore
        if task_id:
            try:
                from frago.server.services.ingestion.store import TaskStore
                store = TaskStore()
                task = store.get(task_id)
                if task and task.reply_context:
                    # If PA provided direct text, send as-is (natural reply)
                    if reply_params.get("text"):
                        full_params = {
                            "text": reply_params["text"],
                            "reply_context": task.reply_context,
                        }
                    else:
                        # Fallback to ingestion contract format
                        full_params = {
                            "status": reply_params.get("status", "completed"),
                            "reply_context": task.reply_context,
                        }
                        if reply_params.get("result_summary"):
                            full_params["result_summary"] = reply_params["result_summary"]
                        if reply_params.get("error"):
                            full_params["error"] = reply_params["error"]
                    if reply_params.get("html_body"):
                        full_params["html_body"] = reply_params["html_body"]
                    reply_params = full_params
            except Exception:
                logger.debug("Failed to enrich reply_params from TaskStore", exc_info=True)

        # Find the notify recipe for this channel
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            channels = raw.get("task_ingestion", {}).get("channels", [])
            notify_recipe = None
            for ch in channels:
                if ch.get("name") == channel:
                    notify_recipe = ch.get("notify_recipe")
                    break

            if not notify_recipe:
                logger.warning("No notify_recipe configured for channel %s", channel)
                return

            from frago.recipes.runner import RecipeRunner
            runner = RecipeRunner()
            await asyncio.to_thread(runner.run, notify_recipe, params=reply_params)
            logger.info("Reply sent via %s for channel %s", notify_recipe, channel)

            # Mark task as completed after successful reply
            if task_id:
                try:
                    from frago.server.services.ingestion.models import TaskStatus
                    from frago.server.services.ingestion.store import TaskStore
                    TaskStore().update_status(task_id, TaskStatus.COMPLETED,
                                             result_summary=reply_params.get("result_summary", "replied"))
                except Exception:
                    logger.debug("Failed to mark task completed after reply", exc_info=True)

        except Exception:
            logger.exception("Failed to send reply for channel %s", channel)

    def _update_task(self, decision: dict) -> None:
        """PA decided action:'update' → update task status and result_summary."""
        task_id = decision.get("task_id")
        result_summary = decision.get("result_summary")
        new_status = decision.get("status")  # optional: "completed", "failed"

        if not task_id:
            return

        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            task = store.get(task_id)
            if task:
                status = task.status
                if new_status == "completed":
                    status = TaskStatus.COMPLETED
                elif new_status == "failed":
                    status = TaskStatus.FAILED
                store.update_status(task_id, status, result_summary=result_summary)
        except Exception:
            logger.debug("Failed to update task %s", task_id, exc_info=True)

    # -- result collection (code layer, 0 tokens) --

    async def _check_results(self) -> list[dict]:
        """Check Run completion status. Pure code, zero LLM calls."""
        collected = []

        try:
            from frago.run.context import ContextManager
            from frago.run.exceptions import RunNotFoundError
            from frago.run.logger import RunLogger
            from frago.run.manager import RunManager

            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            current_run_id = ctx_mgr.get_current_run_id()

            if not current_run_id:
                return collected

            # Check for completion markers in run logs
            run_dir = PROJECTS_DIR / current_run_id
            try:
                run_logger = RunLogger(run_dir)
                recent_logs = run_logger.get_recent_logs(count=5)
            except Exception:
                recent_logs = []

            for log in recent_logs:
                if log.step in ("TASK_COMPLETE", "TASK_FAILED"):
                    # Task finished
                    ctx_mgr.release_context()

                    task = self._find_task_for_run(current_run_id)
                    summary = log.data.get("summary", "") or log.data.get("error", "")
                    if task:
                        from frago.server.services.ingestion.models import TaskStatus
                        from frago.server.services.ingestion.store import TaskStore
                        status = TaskStatus.COMPLETED if log.step == "TASK_COMPLETE" else TaskStatus.FAILED
                        TaskStore().update_status(task.id, status, result_summary=summary)

                    collected.append({
                        "run_id": current_run_id,
                        "task_id": task.id if task else None,
                        "status": "completed" if log.step == "TASK_COMPLETE" else "failed",
                        "summary": summary,
                    })

                    # Archive run
                    try:
                        RunManager(PROJECTS_DIR).archive_run(current_run_id)
                    except Exception:
                        logger.debug("Failed to archive run %s", current_run_id, exc_info=True)
                    return collected

            # Check timeout
            try:
                manager = RunManager(PROJECTS_DIR)
                instance = manager.find_run(current_run_id)
                age = (datetime.now() - instance.created_at).total_seconds()
                if age > DEFAULT_TASK_TIMEOUT:
                    logger.warning("Run %s timed out (age=%ds)", current_run_id, int(age))
                    ctx_mgr.release_context()

                    task = self._find_task_for_run(current_run_id)
                    if task:
                        from frago.server.services.ingestion.models import TaskStatus
                        from frago.server.services.ingestion.store import TaskStore
                        TaskStore().update_status(task.id, TaskStatus.TIMEOUT)

                    collected.append({
                        "run_id": current_run_id,
                        "task_id": task.id if task else None,
                        "status": "timeout",
                        "summary": f"Run 超时 ({int(age)}s)",
                    })

                    try:
                        manager.archive_run(current_run_id)
                    except Exception:
                        logger.debug("Failed to archive timed-out run", exc_info=True)
            except RunNotFoundError:
                # Run disappeared, release lock
                ctx_mgr.release_context()

        except Exception:
            logger.debug("_check_results error", exc_info=True)

        return collected

    def _find_task_for_run(self, run_id: str) -> Any:
        """Find the IngestedTask associated with a run_id."""
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            executing = store.get_by_status(TaskStatus.EXECUTING)
            for task in executing:
                if task.session_id == run_id:
                    return task
        except Exception:
            pass
        return None

    # -- helpers --

    def _has_pending_tasks(self) -> bool:
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            return len(TaskStore().get_by_status(TaskStatus.PENDING)) > 0
        except Exception:
            return False

    def _has_overtime_dispatched(self) -> bool:
        """Check if any dispatched task's run has exceeded timeout."""
        try:
            from frago.run.context import ContextManager
            from frago.run.manager import RunManager
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            run_id = ctx_mgr.get_current_run_id()
            if not run_id:
                return False
            manager = RunManager(PROJECTS_DIR)
            instance = manager.find_run(run_id)
            age = (datetime.now() - instance.created_at).total_seconds()
            return age > DEFAULT_TASK_TIMEOUT
        except Exception:
            return False

    def _should_rotate(self) -> bool:
        """Check if session rotation is needed."""
        if self._total_turns >= ROTATION_TURN_THRESHOLD:
            return True
        return self._accumulated_tokens >= ROTATION_TOKEN_THRESHOLD

    def _format_heartbeat_message(self, collected: list[dict]) -> str:
        """Build heartbeat message with minimal context for PA."""
        now = datetime.now(UTC)
        parts = [f"--- 心跳 [{self._heartbeat_seq}] ---"]
        parts.append(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # New results from _check_results
        if collected:
            parts.append("\n完成的任务:")
            for c in collected:
                parts.append(f"  - [{c['status']}] run={c.get('run_id', '?')}: {c.get('summary', '')[:100]}")

        # Current Run status
        try:
            from frago.run.context import ContextManager
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            current_run_id = ctx_mgr.get_current_run_id()
            if current_run_id:
                parts.append(f"\n当前执行中 Run: {current_run_id}")
            else:
                parts.append("\n当前执行中 Run: 无（空闲）")
        except Exception:
            pass

        # Pending tasks
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            pending = store.get_by_status(TaskStatus.PENDING)
            if pending:
                parts.append(f"\n待处理任务 ({len(pending)} 个):")
                for t in pending[:5]:
                    prompt_preview = t.prompt[:100] if len(t.prompt) <= 100 else t.prompt[:100] + "..."
                    parts.append(f"  - [task_id={t.id}] ({t.channel}) {prompt_preview}")
        except Exception:
            pass

        return "\n".join(parts)

    @staticmethod
    def _build_sub_agent_prompt(
        task_id: str | None,
        task_prompt: str,
        run_id: str,
        related_runs: list[str] | None = None,
    ) -> str:
        """Build the prompt for a sub-agent working in a Run instance."""
        related_section = ""
        if related_runs:
            lines = ["相关历史 Run（可用 frago run info <run_id> 查看详情）:"]
            for rid in related_runs:
                lines.append(f"  - {rid}")
            related_section = "\n" + "\n".join(lines) + "\n"

        # Look up reply_context from TaskStore
        reply_context_str = "{}"
        channel = "unknown"
        message_id = ""
        if task_id:
            try:
                from frago.server.services.ingestion.store import TaskStore
                store = TaskStore()
                task = store.get(task_id)
                if task:
                    reply_context_str = json.dumps(task.reply_context, ensure_ascii=False)
                    channel = task.channel
                    message_id = task.channel_message_id
            except Exception:
                pass

        # Load agent self-knowledge index
        knowledge_section = ""
        try:
            knowledge_file = Path(__file__).parent / "agent_knowledge.json"
            knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
            knowledge_section = "\nfrago 系统索引:\n" + json.dumps(knowledge, ensure_ascii=False, indent=2) + "\n"
        except Exception:
            pass

        return f"""\
/frago.run {task_prompt}

Run 实例: {run_id}
来源: {channel} (消息 ID: {message_id})
{related_section}{knowledge_section}
完成后:
1. frago run log --step "TASK_COMPLETE" --status "success" --action-type "other" --execution-method "analysis" --data '{{"summary": "一句话总结"}}'
2. frago reply --channel {channel} --params '{{"text": "你的回复内容", "reply_context": {reply_context_str}}}'

失败时:
1. frago run log --step "TASK_FAILED" --status "error" --action-type "other" --execution-method "analysis" --data '{{"error": "失败原因"}}'

当前 Run 上下文: FRAGO_CURRENT_RUN={run_id}
"""

    # -- persistence --

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
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.error("Failed to save PA session_id: %s", e)

    @staticmethod
    async def _wait_for_session_id(internal_id: str, timeout: float = 30.0) -> str:
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

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}秒"
        if seconds < 3600:
            return f"{seconds // 60}分钟"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}小时{minutes}分钟"
        return f"{hours}小时"
