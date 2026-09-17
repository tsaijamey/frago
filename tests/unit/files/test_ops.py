"""The three verbs: unix's meanings, and the place this deliberately differs.

The difference is what most of this file pins down — nothing here destroys
anything, a replaced file and a deleted one both land in this machine's trash —
because it is the part a reader would otherwise have to take on trust.
"""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from frago.files import ops


def _trash_dir(home: Path) -> Path:
    if platform.system() == "Darwin":
        return home / ".Trash"
    return home / ".local" / "share" / "Trash" / "files"


# ── cp ─────────────────────────────────────────────────────────────────────


def test_cp_copies_a_file(work: Path) -> None:
    (work / "a.txt").write_text("hello")
    report = ops.copy([work / "a.txt"], work / "b.txt")
    assert report.ok
    assert (work / "b.txt").read_text() == "hello"
    assert (work / "a.txt").exists()


def test_cp_into_an_existing_directory_keeps_the_name(work: Path) -> None:
    (work / "a.txt").write_text("hello")
    (work / "box").mkdir()
    report = ops.copy([work / "a.txt"], work / "box")
    assert report.ok
    assert (work / "box" / "a.txt").read_text() == "hello"


def test_cp_refuses_a_directory_without_r(work: Path) -> None:
    (work / "tree").mkdir()
    report = ops.copy([work / "tree"], work / "copy")
    assert not report.ok
    assert "-r" in report.failed[0].why


def test_cp_r_copies_a_tree(work: Path) -> None:
    (work / "tree" / "inner").mkdir(parents=True)
    (work / "tree" / "inner" / "x.txt").write_text("deep")
    report = ops.copy([work / "tree"], work / "copy", recursive=True)
    assert report.ok
    assert (work / "copy" / "inner" / "x.txt").read_text() == "deep"


def test_cp_replacing_a_file_keeps_the_old_one_in_the_trash(work: Path, home: Path) -> None:
    (work / "new.txt").write_text("new")
    (work / "old.txt").write_text("precious")
    report = ops.copy([work / "new.txt"], work / "old.txt")
    assert report.ok
    assert (work / "old.txt").read_text() == "new"
    replaced = report.done[0].replaced
    assert replaced is not None
    assert Path(replaced["trash_path"]).read_text() == "precious"


def test_cp_no_clobber_leaves_the_destination_alone(work: Path) -> None:
    (work / "new.txt").write_text("new")
    (work / "old.txt").write_text("precious")
    report = ops.copy([work / "new.txt"], work / "old.txt", no_clobber=True)
    assert report.ok
    assert (work / "old.txt").read_text() == "precious"
    assert report.done[0].verb == "skipped"


def test_cp_several_sources_need_an_existing_directory(work: Path) -> None:
    (work / "a.txt").write_text("a")
    (work / "b.txt").write_text("b")
    report = ops.copy([work / "a.txt", work / "b.txt"], work / "nowhere")
    assert not report.ok
    assert len(report.failed) == 2


def test_cp_keeps_going_after_one_source_fails(work: Path) -> None:
    (work / "there.txt").write_text("a")
    (work / "box").mkdir()
    report = ops.copy([work / "missing.txt", work / "there.txt"], work / "box")
    assert not report.ok
    assert (work / "box" / "there.txt").exists()


# ── mv ─────────────────────────────────────────────────────────────────────


def test_mv_renames(work: Path) -> None:
    (work / "draft.md").write_text("text")
    report = ops.move([work / "draft.md"], work / "final.md")
    assert report.ok
    assert not (work / "draft.md").exists()
    assert (work / "final.md").read_text() == "text"


def test_mv_into_an_existing_directory(work: Path) -> None:
    (work / "a.txt").write_text("a")
    (work / "box").mkdir()
    report = ops.move([work / "a.txt"], work / "box")
    assert report.ok
    assert (work / "box" / "a.txt").exists()


def test_mv_moves_a_tree_without_any_flag(work: Path) -> None:
    (work / "tree" / "inner").mkdir(parents=True)
    (work / "tree" / "inner" / "x.txt").write_text("deep")
    report = ops.move([work / "tree"], work / "moved")
    assert report.ok
    assert (work / "moved" / "inner" / "x.txt").read_text() == "deep"


def test_mv_replacing_a_file_keeps_the_old_one(work: Path) -> None:
    (work / "new.txt").write_text("new")
    (work / "old.txt").write_text("precious")
    report = ops.move([work / "new.txt"], work / "old.txt")
    assert report.ok
    replaced = report.done[0].replaced
    assert Path(replaced["trash_path"]).read_text() == "precious"


def test_mv_onto_itself_is_refused(work: Path) -> None:
    (work / "a.txt").write_text("a")
    report = ops.move([work / "a.txt"], work / "a.txt")
    assert not report.ok
    assert (work / "a.txt").read_text() == "a"


# ── rm ─────────────────────────────────────────────────────────────────────


def test_rm_moves_into_the_system_trash(work: Path, home: Path) -> None:
    (work / "notes.txt").write_text("keep me")
    report = ops.remove([work / "notes.txt"])
    assert report.ok
    assert not (work / "notes.txt").exists()
    landed = report.done[0].target
    assert landed.parent == _trash_dir(home)
    assert landed.read_text() == "keep me"


def test_rm_refuses_a_directory_without_r(work: Path) -> None:
    (work / "tree").mkdir()
    report = ops.remove([work / "tree"])
    assert not report.ok
    assert (work / "tree").exists()


def test_rm_r_takes_the_whole_tree_as_one_entry(work: Path) -> None:
    (work / "tree" / "inner").mkdir(parents=True)
    (work / "tree" / "inner" / "x.txt").write_text("deep")
    report = ops.remove([work / "tree"], recursive=True)
    assert report.ok
    assert len(report.done) == 1
    assert (report.done[0].target / "inner" / "x.txt").read_text() == "deep"


def test_rm_on_a_missing_path_fails_unless_forced(work: Path) -> None:
    assert not ops.remove([work / "ghost.txt"]).ok
    assert ops.remove([work / "ghost.txt"], force=True).ok


def test_rm_refuses_the_home_directory(home: Path) -> None:
    report = ops.remove([home], recursive=True)
    assert not report.ok
    assert home.exists()


def test_two_files_of_the_same_name_do_not_overwrite_each_other_in_the_trash(
    work: Path, home: Path
) -> None:
    (work / "a").mkdir()
    (work / "b").mkdir()
    (work / "a" / "same.txt").write_text("first")
    (work / "b" / "same.txt").write_text("second")
    first = ops.remove([work / "a" / "same.txt"])
    second = ops.remove([work / "b" / "same.txt"])
    assert first.ok and second.ok
    assert first.done[0].target != second.done[0].target
    assert first.done[0].target.read_text() == "first"
    assert second.done[0].target.read_text() == "second"


# ── 这一层不承诺替人放回去 ──────────────────────────────────────────────


def test_rm_does_not_offer_to_put_anything_back(work: Path) -> None:
    """删除的回执里不许出现「能撤销」的意思。

    垃圾桶是人自己随时会清空的，frago 没有任何办法保证那里面还有东西。一句
    「可以放回去」在它不成立的那天之前，看上去都像一条能走的回头路。
    """
    (work / "notes.txt").write_text("keep me")
    report = ops.remove([work / "notes.txt"])
    assert report.ok
    printed = str(report.as_dict())
    for promise in ("撤销", "放回", "账目", "undo", "restore"):
        assert promise not in printed


@pytest.mark.skipif(platform.system() == "Windows", reason="no freedesktop trash there")
def test_linux_layout_writes_a_trashinfo_the_desktop_can_read(
    work: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The note is what the file manager's own "Restore" reads — the one thing
    that still knows where the item came from once it is in the trash."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    (work / "notes.txt").write_text("x")
    report = ops.remove([work / "notes.txt"])
    assert report.ok, report.failed
    landed = report.done[0].target
    assert landed.parent == home / ".local" / "share" / "Trash" / "files"
    note = home / ".local" / "share" / "Trash" / "info" / f"{landed.name}.trashinfo"
    assert "[Trash Info]" in note.read_text()
    assert str(work / "notes.txt") in note.read_text()
