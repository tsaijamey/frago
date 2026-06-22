"""Phase 1/3 单测：resolve_backend() 解析优先级 + PA 本体接常驻 tmux。

Phase 1: config.json primary_agent.agent_backend > env FRAGO_AGENT_DRIVER=tmux > 默认 tmux。
Phase 3: PaTmuxRunner 会话复用 / bootstrap 注入语义、tmux 输出走 _handle_pa_output 路由、
rotation 驱逐 resident 会话且不碰 claude-p 子进程机制。
"""

from __future__ import annotations

import asyncio
import json

import frago.server.services.primary_agent_service as pa_mod
from frago.agent_driver.tmux_session import TurnResult
from frago.server.services.agent_service import resolve_backend
from frago.server.services.pa_tmux_runner import PaTmuxRunner
from frago.server.services.primary_agent_service import PrimaryAgentService


def test_default_is_tmux(monkeypatch, tmp_path):
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", tmp_path / "config.json")
    assert resolve_backend() == "tmux"


def test_config_overrides_to_claude_p(monkeypatch, tmp_path):
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"primary_agent": {"agent_backend": "claude-p"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    assert resolve_backend() == "claude-p"


def test_env_tmux_takes_effect(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAGO_AGENT_DRIVER", "tmux")
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", tmp_path / "config.json")
    assert resolve_backend() == "tmux"


# ── Phase 3 helpers ──────────────────────────────────────────────────────────


class FakePool:
    """A WarmSessionPool stand-in recording runs and tracking live session keys."""

    def __init__(self) -> None:
        self.live: set[str] = set()
        self.runs: list[tuple[str, str]] = []   # (session_id, prompt)
        self.evicted: list[str] = []
        self.reply_text = "[]"

    def has(self, session_id: str) -> bool:
        return session_id in self.live

    def run(self, prompt, *, agent_type, session_id, cwd, timeout_s=120.0, resume_hook=None):  # noqa: ARG002
        self.runs.append((session_id, prompt))
        self.live.add(session_id)
        return TurnResult(text=self.reply_text, raw_delta="", status="ok", duration_ms=1)

    def evict(self, session_id: str) -> bool:
        self.evicted.append(session_id)
        existed = session_id in self.live
        self.live.discard(session_id)
        return existed

    def shutdown(self) -> None:
        self.live.clear()


def _fresh_pa() -> PrimaryAgentService:
    svc = PrimaryAgentService.__new__(PrimaryAgentService)
    svc.__init__()
    return svc


# ── Phase 3 tests ────────────────────────────────────────────────────────────


def test_runner_reuses_session_and_injects_bootstrap_once():
    """同一 session_key 连发两条：首轮 bootstrap 独立一轮 + 消息一轮，次轮只发 prompt、复用同一会话。"""
    pool = FakePool()
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")

    runner.run("thread-A", "msg-1", bootstrap="BOOT")
    runner.run("thread-A", "msg-2", bootstrap="BOOT")

    assert [sid for sid, _ in pool.runs] == ["thread-A", "thread-A", "thread-A"]
    # 首轮：bootstrap 作为独立一轮先注入，再发 msg-1；次轮只发 msg-2（会话已暖，不重注入）。
    assert pool.runs[0][1] == "BOOT"
    assert pool.runs[1][1] == "msg-1"
    assert pool.runs[2][1] == "msg-2"


def test_runner_fallback_key_when_no_thread():
    pool = FakePool()
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    runner.run(None, "msg", bootstrap="BOOT")
    assert pool.runs[0][0] == PaTmuxRunner.FALLBACK_KEY


def test_runner_evict_rebuilds_with_bootstrap():
    """evict 后下一轮 run 重新注入 bootstrap（会话已不在）。"""
    pool = FakePool()
    runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    runner.run("thread-A", "msg-1", bootstrap="BOOT")  # runs: BOOT, msg-1
    assert runner.evict("thread-A") is True
    runner.run("thread-A", "msg-2", bootstrap="BOOT")  # 会话已驱逐 → 重注入: BOOT, msg-2
    assert pool.runs[2][1] == "BOOT"
    assert pool.runs[3][1] == "msg-2"
    assert pool.evicted == ["thread-A"]


def test_tmux_output_routes_through_handle_pa_output(monkeypatch):
    """tmux 返回的决策 JSON 喂进 _handle_pa_output（同一条输出处理路径）。"""
    svc = _fresh_pa()
    pool = FakePool()
    pool.reply_text = '[{"action": "reply", "task_id": "t1", "text": "hi"}]'
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")

    # bootstrap 构建走真实路径成本高且依赖 board；mock 成轻量返回。
    monkeypatch.setattr(svc, "_build_bootstrap_prompt", lambda **kw: ("BOOT", "route"))  # noqa: ARG005

    captured: list[str] = []

    async def _capture(text):
        captured.append(text)

    monkeypatch.setattr(svc, "_handle_pa_output", _capture)

    group = [{"type": "user_message", "prompt": "yo", "thread_id": "thread-A"}]
    asyncio.run(svc._dispatch_group_tmux("thread-A", group))

    assert captured == ['[{"action": "reply", "task_id": "t1", "text": "hi"}]']
    # 同一 thread 复用同一 session_key。
    assert pool.runs[0][0] == "thread-A"


def test_rotation_evicts_resident_session_and_resets_counter(monkeypatch):
    """token 超阈值触发 rotation → evict 该 key 且不碰 claude-p _create_pa_session。"""
    svc = _fresh_pa()
    pool = FakePool()
    pool.live.add("thread-A")  # 假装会话已活
    svc._pa_tmux_runner = PaTmuxRunner(pool=pool, cwd="/tmp")
    svc._accumulated_tokens["thread-A"] = pa_mod.ROTATION_TOKEN_THRESHOLD + 1
    svc._rotation_count["thread-A"] = 2

    # _create_pa_session 是 claude-p 机制，rotation 走 tmux 路径绝不能调它。
    def _boom(*a, **k):  # noqa: ARG001
        raise AssertionError("tmux rotation must NOT create a claude-p session")

    monkeypatch.setattr(svc, "_create_pa_session", _boom)

    asyncio.run(svc._rotate_tmux_session("thread-A"))

    assert pool.evicted == ["thread-A"]
    assert svc._accumulated_tokens["thread-A"] == 0
    assert svc._rotation_count["thread-A"] == 3


def test_rotate_session_dispatches_to_tmux_when_backend_tmux(monkeypatch, tmp_path):
    """backend==tmux 时 rotate_session 路由到 _rotate_tmux_session（不动 AgentSession）。"""
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", tmp_path / "config.json")  # 默认 tmux
    svc = _fresh_pa()

    called: list[str | None] = []

    async def _rot(tid=None):
        called.append(tid)

    monkeypatch.setattr(svc, "_rotate_tmux_session", _rot)

    asyncio.run(svc.rotate_session(thread_id="thread-A"))
    assert called == ["thread-A"]
