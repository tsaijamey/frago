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
    res = runner.invoke(todo_group, ["add", "investigate shanghai wind ai agent"])
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


# ── 分类 ────────────────────────────────────────────────────────────────


def _new_id(res):
    return res.output.split("Created todo ")[1].splitlines()[0].strip()


def test_add_with_unknown_category_lists_choices(runner):
    res = _add(runner, "x", "--category", "fun")
    assert res.exit_code != 0
    assert "family(家庭)" in res.output


def test_categorize_rejects_whole_batch(runner, tmp_path):
    a = _new_id(_add(runner, "alpha"))
    b = _new_id(_add(runner, "beta"))
    mapping = json.dumps({a: "work", b: "fun", "ghost": "family"})
    res = runner.invoke(todo_group, ["categorize", mapping])
    assert res.exit_code != 0
    assert "REJECTED, nothing written" in res.output
    assert "ghost" in res.output and "'fun'" in res.output
    # 合法的那条也不许先写进去
    assert json.loads((tmp_path / f"{a}.json").read_text())["category"] is None


def test_categorize_from_stdin_reports_count(runner):
    a = _new_id(_add(runner, "alpha"))
    b = _new_id(_add(runner, "beta"))
    res = runner.invoke(todo_group, ["categorize"], input=json.dumps({a: "work", b: "family"}))
    assert res.exit_code == 0, res.output
    assert res.output.startswith("OK: categorized 2 todo(s)")
    listed = runner.invoke(todo_group, ["list", "--category", "work"]).output
    assert a in listed and b not in listed


def test_categorize_rejects_bad_json(runner):
    res = runner.invoke(todo_group, ["categorize", "not json"])
    assert res.exit_code != 0
    assert "REJECTED" in res.output


def test_edit_clears_category(runner):
    a = _new_id(_add(runner, "alpha", "--category", "work"))
    assert runner.invoke(todo_group, ["edit", a, "--category", "none"]).exit_code == 0
    data = json.loads(runner.invoke(todo_group, ["show", a]).output)
    assert data["category"] is None


def test_category_list_cap(runner):
    for i in range(16):
        res = runner.invoke(todo_group, ["category", "add", f"c{i}", f"分类{i}"])
        assert res.exit_code == 0, res.output
    res = runner.invoke(todo_group, ["category", "add", "overflow", "多一个"])
    assert res.exit_code != 0
    assert "at most 20" in res.output


def test_category_manage_commands(runner):
    assert runner.invoke(todo_group, ["category", "rename", "hobby", "爱好"]).exit_code == 0
    assert runner.invoke(todo_group, ["category", "move", "other", "1"]).exit_code == 0
    out = runner.invoke(todo_group, ["category", "list"]).output
    assert out.index("other") < out.index("family")
    assert "爱好" in out
    assert runner.invoke(todo_group, ["category", "rename", "ghost", "x"]).exit_code != 0


def test_category_rm_reports_referencing_todos(runner):
    _add(runner, "alpha", "--category", "work")
    _add(runner, "beta", "--category", "work")
    res = runner.invoke(todo_group, ["category", "rm", "work"])
    assert res.exit_code != 0
    assert "2 todo(s)" in res.output
    res = runner.invoke(todo_group, ["category", "rm", "work", "--force"])
    assert res.exit_code == 0
    assert "2 todo(s) now sort as uncategorized" in res.output


# ── 弃置 ────────────────────────────────────────────────────────────────


def _drop_target(runner):
    res = _add(runner, "--title", "drop me")
    return res.output.split("Created todo ")[1].splitlines()[0].strip()


def test_drop_records_the_reason(runner):
    todo_id = _drop_target(runner)
    res = runner.invoke(todo_group, ["drop", todo_id, "--reason", "上游换了做法，这条不再成立"])
    assert res.exit_code == 0, res.output
    assert "Dropped" in res.output
    # 回显里带上理由：人刚打完那句话，要看见它被原样收下了。
    assert "上游换了做法，这条不再成立" in res.output

    shown = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert shown["status"] == "dropped"
    assert shown["drop_reason"] == "上游换了做法，这条不再成立"
    assert shown["dropped_at"]


def test_drop_without_reason_option_is_refused_by_the_command_itself(runner):
    todo_id = _drop_target(runner)
    res = runner.invoke(todo_group, ["drop", todo_id])
    assert res.exit_code != 0
    assert "--reason" in res.output


def test_drop_with_a_blank_reason_is_refused(runner):
    todo_id = _drop_target(runner)
    res = runner.invoke(todo_group, ["drop", todo_id, "--reason", "   "])
    assert res.exit_code != 0
    assert "reason is required" in res.output


def test_dropping_twice_is_refused(runner):
    todo_id = _drop_target(runner)
    runner.invoke(todo_group, ["drop", todo_id, "--reason", "第一次的理由"])
    res = runner.invoke(todo_group, ["drop", todo_id, "--reason", "第二次的理由"])
    assert res.exit_code != 0
    assert "第一次的理由" in res.output


@pytest.mark.parametrize("args", [
    ["edit", "--status", "dropped"],
    ["log", "记一笔", "--status", "dropped"],
])
def test_dropped_is_not_settable_through_edit_or_log(runner, args):
    """留一条不用给理由的旁路，理由那一栏迟早大半是空的。"""
    todo_id = _drop_target(runner)
    res = runner.invoke(todo_group, [args[0], todo_id, *args[1:]])
    assert res.exit_code != 0
    assert "'dropped' is not one of" in res.output


def test_add_cannot_start_a_todo_as_dropped(runner):
    res = _add(runner, "--title", "born dropped", "--status", "dropped")
    assert res.exit_code != 0
    assert "'dropped' is not one of" in res.output


def test_list_can_still_filter_by_dropped(runner):
    todo_id = _drop_target(runner)
    runner.invoke(todo_group, ["drop", todo_id, "--reason", "不做了"])
    _add(runner, "--title", "still here")

    res = runner.invoke(todo_group, ["list", "--status", "dropped"])
    assert res.exit_code == 0, res.output
    assert todo_id in res.output
    assert "(1 todos)" in res.output


# ── 标题：非 ASCII 会 slug 成读不出的 id，命令侧当场拦 ──────────────────
# 「凡是会被拿去生成文件名或 slug 的标题字段必须用英文，中文放 --summary / --context」
# 这条约束本来就写在知识域与交接手册里，但只有一条 hook 提醒顶着——提醒归提醒，中文标题
# 照样落盘、照样打印 Created todo、退出码 0。事后无感的错治不住，所以规则挪到命令上。
# 与之配套的一半：id 事后改得动（见下面的 edit --id），否则取错一次就固定一辈子。


def test_cjk_title_is_refused_and_writes_nothing(runner, tmp_path):
    res = _add(runner, "修复会话列表的报错提示")

    assert res.exit_code != 0
    assert list(tmp_path.glob("*.json")) == []


def test_the_offending_characters_are_shown_in_order(runner):
    """排过序再显示等于把原话打乱（「会修列复报提的示」），读的人得自己拼回去。"""
    res = _add(runner, "修复会话列表的报错提示")

    assert "（修复会话列表的报错提示）" in res.output


def test_the_error_shows_the_slug_it_would_have_produced(runner):
    """抽象地说「不许非 ASCII」没用；要让人看见这一条会变成什么。"""
    res = _add(runner, "修复会话列表的报错提示")

    assert "xiu-fu-hui-hua-lie-biao-de-bao" in res.output


def test_the_error_says_where_the_chinese_goes(runner):
    """拒绝一个动作却不说替代路径，调用方下一步就是换个写法再试一遍。"""
    res = _add(runner, "修复会话列表的报错提示")

    assert "--summary" in res.output
    assert "--context" in res.output
    assert "frago todo edit" in res.output


def test_ascii_title_still_works(runner):
    res = _add(runner, "fix-session-list-error", "--summary", "会话列表报错时给出的提示看不懂")
    assert res.exit_code == 0, res.output

    data = json.loads(runner.invoke(todo_group, ["show", _new_id(res)]).output)
    assert data["summary"] == "会话列表报错时给出的提示看不懂"


def test_edit_renames_a_pinyin_id_and_keeps_history(runner):
    """登记时 id 落成了拼音的，改法在这里——created / 标签这些历史不许丢。"""
    todo_id = _new_id(_add(runner, "legacy pinyin id", "--tag", "dx"))
    before = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)

    res = runner.invoke(todo_group, ["edit", todo_id, "--id", "20260627-readable-id"])

    assert res.exit_code == 0, res.output
    after = json.loads(runner.invoke(todo_group, ["show", "20260627-readable-id"]).output)
    assert after["created"] == before["created"]
    assert after["tags"] == ["dx"]
    assert runner.invoke(todo_group, ["show", todo_id]).exit_code != 0  # 旧名不再认


def test_edit_rename_rejects_a_taken_id(runner):
    first = _new_id(_add(runner, "first one"))
    second = _new_id(_add(runner, "second one"))

    res = runner.invoke(todo_group, ["edit", second, "--id", first])

    assert res.exit_code != 0
    assert "already taken" in res.output


def test_edit_title_may_be_non_ascii(runner):
    """标题只有 add 那一刻会被拿去生成 id；改标题不动 id，所以这里放行。

    这条留着是有用的：先建一条英文 id 的事务，再把标题写成中文——中文标题配读得出的
    id 这么得，不必牺牲任何一边。
    """
    todo_id = _new_id(_add(runner, "fix-session-list-error"))

    res = runner.invoke(todo_group, ["edit", todo_id, "--title", "修复会话列表的报错提示"])

    assert res.exit_code == 0, res.output
    data = json.loads(runner.invoke(todo_group, ["show", todo_id]).output)
    assert data["title"] == "修复会话列表的报错提示"
