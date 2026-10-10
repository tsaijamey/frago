"""「改动之前」那一侧从哪来，以及两边怎么对齐。

这一层只做两件事：去 git 里取这个路径的上一版（取不到要说清是哪一种取不到），以及把两边
对齐成一行一格。所以这里钉的是**分寸**：仓库里的读到的是以前那版、还没提交的算新建、
不在仓库里的不算新建、太大的不当成新建；对齐那几条钉的是同一处得摆在同一行上。
"""

from __future__ import annotations

import subprocess

import pytest

from frago.server.services import file_history
from frago.server.services.file_history import added_rows, before_at_head, diff_rows

MAX = 512 * 1024


def _git(cwd, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path):
    """一个真的 git 仓库，里面已经有一版 a.py。"""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "first")
    return tmp_path


# ---------- 上一版从 git 来 ----------


def test_it_reads_the_committed_version(repo):
    """仓库里这一份：交回 HEAD 里那一版，并说清来源。"""
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")

    before = before_at_head(str(repo / "a.py"), max_bytes=MAX)

    assert before.text == "x = 1\n"
    assert before.reason is None
    assert before.source == file_history.GIT_SOURCE


def test_a_file_deeper_in_the_tree_is_read_by_its_repo_relative_path(repo):
    """`git show` 认的是仓库内的位置：嵌套目录要按仓库根算相对路径。"""
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    (nested / "b.py").write_text("old\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add b")
    (nested / "b.py").write_text("new\n", encoding="utf-8")

    before = before_at_head(str(nested / "b.py"), max_bytes=MAX)

    assert before.text == "old\n"


def test_a_file_the_repo_never_saw_is_new(repo):
    """HEAD 里没有这个路径：这一场新建的，左边那一侧就是没有。"""
    fresh = repo / "brand-new.py"
    fresh.write_text("hi\n", encoding="utf-8")

    before = before_at_head(str(fresh), max_bytes=MAX)

    assert before.text is None
    assert before.reason == file_history.NO_BEFORE_NEW


def test_a_file_outside_any_repo_is_not_new(tmp_path):
    """不在仓库里：**不许当成新建的**，那是两回事（产物常常写在 ~/.frago/data 下）。"""
    outside = tmp_path / "report.md"
    outside.write_text("# r\n", encoding="utf-8")

    before = before_at_head(str(outside), max_bytes=MAX)

    assert before.text is None
    assert before.reason == file_history.NO_BEFORE_NOT_GIT


def test_a_huge_earlier_version_is_not_called_new(repo, monkeypatch):
    """上一版太大：说「太大」，NEVER 拿「新建」顶替。"""
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")

    before = before_at_head(str(repo / "a.py"), max_bytes=2)

    assert before.text is None
    assert before.reason == file_history.NO_BEFORE_TOO_LARGE


# ---------- 两边对齐 ----------


def _texts(rows):
    """每一行印成「左|右」，方便一眼看出对齐对不对。"""
    def cell(c):
        return "·" if c is None else f"{c['sign']}{c['no']}:{c['text']}"

    return [f"{cell(left)}|{cell(right)}" for left, right in rows]


def test_a_changed_line_is_one_row_carrying_both_sides():
    """改一行：删的那行与增的那行摆在**同一行**上——左右对照靠的就是这个。"""
    rows = diff_rows("a\nb\nc\n", "a\nB\nc\n")

    assert _texts(rows) == [
        " 1:a| 1:a",
        "-2:b|+2:B",
        " 3:c| 3:c",
    ]


def test_a_deleted_run_and_an_added_run_pair_up_in_order():
    """删三行、增两行：按先后两两对上，多出来的那一侧留空。"""
    rows = diff_rows("keep\n1\n2\n3\nkeep\n", "keep\nX\nY\nkeep\n")

    assert _texts(rows) == [
        " 1:keep| 1:keep",
        "-2:1|+2:X",
        "-3:2|+3:Y",
        "-4:3|·",
        " 5:keep| 4:keep",
    ]


def test_identical_sides_are_all_unchanged():
    rows = diff_rows("a\nb\n", "a\nb\n")

    assert [left["sign"] for left, _ in rows] == [" ", " "]


def test_a_trailing_newline_alone_is_not_a_change():
    """末尾多一个换行不算改动：行数与编辑器里看到的一致，不为一个空行多摆一格。"""
    rows = diff_rows("a\nb\n", "a\nb")

    assert [left["sign"] for left, _ in rows] == [" ", " "]


def test_everything_is_kept_off_both_sides_of_a_wholly_different_file():
    """两边毫无共同行：一格都不吞，先删光再增，多出来的那侧留空。"""
    rows = diff_rows("a\nb", "c")

    assert _texts(rows) == ["-1:a|+1:c", "-2:b|·"]


def test_a_new_file_is_all_additions_on_the_right():
    rows = added_rows("one\ntwo")

    assert _texts(rows) == ["·|+1:one", "·|+2:two"]
