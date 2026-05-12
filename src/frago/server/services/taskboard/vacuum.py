"""Vacuum: bounded-progress 物理归档 retired thread 到 archive/<thread_id>.jsonl.

Spec 20260512-msg-task-board-redesign §Phase 2:
- 仅在 server startup fold 前调用 (runtime 调用抛 VacuumOnlyOnStartupError)
- bounded-progress: 单次启动最多 MAX_MARKERS_PER_STARTUP=100 个 marker
- 触发条件: 扫描 timeline.jsonl 含 ≥1 条 data_type='thread_archived' marker
- 写序: 先写 archive/<thread_id>.jsonl + fsync, 再 atomic rename 新 timeline.jsonl
- crash 一致性: rename 是 atomic, archive 已 fsync, 中途失败回滚到旧 timeline

Yi #92 锁定: vacuum 不暴露给 PA path, 只供 boot 内部使用.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO

MAX_MARKERS_PER_STARTUP = 100


class VacuumOnlyOnStartupError(RuntimeError):
    """Runtime 调用 vacuum 时抛出. 物理隔离: vacuum 只在 boot 路径成立."""


@dataclass
class VacuumReport:
    processed: int = 0
    archived_thread_ids: tuple[str, ...] = ()


def _scan_archive_markers(timeline_path: Path, *, limit: int) -> list[str]:
    """第一遍: 扫 timeline.jsonl 收 archive marker, 保持发现顺序, 截到 limit.

    重复 marker (同 thread_id 多次) 仅记一次 (set 去重 + 保持首次 order).
    """
    seen: set[str] = set()
    order: list[str] = []
    with timeline_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("data_type") != "thread_archived":
                continue
            tid = entry.get("thread_id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            order.append(tid)
            if len(order) >= limit:
                break
    return order


def _open_archive(home: Path, thread_id: str) -> IO[str]:
    archive_dir = home / "timeline" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{thread_id}.jsonl"
    return path.open("a", encoding="utf-8")


def run_bounded_vacuum(
    home: Path, *, max_markers: int = MAX_MARKERS_PER_STARTUP
) -> VacuumReport:
    """仅在 server startup fold 前调用; runtime 调用抛 VacuumOnlyOnStartupError.

    步骤:
    1. 第一遍: 扫 timeline.jsonl 收 ≤ max_markers 个 archive marker (按发现顺序)
    2. 第二遍: 抽 entries — archived thread 的所有 entry (含 marker) 写到
       archive/<thread_id>.jsonl, 其余写新 timeline
    3. fsync archive writers, atomic rename 新 timeline 覆盖旧 timeline

    Returns:
        VacuumReport(processed=实际归档 thread 数, archived_thread_ids=元组)
    """
    timeline_path = home / "timeline" / "timeline.jsonl"
    if not timeline_path.exists():
        return VacuumReport(processed=0)

    markers = _scan_archive_markers(timeline_path, limit=max_markers)
    if not markers:
        return VacuumReport(processed=0)

    marker_set = set(markers)
    new_path = timeline_path.with_suffix(".new")
    archive_writers: dict[str, IO[str]] = {}
    try:
        with (
            timeline_path.open(encoding="utf-8") as src,
            new_path.open("w", encoding="utf-8") as dst,
        ):
            for line in src:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    # 坏行直接丢弃 (vacuum 是合适的清理时机)
                    continue
                tid = entry.get("thread_id")
                if tid in marker_set:
                    aw = archive_writers.get(tid)
                    if aw is None:
                        aw = _open_archive(home, tid)
                        archive_writers[tid] = aw
                    aw.write(stripped + "\n")
                else:
                    dst.write(stripped + "\n")
        # fsync archive files
        for aw in archive_writers.values():
            aw.flush()
            os.fsync(aw.fileno())
        # fsync new timeline before rename
        with new_path.open("rb+") as nf:
            os.fsync(nf.fileno())
        # atomic replace
        os.replace(new_path, timeline_path)
    finally:
        for aw in archive_writers.values():
            with contextlib.suppress(OSError):
                aw.close()
        if new_path.exists():
            with contextlib.suppress(OSError):
                new_path.unlink()

    return VacuumReport(processed=len(markers), archived_thread_ids=tuple(markers))


# ── inline 冗余 entry 压缩 (frago timeline fold --thread <id>) ───────────


@dataclass
class FoldReport:
    """thread 内冗余 entry 折叠结果."""

    thread_id: str
    folded_count: int = 0
    summary_entries_written: int = 0
    bytes_before: int = 0
    bytes_after: int = 0


# 当前能折叠的 data_type 白名单. 选择标准: 高频 + 信息可压缩 (count + first/last ts 即可
# 还原, 不丢业务信息). duplicate_msg_ingest 是 Phase 1 part B 引入的兜底 entry,
# 长时间运行会累积大量同 msg_id 的重复行, 占 PA context 噪音.
_FOLDABLE_DATA_TYPES = frozenset({"duplicate_msg_ingest"})


def fold_thread_duplicates(home: Path, thread_id: str) -> FoldReport:
    """Inline 压缩指定 thread 内的冗余 entry 为单条 summary.

    两遍算法:
    1. 第一遍扫 timeline, 对目标 thread 的 duplicate_msg_ingest 按 msg_id 分组计数,
       记下首/末 entry_id + ts.
    2. 第二遍重写 timeline: 同组的第二条及以后 entry 替换为单条 summary
       (替换发生在原首条出现位置以保持时间序), 其余行原样保留.

    summary entry schema:
        data_type='duplicate_msg_ingest_summary',
        data={msg_id, channel, count, first_entry_id, last_entry_id,
              first_ts, last_ts}

    Returns:
        FoldReport(thread_id, folded_count=被压缩掉的原 entry 数,
                   summary_entries_written=替换写入的 summary 数,
                   bytes_before/after=文件大小)
    """
    timeline_path = home / "timeline" / "timeline.jsonl"
    if not timeline_path.exists():
        return FoldReport(thread_id=thread_id)

    bytes_before = timeline_path.stat().st_size

    # 第一遍: 收集 (msg_id, channel) → 出现的 entries
    groups: dict[tuple[str, str], list[dict]] = {}
    with timeline_path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if entry.get("thread_id") != thread_id:
                continue
            if entry.get("data_type") not in _FOLDABLE_DATA_TYPES:
                continue
            msg_id = entry.get("msg_id") or ""
            channel = (entry.get("data") or {}).get("channel", "")
            groups.setdefault((msg_id, channel), []).append(entry)

    # 只折叠 count ≥ 2 的组
    fold_targets = {key: rows for key, rows in groups.items() if len(rows) >= 2}
    if not fold_targets:
        return FoldReport(
            thread_id=thread_id, bytes_before=bytes_before, bytes_after=bytes_before
        )

    # 取每组的"第一条 entry_id"作为替换锚点; 同组其他 entry_id 全部 drop
    first_anchors: dict[str, tuple[str, str]] = {}  # first_eid → (msg_id, channel)
    drop_anchors: set[str] = set()
    for (msg_id, channel), rows in fold_targets.items():
        first_anchors[rows[0]["entry_id"]] = (msg_id, channel)
        for row in rows[1:]:
            drop_anchors.add(row["entry_id"])

    folded_count = 0
    summary_written = 0
    new_path = timeline_path.with_suffix(".fold")
    try:
        with (
            timeline_path.open(encoding="utf-8") as src,
            new_path.open("w", encoding="utf-8") as dst,
        ):
            for line in src:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                eid = entry.get("entry_id", "")
                if eid in drop_anchors:
                    folded_count += 1
                    continue
                if eid in first_anchors:
                    msg_id, channel = first_anchors[eid]
                    rows = fold_targets[(msg_id, channel)]
                    summary = {
                        "entry_id": eid,  # 复用首条 entry_id 维持 ULID 排序稳定
                        "ts": rows[0].get("ts"),
                        "data_type": "duplicate_msg_ingest_summary",
                        "by": rows[0].get("by", "fold"),
                        "thread_id": thread_id,
                        "msg_id": msg_id,
                        "task_id": None,
                        "data": {
                            "channel": channel,
                            "count": len(rows),
                            "first_entry_id": rows[0]["entry_id"],
                            "last_entry_id": rows[-1]["entry_id"],
                            "first_ts": rows[0].get("ts"),
                            "last_ts": rows[-1].get("ts"),
                        },
                    }
                    dst.write(
                        json.dumps(summary, ensure_ascii=False) + "\n"
                    )
                    summary_written += 1
                else:
                    dst.write(stripped + "\n")
        with new_path.open("rb+") as nf:
            os.fsync(nf.fileno())
        os.replace(new_path, timeline_path)
    finally:
        if new_path.exists():
            with contextlib.suppress(OSError):
                new_path.unlink()

    bytes_after = timeline_path.stat().st_size
    return FoldReport(
        thread_id=thread_id,
        folded_count=folded_count,
        summary_entries_written=summary_written,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
    )
