"""Phase 2 test_vacuum_fold.py — vacuum (bounded-progress + atomic rename) +
inline fold (duplicate_msg_ingest 压缩) 行为测试.

Yi #92 锁定测试范围:
- T5.3 marker_duplicate (vacuum 去重 + record_thread_archived 二次拒绝)
- T5.4 vacuum atomic rename 一致性 (中途 crash 后旧 timeline 仍可读)
- T5.5 vacuum 仅在 boot 路径 (CLI 触发等价于离线 vacuum)
- T_B2.alt.1 bounded 上限 100 markers/run
- fold_thread_duplicates: 9 dup → 1 summary, 多 msg_id 分组, 保持时序
"""

from __future__ import annotations

import json
from pathlib import Path

from frago.server.services.taskboard import vacuum as vac
from frago.server.services.taskboard.board import boot


def _write_timeline(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _read_timeline(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


# ── vacuum 基础行为 ─────────────────────────────────────────────────────


def test_vacuum_no_timeline_returns_zero(tmp_path: Path):
    """vacuum 调用前 timeline.jsonl 不存在 → no-op, processed=0."""
    report = vac.run_bounded_vacuum(tmp_path)
    assert report.processed == 0
    assert report.archived_thread_ids == ()


def test_vacuum_no_markers_no_op(tmp_path: Path):
    """timeline.jsonl 无 thread_archived marker → vacuum no-op, 文件原样保留."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T00:00:00",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
        {"entry_id": "e2", "ts": "2026-05-12T00:00:01",
         "data_type": "msg_received", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "M1"},
    ]
    _write_timeline(timeline, entries)
    before = timeline.read_text(encoding="utf-8")

    report = vac.run_bounded_vacuum(tmp_path)
    assert report.processed == 0
    assert timeline.read_text(encoding="utf-8") == before


def test_vacuum_basic_single_thread_archive(tmp_path: Path):
    """1 thread + 1 marker → vacuum 把 T1 全部 entry 抽到 archive/T1.jsonl,
    主 timeline 只剩非 T1 的 entry."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T00:00:00",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
        {"entry_id": "e2", "ts": "2026-05-12T00:00:01",
         "data_type": "msg_received", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "M1"},
        {"entry_id": "e3", "ts": "2026-05-12T00:00:02",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T2"},
        {"entry_id": "e4", "ts": "2026-05-12T00:00:03",
         "data_type": "thread_archived", "by": "vacuum", "thread_id": "T1",
         "data": {"archived_at": "2026-05-12T00:00:03",
                  "archived_to": "archive/T1.jsonl", "by": "vacuum"}},
    ]
    _write_timeline(timeline, entries)

    report = vac.run_bounded_vacuum(tmp_path)
    assert report.processed == 1
    assert report.archived_thread_ids == ("T1",)

    # main timeline 只剩 T2
    main_entries = _read_timeline(timeline)
    assert len(main_entries) == 1
    assert main_entries[0]["thread_id"] == "T2"

    # archive/T1.jsonl 含 T1 的全部 (3 条: thread_created/msg_received/thread_archived)
    archive_path = tmp_path / "timeline" / "archive" / "T1.jsonl"
    assert archive_path.exists()
    arch_entries = _read_timeline(archive_path)
    assert len(arch_entries) == 3
    assert {e["entry_id"] for e in arch_entries} == {"e1", "e2", "e4"}


def test_vacuum_t_b2_alt_1_bounded_upper_limit(tmp_path: Path):
    """T_B2.alt.1 — 150 markers → max_markers=100, 处理首 100, 剩 50 留待下次."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = []
    for i in range(150):
        tid = f"T_{i:03d}"
        entries.append({
            "entry_id": f"c{i}", "ts": f"2026-05-12T00:{i:02d}:00",
            "data_type": "thread_created", "by": "Ingestor", "thread_id": tid,
        })
        entries.append({
            "entry_id": f"a{i}", "ts": f"2026-05-12T00:{i:02d}:01",
            "data_type": "thread_archived", "by": "vacuum", "thread_id": tid,
            "data": {"archived_at": f"2026-05-12T00:{i:02d}:01",
                     "archived_to": f"archive/{tid}.jsonl", "by": "vacuum"},
        })
    _write_timeline(timeline, entries)

    report = vac.run_bounded_vacuum(tmp_path, max_markers=100)
    assert report.processed == 100, (
        f"应受 bounded 上限约束处理 100 个, got {report.processed}"
    )
    # 剩 50 个 thread 的 entries 仍在主 timeline
    remaining = _read_timeline(timeline)
    remaining_tids = {e.get("thread_id") for e in remaining}
    # 处理掉的 100 个不在主 timeline, 剩 50 个仍在
    assert len(remaining_tids) == 50

    # 再跑一次 vacuum, 处理剩 50
    report2 = vac.run_bounded_vacuum(tmp_path, max_markers=100)
    assert report2.processed == 50
    remaining2 = _read_timeline(timeline)
    assert len(remaining2) == 0


def test_vacuum_t5_3_marker_duplicate_dedup(tmp_path: Path):
    """T5.3 — 同 thread_id 两次 thread_archived marker → vacuum 只算 1 个 thread."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T00:00:00",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
        {"entry_id": "e2", "ts": "2026-05-12T00:00:01",
         "data_type": "thread_archived", "by": "vacuum", "thread_id": "T1",
         "data": {"archived_at": "2026-05-12T00:00:01",
                  "archived_to": "archive/T1.jsonl", "by": "vacuum"}},
        {"entry_id": "e3", "ts": "2026-05-12T00:00:02",
         "data_type": "thread_archived", "by": "user", "thread_id": "T1",
         "data": {"archived_at": "2026-05-12T00:00:02",
                  "archived_to": "archive/T1.jsonl", "by": "user"}},
    ]
    _write_timeline(timeline, entries)

    report = vac.run_bounded_vacuum(tmp_path)
    assert report.processed == 1, (
        f"同 thread 两次 marker 应只算 1 个 processed, got {report.processed}"
    )
    assert report.archived_thread_ids == ("T1",)


def test_vacuum_t5_4_atomic_rename_consistency(tmp_path: Path):
    """T5.4 — vacuum 成功完成后 atomic rename, 旧 .new 临时文件不残留."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T00:00:00",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
        {"entry_id": "e2", "ts": "2026-05-12T00:00:01",
         "data_type": "thread_archived", "by": "vacuum", "thread_id": "T1",
         "data": {"archived_at": "x", "archived_to": "archive/T1.jsonl",
                  "by": "vacuum"}},
    ]
    _write_timeline(timeline, entries)

    vac.run_bounded_vacuum(tmp_path)
    # .new 临时文件不应残留
    new_path = timeline.with_suffix(".new")
    assert not new_path.exists(), "原子 rename 后 .new 不应存在"
    # 主 timeline 仍可读 (即使空), archive 文件存在
    assert timeline.exists()
    assert (tmp_path / "timeline" / "archive" / "T1.jsonl").exists()


def test_vacuum_t5_5_runtime_outside_boot_via_cli():
    """T5.5 — vacuum 通过 CLI 触发等价于离线 vacuum 调用, 不暴露给 PA path.

    实施层面: run_bounded_vacuum 只接受 home arg, 不依赖 running board state,
    所以 CLI 调用 = 离线调用. Yi #92 物理隔离: PA path 不 import 或调用 vacuum.
    本测试通过 grep 静态分析 import + call 痕迹.
    """
    import re

    from frago.server.services.taskboard import vacuum as vac_mod

    # PA path 模块路径
    pa_path_files = [
        "frago/server/services/primary_agent_service.py",
        "frago/server/services/pa_context_builder.py",
        "frago/server/services/pa_prompts.py",
        "frago/server/services/pa_validators.py",
    ]
    # 只拦真实 import + 调用; 不拦注释里的 "vacuum" 字面词.
    forbidden_patterns = [
        r"from\s+frago\.server\.services\.taskboard\s+import\s+[^#\n]*\bvacuum\b",
        r"from\s+frago\.server\.services\.taskboard\.vacuum\s+import",
        r"import\s+frago\.server\.services\.taskboard\.vacuum",
        r"run_bounded_vacuum\s*\(",
        r"fold_thread_duplicates\s*\(",
    ]
    repo_root = Path(vac_mod.__file__).resolve().parents[5]
    for rel in pa_path_files:
        p = repo_root / "src" / rel
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            match = re.search(pat, src)
            assert match is None, (
                f"PA path 文件 {rel} 不应引用 vacuum 模块 (Yi #92 物理隔离); "
                f"pattern={pat!r}, match={match.group(0)!r}"
            )


# ── boot 集成 vacuum + 6 字段 entry ─────────────────────────────────────


def test_boot_with_marker_runs_vacuum(tmp_path: Path):
    """boot 路径含 archive marker 的 timeline → 自动 vacuum + fold + 6 字段 entry."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T00:00:00",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T1"},
        {"entry_id": "e2", "ts": "2026-05-12T00:00:01",
         "data_type": "thread_archived", "by": "vacuum", "thread_id": "T1",
         "data": {"archived_at": "x", "archived_to": "archive/T1.jsonl",
                  "by": "vacuum"}},
        {"entry_id": "e3", "ts": "2026-05-12T00:00:02",
         "data_type": "thread_created", "by": "Ingestor", "thread_id": "T2"},
    ]
    _write_timeline(timeline, entries)

    board = boot(tmp_path)
    # T1 应被 vacuum 抽走, board 内存只剩 T2 (T2 是 thread_created 的, 已 fold)
    assert "T1" not in board._threads
    assert "T2" in board._threads

    # 主 timeline 现在含 T2 entries + startup_fold_completed entry
    all_entries = _read_timeline(timeline)
    last = all_entries[-1]
    assert last["data_type"] == "startup_fold_completed"
    assert set(last["data"].keys()) == {
        "fold_duration_ms", "vacuum_duration_ms",
        "entries_read", "entries_skipped",
        "timeline_bytes", "archived_threads_count",
    }
    assert last["data"]["archived_threads_count"] == 1, (
        f"应记录 1 个 archived thread, got {last['data']['archived_threads_count']}"
    )

    # archive/T1.jsonl 存在
    assert (tmp_path / "timeline" / "archive" / "T1.jsonl").exists()


# ── fold (inline 冗余压缩) ──────────────────────────────────────────────


def test_fold_no_duplicates_noop(tmp_path: Path):
    """fold_thread_duplicates 对不含 duplicate_msg_ingest 的 thread → no-op."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T00:00:00",
         "data_type": "msg_received", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "M1"},
    ]
    _write_timeline(timeline, entries)

    report = vac.fold_thread_duplicates(tmp_path, "T1")
    assert report.folded_count == 0
    assert report.summary_entries_written == 0


def test_fold_basic_9_dup_to_1_summary(tmp_path: Path):
    """9 条 duplicate_msg_ingest (同 msg_id) → 1 条 summary entry, 8 行被压缩."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "e0", "ts": "2026-05-12T00:00:00",
         "data_type": "msg_received", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "feishu:M1",
         "data": {"channel": "feishu"}},
    ]
    for i in range(1, 10):  # 9 条 dup
        entries.append({
            "entry_id": f"d{i}",
            "ts": f"2026-05-12T00:0{i}:00",
            "data_type": "duplicate_msg_ingest",
            "by": "Ingestor",
            "thread_id": "T1",
            "msg_id": "feishu:M1",
            "data": {"channel": "feishu"},
        })
    _write_timeline(timeline, entries)

    report = vac.fold_thread_duplicates(tmp_path, "T1")
    assert report.summary_entries_written == 1
    assert report.folded_count == 8  # 9 dup, 第一条变 summary, 后 8 条被 drop

    # 主 timeline: 1 msg_received + 1 summary
    remaining = _read_timeline(timeline)
    assert len(remaining) == 2
    types = [e["data_type"] for e in remaining]
    assert "msg_received" in types
    assert "duplicate_msg_ingest_summary" in types

    summary = next(e for e in remaining if e["data_type"] == "duplicate_msg_ingest_summary")
    assert summary["thread_id"] == "T1"
    assert summary["msg_id"] == "feishu:M1"
    assert summary["data"]["count"] == 9
    assert summary["data"]["channel"] == "feishu"
    assert summary["data"]["first_entry_id"] == "d1"
    assert summary["data"]["last_entry_id"] == "d9"


def test_fold_count_1_not_folded(tmp_path: Path):
    """单条 duplicate_msg_ingest (count=1) → 不折叠, 保持原样."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "d1", "ts": "2026-05-12T00:00:00",
         "data_type": "duplicate_msg_ingest", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "M1", "data": {"channel": "feishu"}},
    ]
    _write_timeline(timeline, entries)

    report = vac.fold_thread_duplicates(tmp_path, "T1")
    assert report.summary_entries_written == 0
    assert report.folded_count == 0
    # 文件内容不变
    after = _read_timeline(timeline)
    assert len(after) == 1
    assert after[0]["data_type"] == "duplicate_msg_ingest"


def test_fold_multiple_msg_ids_grouped(tmp_path: Path):
    """同 thread 内多组不同 msg_id 的 duplicate → 每组独立 summary."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = []
    for i in range(3):
        entries.append({
            "entry_id": f"A{i}", "ts": f"2026-05-12T00:0{i}:00",
            "data_type": "duplicate_msg_ingest", "by": "Ingestor",
            "thread_id": "T1", "msg_id": "M_A", "data": {"channel": "feishu"},
        })
    for i in range(4):
        entries.append({
            "entry_id": f"B{i}", "ts": f"2026-05-12T01:0{i}:00",
            "data_type": "duplicate_msg_ingest", "by": "Ingestor",
            "thread_id": "T1", "msg_id": "M_B", "data": {"channel": "feishu"},
        })
    _write_timeline(timeline, entries)

    report = vac.fold_thread_duplicates(tmp_path, "T1")
    assert report.summary_entries_written == 2  # M_A + M_B 各 1
    # 3 dup → fold 1, 4 dup → fold 1, drop = 2 + 3 = 5
    assert report.folded_count == 5

    remaining = _read_timeline(timeline)
    summaries = [e for e in remaining if e["data_type"] == "duplicate_msg_ingest_summary"]
    assert len(summaries) == 2
    counts = sorted([s["data"]["count"] for s in summaries])
    assert counts == [3, 4]


def test_fold_other_threads_unaffected(tmp_path: Path):
    """fold --thread T1 不影响 T2 的 entry."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = []
    for i in range(3):
        entries.append({
            "entry_id": f"T1_{i}", "ts": f"2026-05-12T00:0{i}:00",
            "data_type": "duplicate_msg_ingest", "by": "Ingestor",
            "thread_id": "T1", "msg_id": "M1", "data": {"channel": "feishu"},
        })
    for i in range(3):
        entries.append({
            "entry_id": f"T2_{i}", "ts": f"2026-05-12T01:0{i}:00",
            "data_type": "duplicate_msg_ingest", "by": "Ingestor",
            "thread_id": "T2", "msg_id": "M2", "data": {"channel": "feishu"},
        })
    _write_timeline(timeline, entries)

    vac.fold_thread_duplicates(tmp_path, "T1")
    after = _read_timeline(timeline)
    # T2 的 3 条原样保留
    t2_entries = [e for e in after if e.get("thread_id") == "T2"]
    assert len(t2_entries) == 3
    assert all(e["data_type"] == "duplicate_msg_ingest" for e in t2_entries)


def test_fold_preserves_time_order(tmp_path: Path):
    """fold 后非折叠 entry 保持原时序, summary 在原首条出现位置."""
    timeline = tmp_path / "timeline" / "timeline.jsonl"
    entries = [
        {"entry_id": "X1", "ts": "2026-05-12T00:00:00",
         "data_type": "msg_received", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "MX"},
        {"entry_id": "D1", "ts": "2026-05-12T00:01:00",
         "data_type": "duplicate_msg_ingest", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "MX", "data": {"channel": "c"}},
        {"entry_id": "Y1", "ts": "2026-05-12T00:02:00",
         "data_type": "task_appended", "by": "DA",
         "thread_id": "T1", "msg_id": "MX", "task_id": "TK1"},
        {"entry_id": "D2", "ts": "2026-05-12T00:03:00",
         "data_type": "duplicate_msg_ingest", "by": "Ingestor",
         "thread_id": "T1", "msg_id": "MX", "data": {"channel": "c"}},
    ]
    _write_timeline(timeline, entries)

    vac.fold_thread_duplicates(tmp_path, "T1")
    after = _read_timeline(timeline)
    ids = [e["entry_id"] for e in after]
    # 期望: X1, D1 (变 summary, 保持 D1 entry_id), Y1
    # D2 被 drop
    assert ids == ["X1", "D1", "Y1"]
    summary = [e for e in after if e["data_type"] == "duplicate_msg_ingest_summary"][0]
    assert summary["data"]["count"] == 2
    assert summary["data"]["first_entry_id"] == "D1"
    assert summary["data"]["last_entry_id"] == "D2"
