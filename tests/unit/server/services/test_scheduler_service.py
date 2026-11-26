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
    assert m["timeout"] == 7200
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


@pytest.mark.asyncio
async def test_multiple_due_schedules_in_same_tick_do_not_retrigger(svc, monkeypatch):
    """When an earlier schedule reloads self._schedules in _execute_native,
    subsequent due schedules in the same tick must still persist last_run_at
    and not re-trigger on the next tick.
    """
    from frago.server.services import schedule_executor as ex

    s1 = svc.add_schedule(name="first_9am", command="echo 1", cron="0 9 * * *")
    s2 = svc.add_schedule(name="second_9am", command="echo 2", cron="0 9 * * *")
    yesterday = "2026-11-02T09:00:00"
    for s in svc._schedules:
        s["last_run_at"] = yesterday
    svc._save()

    async def fake_run_scheduled(schedule):
        return ex.RunOutcome(
            ok=True,
            kind=schedule.get("kind", "command"),
            exit_code=0,
            stdout="ok",
            duration_ms=10,
            digest="d1",
        )

    monkeypatch.setattr(ex, "run_scheduled", fake_run_scheduled)

    now = datetime(2026, 11, 3, 9, 0, 5)
    monkeypatch.setattr("frago.server.services.scheduler_service._now_utc", lambda: now)

    # Simulate one tick loop body over all schedules
    svc._load()
    for schedule_id in [s["id"] for s in svc._schedules]:
        schedule = next((s for s in svc._schedules if s["id"] == schedule_id), None)
        assert schedule is not None
        assert svc._is_due(schedule, now) is True
        await svc._execute(schedule)

    # Reload from disk and verify both schedules persisted today's last_run_at and run_count == 1
    svc._load()
    by_id = {s["id"]: s for s in svc._schedules}
    assert by_id[s1["id"]]["run_count"] == 1
    assert by_id[s2["id"]]["run_count"] == 1
    assert by_id[s1["id"]]["last_run_at"] == now.isoformat()
    assert by_id[s2["id"]]["last_run_at"] == now.isoformat()

    # On the next tick 5 seconds later, neither schedule is due again
    next_tick = datetime(2026, 11, 3, 9, 0, 10)
    assert svc._is_due(by_id[s1["id"]], next_tick) is False
    assert svc._is_due(by_id[s2["id"]], next_tick) is False


def test_add_update_and_migrate_employee_schedule(svc):
    sch = svc.add_schedule(
        name="早盘巡检",
        prompt="检查行情",
        employee_id="stock",
        session_title_template="[{date} {weekday}] {employee} · {schedule_name} #{seq}",
        cron="0 9 * * 1-5",
    )
    assert sch["kind"] == "employee"
    assert sch["employee_id"] == "stock"
    assert sch["session_title_template"] == "[{date} {weekday}] {employee} · {schedule_name} #{seq}"

    # 仅带 employee_id 的旧/半成品记录也能由 _migrate_schedule 自动识别为 employee
    migrated = SchedulerService._migrate_schedule({"id": "sch_m1", "employee_id": "ops"})
    assert migrated["kind"] == "employee"
    assert migrated["session_title_template"] is None

    updated = svc.update_schedule(
        sch["id"],
        name="盘中盯盘",
        employee_id="analyst",
        interval_seconds=300,
        cron=None,
    )
    assert updated is not None
    assert updated["id"] == sch["id"]
    assert updated["name"] == "盘中盯盘"
    assert updated["employee_id"] == "analyst"
    assert updated["interval_seconds"] == 300
    assert updated["cron"] is None


def test_preview_next_runs_renders_dynamic_title_and_dates(svc, monkeypatch):
    monkeypatch.setattr(
        "frago.server.services.scheduler_service._now_utc",
        lambda: datetime(2026, 11, 4, 8, 0, 0),
    )
    runs = svc.preview_next_runs(
        {
            "name": "早报",
            "kind": "employee",
            "employee_id": "analyst",
            "session_title_template": "[{date} {weekday}] {employee} · {schedule_name} #{seq}",
            "cron": "0 9 * * *",
            "run_count": 30,
        },
        count=3,
        employee_title="金融专家",
    )
    assert len(runs) == 3
    assert runs[0]["seq"] == 31
    assert runs[0]["session_title"] == "[11-04 周三] 金融专家 · 早报 #31"
    assert runs[1]["seq"] == 32
    assert runs[1]["session_title"] == "[11-05 周四] 金融专家 · 早报 #32"
    assert runs[2]["seq"] == 33
    assert runs[2]["session_title"] == "[11-06 周五] 金融专家 · 早报 #33"


@pytest.mark.asyncio
async def test_per_schedule_id_reentrancy_guard_skips_overlapping_trigger(svc, monkeypatch):
    import asyncio

    from frago.server.services import schedule_executor as ex

    sch = svc.add_schedule(
        name="防重入员工任务",
        employee_id="demo-emp",
        prompt="干活",
        interval_seconds=60,
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def fake_run_scheduled(schedule):
        calls.append(schedule["id"])
        started.set()
        await release.wait()
        return ex.RunOutcome(ok=True, kind="employee", stdout="done", digest="d1", session_title="t1")

    monkeypatch.setattr(ex, "run_scheduled", fake_run_scheduled)

    t1 = asyncio.create_task(svc._execute(sch))
    await started.wait()

    # 同一个 schedule_id 在上一轮尚未结束时再次触发，应立即被 per-schedule_id 锁/重入守卫拦截
    await svc._execute(sch)
    assert len(calls) == 1

    release.set()
    await t1
    assert len(calls) == 1
    assert sch["id"] not in svc._active_schedule_ids


