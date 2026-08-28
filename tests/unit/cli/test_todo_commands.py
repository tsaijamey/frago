"""CLI tests for `frago todo` — isolated via FRAGO_TODO_DIR."""

import json

import pytest
from click.testing import CliRunner

from frago.cli.todo_commands import todo_group


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_TODO_DIR", str(tmp_path))
    # 会话来源逐条掐断：默认没有任何声明，也不去真实的 ~/.claude/projects 里
    # 猜——用例要什么会话，自己 setenv。
    monkeypatch.delenv("FRAGO_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(
        "frago.session.self_id.CLAUDE_PROJECTS_DIR", tmp_path / "no-such-projects"
    )
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


# ── 交接：会话尾声把剩下的事写成下一场会话接得住的待办 ──────────────────


def test_how_to_flag_and_subcommand_print_the_same_playbook(runner):
    flagged = runner.invoke(todo_group, ["--how-to"])
    assert flagged.exit_code == 0
    # 交接必须讲清的三件事：会话 id 怎么拿、长周期怎么续、下一场怎么接住
    assert "frago session self" in flagged.output
    assert "frago todo log" in flagged.output
    assert "frago todo next" in flagged.output

    sub = runner.invoke(todo_group, ["how-to"])
    assert sub.exit_code == 0
    assert sub.output == flagged.output


def test_add_records_the_declared_session(runner, monkeypatch):
    monkeypatch.setenv("FRAGO_SESSION_ID", "sess-declared")
    res = _add(runner, "--title", "handover with session")
    assert res.exit_code == 0, res.output
    assert "sess-declared" in res.output
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["sessions"] == ["sess-declared"]


def test_add_without_a_resolvable_session_says_so_and_how_to_fix(runner):
    res = _add(runner, "--title", "no session around")
    assert res.exit_code == 0
    assert "session id not resolved" in res.output
    assert "--session" in res.output  # 给出可直接执行的补救命令
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["sessions"] == []


def test_add_no_session_opts_out(runner, monkeypatch):
    monkeypatch.setenv("FRAGO_SESSION_ID", "sess-declared")
    res = _add(runner, "--title", "opted out", "--no-session")
    assert res.exit_code == 0
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["sessions"] == []
    assert "session id not resolved" not in res.output


def test_log_appends_across_sessions_without_losing_the_earlier_one(runner, monkeypatch):
    monkeypatch.setenv("FRAGO_SESSION_ID", "sess-one")
    res = _add(runner, "--title", "long running task", "--context", "起因：上游改了口径")
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()

    monkeypatch.setenv("FRAGO_SESSION_ID", "sess-two")
    res = runner.invoke(todo_group, ["log", todo_id, "抓到三篇年报，卡在取数口径", "--status", "doing"])
    assert res.exit_code == 0, res.output
    assert "sess-two" in res.output

    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["status"] == "doing"
    assert data["sessions"] == ["sess-one", "sess-two"]
    # 追加，不是覆盖：最初的背景还在
    assert "起因：上游改了口径" in data["context"]
    assert "抓到三篇年报" in data["context"]
    assert "session sess-two" in data["context"]


def test_log_twice_in_one_session_does_not_duplicate_the_id(runner, monkeypatch):
    monkeypatch.setenv("FRAGO_SESSION_ID", "sess-one")
    res = _add(runner, "--title", "same session twice")
    todo_id = res.output.split("Created todo ")[1].splitlines()[0].strip()
    runner.invoke(todo_group, ["log", todo_id, "第一段"])
    runner.invoke(todo_group, ["log", todo_id, "第二段"])
    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["sessions"] == ["sess-one"]
    assert "第一段" in data["context"] and "第二段" in data["context"]


def test_log_on_unknown_ref_errors(runner):
    res = runner.invoke(todo_group, ["log", "nope", "内容"])
    assert res.exit_code != 0
    assert "no todo matching" in res.output.lower()


def test_schema_documents_the_session_trail(runner):
    schema = json.loads(runner.invoke(todo_group, ["schema"]).output)
    names = {f["name"] for f in schema["fields"]}
    assert "sessions" in names
