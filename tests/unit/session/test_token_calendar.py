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


class TestMultiEngineAggregation:
    """五家内核（Claude Code、CoreAgent、Antigravity agy、Codex、OpenCode）统一口径聚合。"""

    def test_agy_transcript_counted_with_step_dedup(self, tmp_path):
        agy_root = tmp_path / "agy_brain"
        transcript = agy_root / "conv-1" / ".system_generated" / "logs" / "transcript.jsonl"
        _write_jsonl(
            transcript,
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 3,
                    "created_at": TS_DAY1,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_tokens": 900,
                },
                # 同一 step_index 重复行只计一次
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 3,
                    "created_at": TS_DAY1,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_tokens": 900,
                },
                # 无用量的工具调用行跳过
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 4,
                    "created_at": TS_DAY1,
                    "tool_calls": [{"name": "search_web", "args": {}}],
                },
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 6,
                    "created_at": TS_DAY2,
                    "input_tokens": 200,
                    "output_tokens": 30,
                    "cache_read_tokens": 0,
                },
            ],
        )
        daily = tcal.compute_calendar(
            agy_brain_root=agy_root,
            cache_path=tmp_path / "cache.json",
        )
        d1, d2 = _local_day(TS_DAY1), _local_day(TS_DAY2)
        assert daily[d1] == {
            "input": 100,
            "output": 50,
            "cache_creation": 0,
            "cache_read": 900,
            "total": 1050,
        }
        assert daily[d2] == {
            "input": 200,
            "output": 30,
            "cache_creation": 0,
            "cache_read": 0,
            "total": 230,
        }

    def test_coreagent_sessions_counted_with_dedup(self, tmp_path):
        ca_root = tmp_path / "coreagent"
        _write_jsonl(
            ca_root / "-private-tmp" / "core_abc123.jsonl",
            [
                _assistant(TS_DAY1, msg_id="ca_m1", tokens=25),
                _assistant(TS_DAY1, msg_id="ca_m1", tokens=25),
            ],
        )
        daily = tcal.compute_calendar(
            coreagent_root=ca_root,
            cache_path=tmp_path / "cache.json",
        )
        d1 = _local_day(TS_DAY1)
        assert daily[d1] == {
            "input": 25,
            "output": 25,
            "cache_creation": 25,
            "cache_read": 25,
            "total": 100,
        }

    def test_codex_rollout_counted_and_deduped_by_total_tokens(self, tmp_path):
        codex_root = tmp_path / "codex"
        rollout = codex_root / "2026" / "07" / "01" / "rollout-2026-07-01-uuid1.jsonl"
        _write_jsonl(
            rollout,
            [
                {
                    "timestamp": TS_DAY1,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 1000,
                                "cached_input_tokens": 600,
                                "cache_write_input_tokens": 300,
                                "output_tokens": 80,
                                "reasoning_output_tokens": 20,
                                "total_tokens": 1080,
                            },
                            "total_token_usage": {"total_tokens": 1080},
                        },
                    },
                },
                # 同一轮重复上报（total_tokens 未推进）跳过
                {
                    "timestamp": TS_DAY1,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 1000,
                                "cached_input_tokens": 600,
                                "cache_write_input_tokens": 300,
                                "output_tokens": 80,
                                "reasoning_output_tokens": 20,
                                "total_tokens": 1080,
                            },
                            "total_token_usage": {"total_tokens": 1080},
                        },
                    },
                },
            ],
        )
        daily = tcal.compute_calendar(
            codex_root=codex_root,
            cache_path=tmp_path / "cache.json",
        )
        d1 = _local_day(TS_DAY1)
        # input = 1000 - 600 - 300 = 100; 四项之和 100 + 80 + 300 + 600 = 1080 == total_tokens
        assert daily[d1] == {
            "input": 100,
            "output": 80,
            "cache_creation": 300,
            "cache_read": 600,
            "total": 1080,
        }

    def test_opencode_sqlite_step_finish_counted(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "opencode.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE part (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
        ts_ms = int(datetime.fromisoformat(TS_DAY1.replace("Z", "+00:00")).timestamp() * 1000)
        conn.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            (
                "p1",
                "ses_1",
                ts_ms,
                json.dumps(
                    {
                        "type": "step-finish",
                        "tokens": {
                            "input": 500,
                            "output": 40,
                            "reasoning": 60,
                            "cache": {"write": 100, "read": 300},
                        },
                    }
                ),
            ),
        )
        conn.commit()
        conn.close()

        daily = tcal.compute_calendar(
            opencode_db_path=db_path,
            cache_path=tmp_path / "cache.json",
        )
        d1 = _local_day(TS_DAY1)
        assert daily[d1] == {
            "input": 500,
            "output": 100,
            "cache_creation": 100,
            "cache_read": 300,
            "total": 1000,
        }

    def test_all_five_engines_summed_into_same_day(self, tmp_path):
        import sqlite3

        claude_root = tmp_path / "claude"
        ca_root = tmp_path / "coreagent"
        agy_root = tmp_path / "agy"
        codex_root = tmp_path / "codex"
        db_path = tmp_path / "opencode.db"

        _write_jsonl(claude_root / "p" / "s1.jsonl", [_assistant(TS_DAY1, msg_id="m1", tokens=10)])
        _write_jsonl(ca_root / "p" / "core_1.jsonl", [_assistant(TS_DAY1, msg_id="m2", tokens=20)])
        _write_jsonl(
            agy_root / "c1" / ".system_generated" / "logs" / "transcript.jsonl",
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "step_index": 1,
                    "created_at": TS_DAY1,
                    "input_tokens": 30,
                    "output_tokens": 30,
                    "cache_read_tokens": 30,
                }
            ],
        )
        _write_jsonl(
            codex_root / "rollout-1.jsonl",
            [
                {
                    "timestamp": TS_DAY1,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 120,
                                "cached_input_tokens": 40,
                                "cache_write_input_tokens": 40,
                                "output_tokens": 40,
                                "total_tokens": 160,
                            },
                            "total_token_usage": {"total_tokens": 160},
                        },
                    },
                }
            ],
        )
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE part (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
        ts_ms = int(datetime.fromisoformat(TS_DAY1.replace("Z", "+00:00")).timestamp() * 1000)
        conn.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?)",
            (
                "p1",
                "ses_1",
                ts_ms,
                json.dumps(
                    {
                        "type": "step-finish",
                        "tokens": {
                            "input": 50,
                            "output": 30,
                            "reasoning": 20,
                            "cache": {"write": 50, "read": 50},
                        },
                    }
                ),
            ),
        )
        conn.commit()
        conn.close()

        daily = tcal.compute_calendar(
            projects_root=claude_root,
            coreagent_root=ca_root,
            agy_brain_root=agy_root,
            codex_root=codex_root,
            opencode_db_path=db_path,
            cache_path=tmp_path / "cache.json",
        )
        d1 = _local_day(TS_DAY1)
        # input: 10 + 20 + 30 + 40 + 50 = 150
        # output: 10 + 20 + 30 + 40 + 50 = 150
        # cache_creation: 10 + 20 + 0 + 40 + 50 = 120
        # cache_read: 10 + 20 + 30 + 40 + 50 = 150
        # total: 570
        assert daily[d1] == {
            "input": 150,
            "output": 150,
            "cache_creation": 120,
            "cache_read": 150,
            "total": 570,
        }

