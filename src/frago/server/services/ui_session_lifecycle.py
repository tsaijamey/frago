"""WebUI 会话集群的空闲回收巡检 —— Phase 2 生命周期状态机。

spec 20260625-webui-session-lifecycle-mediator / Phase 2：server lifespan 内的
周期后台任务，定期扫描 UI runner 常驻的 tmux claude 会话，把「自最后一个终结性
stop_reason 起静默超过 idle_timeout_secs」的会话关掉（kill tmux），释放内存。

设计要点：
- **激活看 last_activity、回收看 jsonl 静默**：空闲判定锚定 claude 写的 jsonl，
  不看页面有没有输入——手动 attach 敲入也落同一 jsonl，双驾驶来源天然统一。
- **干活中绝不误杀**：探针 not done（末条 tool_use / 流式中）的会话不计时。
  具体逻辑在 UiSessionRunner.evict_idle，本服务只管周期触发。
- **复用同一 runner 单例**：操作的就是路由层 _get_runner() 持有的那个 pool。
- **阈值实时取 config**：每轮读 ~/.frago/config.json -> webui_sessions.idle_timeout_secs，
  改配置无需重启即生效。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

logger = logging.getLogger(__name__)

# 巡检间隔：远小于默认 30min 阈值，保证回收及时又不空转。
_SCAN_INTERVAL_S = 60.0


class UiSessionLifecycleService:
    """周期回收空闲 WebUI 会话的后台服务（单例）。"""

    _instance: UiSessionLifecycleService | None = None

    def __init__(self, *, scan_interval_s: float = _SCAN_INTERVAL_S) -> None:
        self._scan_interval_s = scan_interval_s
        self._task: asyncio.Task[None] | None = None

    @classmethod
    def get_instance(cls) -> UiSessionLifecycleService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "UiSessionLifecycleService started (scan every %.0fs)",
            self._scan_interval_s,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._scan_interval_s)
            try:
                await self._scan_once()
            except Exception as e:  # 单轮失败不拖垮巡检循环
                logger.warning("UI session idle scan failed: %s", e)

    async def _scan_once(self) -> None:
        from frago.init.config_manager import load_config
        from frago.server.routes.claude_sessions import _get_runner

        timeout_s = load_config().webui_sessions.idle_timeout_secs
        runner = _get_runner()
        # 探针读 jsonl + tmux kill 都是阻塞 IO，挪到线程里跑。
        evicted = await asyncio.to_thread(runner.evict_idle, float(timeout_s))
        if evicted:
            logger.info(
                "Reclaimed %d idle WebUI session(s): %s",
                len(evicted),
                ", ".join(evicted),
            )
