"""Transcript 持续流式转发（spec 20260607 Phase 6）。

``TranscriptStreamer`` tail 一个 agent 的 transcript，把**新增**记录经既有
``AgentAdapter`` 归一化成 ``ParsedRecord`` 后交给回调。attached 流式因此不再依赖
``claude -p`` 的 stream-json：JSONL 里有完整正文块与完整 ``tool_use.input``，唯一
差异是粒度以**内容块**为单位、没有 token 碎片。

与 PA 的 transcript 转发器（``server/services/primary/watcher.py``）的分工：那个
只投「本轮答完的终答」（whole-turn，判 done 才发），本类要的是**逐记录**的实时事件
（文本块 + 工具调用），两者粒度不同，故各自独立。

Design Principle 1（主路径零 agent 分支）在本模块的兑现：
- transcript **路径**由 driver 提供（``AgentDriver.transcript_path``），本模块不认
  任何 agent 的目录布局；
- transcript **解析**走 ``session.monitor.get_adapter(agent_type)``，与
  ``agent_driver/transcript.py`` 同一套契约。
本文件 NEVER 出现 ``if agent == "claude"``。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from frago.session.parser import ParsedRecord

logger = logging.getLogger(__name__)


class TranscriptStreamer:
    """tail 一份 transcript，按记录粒度发射归一化后的 ``ParsedRecord``。

    ``path_provider`` 每次调用返回当前 transcript 路径（尚未生成时 None）——路径
    由 driver 决定，streamer 不猜。``agent_type`` 决定用哪个 ``AgentAdapter`` 解析。

    断点续读：以**字节偏移**记录已消费位置，只消费以换行结尾的完整行（写入方正在
    追加半行时不会被截断解析），偏移随之推进，故同一条记录 NEVER 发射两次。
    """

    def __init__(
        self,
        agent_type: str,
        path_provider: Callable[[], Path | None],
        *,
        poll_interval_s: float = 0.3,
        missing_backoff_start_s: float = 0.2,
        missing_backoff_max_s: float = 5.0,
    ) -> None:
        self._agent_type = agent_type
        self._path_provider = path_provider
        self._poll_interval_s = poll_interval_s
        self._missing_backoff_start_s = missing_backoff_start_s
        self._missing_backoff_max_s = missing_backoff_max_s
        self._path: Path | None = None
        self._offset = 0
        self._adapter: Any | None = None
        self._adapter_resolved = False

    # ── 路径与偏移 ──────────────────────────────────────────────────
    @property
    def path(self) -> Path | None:
        """当前已锁定的 transcript 路径（尚未出现时 None）。"""
        return self._path

    def _resolve_path(self) -> Path | None:
        """问 driver 要路径；换了文件就把偏移归零（新文件从头读）。"""
        try:
            path = self._path_provider()
        except Exception:
            logger.debug("transcript path_provider raised", exc_info=True)
            return self._path
        if path is not None and path != self._path:
            self._path = path
            self._offset = 0
        return self._path

    def _get_adapter(self) -> Any | None:
        """解析器按 agent_type 从既有注册表取，只解析一次并缓存。"""
        if self._adapter_resolved:
            return self._adapter
        self._adapter_resolved = True
        from frago.session.models import AgentType
        from frago.session.monitor import get_adapter

        try:
            at = AgentType(self._agent_type)
        except ValueError:
            logger.warning("TranscriptStreamer: unknown agent_type=%r", self._agent_type)
            return None
        self._adapter = get_adapter(at)
        if self._adapter is None:
            logger.warning("TranscriptStreamer: no adapter for agent_type=%r", self._agent_type)
        return self._adapter

    def seek_to_end(self) -> None:
        """把偏移锚到当前文件末尾（baseline）。

        首轮投喂**之前**调用：``--resume`` 一个既有会话时 transcript already 有整段
        历史，不锚 baseline 会把历史当「新增」全量重放给前端。文件不存在时偏移留 0，
        文件出现后自然从头读（此时从头即是新增）。
        """
        path = self._resolve_path()
        if path is None:
            return
        try:
            self._offset = path.stat().st_size
        except OSError:
            self._offset = 0

    # ── 同步核心：读一拍 ────────────────────────────────────────────
    def poll_once(self) -> list[ParsedRecord]:
        """读出自上次以来新增的完整记录。文件不存在 / 无解析器时返回空列表，NEVER 抛。"""
        path = self._resolve_path()
        if path is None:
            return []
        adapter = self._get_adapter()
        if adapter is None:
            return []

        try:
            with path.open("rb") as f:
                f.seek(self._offset)
                chunk = f.read()
        except OSError:
            # 文件尚未生成 / 正被替换 —— 下一拍再来，NEVER 崩。
            return []

        if not chunk:
            return []

        # 只消费以换行结尾的完整行；末尾半行留给下一拍（写入方可能正在追加）。
        consumed = chunk.rfind(b"\n")
        if consumed == -1:
            return []
        complete = chunk[: consumed + 1]
        self._offset += len(complete)

        records: list[ParsedRecord] = []
        for raw in complete.split(b"\n"):
            if not raw.strip():
                continue
            try:
                data = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                logger.debug("TranscriptStreamer: skipping non-JSON line")
                continue
            if not isinstance(data, dict):
                continue
            try:
                record = adapter.parse_record(data)
            except Exception:
                logger.debug("TranscriptStreamer: adapter.parse_record raised", exc_info=True)
                continue
            if record is not None:
                records.append(record)
        return records

    # ── 异步循环 ────────────────────────────────────────────────────
    async def drain(self, on_record: Callable[[ParsedRecord], Awaitable[None]]) -> None:
        """把当前已落盘的新增记录一次性发完（收尾用，不等待）。"""
        for record in await asyncio.to_thread(self.poll_once):
            await on_record(record)

    async def run(self, on_record: Callable[[ParsedRecord], Awaitable[None]]) -> None:
        """持续 tail 并发射，直到被 cancel。

        文件尚未生成时按退避轮询（``missing_backoff_start_s`` 起，每次翻倍，封顶
        ``missing_backoff_max_s``）——NEVER 死等（会话起来后必须自动接上），也 NEVER
        立刻放弃（claude 的 jsonl 在 TUI 启动后才落盘）。文件出现后回到固定的
        ``poll_interval_s`` 节奏。
        """
        backoff = self._missing_backoff_start_s
        while True:
            records = await asyncio.to_thread(self.poll_once)
            if records:
                for record in records:
                    await on_record(record)
            if self._path is None:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._missing_backoff_max_s)
                continue
            backoff = self._missing_backoff_start_s
            await asyncio.sleep(self._poll_interval_s)
