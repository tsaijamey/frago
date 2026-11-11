"""AgentHarness 六道刚性安全保护守卫（Guard 1–6）单元测试。

验证：
1. Guard 1: 人类附着在场（attached_clients > 0）绝对豁免；
2. Guard 2: 借住模式宿主窗口（tmux_target is not None）仅退回 shell，严禁 kill-session；
3. Guard 3: 活跃异步派发单保护：作为 target 执行方或 caller 等待回传方，在任务未完结前双方均绝对豁免；
4. Guard 4: 待投递消息队列保护：workbench_queue 中存在待注入消息时绝对豁免；
5. Guard 5: 物理承载忙碌或后台外壳运行（shells still running）绝对豁免；
6. Guard 6: 逐条点名安全关闭铁律：池内走 pool.evict，池外点名 kill-session，严禁 kill-server。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from frago.server.services.harness_lifecycle_coordinator import (
    AgentHarnessLifecycleCoordinator,
    TmuxHarnessMeta,
)
from frago.session.adapters.kernel_adapters import HarnessIdleVerdict


def _make_harness_meta(
    *,
    name: str = "frago-agent-test_sid",
    session_id: str = "test_sid",
    kernel: str = "claude",
    attached_clients: int = 0,
    pane_text: str = "",
    pane_command: str = "python",
    is_borrowed: bool = False,
) -> TmuxHarnessMeta:
    return TmuxHarnessMeta(
        name=name,
        session_id=session_id,
        kernel=kernel,
        created_epoch_secs=1000.0,
        attached_clients=attached_clients,
        pane_command=pane_command,
        pane_text=pane_text,
        is_borrowed=is_borrowed,
    )


def test_guard_1_human_presence_attached() -> None:
    """Guard 1: 人类终端 attach 查看中（attached_clients > 0），必须绝对豁免回收。"""
    coord = AgentHarnessLifecycleCoordinator()
    harness = _make_harness_meta(attached_clients=1)

    verdict = coord.evaluate_guards(harness)
    assert verdict.is_protected is True
    assert "Human Presence" in verdict.guard_name


def test_guard_2_non_agent_prefix_filtered() -> None:
    """Guard 2: 非 frago-agent- 前缀（如宿主窗口 frago-stage），必须被过滤保护。"""
    coord = AgentHarnessLifecycleCoordinator()
    harness = _make_harness_meta(name="frago-stage", session_id="stage")

    verdict = coord.evaluate_guards(harness)
    assert verdict.is_protected is True
    assert "Host Borrowing" in verdict.guard_name


def test_guard_3_async_dispatch_active_target_and_caller() -> None:
    """Guard 3: 活跃异步派发单保护——作为 target 或 caller 均豁免回收。"""
    coord = AgentHarnessLifecycleCoordinator()

    # 1. 模拟会话作为 target_session_id 正在被异步派发执行
    job_target = MagicMock()
    job_target.status = "running"
    job_target.delivery_state = "queued"
    job_target.target_session_id = "target_sid"
    job_target.caller_session_id = "caller_sid"

    with patch("frago.session.async_dispatch.list_dispatch_jobs", return_value=[job_target]):
        harness_target = _make_harness_meta(session_id="target_sid")
        verdict_target = coord.evaluate_guards(harness_target)
        assert verdict_target.is_protected is True
        assert "Active Async Dispatch" in verdict_target.guard_name

        # 2. 模拟调用方员工会话 caller_sid 正在等待回传唤醒，同样绝对保护
        harness_caller = _make_harness_meta(session_id="caller_sid")
        verdict_caller = coord.evaluate_guards(harness_caller)
        assert verdict_caller.is_protected is True
        assert "Active Async Dispatch" in verdict_caller.guard_name


def test_guard_4_pending_workbench_queue() -> None:
    """Guard 4: 待投递消息队列保护——消息队列非空时绝对豁免。"""
    coord = AgentHarnessLifecycleCoordinator()
    harness = _make_harness_meta(session_id="queued_sid")

    # Mock 活跃队列索引包含该会话
    with patch(
        "frago.server.services.workbench_queue._read_active_queues_index",
        return_value={"queued_sid"},
        create=True,
    ):
        verdict = coord.evaluate_guards(harness)
        assert verdict.is_protected is True
        assert "Pending Workbench Queue" in verdict.guard_name


def test_guard_5_physical_busy_and_running_subshells() -> None:
    """Guard 5: 物理忙碌与后台运行子外壳保护。"""
    coord = AgentHarnessLifecycleCoordinator()

    # 1. 后台外壳还在运行
    harness_subshell = _make_harness_meta(session_id="subshell_sid")
    fake_subshell_verdict = HarnessIdleVerdict(
        is_busy=True,
        is_terminal_idle=False,
        has_running_subshells=True,
        detail="2 shells still running",
    )
    with patch.object(
        coord, "_find_pooled_session", return_value=None
    ), patch(
        "frago.server.services.harness_lifecycle_coordinator.get_kernel_session_adapter"
    ) as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.probe_harness_idle.return_value = fake_subshell_verdict
        mock_get_adapter.return_value = mock_adapter

        verdict = coord.evaluate_guards(harness_subshell)
        assert verdict.is_protected is True
        assert "Subshells Running" in verdict.guard_name

    # 2. 热池内状态为 busy
    pooled_busy = MagicMock()
    pooled_busy.status = "busy"
    with patch.object(coord, "_find_pooled_session", return_value=pooled_busy):
        verdict_pool_busy = coord.evaluate_guards(_make_harness_meta(session_id="busy_sid"))
        assert verdict_pool_busy.is_protected is True
        assert "Pool Busy" in verdict_pool_busy.guard_name


def test_guard_6_atomic_reclaim_pool_vs_named_kill() -> None:
    """Guard 6: 逐条点名安全关闭铁律：池内走 pool.evict，池外走 tmux 点名 kill，借住走退出键。"""
    coord = AgentHarnessLifecycleCoordinator()

    # 1. 池内实例：委派 runner.evict
    harness_pool = _make_harness_meta(session_id="pool_sid")
    mock_runner = MagicMock()
    mock_runner._pool.has.return_value = True
    mock_runner.evict.return_value = True

    with patch("frago.server.services.ui_session_runner.get_runner", return_value=mock_runner):
        res = coord.reclaim_harness(harness_pool)
        assert res["ok"] is True
        assert res["via"] == "warm_pool"
        mock_runner.evict.assert_called_once_with("pool_sid")

    # 2. 借住模式：只发退出按键，严禁 kill-session
    harness_borrowed = _make_harness_meta(session_id="borrowed_sid", is_borrowed=True)
    mock_runner._pool.has.return_value = False
    with patch("frago.server.services.ui_session_runner.get_runner", return_value=mock_runner), patch.object(
        coord, "_quit_borrowed_harness"
    ) as mock_quit:
        res_borrowed = coord.reclaim_harness(harness_borrowed)
        assert res_borrowed["ok"] is True
        assert res_borrowed["via"] == "borrowed_quit"
        mock_quit.assert_called_once()

    # 3. 池外实例：逐条点名 kill-session
    harness_ext = _make_harness_meta(name="frago-agent-ext_123", session_id="ext_123")
    mock_runner._pool.has.return_value = False

    executed_cmds: list[list[str]] = []

    def mock_tmux_exec(*args: str) -> str:
        executed_cmds.append(list(args))
        if args[0] == "has-session":
            return ""  # 表示已经不存在了
        return ""

    with patch("frago.server.services.ui_session_runner.get_runner", return_value=mock_runner), patch(
        "frago.server.services.harness_lifecycle_coordinator._run_tmux",
        side_effect=mock_tmux_exec,
    ):
        res_ext = coord.reclaim_harness(harness_ext)
        assert res_ext["ok"] is True
        assert res_ext["via"] == "tmux_named_kill"
        assert ["kill-session", "-t", "frago-agent-ext_123"] in executed_cmds
