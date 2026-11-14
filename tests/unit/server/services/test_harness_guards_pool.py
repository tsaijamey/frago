"""常驻热池取值路径与 Guard 5「Pool Busy」分支的真实路径测试。

现有 `test_harness_guards.py` 里 `patch.object(coord, "_find_pooled_session", ...)`
把取值整体打桩掉了，只能证明别处没改坏，无法证明取值路径本身是通的。

本文件刻意不 patch `_find_pooled_session`：用真 `WarmSessionPool` 跑一遍
`peek` 取值，并让 Guard 5 的 Pool Busy 分支真的走到。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from frago.agent_driver.pool import WarmSessionPool
from frago.server.services.harness_lifecycle_coordinator import (
    AgentHarnessLifecycleCoordinator,
    TmuxHarnessMeta,
)


def _make_harness_meta(
    *,
    name: str = "frago-agent-test_sid",
    session_id: str = "test_sid",
    kernel: str = "claude",
) -> TmuxHarnessMeta:
    return TmuxHarnessMeta(
        name=name,
        session_id=session_id,
        kernel=kernel,
        created_epoch_secs=1000.0,
        attached_clients=0,
        pane_command="python",
        pane_text="",
        is_borrowed=False,
    )


def _runner_with_pool(pool: object) -> MagicMock:
    runner = MagicMock()
    runner._pool = pool
    return runner


def test_warm_pool_exposes_peek_but_not_get() -> None:
    """类契约：常驻池只暴露 peek，没有 get。"""
    assert hasattr(WarmSessionPool, "peek")
    assert not hasattr(WarmSessionPool, "get")


def test_find_pooled_session_reads_real_pool_without_patching() -> None:
    """_find_pooled_session 必须真正跑一遍取值路径，取到常驻会话对象。"""
    pool = WarmSessionPool()
    pooled = MagicMock()
    pool._sessions["real_sid"] = pooled

    coord = AgentHarnessLifecycleCoordinator()
    with patch(
        "frago.server.services.ui_session_runner.get_runner",
        return_value=_runner_with_pool(pool),
    ):
        assert coord._find_pooled_session("real_sid") is pooled
        # 池里没有时返回 None，而不是抛异常
        assert coord._find_pooled_session("absent_sid") is None


def test_find_pooled_session_survives_pool_without_peek() -> None:
    """取值本身失败（池对象没有 peek）时收窄的 except 兜住并返回 None。"""
    coord = AgentHarnessLifecycleCoordinator()
    with patch(
        "frago.server.services.ui_session_runner.get_runner",
        return_value=_runner_with_pool(object()),
    ):
        assert coord._find_pooled_session("any_sid") is None


def test_guard_5_pool_busy_branch_reachable_with_real_pool() -> None:
    """Guard 5 的 Pool Busy 分支必须能从真池状态真的走到。"""
    pool = WarmSessionPool()
    pooled = MagicMock()
    pooled.status = "busy"
    pool._sessions["busy_sid"] = pooled

    coord = AgentHarnessLifecycleCoordinator()
    with patch(
        "frago.server.services.ui_session_runner.get_runner",
        return_value=_runner_with_pool(pool),
    ):
        verdict = coord.evaluate_guards(_make_harness_meta(session_id="busy_sid"))

    assert verdict.is_protected is True
    assert verdict.guard_name == "Guard 5 (Pool Busy)"
