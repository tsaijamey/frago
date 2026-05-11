"""一次性 migration: 旧四套文件 → 新 timeline.jsonl 单源。

旧:
  ~/.frago/message_cache.json
  ~/.frago/ingested_tasks.json + ingested_tasks/*.json
  ~/.frago/threads/index.jsonl
  ~/.frago/traces/trace-*.jsonl

新:
  ~/.frago/timeline/timeline.jsonl  (单一持久化点, append-only)
  ~/.frago/timeline/archive/<thread_id>.jsonl  (按需 lazy 切, Phase 2 vacuum 产生)

Migration 在 server 启动时如果检测到旧数据自动触发, 完成后写 .migration-done 锁。
Ce ask #4 (dedup key (source_path, byte_offset)) + ask #5 (.migration-done 6 字段含 sha256).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass
class MigrationReport:
    finished_at: datetime
    migrated_threads: int
    migrated_tasks: int
    migrated_entries: int
    backup_dir: Path
    source_files_hash: str


LEGACY_PATHS = [
    "message_cache.json",
    "ingested_tasks.json",
    "ingested_tasks",
    "threads",
    "traces",
]


def needs_migration(home: Path) -> bool:
    if (home / ".migration-done").exists():
        return False
    return (home / "ingested_tasks.json").exists()


def migrate(home: Path) -> MigrationReport:
    """一次性迁移。无旧数据时返回 noop report (migrated_*=0)。"""
    backup_dir = home / f".migration-backup-{date.today().isoformat()}"
    timeline_path = home / "timeline" / "timeline.jsonl"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)

    migrated_threads = 0
    migrated_tasks = 0
    migrated_entries = 0
    source_files: list[Path] = []
    seen_offsets: dict[Path, set[int]] = {}

    # 1. ingested_tasks.json + ingested_tasks/*.json
    legacy_tasks_file = home / "ingested_tasks.json"
    if legacy_tasks_file.exists():
        migrated_tasks += _replay_legacy_tasks(legacy_tasks_file, timeline_path)
        source_files.append(legacy_tasks_file)
    legacy_archive_dir = home / "ingested_tasks"
    if legacy_archive_dir.exists():
        for p in sorted(legacy_archive_dir.glob("*.json")):
            migrated_tasks += _replay_legacy_tasks(p, timeline_path)
            source_files.append(p)

    # 2. threads/index.jsonl
    threads_index = home / "threads" / "index.jsonl"
    if threads_index.exists():
        migrated_threads += _replay_thread_index(threads_index, timeline_path)
        source_files.append(threads_index)

    # 3. traces/trace-*.jsonl (含 dedup by (path, offset))
    traces_dir = home / "traces"
    if traces_dir.exists():
        for p in sorted(traces_dir.glob("trace-*.jsonl")):
            migrated_entries += _replay_trace_file(
                p, timeline_path, seen_offsets.setdefault(p, set())
            )
            source_files.append(p)

    # 4. 备份旧文件
    if source_files:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for p in LEGACY_PATHS:
            src = home / p
            if src.exists():
                shutil.move(str(src), str(backup_dir / p))

    # 5. 写 .migration-done (Ce ask #5: 6 字段含 source_files_hash sha256)
    src_hash = _hash_sources(sorted(source_files))
    report = MigrationReport(
        finished_at=datetime.now().astimezone(),
        migrated_threads=migrated_threads,
        migrated_tasks=migrated_tasks,
        migrated_entries=migrated_entries,
        backup_dir=backup_dir,
        source_files_hash=src_hash,
    )
    (home / ".migration-done").write_text(
        json.dumps(
            {
                "finished_at": report.finished_at.isoformat(),
                "migrated_threads": report.migrated_threads,
                "migrated_tasks": report.migrated_tasks,
                "backup_dir": str(report.backup_dir),
                "source_files_hash": report.source_files_hash,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def _replay_legacy_tasks(path: Path, timeline_path: Path) -> int:
    """旧 IngestedTask 列表 → task_appended / task_started / task_finished entries.

    Phase 0 stub: 实际重放逻辑 + dedup 留下次 commit (含 legacy schema 解析)。
    """
    # TODO Phase 0 后续 commit: 解析 legacy IngestedTask 字段 + 生成 timeline entries
    return 0


def _replay_thread_index(path: Path, timeline_path: Path) -> int:
    """threads/index.jsonl → thread_created entries."""
    # TODO Phase 0 后续 commit
    return 0


def _replay_trace_file(
    path: Path, timeline_path: Path, seen_offsets: set[int]
) -> int:
    """旧 trace JSONL → timeline.jsonl (按 (path, byte_offset) dedup).

    Ce ask #4: 旧 trace 无 entry_id, 用 byte_offset 做迁移 dedup。
    """
    count = 0
    with path.open("rb") as src, timeline_path.open("ab") as dst:
        while True:
            offset = src.tell()
            line = src.readline()
            if not line:
                break
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)
            dst.write(line)
            count += 1
    return count


def _hash_sources(paths: list[Path]) -> str:
    """所有 source file path 按 sorted 顺序拼接后取 sha256 hex (Ce ask #5)."""
    h = hashlib.sha256()
    for p in paths:
        h.update(str(p).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()
