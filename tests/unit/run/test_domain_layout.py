"""Phase 1 tests — run-as-domain-knowledge-base data model + directory layout.

Covers:
- ``RunStatus`` is now ``active``/``inactive`` (no ``archived``).
- ``RunInstance`` carries domain fields with sensible defaults; from_dict
  migrates the legacy ``"archived"`` literal to ``INACTIVE``.
- ``parse_cross_domain`` / ``is_legacy_run_dir`` / ``normalize_domain_name``.
- ``RunManager.ensure_domain`` writes ``_domain.json`` with no date prefix
  and is idempotent.
- ``RunManager.deactivate_domain`` flips status to ``INACTIVE``.
- ``RunManager.resolve_domain_for_session`` honours ``FRAGO_DOMAIN`` and
  falls back to ``"misc"``.
- ``MonitoredSession`` has new ``domain`` and ``source_jsonl`` fields.
- Domain-aware ``write_metadata`` lands under ``~/.frago/projects/<domain>/``.
- ``write_summary_md`` produces a markdown summary.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from frago.run.manager import DOMAIN_METADATA_FILENAME, RunManager
from frago.run.models import RunInstance, RunStatus
from frago.run.utils import (
    is_legacy_run_dir,
    normalize_domain_name,
    parse_cross_domain,
)


# --------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------- #


class TestRunStatus:
    def test_only_active_and_inactive(self):
        assert RunStatus.ACTIVE.value == "active"
        assert RunStatus.INACTIVE.value == "inactive"
        assert not hasattr(RunStatus, "ARCHIVED")
        assert {s.value for s in RunStatus} == {"active", "inactive"}


class TestRunInstanceFields:
    def _now(self) -> datetime:
        return datetime.now()

    def test_defaults_for_new_fields(self):
        now = self._now()
        inst = RunInstance(
            run_id="twitter",
            theme_description="twitter",
            created_at=now,
            last_accessed=now,
        )
        assert inst.domain is None
        assert inst.aliases == []
        assert inst.is_cross_domain is False
        assert inst.component_domains == []
        assert inst.session_count == 0
        assert inst.insight_count == 0
        assert inst.status == RunStatus.ACTIVE

    def test_to_dict_round_trip(self):
        now = self._now()
        inst = RunInstance(
            run_id="CROSS-twitter-feishu",
            theme_description="cross sync",
            created_at=now,
            last_accessed=now,
            status=RunStatus.ACTIVE,
            domain="CROSS-twitter-feishu",
            aliases=["sync"],
            is_cross_domain=True,
            component_domains=["twitter", "feishu"],
            session_count=3,
            insight_count=12,
        )
        data = inst.to_dict()
        for key in (
            "domain",
            "aliases",
            "is_cross_domain",
            "component_domains",
            "session_count",
            "insight_count",
        ):
            assert key in data
        rebuilt = RunInstance.from_dict(data)
        assert rebuilt.is_cross_domain is True
        assert rebuilt.component_domains == ["twitter", "feishu"]
        assert rebuilt.session_count == 3
        assert rebuilt.insight_count == 12
        assert rebuilt.aliases == ["sync"]
        assert rebuilt.status == RunStatus.ACTIVE

    def test_from_dict_migrates_legacy_archived(self):
        now = self._now()
        data = {
            "run_id": "twitter",
            "theme_description": "twitter",
            "created_at": now.isoformat(),
            "last_accessed": now.isoformat(),
            "status": "archived",
        }
        inst = RunInstance.from_dict(data)
        assert inst.status == RunStatus.INACTIVE


# --------------------------------------------------------------------- #
# utils
# --------------------------------------------------------------------- #


class TestUtils:
    def test_parse_cross_domain_match(self):
        assert parse_cross_domain("CROSS-twitter-feishu") == ["twitter", "feishu"]

    def test_parse_cross_domain_none(self):
        assert parse_cross_domain("twitter") is None
        assert parse_cross_domain("crossover") is None

    def test_parse_cross_domain_case_insensitive(self):
        assert parse_cross_domain("cross-foo-bar") == ["foo", "bar"]

    def test_is_legacy_run_dir(self):
        assert is_legacy_run_dir("20260426-foo") is True
        assert is_legacy_run_dir("20260426-foo-bar") is True
        assert is_legacy_run_dir("twitter") is False
        assert is_legacy_run_dir("CROSS-a-b") is False

    def test_normalize_domain_name_basic(self):
        assert normalize_domain_name("Twitter") == "twitter"
        assert normalize_domain_name("Frago Meta") == "frago-meta"

    def test_normalize_domain_name_keeps_cross_prefix(self):
        out = normalize_domain_name("CROSS-Twitter-FeiShu")
        assert out.startswith("CROSS-")
        assert "twitter-feishu" in out.lower()

    def test_normalize_domain_name_cross_lowercase_input(self):
        out = normalize_domain_name("cross-foo-bar")
        assert out.startswith("CROSS-")


# --------------------------------------------------------------------- #
# RunManager — ensure_domain / deactivate_domain / resolve
# --------------------------------------------------------------------- #


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    p = tmp_path / "projects"
    p.mkdir(parents=True)
    return p


class TestEnsureDomain:
    def test_creates_domain_directory_without_date_prefix(self, projects_dir: Path):
        mgr = RunManager(projects_dir)
        inst = mgr.ensure_domain("twitter")

        domain_dir = projects_dir / "twitter"
        assert domain_dir.is_dir()
        assert (domain_dir / DOMAIN_METADATA_FILENAME).is_file()
        # No legacy YYYYMMDD-twitter directory should exist.
        for child in projects_dir.iterdir():
            assert not child.name.startswith("2026")
        assert inst.run_id == "twitter"
        assert inst.domain == "twitter"
        assert inst.is_cross_domain is False
        assert inst.status == RunStatus.ACTIVE

    def test_idempotent(self, projects_dir: Path):
        mgr = RunManager(projects_dir)
        a = mgr.ensure_domain("twitter")
        b = mgr.ensure_domain("twitter")
        assert a.run_id == b.run_id == "twitter"
        # Only the canonical _domain.json exists.
        meta = projects_dir / "twitter" / DOMAIN_METADATA_FILENAME
        assert meta.exists()

    def test_cross_domain_detection(self, projects_dir: Path):
        mgr = RunManager(projects_dir)
        inst = mgr.ensure_domain("CROSS-twitter-feishu")
        assert inst.is_cross_domain is True
        assert inst.component_domains == ["twitter", "feishu"]
        assert (projects_dir / "CROSS-twitter-feishu" / DOMAIN_METADATA_FILENAME).exists()

    def test_metadata_file_contents(self, projects_dir: Path):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        data = json.loads(
            (projects_dir / "twitter" / DOMAIN_METADATA_FILENAME).read_text(encoding="utf-8")
        )
        assert data["domain"] == "twitter"
        assert data["status"] == "active"
        assert data["session_count"] == 0
        assert data["insight_count"] == 0
        assert data["is_cross_domain"] is False


class TestDeactivateDomain:
    def test_flips_to_inactive(self, projects_dir: Path):
        mgr = RunManager(projects_dir)
        mgr.ensure_domain("twitter")
        result = mgr.deactivate_domain("twitter")
        assert result.status == RunStatus.INACTIVE
        # Verify it persisted.
        reloaded = mgr.find_run("twitter")
        assert reloaded.status == RunStatus.INACTIVE


class TestResolveDomainForSession:
    def test_env_var_wins(self, projects_dir: Path, monkeypatch):
        mgr = RunManager(projects_dir)
        monkeypatch.setenv("FRAGO_DOMAIN", "Twitter")
        assert mgr.resolve_domain_for_session("sess-1", "/some/path") == "twitter"

    def test_falls_back_to_misc(self, projects_dir: Path, monkeypatch):
        mgr = RunManager(projects_dir)
        monkeypatch.delenv("FRAGO_DOMAIN", raising=False)
        # No current_run context exists in this isolated projects_dir layout.
        assert mgr.resolve_domain_for_session("sess-1", "/some/path") == "misc"


# --------------------------------------------------------------------- #
# Session model + storage
# --------------------------------------------------------------------- #


class TestSessionDomainFields:
    def test_monitored_session_has_domain_and_source_jsonl(self):
        from frago.session.models import AgentType, MonitoredSession, SessionStatus

        now = datetime.now()
        ms = MonitoredSession(
            session_id="abc",
            agent_type=AgentType.CLAUDE,
            project_path="/tmp/x",
            source_file="/foo.jsonl",
            started_at=now,
            status=SessionStatus.RUNNING,
            last_activity=now,
            domain="twitter",
            source_jsonl="/abs/path/abc.jsonl",
        )
        assert ms.domain == "twitter"
        assert ms.source_jsonl == "/abs/path/abc.jsonl"


class TestDomainAwareSessionStorage:
    def test_write_metadata_lands_under_domain_path(self, mock_home, monkeypatch):
        # Force projects dir into the isolated tmp ~/.frago/projects.
        monkeypatch.setenv(
            "FRAGO_PROJECTS_DIR", str(mock_home / ".frago" / "projects")
        )
        from frago.session.models import AgentType, MonitoredSession, SessionStatus
        from frago.session.storage import write_metadata

        now = datetime.now()
        ms = MonitoredSession(
            session_id="sess-x",
            agent_type=AgentType.CLAUDE,
            project_path="/tmp/x",
            source_file="/abs/path/sess-x.jsonl",
            started_at=now,
            status=SessionStatus.RUNNING,
            last_activity=now,
            domain="twitter",
            source_jsonl="/abs/path/sess-x.jsonl",
        )
        path = write_metadata(ms)
        expected_dir = mock_home / ".frago" / "projects" / "twitter" / "sess-x"
        assert expected_dir.is_dir()
        assert path == expected_dir / "metadata.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["domain"] == "twitter"
        assert data["source_jsonl"] == "/abs/path/sess-x.jsonl"


class TestWriteSummaryMd:
    def test_renders_summary_md(self, mock_home, monkeypatch):
        monkeypatch.setenv(
            "FRAGO_PROJECTS_DIR", str(mock_home / ".frago" / "projects")
        )
        from frago.session.models import (
            AgentType,
            MonitoredSession,
            SessionStatus,
        )
        from frago.session.storage import write_metadata, write_summary_md

        now = datetime.now()
        ms = MonitoredSession(
            session_id="sess-summary",
            agent_type=AgentType.CLAUDE,
            project_path="/tmp",
            source_file="/abs/sess-summary.jsonl",
            started_at=now,
            status=SessionStatus.COMPLETED,
            last_activity=now,
            ended_at=now,
            domain="twitter",
            source_jsonl="/abs/sess-summary.jsonl",
        )
        write_metadata(ms)
        md_path = write_summary_md("sess-summary", AgentType.CLAUDE, domain="twitter")
        assert md_path is not None
        text = md_path.read_text(encoding="utf-8")
        assert "sess-summary" in text
        assert "Status:" in text
        assert "Tool calls:" in text
