"""Timeline: 单一持久化点 ~/.frago/timeline/timeline.jsonl (append-only).

ulid_new() module-level (Ce ask #1: 不放 utils, 不在 models 内, 锁 import 路径
`from frago.server.services.taskboard.timeline import ulid_new`)。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from frago.server.services.taskboard.models import TimelineEntry

# Crockford base32 字母表 (ULID 标准)
_CROCKFORD_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RAND_BITS = 80
_ULID_RAND_BYTES = _ULID_RAND_BITS // 8

_ulid_lock = threading.Lock()
_ulid_last_ms = 0
_ulid_last_rand = 0


def ulid_new() -> str:
    """生成 ULID (26 字符 Crockford-base32), 同毫秒内单调递增。

    Ce ask #1 锁定: ULID 字符集 + 单调性可断言, 不校函数位置。
    """
    global _ulid_last_ms, _ulid_last_rand
    with _ulid_lock:
        ms = int(time.time() * 1000)
        if ms == _ulid_last_ms:
            _ulid_last_rand += 1
            rand_int = _ulid_last_rand
        else:
            rand_bytes = secrets.token_bytes(_ULID_RAND_BYTES)
            rand_int = int.from_bytes(rand_bytes, "big")
            _ulid_last_ms = ms
            _ulid_last_rand = rand_int

    # 编码: 48-bit timestamp + 80-bit randomness → 26 chars
    raw = (ms << _ULID_RAND_BITS) | (rand_int & ((1 << _ULID_RAND_BITS) - 1))
    out = []
    for i in range(26):
        shift = (25 - i) * 5
        out.append(_CROCKFORD_B32[(raw >> shift) & 0x1F])
    return "".join(out)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Unhandled type: {type(obj)}")


class Timeline:
    """append-only 写入器 + 迭代器。fsync 在调用方控制。"""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append_entry(
        self,
        *,
        data_type: str,
        by: str,
        thread_id: str | None = None,
        msg_id: str | None = None,
        task_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> TimelineEntry:
        entry = TimelineEntry(
            entry_id=ulid_new(),
            ts=datetime.now().astimezone(),
            data_type=data_type,
            by=by,
            thread_id=thread_id,
            msg_id=msg_id,
            task_id=task_id,
            data=data or {},
        )
        line = json.dumps(asdict(entry), ensure_ascii=False, default=_serialize)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return entry

    def fsync(self) -> None:
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.flush()
                os.fsync(f.fileno())

    def iter_entries(self) -> Iterator[dict[str, Any]]:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # 损坏的尾部行跳过 (Phase 0 简化, Phase 2 vacuum 会清理)
                    continue
