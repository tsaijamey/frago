"""统一的 Hook 时机枚举与四家 CLI 事件名字映射表。

## 为什么需要这张表

frago 的规则引擎（``frago-core --engine``）只认五种事件名：
``SessionStart`` / ``UserPromptSubmit`` / ``PreToolUse`` / ``PostToolUse`` / ``Stop``。
但四家 CLI（``claude``、``codex``、``opencode``、``agy``）各自拥有不同的事件模型与触发频率。

过去「时机」在代码里没有独立身份，靠散落在四处的手写字典或桥接脚本各自翻译，
导致把 agy 的 ``PreInvocation``（每次调模型前触发，``1x/model_call``）直接当成
``UserPromptSubmit``（用户提交一轮触发，``1x/turn``），引发「agy 每个内部步骤都触发
一次轻量 AI 复核」的缺陷。

本模块把「时机（:class:`HookTiming`）」与「触发频率（:class:`HookFrequency`）」定为
受校验的一手数据结构，并集中维护四家 CLI 的名字映射表（:data:`HARNESS_HOOK_TABLES`）：

1. 任何 CLI 的原生事件若想归入某个 :class:`HookTiming`，其 ``observed_frequency``
   必须与该时机的定义频率完全一致（例如 ``1x/model_call`` 绝不能填进 ``turn.submit``）。
2. 若某个高频时机（如 ``model.pre``，``1x/model_call``）需借道引擎的单轮事件
   （``UserPromptSubmit``，``1x/turn``），必须显式声明 ``requires_turn_gate=True``，
   由垫片层实现单轮门控判据（见 ``agy_records.review_context``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class HookTiming(str, Enum):
    """与具体 CLI 无关的统一 Hook 时机标识。"""

    SESSION_START = "session.start"
    TURN_SUBMIT = "turn.submit"
    MODEL_PRE = "model.pre"
    MODEL_POST = "model.post"
    TOOL_PRE = "tool.pre"
    TOOL_POST = "tool.post"
    SESSION_STOP = "session.stop"


class HookFrequency(str, Enum):
    """Hook 时机的标准触发频率（头等校验字段）。"""

    ONCE_PER_SESSION = "1x/session"
    ONCE_PER_TURN = "1x/turn"
    ONCE_PER_MODEL_CALL = "1x/model_call"
    ONCE_PER_TOOL_CALL = "1x/tool_call"


@dataclass(frozen=True)
class TimingSpec:
    """单个统一时机的权威规格。"""

    timing: HookTiming
    frequency: HookFrequency
    engine_event: str | None
    description: str


#: 七个统一时机的权威规格表。
TIMING_SPECS: Mapping[HookTiming, TimingSpec] = MappingProxyType(
    {
        HookTiming.SESSION_START: TimingSpec(
            timing=HookTiming.SESSION_START,
            frequency=HookFrequency.ONCE_PER_SESSION,
            engine_event="SessionStart",
            description="新会话建立、首次模型调用之前",
        ),
        HookTiming.TURN_SUBMIT: TimingSpec(
            timing=HookTiming.TURN_SUBMIT,
            frequency=HookFrequency.ONCE_PER_TURN,
            engine_event="UserPromptSubmit",
            description="用户提交一轮输入、本轮模型尚未开始调用",
        ),
        HookTiming.MODEL_PRE: TimingSpec(
            timing=HookTiming.MODEL_PRE,
            frequency=HookFrequency.ONCE_PER_MODEL_CALL,
            engine_event=None,
            description="每次调用模型之前（一轮内可触发多次）",
        ),
        HookTiming.MODEL_POST: TimingSpec(
            timing=HookTiming.MODEL_POST,
            frequency=HookFrequency.ONCE_PER_MODEL_CALL,
            engine_event=None,
            description="每次模型调用完成之后（一轮内可触发多次）",
        ),
        HookTiming.TOOL_PRE: TimingSpec(
            timing=HookTiming.TOOL_PRE,
            frequency=HookFrequency.ONCE_PER_TOOL_CALL,
            engine_event="PreToolUse",
            description="工具执行之前（可拦截）",
        ),
        HookTiming.TOOL_POST: TimingSpec(
            timing=HookTiming.TOOL_POST,
            frequency=HookFrequency.ONCE_PER_TOOL_CALL,
            engine_event="PostToolUse",
            description="工具执行之后",
        ),
        HookTiming.SESSION_STOP: TimingSpec(
            timing=HookTiming.SESSION_STOP,
            frequency=HookFrequency.ONCE_PER_TURN,
            engine_event="Stop",
            description="本轮执行循环将要终止",
        ),
    }
)

#: 引擎事件名 → 其原生归属的统一时机（供频率反查）。
ENGINE_EVENT_TIMING: Mapping[str, HookTiming] = MappingProxyType(
    {
        spec.engine_event: timing
        for timing, spec in TIMING_SPECS.items()
        if spec.engine_event is not None
    }
)


@dataclass(frozen=True)
class HarnessHookEntry:
    """某家 CLI 在单个统一时机上的映射条目。

    Attributes:
        timing: 对应的统一时机。
        native_event: 该 CLI 侧的原生事件名；若该 CLI 在语义上不存在此时机，填 ``None``。
        observed_frequency: 原生事件自身的触发频率；``native_event`` 非空时必填。
        engine_target: 翻译后送往 ``frago-core --engine`` 的事件名；不送引擎则填 ``None``。
        requires_turn_gate: 当原生事件频率高于 ``engine_target`` 的期望频率（如把
            ``1x/model_call`` 的 ``PreInvocation`` 借道送往 ``1x/turn`` 的
            ``UserPromptSubmit``）时，必须显式设为 ``True``，声明由垫片执行单轮门控。
        provenance: 一手依据出处（实测会话编号、官方文档或代码位置）。
        verified: 是否已完成本机一手实测确认。
    """

    timing: HookTiming
    native_event: str | None
    observed_frequency: HookFrequency | None
    engine_target: str | None
    requires_turn_gate: bool = False
    provenance: str = ""
    verified: bool = True


#: 四家 CLI 的统一时机映射表。
HARNESS_HOOK_TABLES: Mapping[str, Mapping[HookTiming, HarnessHookEntry]] = MappingProxyType(
    {
        "claude": MappingProxyType(
            {
                HookTiming.SESSION_START: HarnessHookEntry(
                    timing=HookTiming.SESSION_START,
                    native_event="SessionStart",
                    observed_frequency=HookFrequency.ONCE_PER_SESSION,
                    engine_target="SessionStart",
                    provenance="~/.claude/settings.json + 实测会话 3c3c795a (1x)",
                    verified=True,
                ),
                HookTiming.TURN_SUBMIT: HarnessHookEntry(
                    timing=HookTiming.TURN_SUBMIT,
                    native_event="UserPromptSubmit",
                    observed_frequency=HookFrequency.ONCE_PER_TURN,
                    engine_target="UserPromptSubmit",
                    provenance="~/.claude/settings.json + 实测会话 3c3c795a (1x)",
                    verified=True,
                ),
                HookTiming.MODEL_PRE: HarnessHookEntry(
                    timing=HookTiming.MODEL_PRE,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="Claude Code 无每次模型调用钩子",
                    verified=True,
                ),
                HookTiming.MODEL_POST: HarnessHookEntry(
                    timing=HookTiming.MODEL_POST,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="Claude Code 无每次模型调用钩子",
                    verified=True,
                ),
                HookTiming.TOOL_PRE: HarnessHookEntry(
                    timing=HookTiming.TOOL_PRE,
                    native_event="PreToolUse",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PreToolUse",
                    provenance="~/.claude/settings.json + 实测会话 3c3c795a (1x)",
                    verified=True,
                ),
                HookTiming.TOOL_POST: HarnessHookEntry(
                    timing=HookTiming.TOOL_POST,
                    native_event="PostToolUse",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PostToolUse",
                    provenance="~/.claude/settings.json + 实测会话 3c3c795a (1x)",
                    verified=True,
                ),
                HookTiming.SESSION_STOP: HarnessHookEntry(
                    timing=HookTiming.SESSION_STOP,
                    native_event="Stop",
                    observed_frequency=HookFrequency.ONCE_PER_TURN,
                    engine_target="Stop",
                    provenance="~/.claude/settings.json + 实测会话 3c3c795a (1x)",
                    verified=True,
                ),
            }
        ),
        "codex": MappingProxyType(
            {
                HookTiming.SESSION_START: HarnessHookEntry(
                    timing=HookTiming.SESSION_START,
                    native_event="SessionStart",
                    observed_frequency=HookFrequency.ONCE_PER_SESSION,
                    engine_target="SessionStart",
                    provenance="~/.codex/hooks.json + 实测会话 2275ac9f (1x)",
                    verified=True,
                ),
                HookTiming.TURN_SUBMIT: HarnessHookEntry(
                    timing=HookTiming.TURN_SUBMIT,
                    native_event="UserPromptSubmit",
                    observed_frequency=HookFrequency.ONCE_PER_TURN,
                    engine_target="UserPromptSubmit",
                    provenance="~/.codex/hooks.json + 实测会话 2275ac9f (1x)",
                    verified=True,
                ),
                HookTiming.MODEL_PRE: HarnessHookEntry(
                    timing=HookTiming.MODEL_PRE,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="codex 无每次模型调用钩子",
                    verified=True,
                ),
                HookTiming.MODEL_POST: HarnessHookEntry(
                    timing=HookTiming.MODEL_POST,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="codex 无每次模型调用钩子",
                    verified=True,
                ),
                HookTiming.TOOL_PRE: HarnessHookEntry(
                    timing=HookTiming.TOOL_PRE,
                    native_event="PreToolUse",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PreToolUse",
                    provenance="~/.codex/hooks.json + 实测会话 2275ac9f (1x)",
                    verified=True,
                ),
                HookTiming.TOOL_POST: HarnessHookEntry(
                    timing=HookTiming.TOOL_POST,
                    native_event="PostToolUse",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PostToolUse",
                    provenance="~/.codex/hooks.json + 实测会话 2275ac9f (1x)",
                    verified=True,
                ),
                HookTiming.SESSION_STOP: HarnessHookEntry(
                    timing=HookTiming.SESSION_STOP,
                    native_event="Stop",
                    observed_frequency=HookFrequency.ONCE_PER_TURN,
                    engine_target="Stop",
                    provenance="~/.codex/hooks.json + 实测会话 2275ac9f (1x)",
                    verified=True,
                ),
            }
        ),
        "opencode": MappingProxyType(
            {
                HookTiming.SESSION_START: HarnessHookEntry(
                    timing=HookTiming.SESSION_START,
                    native_event="chat.message#first",
                    observed_frequency=HookFrequency.ONCE_PER_SESSION,
                    engine_target="SessionStart",
                    provenance=(
                        "resources/opencode/frago-hook.js:13,616-624 (opencode 1.18.5 协议；"
                        "opencode 2.0.20 需适配 default plugin export)"
                    ),
                    verified=False,
                ),
                HookTiming.TURN_SUBMIT: HarnessHookEntry(
                    timing=HookTiming.TURN_SUBMIT,
                    native_event="chat.message",
                    observed_frequency=HookFrequency.ONCE_PER_TURN,
                    engine_target="UserPromptSubmit",
                    provenance=(
                        "resources/opencode/frago-hook.js:14,628-634 (opencode 1.18.5 协议；"
                        "opencode 2.0.20 需适配 default plugin export)"
                    ),
                    verified=False,
                ),
                HookTiming.MODEL_PRE: HarnessHookEntry(
                    timing=HookTiming.MODEL_PRE,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="opencode 插件桥无每次模型调用钩子",
                    verified=True,
                ),
                HookTiming.MODEL_POST: HarnessHookEntry(
                    timing=HookTiming.MODEL_POST,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="opencode 插件桥无每次模型调用钩子",
                    verified=True,
                ),
                HookTiming.TOOL_PRE: HarnessHookEntry(
                    timing=HookTiming.TOOL_PRE,
                    native_event="tool.execute.before",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PreToolUse",
                    provenance="resources/opencode/frago-hook.js:15,684-723 (opencode 1.18.5 协议)",
                    verified=False,
                ),
                HookTiming.TOOL_POST: HarnessHookEntry(
                    timing=HookTiming.TOOL_POST,
                    native_event="tool.execute.after",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target=None,
                    provenance=(
                        "resources/opencode/frago-hook.js:17-22,725-761 "
                        "(承接 PreToolUse 延迟注入与图片描述，不单独调引擎 PostToolUse)"
                    ),
                    verified=False,
                ),
                HookTiming.SESSION_STOP: HarnessHookEntry(
                    timing=HookTiming.SESSION_STOP,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="resources/opencode/frago-hook.js 未挂载 Stop 事件",
                    verified=False,
                ),
            }
        ),
        "agy": MappingProxyType(
            {
                HookTiming.SESSION_START: HarnessHookEntry(
                    timing=HookTiming.SESSION_START,
                    native_event="SessionStart",
                    observed_frequency=HookFrequency.ONCE_PER_SESSION,
                    engine_target="SessionStart",
                    provenance="agy hooks.md + 实测会话 51101f95 (1x)",
                    verified=True,
                ),
                HookTiming.TURN_SUBMIT: HarnessHookEntry(
                    timing=HookTiming.TURN_SUBMIT,
                    native_event=None,
                    observed_frequency=None,
                    engine_target=None,
                    provenance="agy 无 turn.submit 对端（PreInvocation 属 model.pre）",
                    verified=True,
                ),
                HookTiming.MODEL_PRE: HarnessHookEntry(
                    timing=HookTiming.MODEL_PRE,
                    native_event="PreInvocation",
                    observed_frequency=HookFrequency.ONCE_PER_MODEL_CALL,
                    engine_target="UserPromptSubmit",
                    requires_turn_gate=True,
                    provenance=(
                        "agy hooks.md + 实测会话 51101f95 / cd3aca22 "
                        "(借道 UserPromptSubmit，由 agy_records.review_context 单轮门控)"
                    ),
                    verified=True,
                ),
                HookTiming.MODEL_POST: HarnessHookEntry(
                    timing=HookTiming.MODEL_POST,
                    native_event="PostInvocation",
                    observed_frequency=HookFrequency.ONCE_PER_MODEL_CALL,
                    engine_target=None,
                    provenance="agy hooks.md（用于强制续跑，frago 引擎无对端）",
                    verified=True,
                ),
                HookTiming.TOOL_PRE: HarnessHookEntry(
                    timing=HookTiming.TOOL_PRE,
                    native_event="PreToolUse",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PreToolUse",
                    provenance="agy hooks.md + 实测会话 51101f95 / cd3aca22",
                    verified=True,
                ),
                HookTiming.TOOL_POST: HarnessHookEntry(
                    timing=HookTiming.TOOL_POST,
                    native_event="PostToolUse",
                    observed_frequency=HookFrequency.ONCE_PER_TOOL_CALL,
                    engine_target="PostToolUse",
                    provenance="agy hooks.md + cli/agy_hook.py",
                    verified=True,
                ),
                HookTiming.SESSION_STOP: HarnessHookEntry(
                    timing=HookTiming.SESSION_STOP,
                    native_event="Stop",
                    observed_frequency=HookFrequency.ONCE_PER_TURN,
                    engine_target="Stop",
                    provenance="agy hooks.md + cli/agy_hook.py",
                    verified=True,
                ),
            }
        ),
    }
)


def validate_harness_table(
    harness: str,
    table: Mapping[HookTiming, HarnessHookEntry],
) -> None:
    """校验单家 CLI 的 Hook 名字映射表是否满足时机与频率不变量。

    校验四条硬规则：
    1. 必须完整覆盖全部 :class:`HookTiming` 枚举值，不得遗漏。
    2. 条目的 ``timing`` 字段必须与字典键一致。
    3. 当 ``native_event`` 为 ``None`` 时，``observed_frequency`` 与 ``engine_target``
       必须同为 ``None``；当 ``native_event`` 非空时，``observed_frequency`` 必须等于
       该时机在 :data:`TIMING_SPECS` 中定义的标准频率（防止把 ``1x/model_call`` 事件
       塞进 ``turn.submit``）。
    4. 当 ``engine_target`` 非空时，必须是 :data:`ENGINE_EVENT_TIMING` 中合法的引擎事件；
       若条目所在时机的频率与目标引擎事件所属时机的频率不一致（例如把 ``model.pre``
       借道送给 ``UserPromptSubmit``），则必须显式声明 ``requires_turn_gate=True``。
    """
    missing = set(HookTiming) - set(table.keys())
    if missing:
        names = ", ".join(sorted(t.value for t in missing))
        raise ValueError(f"{harness}: 缺少统一时机条目: {names}")

    for timing, entry in table.items():
        if entry.timing != timing:
            raise ValueError(
                f"{harness}[{timing.value}]: entry.timing={entry.timing.value} 与键不一致"
            )

        spec = TIMING_SPECS[timing]

        if entry.native_event is None:
            if entry.observed_frequency is not None or entry.engine_target is not None:
                raise ValueError(
                    f"{harness}[{timing.value}]: native_event 为空时，"
                    "observed_frequency 与 engine_target 必须同为空"
                )
            if entry.requires_turn_gate:
                raise ValueError(
                    f"{harness}[{timing.value}]: native_event 为空时不应设置 requires_turn_gate"
                )
            continue

        if entry.observed_frequency != spec.frequency:
            raise ValueError(
                f"{harness}[{timing.value}]: 原生事件 {entry.native_event!r} 的频率 "
                f"{entry.observed_frequency} 与时机标准频率 {spec.frequency} 不符"
            )

        if entry.engine_target is not None:
            target_timing = ENGINE_EVENT_TIMING.get(entry.engine_target)
            if target_timing is None:
                raise ValueError(
                    f"{harness}[{timing.value}]: 未知的引擎事件目标 {entry.engine_target!r}"
                )
            target_spec = TIMING_SPECS[target_timing]
            freq_mismatch = spec.frequency != target_spec.frequency
            if freq_mismatch and not entry.requires_turn_gate:
                raise ValueError(
                    f"{harness}[{timing.value}]: 原生事件 {entry.native_event!r} "
                    f"({spec.frequency.value}) 借道引擎事件 {entry.engine_target!r} "
                    f"({target_spec.frequency.value}) 时必须显式声明 requires_turn_gate=True"
                )
            if not freq_mismatch and entry.requires_turn_gate:
                raise ValueError(
                    f"{harness}[{timing.value}]: 频率已对齐 ({spec.frequency.value})，"
                    "无需设置 requires_turn_gate=True"
                )


def validate_all_harness_tables() -> None:
    """校验 :data:`HARNESS_HOOK_TABLES` 中登记的全部 CLI 映射表。"""
    for harness, table in HARNESS_HOOK_TABLES.items():
        validate_harness_table(harness, table)


def build_engine_event_map(harness: str) -> dict[str, str]:
    """从指定 CLI 的统一时机映射表导出 ``{原生事件名: 引擎事件名}`` 字典。

    仅收录 ``native_event`` 与 ``engine_target`` 均非空的条目。
    """
    table = HARNESS_HOOK_TABLES.get(harness)
    if table is None:
        raise KeyError(f"未知的 CLI harness: {harness!r}")
    return {
        entry.native_event: entry.engine_target
        for entry in table.values()
        if entry.native_event is not None and entry.engine_target is not None
    }


# 模块导入期即自检四家表结构与频率一致性
validate_all_harness_tables()
