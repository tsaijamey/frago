"""配方自己那两个目录，在起进程之前就得在那儿。

**不建的后果只在 Linux 上出现，而且一路不报错。** 两个隔离后端对「路径不存在」的
处理不一样：macOS 那边按路径前缀放行，目录在不在都能写；Linux 那边是挂载，挂不上
一个不存在的源就跳过，而 bwrap 为了放别的挂载点会顺手造出它的上级目录——那些上级
在这次运行自己的根上。于是配方 mkdir 成功、写入成功、进程一退全部消失。

2026-09-22 实测过一次：中继配方答「team 建好了，码给你」，下一次调用就找不到这个
team；同一份代码在 macOS 上完全正常。

建目录发生在 :func:`~frago.recipes.isolation.wrap`，不在 ``view_for``——后者只描述
一个视图，而 ``frago recipe validate`` 会拿它去问那些根本不会被启动的配方。
"""

from __future__ import annotations

from pathlib import Path

from frago.recipes import isolation


def _view(tmp_path: Path) -> isolation.View:
    landing = tmp_path / "users" / "someone" / "recipe-data" / "some_recipe"
    own = tmp_path / ".frago" / "recipe-data" / "some_recipe"
    return isolation.View(writable=(landing, own))


def test_描述视图的那一步不碰磁盘(tmp_path, monkeypatch):
    """``frago recipe validate`` 拿它问的是根本不会被启动的配方。

    在这里建目录，等于查一次就在磁盘上留一份东西。
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    isolation.view_for("some_recipe", landing_spot=None, recipe_dir=None)

    assert not (tmp_path / ".frago" / "recipe-data" / "some_recipe").exists()


def test_挂载之前把自己的两个目录建好(tmp_path):
    """挂载要求源存在，所以 Linux 那个后端自己动手。"""
    view = _view(tmp_path)
    for root in view.writable:
        assert not root.exists()

    isolation.Bubblewrap().wrap(["/bin/true"], view, cwd=None)

    for root in view.writable:
        assert root.is_dir(), f"{root} 没建出来，Linux 上写进去的东西会随进程消失"


def test_macOS那边不建目录(tmp_path):
    """按路径前缀放行，目录在不在都能写，所以不必也不该动磁盘。"""
    view = _view(tmp_path)

    isolation.SandboxExec().wrap(["/bin/true"], view, cwd=None)

    for root in view.writable:
        assert not root.exists()


def test_建不出来也不让起进程这件事整个失败(tmp_path, monkeypatch):
    """磁盘满、权限不对时不在这里抛。

    建不成的后果由内核在起进程时报出来，那时的报错带着完整上下文。
    """
    def refuse(*_a, **_k):
        raise PermissionError("只读文件系统")

    monkeypatch.setattr(Path, "mkdir", refuse)

    argv = isolation.Bubblewrap().wrap(["/bin/true"], _view(tmp_path), cwd=None)

    assert argv[0] == "bwrap"
    assert argv[-1] == "/bin/true"
