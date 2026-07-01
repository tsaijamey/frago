"""Unit tests for SchedulerService pure logic and CRUD.

Covers module-level helpers (_parse_interval, _parse_dt) and the
SchedulerService methods _migrate_schedule + add/remove/toggle/list.
Persistence is redirected to tmp_path so the real ~/.frago/schedules.json
is never touched.
"""

from datetime import datetime

import pytest

from frago.server.services.scheduler_service import (
    SchedulerService,
    _parse_dt,
    _parse_interval,
)


@pytest.fixture
def svc(tmp_path):
    """A fresh (non-singleton) SchedulerService with tmp-backed storage."""
    s = SchedulerService()
    s._schedules_path = tmp_path / "schedules.json"
    return s


# --- _parse_interval ---

@pytest.mark.parametrize(
    "spec,expected",
    [
        ("30s", 30),
        ("10m", 600),
        ("2h", 7200),
        ("45", 45),
        (" 1H ", 3600),  # whitespace + uppercase normalized
        ("0s", 0),
    ],
)
def test_parse_interval(spec, expected):
    assert _parse_interval(spec) == expected


# --- _parse_dt ---

def test_parse_dt_none():
    assert _parse_dt(None) is None
    assert _parse_dt("") is None


def test_parse_dt_naive():
    dt = _parse_dt("2026-06-29T12:00:00")
    assert dt == datetime(2026, 6, 29, 12, 0, 0)
    assert dt.tzinfo is None


def test_parse_dt_strips_tz():
    dt = _parse_dt("2026-06-29T12:00:00+08:00")
    assert dt.tzinfo is None
    # Time-of-day preserved, just tz dropped (no offset normalization).
    assert dt == datetime(2026, 6, 29, 12, 0, 0)


# --- _migrate_schedule ---

def test_migrate_schedule_old_format():
    old = {"id": "x", "recipe_name": "daily_report", "enabled": True}
    m = SchedulerService._migrate_schedule(old)
    assert m["name"] == "daily_report"
    assert m["prompt"] == "执行 recipe daily_report"
    assert m["recipe"] == "daily_report"
    assert m["cron"] is None
    assert m["overlap"] == "skip"
    assert m["timeout"] == 300
    assert m["history"] == []
    assert m["reply_channel"] is None
    assert m["reply_context"] == {}


def test_migrate_schedule_no_recipe():
    m = SchedulerService._migrate_schedule({"id": "y"})
    assert m["name"] == "unnamed"
    assert m["prompt"] == ""
    # No recipe_name → recipe key not injected
    assert "recipe" not in m


def test_migrate_schedule_preserves_existing():
    s = {
        "id": "z",
        "name": "keep",
        "prompt": "keep prompt",
        "recipe": "r",
        "cron": "* * * * *",
        "overlap": "queue",
        "timeout": 99,
        "history": [{"status": "ok"}],
        "reply_channel": "feishu",
        "reply_context": {"a": 1},
    }
    m = SchedulerService._migrate_schedule(s)
    assert m["name"] == "keep"
    assert m["prompt"] == "keep prompt"
    assert m["overlap"] == "queue"
    assert m["timeout"] == 99
    assert m["history"] == [{"status": "ok"}]
    assert m["reply_channel"] == "feishu"
    assert m["reply_context"] == {"a": 1}


# --- CRUD ---

def test_add_schedule_persists_and_defaults(svc):
    sch = svc.add_schedule(recipe_name="rep", interval_seconds=600)
    assert sch["id"].startswith("sch_")
    assert sch["name"] == "rep"
    assert sch["prompt"] == "执行 recipe rep"
    assert sch["recipe"] == "rep"
    assert sch["interval_seconds"] == 600
    assert sch["enabled"] is True
    assert sch["run_count"] == 0
    # Persisted to disk and reloadable.
    assert svc._schedules_path.exists()
    assert len(svc.list_schedules()) == 1
    assert svc.list_schedules()[0]["id"] == sch["id"]


def test_add_schedule_explicit_name_prompt(svc):
    sch = svc.add_schedule(name="custom", prompt="do it", interval_seconds=30)
    assert sch["name"] == "custom"
    assert sch["prompt"] == "do it"
    assert sch["recipe"] is None


def test_add_schedule_no_recipe_empty_prompt(svc):
    sch = svc.add_schedule(interval_seconds=30)
    assert sch["name"] == "unnamed"
    assert sch["prompt"] == ""


def test_remove_schedule(svc):
    a = svc.add_schedule(name="a", interval_seconds=30)
    b = svc.add_schedule(name="b", interval_seconds=30)
    assert svc.remove_schedule(a["id"]) is True
    remaining = [s["id"] for s in svc.list_schedules()]
    assert remaining == [b["id"]]
    # Removing again is a no-op.
    assert svc.remove_schedule(a["id"]) is False


def test_remove_schedule_missing(svc):
    svc.add_schedule(name="a", interval_seconds=30)
    assert svc.remove_schedule("sch_nope") is False


def test_toggle_schedule(svc):
    sch = svc.add_schedule(name="a", interval_seconds=30)
    assert sch["enabled"] is True
    assert svc.toggle_schedule(sch["id"]) is False
    assert svc.list_schedules()[0]["enabled"] is False
    assert svc.toggle_schedule(sch["id"]) is True
    assert svc.list_schedules()[0]["enabled"] is True


def test_toggle_schedule_missing(svc):
    assert svc.toggle_schedule("sch_nope") is None


def test_list_schedules_empty(svc):
    assert svc.list_schedules() == []


def test_crud_survives_reload(svc):
    """A separate instance pointed at the same file sees persisted data."""
    svc.add_schedule(name="persisted", interval_seconds=60)
    other = SchedulerService()
    other._schedules_path = svc._schedules_path
    listed = other.list_schedules()
    assert len(listed) == 1
    assert listed[0]["name"] == "persisted"
