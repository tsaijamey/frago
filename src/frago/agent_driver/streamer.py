"""Transcript 持续流式转发（spec 20260607 Phase 6；来源抽象化 20260725 Phase 2）。

``TranscriptStreamer`` 轮询一个 ``TranscriptSource``，把**新增**记录（已归一化成
``ParsedRecord``）交给回调。attached 流式因此不再依赖 ``claude -p`` 的 stream-json：
记录里有完整正文块与完整 ``tool_use.input``，唯一差异是粒度以**内容块**为单位、
没有 token 碎片。

与 PA 的 transcript 转发器（``server/services/primary/watcher.py``）的分工：那个
只投「本轮答完的终答」（whole-turn，判 done 才发），本类要的是**逐记录**的实时事件
（文本块 + 工具调用），两者粒度不同，故各自独立。

Design Principle 1（主路径零 agent 分支）在本模块的兑现：记录**存在哪、怎么解析**
全部落在 driver 提供的来源对象里（``AgentDriver.transcript_source``），本类只管
"隔一拍问一次有没有新的"。本文件 NEVER 出现 ``if agent == "claude"``。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from frago.agent_driver.transcript_source import TranscriptSource
    from frago.session.parser import ParsedRecord

logger = logging.getLogger(__name__)


class TranscriptStreamer:
    """轮询一个记录来源，按记录粒度发射归一化后的 ``ParsedRecord``。

    去重与断点续读的责任在来源自己（文件版记字节偏移、会话库版记片段游标），本类
    只保证"取到就发、取空就等"。
    """

    def __init__(
        self,
        source: TranscriptSource,
        *,
        poll_interval_s: float = 0.3,
        missing_backoff_start_s: float = 0.2,
        missing_backoff_max_s: float = 5.0,
    ) -> None:
        self._source = source
        self._poll_interval_s = poll_interval_s
        self._missing_backoff_start_s = missing_backoff_start_s
        self._missing_backoff_max_s = missing_backoff_max_s

    @property
    def source(self) -> TranscriptSource:
        return self._source

    @property
    def native_session_id(self) -> str | None:
        """该会话在 agent 自己那边的原生会话 id（来源尚未出现时 None）。"""
        return self._source.native_session_id

    def seek_to_end(self) -> None:
        """把来源的游标锚到当前末尾（baseline）。

        首轮投喂**之前**调用：续接既有会话时记录里已有整段历史，不锚基线会把历史
        当「新增」全量重放给前端。
        """
        self._source.seek_to_end()

    def poll_once(self) -> list[ParsedRecord]:
        """读出自上次以来的新增记录。来源不可用时返回空列表，NEVER 抛。"""
        try:
            return self._source.poll_once()
        except Exception:
            logger.debug("TranscriptStreamer: source.poll_once raised", exc_info=True)
            return []

    # ── 异步循环 ────────────────────────────────────────────────────
    async def drain(self, on_record: Callable[[ParsedRecord], Awaitable[None]]) -> None:
        """把当前已落盘的新增记录一次性发完（收尾用，不等待）。"""
        for record in await asyncio.to_thread(self.poll_once):
            await on_record(record)

    async def run(self, on_record: Callable[[ParsedRecord], Awaitable[None]]) -> None:
        """持续轮询并发射，直到被 cancel。

        来源尚未出现时按退避轮询（``missing_backoff_start_s`` 起，每次翻倍，封顶
        ``missing_backoff_max_s``）——NEVER 死等（会话起来后必须自动接上），也 NEVER
        立刻放弃（claude 的 jsonl 在 TUI 启动后才落盘，opencode 的会话行要等首轮
        提交才建）。来源出现后回到固定的 ``poll_interval_s`` 节奏。
        """
        backoff = self._missing_backoff_start_s
        while True:
            records = await asyncio.to_thread(self.poll_once)
            if records:
                for record in records:
                    await on_record(record)
            if self._source.native_session_id is None:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._missing_backoff_max_s)
                continue
            backoff = self._missing_backoff_start_s
            await asyncio.sleep(self._poll_interval_s)
