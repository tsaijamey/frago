"""一场会话动过哪些文件：从工具调用里读出来的那一层。

钉的是判据，不是数字：哪几个工具算动过、路径从哪个键取、同一个文件动两次算几个、
顺序按什么排。四家的记录形状不同，但工具调用那一格是同一个形状（``tool_name`` + ``args``），
所以这里用同一批记录喂进去，只换工具名和路径键。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frago.session import record_reader
from frago.session.session_files import is_scratch_path, session_files
from frago.session.unified_record import UnifiedRecord


def _call(seq: int, tool: str, args: dict | None = None) -> UnifiedRecord:
    return UnifiedRecord(
        id=f"r{seq}",
        session_id="sid-1",
        group_id=None,
        seq=seq,
        ts=1_700_000_000_000 + seq,
        kind="tool.call",
        payload={"call_id": f"c{seq}", "tool_name": tool, "args": args or {}},
    )


@pytest.fixture
def feed(monkeypatch):
    """把一批记录塞给 record_reader，整场一次读完。"""

    def _feed(records):
        monkeypatch.setattr(
            record_reader, "read_records", lambda sid, after=0, limit=200, tail=False: records
        )

    return _feed


def test_write_is_created_and_edit_is_modified(feed):
    feed([
        _call(0, "Write", {"file_path": "/w/new.py", "content": "x"}),
        _call(1, "Edit", {"file_path": "/w/old.py", "old_string": "a", "new_string": "b"}),
    ])

    files = session_files("sid-1")

    assert [(f.path, f.action) for f in files] == [
        ("/w/new.py", "created"),
        ("/w/old.py", "modified"),
    ]


def test_a_file_written_then_edited_stays_created_and_counts_both(feed):
    feed([
        _call(0, "Write", {"file_path": "/w/a.py"}),
        _call(5, "Edit", {"file_path": "/w/a.py"}),
        _call(9, "Edit", {"file_path": "/w/a.py"}),
    ])

    [only] = session_files("sid-1")

    assert (only.action, only.count, only.first_seq) == ("created", 3, 0)


def test_opencode_spells_the_path_differently(feed):
    """opencode 的写改工具叫 write / edit，路径在 filePath 上。"""
    feed([
        _call(0, "write", {"filePath": "/w/a.ts"}),
        _call(1, "edit", {"filePath": "/w/b.ts"}),
    ])

    assert [(f.path, f.action) for f in session_files("sid-1")] == [
        ("/w/a.ts", "created"),
        ("/w/b.ts", "modified"),
    ]


def test_tool_names_are_matched_case_insensitively(feed):
    feed([_call(0, "MULTIEDIT", {"file_path": "/w/a.py"})])

    [only] = session_files("sid-1")

    assert only.action == "modified"


def test_reading_is_not_touching(feed):
    """看过什么不算动过，收进来会把清单淹掉。"""
    feed([
        _call(0, "Read", {"file_path": "/w/a.py"}),
        _call(1, "Grep", {"pattern": "x"}),
        _call(2, "Bash", {"command": "cat a.py"}),
        _call(3, "glob", {"pattern": "*.py"}),
    ])

    assert session_files("sid-1") == []


def test_a_write_without_a_path_is_skipped(feed):
    """``Write`` 没带路径、路径是空串、或参数根本不是字典，一律不放进来。"""
    feed([
        _call(0, "Write", {}),
        _call(1, "Write", {"file_path": "   "}),
        _call(2, "Write", None),
    ])

    assert session_files("sid-1") == []


def test_only_tool_calls_are_read(feed):
    """agent 说的话里提到路径不算动过文件。"""
    said = UnifiedRecord(
        id="r9", session_id="sid-1", group_id=None, seq=0, ts=0,
        kind="agent.say", payload={"text": "I changed /w/a.py"},
    )
    feed([said])

    assert session_files("sid-1") == []


def test_the_list_follows_the_order_of_first_touch(feed):
    feed([
        _call(4, "Edit", {"file_path": "/w/b.py"}),
        _call(8, "Edit", {"file_path": "/w/a.py"}),
        _call(9, "Edit", {"file_path": "/w/b.py"}),
    ])

    assert [f.path for f in session_files("sid-1")] == ["/w/b.py", "/w/a.py"]


def test_a_session_that_touched_nothing_is_empty(feed):
    feed([])

    assert session_files("sid-1") == []


# ---------- 临时区：被这场会话创建过，但不是「在我项目里改了什么」 ----------


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/a.py",
        "/private/tmp/a.py",
        "/var/tmp/a.py",
        "/var/folders/5x/hsq599m139v8n8p7d65bp3r40000gp/T/opencode/a.py",
        "/private/var/folders/5x/hsq599m139v8n8p7d65bp3r40000gp/T/x.py",
        "/private/tmp/claude-502/-Users-frago/sid/scratchpad/probe.sh",
    ],
)
def test_temp_roots_are_scratch(path):
    assert is_scratch_path(path) is True


def test_opencode_tool_output_is_scratch():
    assert is_scratch_path(str(Path.home() / ".local/share/opencode/tool-output/tool_abc")) is True


@pytest.mark.parametrize(
    "path",
    [
        "/Users/frago/Repos/frago/src/frago/session/session_files.py",
        "/Users/frago/Repos/frago/tmp/a.py",          # 项目里自己叫 tmp 的子目录是人自己的东西
        "/Users/frago/Repos/frago/.tmp/notes.md",
        "/tmpfoo/a.py",                                # 名字带 tmp，但不是临时区的根
        "/Users/frago/.frago/data/writing/20261010-doc-language-skill/SKILL.md",
        str(Path.home() / ".local/share/opencode/tool-output-2/keep.txt"),   # 临时区的邻居
        "",
    ],
)
def test_ordinary_paths_are_kept(path):
    assert is_scratch_path(path) is False


def test_scratch_files_never_reach_the_list(feed):
    """一场会话同时动了项目和临时文件时，清单里只剩项目那几个。"""
    feed([
        _call(0, "Write", {"file_path": "/tmp/probe.py"}),
        _call(1, "Write", {"file_path": "/Users/frago/Repos/frago/a.py"}),
        _call(2, "write", {"filePath": "/var/folders/5x/hsq/T/opencode/out.json"}),
        _call(3, "Edit", {"file_path": "/Users/frago/Repos/frago/b.py"}),
    ])

    assert [f.path for f in session_files("sid-1")] == [
        "/Users/frago/Repos/frago/a.py",
        "/Users/frago/Repos/frago/b.py",
    ]


# ---------- codex：一次补丁改一批，路径在补丁头那几行上 ----------


def _patch(seq: int, text: str) -> UnifiedRecord:
    """codex 的写改那一下。它带的是补丁正文，不是一个字段一个值的参数字典。"""
    return _call(seq, "apply_patch", {"input": text})


def _state(seq: int, cwd: str) -> UnifiedRecord:
    return UnifiedRecord(
        id=f"s{seq}",
        session_id="sid-1",
        group_id=None,
        seq=seq,
        ts=1_700_000_000_000 + seq,
        kind="session.state",
        payload={"cwd": cwd},
    )


def test_a_patch_marks_each_file_new_changed_or_deleted(feed):
    """补丁头写着什么就是什么：新建／改／删各一枚标，一次补丁里的几个文件各算各的。"""
    feed([
        _patch(
            0,
            "*** Begin Patch\n"
            "*** Add File: a.py\n"
            "+x = 1\n"
            "*** Update File: b.py\n"
            "@@\n-old\n+new\n"
            "*** Delete File: c.py\n"
            "*** End Patch\n",
        )
    ])

    assert [(f.path, f.action) for f in session_files("sid-1")] == [
        ("a.py", "created"),
        ("b.py", "modified"),
        ("c.py", "deleted"),
    ]


def test_patch_paths_are_resolved_against_the_session_cwd(feed):
    """补丁里写的是相对路径，按这场会话的工作目录拼全——不然清单里的路径点不开。"""
    feed([
        _state(0, "/Users/frago/Repos/frago"),
        _patch(1, "*** Update File: src/a.py\n*** Delete File: docs/gone.md\n"),
    ])

    assert [f.path for f in session_files("sid-1")] == [
        "/Users/frago/Repos/frago/src/a.py",
        "/Users/frago/Repos/frago/docs/gone.md",
    ]


def test_without_a_cwd_the_path_is_kept_as_the_patch_wrote_it(feed):
    """这一场没留下工作目录时照实留着——清单记的是它动过什么，能不能打开是另一层的事。"""
    feed([_patch(0, "*** Update File: src/a.py\n")])

    assert [f.path for f in session_files("sid-1")] == ["src/a.py"]


def test_an_absolute_patch_path_is_left_alone(feed):
    feed([
        _state(0, "/Users/frago/Repos/frago"),
        _patch(1, "*** Update File: /Users/frago/Repos/other/a.py\n"),
    ])

    assert [f.path for f in session_files("sid-1")] == ["/Users/frago/Repos/other/a.py"]


def test_a_path_that_only_appears_inside_the_patch_body_is_not_counted(feed):
    """正文里提到「*** Add File: …」的那一行不算动过它——只有顶格那几行是补丁头。

    笔记里、示例里、被删掉的那一行里都可能写着这句话；照它算，别人的文件就记到这一场头上了。
    """
    feed([
        _patch(
            0,
            "*** Begin Patch\n"
            "*** Update File: notes.md\n"
            "@@\n"
            "+*** Add File: pretend.py\n"      # 被写进正文的一行，不是补丁头
            "-*** Add File: also-not-real.py\n"
            " *** Add File: indented.py\n"    # 顶格才是头，缩进的不算
            "*** End Patch\n",
        )
    ])

    assert [(f.path, f.action) for f in session_files("sid-1")] == [("notes.md", "modified")]


def test_a_move_is_ignored_but_the_update_line_still_counts(feed):
    """改名那行不放进来（改名前那个路径已经没有东西了），改这一下照旧算在它头上。"""
    feed([
        _patch(0, "*** Update File: old-name.md\n*** Move to: new-name.md\n@@\n-a\n+b\n"),
    ])

    assert [(f.path, f.action) for f in session_files("sid-1")] == [
        ("old-name.md", "modified"),
    ]


def test_a_patch_without_text_is_skipped(feed):
    feed([_call(0, "apply_patch", {}), _call(1, "apply_patch", {"input": None})])

    assert session_files("sid-1") == []


def test_a_patch_over_a_scratch_file_is_filtered_like_any_other(feed):
    """补丁开出来的临时文件与别的工具开出来的一样滤掉。"""
    feed([
        _patch(
            0,
            "*** Add File: /tmp/probe.py\n"
            "*** Add File: /Users/frago/Repos/frago/keep.py\n",
        )
    ])

    assert [f.path for f in session_files("sid-1")] == ["/Users/frago/Repos/frago/keep.py"]


# ---------- 最后那一下说了算 ----------
#
# 一场会话常把「整份换掉」记成先删、紧接着再新建（本机实测两下相隔 10 秒）。只看第一下会
# 把这些文件全报成「已删除」，而它们好好地在磁盘上——2026-10-10 在真界面上撞见的。


def test_a_file_deleted_then_re_added_is_not_deleted(feed):
    """先删后建：最后一动是写，文件还在。"""
    feed([
        _patch(0, "*** Begin Patch\n*** Delete File: README.md\n*** End Patch\n"),
        _patch(1, "*** Begin Patch\n*** Add File: README.md\n+hello\n*** End Patch\n"),
        _patch(2, "*** Begin Patch\n*** Update File: README.md\n@@\n+more\n*** End Patch\n"),
    ])

    [only] = session_files("sid-1")

    assert (only.action, only.count) == ("modified", 3)


def test_a_file_written_then_deleted_is_deleted(feed):
    feed([
        _call(0, "Edit", {"file_path": "/w/a.py"}),
        _patch(1, "*** Delete File: /w/a.py\n"),
    ])

    [only] = session_files("sid-1")

    assert only.action == "deleted"


def test_a_file_created_then_deleted_is_deleted(feed):
    feed([
        _call(0, "Write", {"file_path": "/w/a.py"}),
        _patch(1, "*** Delete File: /w/a.py\n"),
    ])

    [only] = session_files("sid-1")

    assert only.action == "deleted"


def test_a_file_deleted_then_re_added_then_deleted_again_is_deleted(feed):
    feed([
        _patch(0, "*** Delete File: a.py\n*** Add File: a.py\n+x\n"),
        _patch(1, "*** Delete File: a.py\n"),
    ])

    [only] = session_files("sid-1")

    assert only.action == "deleted"


def test_a_file_created_then_deleted_then_created_again_is_still_new(feed):
    """这一场从零建起来的东西，中间被它自己删过一次，最后还是它建的，算新建。"""
    feed([
        _call(0, "Write", {"file_path": "/w/a.py"}),
        _patch(1, "*** Delete File: /w/a.py\n"),
        _patch(2, "*** Add File: /w/a.py\n+x\n"),
    ])

    [only] = session_files("sid-1")

    assert (only.action, only.count) == ("created", 3)


def test_deleting_a_path_before_ever_writing_it_makes_it_changed_not_new(feed):
    """删得掉，说明它本来就在：先删后改的那些不算这场会话新建的。"""
    feed([
        _patch(0, "*** Delete File: docs/examples.zh-CN.md\n*** End Patch\n"),
        _patch(1, "*** Add File: docs/examples.zh-CN.md\n+rewritten\n*** End Patch\n"),
    ])

    [only] = session_files("sid-1")

    assert only.action == "modified"
