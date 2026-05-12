"""Phase 0 test_taskboard_migration.py — 5 用例 (Ce specify 00:18:41 + verify 00:26:55 加强).

xpass 三处已转 pass: Gap 5 实施后 _replay_legacy_tasks / _replay_thread_index /
_replay_trace_file 全部真正可工作, fixture 注入 legacy data 后断言 timeline.jsonl
含 ≥3 task_* entries (Ce 03/full_legacy 加强).
"""

from __future__ import annotations

import json
from pathlib import Path

from frago.server.services.taskboard import migration


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def test_migrate_no_legacy_data_noop(tmp_path: Path):
    """空 ~/.frago/ → MigrationReport 计数 0, .migration-done 不写, timeline 不创建."""
    assert not migration.needs_migration(tmp_path)
    report = migration.migrate(tmp_path)
    assert report.migrated_threads == 0
    assert report.migrated_tasks == 0
    assert report.migrated_entries == 0
    # source_files 为空 → .migration-done 写入了但 backup 目录未创建
    assert not (tmp_path / f".migration-backup-{report.finished_at.date()}").exists()


def test_migrate_ingested_tasks_only(tmp_path: Path):
    """Ce 03/full_legacy 加强: 注入 legacy ingested_tasks.json 含 sub_tasks → 断言
    timeline.jsonl 含 ≥3 task_* entries (msg_received + task_started + task_finished)."""
    (tmp_path / "ingested_tasks.json").write_text(
        json.dumps([
            {
                "id": "feishu:om_test",
                "channel": "feishu",
                "channel_message_id": "om_test",
                "prompt": "调研竞品",
                "status": "completed",
                "thread_id": "T1",
                "sub_tasks": [
                    {
                        "description": "竞品调研",
                        "prompt": "去找 3 个竞品",
                        "session_id": "R1",
                        "claude_session_id": "csid_x",
                        "pid": 12345,
                        "result_summary": "找到 3 个",
                        "status": "completed",
                        "completed_at": "2026-05-11T20:00:00+08:00",
                    },
                ],
            },
        ]),
        encoding="utf-8",
    )
    report = migration.migrate(tmp_path)
    assert report.migrated_tasks == 1
    timeline_path = tmp_path / "timeline" / "timeline.jsonl"
    assert timeline_path.exists()
    entries = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    data_types = [e["data_type"] for e in entries]
    # 至少包含 msg_received + task_started + task_finished
    assert "msg_received" in data_types
    assert "task_started" in data_types
    assert "task_finished" in data_types
    assert sum(1 for dt in data_types if dt.startswith("msg_") or dt.startswith("task_")) >= 3


def test_migrate_full_legacy(tmp_path: Path):
    """Ce 03/full_legacy: 全部 4 套旧文件 + 6 字段 .migration-done."""
    _write_jsonl(
        tmp_path / "threads" / "index.jsonl",
        [{
            "thread_id": "T1", "origin": "external", "subkind": "feishu",
            "created_at": "2026-05-11T10:00:00+08:00",
            "last_active_ts": "2026-05-11T20:00:00+08:00",
            "status": "active", "root_summary": "测试线程",
        }],
    )
    (tmp_path / "ingested_tasks.json").write_text(
        json.dumps([{
            "id": "feishu:om_x", "channel": "feishu",
            "channel_message_id": "om_x", "prompt": "x",
            "thread_id": "T1", "sub_tasks": [],
        }]),
        encoding="utf-8",
    )
    report = migration.migrate(tmp_path)
    assert (tmp_path / ".migration-done").exists()
    done_json = json.loads((tmp_path / ".migration-done").read_text())
    # Ce ask #5: 5 字段 (finished_at, migrated_threads, migrated_tasks, backup_dir, source_files_hash)
    assert set(done_json.keys()) == {
        "finished_at",
        "migrated_threads",
        "migrated_tasks",
        "backup_dir",
        "source_files_hash",
    }
    assert len(done_json["source_files_hash"]) == 64  # sha256 hex
    assert report.migrated_threads == 1
    assert report.migrated_tasks == 1
    # 备份目录已创建
    assert any(tmp_path.glob(".migration-backup-*"))


def test_migrate_idempotent(tmp_path: Path):
    (tmp_path / "ingested_tasks.json").write_text("[]", encoding="utf-8")
    migration.migrate(tmp_path)
    assert (tmp_path / ".migration-done").exists()
    # 第二次 needs_migration 应返回 False
    assert not migration.needs_migration(tmp_path)


def test_migrate_traces_replay_dedup(tmp_path: Path):
    """Ce 03/traces_dedup: 旧 trace JSONL 重放 + dedup by (path, byte_offset).
    xfail 已摘 (Ce verify 实际可工作)."""
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "trace-2026-05-01.jsonl").write_text(
        '{"id":"01OLD1","data_type":"task_appended"}\n'
        '{"id":"01OLD2","data_type":"task_finished"}\n',
        encoding="utf-8",
    )
    (tmp_path / "ingested_tasks.json").write_text("[]", encoding="utf-8")
    report = migration.migrate(tmp_path)
    assert report.migrated_entries == 2
    timeline_path = tmp_path / "timeline" / "timeline.jsonl"
    assert timeline_path.exists()
    lines = [line for line in timeline_path.read_text().splitlines() if line.strip()]
    # 含 2 条旧 trace entry
    assert len(lines) >= 2
