"""Phase 8 单测：滚动记录最近 conv_key + 重启后预热。

覆盖：
- 记录：提到最前 / 去重 / 截断到 10 / __fallback__ 与 None 不记。
- 持久化：read-modify-write 只改 primary_agent.warm_convs，别的字段不被冲掉；
  列表无变化时不写盘。
- 预热：后台任务读 warm_convs，对每个串行调 runner.warm；已活的跳过；不预热
  __fallback__。
"""

from __future__ import annotations

import asyncio
import json

import frago.server.services.primary_agent_service as pa_mod
from frago.server.services.primary_agent_service import (
    WARM_CONVS_MAX,
    PrimaryAgentService,
)


def _svc() -> PrimaryAgentService:
    return PrimaryAgentService()


def _write_config(path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_warm(path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))["primary_agent"]["warm_convs"]


def test_record_promotes_to_front(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {"warm_convs": ["voice:a", "feishu:b", "email:c"]}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    _svc()._record_warm_conv("email:c")
    assert _read_warm(cfg) == ["email:c", "voice:a", "feishu:b"]


def test_record_dedup(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {"warm_convs": ["voice:a", "feishu:b"]}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    _svc()._record_warm_conv("slack:new")
    assert _read_warm(cfg) == ["slack:new", "voice:a", "feishu:b"]
    _svc()._record_warm_conv("voice:a")
    assert _read_warm(cfg) == ["voice:a", "slack:new", "feishu:b"]


def test_record_truncates_to_max(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    existing = [f"feishu:c{i}" for i in range(WARM_CONVS_MAX)]
    _write_config(cfg, {"primary_agent": {"warm_convs": existing}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    _svc()._record_warm_conv("voice:fresh")
    new = _read_warm(cfg)
    assert len(new) == WARM_CONVS_MAX
    assert new[0] == "voice:fresh"
    assert "feishu:c9" not in new  # 最旧被挤出


def test_record_ignores_fallback_none_and_non_channel(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {"warm_convs": ["voice:a"]}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    svc = _svc()
    svc._record_warm_conv(pa_mod.PaTmuxRunner_FALLBACK)
    svc._record_warm_conv("")
    # 内部反思 tick 的裸 ULID（无 channel 前缀）+ 测试夹具值（无前缀）+ 未注册 channel 前缀
    # 一律不记——只有真实 channel 会话进 warm_convs。
    svc._record_warm_conv("01KW56S8737MMDW2A015RD3NDG")  # 反思裸 ULID
    svc._record_warm_conv("thread-A")                    # 无前缀测试夹具
    svc._record_warm_conv("bogus:x")                     # 未注册 channel
    assert _read_warm(cfg) == ["voice:a"]


def test_record_preserves_other_fields(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {
        "session_id": "keep-me",
        "primary_agent": {"warm_convs": ["voice:a"], "heartbeat": {"enabled": True}},
        "other": {"x": 1},
    })
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    _svc()._record_warm_conv("feishu:b")
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    assert raw["session_id"] == "keep-me"
    assert raw["other"] == {"x": 1}
    assert raw["primary_agent"]["heartbeat"] == {"enabled": True}
    assert raw["primary_agent"]["warm_convs"] == ["feishu:b", "voice:a"]


def test_record_no_write_when_unchanged(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {"warm_convs": ["voice:a", "feishu:b"]}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    before = cfg.stat().st_mtime_ns
    _svc()._record_warm_conv("voice:a")  # 已在最前 → 无变化
    assert cfg.stat().st_mtime_ns == before


class _FakeWarmRunner:
    def __init__(self, alive: set[str]) -> None:
        self._alive = alive
        self.calls: list[str] = []

    def warm(self, key: str, *, bootstrap=None, on_ready=None) -> bool:
        # 预热改为注入 bootstrap 那轮（真实提交+等答完）：签名带 bootstrap/on_ready。
        self.calls.append(key)
        created = key not in self._alive  # 已活返回 False
        if created and on_ready is not None:
            on_ready(key)
        return created


def test_preheat_warms_each_serially_skips_alive(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {"warm_convs": ["a", "b", "c"]}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    svc = _svc()
    runner = _FakeWarmRunner(alive={"b"})
    monkeypatch.setattr(svc, "_get_pa_tmux_runner", lambda: runner)

    asyncio.run(svc._preheat_warm_convs())

    # 按 warm_convs 顺序串行调 warm，每个都调一次（已活的也会问一次再跳过）。
    assert runner.calls == ["a", "b", "c"]


def test_preheat_skips_fallback(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {
        "warm_convs": [pa_mod.PaTmuxRunner_FALLBACK, "real"],
    }})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    svc = _svc()
    runner = _FakeWarmRunner(alive=set())
    monkeypatch.setattr(svc, "_get_pa_tmux_runner", lambda: runner)

    asyncio.run(svc._preheat_warm_convs())

    assert runner.calls == ["real"]


def test_preheat_empty_is_noop(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"primary_agent": {}})
    monkeypatch.setattr(pa_mod, "CONFIG_FILE", cfg)
    svc = _svc()
    called = []
    monkeypatch.setattr(svc, "_get_pa_tmux_runner", lambda: called.append(1))
    asyncio.run(svc._preheat_warm_convs())
    assert called == []
