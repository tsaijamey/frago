"""跨 claude / opencode 的会话检索。

分三块钉：关键词那一层（洗词、解析模型输出、退路），两个库各自的搜索，
以及合并排序的口径——命中的**不同关键词数**优先于命中密度，
因为 JSONL 一行是一整条记录，同一个词在一行里出现一百次不代表更相关。
"""

import json
import shutil
import sqlite3

import pytest

from frago.session import search as search_mod
from frago.session.search import (
    KeywordPlan,
    SessionHit,
    _clean_terms,
    _parse_expansion,
    literal_terms,
    search_claude,
    search_opencode,
    search_sessions,
)

needs_rg = pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep 不在 PATH 上")


# ── 会话库脚手架 ────────────────────────────────────────────────────
def write_claude_session(root, project, sid, messages):
    """造一个 claude 会话文件：一条记录一行，形状与真实转录一致。"""
    proj = root / project
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    lines = []
    for role, text in messages:
        lines.append(
            json.dumps(
                {
                    "type": role,
                    "cwd": f"/work/{project}",
                    "slug": f"slug-{sid}",
                    "timestamp": "2026-07-28T10:00:00Z",
                    "message": {"content": text},
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def opencode_db(tmp_path, monkeypatch):
    """造一个最小的 opencode 会话库，并把 db_path() 指过去。"""
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY, title TEXT, directory TEXT,
            time_created INTEGER, time_updated INTEGER
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY, session_id TEXT, data TEXT,
            time_created INTEGER
        );
        CREATE TABLE part (
            id TEXT PRIMARY KEY, session_id TEXT, message_id TEXT, data TEXT,
            time_created INTEGER, time_updated INTEGER
        );
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    return path


def add_opencode_session(db, sid, title, directory, updated_ms, texts):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?)", (sid, title, directory, updated_ms, updated_ms)
    )
    for i, text in enumerate(texts):
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?,?)",
            (
                f"{sid}-p{i}",
                sid,
                f"{sid}-m{i}",
                json.dumps({"type": "text", "text": text}, ensure_ascii=False),
                updated_ms,
                updated_ms,
            ),
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


# ── claude 侧 ───────────────────────────────────────────────────────
@needs_rg
class TestSearchClaude:
    def test_finds_the_session_containing_the_term(self, tmp_path):
        root = tmp_path / "projects"
        write_claude_session(root, "proj-a", "sid-a", [("user", "调通了 opencode 的会话库")])
        write_claude_session(root, "proj-b", "sid-b", [("user", "完全无关的内容")])
        hits, scanned, warnings = search_claude(["opencode"], projects_root=root)
        assert scanned == 2
        assert [h.session_id for h in hits] == ["sid-a"]
        assert warnings == []

    def test_matching_is_case_insensitive(self, tmp_path):
        root = tmp_path / "projects"
        write_claude_session(root, "p", "sid", [("user", "OpenCode rocks")])
        hits, _, _ = search_claude(["opencode"], projects_root=root)
        assert len(hits) == 1

    def test_terms_are_literal_not_regex(self, tmp_path):
        """关键词里的 . ( + 是字面量，NEVER 当正则解释。"""
        root = tmp_path / "projects"
        write_claude_session(root, "p", "hit", [("user", "see builtin-rules.json here")])
        write_claude_session(root, "p", "miss", [("user", "builtin-rulesXjson")])
        hits, _, _ = search_claude(["builtin-rules.json"], projects_root=root)
        assert [h.session_id for h in hits] == ["hit"]

    def test_more_distinct_terms_outranks_more_repeats(self, tmp_path):
        """一行里刷一百遍同一个词，不如同时命中两个不同的词。"""
        root = tmp_path / "projects"
        write_claude_session(root, "p", "repeat", [("user", "sqlite " * 100)])
        write_claude_session(root, "p", "broad", [("user", "sqlite"), ("user", "opencode")])
        hits, _, _ = search_claude(["sqlite", "opencode"], projects_root=root)
        assert hits[0].session_id == "broad"

    def test_reports_cwd_and_resume_command(self, tmp_path):
        root = tmp_path / "projects"
        write_claude_session(root, "proj-a", "sid-a", [("user", "opencode")])
        hit = search_claude(["opencode"], projects_root=root)[0][0]
        assert hit.cwd == "/work/proj-a"
        assert hit.resume_command == "claude --resume sid-a"
        assert hit.source == "claude"

    def test_snippet_is_readable_text_not_raw_json(self, tmp_path):
        root = tmp_path / "projects"
        write_claude_session(root, "p", "sid", [("user", "调通了 opencode 的会话库")])
        hit = search_claude(["opencode"], projects_root=root)[0][0]
        assert hit.snippets
        assert "调通了 opencode 的会话库" in hit.snippets[0].text
        assert '"type":' not in hit.snippets[0].text

    def test_days_filter_excludes_old_files(self, tmp_path):
        import os
        import time

        root = tmp_path / "projects"
        old = write_claude_session(root, "p", "old", [("user", "opencode")])
        os.utime(old, (time.time() - 86400 * 40, time.time() - 86400 * 40))
        write_claude_session(root, "p", "new", [("user", "opencode")])
        hits, scanned, _ = search_claude(
            ["opencode"], since_ts=time.time() - 86400 * 7, projects_root=root
        )
        assert scanned == 1
        assert [h.session_id for h in hits] == ["new"]

    def test_missing_root_warns_instead_of_crashing(self, tmp_path):
        hits, scanned, warnings = search_claude(["x"], projects_root=tmp_path / "nope")
        assert hits == [] and scanned == 0 and warnings

    def test_top_caps_the_result_count(self, tmp_path):
        root = tmp_path / "projects"
        for i in range(5):
            write_claude_session(root, "p", f"sid{i}", [("user", "opencode")])
        hits, _, _ = search_claude(["opencode"], top=2, projects_root=root)
        assert len(hits) == 2


# ── opencode 侧 ─────────────────────────────────────────────────────
class TestSearchOpencode:
    def test_finds_session_by_part_text(self, opencode_db):
        add_opencode_session(
            opencode_db, "ses_a", "调 ETF 回测", "/work/etf", 1780000000000, ["跑一遍 backtest"]
        )
        add_opencode_session(opencode_db, "ses_b", "别的", "/work/x", 1780000000000, ["无关"])
        hits, available, warnings = search_opencode(["backtest"])
        assert available and warnings == []
        assert [h.session_id for h in hits] == ["ses_a"]

    def test_reports_title_directory_and_resume(self, opencode_db):
        add_opencode_session(
            opencode_db, "ses_a", "调 ETF 回测", "/work/etf", 1780000000000, ["backtest"]
        )
        hit = search_opencode(["backtest"])[0][0]
        assert hit.title == "调 ETF 回测"
        assert hit.cwd == "/work/etf"
        assert hit.resume_command == "opencode -s ses_a"
        assert hit.source == "opencode"

    def test_like_wildcards_in_the_term_are_escaped(self, opencode_db):
        """关键词里的 % _ 是字面量，NEVER 当 LIKE 通配符。"""
        add_opencode_session(opencode_db, "lit", "t", "/w", 1780000000000, ["100%_done"])
        add_opencode_session(opencode_db, "other", "t", "/w", 1780000000000, ["100XYdone"])
        hits, _, _ = search_opencode(["100%_done"])
        assert [h.session_id for h in hits] == ["lit"]

    def test_snippet_comes_from_part_text(self, opencode_db):
        add_opencode_session(
            opencode_db, "ses_a", "t", "/w", 1780000000000, ["先跑一遍 backtest 再看结果"]
        )
        hit = search_opencode(["backtest"])[0][0]
        assert "backtest" in hit.snippets[0].text

    def test_since_filter_drops_old_sessions(self, opencode_db):
        add_opencode_session(opencode_db, "old", "t", "/w", 1_600_000_000_000, ["backtest"])
        add_opencode_session(opencode_db, "new", "t", "/w", 1_780_000_000_000, ["backtest"])
        hits, _, _ = search_opencode(["backtest"], since_ts=1_700_000_000)
        assert [h.session_id for h in hits] == ["new"]

    def test_unreadable_db_reports_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "gone.db"))
        hits, available, warnings = search_opencode(["x"])
        assert hits == [] and available is False and warnings


# ── 编排 ────────────────────────────────────────────────────────────
class TestSearchSessions:
    def test_explicit_terms_skip_the_model(self, tmp_path, opencode_db, monkeypatch):
        class Boom:
            def run(self, *a, **kw):
                raise AssertionError("显式给了关键词就 NEVER 该起模型")

        monkeypatch.setattr("frago.agent_driver.SessionLauncher", Boom)
        result = search_sessions(
            "whatever", terms=["opencode"], projects_root=tmp_path / "projects"
        )
        assert result.plan.source == "explicit"
        assert result.plan.terms == ["opencode"]

    def test_no_expand_uses_literal_tokenization(self, tmp_path, opencode_db):
        result = search_sessions(
            "opencode 会话库", expand=False, projects_root=tmp_path / "projects"
        )
        assert result.plan.source == "literal"
        assert result.plan.terms == ["opencode", "会话库"]

    def test_unusable_query_returns_empty_with_a_warning(self, tmp_path, opencode_db):
        result = search_sessions("a b c", expand=False, projects_root=tmp_path / "projects")
        assert result.hits == []
        assert result.warnings

    @needs_rg
    def test_merges_and_ranks_both_sources(self, tmp_path, opencode_db):
        root = tmp_path / "projects"
        write_claude_session(root, "p", "claude-one", [("user", "sqlite")])
        add_opencode_session(
            opencode_db, "ses_a", "t", "/w", 1_780_000_000_000, ["sqlite", "opencode 会话库"]
        )
        result = search_sessions(
            "q", terms=["sqlite", "opencode"], projects_root=root
        )
        sources = {h.source for h in result.hits}
        assert sources == {"claude", "opencode"}
        # opencode 那场命中两个词，claude 那场只命中一个
        assert result.hits[0].source == "opencode"

    @needs_rg
    def test_top_applies_after_the_merge(self, tmp_path, opencode_db):
        root = tmp_path / "projects"
        for i in range(4):
            write_claude_session(root, "p", f"c{i}", [("user", "sqlite")])
        add_opencode_session(opencode_db, "ses_a", "t", "/w", 1_780_000_000_000, ["sqlite"])
        result = search_sessions("q", terms=["sqlite"], top=3, projects_root=root)
        assert len(result.hits) == 3


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
