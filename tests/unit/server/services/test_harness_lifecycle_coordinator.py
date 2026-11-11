"""AgentHarnessLifecycleCoordinator 全域生命周期协调器集成单元测试。

验证：
1. 全域承载发现与会话 ID 解析；
2. 首次观测安全计时基线（First-Observed Safety Anchor）：刚进入视野的池外会话受冷却宽限期保护，绝不被秒杀；
3. 一次性后台 Worker 快速冷却回收（300s）；
4. 普通工作台/员工会话闲置回收（1800s）；
5. 坏壳空 shell 自动识别并回收；
6. 销毁后 observed_tracker 键同步清理，防止内存膨胀。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.harness_lifecycle_coordinator import (
    AgentHarnessLifecycleCoordinator,
    TmuxHarnessMeta,
)
from frago.session.adapters.kernel_adapters import TurnCompletionVerdict


@pytest.fixture
def coordinator() -> AgentHarnessLifecycleCoordinator:
    return AgentHarnessLifecycleCoordinator(scan_interval_s=60.0)


def test_first_observed_grace_period_prevents_premature_kill(
    coordinator: AgentHarnessLifecycleCoordinator,
) -> None:
    """首次观测安全计时基线：即使转录文件时间是 5 小时前，首次观测未满宽限期绝对不回收（防秒杀！）。"""
    now = 10000.0
    harness = TmuxHarnessMeta(
        name="frago-agent-resumed_sid",
        session_id="resumed_sid",
        kernel="claude",
        created_epoch_secs=now - 10.0,  # 刚起来 10 秒
        attached_clients=0,
        pane_command="claude",
        pane_text="Some old text\n❯ ",
    )

    with patch.object(
        coordinator, "_find_pooled_session", return_value=None
    ), patch.object(
        coordinator, "_get_latest_dispatch_completion_ts", return_value=None
    ), patch.object(
        coordinator,
        "_get_transcript_mtime",
        return_value=now - 5 * 3600,  # 旧转录是 5 小时前！
    ), patch(
        "frago.server.services.harness_lifecycle_coordinator.get_kernel_session_adapter"
    ) as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.probe_turn_completion.return_value = TurnCompletionVerdict(
            done=True, stop_reason="end_turn"
        )
        mock_get_adapter.return_value = mock_adapter

        # 首次计算：刚进入视野
        idle_first = coordinator.compute_harness_idle_age(
            harness, now=now, grace_secs=120.0
        )
        # 宽限期生效，必须返回 None 豁免！
        assert idle_first is None
        assert harness.name in coordinator._observed_tracker

        # 60 秒后（仍小于 120 秒）：仍然受到保护！
        idle_60s = coordinator.compute_harness_idle_age(
            harness, now=now + 60.0, grace_secs=120.0
        )
        assert idle_60s is None

        # 130 秒后（已过 120 秒冷却期）：开始正常返回空闲时长
        idle_130s = coordinator.compute_harness_idle_age(
            harness, now=now + 130.0, grace_secs=120.0
        )
        assert idle_130s is not None
        assert idle_130s >= 130.0


def test_one_off_worker_cooling_reclaim_threshold(
    coordinator: AgentHarnessLifecycleCoordinator,
) -> None:
    """一次性后台 Worker（已成功送达）采用更快的冷却超时门槛（300s）。"""
    job_mock = MagicMock()
    job_mock.kind = "worker"
    job_mock.mode = "new"
    job_mock.delivery_state = "delivered"
    job_mock.updated_at = "2026-11-11T10:00:00Z"

    with patch("frago.session.async_dispatch.list_dispatch_jobs", return_value=[job_mock]):
        th = coordinator._resolve_timeout_threshold(
            "worker_sid", default_timeout=1800.0, worker_timeout=300.0
        )
        assert th == 300.0

    # 普通员工会话或交互会话使用 1800s
    job_emp = MagicMock()
    job_emp.kind = "employee"
    job_emp.mode = "ask"
    job_emp.delivery_state = "delivered"
    job_emp.updated_at = "2026-11-11T10:00:00Z"

    with patch("frago.session.async_dispatch.list_dispatch_jobs", return_value=[job_emp]):
        th_emp = coordinator._resolve_timeout_threshold(
            "emp_sid", default_timeout=1800.0, worker_timeout=300.0
        )
        assert th_emp == 1800.0


def test_dead_shell_harness_can_be_reclaimed(
    coordinator: AgentHarnessLifecycleCoordinator,
) -> None:
    """智能体进程已退、窗格仅剩 zsh/bash 空壳的坏壳承载，无需等待转录 done 即可安全回收。"""
    now = 5000.0
    dead_harness = TmuxHarnessMeta(
        name="frago-agent-dead_sid",
        session_id="dead_sid",
        kernel="claude",
        created_epoch_secs=now - 2000.0,
        attached_clients=0,
        pane_command="zsh",  # 前台已退回 shell 空壳
        pane_text="frago$ ",
    )

    # 预设已经过了观测宽限期
    coordinator._observed_tracker[dead_harness.name] = now - 150.0

    with patch.object(coordinator, "_find_pooled_session", return_value=None), patch.object(
        coordinator, "_get_latest_dispatch_completion_ts", return_value=None
    ), patch.object(coordinator, "_get_transcript_mtime", return_value=now - 2000.0):
        idle_age = coordinator.compute_harness_idle_age(
            dead_harness, now=now, grace_secs=120.0
        )
        assert idle_age is not None
        assert idle_age >= 150.0


def test_scan_and_reclaim_cleans_observed_tracker(
    coordinator: AgentHarnessLifecycleCoordinator,
) -> None:
    """回收执行成功后，对应的 harness_name 会从 observed_tracker 移除，且已消亡的会话会被自动修剪。"""
    now = 10000.0

    harness_victim = TmuxHarnessMeta(
        name="frago-agent-victim_sid",
        session_id="victim_sid",
        kernel="claude",
        created_epoch_secs=now - 3000.0,
        attached_clients=0,
        pane_command="claude",
        pane_text="Finished.\n❯ ",
    )

    # 预设已过宽限期
    coordinator._observed_tracker[harness_victim.name] = now - 200.0
    coordinator._observed_tracker["frago-agent-already_gone"] = now - 500.0

    cfg_mock = MagicMock()
    cfg_mock.idle_timeout_secs = 1800
    cfg_mock.worker_idle_timeout_secs = 300
    cfg_mock.observed_cooling_grace_secs = 120
    cfg_mock.global_reclaim_enabled = True

    with patch.object(
        coordinator, "discover_harnesses", return_value=[harness_victim]
    ), patch.object(
        coordinator, "evaluate_guards"
    ) as mock_guard, patch.object(
        coordinator, "compute_harness_idle_age", return_value=2500.0  # 超过 1800s
    ), patch.object(
        coordinator, "reclaim_harness", return_value={"harness": harness_victim.name, "ok": True, "via": "tmux_named_kill"}
    ):
        guard_verdict_mock = MagicMock()
        guard_verdict_mock.is_protected = False
        mock_guard.return_value = guard_verdict_mock

        results = coordinator._scan_and_reclaim_sync(cfg_mock)

        assert len(results) == 1
        assert results[0]["ok"] is True
        # victim 已被回收并从 tracker 清理
        assert harness_victim.name not in coordinator._observed_tracker
        # already_gone 已自然消亡，被修剪清理
        assert "frago-agent-already_gone" not in coordinator._observed_tracker
