"""Phase 1 单测：claude driver 的 needs_input 阻断门信号。

靶子两类：① 认证墙 / API 鉴权失败；② agent 自抛的编号选择菜单（``❯ 1.``）。
MUST 不误命中正常空输入框 ``_READY_BOX``（``❯ `` 行尾为空）与本轮答案正文。
"""

from __future__ import annotations

import frago.agent_driver.drivers.claude as claude_mod
from frago.agent_driver.driver import load_driver


def test_claude_registers_needs_input_signal():
    driver = load_driver("claude")
    assert driver.needs_input_signal is not None
    assert driver.needs_input_signal.name == "claude-needs-input"


def _match(text: str) -> bool:
    return claude_mod._NEEDS_INPUT.matches(text)


def test_auth_wall_variants_hit():
    for s in (
        "Invalid API key · Please run /login",
        "You are not logged in",
        "Error: Unauthorized (401)",
        "Authentication failed",
        "Credit balance is too low",
    ):
        assert _match(s), f"auth wall should match: {s!r}"


def test_select_menu_hits():
    pane = (
        "Do you want to proceed?\n"
        "│ ❯ 1. Yes\n"
        "│   2. No\n"
    )
    assert _match(pane)
    # 闭括号编号同样命中
    assert _match("❯ 1) Option A")


def test_ready_box_not_matched():
    # 空输入框：❯ 行尾为空——绝不能被当成阻断门。
    assert not _match("╭──────────╮\n│ ❯        │\n╰──────────╯")
    assert not claude_mod._READY_BOX.matches("❯ 1. Yes")  # sanity: 菜单不是 ready


def test_normal_answer_text_not_matched():
    pane = (
        "⏺ Here is the plan:\n"
        "We will refactor the module and add tests.\n"
        "❯ "
    )
    assert not _match(pane)


def test_prompt_echo_not_matched():
    # 用户消息回显 ``❯ <text>``（非编号选项）不应命中。
    assert not _match("❯ help me write a function")
