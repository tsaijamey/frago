"""Phase 0 test_taskboard_migration.py — 5 用例 (Ce specify 00:18:41).

Phase 0 minimum viable: noop + idempotent 已实测; legacy 数据解析 _replay_*
属于 Phase 0 后续 commit 范围, 这里的 test_migrate_ingested_tasks_only /
test_migrate_full_legacy 标 xfail 待补 (Ce verify 阶段会跑实际数据 fixture)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.server.services.taskboard import migration


def test_migrate_no_legacy_data_noop(tmp_path: Path):
    """空 ~/.frago/ → MigrationReport 计数 0, .migration-done 不写."""
    assert not migration.needs_migration(tmp_path)


@pytest.mark.xfail(reason="Phase 0 后续 commit 补 _replay_legacy_tasks 实现")
def test_migrate_ingested_tasks_only(tmp_path: Path):
    (tmp_path / "ingested_tasks.json").write_text(
        json.dumps([{"id": "feishu:om_x", "channel": "feishu"}]), encoding="utf-8"
    )
    report = migration.migrate(tmp_path)
    assert report.migrated_tasks >= 1


@pytest.mark.xfail(reason="Phase 0 后续 commit 补 full legacy 重放")
def test_migrate_full_legacy(tmp_path: Path):
    (tmp_path / "ingested_tasks.json").write_text("[]", encoding="utf-8")
    (tmp_path / "threads").mkdir()
    (tmp_path / "threads" / "index.jsonl").write_text("", encoding="utf-8")
    report = migration.migrate(tmp_path)
    assert (tmp_path / ".migration-done").exists()
    done_json = json.loads((tmp_path / ".migration-done").read_text())
    # Ce ask #5: 6 字段含 source_files_hash sha256
    assert set(done_json.keys()) == {
        "finished_at",
        "migrated_threads",
        "migrated_tasks",
        "backup_dir",
        "source_files_hash",
    }
    assert len(done_json["source_files_hash"]) == 64  # sha256 hex


def test_migrate_idempotent(tmp_path: Path):
    (tmp_path / "ingested_tasks.json").write_text("[]", encoding="utf-8")
    migration.migrate(tmp_path)
    assert (tmp_path / ".migration-done").exists()
    # 第二次 needs_migration 应返回 False
    assert not migration.needs_migration(tmp_path)


@pytest.mark.xfail(reason="Phase 0 后续 commit 补 trace dedup 实测")
def test_migrate_traces_replay_dedup(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "trace-2026-05-01.jsonl").write_text(
        '{"id":"01OLD1","data_type":"task_appended"}\n', encoding="utf-8"
    )
    report = migration.migrate(tmp_path)
    assert report.migrated_entries == 1
