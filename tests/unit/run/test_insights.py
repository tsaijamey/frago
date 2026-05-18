"""Phase 2 tests — domain insight CRUD (run/insights.py + manager extensions)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from frago.run.insights import (
    DomainInsight,
    DomainInsightType,
    INSIGHT_FILENAME,
    count_insights,
    find_insight,
    list_insights,
    query_insights,
    save_insight,
    search_insights_across_domains,
    update_insight,
)
from frago.run.manager import RunManager


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    p = tmp_path / "projects"
    p.mkdir(parents=True)
    return p


@pytest.fixture
def manager(projects_dir: Path) -> RunManager:
    mgr = RunManager(projects_dir)
    mgr.ensure_domain("twitter")
    return mgr


# -------------------------- schema -------------------------- #


class TestSchema:
    def test_to_from_dict_roundtrip(self):
        now = datetime.now()
        ins = DomainInsight(
            id="abc",
            type=DomainInsightType.FACT,
            payload="hi",
            confidence=0.7,
            related_session_ids=["s1"],
            created_at=now,
            updated_at=now,
        )
        rebuilt = DomainInsight.from_dict(ins.to_dict())
        assert rebuilt.id == "abc"
        assert rebuilt.type == DomainInsightType.FACT
        assert rebuilt.related_session_ids == ["s1"]
        assert rebuilt.confidence == 0.7

    def test_invalid_confidence(self):
        with pytest.raises(Exception):
            DomainInsight(
                id="a",
                type=DomainInsightType.FACT,
                payload="x",
                confidence=2.0,
                related_session_ids=[],
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )


# -------------------------- save / list / query -------------------------- #


class TestSaveAndList:
    def test_save_appends_jsonl(self, manager, projects_dir):
        e1 = save_insight(
            projects_dir,
            "twitter",
            type="fact",
            payload="API limit 100/15min",
            confidence=0.9,
        )
        path = projects_dir / "twitter" / INSIGHT_FILENAME
        assert path.exists()
        rows = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 1
        data = json.loads(rows[0])
        assert data["type"] == "fact"
        assert data["payload"] == "API limit 100/15min"
        assert data["id"] == e1.id

    def test_list_returns_newest_first(self, manager, projects_dir):
        a = save_insight(projects_dir, "twitter", type="fact", payload="a")
        b = save_insight(projects_dir, "twitter", type="lesson", payload="b")
        items = list_insights(projects_dir, "twitter")
        assert [i.id for i in items][:2] == [b.id, a.id]

    def test_list_filter_by_type(self, manager, projects_dir):
        save_insight(projects_dir, "twitter", type="fact", payload="a")
        save_insight(projects_dir, "twitter", type="lesson", payload="b")
        items = list_insights(projects_dir, "twitter", type="fact")
        assert len(items) == 1
        assert items[0].type == DomainInsightType.FACT

    def test_query_substring(self, manager, projects_dir):
        save_insight(projects_dir, "twitter", type="fact", payload="rate limit 100")
        save_insight(projects_dir, "twitter", type="fact", payload="login redirect")
        hits = query_insights(projects_dir, "twitter", keyword="limit")
        assert len(hits) == 1
        assert "rate limit" in hits[0].payload.lower()

    def test_invalid_type_rejected(self, manager, projects_dir):
        with pytest.raises(ValueError):
            save_insight(projects_dir, "twitter", type="bogus", payload="x")

    def test_empty_payload_rejected(self, manager, projects_dir):
        with pytest.raises(ValueError):
            save_insight(projects_dir, "twitter", type="fact", payload="   ")


# -------------------------- update -------------------------- #


class TestUpdate:
    def test_update_appends_new_version(self, manager, projects_dir):
        a = save_insight(projects_dir, "twitter", type="fact", payload="v1")
        bumped = update_insight(
            projects_dir, "twitter", a.id, payload="v2", confidence=0.95
        )
        assert bumped.id == a.id
        assert bumped.version == 2
        assert bumped.payload == "v2"
        assert bumped.confidence == 0.95

        # File now has 2 rows; list collapses to latest version.
        path = projects_dir / "twitter" / INSIGHT_FILENAME
        rows = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 2

        items = list_insights(projects_dir, "twitter")
        assert len(items) == 1
        assert items[0].payload == "v2"
        assert items[0].version == 2

    def test_update_unknown_raises(self, manager, projects_dir):
        from frago.run.exceptions import RunNotFoundError

        with pytest.raises(RunNotFoundError):
            update_insight(projects_dir, "twitter", "no-such-id", payload="x")


# -------------------------- find / count -------------------------- #


class TestFindCount:
    def test_find_insight_returns_latest_version(self, manager, projects_dir):
        a = save_insight(projects_dir, "twitter", type="fact", payload="v1")
        update_insight(projects_dir, "twitter", a.id, payload="v2")
        found = find_insight(projects_dir, "twitter", a.id)
        assert found is not None
        assert found.version == 2

    def test_count_insights_after_update(self, manager, projects_dir):
        a = save_insight(projects_dir, "twitter", type="fact", payload="v1")
        update_insight(projects_dir, "twitter", a.id, payload="v2")
        assert count_insights(projects_dir, "twitter") == 1


# -------------------------- search across domains -------------------------- #


class TestSearchAcrossDomains:
    def test_search_finds_payload(self, projects_dir):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        mgr.ensure_domain("feishu")
        save_insight(projects_dir, "twitter", type="fact", payload="rate limit detected")
        save_insight(projects_dir, "feishu", type="state", payload="webhook OK")
        hits = search_insights_across_domains(projects_dir, "rate limit")
        assert len(hits) == 1
        assert hits[0]["domain"] == "twitter"


# -------------------------- manager bump / peek -------------------------- #


class TestManagerExtensions:
    def test_bump_insight_count(self, projects_dir):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        inst = mgr.bump_insight_count("twitter", delta=2)
        assert inst.insight_count == 2
        # Persisted on disk
        reloaded = mgr.find_run("twitter")
        assert reloaded.insight_count == 2

    def test_peek_domain_returns_summary(self, projects_dir):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        save_insight(projects_dir, "twitter", type="fact", payload="abc")
        mgr.bump_insight_count("twitter", delta=1)
        summary = mgr.peek_domain("twitter")
        assert summary["domain"] == "twitter"
        assert summary["insight_count"] == 1
        assert isinstance(summary["top_insights"], list)
        assert summary["top_insights"][0]["payload"] == "abc"

    def test_update_run_patch(self, projects_dir):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        mgr.update_run("twitter", aliases=["twi", "推特"])
        reloaded = mgr.find_run("twitter")
        assert reloaded.aliases == ["twi", "推特"]


# -------------------------- append-only resilience -------------------------- #


class TestJsonlResilience:
    def test_skips_corrupted_lines(self, projects_dir):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        save_insight(projects_dir, "twitter", type="fact", payload="ok")
        path = projects_dir / "twitter" / INSIGHT_FILENAME
        with path.open("a", encoding="utf-8") as f:
            f.write("{not valid json}\n")
        # Should not raise; corrupt line skipped.
        items = list_insights(projects_dir, "twitter")
        assert len(items) == 1
