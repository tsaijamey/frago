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
