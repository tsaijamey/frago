"""会话备份的语义检索。

分四块钉：关键词那一层（洗词、解析模型输出、退路），备份树的搜索，
记录里的时间（``--days`` 的依据，NEVER 用文件 mtime），
以及排序口径——命中的**不同关键词数**优先于命中密度，
因为 JSONL 一行是一整条记录，同一个词在一行里出现一百次不代表更相关。
"""

import json
import shutil
import sqlite3
import time

import pytest

from frago.session import search as search_mod
from frago.session.search import (
    KeywordPlan,
    SessionHit,
    _clean_terms,
    _parse_expansion,
    last_activity_of,
    literal_terms,
    search_backup,
    search_sessions,
)

needs_rg = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep 不在 PATH 上")


# ── 备份树脚手架 ────────────────────────────────────────────────────
def write_raw(root, sid, messages, *, core="claude", cwd=None, stamp="2026-07-28T10:00:00Z"):
    """造一份原文副本：形状与 Claude 的真实转录一致，一条记录一行。"""
    path = root / core / sid / "raw.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": role,
                "cwd": cwd or f"/work/{sid}",
                "slug": f"slug-{sid}",
                "timestamp": stamp,
                "message": {"content": text},
            },
            ensure_ascii=False,
        )
        for role, text in messages
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_opencode_raw(root, sid, texts, *, start_ms=1_780_000_000_000):
    """造一份 opencode 原文副本：一行一个原始片段，时间在 ``time`` 里。"""
    path = root / "opencode" / sid / "raw.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {"type": "text", "text": text, "time": {"start": start_ms, "end": start_ms + 100}},
            ensure_ascii=False,
        )
        for text in texts
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_steps(root, sid, summaries, *, core="claude", stamp="2026-06-23T21:53:49.387000"):
    """造一份早期加工副本：只有 content_summary，时间不带时区。"""
    path = root / core / sid / "steps.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "step_id": i,
                "session_id": sid,
                "type": "user",
                "timestamp": stamp,
                "content_summary": text,
            },
            ensure_ascii=False,
        )
        for i, text in enumerate(summaries, start=1)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def opencode_db(tmp_path, monkeypatch):
    """造一个最小的 opencode 会话库，只为给命中的会话补标题和目录。"""
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY, title TEXT, directory TEXT,
            time_created INTEGER, time_updated INTEGER
        );
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    return path


def add_opencode_meta(db, sid, title, directory, updated_ms=1_780_000_000_000):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?)", (sid, title, directory, updated_ms, updated_ms)
    )
    conn.commit()
    conn.close()


# ── 关键词层 ────────────────────────────────────────────────────────
class TestCleanTerms:
    def test_drops_too_short_ascii(self):
        assert _clean_terms(["ab", "abc"]) == ["abc"]

    def test_keeps_two_char_cjk(self):
        """两个汉字已经有足够信息量，英文两个字母没有。"""
        assert _clean_terms(["回测"]) == ["回测"]

    def test_dedupes_case_insensitively(self):
        assert _clean_terms(["OpenCode", "opencode"]) == ["OpenCode"]

    def test_ignores_non_strings_and_blanks(self):
        assert _clean_terms(["  ", 42, None, "sqlite"]) == ["sqlite"]

    def test_non_list_yields_nothing(self):
        assert _clean_terms("sqlite") == []


class TestParseExpansion:
    def test_extracts_json_out_of_surrounding_prose(self):
        raw = 'blah blah\n```json\n{"terms": ["opencode", "sqlite"], "note": "两语种"}\n```\ndone'
        terms, note = _parse_expansion(raw)
        assert terms == ["opencode", "sqlite"]
        assert note == "两语种"

    def test_missing_note_is_empty_not_fatal(self):
        terms, note = _parse_expansion('{"terms": ["sqlite"]}')
        assert terms == ["sqlite"]
        assert note == ""

    def test_non_json_returns_none(self):
        assert _parse_expansion("I could not do that") is None

    def test_all_terms_filtered_out_returns_none(self):
        assert _parse_expansion('{"terms": ["a", "b"]}') is None


class TestLiteralTerms:
    def test_splits_on_punctuation_and_filters(self):
        assert literal_terms("opencode 会话库 的 db!") == ["opencode", "会话库"]

    def test_query_of_only_stopwordish_shorts_yields_nothing(self):
        assert literal_terms("a b c") == []


class TestExpansionFallback:
    def test_driver_failure_falls_back_to_literal(self, monkeypatch):
        """扩展失败 NEVER 让整条命令失败——差的检索远好过没有检索。"""

        class Boom:
            def run(self, *a, **kw):
                raise RuntimeError("tmux missing")

        monkeypatch.setattr("frago.agent_driver.SessionLauncher", Boom)
        plan = search_mod.expand_query("opencode 会话库")
        assert plan.source == "literal"
        assert plan.terms == ["opencode", "会话库"]

    def test_non_ok_status_falls_back_to_literal(self, monkeypatch):
        class Timeout:
            def run(self, *a, **kw):
                return type("R", (), {"status": "timeout", "text": ""})()

        monkeypatch.setattr("frago.agent_driver.SessionLauncher", Timeout)
        plan = search_mod.expand_query("opencode 会话库")
        assert plan.source == "literal"
        assert "timeout" in plan.note

    def test_good_output_is_used(self, monkeypatch):
        class Good:
            def run(self, *a, **kw):
                return type(
                    "R",
                    (),
                    {"status": "ok", "text": '{"terms": ["sqlite", "会话库"], "note": "n"}'},
                )()

        monkeypatch.setattr("frago.agent_driver.SessionLauncher", Good)
        plan = search_mod.expand_query("q")
        assert plan.source == "agent"
        assert plan.terms == ["sqlite", "会话库"]


# ── 记录里的时间 ────────────────────────────────────────────────────
class TestLastActivity:
    def test_reads_claude_timestamp_from_the_last_record(self, tmp_path):
        path = write_raw(tmp_path, "sid", [("user", "x")], stamp="2026-07-28T10:00:00Z")
        assert last_activity_of(path) == pytest.approx(1785232800.0)

    def test_reads_opencode_time_in_milliseconds(self, tmp_path):
        path = write_opencode_raw(tmp_path, "ses_a", ["x"], start_ms=1_780_000_000_000)
        assert last_activity_of(path) == pytest.approx(1_780_000_000.1)

    def test_skips_trailing_records_that_carry_no_time(self, tmp_path):
        """转录尾部常是 mode / permission-mode 这类无时间的元数据记录。"""
        path = tmp_path / "claude" / "sid" / "raw.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            "\n".join(
                [
                    json.dumps({"type": "user", "timestamp": "2026-07-28T10:00:00Z"}),
                    json.dumps({"type": "mode", "mode": "normal"}),
                    json.dumps({"type": "permission-mode", "permissionMode": "default"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        assert last_activity_of(path) == pytest.approx(1785232800.0)

    def test_file_without_any_time_yields_none_not_mtime(self, tmp_path):
        """空壳会话没有时间就是没有，NEVER 拿文件 mtime 顶替。"""
        path = tmp_path / "claude" / "sid" / "raw.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "mode", "mode": "normal"}) + "\n", encoding="utf-8")
        assert last_activity_of(path) is None

    def test_missing_file_yields_none(self, tmp_path):
        assert last_activity_of(tmp_path / "nope.jsonl") is None

    def test_walks_back_across_block_boundaries(self, tmp_path):
        """尾部无时间的记录多到超过一个读取块时，仍要退回去找到。"""
        path = tmp_path / "claude" / "sid" / "raw.jsonl"
        path.parent.mkdir(parents=True)
        filler = json.dumps({"type": "mode", "pad": "x" * 2000})
        lines = [json.dumps({"type": "user", "timestamp": "2026-07-28T10:00:00Z"})]
        lines += [filler] * 60  # 远超 64KB 一块
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert last_activity_of(path) == pytest.approx(1785232800.0)


# ── 备份树的搜索 ────────────────────────────────────────────────────
@needs_rg
class TestSearchBackup:
    def test_finds_the_session_containing_the_term(self, tmp_path):
        write_raw(tmp_path, "sid-a", [("user", "调通了 opencode 的会话库")])
        write_raw(tmp_path, "sid-b", [("user", "完全无关的内容")])
        hits, scanned, warnings = search_backup(["opencode"], root=tmp_path)
        assert scanned == 2
        assert [h.session_id for h in hits] == ["sid-a"]
        assert warnings == []

    def test_matching_is_case_insensitive(self, tmp_path):
        write_raw(tmp_path, "sid", [("user", "OpenCode rocks")])
        hits, _, _ = search_backup(["opencode"], root=tmp_path)
        assert len(hits) == 1

    def test_terms_are_literal_not_regex(self, tmp_path):
        """关键词里的 . ( + 是字面量，NEVER 当正则解释。"""
        write_raw(tmp_path, "hit", [("user", "see builtin-rules.json here")])
        write_raw(tmp_path, "miss", [("user", "builtin-rulesXjson")])
        hits, _, _ = search_backup(["builtin-rules.json"], root=tmp_path)
        assert [h.session_id for h in hits] == ["hit"]

    def test_more_distinct_terms_outranks_more_repeats(self, tmp_path):
        """一行里刷一百遍同一个词，不如同时命中两个不同的词。"""
        write_raw(tmp_path, "repeat", [("user", "sqlite " * 100)])
        write_raw(tmp_path, "broad", [("user", "sqlite"), ("user", "opencode")])
        hits, _, _ = search_backup(["sqlite", "opencode"], root=tmp_path)
        assert hits[0].session_id == "broad"

    def test_reports_cwd_and_resume_command(self, tmp_path):
        write_raw(tmp_path, "sid-a", [("user", "opencode")], cwd="/work/proj-a")
        hit = search_backup(["opencode"], root=tmp_path)[0][0]
        assert hit.cwd == "/work/proj-a"
        assert hit.resume_command == "claude --resume sid-a"
        assert hit.source == "claude"
        assert hit.degraded is False

    def test_snippet_is_readable_text_not_raw_json(self, tmp_path):
        write_raw(tmp_path, "sid", [("user", "调通了 opencode 的会话库")])
        hit = search_backup(["opencode"], root=tmp_path)[0][0]
        assert hit.snippets
        assert "调通了 opencode 的会话库" in hit.snippets[0].text
        assert '"type":' not in hit.snippets[0].text

    def test_missing_root_warns_instead_of_crashing(self, tmp_path):
        hits, scanned, warnings = search_backup(["x"], root=tmp_path / "nope")
        assert hits == [] and scanned == 0 and warnings

    def test_top_caps_the_result_count(self, tmp_path):
        for i in range(5):
            write_raw(tmp_path, f"sid{i}", [("user", "opencode")])
        hits, _, _ = search_backup(["opencode"], top=2, root=tmp_path)
        assert len(hits) == 2

    def test_files_outside_the_backup_layout_are_ignored(self, tmp_path):
        """备份布局是 <核>/<会话 id>/<文件>，别处的同名文件不算会话。"""
        stray = tmp_path / "raw.jsonl"
        stray.write_text(json.dumps({"type": "user", "message": {"content": "opencode"}}) + "\n")
        write_raw(tmp_path, "sid", [("user", "opencode")])
        hits, _, _ = search_backup(["opencode"], root=tmp_path)
        assert [h.session_id for h in hits] == ["sid"]


@needs_rg
class TestBothBackupGenerations:
    def test_searches_the_early_summary_copy_too(self, tmp_path):
        """老会话的原文已随 Claude 滚删消失，只剩加工副本——照样要搜到。"""
        write_steps(tmp_path, "old", ["调通了 opencode 的桥接"])
        hits, _, warnings = search_backup(["opencode"], root=tmp_path)
        assert [h.session_id for h in hits] == ["old"]
        assert hits[0].degraded is True
        assert any("加工副本" in w for w in warnings)

    def test_raw_wins_when_a_session_has_both(self, tmp_path):
        write_raw(tmp_path, "sid", [("user", "opencode 原文")])
        write_steps(tmp_path, "sid", ["opencode 摘要"])
        hits, _, _ = search_backup(["opencode"], root=tmp_path)
        assert len(hits) == 1
        assert hits[0].degraded is False
        assert hits[0].location.endswith("raw.jsonl")

    def test_hits_across_both_files_merge_into_one_session(self, tmp_path):
        write_raw(tmp_path, "sid", [("user", "sqlite")])
        write_steps(tmp_path, "sid", ["opencode"])
        hits, _, _ = search_backup(["sqlite", "opencode"], root=tmp_path)
        assert len(hits) == 1
        assert hits[0].matched_terms == ["opencode", "sqlite"]

    def test_claude_misc_counts_as_claude(self, tmp_path):
        write_steps(tmp_path, "sid", ["opencode"], core="claude-misc")
        hits, _, _ = search_backup(["opencode"], root=tmp_path)
        assert [h.source for h in hits] == ["claude"]


@needs_rg
class TestOpencodeSide:
    def test_finds_session_by_part_text(self, tmp_path, opencode_db):
        write_opencode_raw(tmp_path, "ses_a", ["跑一遍 backtest"])
        write_opencode_raw(tmp_path, "ses_b", ["无关"])
        hits, _, _ = search_backup(["backtest"], root=tmp_path)
        assert [h.session_id for h in hits] == ["ses_a"]
        assert hits[0].resume_command == "opencode -s ses_a"
        assert hits[0].source == "opencode"

    def test_title_and_directory_come_from_the_session_database(self, tmp_path, opencode_db):
        write_opencode_raw(tmp_path, "ses_a", ["backtest"])
        add_opencode_meta(opencode_db, "ses_a", "调 ETF 回测", "/work/etf")
        hit = search_backup(["backtest"], root=tmp_path)[0][0]
        assert hit.title == "调 ETF 回测"
        assert hit.cwd == "/work/etf"

    def test_missing_database_leaves_metadata_blank_not_broken(self, tmp_path, monkeypatch):
        """会话已从库里滚掉，或用户根本没装 opencode——检索照跑，只是没标题。"""
        monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "gone.db"))
        write_opencode_raw(tmp_path, "ses_a", ["backtest"])
        hit = search_backup(["backtest"], root=tmp_path)[0][0]
        assert hit.session_id == "ses_a"
        assert hit.title is None and hit.cwd is None

    def test_snippet_comes_from_part_text(self, tmp_path, opencode_db):
        write_opencode_raw(tmp_path, "ses_a", ["先跑一遍 backtest 再看结果"])
        hit = search_backup(["backtest"], root=tmp_path)[0][0]
        assert "backtest" in hit.snippets[0].text


@needs_rg
class TestDaysFilter:
    def test_filters_on_record_time_not_file_mtime(self, tmp_path):
        """备份文件的 mtime 是"什么时候备的"，批量回填过的全是同一个时刻。"""
        import os

        now = time.time()
        old = write_raw(tmp_path, "old", [("user", "opencode")], stamp="2020-01-01T00:00:00Z")
        new = write_raw(tmp_path, "new", [("user", "opencode")], stamp="2026-07-28T10:00:00Z")
        # 两个文件的 mtime 反过来设：按 mtime 筛会得出相反的答案。
        os.utime(old, (now, now))
        os.utime(new, (now - 86400 * 400, now - 86400 * 400))

        hits, _, _ = search_backup(
            ["opencode"], since_ts=1_700_000_000, root=tmp_path
        )
        assert [h.session_id for h in hits] == ["new"]

    def test_last_activity_is_reported_from_the_record(self, tmp_path):
        write_raw(tmp_path, "sid", [("user", "opencode")], stamp="2026-07-28T10:00:00Z")
        hit = search_backup(["opencode"], root=tmp_path)[0][0]
        assert hit.last_activity == pytest.approx(1785232800.0)

    def test_undated_sessions_are_excluded_and_counted(self, tmp_path):
        """判不出时间的会话被排除时 MUST 报数，NEVER 悄悄消失。"""
        path = tmp_path / "claude" / "shell" / "raw.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"type": "last-prompt", "lastPrompt": "opencode"}) + "\n", encoding="utf-8"
        )
        hits, _, warnings = search_backup(["opencode"], since_ts=1_700_000_000, root=tmp_path)
        assert hits == []
        assert any("没有任何时间戳" in w for w in warnings)

    def test_undated_sessions_survive_when_no_days_given(self, tmp_path):
        path = tmp_path / "claude" / "shell" / "raw.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"type": "last-prompt", "lastPrompt": "opencode"}) + "\n", encoding="utf-8"
        )
        hits, _, _ = search_backup(["opencode"], root=tmp_path)
        assert [h.session_id for h in hits] == ["shell"]
        assert hits[0].last_activity == 0.0


# ── 编排 ────────────────────────────────────────────────────────────
class TestSearchSessions:
    def test_explicit_terms_skip_the_model(self, tmp_path, monkeypatch):
        class Boom:
            def run(self, *a, **kw):
                raise AssertionError("显式给了关键词就 NEVER 该起模型")

        monkeypatch.setattr("frago.agent_driver.SessionLauncher", Boom)
        result = search_sessions("whatever", terms=["opencode"], root=tmp_path)
        assert result.plan.source == "explicit"
        assert result.plan.terms == ["opencode"]

    def test_no_expand_uses_literal_tokenization(self, tmp_path):
        result = search_sessions("opencode 会话库", expand=False, root=tmp_path)
        assert result.plan.source == "literal"
        assert result.plan.terms == ["opencode", "会话库"]

    def test_unusable_query_returns_empty_with_a_warning(self, tmp_path):
        result = search_sessions("a b c", expand=False, root=tmp_path)
        assert result.hits == []
        assert result.warnings

    @needs_rg
    def test_merges_and_ranks_both_cores(self, tmp_path, opencode_db):
        write_raw(tmp_path, "claude-one", [("user", "sqlite")])
        write_opencode_raw(tmp_path, "ses_a", ["sqlite", "opencode 会话库"])
        result = search_sessions("q", terms=["sqlite", "opencode"], root=tmp_path)
        assert {h.source for h in result.hits} == {"claude", "opencode"}
        # opencode 那场命中两个词，claude 那场只命中一个
        assert result.hits[0].source == "opencode"

    @needs_rg
    def test_top_applies_after_the_merge(self, tmp_path, opencode_db):
        for i in range(4):
            write_raw(tmp_path, f"c{i}", [("user", "sqlite")])
        write_opencode_raw(tmp_path, "ses_a", ["sqlite"])
        result = search_sessions("q", terms=["sqlite"], top=3, root=tmp_path)
        assert len(result.hits) == 3

    @needs_rg
    def test_reports_the_corpus_it_searched(self, tmp_path):
        write_raw(tmp_path, "sid", [("user", "sqlite")])
        result = search_sessions("q", terms=["sqlite"], root=tmp_path)
        assert result.corpus_root == str(tmp_path)
        assert result.scanned_sessions == 1


class TestRanking:
    def make(self, terms, lines, activity):
        return SessionHit(
            source="claude",
            session_id="x",
            title=None,
            cwd=None,
            last_activity=activity,
            matched_terms=terms,
            hit_lines=lines,
            location="/x",
            resume_command="",
        )

    def test_distinct_terms_dominate_density(self):
        broad = self.make(["a", "b"], 2, 0)
        dense = self.make(["a"], 999, 0)
        assert broad.rank > dense.rank

    def test_density_breaks_ties_on_terms(self):
        assert self.make(["a"], 9, 0).rank > self.make(["a"], 1, 0).rank

    def test_recency_breaks_ties_on_density(self):
        assert self.make(["a"], 1, 200.0).rank > self.make(["a"], 1, 100.0).rank


class TestKeywordPlan:
    def test_plan_carries_its_provenance(self):
        plan = KeywordPlan(["a"], "note", "agent")
        assert (plan.terms, plan.note, plan.source) == (["a"], "note", "agent")
