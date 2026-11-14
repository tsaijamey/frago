"""POST /api/workbench/sessions/{sid}/stop 对 CoreAgent 进程内与池外 tmux Worker 的关闭路由单测（P0）。

覆盖四类核心场景（全程替身隔离，不碰宿主真 tmux）：
1. ``core_*`` 在 ``coreagent_runner`` 进程内运行中 -> 直接由 ``coreagent_runner.stop`` 停机返回，不查 tmux；
2. 池外 ``core_*`` Worker（不在 ``coreagent_runner``，但在 ``tmux_sessions_service`` 存活且空闲）
   -> 回退 ``find_for_session`` + ``close_sessions`` 成功关闭 tmux 会话；
3. 池外 ``core_*`` Worker 在 ``tmux`` 中忙碌：``force=False`` 返回 ``busy=True, stopped=False`` 触发二次确认，
   ``force=True`` 强制关闭；
4. ``core_*`` 既不在 ``coreagent_runner`` 也不在 ``tmux`` -> 如实返回 ``alive=False, stopped=False``。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.server.services import coreagent_runner
from frago.server.services import tmux_sessions_service as svc

CORE_SID = "core_7767aabbccddeeff0011223344556677"
TMUX_NAME = f"frago-agent-{CORE_SID}"


@pytest.fixture
def client() -> TestClient:
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def _core_link(*, busy: bool) -> svc.TmuxSessionLink:
    return svc.TmuxSessionLink(
        name=TMUX_NAME,
        label=CORE_SID,
        busy=busy,
        managed=False,
        memory_mb=240,
    )


def test_in_process_running_coreagent_stops_via_runner_without_tmux_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """场景 1：进程内 coreagent_runner 正在运行的会话直接停机返回，不触发 tmux 回退。"""
    tmux_queries: list[str] = []
    monkeypatch.setattr(
        coreagent_runner,
        "stop",
        lambda sid, by="": {"running": True, "stopped": True, "busy": True, "dropped": 2},
    )
    monkeypatch.setattr(
        svc, "find_for_session", lambda sid: tmux_queries.append(sid) or None
    )

    body = client.post(f"/api/workbench/sessions/{CORE_SID}/stop", json={}).json()

    assert body["sid"] == CORE_SID
    assert body["alive"] is True
    assert body["busy"] is True
    assert body["stopped"] is True
    assert body["dropped"] == 2
    assert body["via"] == "coreagent"
    assert body["error"] is None
    assert tmux_queries == []


def test_out_of_pool_idle_coreagent_tmux_worker_falls_back_to_tmux_close(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """场景 2：CLI 拉起的池外 frago-agent-core_* Worker 不在内存字典中时，回退关闭 tmux。"""
    closed_targets: list[list[str]] = []
    monkeypatch.setattr(
        coreagent_runner,
        "stop",
        lambda sid, by="": {"running": False, "stopped": False, "busy": False, "dropped": 1},
    )
    monkeypatch.setattr(
        svc,
        "find_for_session",
        lambda sid: _core_link(busy=False) if sid == CORE_SID else None,
    )

    def _fake_close(names: list[str]) -> list[dict]:
        closed_targets.append(names)
        return [{"name": names[0], "ok": True, "via": "tmux", "error": None}]

    monkeypatch.setattr(svc, "close_sessions", _fake_close)

    body = client.post(f"/api/workbench/sessions/{CORE_SID}/stop", json={}).json()

    assert body["sid"] == CORE_SID
    assert body["alive"] is True
    assert body["busy"] is False
    assert body["stopped"] is True
    assert body["dropped"] == 1
    assert body["name"] == TMUX_NAME
    assert body["via"] == "tmux"
    assert body["error"] is None
    assert closed_targets == [[TMUX_NAME]]


def test_out_of_pool_busy_coreagent_tmux_worker_requires_force_confirmation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """场景 3：池外 core_* Worker 在 tmux 中忙碌时，force=False 先拦截确认，force=True 才强关。"""
    closed_targets: list[list[str]] = []
    monkeypatch.setattr(
        coreagent_runner,
        "stop",
        lambda sid, by="": {"running": False, "stopped": False, "busy": False, "dropped": 0},
    )
    monkeypatch.setattr(
        svc,
        "find_for_session",
        lambda sid: _core_link(busy=True) if sid == CORE_SID else None,
    )
    monkeypatch.setattr(
        svc,
        "close_sessions",
        lambda names: closed_targets.append(names)
        or [{"name": names[0], "ok": True, "via": "tmux", "error": None}],
    )

    first = client.post(
        f"/api/workbench/sessions/{CORE_SID}/stop", json={"force": False}
    ).json()
    assert first["alive"] is True
    assert first["busy"] is True
    assert first["stopped"] is False
    assert first["dropped"] == 0
    assert first["name"] == TMUX_NAME
    assert closed_targets == []

    second = client.post(
        f"/api/workbench/sessions/{CORE_SID}/stop", json={"force": True}
    ).json()
    assert second["alive"] is True
    assert second["busy"] is True
    assert second["stopped"] is True
    assert second["name"] == TMUX_NAME
    assert second["via"] == "tmux"
    assert closed_targets == [[TMUX_NAME]]


def test_coreagent_absent_from_both_runner_and_tmux_reports_not_alive(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """场景 4：既不在 coreagent_runner 也不在 tmux 时，返回 alive=False, stopped=False。"""
    closed_targets: list[list[str]] = []
    monkeypatch.setattr(
        coreagent_runner,
        "stop",
        lambda sid, by="": {"running": False, "stopped": False, "busy": False, "dropped": 0},
    )
    monkeypatch.setattr(svc, "find_for_session", lambda sid: None)
    monkeypatch.setattr(
        svc, "close_sessions", lambda names: closed_targets.append(names) or []
    )

    body = client.post(f"/api/workbench/sessions/{CORE_SID}/stop", json={}).json()

    assert body["sid"] == CORE_SID
    assert body["alive"] is False
    assert body["busy"] is False
    assert body["stopped"] is False
    assert body["dropped"] == 0
    assert body["name"] is None
    assert body["via"] is None
    assert body["error"] is None
    assert closed_targets == []
