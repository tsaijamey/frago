"""Phase 0 spike 单测：不拉真实 tmux，用 fake runner 驱动 driver。

覆盖最大风险点——delta 取增量正确、done_signal 命中/超时兜底、recipe extract
去 chrome、opencode 启动模态与双 Enter 提交由 recipe 自动处理。
"""

from __future__ import annotations

import pytest

from frago.agent_driver.recipe import (
    AgentRecipe,
    LaunchCtx,
    PaneMatcher,
    load_recipe,
)
from frago.agent_driver.tmux_session import (
    TmuxAgentSession,
    _compute_delta,
)


class FakeTmux:
    """脚本化的 tmux 替身：记录所有命令，按 capture 队列吐 pane 文本。"""

    def __init__(self, panes: list[str]) -> None:
        self._panes = list(panes)
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        if argv[:1] == ["tmux"] and argv[1:2] == ["capture-pane"]:
            return self._panes.pop(0) if len(self._panes) > 1 else self._panes[0]
        return ""

    def sent_keys(self) -> list[list[str]]:
        return [c for c in self.commands if c[1:2] == ["send-keys"]]


def _no_sleep(_: float) -> None:
    return None


# ── _compute_delta ─────────────────────────────────────────────────
def test_delta_takes_text_after_snapshot_anchor() -> None:
    # 末行 "> " 投喂后变 "> hi"，锚点回退到稳定行 "line B"。
    pre = "line A\nline B\n> "
    scrollback = "line A\nline B\n> hi\nanswer 1\nanswer 2\n> "
    assert _compute_delta(pre, scrollback) == "> hi\nanswer 1\nanswer 2\n> "


def test_delta_falls_back_to_full_when_anchor_missing() -> None:
    assert _compute_delta("zzz", "a\nb\nc") == "a\nb\nc"


def test_delta_empty_snapshot_returns_full() -> None:
    assert _compute_delta("   \n\n", "a\nb") == "a\nb"


def test_delta_uses_last_anchor_occurrence() -> None:
    # 稳定锚点重复出现时取最后一次之后的增量。
    pre = "MARK"
    scrollback = "MARK\nr1\nMARK\nr2"
    assert _compute_delta(pre, scrollback) == "r2"


# ── PaneMatcher ────────────────────────────────────────────────────
def test_pane_matcher_multiline() -> None:
    m = PaneMatcher(name="x", pattern=r"^DONE$")
    assert m.matches("foo\nDONE\nbar")
    assert not m.matches("not done")


# ── send(): done 命中 + extract ────────────────────────────────────
def _echo_recipe(done_pattern: str = r"^DONE$") -> AgentRecipe:
    return AgentRecipe(
        agent_type="echo",
        launch_command=lambda _ctx: "echo-agent",
        ready_signal=PaneMatcher(name="ready", pattern=r"READY"),
        submit=lambda s, _p: s.send_keys("Enter"),
        done_signal=PaneMatcher(name="done", pattern=done_pattern),
        extract=lambda d: "\n".join(
            ln
            for ln in d.splitlines()
            if ln and not ln.startswith(("#", ">")) and ln != "DONE"
        ).strip(),
    )


def test_send_returns_ok_and_extracts_delta() -> None:
    panes = [
        "prompt\n> ",  # pre-snapshot
        "prompt\n> hi\n#chrome\nhello world\nDONE",  # poll: done hit
        "prompt\n> hi\n#chrome\nhello world\nDONE",  # full scrollback
    ]
    fake = FakeTmux(panes)
    sess = TmuxAgentSession(
        "s1", _echo_recipe(), cwd="/tmp", runner=fake, sleep=_no_sleep
    )
    result = sess.send("hi", timeout_s=5)
    assert result.status == "ok"
    assert result.text == "hello world"
    assert "#chrome" not in result.text


def test_send_times_out_when_done_never_hits() -> None:
    clock = iter([0.0, 0.0, 10.0, 10.0])  # start, poll-check, deadline, end-stamp

    fake = FakeTmux(["> ", "no done here", "no done here"])
    sess = TmuxAgentSession(
        "s2",
        _echo_recipe(),
        cwd="/tmp",
        runner=fake,
        sleep=_no_sleep,
        clock=lambda: next(clock),
    )
    result = sess.send("hi", timeout_s=1)
    assert result.status == "timeout"


# ── recipe 注册表 ──────────────────────────────────────────────────
def test_load_recipe_known_agents() -> None:
    assert load_recipe("claude").agent_type == "claude"
    assert load_recipe("opencode").agent_type == "opencode"


def test_load_recipe_unknown_raises() -> None:
    with pytest.raises(KeyError):
        load_recipe("nope")


# ── claude recipe ──────────────────────────────────────────────────
def test_claude_submit_single_enter() -> None:
    recipe = load_recipe("claude")
    fake = FakeTmux(["pane"])
    sess = TmuxAgentSession("c", recipe, cwd="/tmp", runner=fake, sleep=_no_sleep)
    recipe.submit(sess, "hello")
    keys = fake.sent_keys()
    assert ["tmux", "send-keys", "-t", sess.tmux_name, "-l", "--", "hello"] in keys
    enter_count = sum(1 for k in keys if k[-1] == "Enter")
    assert enter_count == 1


def test_claude_extract_strips_border_chrome() -> None:
    recipe = load_recipe("claude")
    delta = "╭─────╮\n│ > q │\nthe answer\n— for shortcuts"
    assert recipe.extract(delta) == "the answer"


# ── opencode recipe ────────────────────────────────────────────────
def test_opencode_double_enter_submit() -> None:
    recipe = load_recipe("opencode")
    fake = FakeTmux(["PONG42 typed into box"])
    sess = TmuxAgentSession("o", recipe, cwd="/tmp", runner=fake, sleep=_no_sleep)
    recipe.submit(sess, "PONG42 typed into box")
    enter_count = sum(1 for k in fake.sent_keys() if k[-1] == "Enter")
    assert enter_count == 2


def test_opencode_done_signal_matches_build_footer() -> None:
    recipe = load_recipe("opencode")
    assert recipe.done_signal.matches("▣ Build · claude-opus · 3.7s")
    assert not recipe.done_signal.matches("still working…")


def test_opencode_update_modal_handler_sends_escape() -> None:
    recipe = load_recipe("opencode")
    handler = recipe.exception_handlers[0]
    assert handler.trigger.matches("A new Update is available now")
    fake = FakeTmux(["pane"])
    sess = TmuxAgentSession("o2", recipe, cwd="/tmp", runner=fake, sleep=_no_sleep)
    handler.action(sess)
    assert any(k[-1] == "Escape" for k in fake.sent_keys())


# ── open(): 就绪等待 + 一次性异常处理 ──────────────────────────────
def test_open_waits_ready_and_dismisses_modal() -> None:
    # launch 后第一屏带 Update 模态且已就绪，应触发 Esc。
    panes = [
        "Ask anything\nUpdate is available",  # ready poll hit
        "Ask anything\nUpdate is available",  # exception_handlers capture
    ]
    fake = FakeTmux(panes)
    recipe = load_recipe("opencode")
    sess = TmuxAgentSession("o3", recipe, cwd="/tmp", runner=fake, sleep=_no_sleep)
    sess.open(ready_timeout_s=5)
    assert sess.status == "ready"
    assert any(k[-1] == "Escape" for k in fake.sent_keys())
    # 验证 new-session 带固定尺寸。
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert "-x" in new_sess and "-y" in new_sess


def test_launch_command_receives_ctx() -> None:
    recipe = load_recipe("claude")
    cmd = recipe.launch_command(LaunchCtx(cwd="/w", session_id="s"))
    assert cmd.startswith("claude")
    assert "--dangerously-skip-permissions" in cmd
