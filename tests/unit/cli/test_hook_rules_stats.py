"""hook-rules stats 读取侧：轮转后两代日志都要计入。

引擎在 8 MB 处把 hook-rules-hits.log 挪成 .1 再起新文件。读取侧若只看主文件，
轮转当天所有规则的命中数会凭空掉一截，prune 会据此把仍在活跃的规则判成过期。
这里锁死「两代都读」的行为。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import frago.cli.hook_rules_commands as hr


@pytest.fixture
def hits_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the reader at an isolated pair of log files."""
    live = tmp_path / "hook-rules-hits.log"
    backup = tmp_path / "hook-rules-hits.log.1"
    monkeypatch.setattr(hr, "HITS_LOG_PATH", live)
    monkeypatch.setattr(hr, "HITS_LOG_BACKUP_PATH", backup)
    return live, backup


def _write(path: Path, records: list[tuple[int, str, str, str]]) -> None:
    path.write_text("".join(f"{ts}\t{sid}\t{rid}\t{out}\n" for ts, sid, rid, out in records))


class TestReadHitsAcrossGenerations:
    def test_backup_absent_reads_live_only(self, hits_logs):
        live, _ = hits_logs
        _write(live, [(1_700_000_000, "s1", "r1", "injected")])

        stats = hr._read_hits()

        assert stats["r1"]["count"] == 1
        assert stats["r1"]["injected"] == 1

    def test_both_generations_are_counted(self, hits_logs):
        live, backup = hits_logs
        _write(
            backup,
            [
                (1_700_000_000, "s1", "r1", "injected"),
                (1_700_000_100, "s1", "r1", "deduped"),
                (1_700_000_200, "s1", "r2", "empty"),
            ],
        )
        _write(
            live,
            [
                (1_700_001_000, "s2", "r1", "injected"),
                (1_700_001_100, "s2", "r3", "injected"),
            ],
        )

        stats = hr._read_hits()

        # r1 spans the rotation boundary — its history must survive it.
        assert stats["r1"]["count"] == 3
        assert stats["r1"]["injected"] == 2
        assert stats["r1"]["deduped"] == 1
        # last_ts comes from the newer generation even though it is read second.
        assert stats["r1"]["last_ts"] == 1_700_001_000
        # A rule that only ever appears in the rotated generation still shows up,
        # which is what keeps prune from mistaking it for never-matched.
        assert stats["r2"]["empty"] == 1
        assert stats["r3"]["count"] == 1

    def test_live_absent_reads_backup_only(self, hits_logs):
        """Right after a rotation the live file does not exist yet."""
        _, backup = hits_logs
        _write(backup, [(1_700_000_000, "s1", "r1", "injected")])

        stats = hr._read_hits()

        assert stats["r1"]["count"] == 1

    def test_neither_generation_present(self, hits_logs):
        live, backup = hits_logs
        assert not live.exists() and not backup.exists()
        assert hr._read_hits() == {}


class TestMalformedRecordsStillDropped:
    """轮转不能把既有的畸形记录守卫弄丢。"""

    def test_insane_timestamps_dropped_in_both_generations(self, hits_logs):
        live, backup = hits_logs
        # Two hooks interleaving mid-record used to concatenate timestamps;
        # such a line must be dropped, not counted, in either generation.
        backup.write_text(
            "17000000001700000000\ts1s1\tr1\tinjected\n"
            "1700000000\ts1\tr1\tinjected\n"
        )
        live.write_text(
            "\ts2\tr1\tinjected\n"
            "0\ts2\tr1\tinjected\n"
            f"{hr._TS_SANE_MAX}\ts2\tr1\tinjected\n"
            "1700001000\ts2\tr1\tinjected\n"
        )

        stats = hr._read_hits()

        assert stats["r1"]["count"] == 2
        assert stats["r1"]["last_ts"] == 1_700_001_000

    def test_legacy_three_field_records_read_as_injected(self, hits_logs):
        live, backup = hits_logs
        backup.write_text("1700000000\ts1\tr1\n")
        live.write_text("1700001000\ts2\tr1\n")

        stats = hr._read_hits()

        assert stats["r1"]["count"] == 2
        assert stats["r1"]["injected"] == 2

    def test_trailing_newline_does_not_corrupt_the_outcome(self, hits_logs):
        """逐行读若忘了剥掉换行，outcome 会变成 'injected\\n' 落不进任何桶。"""
        live, _ = hits_logs
        live.write_text("1700000000\ts1\tr1\tdeduped\n")

        stats = hr._read_hits()

        assert stats["r1"]["deduped"] == 1
        assert stats["r1"]["injected"] == 0
