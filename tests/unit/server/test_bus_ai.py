"""Tests for ``POST /api/bus/ai`` and ``Recipe.ask_ai`` — the recipe model-chat door."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.agent_driver.kernel_backend import KernelTurn
from frago.server.routes import bus

RUNTIME_DIR = str(Path(__file__).resolve().parents[3] / "src" / "frago" / "recipes" / "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

import frago_recipe  # noqa: E402


@pytest.fixture()
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "bus-edges.jsonl"
    monkeypatch.setattr(bus, "edges_path", lambda: path)
    bus._rollup.clear()
    return path


@pytest.fixture()
def client(ledger: Path) -> TestClient:
    app = FastAPI()
    app.include_router(bus.router)
    return TestClient(app)


def test_refuses_undeclared_caller_and_records_edge(client: TestClient, ledger: Path):
    """A recipe that did not set ``ai = True`` gets 403 and an edge in bus-edges.jsonl."""
    resp = client.post(
        "/api/bus/ai",
        json={"prompt": "你好", "caller_ai": False},
        headers={"X-Frago-Recipe": "undeclared_recipe"},
    )
    assert resp.status_code == 403
    assert "ai = True" in resp.json()["detail"]

    edges = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(edges) == 1
    assert edges[0]["caller"] == "undeclared_recipe"
    assert edges[0]["callee"] == "ai"
    assert edges[0]["mode"] == "chat"
    assert edges[0]["allowed"] is False
    assert edges[0]["why"] == "caller-did-not-declare"


def test_declared_caller_runs_chat_turn_and_strips_caller_env(
    client: TestClient, ledger: Path, monkeypatch: pytest.MonkeyPatch
):
    """A declared call runs ``kernel_backend.run_chat_turn``, strips recipe env, and records the edge."""
    monkeypatch.setenv("FRAGO_RECIPE_DATA_DIR", "/tmp/caller-landing-spot")
    monkeypatch.setenv("FRAGO_CURRENT_RUN", "1")
    monkeypatch.setattr(bus, "_resolve_ai_profile_id", lambda: "9e770df9")

    captured: dict = {}

    def fake_chat_turn(prompt_text: str, *, cwd, profile_id=None, timeout_s=None, env=None):
        captured["prompt_text"] = prompt_text
        captured["cwd"] = cwd
        captured["profile_id"] = profile_id
        captured["timeout_s"] = timeout_s
        captured["env"] = env or {}
        return KernelTurn(
            text='{"what_is_it": "测试解读"}',
            status="ok",
            duration_ms=420,
        )

    with patch("frago.agent_driver.kernel_backend.run_chat_turn", side_effect=fake_chat_turn):
        resp = client.post(
            "/api/bus/ai",
            json={
                "prompt": "请输出 JSON",
                "system": "你是解读助手",
                "timeout": 90,
                "caller_ai": True,
            },
            headers={"X-Frago-Recipe": "social_read_card"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert body["text"] == '{"what_is_it": "测试解读"}'
    assert body["duration_ms"] == 420

    assert captured["prompt_text"] == "你是解读助手\n\n请输出 JSON"
    assert captured["profile_id"] == "9e770df9"
    assert captured["timeout_s"] == 90
    assert "FRAGO_RECIPE_DATA_DIR" not in captured["env"]
    assert "FRAGO_CURRENT_RUN" not in captured["env"]

    edges = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(edges) == 1
    assert edges[0]["caller"] == "social_read_card"
    assert edges[0]["callee"] == "ai"
    assert edges[0]["mode"] == "chat"
    assert edges[0]["allowed"] is True
    assert edges[0]["why"] == ""


def test_timeout_and_needs_input_statuses(client: TestClient, ledger: Path):
    """Non-ok statuses from ``KernelTurn`` return ``ok: False`` with structured status."""
    monkeypatch_turn = KernelTurn(text="", status="timeout", duration_ms=120000)
    with patch("frago.agent_driver.kernel_backend.run_chat_turn", return_value=monkeypatch_turn):
        resp = client.post(
            "/api/bus/ai",
            json={"prompt": "你好", "timeout": 30, "caller_ai": True},
            headers={"X-Frago-Recipe": "social_read_card"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "timeout"
    assert "30s" in body["error"]["message"]


def test_recipe_ask_ai_parses_json_and_classifies_failures(monkeypatch: pytest.MonkeyPatch):
    """``Recipe.ask_ai(response_json=True)`` extracts fenced JSON and classifies errors."""

    class SampleRecipe(frago_recipe.Recipe):
        name = "sample_ai_recipe"
        ai = True

        def mode_run(self):
            return {}

    r = SampleRecipe()

    # 1. Valid fenced JSON
    monkeypatch.setattr(
        frago_recipe.Bus,
        "_call",
        lambda self, path, payload, timeout=120: {
            "ok": True,
            "status": "ok",
            "text": "下面是结果：\n```json\n{\"hello\": \"world\"}\n```",
            "duration_ms": 100,
        },
    )
    assert r.ask_ai("give json", response_json=True) == {"hello": "world"}

    # 2. Invalid JSON raises RecipeFailed with kind="deterministic", status="invalid_json"
    monkeypatch.setattr(
        frago_recipe.Bus,
        "_call",
        lambda self, path, payload, timeout=120: {
            "ok": True,
            "status": "ok",
            "text": "这不是 JSON",
            "duration_ms": 100,
        },
    )
    with pytest.raises(frago_recipe.RecipeFailed) as exc_info:
        r.ask_ai("give json", response_json=True)
    assert exc_info.value.detail["kind"] == "deterministic"
    assert exc_info.value.detail["status"] == "invalid_json"

    # 3. Timeout from hub raises RecipeFailed with kind="transient", status="timeout"
    monkeypatch.setattr(
        frago_recipe.Bus,
        "_call",
        lambda self, path, payload, timeout=120: {
            "ok": False,
            "status": "timeout",
            "error": {"code": "ai-timeout", "status": "timeout", "message": "模型超过 60s 没有答完"},
        },
    )
    with pytest.raises(frago_recipe.RecipeFailed) as exc_info2:
        r.ask_ai("give json", response_json=True)
    assert exc_info2.value.detail["kind"] == "transient"
    assert exc_info2.value.detail["status"] == "timeout"
