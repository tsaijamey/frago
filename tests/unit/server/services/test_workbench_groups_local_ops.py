"""「本机管理」那一组：程序自己发起的会话有个固定落点。

盯四件事：

1. 第一场就把组建出来，第二场落进同一个组，不重复建。
2. 人已经把某一场搬到别的组里了，程序不许把它抢回来。
3. 人把组名改了，下一场照样落进同一个组（认的是记号，不是名字）。
4. 这个组不算"这台机器已经有标签了"——算的话，AI 就永远等不到拟第一套标签的时机。
"""

from __future__ import annotations

import pytest

from frago.server.services import workbench_groups as wg


@pytest.fixture(autouse=True)
def own_file(monkeypatch, tmp_path):
    monkeypatch.setattr(wg, "GROUPS_FILE", tmp_path / "groups.json")


def _tag_named(name: str) -> dict[str, str] | None:
    return next((t for t in wg.load()["tags"] if t["name"] == name), None)


def test_第一场建组第二场落进同一个组():
    first = wg.file_under("core_1", wg.LOCAL_OPS_TAG, key=wg.LOCAL_OPS_KEY)
    second = wg.file_under("core_2", wg.LOCAL_OPS_TAG, key=wg.LOCAL_OPS_KEY)
    assert first == second
    state = wg.load()
    assert len([t for t in state["tags"] if t["name"] == wg.LOCAL_OPS_TAG]) == 1
    assert state["sessions"][first] == ["core_1", "core_2"]


def test_人搬走过的那一场程序不抢回来():
    mine = wg.create_tag("我自己的一组")["tags"][0]["id"]
    wg.assign("core_9", mine)
    assert wg.file_under("core_9", wg.LOCAL_OPS_TAG, key=wg.LOCAL_OPS_KEY) is None
    assert wg.load()["sessions"][mine] == ["core_9"]


def test_人改了组名下一场还落进同一个组():
    tag_id = wg.file_under("core_1", wg.LOCAL_OPS_TAG, key=wg.LOCAL_OPS_KEY)
    # 人在页面上把这一组改了名（这里直接改盘上那一份，等价于改名那条接口）。
    state = wg.load()
    for tag in state["tags"]:
        if tag["id"] == tag_id:
            tag["name"] = "机器活儿"
    wg._write(state)

    assert wg.file_under("core_2", wg.LOCAL_OPS_TAG, key=wg.LOCAL_OPS_KEY) == tag_id
    assert _tag_named(wg.LOCAL_OPS_TAG) is None, "NEVER 再建一个原名的新组"
    assert wg.load()["sessions"][tag_id] == ["core_1", "core_2"]


def test_这个组不算这台机器已经有标签了(monkeypatch):
    """AI 从零拟标签只在"一个标签都没有"时做。程序建的这个组第一次跑定时任务就出现，
    把它算进来，这台机器就再也等不到那一次了。"""
    wg.file_under("core_1", wg.LOCAL_OPS_TAG, key=wg.LOCAL_OPS_KEY)

    drafted: list[list[str]] = []

    def draft(pending, _ask):
        drafted.append([c.title for c in pending])
        return ["甲", "乙"]

    monkeypatch.setattr(wg, "_draft_tags", draft)
    # 归组那一步本身不是这条用例要验的：给它一个"这一批谁都不归"的干净回答。
    monkeypatch.setattr(wg, "_assign_batch", lambda *_a, **_k: ({}, []))
    monkeypatch.setattr(wg, "candidates", lambda cards, _state: list(cards))

    class Card:
        session_id = "sess-1"
        title = "一场人自己的会话"
        directory = "/repos/x"
        family = "claude-code"

    wg.run_ai_grouping([Card()], ask=lambda *_a, **_k: "{}")
    assert drafted == [["一场人自己的会话"]], "AI 仍该拟它的第一套标签"
    assert _tag_named("甲") is not None
