"""统一 Hook 时机枚举与四家 CLI 名字映射表（frago.init.hook_timing）的单元测试。"""

from __future__ import annotations

import pytest

from frago.cli.agy_hook import EVENT_MAP as AGY_EVENT_MAP
from frago.init.hook_timing import (
    ENGINE_EVENT_TIMING,
    HARNESS_HOOK_TABLES,
    TIMING_SPECS,
    HarnessHookEntry,
    HookFrequency,
    HookTiming,
    build_engine_event_map,
    validate_all_harness_tables,
    validate_harness_table,
)


def test_timing_specs_cover_all_seven_timings() -> None:
    """七个统一时机在 TIMING_SPECS 中完整定义，且频率字段俱全。"""
    assert set(TIMING_SPECS.keys()) == set(HookTiming)
    assert TIMING_SPECS[HookTiming.SESSION_START].frequency == HookFrequency.ONCE_PER_SESSION
    assert TIMING_SPECS[HookTiming.TURN_SUBMIT].frequency == HookFrequency.ONCE_PER_TURN
    assert TIMING_SPECS[HookTiming.MODEL_PRE].frequency == HookFrequency.ONCE_PER_MODEL_CALL
    assert TIMING_SPECS[HookTiming.MODEL_POST].frequency == HookFrequency.ONCE_PER_MODEL_CALL
    assert TIMING_SPECS[HookTiming.TOOL_PRE].frequency == HookFrequency.ONCE_PER_TOOL_CALL
    assert TIMING_SPECS[HookTiming.TOOL_POST].frequency == HookFrequency.ONCE_PER_TOOL_CALL
    assert TIMING_SPECS[HookTiming.SESSION_STOP].frequency == HookFrequency.ONCE_PER_TURN


def test_engine_event_timing_reverse_lookup() -> None:
    """引擎识别的五个事件名能准确反查回其所属时机。"""
    assert dict(ENGINE_EVENT_TIMING) == {
        "SessionStart": HookTiming.SESSION_START,
        "UserPromptSubmit": HookTiming.TURN_SUBMIT,
        "PreToolUse": HookTiming.TOOL_PRE,
        "PostToolUse": HookTiming.TOOL_POST,
        "Stop": HookTiming.SESSION_STOP,
    }


def test_all_four_harnesses_present_and_valid() -> None:
    """claude / codex / opencode / agy 四家表均在册且通过完整性与频率校验。"""
    assert set(HARNESS_HOOK_TABLES.keys()) == {"claude", "codex", "opencode", "agy"}
    validate_all_harness_tables()


def test_agy_pre_invocation_is_model_pre_not_turn_submit() -> None:
    """agy 的 PreInvocation 必须归在 model.pre 而非 turn.submit，且声明 requires_turn_gate。"""
    agy_table = HARNESS_HOOK_TABLES["agy"]
    assert agy_table[HookTiming.TURN_SUBMIT].native_event is None
    model_pre = agy_table[HookTiming.MODEL_PRE]
    assert model_pre.native_event == "PreInvocation"
    assert model_pre.observed_frequency == HookFrequency.ONCE_PER_MODEL_CALL
    assert model_pre.engine_target == "UserPromptSubmit"
    assert model_pre.requires_turn_gate is True


def test_agy_hook_event_map_derived_from_timing_table() -> None:
    """cli/agy_hook.py 的 EVENT_MAP 由权威名字表导出且保持五路兼容。"""
    expected = {
        "SessionStart": "SessionStart",
        "PreInvocation": "UserPromptSubmit",
        "PreToolUse": "PreToolUse",
        "PostToolUse": "PostToolUse",
        "Stop": "Stop",
    }
    assert build_engine_event_map("agy") == expected
    assert AGY_EVENT_MAP == expected


def test_validator_rejects_missing_timing() -> None:
    """缺少任意 HookTiming 条目的映射表应被校验器拒绝。"""
    incomplete = dict(HARNESS_HOOK_TABLES["claude"])
    incomplete.pop(HookTiming.SESSION_STOP)
    with pytest.raises(ValueError, match="缺少统一时机条目"):
        validate_harness_table("broken", incomplete)


def test_validator_rejects_frequency_mismatch_on_timing() -> None:
    """把 1x/model_call 的事件直接塞进 turn.submit（1x/turn）会被校验器当场拦下。"""
    bad = dict(HARNESS_HOOK_TABLES["agy"])
    bad[HookTiming.TURN_SUBMIT] = HarnessHookEntry(
        timing=HookTiming.TURN_SUBMIT,
        native_event="PreInvocation",
        observed_frequency=HookFrequency.ONCE_PER_MODEL_CALL,
        engine_target="UserPromptSubmit",
    )
    with pytest.raises(ValueError, match="与时机标准频率.*不符"):
        validate_harness_table("bad_agy", bad)


def test_validator_rejects_cross_frequency_engine_target_without_turn_gate() -> None:
    """高频时机（model.pre）借道低频引擎事件（UserPromptSubmit）却未声明 requires_turn_gate 时报错。"""
    bad = dict(HARNESS_HOOK_TABLES["agy"])
    bad[HookTiming.MODEL_PRE] = HarnessHookEntry(
        timing=HookTiming.MODEL_PRE,
        native_event="PreInvocation",
        observed_frequency=HookFrequency.ONCE_PER_MODEL_CALL,
        engine_target="UserPromptSubmit",
        requires_turn_gate=False,
    )
    with pytest.raises(ValueError, match="requires_turn_gate=True"):
        validate_harness_table("ungated_agy", bad)
