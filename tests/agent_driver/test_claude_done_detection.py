"""claude driver 完成判定与答案抽取单测（当前 claude v2.1.x，提示符 ``❯``）。

覆盖三个根因修复：
  1. done = 提示符在 AND 非忙碌（思考期空输入框持续显示，不能只认提示符）。
  2. 提示符正则同认 ``>`` 与 ``❯``。
  3. read_answer 从可见 pane 按 prompt 回显定位本轮 ``⏺`` 答案（多轮 delta 语义）。
"""

from __future__ import annotations

import frago.agent_driver.drivers.claude  # noqa: F401  触发注册
from frago.agent_driver import load_driver
from frago.agent_driver.drivers.claude import _BUSY, _DONE, _READY_BOX, _read_answer

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


# ── 启动就绪：空输入框里只有灰色输入提示（SGR 2 暗色）也判就绪 ──────────
# claude 2026-09-25 升 2.1.282 后，空输入框会显示一句灰色输入提示（``❯ Try "…"``）。
# 它是暗色字、不是人打进去的；不带颜色读屏它像框里有字，``_READY_BOX`` 永不命中、
# 30 秒后误判启动失败。ready_signal 走带颜色读屏（open() 按 ready_signal_ansi 带 -e
# 抓屏）：先 ``blank_dim_runs`` 抹空暗色字再判空，启动失败字样在纯文本上认。
_CLAUDE_READY = load_driver("claude").ready_signal

# 刚启动：整句提示都包在 SGR 2 暗色里（主控实抓 p1.ansi 的形状）。
_DIM_HINT_PANE = '❯\xa0\x1b[2mTry\x1b[0m \x1b[2m"fix typecheck errors"\x1b[0m'
# 光标压在提示首字上：那个字反显（SGR 7）、后面紧跟暗色段。
_DIM_HINT_CURSOR = '❯\xa0\x1b[7mT\x1b[27m\x1b[2mry "fix lint errors"\x1b[22m'
# 人打进去的正常颜色字（故意也以 Try 开头，主控实抓 p2.ansi 的形状）。
_TYPED_PANE = "❯\xa0Try hello"


def test_ready_with_only_dim_input_hint() -> None:
    assert _CLAUDE_READY.matches(_DIM_HINT_PANE) is True


def test_ready_with_cursor_on_first_dim_hint_letter() -> None:
    assert _CLAUDE_READY.matches(_DIM_HINT_CURSOR) is True


def test_ready_rejects_normal_coloured_typed_text() -> None:
    assert _CLAUDE_READY.matches(_TYPED_PANE) is False


def test_ready_rejects_fatal_startup_phrase() -> None:
    # 启动失败那两句在带颜色的屏上照样拦下；错误字样带暗色也不放行
    # （致命判据走 strip_ansi，不把暗色字抹空）。
    fatal_dim = '\x1b[2mNo conversation found with session id\x1b[0m abcd\n❯\xa0'
    assert _CLAUDE_READY.matches(fatal_dim) is False
    fatal_plain = "❯\xa0Session ID abc is already in use\n"
    assert _CLAUDE_READY.matches(fatal_plain) is False


def test_ready_still_works_on_plain_text() -> None:
    # 兼容不带颜色的调用方（pool 接管 / CLI 复查）：行为与旧版一致。
    assert _CLAUDE_READY.matches("❯ \n") is True
    assert _CLAUDE_READY.matches("❯ claude --resume abc\n") is False


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
    assert load_driver("claude").read_answer is _read_answer
