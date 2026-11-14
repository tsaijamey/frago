"""Tests for AgentDriver 6 orthogonal capability facets and ontology alignment (Phase 3)."""

from __future__ import annotations

from frago.agent_driver.driver import (
    AgentDriver,
    AgentDriverFacets,
    AwaitingInputProbeFacet,
    BusyProbeFacet,
    ContextWatermarkFacet,
    HookInjectionFacet,
    IdentityProbeFacet,
    LifecycleActionFacet,
    PaneMatcher,
    TranscriptSyncFacet,
    load_driver,
    registered_drivers,
    runs_on_kernel,
)


def test_agent_driver_facets_structure() -> None:
    facets = AgentDriverFacets(
        identity_probe=IdentityProbeFacet(
            agent_type="dummy",
            display_name="Dummy Agent",
            locate=lambda: "/bin/dummy",
            capability_level="native",
        ),
        lifecycle_action=LifecycleActionFacet(
            launch_command=lambda ctx: "dummy run",
            ready_signal=PaneMatcher("ready", r"ready>"),
            submit=lambda sess, text: None,
            done_signal=PaneMatcher("done", r"done>"),
            capability_level="native",
        ),
        transcript_sync=TranscriptSyncFacet(
            extract=lambda delta: delta.strip(),
            capability_level="adapted",
        ),
        awaiting_input_probe=AwaitingInputProbeFacet(
            awaiting_input=lambda pane: True,
            capability_level="adapted",
        ),
        context_watermark=ContextWatermarkFacet(
            known_models=("model-a", "model-b"),
            capability_level="native",
        ),
        hook_injection=HookInjectionFacet(
            profile_mode="file_and_env",
            capability_level="native",
        ),
    )

    assert facets.identity_probe.display_name == "Dummy Agent"
    assert facets.get_facet("context_watermark").known_models == ("model-a", "model-b")
    assert isinstance(facets.get_facet("busy_probe"), BusyProbeFacet)
    as_map = facets.as_dict()
    assert set(as_map.keys()) == {
        "identity_probe",
        "lifecycle_action",
        "transcript_sync",
        "awaiting_input_probe",
        "busy_probe",
        "context_watermark",
        "hook_injection",
    }


def test_agent_driver_backward_compatibility_and_facet_view() -> None:
    driver = AgentDriver(
        agent_type="claude",
        launch_command=lambda ctx: "claude",
        ready_signal=PaneMatcher("ready", r">"),
        submit=lambda sess, text: None,
        done_signal=PaneMatcher("done", r"done"),
        extract=lambda s: s,
        display_name="Claude Code",
        locate=lambda: "/usr/local/bin/claude",
        profile_apply=lambda profile: None,
        profile_mode="file_and_env",
    )

    # 1. 存量顶层字段访问 100% 保持兼容
    assert driver.agent_type == "claude"
    assert driver.display_name == "Claude Code"
    assert driver.locate is not None and driver.locate() == "/usr/local/bin/claude"
    assert driver.supports_profile_apply is True

    # 2. 结构化切面视图
    facets = driver.facets
    assert isinstance(facets, AgentDriverFacets)
    assert facets.identity_probe.agent_type == "claude"
    assert facets.hook_injection.profile_mode == "file_and_env"
    assert driver.get_capability_level("identity_probe") == "native"
    assert driver.get_capability_level("awaiting_input_probe") == "adapted"

    # 3. 导出本体字典
    kernel_dict = driver.to_ontology_kernel_dict()
    assert kernel_dict["name"] == "claude"
    assert kernel_dict["execution_mode"] == "tmux_tui"
    assert kernel_dict["runs_in_tmux"] is True
    assert kernel_dict["supports_for_you"] is True
    assert kernel_dict["capabilities"]["awaiting_input_probe"] == "adapted"


def test_runs_on_kernel_contract() -> None:
    assert runs_on_kernel("coreagent") is True
    assert runs_on_kernel("claude") is False
    assert runs_on_kernel("agy") is False
    assert runs_on_kernel("codex") is False
    assert runs_on_kernel("opencode") is False


def test_registered_drivers_have_facets_and_probes() -> None:
    drivers = registered_drivers()
    assert "claude" in drivers
    assert "agy" in drivers
    assert "codex" in drivers
    assert "opencode" in drivers

    claude_driver = load_driver("claude")
    assert claude_driver.awaiting_input is not None
    assert callable(claude_driver.awaiting_input)
    assert claude_driver.facets.awaiting_input_probe.awaiting_input is not None
    assert callable(claude_driver.facets.busy_probe.is_busy)
    assert claude_driver.facets.busy_probe.capability_level == "native"
    assert claude_driver.supports_profile_apply is True

    agy_driver = load_driver("agy")
    assert agy_driver.facets.hook_injection.profile_mode == "file_and_env"
    assert callable(agy_driver.facets.busy_probe.is_busy)
    assert agy_driver.facets.busy_probe.capability_level == "adapted"
    assert agy_driver.supports_profile_apply is True

    codex_driver = load_driver("codex")
    assert codex_driver.facets.hook_injection.profile_mode == "file_and_env"
    assert codex_driver.supports_profile_apply is True

    opencode_driver = load_driver("opencode")
    assert opencode_driver.facets.hook_injection.profile_mode == "file_and_env"
    assert opencode_driver.supports_profile_apply is True
