"""Two-pass fold of timeline.jsonl → in-memory TaskBoard projection.

Spec ref: 20260512-msg-task-board-redesign §Phase 0 / T5.1.

Algorithm:
  1. First pass: scan all entries collect ``archived_thread_ids`` set from
     ``data_type == 'thread_archived'`` markers.
  2. Second pass: read entries, skip any whose ``thread_id`` is in the
     archived set, replay the rest via ``board._apply_entry``.

Lives in its own module (Phase finish — was inline in board.py prior) so the
algorithm is independently testable and the dependency direction is
``board → fold``, not the other way around.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from frago.server.services.taskboard.timeline import Timeline

if TYPE_CHECKING:
    from frago.server.services.taskboard.board import TaskBoard


def fold_into_board(board: TaskBoard, timeline_path: Path) -> tuple[int, int]:
    """Populate ``board`` by replaying entries from ``timeline_path``.

    Returns ``(entries_read, entries_skipped)``. ``board`` mutation is in-place.
    Caller is responsible for storing the counts (typically on the board).
    """
    timeline = Timeline(timeline_path)

    # First pass: collect archived thread ids
    archived_thread_ids: set[str] = set()
    for entry in timeline.iter_entries():
        if entry.get("data_type") == "thread_archived":
            tid = entry.get("thread_id")
            if tid:
                archived_thread_ids.add(tid)

    # Second pass: replay non-archived entries
    entries_read = 0
    entries_skipped = 0
    for entry in timeline.iter_entries():
        entries_read += 1
        tid = entry.get("thread_id")
        if tid in archived_thread_ids:
            entries_skipped += 1
            continue
        board._apply_entry(entry)

    return entries_read, entries_skipped


def fold(timeline_path: Path) -> TaskBoard:
    """Convenience wrapper: build a fresh board and fold ``timeline_path`` into it.

    Equivalent to ``TaskBoard.fold(timeline_path)`` — kept as a top-level
    function so the algorithm can be invoked without holding the TaskBoard
    class import path.
    """
    from frago.server.services.taskboard.board import TaskBoard

    board = TaskBoard(Timeline(timeline_path))
    entries_read, entries_skipped = fold_into_board(board, timeline_path)
    board.entries_read = entries_read
    board.entries_skipped = entries_skipped
    return board
