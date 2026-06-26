"""Phase 1 单测：UiSessionRunner 透传纠偏 + 配置缺省自愈。

spec 20260625-webui-session-lifecycle-mediator / Phase 1。验证：
- 同一 session_id 第二次 send 复用常驻会话（未重建）。
- 冷会话触发 pool resume 重建（acquire 重新建会话）。
- UI runner 的 pool 与 PA PaTmuxRunner 的 pool 实例隔离。
- config.json 缺 webui_sessions 段时由 load_config 缺省自愈补 10/1800 并回写。
"""

from __future__ import annotations

import json

from frago.agent_driver.tmux_session import TurnResult
from frago.server.services.pa_tmux_runner import PaTmuxRunner
from frago.server.services.ui_session_runner import UiSessionRunner


class FakePool:
    """WarmSessionPool 替身：记录 run/resume，跟踪活会话 key。"""

    def __init__(self) -> None:
        self.live: set[str] = set()
        self.runs: list[tuple[str, str]] = []  # (session_id, prompt)
        self.builds: list[str] = []            # 触发冷启动重建的 session_id
        self.native_flags: list[bool] = []     # 每轮 run 收到的 native_session_id
        self.reply_text = "ok"

    def has(self, session_id: str) -> bool:
        return session_id in self.live

    def run(self, prompt, *, agent_type, session_id, cwd, native_session_id=False, timeout_s=120.0, resume_hook=None):  # noqa: ARG002
        if session_id not in self.live:
            # 冷会话：pool 会 resume 重建。
            self.builds.append(session_id)
            self.live.add(session_id)
        self.runs.append((session_id, prompt))
        self.native_flags.append(native_session_id)
        return TurnResult(text=self.reply_text, raw_delta="", status="ok", duration_ms=1)

    def evict(self, session_id: str) -> bool:
        existed = session_id in self.live
        self.live.discard(session_id)
        return existed

    def shutdown(self) -> None:
        self.live.clear()


def test_second_send_reuses_resident_session_without_rebuild():
    pool = FakePool()
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    a1 = runner.send("sess-A", "msg-1")
    a2 = runner.send("sess-A", "msg-2")

    # 两轮都打到同一 session_id；只在首轮触发一次冷启动重建。
    assert [sid for sid, _ in pool.runs] == ["sess-A", "sess-A"]
    assert pool.builds == ["sess-A"]
    # 首轮冷启动 → activating；次轮命中常驻 → ready。
    assert a1.status == "activating"
    assert a2.status == "ready"
    assert a2.text == "ok"


def test_send_passes_native_session_id_true():
    """UI 列的是真实 claude jsonl 会话 id，必须以 native 透传给 pool，
    冷启动才会用真实 id 续上原会话、而非另起新会话写进别的 jsonl。"""
    pool = FakePool()
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    runner.send("real-claude-sid", "hi")

    assert pool.native_flags == [True]


def test_cold_session_triggers_resume_rebuild():
    pool = FakePool()
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    activation = runner.send("cold-X", "hello")

    assert pool.builds == ["cold-X"]       # 冷会话经 pool resume 重建
    assert activation.status == "activating"


def test_ui_runner_pool_isolated_from_pa_pool():
    ui = UiSessionRunner(max_size=10)
    pa = PaTmuxRunner()

    # 各持独立 WarmSessionPool 实例，UI 驾驶不会驱逐/串扰 PA 的常驻会话。
    assert ui._pool is not pa._pool
    assert ui._pool._max_size == 10


def test_load_config_self_heals_missing_webui_sessions(monkeypatch, tmp_path):
    from frago.init import config_manager

    cfg_path = tmp_path / "config.json"
    # 写一个不含 webui_sessions 段的旧 config.json。
    cfg_path.write_text(
        json.dumps({"schema_version": "1.0", "auth_method": "official"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_manager, "CONFIG_PATH", cfg_path)
    # 屏蔽 api_endpoint 迁移副作用（标志文件路径）。
    monkeypatch.setattr(
        config_manager, "_MIGRATION_PERFORMED_FLAG", tmp_path / ".migrated"
    )

    config = config_manager.load_config()

    assert config.webui_sessions.max_resident == 10
    assert config.webui_sessions.idle_timeout_secs == 1800
    # 缺省自愈：补默认后回写，磁盘上现在带有 webui_sessions 段。
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert persisted["webui_sessions"]["max_resident"] == 10
    assert persisted["webui_sessions"]["idle_timeout_secs"] == 1800
