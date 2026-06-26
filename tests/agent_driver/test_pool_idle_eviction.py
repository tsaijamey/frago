"""Phase 2 单测：WarmSessionPool.evict_idle 按空闲时长驱逐。

spec 20260625-webui-session-lifecycle-mediator / Phase 2。验证：
- 空闲秒数 > timeout 的会话被驱逐（kill）。
- idle_age_fn 返回 None（干活中 / 无锚点）的会话 NEVER 被驱逐。
- 时间维度驱逐与数量 LRU 并存、互不干扰。
"""

from __future__ import annotations

from frago.agent_driver.pool import WarmSessionPool


class FakeSession:
    """TmuxAgentSession 替身：evict_idle 只需要 close() 和可识别身份。"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.cwd = "/tmp"
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _pool_with(sessions: dict[str, FakeSession], max_size: int = 8) -> WarmSessionPool:
    pool = WarmSessionPool(max_size=max_size)
    for sid, sess in sessions.items():
        pool._sessions[sid] = sess  # 直接装入，绕过真实 tmux open
    return pool


def test_evicts_sessions_idle_over_timeout():
    a, b = FakeSession("a"), FakeSession("b")
    pool = _pool_with({"a": a, "b": b})
    ages = {"a": 100.0, "b": 4000.0}  # a 刚停，b 空闲很久

    evicted = pool.evict_idle(lambda s: ages[s.session_id], timeout_s=1800.0)

    assert evicted == ["b"]
    assert b.closed is True and pool.has("b") is False
    assert a.closed is False and pool.has("a") is True


def test_busy_session_never_evicted():
    """idle_age_fn 返回 None（探针 not done）→ 干活中，绝不回收。"""
    busy = FakeSession("busy")
    pool = _pool_with({"busy": busy})

    evicted = pool.evict_idle(lambda _s: None, timeout_s=0.0)  # 阈值为 0 也不该杀

    assert evicted == []
    assert busy.closed is False and pool.has("busy") is True


def test_boundary_strictly_greater():
    """恰好等于阈值不驱逐，严格大于才驱逐。"""
    s = FakeSession("s")
    pool = _pool_with({"s": s})

    assert pool.evict_idle(lambda _s: 1800.0, timeout_s=1800.0) == []
    assert pool.evict_idle(lambda _s: 1800.1, timeout_s=1800.0) == ["s"]


def test_idle_eviction_coexists_with_count_lru():
    """时间驱逐挑空闲项，数量 LRU 仍按容量约束——两者独立生效。"""
    sessions = {sid: FakeSession(sid) for sid in ("a", "b", "c")}
    pool = _pool_with(sessions, max_size=8)
    # 只有 b 空闲超时；a、c 仍在干活（None）。
    ages = {"a": None, "b": 5000.0, "c": None}

    evicted = pool.evict_idle(lambda s: ages[s.session_id], timeout_s=1800.0)

    assert evicted == ["b"]
    assert pool.has("a") and pool.has("c") and not pool.has("b")
