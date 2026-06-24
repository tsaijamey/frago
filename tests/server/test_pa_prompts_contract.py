"""Contract tests: PA_SYSTEM_PROMPT 必须与代码现实一致。

锁住 20260624-pa-system-prompt-realign 修订成果，防止提示词再次漂移：
- action 词汇集与 pa_validators.VALID_PA_ACTIONS 一致（不教 schedule，教 dismiss）
- 消息结构描述与运行期 <msg> 模板一致
- 每个 PA 会收到的队列消息类型都有处理契约
- schedule 死代码（模板）已删
"""

import frago.server.services.pa_prompts as M
from frago.server.services.pa_prompts import (
    PA_INTERNAL_REFLECTION_TEMPLATE,
    PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE,
    PA_SYSTEM_PROMPT,
)
from frago.server.services.pa_validators import VALID_PA_ACTIONS


def test_no_schedule_emit_teaching() -> None:
    """提示词不得教 PA 发起 schedule（校验器会整轮拒）。"""
    assert '"action": "schedule"' not in PA_SYSTEM_PROMPT
    assert '"action":"schedule"' not in PA_SYSTEM_PROMPT
    assert "### schedule" not in PA_SYSTEM_PROMPT
    assert "用 **schedule**" not in PA_SYSTEM_PROMPT
    assert "schedule — 注册定时任务" not in PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE
    assert "reply/run/schedule" not in PA_INTERNAL_REFLECTION_TEMPLATE


def test_schedule_failed_template_removed() -> None:
    """schedule 发起侧失败模板属死代码，已删。"""
    assert not hasattr(M, "PA_SCHEDULE_FAILED_TEMPLATE")


def test_action_vocab_matches_validator() -> None:
    """提示词只教校验器认可的 4 个 action；schedule 不在内、dismiss 在内。"""
    assert {"reply", "run", "resume", "dismiss"} == VALID_PA_ACTIONS
    assert "schedule" not in VALID_PA_ACTIONS
    # dismiss 是一等 action：必须有 JSON 示例
    assert (
        '"action": "dismiss"' in PA_SYSTEM_PROMPT
        or '"action":"dismiss"' in PA_SYSTEM_PROMPT
    )
    # 调度路由教 dismiss
    assert "用 **dismiss**" in PA_SYSTEM_PROMPT


def test_correction_template_lists_exactly_four_actions() -> None:
    """纠错模板列的可选 action = 校验器 4 个（含 dismiss，不含 schedule）。"""
    for act in ("reply", "run", "resume", "dismiss"):
        assert f"  {act}" in PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE, act
    assert "schedule" not in PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE


def test_message_structure_uses_msg_tag() -> None:
    """消息结构描述对齐运行期 <msg> 模板，不再用 <instruction>/<context>。"""
    assert "<instruction>" not in PA_SYSTEM_PROMPT
    assert "<context>" not in PA_SYSTEM_PROMPT
    assert "<msg msg_id" in PA_SYSTEM_PROMPT


def test_all_received_queue_types_have_handling() -> None:
    """PA 会收到的每类队列消息都有处理契约写在提示词里。"""
    for kw in (
        "scheduled_task",
        "reply_failed",
        "run_failed",
        "resume_failed",
        "recovered_failed_task",
        "internal_reflection",
    ):
        assert kw in PA_SYSTEM_PROMPT, kw


def test_bootstrap_injection_list_complete() -> None:
    """reborn 节列出的 bootstrap 注入项覆盖 build_bootstrap 实际产出的关键段。"""
    assert "TaskBoard 视图" in PA_SYSTEM_PROMPT
    assert "Active threads 折叠视图" in PA_SYSTEM_PROMPT
