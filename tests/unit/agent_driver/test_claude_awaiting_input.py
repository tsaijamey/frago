"""Claude Code 是不是停在待输入态——会话页「For you」的第③条判据。

带颜色读屏：答完后输入框里那句灰色建议、没字时的灰色输入提示都是暗色字，
必须当空；人自己打的字不是暗色，必须让输入框「非空」。
"""

from frago.agent_driver.drivers import claude as c

RULE = "─" * 20


def _screen(box: str, above: str = "⏺ 做完了。") -> str:
    return f"{above}\n\n{RULE}\n{box}\n{RULE}\n  ⏵⏵ bypass permissions on\n"


class TestBlankDimRuns:
    def test_dim_suggestion_becomes_spaces(self):
        assert c.blank_dim_runs("❯\xa0\x1b[2mA, go ahead\x1b[0m").strip() == "❯"

    def test_typed_text_is_kept(self):
        assert c.blank_dim_runs("❯\xa0\x1b[39mhello\x1b[0m").strip() == "❯\xa0hello"

    def test_cursor_on_the_first_letter_of_a_placeholder_is_blank(self):
        # 光标压在输入提示第一个字上：那个字反显，后面紧跟暗色段
        line = '❯\xa0\x1b[7mT\x1b[27m\x1b[2mry "fix lint errors"\x1b[22m'
        assert c.blank_dim_runs(line).strip() == "❯"

    def test_reverse_letter_followed_by_typed_text_is_kept(self):
        line = "❯\xa0\x1b[7mh\x1b[27mello"
        assert c.blank_dim_runs(line).strip() == "❯\xa0hello"

    def test_extended_colour_params_are_not_read_as_dim(self):
        # 38;5;2 里的 2 是色号，不是暗色
        assert c.blank_dim_runs("\x1b[38;5;2mok\x1b[39m") == "ok"

    def test_mixed_screen_only_blanks_the_dim_part(self):
        out = c.blank_dim_runs("❯\xa0typed \x1b[2mghost\x1b[22m")
        assert out.rstrip() == "❯\xa0typed"


class TestAwaitingInput:
    def test_empty_box(self):
        assert c.awaiting_input(_screen("❯\xa0")) is True

    def test_dim_suggestion_counts_as_empty(self):
        assert c.awaiting_input(_screen("❯\xa0\x1b[2mA, go ahead\x1b[0m")) is True

    def test_typed_draft_is_not_waiting(self):
        assert c.awaiting_input(_screen("❯\xa0still typing")) is False

    def test_spinner_means_busy(self):
        assert (
            c.awaiting_input(_screen("❯\xa0", above="✻ Cogitating… (12s · esc to interrupt)"))
            is False
        )

    def test_dim_busy_marker_still_means_busy(self):
        # 计时和 esc to interrupt 常是暗色字，抹掉它们会把在忙判成等人
        above = "\x1b[2m(12s · ↑ 1.2k tokens · esc to interrupt)\x1b[22m"
        assert c.awaiting_input(_screen("❯\xa0", above=above)) is False

    def test_background_shell_still_running(self):
        assert c.awaiting_input(_screen("❯\xa0", above="1 shell still running")) is False

    def test_numbered_menu(self):
        assert c.awaiting_input(_screen("❯ 1. Yes")) is False

    def test_fatal_startup(self):
        assert (
            c.awaiting_input(_screen("❯\xa0", above="No conversation found with session ID x"))
            is False
        )
