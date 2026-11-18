"""Tests for workbench agents capabilities and UI feature metadata exposure (Phase 4)."""

from __future__ import annotations

from dataclasses import asdict

from frago.server.services.workbench_agents import list_agents


def test_list_agents_contains_capabilities_and_ui_features() -> None:
    agents = list_agents()
    assert len(agents) >= 5

    agents_by_type = {a.agent_type: a for a in agents}

    # 1. Claude
    claude = agents_by_type.get("claude")
    assert claude is not None
    assert claude.capabilities.get("identity_probe") == "native"
    assert claude.capabilities.get("awaiting_input_probe") == "adapted"
    assert claude.runs_in_tmux is True
    assert claude.supports_resume is True
    assert claude.supports_branch is True
    assert claude.supports_for_you is True
    assert claude.capability_tier == "tier1"

    # 2. AGY
    agy = agents_by_type.get("agy")
    assert agy is not None
    assert agy.capabilities.get("identity_probe") == "adapted"
    assert agy.capabilities.get("awaiting_input_probe") == "fallback"
    assert agy.runs_in_tmux is True
    assert agy.supports_resume is True
    assert agy.supports_branch is True
    assert agy.supports_for_you is True
    assert agy.capability_tier == "tier2"

    # 3. Codex (promoted to tier1 with adapted probes)
    codex = agents_by_type.get("codex")
    assert codex is not None
    assert codex.capabilities.get("identity_probe") == "adapted"
    assert codex.capabilities.get("awaiting_input_probe") == "adapted"
    assert codex.capabilities.get("busy_probe") == "adapted"
    assert codex.capabilities.get("hook_injection") == "adapted"
    assert codex.capability_tier == "tier1"
    assert codex.supports_branch is True

    # 4. OpenCode
    opencode = agents_by_type.get("opencode")
    assert opencode is not None
    assert opencode.capabilities.get("identity_probe") == "adapted"
    assert opencode.capabilities.get("transcript_sync") == "adapted"
    assert opencode.capabilities.get("awaiting_input_probe") == "fallback"
    assert opencode.supports_branch is True

    # 5. CoreAgent
    core = agents_by_type.get("coreagent")
    assert core is not None
    assert core.execution_mode == "tmux_kernel_host"
    assert core.runs_in_tmux is True
    assert core.supports_resume is True
    assert core.supports_branch is True
    assert core.supports_for_you is True
    assert core.capabilities.get("awaiting_input_probe") == "adapted"

    # 6. 验证序列化后字典结构完全保持向后兼容
    serialized = [asdict(a) for a in agents]
    for item in serialized:
        # 原有关键字段 100% 存在
        assert "agent_type" in item
        assert "display_name" in item
        assert "installed" in item
        assert "path" in item
        assert "family" in item
        assert "selectable" in item
        assert "reason" in item
        assert "id_origin" in item
        # 新增能力矩阵与 UI 特性字段
        assert "capabilities" in item
        assert "execution_mode" in item
        assert "runs_in_tmux" in item
        assert "supports_resume" in item
        assert "supports_branch" in item
        assert "supports_for_you" in item
        assert "capability_tier" in item
        assert "profile_mode" in item


def test_workbench_agents_exposes_codex_as_tier1() -> None:
    agents_by_type = {a.agent_type: a for a in list_agents()}
    codex = agents_by_type["codex"]
    assert codex.capability_tier == "tier1"
    for facet, level in codex.capabilities.items():
        assert level in ("native", "adapted"), f"codex {facet} should not be {level}"

