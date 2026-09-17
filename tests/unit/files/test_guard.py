"""The targets this layer refuses, and — just as load-bearing — the ones it does not.

Half of these tests exist for the second half of that sentence. A guard that
creeps outward is a guard people work around, so the cases pinning ``/tmp``,
``~/.frago/data`` and an ordinary file open are as much the contract as the
refusals are.
"""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from frago.files.guard import Refused, check


def test_ordinary_file_is_fine(work: Path) -> None:
    target = work / "notes.txt"
    target.write_text("hi")
    assert check(target, verb="删除") == target


def test_scratch_space_is_not_the_operating_system(home: Path) -> None:
    # /tmp deliberately sits outside the system list: it is where half this
    # layer's real work happens.
    assert check(Path("/tmp/frago-guard-probe"), verb="写入")


def test_home_itself_is_refused(home: Path) -> None:
    with pytest.raises(Refused, match="全部"):
        check(home, verb="删除")


def test_root_is_refused(home: Path) -> None:
    with pytest.raises(Refused):
        check(Path("/"), verb="删除")


def test_ancestor_of_home_is_refused(home: Path) -> None:
    with pytest.raises(Refused):
        check(home.parent, verb="删除")


def test_mount_holder_itself_is_refused(home: Path) -> None:
    holder = "/Volumes" if platform.system() == "Darwin" else "/mnt"
    with pytest.raises(Refused, match="挂载点"):
        check(Path(holder), verb="删除")


def test_system_tree_is_refused(home: Path) -> None:
    target = "/usr/local/lib/thing" if platform.system() != "Windows" else r"C:\Windows\x"
    with pytest.raises(Refused, match="操作系统"):
        check(Path(target), verb="删除")


def test_frago_home_is_refused(home: Path) -> None:
    with pytest.raises(Refused, match=r"\.frago"):
        check(home / ".frago" / "bus-edges.jsonl", verb="删除")


def test_work_products_under_frago_home_are_allowed(home: Path) -> None:
    target = home / ".frago" / "data" / "20260916-report" / "out.md"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    assert check(target, verb="删除") == target


def test_trash_is_refused(home: Path) -> None:
    trash = home / ".Trash" if platform.system() == "Darwin" else (
        home / ".local" / "share" / "Trash"
    )
    trash.mkdir(parents=True)
    with pytest.raises(Refused, match="垃圾桶"):
        check(trash / "something", verb="删除")


def test_symlink_is_judged_as_itself_not_as_its_target(work: Path) -> None:
    # `rm link` removes the link. A guard that resolved the last component would
    # refuse this because of where it points, which is not what is being removed.
    link = work / "shortcut"
    link.symlink_to("/usr")
    assert check(link, verb="删除") == link


def test_a_symlinked_parent_cannot_smuggle_a_target_past_the_guard(work: Path) -> None:
    door = work / "door"
    door.symlink_to("/usr")
    with pytest.raises(Refused, match="操作系统"):
        check(door / "lib" / "thing", verb="删除")
