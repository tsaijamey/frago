"""Keeps the virtual desktop alive — unless a person said to stop it.

The virtual desktop (recipe ``agent_os``) is meant to be there whenever someone
wants it: an agent sends a command and the stage is already running. Before this
service, nothing kept it up. It was started by hand, and once its process was
gone — crashed, killed by a restart, reaped by the OS — everything downstream
kept behaving as if it were still there: the registry still said ``running``,
the desktop page kept showing its last frame, and the next command failed with a
connection error that named a port rather than the reason.

Why not the generic daemon supervisor
-------------------------------------
``DaemonService`` restarts a recipe whenever it exits with a non-zero code. The
stage's own stop command kills the process with a signal, and a signalled exit
is never zero — so the supervisor would immediately bring back what the person
just shut down, while the stop command's receipt says it succeeded. Lying to
the operator is worse than not supervising at all.

The difference is intent, and intent has to be written down. The registry
records whether a person *wants* the desktop running; this service only ever
starts something that is wanted and missing. Stopping it is therefore final
until someone runs ``aos up`` again — which flips the intent back as a side
effect of starting.

Exactly one instance
--------------------
The desktop is a singular thing: one virtual machine on this computer, one
address to look at it. This service only ever supervises the default instance.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 巡检节奏。桌面不在了要多久能被拉起来，取决于这个数；太密则每次都要读注册表、
# 探端口，纯属噪声。十五秒是"人切个标签回来它已经好了"的量级。
_SCAN_INTERVAL_S = 15.0

# 拉起动作本身要几秒（发布页面配置、起进程、等浏览器）。这段时间里不再重复触发，
# 否则一轮没跑完下一轮又来一次，会同时起好几个。
_START_COOLDOWN_S = 90.0

_RECIPE = "agent_os"
_INSTANCE = "default"
_REGISTRY = Path.home() / ".frago" / "recipes" / "workflows" / _RECIPE / "registry.py"


class VirtualOsLifecycleService:
    """Bring the virtual desktop back when it is wanted and missing."""

    _instance: VirtualOsLifecycleService | None = None

    def __init__(self, *, scan_interval_s: float = _SCAN_INTERVAL_S) -> None:
        self._scan_interval_s = scan_interval_s
        self._task: asyncio.Task[None] | None = None
        self._last_start_at = 0.0

    @classmethod
    def get_instance(cls) -> VirtualOsLifecycleService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not _REGISTRY.exists():
            logger.info("VirtualOsLifecycleService: recipe %s not installed, idle", _RECIPE)
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "VirtualOsLifecycleService started (scan every %.0fs)", self._scan_interval_s
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
                logger.warning("Virtual OS lifecycle scan failed: %s", e)

    async def _scan_once(self) -> None:
        import time

        state = await asyncio.to_thread(self._read_state)
        if state is None:
            return                      # 从来没建过实例，没有可守的东西
        wanted, alive = state
        if not wanted:
            return                      # 人明说了不想让它跑
        if alive:
            return

        if time.time() - self._last_start_at < _START_COOLDOWN_S:
            return
        self._last_start_at = time.time()
        logger.info("Virtual OS is wanted but not running — starting it")
        await asyncio.to_thread(self._start_desktop)

    @staticmethod
    def _read_state() -> tuple[bool, bool] | None:
        """(人想让它跑, 它确实在跑)。没有实例记录时返回 None。

        直接加载配方自带的注册表模块，而不是自己解析那些 json：判定「在跑」
        要同时看进程和端口，那套判据住在配方里，抄一份到这里必然漂移。
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location("_agent_os_registry", _REGISTRY)
        if spec is None or spec.loader is None:
            return None
        registry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registry)

        record = registry.read_instance(_INSTANCE)
        if record is None:
            return None
        return registry.wants_running(_INSTANCE), record.get("status") == "running"

    @staticmethod
    def _start_desktop() -> None:
        from frago.recipes.runner import RecipeRunner

        result = RecipeRunner().run(_RECIPE, {}, timeout=180)
        ok = isinstance(result, dict) and result.get("status") != "error"
        if ok:
            logger.info("Virtual OS started")
        else:
            logger.warning("Virtual OS start failed: %s", result)
