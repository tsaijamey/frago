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


# ── 启动失败：裸提示符与空输入框长得一模一样，就绪判据必须多问一句 ──────────
#
# 20260902 实测：claude v2.1.258 的输入框是「横线 + ``❯ `` + 横线」，而裸 zsh 提示符
# 也是 ``❯ ``——``_READY_BOX`` 两者都命中。claude 起不来时（报完一句就退出）pane 落回
# shell，就绪判据在裸提示符主题下会当场判就绪，于是用户那句话被打进 shell 并按下
# Enter，**当成命令执行**。本机 starship 行尾多画了个 ``─╯`` 才侥幸不命中。

NO_CONVERSATION_PANE = (
    "❯ claude --dangerously-skip-permissions --resume 00000000-1111-2222-3333-444444444444\n"
    "No conversation found with session ID: 00000000-1111-2222-3333-444444444444\n"
    "❯\n"
)
SESSION_IN_USE_PANE = (
    "❯ claude --dangerously-skip-permissions --session-id abc-123\n"
    "Error: Session ID abc-123 is already in use\n"
    "❯ \n"
)
# claude v2.1.258 的真实空输入框（本机 tmux 抓的形状）。
LIVE_INPUT_BOX_PANE = (
    "  ▝▝ ▝▝    /private/tmp/scratchpad/cc\n"
    "────────────────────────────────────────\n"
    "❯ \n"
    "────────────────────────────────────────\n"
    "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
)


def test_bare_shell_prompt_is_indistinguishable_from_an_empty_input_box():
    """把这条钉死：两者在 ``_READY_BOX`` 眼里一模一样。

    这不是要修的行为，是解释**为什么就绪判据必须再多问一句"屏上有没有启动失败"**。
    哪天有人想收紧 ``_READY_BOX`` 去区分它俩，这条会告诉他那条路走不通。
    """
    assert claude_mod._READY_BOX.matches("❯ \n") is True
    assert claude_mod._READY_BOX.matches(LIVE_INPUT_BOX_PANE) is True


def test_ready_refuses_a_pane_that_shows_a_failed_launch():
    """回归：起不来那两屏 MUST 不算就绪，否则用户那句话会被 shell 执行。"""
    assert claude_mod._READY.matches(NO_CONVERSATION_PANE) is False
    assert claude_mod._READY.matches(SESSION_IN_USE_PANE) is False


def test_ready_still_matches_a_live_input_box():
    """守另一边：真实空输入框 MUST 仍然算就绪，NEVER 因为这道闸让每一场都起不来。"""
    assert claude_mod._READY.matches(LIVE_INPUT_BOX_PANE) is True


def test_needs_input_catches_a_failed_launch_so_the_turn_ends_fast():
    """这道门在轮询里反复看，错误行晚上屏也接得住，本轮不会空等到超时。"""
    assert _match(NO_CONVERSATION_PANE) is True
    assert _match(SESSION_IN_USE_PANE) is True
    # 守另一边：正常输入框与答案正文 MUST 不命中。
    assert _match(LIVE_INPUT_BOX_PANE) is False
    assert _match("我把会话恢复那段写完了，没有找到别的问题") is False


class _FakePane:
    def __init__(self, pane: str) -> None:
        self.pane = pane
        self.keys: list[tuple[str, ...]] = []
        self.session_id = "sid"
        self.cwd = "/tmp"
        self.native_session_id = True
        self._poll_interval_s = 0

    def capture_pane(self, **_kw) -> str:
        return self.pane

    def send_text(self, text: str) -> None:
        pass

    def send_keys(self, *keys: str) -> None:
        self.keys.append(keys)

    def _sleep(self, _s: float) -> None:
        return None


def test_submit_never_presses_enter_into_a_dead_tui(monkeypatch):
    """安全闸回归：claude 已经起不来时 MUST 不按 Enter。

    按下去，用户在页面上打的那句话就落到 shell 上被当成命令执行。文本本身已经发出去
    了没关系：没有 Enter，它只停在 shell 的行缓冲里。
    """
    monkeypatch.setattr(claude_mod, "transcript_path_for", lambda s: None)
    session = _FakePane(NO_CONVERSATION_PANE)
    claude_mod._submit(session, "rm -rf 看起来像命令的一句话")
    assert session.keys == [], "claude 已经不在了，一个 Enter 都不该发出去"


def test_submit_still_presses_enter_on_a_live_tui(monkeypatch):
    """守另一边：健康会话照常提交。"""
    monkeypatch.setattr(claude_mod, "transcript_path_for", lambda s: None)
    session = _FakePane(LIVE_INPUT_BOX_PANE)
    claude_mod._submit(session, "干活")
    assert ("Enter",) in session.keys
