"""Phase 2 单测：UI 会话空闲回收的判定与巡检。

spec 20260625-webui-session-lifecycle-mediator / Phase 2。验证：
- UiSessionRunner.evict_idle 以 jsonl 终结时间戳算空闲：done 且超阈值 → 回收；
  探针 not done（干活中）→ 跳过。
- UiSessionLifecycleService 巡检从 config 取阈值并交给 runner 回收。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from frago.server.services import transcript_completion as tc
from frago.server.services.transcript_completion import TurnCompletion
from frago.server.services.ui_session_runner import UiSessionRunner


class FakeSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.cwd = "/tmp"
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePool:
    """支持 has + evict_idle（按真实语义应用传入的 idle_age_fn）。"""

    def __init__(self, sessions: list[FakeSession]) -> None:
        self._sessions = {s.session_id: s for s in sessions}

    def has(self, sid: str) -> bool:
        return sid in self._sessions

    def evict_idle(self, idle_age_fn, timeout_s):
        evicted = []
        for sid, sess in list(self._sessions.items()):
            age = idle_age_fn(sess)
            if age is not None and age > timeout_s:
                del self._sessions[sid]
                sess.close()
                evicted.append(sid)
        return evicted


def _completion(done: bool, ts: datetime | None) -> TurnCompletion:
    return TurnCompletion(
        done=done,
        stop_reason="end_turn" if done else "tool_use",
        final_text="",
        request_id=None,
        last_uuid="u",
        pending_tool_use=not done,
        session_id=None,
        source_path=None,
        last_terminal_ts=ts,
    )


def test_evict_idle_reclaims_done_and_old_skips_busy(monkeypatch):
    now = datetime.now(UTC)
    verdicts = {
        # 已说完、静默 2 小时 → 该回收。
        "old-done": _completion(True, now - timedelta(hours=2)),
        # 已说完、刚停 1 分钟 → 不到阈值。
        "fresh-done": _completion(True, now - timedelta(minutes=1)),
        # 仍在干活（not done）→ 永不回收。
        "busy": _completion(False, None),
    }
    pool = FakePool([FakeSession(s) for s in verdicts])

    monkeypatch.setattr(tc, "locate_transcript", lambda sid, **_: f"/{sid}.jsonl")
    monkeypatch.setattr(tc, "evaluate_file", lambda path: verdicts[path.strip("/").removesuffix(".jsonl")])

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    evicted = runner.evict_idle(timeout_s=1800.0)  # 30min

    assert evicted == ["old-done"]
    assert not pool.has("old-done")
    assert pool.has("fresh-done") and pool.has("busy")


def test_evict_idle_skips_when_no_transcript(monkeypatch):
    pool = FakePool([FakeSession("x")])
    monkeypatch.setattr(tc, "locate_transcript", lambda *_a, **_k: None)
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=0.0) == []
    assert pool.has("x")


def test_lifecycle_scan_uses_config_threshold(monkeypatch):
    from frago.server.services import ui_session_lifecycle as life

    calls: list[float] = []

    class StubRunner:
        def evict_idle(self, timeout_s):
            calls.append(timeout_s)
            return []

    class StubCfg:
        class webui_sessions:  # noqa: N801
            idle_timeout_secs = 1234

    monkeypatch.setattr("frago.init.config_manager.load_config", lambda: StubCfg)
    monkeypatch.setattr(
        "frago.server.routes.claude_sessions._get_runner", lambda: StubRunner()
    )

    svc = life.UiSessionLifecycleService(scan_interval_s=0.01)
    asyncio.run(svc._scan_once())

    assert calls == [1234.0]
