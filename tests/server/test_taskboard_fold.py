"""Phase 0 test_taskboard_fold.py — 4 用例 (Ce specify 00:18:41, Gap 2 新增).

含 T5.1 (case_marker_skip): fold 两遍跳过 archived_thread_ids。
"""

from __future__ import annotations

import json
from pathlib import Path

from frago.server.services.taskboard.board import TaskBoard, boot
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


def test_fold_basic_lifecycle(tmp_path: Path):
    """完整 lifecycle entries fold 后 board 含实际对象 (Ce verify 03/fold_basic 加强)."""
    p = tmp_path / "timeline" / "timeline.jsonl"
    _write_timeline(
        p,
        [
            {"entry_id": "01E1", "ts": "2026-05-12T00:00:00+08:00",
             "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1",
             "data": {"origin": "external", "subkind": "feishu",
                      "root_summary": "测试", "status": "active"}},
            {"entry_id": "01E2", "ts": "2026-05-12T00:00:01+08:00",
             "data_type": "msg_received", "by": "Ingestor",
             "thread_id": "T1", "msg_id": "feishu:M1",
             "data": {"channel": "feishu", "sender_id": "u1",
                      "status": "awaiting_decision", "prompt": "你好"}},
            {"entry_id": "01E3", "ts": "2026-05-12T00:00:02+08:00",
             "data_type": "task_appended", "by": "DA",
             "thread_id": "T1", "msg_id": "feishu:M1", "task_id": "TK1",
             "data": {"prev_status": "awaiting_decision", "status": "dispatched",
                      "type": "run", "prompt": "摘要\n\n正文"}},
            {"entry_id": "01E4", "ts": "2026-05-12T00:00:03+08:00",
             "data_type": "task_started", "by": "EA",
             "thread_id": "T1", "task_id": "TK1",
             "data": {"run_id": "R1", "csid": "csid_abc",
                      "started_at": "2026-05-12T00:00:03+08:00"}},
            {"entry_id": "01E5", "ts": "2026-05-12T00:00:04+08:00",
             "data_type": "task_finished", "by": "EA",
             "thread_id": "T1", "task_id": "TK1",
             "data": {"run_id": "R1", "ended_at": "2026-05-12T00:00:04+08:00",
                      "status": "completed", "result_summary": "done"}},
        ],
    )
    board = TaskBoard.fold(p)
    assert board.entries_read == 5
    assert "T1" in board._threads, "fold 后 thread T1 应在内存"
    thread = board._threads["T1"]
    assert len(thread.msgs) == 1, "thread T1 应含 1 个 msg"
    msg = thread.msgs[0]
    assert msg.msg_id == "feishu:M1"
    assert msg.status == "dispatched", "task_appended 后 msg.status 应为 dispatched"
    assert len(msg.tasks) == 1, "msg 应含 1 个 task"
    task = msg.tasks[0]
    assert task.task_id == "TK1"
    assert task.status == "completed", "task_finished 后 status 应为 completed"
    assert task.session is not None
    assert task.session.run_id == "R1"
    assert task.session.claude_session_id == "csid_abc"
    assert task.result is not None
    assert task.result.summary == "done"


def test_fold_two_pass_marker_skip(tmp_path: Path):
    """T5.1 — fold 两遍, archived thread 的全部 entries 被跳过."""
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
    assert "T1" not in board._threads, "archived thread 不应进内存 board"


def test_startup_fold_completed_phase2_6_fields(tmp_path: Path):
    """Ce specify: Phase 2 startup_fold_completed entry 严格 6 字段 (Yi #92 锁定).

    Phase 0 锁定 4 字段, Phase 2 vacuum 引入后扩展 +2:
    vacuum_duration_ms / archived_threads_count.
    """
    home = tmp_path
    board = boot(home)
    assert board is not None

    timeline = Timeline(home / "timeline" / "timeline.jsonl")
    entries = list(timeline.iter_entries())
    assert len(entries) >= 1, "boot 应至少写一条 startup_fold_completed"
    last = entries[-1]
    assert last["data_type"] == "startup_fold_completed"
    assert set(last["data"].keys()) == {
        "fold_duration_ms",
        "vacuum_duration_ms",
        "entries_read",
        "entries_skipped",
        "timeline_bytes",
        "archived_threads_count",
    }, f"Phase 2 字段集严格 6 字段, got {set(last['data'].keys())}"
    assert isinstance(last["data"]["fold_duration_ms"], int)
    assert isinstance(last["data"]["vacuum_duration_ms"], int)
    assert last["data"]["entries_read"] == 0  # 空 timeline
    assert last["data"]["entries_skipped"] == 0
    assert last["data"]["timeline_bytes"] == 0
    assert last["data"]["archived_threads_count"] == 0  # 空 timeline 没 marker
