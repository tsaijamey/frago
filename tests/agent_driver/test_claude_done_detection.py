"""claude recipe 完成判定与答案抽取单测（当前 claude v2.1.x，提示符 ``❯``）。

覆盖三个根因修复：
  1. done = 提示符在 AND 非忙碌（思考期空输入框持续显示，不能只认提示符）。
  2. 提示符正则同认 ``>`` 与 ``❯``。
  3. read_answer 从可见 pane 按 prompt 回显定位本轮 ``⏺`` 答案（多轮 delta 语义）。
"""

from __future__ import annotations

import frago.agent_driver.recipes.claude  # noqa: F401  触发注册
from frago.agent_driver import load_recipe
from frago.agent_driver.recipes.claude import _BUSY, _DONE, _READY_BOX, _read_answer

# 思考中：空输入框 ``❯ `` 已在，但 spinner 行在其上方 → 仍忙碌，未完成。
_BUSY_PANE = """❯ Reply with exactly: PINGZ

· Vibing…

────────
❯
────────
  ⏵⏵ bypass permissions on (shift+tab to cycle)
"""

# 带计时/tokens 的 spinner 行同样判忙碌。
_BUSY_PANE_TIMING = """❯ Reply with exactly: PINGZ
· Propagating… (running stop hook · 4s · ↓ 7 tokens)
❯
"""

# 答完：提示符回到空框，spinner 变为不带省略号的完成摘要 → 非忙碌。
_DONE_PANE = """❯ Reply with exactly: PINGZ

⏺ PINGZ

✻ Cogitated for 5s

────────
❯
────────
  ⏵⏵ bypass permissions on (shift+tab to cycle)
"""


def test_busy_pane_is_not_done() -> None:
    assert _BUSY.search(_BUSY_PANE) is not None
    assert not _DONE.matches(_BUSY_PANE)


def test_busy_pane_timing_is_not_done() -> None:
    assert _BUSY.search(_BUSY_PANE_TIMING) is not None
    assert not _DONE.matches(_BUSY_PANE_TIMING)


def test_done_pane_is_done() -> None:
    # 完成摘要 "✻ Cogitated for 5s" 不带括号计时/…，不应误判忙碌。
    assert _BUSY.search(_DONE_PANE) is None
    assert _DONE.matches(_DONE_PANE)


def test_prompt_box_accepts_both_glyphs() -> None:
    assert _DONE.matches("❯ \n")
    assert _DONE.matches("> \n")


def test_ready_box_rejects_shell_echo_of_launch_command() -> None:
    # shell 回显的启动命令行（❯ 后有命令文本）不得判为就绪。
    assert not _READY_BOX.matches("❯ claude --dangerously-skip-permissions\n")
    # 空载输入框才算就绪。
    assert _READY_BOX.matches("❯ \n")


def test_read_answer_picks_current_turn_in_multiturn_pane() -> None:
    pane = (
        "❯ Reply with exactly: AONE\n\n⏺ AONE\n\n✻ Crunched for 5s\n\n"
        "❯ Reply with exactly: BTWO\n\n⏺ BTWO\n\n✻ Worked for 4s\n\n"
        "────────\n❯ \n────────\n  ⏵⏵ bypass permissions on\n"
    )
    assert _read_answer(pane, "Reply with exactly: BTWO") == "BTWO"
    assert _read_answer(pane, "Reply with exactly: AONE") == "AONE"


def test_read_answer_handles_nbsp_in_prompt_echo() -> None:
    # claude 输入框回显里 ❯ 与文本间可能是 nbsp。
    pane = "❯\xa0Reply with exactly: PINGZ\n\n⏺ PINGZ\n\n✻ Baked for 5s\n────────\n❯ \n"
    assert _read_answer(pane, "Reply with exactly: PINGZ") == "PINGZ"


def test_recipe_wires_read_answer() -> None:
    assert load_recipe("claude").read_answer is _read_answer
