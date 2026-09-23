"""一侧的记录推不上中继时，不能悄无声息。

实际发生过：对话多的那一侧每一批都超了中继的参数上限，中继把失败说成「码不可用」，
本机把推送失败吞掉接着收消息——这一侧照常显示「在」、照常收到消息，只有对方屏幕上
这一侧永远是空的，两个多小时没人看得出原因。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.team import state as team_state
from frago.team import sync
from frago.team.relay import RelayError
from frago.team.state import TeamBinding, TeamState


@pytest.fixture(autouse=True)
def 状态文件(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(team_state, "STATE_PATH", tmp_path / "state.json")


@dataclass
class _Record:
    seq: int
    text: str = field(default="")


def _state() -> tuple[TeamState, TeamBinding]:
    binding = TeamBinding(code="ABCDEFGHJK", session_id="s", side="B", secret="k")
    state = TeamState(member="m")
    state.teams[binding.code] = binding
    return state, binding


def test_一批超了字节上限就切小再推(monkeypatch):
    records = [_Record(seq=i, text="中" * 3000) for i in range(40)]  # 每条约 18KB
    monkeypatch.setattr(sync.record_reader, "read_records", lambda *a, **k: records)
    sent: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(sync, "_call", lambda s, b, action, **p: sent.append(p["records"]) or {})

    state, binding = _state()
    pushed = sync._push_records(state, binding, 60)

    assert len(json.dumps(sent[0]).encode()) <= sync.PUSH_BYTES
    assert 0 < pushed < 40
    # 游标只走到真正送出去的那一条，剩下的下一轮接着推
    assert binding.pushed_seq == sent[0][-1]["seq"]


def test_推不上去的原因落在本机状态里_推成功后清掉(monkeypatch):
    state, binding = _state()
    monkeypatch.setattr(sync, "_call", lambda *a, **k: {"messages": [], "peer_present": True})

    def boom(*a, **k):
        raise RelayError("中继拒绝了 push（HTTP 502）：Argument list too long")

    monkeypatch.setattr(sync, "_push_records", boom)
    outcome = sync.sync_once(state, binding, deliver=lambda _: None)
    assert "Argument list too long" in outcome.note
    assert "Argument list too long" in team_state.load_state().teams[binding.code].push_trouble

    monkeypatch.setattr(sync, "_push_records", lambda *a, **k: 0)
    sync.sync_once(state, binding, deliver=lambda _: None)
    assert team_state.load_state().teams[binding.code].push_trouble == ""


def _door(monkeypatch, result: dict) -> TestClient:
    from frago.server import identity as ident
    from frago.server.routes import teaming
    from frago.server.services.recipe_service import RecipeService

    monkeypatch.setattr(ident, "allow_teaming", lambda _addr: True)
    monkeypatch.setattr(ident, "allow_teaming_code", lambda _code: True)
    monkeypatch.setattr(RecipeService, "run_recipe", staticmethod(lambda *a, **k: result))
    app = FastAPI()
    app.include_router(teaming.router, prefix="/api")
    return TestClient(app)


def test_中继跑失败了不再冒充码不可用(monkeypatch):
    client = _door(monkeypatch, {"status": "error", "error": "Argument list too long"})
    got = client.post("/api/teaming", json={"action": "push", "code": "ABCDEFGHJK"})
    assert got.status_code == 502
    assert got.json()["error"] == "relay_failed"
    assert "Argument list too long" in got.json()["detail"]


def test_码不对仍是那个统一的404(monkeypatch):
    client = _door(monkeypatch, {"status": "ok", "data": {"refused": "这个连接码在这台中继上不可用"}})
    got = client.post("/api/teaming", json={"action": "push", "code": "ABCDEFGHJK"})
    assert got.status_code == 404
