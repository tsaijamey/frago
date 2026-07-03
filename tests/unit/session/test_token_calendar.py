"""Unit tests for the token calendar aggregation service.

所有文件 IO 走 tmp_path 注入 projects_root / cache_path，NEVER 碰真实
~/.claude/projects 与 ~/.frago/cache。时间戳选 UTC 正午且日期相隔两天，
保证任何本地时区下本地日期都不同。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from frago.session import token_calendar as tcal


def _local_day(iso_utc: str) -> str:
    return (
        datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        .astimezone()
        .strftime("%Y-%m-%d")
    )


def _assistant(ts: str, msg_id: str | None = None, tokens: int = 100, **extra) -> dict:
    rec = {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "usage": {
                "input_tokens": tokens,
                "output_tokens": tokens,
                "cache_creation_input_tokens": tokens,
                "cache_read_input_tokens": tokens,
            }
        },
        **extra,
    }
    if msg_id:
        rec["message"]["id"] = msg_id
    return rec


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


TS_DAY1 = "2026-07-01T12:00:00.000Z"
TS_DAY2 = "2026-07-03T12:00:00.000Z"


class TestCrossDayAttribution:
    def test_records_attributed_to_their_own_local_date(self, tmp_path):
        _write_jsonl(
            tmp_path / "proj" / "s.jsonl",
            [
                _assistant(TS_DAY1, msg_id="m1", tokens=10),
                _assistant(TS_DAY2, msg_id="m2", tokens=20),
            ],
        )
        daily = tcal.compute_calendar(
            projects_root=tmp_path, cache_path=tmp_path / "cache.json"
        )
        d1, d2 = _local_day(TS_DAY1), _local_day(TS_DAY2)
        assert d1 != d2
        assert daily[d1]["total"] == 40  # 4 buckets × 10
        assert daily[d2]["total"] == 80
        assert daily[d1]["input"] == 10
        assert daily[d2]["cache_read"] == 20


class TestDedup:
    def test_same_message_id_counted_once(self, tmp_path):
        _write_jsonl(
            tmp_path / "proj" / "s.jsonl",
            [
                _assistant(TS_DAY1, msg_id="dup", tokens=10),
                _assistant(TS_DAY1, msg_id="dup", tokens=10),
            ],
        )
        daily = tcal.compute_calendar(
            projects_root=tmp_path, cache_path=tmp_path / "cache.json"
        )
        assert daily[_local_day(TS_DAY1)]["total"] == 40

    def test_request_id_fallback_dedup(self, tmp_path):
        _write_jsonl(
            tmp_path / "proj" / "s.jsonl",
            [
                _assistant(TS_DAY1, tokens=10, requestId="req_1"),
                _assistant(TS_DAY1, tokens=10, requestId="req_1"),
                _assistant(TS_DAY1, tokens=10, requestId="req_2"),
            ],
        )
        daily = tcal.compute_calendar(
            projects_root=tmp_path, cache_path=tmp_path / "cache.json"
        )
        assert daily[_local_day(TS_DAY1)]["total"] == 80


class TestCacheReuse:
    def test_cache_hit_skips_reparse_and_mtime_change_invalidates(self, tmp_path):
        jsonl = tmp_path / "proj" / "s.jsonl"
        cache_path = tmp_path / "cache.json"
        _write_jsonl(jsonl, [_assistant(TS_DAY1, msg_id="m1", tokens=10)])
        day = _local_day(TS_DAY1)

        daily = tcal.compute_calendar(projects_root=tmp_path, cache_path=cache_path)
        assert daily[day]["total"] == 40

        # 篡改缓存数值但保持 (mtime,size) 一致 → 第二次必须直接复用篡改值。
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        entry = cache["files"][str(jsonl)]
        entry["days"][day]["total"] = 999999
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

        daily2 = tcal.compute_calendar(projects_root=tmp_path, cache_path=cache_path)
        assert daily2[day]["total"] == 999999

        # touch 改 mtime → 缓存失效、重解析回真实值。
        st = jsonl.stat()
        os.utime(jsonl, (st.st_atime + 10, st.st_mtime + 10))
        daily3 = tcal.compute_calendar(projects_root=tmp_path, cache_path=cache_path)
        assert daily3[day]["total"] == 40


class TestCacheCleanup:
    def test_deleted_file_entry_removed(self, tmp_path):
        jsonl = tmp_path / "proj" / "gone.jsonl"
        cache_path = tmp_path / "cache.json"
        _write_jsonl(jsonl, [_assistant(TS_DAY1, msg_id="m1")])
        tcal.compute_calendar(projects_root=tmp_path, cache_path=cache_path)
        assert str(jsonl) in json.loads(cache_path.read_text())["files"]

        jsonl.unlink()
        daily = tcal.compute_calendar(projects_root=tmp_path, cache_path=cache_path)
        assert daily == {}
        assert json.loads(cache_path.read_text())["files"] == {}


class TestProgress:
    def test_progress_cb_reaches_total(self, tmp_path):
        for i in range(3):
            _write_jsonl(
                tmp_path / "proj" / f"s{i}.jsonl", [_assistant(TS_DAY1, msg_id=f"m{i}")]
            )
        calls: list[tuple[int, int]] = []
        tcal.compute_calendar(
            projects_root=tmp_path,
            cache_path=tmp_path / "cache.json",
            progress_cb=lambda done, total: calls.append((done, total)),
        )
        assert len(calls) == 3
        assert calls[-1] == (3, 3)
        assert [d for d, _ in calls] == [1, 2, 3]

    def test_cached_files_also_counted_in_progress(self, tmp_path):
        _write_jsonl(tmp_path / "proj" / "s.jsonl", [_assistant(TS_DAY1, msg_id="m")])
        cache_path = tmp_path / "cache.json"
        tcal.compute_calendar(projects_root=tmp_path, cache_path=cache_path)
        calls: list[tuple[int, int]] = []
        tcal.compute_calendar(
            projects_root=tmp_path,
            cache_path=cache_path,
            progress_cb=lambda done, total: calls.append((done, total)),
        )
        assert calls == [(1, 1)]
