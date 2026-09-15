"""跑完之后开不开页面，由平台一处决定。

两种情况不开：访客按的（陌生人不能在主人屏幕上弹窗），和从配方自己页面上按的
（人已经在页面上了，再开一次就是整页重载、WebUI 菜单里每跑一次多一行）。
配方被拒时同样可以要求开页面，规则一样。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from frago.recipes.runner import page_to_open

URL = "http://127.0.0.1:8093/app/demo?key=r1"
OWNER = None
VISITOR = SimpleNamespace(is_visitor=True)


def test_owner_run_from_outside_the_page_opens_it() -> None:
    assert page_to_open("demo", {"open_url": URL}, ctx=OWNER, show_page=True) == URL


def test_refusal_asking_for_its_page_opens_it_too() -> None:
    data = {"refused": "open_session", "message": "还有一局", "open_url": URL}
    assert page_to_open("demo", data, ctx=OWNER, show_page=True) == URL


def test_run_started_from_the_page_does_not_reopen_it() -> None:
    assert page_to_open("demo", {"open_url": URL}, ctx=OWNER, show_page=False) is None


def test_visitor_run_never_opens_a_window() -> None:
    assert page_to_open("demo", {"open_url": URL}, ctx=VISITOR, show_page=True) is None


@pytest.mark.parametrize("data", [None, {}, {"url": URL}, {"open_url": ""}, "text"])
def test_nothing_asked_nothing_opened(data) -> None:
    assert page_to_open("demo", data, ctx=OWNER, show_page=True) is None
