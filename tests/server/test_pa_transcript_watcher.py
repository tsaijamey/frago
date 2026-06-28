"""Phase 6 单测（spec 20260627）：transcript 持续转发器 + 喂料门 + 回收。

覆盖：
- watcher 去重：同 marker 只投一次、新 marker 投新文本。
- 喂料门在忙时不投（_wait_until_truly_idle 持续等到真空闲才返回）。
- idle_age_fn 忙时返回 None（在跑活的会话 NEVER 被回收）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import frago.agent_driver.drivers.claude as claude_mod
from frago.server.services.primary_agent_service import PrimaryAgentService


def _tc(done: bool, marker: str | None, text: str) -> SimpleNamespace:
    """TurnCompletion 替身：watcher 只读 done / last_uuid / final_text。"""
    return SimpleNamespace(done=done, last_uuid=marker, final_text=text)


class _FakeRunner:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self.sessions: dict[str, object] = {}

    def active_session_keys(self) -> list[str]:
        return self._keys

    def session(self, key: str):
        return self.sessions.get(key)


def _svc_with_runner(keys: list[str]) -> PrimaryAgentService:
    svc = PrimaryAgentService()
    svc._pa_tmux_runner = _FakeRunner(keys)
    for k in keys:
        svc._conv_route_cache[k] = {
            "channel": "feishu", "conv_key": k, "reply_context": {"chat_id": "x"},
        }
    return svc


def test_watcher_dedup_same_marker_delivers_once():
    svc = _svc_with_runner(["c1"])
    delivered: list[tuple[str, dict]] = []

    async def _fake_deliver(text, route):
        delivered.append((text, route))

    svc.deliver = _fake_deliver  # type: ignore[assignment]

    # mtime 每拍推进（绕开 stat 短路，单独验 marker 去重），但 marker 不变 → 只投一次。
    _n = {"v": 0}

    def _poll(_ck, _since):
        _n["v"] += 1
        return float(_n["v"]), _tc(True, "m1", "完整答案 A")

    svc._watch_poll = _poll  # type: ignore[assignment]
    asyncio.run(svc._watch_tick())
    asyncio.run(svc._watch_tick())

    assert len(delivered) == 1
    assert delivered[0][0] == "完整答案 A"
    assert delivered[0][1]["channel"] == "feishu"


def test_watcher_new_marker_delivers_new_text():
    svc = _svc_with_runner(["c1"])
    delivered: list[str] = []

    async def _fake_deliver(text, _route):
        delivered.append(text)

    svc.deliver = _fake_deliver  # type: ignore[assignment]

    # mtime 推进 + marker 推进（稍等 → 后台续干出真结果）→ 两条都投。
    _seq = iter([
        (1.0, _tc(True, "m1", "稍等，我去查一下")),
        (2.0, _tc(True, "m2", "查到了，结果是 42")),
    ])
    svc._watch_poll = lambda _ck, _since: next(_seq)  # type: ignore[assignment]
    asyncio.run(svc._watch_tick())
    asyncio.run(svc._watch_tick())

    assert delivered == ["稍等，我去查一下", "查到了，结果是 42"]


def test_watch_poll_short_circuits_on_unchanged_mtime(tmp_path, monkeypatch):
    """真实 _watch_poll：mtime 没变那拍只 stat、不调 evaluate_file（省全量重读）。"""
    import frago.server.services.transcript_completion as tc_mod

    f = tmp_path / "t.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    calls = {"n": 0}
    real_eval = tc_mod.evaluate_file

    def _spy(p):
        calls["n"] += 1
        return real_eval(p)

    monkeypatch.setattr(tc_mod, "locate_transcript", lambda _sid, **_k: f)
    monkeypatch.setattr(tc_mod, "evaluate_file", _spy)

    svc = PrimaryAgentService()
    mt, _ = svc._watch_poll("c1", None)          # 首次（since None）→ 解析
    assert mt is not None and calls["n"] == 1
    mt2, tc2 = svc._watch_poll("c1", mt)         # since==mtime → 短路，不解析
    assert mt2 == mt and tc2 is None and calls["n"] == 1


def test_watcher_skips_not_done_and_bootstrapping():
    svc = _svc_with_runner(["c1"])
    delivered: list[str] = []
    svc.deliver = lambda t, _r: delivered.append(t)  # type: ignore

    # not done（tool_use 进行中 / 流式半截）→ 不投。
    svc._eval_conv_transcript = lambda _ck: _tc(False, "mX", "半截")  # type: ignore
    asyncio.run(svc._watch_tick())
    assert delivered == []

    # bootstrapping 窗口内 → 跳过该 conv（baseline 未锚定，避免误投 bootstrap 回复）。
    svc._bootstrapping_convs.add("c1")
    svc._eval_conv_transcript = lambda _ck: _tc(True, "m1", "bootstrap 回复")  # type: ignore
    asyncio.run(svc._watch_tick())
    assert delivered == []


def test_feeding_gate_waits_while_busy():
    """喂料门在忙时不放行：_wait_until_truly_idle 持续等到真空闲才返回。"""
    svc = _svc_with_runner(["c1"])
    svc._pa_tmux_runner.sessions["c1"] = object()  # 有活会话，进入等待
    svc._watch_config = {**svc._watch_config, "idle_poll_seconds": 0.001,
                         "feeding_gate_max_seconds": 5.0}

    calls = {"n": 0}

    def _idle(_key):
        calls["n"] += 1
        return calls["n"] >= 3  # 前两次忙、第三次才真空闲

    svc._is_truly_idle = _idle  # type: ignore

    asyncio.run(svc._wait_until_truly_idle("c1"))
    assert calls["n"] == 3  # 一直等到真空闲才返回


def test_feeding_gate_timeout_proceeds():
    """永远不空闲时，超过上限放行（记日志），不死等。"""
    svc = _svc_with_runner(["c1"])
    svc._pa_tmux_runner.sessions["c1"] = object()
    svc._watch_config = {**svc._watch_config, "idle_poll_seconds": 0.001,
                         "feeding_gate_max_seconds": 0.0}
    svc._is_truly_idle = lambda _key: False  # type: ignore
    # max_wait=0 → 首次检查后即超时放行，不抛、不死等。
    asyncio.run(svc._wait_until_truly_idle("c1"))


def test_idle_age_fn_returns_none_when_busy(monkeypatch):
    """回收用的 idle_age_fn：会话在跑活（is_truly_idle False）→ None，NEVER 回收。"""
    captured = {}

    class _Pool:
        def evict_idle(self, fn, timeout_s):
            captured["fn"] = fn
            captured["timeout"] = timeout_s
            return []

    svc = PrimaryAgentService()
    svc._pa_tmux_runner = SimpleNamespace(_pool=_Pool())

    # 忙：is_truly_idle 返回 False → idle_age 必须 None。
    monkeypatch.setattr(claude_mod, "is_truly_idle", lambda _s, **_k: False)
    asyncio.run(svc._evict_idle_sessions())

    idle_age = captured["fn"]
    assert idle_age(SimpleNamespace()) is None
