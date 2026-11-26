"""CLI tests for `frago schedule` native employee binding (--employee, --title-template)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from frago.cli.main import cli
from frago.employee.store import EmployeePostRecord, save_post
from frago.server.services.scheduler_service import SchedulerService


@pytest.fixture
def isolated_cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))
    svc = SchedulerService()
    svc._schedules_path = tmp_path / "schedules.json"
    monkeypatch.setattr(SchedulerService, "get_instance", classmethod(lambda cls: svc))
    save_post(
        EmployeePostRecord(
            member_post_id="demo-ops",
            title="巡检专员",
            description="负责例行巡检",
            agent_kernel="coreagent",
        )
    )
    return svc


def test_schedule_add_employee_persists_and_lists_emp_tag(isolated_cli_env):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "schedule",
            "add",
            "--employee",
            "demo-ops",
            "--prompt",
            "检查告警队列",
            "--every",
            "10m",
            "--name",
            "告警巡检",
            "--notify-to",
            "desktop",
            "--title-template",
            "[{date} {weekday}] {employee} · {schedule_name} #{seq}",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "Employee: @demo-ops" in res.output

    schedules = isolated_cli_env.list_schedules()
    assert len(schedules) == 1
    assert schedules[0]["kind"] == "employee"
    assert schedules[0]["employee_id"] == "demo-ops"
    assert schedules[0]["session_title_template"] == "[{date} {weekday}] {employee} · {schedule_name} #{seq}"

    list_res = runner.invoke(cli, ["schedule", "list"])
    assert list_res.exit_code == 0, list_res.output
    assert "emp:@demo-ops" in list_res.output


def test_schedule_add_missing_employee_fails_cleanly(isolated_cli_env):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "schedule",
            "add",
            "--employee",
            "ghost-emp",
            "--prompt",
            "巡检",
            "--every",
            "10m",
            "--notify-on",
            "never",
        ],
    )
    assert res.exit_code != 0
    assert "ghost-emp" in res.output


def test_schedule_add_rejects_mixing_employee_with_command(isolated_cli_env):
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "schedule",
            "add",
            "--employee",
            "demo-ops",
            "--command",
            "echo hi",
            "--every",
            "10m",
            "--notify-on",
            "never",
        ],
    )
    assert res.exit_code != 0
    assert "只能给一个" in res.output
