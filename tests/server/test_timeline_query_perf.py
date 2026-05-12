"""T9.7b: perf assertion for frago task history on a 10000-entry timeline.

spec ref: 20260512-msg-task-board-redesign §AC T9.7b — task history query
against a 10000-entry ~/.frago/timeline/timeline.jsonl finishes in ≤ 5 s.

Fixture generates a real JSONL on disk with mixed data types (task_appended /
task_started / task_finished / task_resumed_caseA + duplicate_msg_ingest noise)
across many task_ids; one target task_id has a full run history (init + 3
resumes) so the test can both measure scan time and verify correctness of the
returned entries.

The test is marked ``@pytest.mark.perf`` so it can be excluded from default
fast suites via ``pytest -m 'not perf'`` if CI ever needs to gate on it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from frago.cli.task_commands import task_history

TARGET_TASK_ID = "T_PERF_TARGET"
TOTAL_ENTRIES = 10_000
TARGET_HISTORY_ROUNDS = 4  # init + 3 resumes
PERF_BUDGET_SECONDS = 5.0


def _make_entry(idx: int, data_type: str, **kwargs) -> dict:
    """Synthesize one timeline entry. Uses the same shape as Timeline writes."""
    base = {
        "entry_id": f"e{idx:06d}",
        "ts": f"2026-05-12T{(idx % 24):02d}:{(idx % 60):02d}:00",
        "data_type": data_type,
        "by": kwargs.pop("by", "perf-fixture"),
    }
    base.update(kwargs)
    return base


def _build_fixture_lines(total: int) -> list[str]:
    """Build a list of JSON-serialized timeline entries.

    Layout:
      - First TARGET_HISTORY_ROUNDS * 2 entries belong to TARGET_TASK_ID
        (task_started + task_finished per round), simulating a multi-run task
      - The rest is noise: task_appended / task_started / task_finished /
        duplicate_msg_ingest for many other task_ids, scattered across threads
    """
    lines: list[str] = []

    # Target task history entries (8 entries: 4 rounds × {started, finished})
    for round_idx in range(TARGET_HISTORY_ROUNDS):
        lines.append(json.dumps(_make_entry(
            len(lines),
            "task_started",
            thread_id=f"T_PERF_THREAD_{round_idx % 4}",
            task_id=TARGET_TASK_ID,
            data={"run_id": f"r{round_idx}", "csid": f"csid_{round_idx}"},
        ), ensure_ascii=False))
        lines.append(json.dumps(_make_entry(
            len(lines),
            "task_finished",
            thread_id=f"T_PERF_THREAD_{round_idx % 4}",
            task_id=TARGET_TASK_ID,
            data={"run_id": f"r{round_idx}", "status": "completed"},
        ), ensure_ascii=False))

    # Pad to TOTAL_ENTRIES with noise across non-target task ids
    noise_data_types = (
        "task_appended", "task_started", "task_finished", "duplicate_msg_ingest",
        "msg_received", "thread_created",
    )
    remaining = total - len(lines)
    for i in range(remaining):
        dt = noise_data_types[i % len(noise_data_types)]
        # ~5 % of noise also touches TARGET_TASK_ID via embedded data.task_id
        # (exercises the "data.task_id" fallback path in task_history)
        if i % 200 == 0:
            entry = _make_entry(
                len(lines), dt,
                thread_id=f"T_PERF_THREAD_{i % 32}",
                task_id=None,
                data={"task_id": TARGET_TASK_ID, "run_id": f"noise_r{i}"},
            )
        else:
            entry = _make_entry(
                len(lines), dt,
                thread_id=f"T_PERF_THREAD_{i % 32}",
                task_id=f"T_NOISE_{i:06d}",
                data={"prompt_head": f"noise prompt {i}"},
            )
        lines.append(json.dumps(entry, ensure_ascii=False))

    return lines


@pytest.mark.perf
def test_t9_7b_task_history_perf_10000_entries(tmp_path: Path, monkeypatch):
    """Real 10000-entry fixture; assert ``frago task history <id>`` ≤ 5s.

    No mock / freeze / monkeypatch on time/clock — only HOME redirection so the
    CLI reads the synthetic timeline. Wall-clock measured around CliRunner invoke.
    """
    home = tmp_path / "home"
    timeline_dir = home / ".frago" / "timeline"
    timeline_dir.mkdir(parents=True)
    timeline_path = timeline_dir / "timeline.jsonl"

    lines = _build_fixture_lines(TOTAL_ENTRIES)
    assert len(lines) == TOTAL_ENTRIES, (
        f"fixture builder gave {len(lines)} entries, expected {TOTAL_ENTRIES}"
    )
    timeline_path.write_text("\n".join(lines), encoding="utf-8")

    # Sanity: fixture file is on disk and parseable
    assert timeline_path.stat().st_size > 0

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    runner = CliRunner()
    start = time.monotonic()
    result = runner.invoke(task_history, [TARGET_TASK_ID])
    elapsed = time.monotonic() - start

    assert result.exit_code == 0, (
        f"task history exited {result.exit_code}: {result.output[:500]}"
    )
    payload = json.loads(result.output)
    assert payload["task_id"] == TARGET_TASK_ID
    # 4 rounds × 2 explicit entries (started/finished) plus the ~5% noise
    # entries that mention TARGET_TASK_ID via data.task_id. We expect ≥ 8.
    assert payload["count"] >= TARGET_HISTORY_ROUNDS * 2, (
        f"expected at least {TARGET_HISTORY_ROUNDS * 2} entries for target, "
        f"got {payload['count']}"
    )

    assert elapsed < PERF_BUDGET_SECONDS, (
        f"task history scan over {TOTAL_ENTRIES} entries took "
        f"{elapsed:.3f}s (budget {PERF_BUDGET_SECONDS}s)"
    )
