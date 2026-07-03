"""End-to-end tests for the token calendar API endpoint.

用 FastAPI TestClient 挂真实 router，monkeypatch 掉 CLAUDE_PROJECTS_DIR 与
DEFAULT_CACHE_PATH 指向 tmp_path。GET 同步返回（服务端在 worker 线程里增量
计算），不涉及后台 job 与轮询。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.server.routes import claude_sessions as routes
from frago.session import token_calendar as tcal

TS = "2026-07-01T12:00:00.000Z"
TS2 = "2026-07-03T12:00:00.000Z"


def _local_day(iso_utc: str) -> str:
    return (
        datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        .astimezone()
        .strftime("%Y-%m-%d")
    )


def _assistant(ts: str, msg_id: str, tokens: int) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "id": msg_id,
            "usage": {
                "input_tokens": tokens,
                "output_tokens": tokens,
                "cache_creation_input_tokens": tokens,
                "cache_read_input_tokens": tokens,
            },
        },
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    proj = tmp_path / "projects" / "proj"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                _assistant(TS, "m1", 10),
                _assistant(TS2, "m2", 20),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tcal, "CLAUDE_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(tcal, "DEFAULT_CACHE_PATH", tmp_path / "cache.json")

    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


class TestTokenCalendarApi:
    def test_get_returns_month_aggregation(self, client):
        d1, d2 = _local_day(TS), _local_day(TS2)
        month = d1[:7]
        resp = client.get(f"/api/claude-sessions/token-calendar?month={month}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["month"] == month
        assert data["days"][d1] == {
            "input": 10, "output": 10, "cache_creation": 10, "cache_read": 10,
            "total": 40,
        }
        expected_total = 40 + (80 if d2[:7] == month else 0)
        assert data["month_total"]["total"] == expected_total
        assert data["computed_at"] is not None

    def test_second_get_cache_hit_same_result(self, client, tmp_path):
        month = _local_day(TS)[:7]
        first = client.get(f"/api/claude-sessions/token-calendar?month={month}").json()
        assert (tmp_path / "cache.json").exists()
        second = client.get(f"/api/claude-sessions/token-calendar?month={month}").json()
        assert second["days"] == first["days"]
        assert second["month_total"] == first["month_total"]

    def test_month_without_data_is_empty(self, client):
        resp = client.get("/api/claude-sessions/token-calendar?month=1999-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days"] == {}
        assert data["month_total"]["total"] == 0

    @pytest.mark.parametrize("month", ["2026-13", "202607", "2026-7", "abc", "2026-00"])
    def test_invalid_month_is_400(self, client, month):
        resp = client.get(
            "/api/claude-sessions/token-calendar", params={"month": month}
        )
        assert resp.status_code == 400
