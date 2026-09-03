"""Keeps the virtual desktop alive — unless a person said to stop it.

The virtual desktop (``frago.desktop``) is meant to be there whenever someone
wants it: an agent sends a command and the stage is already running. Before this
service, nothing kept it up. It was started by hand, and once its process was
gone — crashed, killed by a restart, reaped by the OS — everything downstream
kept behaving as if it were still there: the registry still said ``running``,
the desktop page kept showing its last frame, and the next command failed with a
connection error that named a port rather than the reason.

It had never once worked on this machine
----------------------------------------
Until 2026-09-02 the stage was a recipe on disk, and this service reached it the
way one reaches a recipe: it loaded the registry module *by path* and started
the stage through ``RecipeRunner``. The registry demanded that whoever imports it
declare where the stage keeps its ledger (``FRAGO_RECIPE_DATA_DIR``), and the
server never did. So every scan raised, and ``_loop`` swallowed it into a single
WARNING line — 4005 consecutive times, once every fifteen seconds. The desktop on
this machine was never supervised, and nothing above WARNING ever said so.

Both halves are now plain in-package calls: ``frago.desktop.registry`` for the
state, ``frago.desktop.stage.up()`` for the start. The environment-variable
handover that rotted is gone — the registry works its own landing spot out, so
there is no longer anything for a caller to forget.

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

logger = logging.getLogger(__name__)

# 巡检节奏。桌面不在了要多久能被拉起来，取决于这个数；太密则每次都要读注册表、
# 探端口，纯属噪声。十五秒是"人切个标签回来它已经好了"的量级。
_SCAN_INTERVAL_S = 15.0

# 拉起动作本身要几秒（发布页面配置、起进程、等浏览器）。这段时间里不再重复触发，
# 否则一轮没跑完下一轮又来一次，会同时起好几个。
_START_COOLDOWN_S = 90.0

_INSTANCE = "default"


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
        # 从前这里有一道「配方装了没有」的闸。舞台跟着包走之后它永远为真，而且
        # ``_read_state`` 在没有实例记录时本来就返回 None、循环自己会早退——
        # 一道恒真的闸只会让读的人以为还有别的情况。
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

        用舞台自己的注册表模块，而不是自己解析那些 json：判定「在跑」要同时看
        进程和端口，那套判据只有一份，抄一份到这里必然漂移。从前这份判据住在
        配方目录里、只能按路径 import；搬进本体之后普通 import 把同一件事做得更好。
        """
        from frago.desktop import registry

        record = registry.read_instance(_INSTANCE)
        if record is None:
            return None
        return registry.wants_running(_INSTANCE), record.get("status") == "running"

    @staticmethod
    def _start_desktop() -> None:
        """把舞台拉起来。直调包内的 up()，不再经 RecipeRunner。

        少掉的不只是一层转发：走 RecipeRunner 就要套 ``frago.recipes.isolation``
        的沙箱，而舞台要开浏览器、读人的 profile、写 clips——那个沙箱正是搬家要
        脱掉的东西。
        """
        from frago.desktop import stage

        try:
            result = stage.up()
        except Exception as e:  # noqa: BLE001 —— 起不来不该拖垮巡检循环
            # 单独记，不让它冒到 _loop 的 except 里去：那条 WARNING 说的是
            # 「这一轮巡检本身崩了」，与「舞台没起来」是两件事，混在一起就分不出
            # 到底哪一环坏了——上一版把两件事混成一句，吞了 4005 次。
            logger.warning("Virtual OS start failed: %s", e)
            return
        runtime = result.get("runtime") if isinstance(result, dict) else None
        logger.info("Virtual OS started: %s", runtime)
