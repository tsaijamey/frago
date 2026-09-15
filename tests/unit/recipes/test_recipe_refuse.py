"""配方基类的「拒绝」出口与页面地址。

拒绝不是失败：配方看过之后说不，结果照常返回。约定是结果里写 `refused`（原因代号）
和 `message`（给人看的话）；带上 `page` 就给出人去处理的页面地址，平台据此在 WebUI
里打开。页面地址由基类给，配方不自己拼。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parents[3] / "src" / "frago" / "recipes" / "runtime"
sys.path.insert(0, str(RUNTIME))

from frago_recipe import BUS_ENV, Recipe  # noqa: E402


class _Demo(Recipe):
    name = "demo_recipe"

    def mode_run(self):
        return {}


@pytest.fixture(autouse=True)
def bus(monkeypatch):
    monkeypatch.setenv(BUS_ENV, "http://127.0.0.1:8093/")


def test_page_url_short_and_with_slot() -> None:
    me = _Demo()
    assert me.page_url() == "http://127.0.0.1:8093/app/demo_recipe"
    assert me.page_url("r 1") == "http://127.0.0.1:8093/app/demo_recipe?key=r%201"


def test_refuse_without_page_is_just_the_reason() -> None:
    out = _Demo().refuse("no_data", "今天的数据还没到", day="2026-09-15")
    assert out == {"refused": "no_data", "message": "今天的数据还没到", "day": "2026-09-15"}


def test_refuse_with_a_slot_hands_over_that_page() -> None:
    out = _Demo().refuse("open_session", "还有一局没打完", page="r1", session_id="r1")
    assert out["refused"] == "open_session"
    assert out["session_id"] == "r1"
    assert out["url"] == out["open_url"] == "http://127.0.0.1:8093/app/demo_recipe?key=r1"


def test_refuse_with_page_true_hands_over_the_short_address() -> None:
    out = _Demo().refuse("no_cash", "账户没钱了", page=True)
    assert out["open_url"] == "http://127.0.0.1:8093/app/demo_recipe"


def test_open_false_keeps_the_address_but_asks_nothing_to_open() -> None:
    out = _Demo({"open": False}).refuse("no_cash", "账户没钱了", page=True)
    assert out["url"] == "http://127.0.0.1:8093/app/demo_recipe"
    assert "open_url" not in out
