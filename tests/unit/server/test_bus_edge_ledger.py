"""总线依赖账本记什么、不记什么。

盯的是这本账的用途：它要回答「我改这个模块之前，有没有别人依赖它」，那是关于
哪些调用**存在**的问题，不是每条调用发生过**几次**。一张看板页面每两秒问一次
进度，两天写出 49366 条记录说同样的 56 件事，把仅有的 52 条真正有话要说的记录
（拒绝、失败、返回值里带出绝对路径）埋在 99.89% 的噪音底下。

所以分两档：带 ``why`` 的和被拒的每次都原样写；干干净净成功的调用只在首次见到
时写一次，之后折进计数，一个窗口落一行。用例全程走临时文件，不碰本机真账本。
"""

from __future__ import annotations

import json

import pytest

from frago.server.routes import bus


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """把账本挪到临时文件，并清掉进程内攒着的计数。"""
    path = tmp_path / "bus-edges.jsonl"
    monkeypatch.setattr(bus, "edges_path", lambda: path)
    monkeypatch.setattr(bus, "_rollup", {})

    def read() -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    return read


def test_首次见到的调用当场写下来(ledger):
    bus._record_edge("plan", "engine", "progress", True)

    rows = ledger()
    assert len(rows) == 1
    assert rows[0]["caller"] == "plan"
    assert rows[0]["callee"] == "engine"
    assert rows[0]["times"] == 1


def test_窗口内的重复只攒计数不落盘(ledger):
    for _ in range(500):
        bus._record_edge("plan", "engine", "progress", True)

    # 首次那一条已经写下，剩下 499 次是同一件事，不该各占一行。
    assert len(ledger()) == 1


def test_窗口到点把攒下的次数落成一行(ledger, monkeypatch):
    monkeypatch.setattr(bus, "_ROLLUP_WINDOW_SECONDS", 0)

    for _ in range(4):
        bus._record_edge("plan", "engine", "progress", True)

    rows = ledger()
    # 首次一行 + 之后每次都因为窗口为零而立刻结算
    assert rows[0]["times"] == 1
    assert [r["times"] for r in rows[1:]] == [1, 1, 1]
    assert all("since" in r for r in rows[1:])


def test_不同的边各记各的(ledger):
    for _ in range(50):
        bus._record_edge("plan", "engine", "progress", True)
        bus._record_edge("plan", "feed", "quotes", True)
        bus._record_edge("board", "engine", "progress", True)

    rows = ledger()
    assert len(rows) == 3
    assert {(r["caller"], r["callee"], r["mode"]) for r in rows} == {
        ("plan", "engine", "progress"),
        ("plan", "feed", "quotes"),
        ("board", "engine", "progress"),
    }


def test_被拒绝的调用每一次都原样写下(ledger):
    for _ in range(5):
        bus._record_edge("plan", "engine", "write", False, "mode-not-exported")

    rows = ledger()
    assert len(rows) == 5
    assert all(r["allowed"] is False for r in rows)
    assert all(r["why"] == "mode-not-exported" for r in rows)
    # 拒绝不参与折叠，因此不带次数字段
    assert all("times" not in r for r in rows)


def test_成功但有话要说的也每次都写(ledger):
    """返回值里带出了绝对路径、被调方说不、跑挂了——都不是任何东西的重复。"""
    for _ in range(3):
        bus._record_edge("plan", "feed", "quotes", True, "paths-in-return: cache_dir = '/x'")
    for _ in range(2):
        bus._record_edge("plan", "engine", "progress", True, "callee-said-no")

    rows = ledger()
    assert len(rows) == 5
    assert all(r["why"] for r in rows)


def test_噪音不会把真正有话要说的记录挤掉(ledger):
    """这条用例守的是这次改动的初衷。"""
    for _ in range(2000):
        bus._record_edge("plan", "engine", "progress", True)
    bus._record_edge("stray", "engine", "write", False, "caller-did-not-declare")
    for _ in range(2000):
        bus._record_edge("plan", "engine", "progress", True)

    rows = ledger()
    assert len(rows) == 2
    assert [r for r in rows if not r["allowed"]][0]["why"] == "caller-did-not-declare"


def test_进程退出前把还攒着的计数写下来(ledger):
    for _ in range(10):
        bus._record_edge("plan", "engine", "progress", True)
    assert len(ledger()) == 1

    bus._flush_rollups()

    rows = ledger()
    assert len(rows) == 2
    assert rows[1]["times"] == 9
    assert rows[1]["since"] == rows[0]["when"]


def test_没有攒下东西时退出不写空行(ledger):
    bus._record_edge("plan", "engine", "progress", True)
    bus._flush_rollups()
    bus._flush_rollups()

    assert len(ledger()) == 1


def test_账本写不进去不能连累调用本身(ledger, monkeypatch, tmp_path):
    """记账失败只该留一条警告，NEVER 让配方之间的调用跟着失败。"""
    monkeypatch.setattr(bus, "edges_path", lambda: tmp_path / "没有这个目录" / "x.jsonl")

    def 打不开(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(bus.Path, "mkdir", 打不开)
    bus._record_edge("plan", "engine", "progress", True)  # 不抛就算过
