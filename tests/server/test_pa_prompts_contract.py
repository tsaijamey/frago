"""Contract tests: PA_SYSTEM_PROMPT 必须与代码现实一致。

Phase 2 (spec 20260627-pa-deboard-resident-agent) 去掉了 JSON 决策协议——常驻 agent
自然说话，最终文本即回复内容。本契约锁住"提示词不再教 JSON 决策协议"这一成果，防止
旧的 run/reply/resume/dismiss 四 action 教学漂移回来。
"""

import frago.server.services.pa_prompts as M
from frago.server.services.pa_prompts import (
    PA_SYSTEM_PROMPT,
)


def test_no_json_decision_protocol() -> None:
    """提示词不得再教"最终输出 JSON 数组"决策协议。"""
    assert "JSON 数组" not in PA_SYSTEM_PROMPT
    assert "JSON.parse" not in PA_SYSTEM_PROMPT
    assert '"action"' not in PA_SYSTEM_PROMPT
    assert "空闲时输出: `[]`" not in PA_SYSTEM_PROMPT


def test_correction_template_removed() -> None:
    """JSON 纠错模板属死代码，已删。"""
    assert not hasattr(M, "PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE")


def test_schedule_failed_template_removed() -> None:
    assert not hasattr(M, "PA_SCHEDULE_FAILED_TEMPLATE")


def test_teaches_natural_language_output() -> None:
    """提示词教 agent 用自然语言、最终文本即回复内容。"""
    assert "自然语言" in PA_SYSTEM_PROMPT
    assert "最终文本" in PA_SYSTEM_PROMPT


def test_teaches_frago_agent_start_worker() -> None:
    """派重活用 frago agent start，worker 完成以新消息回来。"""
    assert "frago agent start" in PA_SYSTEM_PROMPT
    assert "worker" in PA_SYSTEM_PROMPT
    assert "新消息" in PA_SYSTEM_PROMPT


def test_message_structure_uses_msg_tag() -> None:
    """消息结构描述仍对齐运行期 <msg> 模板。"""
    assert "<instruction>" not in PA_SYSTEM_PROMPT
    assert "<context>" not in PA_SYSTEM_PROMPT
    assert "<msg msg_id" in PA_SYSTEM_PROMPT


def test_received_queue_types_have_handling() -> None:
    """PA 会收到的系统投递消息类型仍有处理契约。"""
    for kw in (
        "agent_completed",
        "scheduled_task",
        "reply_failed",
        "recovered_failed_task",
    ):
        assert kw in PA_SYSTEM_PROMPT, kw
