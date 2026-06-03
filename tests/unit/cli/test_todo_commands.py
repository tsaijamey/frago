"""CLI tests for `frago todo` — isolated via FRAGO_TODO_DIR."""

import json

import pytest
from click.testing import CliRunner

from frago.cli.todo_commands import todo_group


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_TODO_DIR", str(tmp_path))
    return CliRunner()


def _add(runner, *args):
    return runner.invoke(todo_group, ["add", *args])


def test_add_list_show_done_rm_roundtrip(runner):
    # add
    res = _add(runner, "--title", "add chrome fill command", "--priority", "high",
               "--tag", "chrome", "--tag", "cli", "--done-when", "drop the recipe")
    assert res.exit_code == 0, res.output
    assert "Created todo" in res.output
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    assert todo_id.endswith("-add-chrome-fill-command")

    # list shows it
    res = runner.invoke(todo_group, ["list"])
    assert todo_id in res.output
    assert "(1 todos)" in res.output

    # list filter
    res = runner.invoke(todo_group, ["list", "--status", "todo", "--priority", "high"])
    assert todo_id in res.output

    # show (prefix) returns valid JSON with all fields
    res = runner.invoke(todo_group, ["show", todo_id[:12]])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["id"] == todo_id
    assert data["tags"] == ["chrome", "cli"]
    assert data["done_when"] == ["drop the recipe"]

    # done stamps done_at
    res = runner.invoke(todo_group, ["done", todo_id[:12]])
    assert res.exit_code == 0
    assert "Marked done" in res.output
    res = runner.invoke(todo_group, ["show", todo_id])
    data = json.loads(res.output)
    assert data["status"] == "done"
    assert data["done_at"]

    # rm
    res = runner.invoke(todo_group, ["rm", todo_id])
    assert res.exit_code == 0
    assert "Removed" in res.output
    res = runner.invoke(todo_group, ["list"])
    assert "No todos." in res.output


def test_add_positional_title(runner):
    res = runner.invoke(todo_group, ["add", "调研上海万得在 AI agent 方面的近况"])
    assert res.exit_code == 0, res.output
    assert "Created todo" in res.output
    # positional and --title are equivalent; --title still works too
    res2 = runner.invoke(todo_group, ["add", "--title", "via option"])
    assert res2.exit_code == 0


def test_add_without_any_title_errors(runner):
    res = runner.invoke(todo_group, ["add"])
    assert res.exit_code != 0
    assert "provide a title" in res.output.lower()


def test_bare_invocation_lists(runner):
    _add(runner, "--title", "bare list check")
    res = runner.invoke(todo_group, [])
    assert res.exit_code == 0
    assert "bare-list-check" in res.output


def test_next_picks_correct(runner):
    _add(runner, "--title", "low task", "--priority", "low")
    _add(runner, "--title", "high task", "--priority", "high")
    res = runner.invoke(todo_group, ["next"])
    assert res.exit_code == 0
    assert "high-task" in res.output
    assert "[high]" in res.output


def test_schema_lists_all_fields(runner):
    res = runner.invoke(todo_group, ["schema"])
    assert res.exit_code == 0
    schema = json.loads(res.output)
    names = {f["name"] for f in schema["fields"]}
    assert {"id", "title", "status", "priority", "done_at", "done_when"} <= names


def test_show_ambiguous_prefix_errors(runner):
    _add(runner, "--title", "alpha one")
    _add(runner, "--title", "alpha two")
    res = runner.invoke(todo_group, ["show", "2026"])  # date prefix matches both
    assert res.exit_code != 0
    assert "ambiguous" in res.output.lower()


def test_edit_changes_fields(runner):
    res = _add(runner, "--title", "editable task")
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    res = runner.invoke(todo_group, ["edit", todo_id, "--priority", "high", "--status", "doing"])
    assert res.exit_code == 0
    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["priority"] == "high"
    assert data["status"] == "doing"


def test_edit_without_options_errors(runner):
    res = _add(runner, "--title", "no-op edit")
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    res = runner.invoke(todo_group, ["edit", todo_id])
    assert res.exit_code != 0
    assert "nothing to edit" in res.output.lower()
