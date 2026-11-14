"""针对 KernelSessionAdapter 统一适配器契约与注册表的单元测试。

验证关键链路：
1. 五内核 (claude-code, coreagent, agy, codex, opencode) 注册表完备性；
2. 各适配器符合 KernelSessionAdapter 契约；
3. opencode 显式不支持文件流 (supports_file_stream = False)；
4. 动态扩展与未知内核异常处理。
"""

from __future__ import annotations

import pytest

from frago.session.adapters.kernel_adapters import (
    KERNEL_SESSION_REGISTRY,
    AgySessionAdapter,
    ClaudeCodeSessionAdapter,
    CodexSessionAdapter,
    CoreAgentSessionAdapter,
    KernelSessionAdapter,
    KernelSessionAdapterNotRegistered,
    OpencodeSessionAdapter,
    TurnCompletionVerdict,
    get_kernel_session_adapter,
    list_kernel_session_adapters,
    register_kernel_session_adapter,
)


def test_kernel_session_registry_contains_all_five_kernels():
    """验证注册表覆盖 claude-code/claude, coreagent, agy, codex, opencode。"""
    registered = list_kernel_session_adapters()
    expected = {"claude-code", "claude", "coreagent", "agy", "codex", "opencode"}
    assert expected.issubset(set(registered))

    assert isinstance(get_kernel_session_adapter("claude-code"), ClaudeCodeSessionAdapter)
    assert isinstance(get_kernel_session_adapter("claude"), ClaudeCodeSessionAdapter)
    assert isinstance(get_kernel_session_adapter("coreagent"), CoreAgentSessionAdapter)
    assert isinstance(get_kernel_session_adapter("agy"), AgySessionAdapter)
    assert isinstance(get_kernel_session_adapter("codex"), CodexSessionAdapter)
    assert isinstance(get_kernel_session_adapter("opencode"), OpencodeSessionAdapter)


def test_kernel_session_adapter_protocol_conformance():
    """验证所有注册适配器均符合 KernelSessionAdapter 协议。"""
    for family in list_kernel_session_adapters():
        adapter = get_kernel_session_adapter(family)
        assert isinstance(adapter, KernelSessionAdapter)
        assert hasattr(adapter, "family")
        assert hasattr(adapter, "supports_file_stream")
        assert callable(adapter.locate_transcript)
        assert callable(adapter.read_unified_records)
        assert callable(adapter.probe_turn_completion)


def test_opencode_adapter_explicit_contract():
    """验证 opencode 显式不走文件流，且安全回退空记录与探针。"""
    adapter = get_kernel_session_adapter("opencode")
    assert adapter.supports_file_stream is False
    assert adapter.locate_transcript("session-123") is None
    assert adapter.read_unified_records("session-123") == []
    verdict = adapter.probe_turn_completion("session-123")
    assert isinstance(verdict, TurnCompletionVerdict)
    assert verdict.done is False
    assert verdict.stop_reason is None


def test_unknown_kernel_raises_not_registered():
    """验证未知内核报错并列出已知候选。"""
    with pytest.raises(KernelSessionAdapterNotRegistered, match="尚未注册会话适配器"):
        get_kernel_session_adapter("unknown-future-kernel")


def test_dynamic_register_custom_adapter():
    """测试动态注册自定义内核适配器。"""

    class DummyAdapter:
        family = "dummy-kernel"
        supports_file_stream = True

        def locate_transcript(self, session_id: str):
            return None

        def read_unified_records(self, session_id: str, path=None):
            return []

        def probe_turn_completion(self, session_id: str, path=None):
            return TurnCompletionVerdict(done=True, stop_reason="dummy")

    register_kernel_session_adapter("dummy-kernel", DummyAdapter())
    try:
        assert "dummy-kernel" in list_kernel_session_adapters()
        adapter = get_kernel_session_adapter("dummy-kernel")
        assert adapter.probe_turn_completion("s1").stop_reason == "dummy"
    finally:
        KERNEL_SESSION_REGISTRY.pop("dummy-kernel", None)


def test_agy_adapter_distinguishes_unknown_from_in_progress(monkeypatch):
    """AgySessionAdapter.probe_turn_completion 必须区分『无法定位轮次(unknown=True)』与『明确未完成(unknown=False)』。"""
    from frago.session import agy_store

    adapter = get_kernel_session_adapter("agy")
    assert isinstance(adapter, AgySessionAdapter)

    monkeypatch.setattr(agy_store, "latest_turn", lambda _sid: None)
    unknown_verdict = adapter.probe_turn_completion("agy-unknown")
    assert unknown_verdict.done is False
    assert unknown_verdict.unknown is True
    assert unknown_verdict.stop_reason is None

    monkeypatch.setattr(
        agy_store,
        "latest_turn",
        lambda _sid: agy_store.AgyTurn(turn_id="5", done=False, text="", error=None),
    )
    active_verdict = adapter.probe_turn_completion("agy-active")
    assert active_verdict.done is False
    assert active_verdict.unknown is False

    monkeypatch.setattr(
        agy_store,
        "latest_turn",
        lambda _sid: agy_store.AgyTurn(turn_id="5", done=True, text="最终答复", error=None),
    )
    done_verdict = adapter.probe_turn_completion("agy-done")
    assert done_verdict.done is True
    assert done_verdict.unknown is False
    assert done_verdict.stop_reason == "end_turn"
    assert done_verdict.final_text == "最终答复"


def test_turn_finished_unknown_fallback_and_safety_gates(tmp_path, monkeypatch):
    """验证 _turn_finished 在转录 unknown 时允许已落盘就绪窗格退回读屏，同时严防忙碌屏与新建未落盘误放行。"""
    import json
    from types import SimpleNamespace

    import frago.agent_driver.drivers.agy  # noqa: F401
    from frago.agent_driver.driver import registered_drivers
    from frago.server.services import ui_session_runner as usr
    from frago.session import agy_store

    app_root = tmp_path / "antigravity-cli"
    app_root.mkdir()
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(app_root))
    monkeypatch.setattr(agy_store, "get_binding", lambda _sid: None)

    ready_pane = (
        "Previous delivery output\n"
        "> Auto mode: edits & safe commands auto-approved (shift+tab to cycle)\n"
        "? for shortcuts · auto · Gemini 4 Hydrogen · high\n"
    )
    busy_pane = (
        "Working on files...\n"
        "⣻  Generating...\n"
        "esc to cancel\n"
    )
    real_agy_driver = registered_drivers()["agy"]

    def _make_session(sid: str, pane: str):
        return SimpleNamespace(
            driver=real_agy_driver,
            session_id=sid,
            capture_pane=lambda: pane,
        )

    # 1. 新建刚启动尚未落盘（无 transcript 文件）：即便屏幕出现就绪状态栏也绝不误放行
    assert usr._turn_finished(_make_session("new-unpersisted-sid", ready_pane)) is False

    # 2. 0 字节空转录文件：同样不放行
    empty_sid = "empty-persisted-sid"
    empty_path = agy_store.transcript_path(empty_sid)
    empty_path.parent.mkdir(parents=True, exist_ok=True)
    empty_path.write_text("", encoding="utf-8")
    assert usr._turn_finished(_make_session(empty_sid, ready_pane)) is False

    # 3. 已落盘非空转录但无 USER_INPUT（latest_turn=None -> unknown=True）：
    #    - 窗格就绪空闲 -> 退回读屏信号放行 True
    #    - 窗格正在 Generating / esc to cancel -> 忙碌拦截 False
    no_user_sid = "persisted-no-user-sid"
    no_user_path = agy_store.transcript_path(no_user_sid)
    no_user_path.parent.mkdir(parents=True, exist_ok=True)
    no_user_path.write_text(
        json.dumps({"step_index": 1, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": "init"})
        + "\n",
        encoding="utf-8",
    )
    assert agy_store.latest_turn(no_user_sid) is None
    assert usr._turn_finished(_make_session(no_user_sid, ready_pane)) is True
    assert usr._turn_finished(_make_session(no_user_sid, busy_pane)) is False

    # 4. 转录明确记录未完成（done=False, unknown=False，例如后台任务等待回调）：即便屏幕静态就绪也必须拦住
    bg_sid = "persisted-bg-running-sid"
    bg_path = agy_store.transcript_path(bg_sid)
    bg_path.parent.mkdir(parents=True, exist_ok=True)
    bg_records = [
        {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>run bg</USER_REQUEST>"},
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "GENERIC",
            "status": "RUNNING",
            "content": f"Tool is running as a background task with task id: {bg_sid}/task-1\n",
        },
        {"step_index": 2, "type": "PLANNER_RESPONSE", "content": "等待后台命令完成…"},
    ]
    bg_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in bg_records) + "\n",
        encoding="utf-8",
    )
    assert usr._turn_finished(_make_session(bg_sid, ready_pane)) is False


def test_75d51ed1_long_transcript_shape_delivers_via_submit_when_idle(tmp_path, monkeypatch):
    """端到端复现 75d51ed1 长转录形态（单轮 > 530KB 输出）：submit_when_idle 不再陷入 not_now 死循环。"""
    import json
    import threading
    from types import SimpleNamespace

    import frago.agent_driver.drivers.agy  # noqa: F401
    from frago.agent_driver.driver import registered_drivers
    from frago.server.services.ui_session_runner import UiSessionRunner
    from frago.session import agy_store

    app_root = tmp_path / "antigravity-cli"
    app_root.mkdir()
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(app_root))
    monkeypatch.setattr(agy_store, "get_binding", lambda _sid: None)

    sid = "75d51ed1-71b3-4fee-9419-f510c08f2674"
    tpath = agy_store.transcript_path(sid)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"step_index": 287, "type": "USER_INPUT", "content": "<USER_REQUEST>升华设计</USER_REQUEST>"},
    ]
    filler = "z" * 16_384
    for i in range(35):
        records.append({"step_index": 288 + i, "type": "GENERIC", "content": filler})
    records.append({"step_index": 763, "type": "PLANNER_RESPONSE", "content": "已全部完成。"})
    tpath.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    assert tpath.stat().st_size > 530 * 1024

    submitted: list[str] = []
    ready_pane = (
        "> Auto mode: edits & safe commands auto-approved\n"
        "? for shortcuts · auto · Gemini 4 Hydrogen · high\n"
    )
    fake_driver = SimpleNamespace(
        agent_type="agy",
        ready_signal=registered_drivers()["agy"].ready_signal,
        submit=lambda _sess, txt: submitted.append(txt),
        clear_input=None,
    )
    fake_session = SimpleNamespace(
        session_id=sid,
        status="idle",
        driver=fake_driver,
        _submit_lock=threading.Lock(),
        capture_pane=lambda: ready_pane,
    )

    class _Pool:
        def acquire(self, *_a, **_kw):
            return fake_session

    runner = UiSessionRunner(pool=_Pool(), cwd=str(tmp_path), agent_type="agy")
    outcome = runner.submit_when_idle(
        sid,
        "<frago-async-callback job_id=\"disp-b83d9e458af9\">done</frago-async-callback>",
        landed=lambda: bool(submitted),
        agent_type="agy",
        cwd=str(tmp_path),
    )
    assert outcome == "landed"
    assert len(submitted) == 1

