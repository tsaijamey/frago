"""配方跑到一半自己要求打开页面时，守的规则跟「跑完给页面地址」一样。

配方直接调「打开页面」走的是总线的 open 入口。这个入口从前什么都不问就去开，
于是绕过了平台对结果里页面地址的两条规则：访客发起的运行会在主人屏幕上弹页面，
从配方自己页面上发起的运行会把人正在看的页面再开一遍。现在按执行编号查这次运行
是谁的、从哪来的，两种都不开。
"""

import pytest
from fastapi.testclient import TestClient

from frago.recipes import context
from frago.recipes import runner as recipe_runner

URL = "http://127.0.0.1:8093/app/demo_recipe"


@pytest.fixture
def opened(monkeypatch):
    calls: list[str] = []

    def fake_open(url):
        calls.append(url)
        return True

    monkeypatch.setattr("frago.viewer.browser.open_url", fake_open)
    return calls


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    for key in context.CONTEXT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    from frago.server.app import create_app

    return TestClient(create_app(), follow_redirects=False, client=("127.0.0.1", 5555))


def _open(client, execution=None):
    headers = {"X-Frago-Recipe": "demo_recipe"}
    if execution:
        headers["X-Frago-Execution"] = execution
    return client.post("/api/bus/open", json={"url": URL}, headers=headers).json()


def test_owner_run_outside_the_page_opens(client, opened):
    assert _open(client).get("ok") is True
    assert opened == [URL]


def test_execution_this_process_never_started_is_the_owner_s(client, opened):
    """命令行起的运行、重启前的运行：没有登记，就按主人在页面外处理。"""
    assert _open(client, "never-seen").get("ok") is True
    assert opened == [URL]


def test_run_started_from_its_page_does_not_reopen(client, opened):
    recipe_runner._remember_page_run("page-exec")
    try:
        body = _open(client, "page-exec")
    finally:
        recipe_runner._forget_run_context("page-exec")
    assert body == {"ok": False, "ignored": True}
    assert opened == []


def test_visitor_run_never_opens_a_page(client, opened):
    ctx = context.InvocationContext(caller=context.VISITOR, slot="0123456789abcdef" * 2)
    recipe_runner._remember_run_context("visitor-exec", ctx)
    try:
        body = _open(client, "visitor-exec")
    finally:
        recipe_runner._forget_run_context("visitor-exec")
    assert body == {"ok": False, "ignored": True}
    assert opened == []


def test_forgetting_the_run_clears_the_page_mark() -> None:
    recipe_runner._remember_page_run("done-exec")
    recipe_runner._forget_run_context("done-exec")
    assert recipe_runner.may_open_page("done-exec") is True
