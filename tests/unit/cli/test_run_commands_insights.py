"""Phase 2 CLI tests — frago run insights / init / list / info / find."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import frago.cli.run_commands as run_mod
from frago.cli.run_commands import run_group


@pytest.fixture
def isolated_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect FRAGO_HOME / PROJECTS_DIR to an isolated tmp tree."""
    home = tmp_path / ".frago"
    projects = home / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(run_mod, "FRAGO_HOME", home)
    monkeypatch.setattr(run_mod, "PROJECTS_DIR", projects)
    # ContextManager honours FRAGO_CURRENT_RUN before the config file; clear
    # it so tests see only the per-test set-context state.
    monkeypatch.delenv("FRAGO_CURRENT_RUN", raising=False)
    monkeypatch.delenv("FRAGO_DOMAIN", raising=False)
    return projects


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _ensure_domain(runner: CliRunner, domain: str) -> None:
    result = runner.invoke(run_group, ["init", domain])
    assert result.exit_code == 0, result.output


def _set_context(runner: CliRunner, domain: str) -> None:
    result = runner.invoke(run_group, ["set-context", domain])
    assert result.exit_code == 0, result.output


# -------------------------- init -------------------------- #


class TestInit:
    def test_init_creates_domain(self, runner, isolated_projects):
        result = runner.invoke(run_group, ["init", "twitter"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["domain"] == "twitter"
        assert (isolated_projects / "twitter" / "_domain.json").exists()

    def test_init_dry_run(self, runner, isolated_projects):
        result = runner.invoke(run_group, ["init", "twitter", "--dry-run"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["status"] == "new"
        # No directory created.
        assert not (isolated_projects / "twitter").exists()


# -------------------------- list -------------------------- #


class TestList:
    def test_list_default_domain_view(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _ensure_domain(runner, "feishu")
        result = runner.invoke(run_group, ["list"])
        assert result.exit_code == 0
        assert "DOMAIN" in result.output
        assert "twitter" in result.output
        assert "feishu" in result.output

    def test_list_flat_legacy_view(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        result = runner.invoke(run_group, ["list", "--flat"])
        assert result.exit_code == 0
        assert "RUN_ID" in result.output


# -------------------------- insights save / list / query / update -------------------------- #


class TestInsightsCli:
    def test_save_requires_type(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        result = runner.invoke(
            run_group, ["insights", "--save", "--payload", "no type"]
        )
        assert result.exit_code != 0
        assert "--type" in result.output

    def test_save_requires_payload(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        result = runner.invoke(
            run_group, ["insights", "--save", "--type", "fact"]
        )
        assert result.exit_code != 0
        assert "--payload" in result.output

    def test_save_then_list(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")

        save = runner.invoke(
            run_group,
            [
                "insights",
                "--save",
                "--type",
                "fact",
                "--payload",
                "API rate limit",
                "--confidence",
                "0.9",
            ],
        )
        assert save.exit_code == 0, save.output
        saved_id = json.loads(save.output)["saved"]["id"]

        listed = runner.invoke(run_group, ["insights", "--format", "json"])
        assert listed.exit_code == 0
        data = json.loads(listed.output)
        assert data["count"] == 1
        assert data["insights"][0]["id"] == saved_id

    def test_query_filter(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        for payload in ("rate limit hit", "login redirect"):
            r = runner.invoke(
                run_group,
                ["insights", "--save", "--type", "fact", "--payload", payload],
            )
            assert r.exit_code == 0, r.output

        result = runner.invoke(
            run_group, ["insights", "--query", "rate", "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1
        assert "rate" in data["insights"][0]["payload"]

    def test_update_appends_version(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        save = runner.invoke(
            run_group,
            ["insights", "--save", "--type", "fact", "--payload", "v1"],
        )
        saved_id = json.loads(save.output)["saved"]["id"]
        upd = runner.invoke(
            run_group,
            ["insights", "--update", saved_id, "--payload", "v2"],
        )
        assert upd.exit_code == 0, upd.output
        data = json.loads(upd.output)
        assert data["updated"]["payload"] == "v2"
        assert data["updated"]["version"] == 2

    def test_explicit_domain_flag(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        # No set-context: rely on --domain.
        save = runner.invoke(
            run_group,
            [
                "insights",
                "--domain",
                "twitter",
                "--save",
                "--type",
                "fact",
                "--payload",
                "without context",
            ],
        )
        assert save.exit_code == 0, save.output

    def test_save_bumps_insight_count(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        runner.invoke(
            run_group,
            ["insights", "--save", "--type", "fact", "--payload", "x"],
        )
        meta = json.loads(
            (isolated_projects / "twitter" / "_domain.json").read_text(encoding="utf-8")
        )
        assert meta["insight_count"] == 1


# -------------------------- info --peek -------------------------- #


class TestInfoPeek:
    def test_peek_returns_summary_json(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        runner.invoke(
            run_group,
            [
                "insights",
                "--save",
                "--type",
                "fact",
                "--payload",
                "Important fact",
            ],
        )
        result = runner.invoke(run_group, ["info", "twitter", "--peek"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["domain"] == "twitter"
        assert data["insight_count"] >= 1
        assert any("Important fact" in i["payload"] for i in data["top_insights"])


# -------------------------- find -------------------------- #


class TestFind:
    def test_find_searches_insight_payloads(self, runner, isolated_projects):
        _ensure_domain(runner, "twitter")
        _set_context(runner, "twitter")
        runner.invoke(
            run_group,
            [
                "insights",
                "--save",
                "--type",
                "fact",
                "--payload",
                "needle xyzzy in payload",
            ],
        )
        result = runner.invoke(run_group, ["find", "xyzzy", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert any(
            "xyzzy" in h["insight"]["payload"] for h in data.get("insights", [])
        )
