"""Phase 0 test_taskboard_fold.py — 4 用例 (Ce specify 00:18:41, Gap 2 新增).

含 T5.1 (case_marker_skip): fold 两遍跳过 archived_thread_ids。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.timeline import Timeline


def _write_timeline(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def test_fold_empty_timeline(tmp_path: Path):
    p = tmp_path / "timeline" / "timeline.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    board = TaskBoard.fold(p)
    assert board.entries_read == 0
    assert board.entries_skipped == 0


@pytest.mark.xfail(reason="Phase 0 后续 commit 完善 _apply_entry 重建对象")
def test_fold_basic_lifecycle(tmp_path: Path):
    p = tmp_path / "timeline" / "timeline.jsonl"
    _write_timeline(
        p,
        [
            {"entry_id": "01E1", "ts": "2026-05-12T00:00:00+08:00",
             "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
            {"entry_id": "01E2", "ts": "2026-05-12T00:00:01+08:00",
             "data_type": "msg_received", "by": "Ingestor",
             "thread_id": "T1", "msg_id": "M1"},
            {"entry_id": "01E3", "ts": "2026-05-12T00:00:02+08:00",
             "data_type": "task_appended", "by": "DA",
             "thread_id": "T1", "msg_id": "M1", "task_id": "TK1"},
            {"entry_id": "01E4", "ts": "2026-05-12T00:00:03+08:00",
             "data_type": "task_started", "by": "EA",
             "thread_id": "T1", "task_id": "TK1"},
            {"entry_id": "01E5", "ts": "2026-05-12T00:00:04+08:00",
             "data_type": "task_finished", "by": "EA",
             "thread_id": "T1", "task_id": "TK1"},
        ],
    )
    board = TaskBoard.fold(p)
    assert board.entries_read == 5


def test_fold_two_pass_marker_skip(tmp_path: Path):
    """T5.1 — fold 两遍, archived thread 的全部 entries 被跳过。"""
    p = tmp_path / "timeline" / "timeline.jsonl"
    _write_timeline(
        p,
        [
            {"entry_id": "01E1", "ts": "2026-05-12T00:00:00+08:00",
             "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
            {"entry_id": "01E2", "ts": "2026-05-12T00:00:01+08:00",
             "data_type": "msg_received", "by": "Ingestor",
             "thread_id": "T1", "msg_id": "M1"},
            {"entry_id": "01E3", "ts": "2026-05-12T00:00:02+08:00",
             "data_type": "task_appended", "by": "DA", "thread_id": "T1"},
            {"entry_id": "01E4", "ts": "2026-05-12T00:00:03+08:00",
             "data_type": "task_started", "by": "EA", "thread_id": "T1"},
            {"entry_id": "01E5", "ts": "2026-05-12T00:00:04+08:00",
             "data_type": "task_finished", "by": "EA", "thread_id": "T1"},
            {"entry_id": "01E6", "ts": "2026-05-12T00:00:05+08:00",
             "data_type": "thread_archived", "by": "vacuum", "thread_id": "T1",
             "data": {"archived_at": "2026-05-12T00:00:05+08:00",
                      "archived_to": "archive/T1.jsonl"}},
        ],
    )
    board = TaskBoard.fold(p)
    assert board.entries_read == 6
    assert board.entries_skipped == 6, (
        f"all T1 entries (含 marker) 应被跳过, got skipped={board.entries_skipped}"
    )


@pytest.mark.xfail(reason="Phase 0 boot 序列含此 entry 写入, 单元测试 Phase 0 后续 commit 补")
def test_startup_fold_completed_phase0_4_fields(tmp_path: Path):
    """Ce specify: Phase 0 startup_fold_completed entry 严格 4 字段."""
    p = tmp_path / "timeline" / "timeline.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    # boot 序列写入这条 entry 留 Phase 0 后续 commit (boot 函数尚未实现)
    timeline = Timeline(p)
    entries = list(timeline.iter_entries())
    last = entries[-1]
    assert last["data_type"] == "startup_fold_completed"
    assert set(last["data"].keys()) == {
        "fold_duration_ms",
        "entries_read",
        "entries_skipped",
        "timeline_bytes",
    }
