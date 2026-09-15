"""配方页面开在 WebUI 里。

两件事：认得出哪些地址是本机的配方页面（只有它们改道进 WebUI，别的照旧交给浏览器）；
服务端问开着的 WebUI 时，只有界面真回了话才算送到——旧界面不认这条推送，
算它送到了，人就什么也看不见。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.server.routes import recipes as recipes_routes
from frago.viewer.browser import recipe_page_of, webui_url_for


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:8093/app/demo", ("demo", None, "http://localhost:8093")),
        ("http://127.0.0.1:8093/app/demo/", ("demo", None, "http://127.0.0.1:8093")),
        ("http://localhost:8093/app/demo?key=2024", ("demo", "2024", "http://localhost:8093")),
        # 不是本机的、不是配方页面根的、带了 key 以外参数的，一律不改道
        ("http://example.com/app/demo", None),
        ("http://localhost:8093/app/demo/data/x.json", None),
        ("http://localhost:8093/app/demo?userInput=true", None),
        ("http://localhost:8093/viewer/content/abc/index.html", None),
        ("file:///tmp/x.html", None),
        # 虚拟桌面有自己的窗口
        ("http://127.0.0.1:8093/app/agent_os", None),
    ],
)
def test_recipe_page_of(url, expected) -> None:
    assert recipe_page_of(url) == expected


def test_webui_url_for() -> None:
    assert webui_url_for("http://localhost:8093", "demo", None) == "http://localhost:8093/#/app/demo"
    assert webui_url_for("http://localhost:8093", "demo", "default") == "http://localhost:8093/#/app/demo"
    assert webui_url_for("http://localhost:8093", "demo", "a-1") == "http://localhost:8093/#/app/demo/a-1"


class _FakeManager:
    def __init__(self, connections: int, acks: bool):
        self.connection_count = connections
        self.acks = acks
        self.sent: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.sent.append(message)
        if self.acks:
            request_id = message["data"]["request_id"]
            # 界面收到后回话，走的是另一次请求，这里直接置位同一个事件
            asyncio.get_running_loop().call_soon(recipes_routes._pending_shows[request_id].set)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(recipes_routes, "has_page", lambda name: name == "demo")
    monkeypatch.setattr(recipes_routes, "_SHOW_ACK_TIMEOUT", 0.2)
    app = FastAPI()
    app.include_router(recipes_routes.router, prefix="/api")
    return TestClient(app)


def _use_manager(monkeypatch, manager) -> None:
    monkeypatch.setattr("frago.server.websocket.manager", manager)


def test_delivered_only_when_webui_answers(client, monkeypatch) -> None:
    manager = _FakeManager(connections=1, acks=True)
    _use_manager(monkeypatch, manager)
    r = client.post("/api/recipe-apps/demo/show", json={"slot": "2024"})
    assert r.status_code == 200
    assert r.json() == {"delivered": True}
    assert manager.sent[0]["type"] == "recipe_app_open"
    assert manager.sent[0]["data"]["name"] == "demo"
    assert manager.sent[0]["data"]["slot"] == "2024"
    assert recipes_routes._pending_shows == {}


def test_old_webui_that_never_answers_is_not_delivered(client, monkeypatch) -> None:
    _use_manager(monkeypatch, _FakeManager(connections=1, acks=False))
    r = client.post("/api/recipe-apps/demo/show", json={})
    assert r.json() == {"delivered": False}
    assert recipes_routes._pending_shows == {}


def test_no_webui_open_is_not_delivered(client, monkeypatch) -> None:
    manager = _FakeManager(connections=0, acks=True)
    _use_manager(monkeypatch, manager)
    assert client.post("/api/recipe-apps/demo/show", json={}).json() == {"delivered": False}
    assert manager.sent == []


def test_recipe_without_page_is_404(client, monkeypatch) -> None:
    _use_manager(monkeypatch, _FakeManager(connections=1, acks=True))
    assert client.post("/api/recipe-apps/nopage/show", json={}).status_code == 404


def test_bad_slot_is_400(client, monkeypatch) -> None:
    _use_manager(monkeypatch, _FakeManager(connections=1, acks=True))
    assert client.post("/api/recipe-apps/demo/show", json={"slot": "../x"}).status_code == 400
