"""Skill management service.

会话页与技能页看到的 skill 都来自 frago 的集中副本 ``~/.frago/skills/``：各家 agent
目录里装的包由 :class:`SkillSyncService` 定时扫进来（见 :mod:`frago.skills.agent_skills`）。
从前这里只读 ``~/.claude/skills/``，codex 与 opencode 装的包界面上一个都看不见。
"""

import asyncio
import contextlib
import logging
import threading
from typing import Any, Optional

from frago.skills.agent_skills import ManagedSkillStore, SyncReport, scan_and_sync

logger = logging.getLogger(__name__)

#: 多久扫一次各家 agent 的 skill 目录。装一个新包，最多等这么久会话页就能点到它。
SKILL_SYNC_INTERVAL_SECONDS = 300


class SkillService:
    """Service for skill management operations.

    Note: This service always loads fresh from filesystem.
    For cached access via WebSocket updates, use StateManager.get_skills().
    """

    @staticmethod
    def get_skills(force_reload: bool = False) -> list[dict[str, Any]]:  # noqa: ARG004 — kept for API compatibility
        """Get list of available skills from the managed store."""
        return SkillService._load_skills()

    @staticmethod
    def _load_skills() -> list[dict[str, Any]]:
        store = ManagedSkillStore()
        skills = [
            {
                "name": s.name,
                "description": s.description,
                "file_path": str(s.skill_md(store.root)),
                "source_path": s.source_dir,
                "agents": list(s.agents),
            }
            for s in store.list()
        ]
        logger.debug("Loaded %d skills from %s", len(skills), store.root)
        return skills


class SkillSyncService:
    """定时把各家 agent 装的 skill 同步进 ``~/.frago/skills/``，有变化就推给界面。"""

    _instance: Optional["SkillSyncService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        # 定时那一轮与人手动点的那一轮不能同时往同一个目录里复制。
        self._sync_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "SkillSyncService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("Skill sync service started (interval: %ss)", SKILL_SYNC_INTERVAL_SECONDS)

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Skill sync service stopped")

    async def sync_now(self) -> SyncReport:
        """扫一轮。副本有变化就刷新状态并广播，界面上的 skill 清单跟着换。"""
        async with self._sync_lock:
            report = await asyncio.to_thread(scan_and_sync)
        if report.changed:
            logger.info("Skills synced: %s", report.summary())
            from frago.server.state import StateManager

            state = StateManager.get_instance()
            if state.is_initialized():
                await state.refresh_skills()
        return report

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.sync_now()
            except Exception as e:  # noqa: BLE001 — 一轮失败不该让定时扫描停掉
                logger.warning("Skill sync failed: %s", e)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=SKILL_SYNC_INTERVAL_SECONDS)
                break
            except TimeoutError:
                continue
