"""中继那扇长连接门的接线。

验的是三件事：凭证过不去就挂不上、挂上之后在线表里认得出这一侧、以及对面办完一次
之后这边当场收到一句。**配方那一步在这里是替身**（真正跑一遍的验证见
``tests/unit/server/test_team_presence.py`` 顶部那段说明）——这里只钉接线，不钉配方。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from frago.server.routes import teaming
from frago.server.services.team_presence import TeamPresence


@pytest.fixture(autouse=True)
def _clean_presence():
    TeamPresence.reset_instance()
    yield
    TeamPresence.reset_instance()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(teaming.router, prefix="/api")
    return TestClient(app)


def _as_side(side: str | None):
    """替掉「问配方这台机器是哪一侧」那一步。"""

    async def resolve(code, fingerprint, secret):
        return side

    return resolve


def _recipe_replies(monkeypatch, data: dict):
    """替掉配方：POST 门这一次直接回给它的数据。"""

    def fake_run(_recipe, _params, *_rest, **_kw):
        return {"status": "ok", "data": data}

    monkeypatch.setattr(
        "frago.server.services.recipe_service.RecipeService.run_recipe", fake_run
    )


def test_凭证过不去就挂不上(client, monkeypatch):
    monkeypatch.setattr(teaming, "_live_side", _as_side(None))

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/api/teaming/ws?code=CODE123456&fingerprint=fp&secret=nope"
        ) as ws,
    ):
        ws.receive_text()


def test_挂上之后在线表认得出这一侧(client, monkeypatch):
    monkeypatch.setattr(teaming, "_live_side", _as_side("A"))

    with client.websocket_connect(
        "/api/teaming/ws?code=CODE123456&fingerprint=fp&secret=s"
    ):
        assert TeamPresence.get_instance().online_sides("CODE123456") == ["A"]

    # 断开之后要摘干净：留着的话，对面下次动的通知会投给一个没人读的口子。
    assert TeamPresence.get_instance().online_sides("CODE123456") == []


def test_对面推一次这边当场收到(client, monkeypatch):
    monkeypatch.setattr(teaming, "_live_side", _as_side("A"))
    _recipe_replies(monkeypatch, {"stored": 2, "total": 2, "side": "B"})

    with client.websocket_connect(
        "/api/teaming/ws?code=CODE123456&fingerprint=fp&secret=s"
    ) as ws:
        got = client.post(
            "/api/teaming",
            json={
                "action": "push",
                "code": "CODE123456",
                "fingerprint": "peer",
                "secret": "ps",
                "records": [],
            },
        )
        assert got.status_code == 200
        assert ws.receive_json() == {"type": "peer_activity", "action": "push"}


def test_对面投一条消息这边当场收到(client, monkeypatch):
    monkeypatch.setattr(teaming, "_live_side", _as_side("A"))
    _recipe_replies(monkeypatch, {"message_id": "m-1", "delivered_to": "A"})

    with client.websocket_connect(
        "/api/teaming/ws?code=CODE123456&fingerprint=fp&secret=s"
    ) as ws:
        client.post(
            "/api/teaming",
            json={
                "action": "send",
                "code": "CODE123456",
                "fingerprint": "peer",
                "secret": "ps",
                "text": "在吗",
            },
        )
        assert ws.receive_json() == {"type": "peer_activity", "action": "send"}
