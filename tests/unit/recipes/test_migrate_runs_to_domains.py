"""Tests for the migrate_runs_to_domains atomic recipe (Phase 4)."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

RECIPE_PATH = (
    Path.home() / ".frago" / "recipes" / "atomic" / "system"
    / "migrate_runs_to_domains" / "recipe.py"
)


def _load_recipe_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_runs_to_domains_recipe", RECIPE_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def recipe_mod():
    return _load_recipe_module()


def _make_legacy_run(
    projects_dir: Path,
    name: str,
    *,
    theme: str = "",
    execution_rows: list[dict] | None = None,
) -> Path:
    run = projects_dir / name
    (run / "logs").mkdir(parents=True)
    (run / "screenshots").mkdir()
    (run / "scripts").mkdir()
    (run / "outputs").mkdir()
    if theme:
        (run / ".metadata.json").write_text(
            json.dumps(
                {
                    "run_id": name,
                    "theme_description": theme,
                    "created_at": datetime.now().isoformat(),
                    "last_accessed": datetime.now().isoformat(),
                    "status": "archived",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if execution_rows:
        log = run / "logs" / "execution.jsonl"
        with log.open("w", encoding="utf-8") as f:
            for row in execution_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return run


@pytest.fixture
def fake_projects(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    # twitter (3 runs: 1 with insightful execution rows)
    _make_legacy_run(
        projects,
        "20260101-twitter-trending-research",
        theme="twitter trending research",
        execution_rows=[
            {"action_type": "navigation", "step": "go to x.com", "data": {}},
            {"action_type": "decision", "step": "skip ads", "data": {"why": "noise"}},
            {"action_type": "lesson", "step": "x.com hides metrics for guests", "data": {}},
        ],
    )
    _make_legacy_run(projects, "20260102-x-trending-topics")
    _make_legacy_run(projects, "20260103-tweet-extraction")
    # frago (use unique alias 'agent-os' to avoid cross-hit)
    _make_legacy_run(projects, "20260104-agent-os-runner-bug")
    # cross-domain (frago + twitter)
    _make_legacy_run(projects, "20260105-agent-os-and-twitter-integration-test")
    # misc fallback (no alias hit)
    _make_legacy_run(projects, "20260106-zzz-unrelated-topic")
    # already migrated marker — should be skipped
    (projects / "_legacy_20260107-already").mkdir()
    _make_legacy_run(projects, "20260107-already")
    return projects


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_dry_run_preview_no_writes(recipe_mod, fake_projects, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "recipe.py",
        json.dumps({"projects_dir": str(fake_projects)}),
    ])
    with pytest.raises(SystemExit) as exc:
        recipe_mod.main()
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["success"] is True
    data = out["data"]
    assert data["applied"] is False
    assert data["total_legacy"] == 7
    assert data["cluster"]["twitter"] >= 3
    assert data["cluster"]["frago"] >= 1
    assert "misc" in data["cluster"]
    # CROSS- candidate captured
    assert any(name.startswith("CROSS-") for name in data["cluster"].keys())
    # No domain dirs created in dry run
    assert not (fake_projects / "twitter").exists()
    assert not (fake_projects / "frago").exists()


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def test_apply_migrates_and_writes_insights(recipe_mod, fake_projects, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "recipe.py",
        json.dumps({
            "projects_dir": str(fake_projects),
            "dry_run": False,
            "apply": True,
            "_skip_backup": True,
        }),
    ])
    with pytest.raises(SystemExit) as exc:
        recipe_mod.main()
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out.strip())
    data = out["data"]
    assert data["applied"] is True
    assert data["migrated"] >= 5
    assert data["skipped"] >= 1  # the _legacy_ already-migrated stub
    assert data["failed"] == []

    # twitter domain dir exists with all 3 runs migrated under it
    twitter_dir = fake_projects / "twitter"
    assert twitter_dir.is_dir()
    assert (twitter_dir / "_domain.json").exists()
    assert (twitter_dir / "20260101-twitter-trending-research").is_dir()

    # markers at original locations
    assert (fake_projects / "_legacy_20260101-twitter-trending-research").is_dir()
    marker_payload = json.loads(
        (fake_projects / "_legacy_20260101-twitter-trending-research"
         / "migrated.json").read_text(encoding="utf-8")
    )
    assert marker_payload["domain"] == "twitter"
    assert marker_payload["insights_written"] >= 3  # 1 summary + decision + lesson

    # insight.jsonl has decision + lesson + summary
    insight_log = twitter_dir / "insight.jsonl"
    assert insight_log.exists()
    rows = [json.loads(l) for l in insight_log.read_text().splitlines() if l]
    types = {r["type"] for r in rows}
    assert {"decision", "lesson", "fact"}.issubset(types)
    # confidence preserved
    assert all(r["confidence"] == 0.5 for r in rows)

    # log file written
    log_file = fake_projects.parent / "_legacy" / "migration.log"
    assert log_file.exists()
    assert "OK 20260101-twitter-trending-research" in log_file.read_text()


def test_apply_is_idempotent(recipe_mod, fake_projects, capsys, monkeypatch):
    """Running apply twice should skip the already-migrated runs."""
    args = json.dumps({
        "projects_dir": str(fake_projects),
        "dry_run": False,
        "apply": True,
        "_skip_backup": True,
    })
    monkeypatch.setattr(sys, "argv", ["recipe.py", args])
    with pytest.raises(SystemExit):
        recipe_mod.main()
    capsys.readouterr()  # discard

    # Second run
    with pytest.raises(SystemExit):
        recipe_mod.main()
    out2 = json.loads(capsys.readouterr().out.strip())
    data2 = out2["data"]
    # Second pass: only the pre-existing already-migrated stub dir lingers
    # (its source still exists because the original marker blocked pass 1).
    assert data2["migrated"] == 0
    assert data2["skipped"] >= 1
    assert data2["failed"] == []


# ---------------------------------------------------------------------------
# target filter
# ---------------------------------------------------------------------------


def test_target_filter_only_touches_one_domain(recipe_mod, fake_projects, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "recipe.py",
        json.dumps({
            "projects_dir": str(fake_projects),
            "dry_run": False,
            "apply": True,
            "target": "twitter",
            "_skip_backup": True,
        }),
    ])
    with pytest.raises(SystemExit):
        recipe_mod.main()
    out = json.loads(capsys.readouterr().out.strip())
    data = out["data"]
    # Only the twitter cluster shows up in preview
    assert set(data["cluster"].keys()) == {"twitter"}
    assert data["migrated"] == data["cluster"]["twitter"]
    # frago not created
    assert not (fake_projects / "frago").exists()


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def test_backup_tar_is_created(recipe_mod, fake_projects, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "recipe.py",
        json.dumps({
            "projects_dir": str(fake_projects),
            "dry_run": False,
            "apply": True,
            "target": "twitter",
        }),
    ])
    with pytest.raises(SystemExit):
        recipe_mod.main()
    out = json.loads(capsys.readouterr().out.strip())
    backup_path = Path(out["data"]["backup_path"])
    assert backup_path.exists()
    assert backup_path.suffix == ".gz"
    assert backup_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_extract_insights_filters_noise(recipe_mod, tmp_path: Path):
    log = tmp_path / "execution.jsonl"
    rows = [
        {"action_type": "navigation", "step": "noise", "data": {}},
        {"action_type": "decision", "step": "use option A", "data": {"reason": "x"}},
        {"action_type": "fact", "step": "API rate limit is 100/min", "data": {}},
        {"action_type": "websearch", "step": "noise2", "data": {}},
    ]
    log.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    out = recipe_mod._extract_insights_from_execution_log(log)
    assert len(out) == 2
    types = {t for t, _ in out}
    assert types == {"decision", "fact"}


def test_classify_uses_metadata_theme(recipe_mod, tmp_path: Path):
    projects = tmp_path / "projects"
    projects.mkdir()
    # slug alone has no domain hit; theme provides it
    run = _make_legacy_run(projects, "20260101-zz-aa-bb", theme="hacker news front page check")
    assert recipe_mod.classify(run) == "hn"
