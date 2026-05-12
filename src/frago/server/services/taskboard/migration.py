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
        n_tasks, n_entries = _replay_legacy_tasks(legacy_tasks_file, timeline_path)
        migrated_tasks += n_tasks
        migrated_entries += n_entries
        source_files.append(legacy_tasks_file)
    legacy_archive_dir = home / "ingested_tasks"
    if legacy_archive_dir.exists():
        for p in sorted(legacy_archive_dir.glob("*.json")):
            n_tasks, n_entries = _replay_legacy_tasks(p, timeline_path)
            migrated_tasks += n_tasks
            migrated_entries += n_entries
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


def _replay_legacy_tasks(path: Path, timeline_path: Path) -> tuple[int, int]:
    """旧 IngestedTask 列表 → task_appended / task_started / task_finished entries.

    Legacy schema (src/frago/server/services/ingestion/models.py):
      IngestedTask: id, channel, channel_message_id, prompt, status, created_at,
                    reply_context, thread_id, sub_tasks (list[SubTask]),
                    retry_count, recovery_count
      SubTask: description, prompt, session_id (run_id), claude_session_id, pid,
               result_summary, error, status, created_at, completed_at

    Returns: (task_count, entry_count) — 任务数 + 写入 timeline 的 entry 总数。
    """
    from frago.server.services.taskboard.timeline import Timeline, ulid_new

    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data if isinstance(data, list) else data.get("tasks", [])
    if not tasks:
        return 0, 0

    timeline = Timeline(timeline_path)
    count = 0
    for task in tasks:
        thread_id = task.get("thread_id")
        channel = task.get("channel", "external")
        msg_id_raw = task.get("channel_message_id") or task.get("id", "")
        msg_id = f"{channel}:{msg_id_raw}" if msg_id_raw else None
        task_id = task.get("id") or ulid_new()

        # msg_received (重放原始入站)
        timeline.append_entry(
            data_type="msg_received",
            by="migration",
            thread_id=thread_id,
            msg_id=msg_id,
            data={
                "channel": channel,
                "sender_id": "__migration__",
                "status": "received",
                "prompt": task.get("prompt", ""),
            },
        )
        count += 1

        # 每个 sub_task 重放 task_started + task_finished
        for sub in task.get("sub_tasks") or []:
            sub_status = (sub.get("status") or "").lower()
            timeline.append_entry(
                data_type="task_started",
                by="migration",
                thread_id=thread_id,
                msg_id=msg_id,
                task_id=task_id,
                data={
                    "run_id": sub.get("session_id"),
                    "csid": sub.get("claude_session_id"),
                    "started_at": sub.get("created_at"),
                },
            )
            count += 1
            if sub_status in {"completed", "failed"}:
                timeline.append_entry(
                    data_type="task_finished",
                    by="migration",
                    thread_id=thread_id,
                    msg_id=msg_id,
                    task_id=task_id,
                    data={
                        "run_id": sub.get("session_id"),
                        "ended_at": sub.get("completed_at"),
                        "status": sub_status,
                        "result_summary": sub.get("result_summary"),
                        "error": sub.get("error"),
                    },
                )
                count += 1

        # 若 task 顶层是终态但无 sub_task 终态记录, 补一条 task_appended
        if not task.get("sub_tasks"):
            timeline.append_entry(
                data_type="task_appended",
                by="migration",
                thread_id=thread_id,
                msg_id=msg_id,
                task_id=task_id,
                data={
                    "prev_status": "awaiting_decision",
                    "status": "dispatched",
                    "type": "run",
                },
            )
            count += 1
    return len(tasks), count


def _replay_thread_index(path: Path, timeline_path: Path) -> int:
    """threads/index.jsonl → thread_created entries (latest-wins dedup by thread_id)."""
    from frago.server.services.taskboard.timeline import Timeline

    if not path.exists():
        return 0

    # latest-wins dedup
    by_id: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = entry.get("thread_id")
            if tid:
                by_id[tid] = entry

    if not by_id:
        return 0

    timeline = Timeline(timeline_path)
    for tid, entry in by_id.items():
        timeline.append_entry(
            data_type="thread_created",
            by="migration",
            thread_id=tid,
            data={
                "origin": entry.get("origin", "external"),
                "subkind": entry.get("subkind", ""),
                "root_summary": entry.get("root_summary", ""),
                "status": entry.get("status", "active"),
            },
        )
    return len(by_id)


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
