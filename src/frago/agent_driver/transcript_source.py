"""会话记录的增量读取来源（spec 20260725 Phase 2）。

``TranscriptStreamer`` 原先直接假设"记录 = 一个文件 + 字节偏移"。这个假设只对
claude 那种把每轮追加进 JSONL 的 agent 成立；opencode 把记录搬进了 SQLite，没有
"一个文件"也没有字节偏移可言。所以把假设从共用代码里摘出来：streamer 只要求
"锚基线 / 取增量 / 报原生会话 id"这三件事，怎么存是各 driver 自己的事。

``JsonlTranscriptSource`` 是原逻辑原封不动的搬迁（路径解析、只消费整行、换文件
归零偏移、走 ``session.monitor`` 的 adapter 解析），claude 的行为一字未变。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from frago.session.parser import ParsedRecord

logger = logging.getLogger(__name__)


@runtime_checkable
class TranscriptSource(Protocol):
    """一个 agent 会话记录的可增量读取来源。"""

    def seek_to_end(self) -> None:
        """把游标锚到当前末尾。

        首轮投喂**之前**调用：续接一个既有会话时记录里已有整段历史，不锚基线会
        把历史当「新增」全量重放给前端。
        """
        ...

    def poll_once(self) -> list[ParsedRecord]:
        """取自上次以来的新增记录。

        来源尚不可用（文件未生成 / 会话未认领 / 库被占）时返回空列表，NEVER 抛
        —— 调用方是一个持续轮询的循环，一次读失败只该丢掉这一拍。
        """
        ...

    @property
    def native_session_id(self) -> str | None:
        """该会话在 agent 自己那边的原生会话 id；未知时 None。

        未知同时也是"来源还没出现"的信号，轮询循环据此退避。
        """
        ...


class JsonlTranscriptSource:
    """JSONL 文件版记录来源（claude）。

    ``path_provider`` 每次调用返回当前 transcript 路径（尚未生成时 None）——路径
    由 driver 决定，本类不猜。``agent_type`` 决定用哪个 ``AgentAdapter`` 解析。

    断点续读：以**字节偏移**记录已消费位置，只消费以换行结尾的完整行（写入方正在
    追加半行时不会被截断解析），偏移随之推进，故同一条记录 NEVER 发射两次。
    """

    def __init__(self, agent_type: str, path_provider: Callable[[], Path | None]) -> None:
        self._agent_type = agent_type
        self._path_provider = path_provider
        self._path: Path | None = None
        self._offset = 0
        self._adapter: Any | None = None
        self._adapter_resolved = False

    # ── 路径与偏移 ──────────────────────────────────────────────────
    @property
    def path(self) -> Path | None:
        """当前已锁定的 transcript 路径（尚未出现时 None）。"""
        return self._path

    @property
    def native_session_id(self) -> str | None:
        """文件名去掉扩展名**就是** agent 的原生会话 id（driver 启动时用的那个）。"""
        return self._path.stem if self._path is not None else None

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
            logger.warning("JsonlTranscriptSource: unknown agent_type=%r", self._agent_type)
            return None
        self._adapter = get_adapter(at)
        if self._adapter is None:
            logger.warning(
                "JsonlTranscriptSource: no adapter for agent_type=%r", self._agent_type
            )
        return self._adapter

    def seek_to_end(self) -> None:
        """把偏移锚到当前文件末尾（baseline）。

        文件不存在时偏移留 0，文件出现后自然从头读（此时从头即是新增）。
        """
        path = self._resolve_path()
        if path is None:
            return
        try:
            self._offset = path.stat().st_size
        except OSError:
            self._offset = 0

    # ── 读一拍 ──────────────────────────────────────────────────────
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
                logger.debug("JsonlTranscriptSource: skipping non-JSON line")
                continue
            if not isinstance(data, dict):
                continue
            try:
                record = adapter.parse_record(data)
            except Exception:
                logger.debug(
                    "JsonlTranscriptSource: adapter.parse_record raised", exc_info=True
                )
                continue
            if record is not None:
                records.append(record)
        return records
