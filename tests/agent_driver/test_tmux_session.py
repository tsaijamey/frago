"""Phase 0 spike 单测：不拉真实 tmux，用 fake runner 驱动 driver。

覆盖最大风险点——delta 取增量正确、done_signal 命中/超时兜底、driver extract
去 chrome、opencode 启动模态与单 Enter 提交由 driver 自动处理。
"""

from __future__ import annotations

import subprocess

import pytest

from frago.agent_driver.driver import (
    AgentDriver,
    LaunchCtx,
    PaneMatcher,
    load_driver,
)
from frago.agent_driver.tmux_session import (
    TmuxAgentSession,
    _compute_delta,
    _pane_tail,
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


# ── _pane_tail（启动失败时的可读末屏）─────────────────────────────
def test_pane_tail_surfaces_top_anchored_dialog() -> None:
    # 首启菜单渲染在上半区、下半区全是空行：直接取最后 20 行会得到一片空白。
    # _pane_tail 先滤空行，让菜单露出来。
    pane = "Is this a project you trust?\n❯ 1. Yes, I trust this folder\n  2. No, exit\n" + "\n" * 40
    tail = _pane_tail(pane)
    assert "Yes, I trust this folder" in tail
    assert tail.strip() != ""


def test_pane_tail_keeps_only_last_n_meaningful() -> None:
    pane = "\n".join(str(i) for i in range(30))
    assert _pane_tail(pane, lines=5) == "25\n26\n27\n28\n29"


def test_pane_tail_all_blank_is_empty() -> None:
    assert _pane_tail("\n\n   \n") == ""


# ── PaneMatcher ────────────────────────────────────────────────────
def test_pane_matcher_multiline() -> None:
    m = PaneMatcher(name="x", pattern=r"^DONE$")
    assert m.matches("foo\nDONE\nbar")
    assert not m.matches("not done")


# ── send(): done 命中 + extract ────────────────────────────────────
def _echo_driver(done_pattern: str = r"^DONE$") -> AgentDriver:
    return AgentDriver(
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
        "s1", _echo_driver(), cwd="/tmp", runner=fake, sleep=_no_sleep
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
        _echo_driver(),
        cwd="/tmp",
        runner=fake,
        sleep=_no_sleep,
        clock=lambda: next(clock),
    )
    result = sess.send("hi", timeout_s=1)
    assert result.status == "timeout"


# ── driver 注册表 ──────────────────────────────────────────────────
def test_load_driver_known_agents() -> None:
    assert load_driver("claude").agent_type == "claude"
    assert load_driver("opencode").agent_type == "opencode"


def test_load_driver_unknown_raises() -> None:
    with pytest.raises(KeyError):
        load_driver("nope")


# ── claude driver ──────────────────────────────────────────────────
def test_claude_submit_single_enter() -> None:
    # 提交后 pane 立即出现忙碌标记 → 提交验证一次通过，只发 1 个 Enter。
    driver = load_driver("claude")
    fake = FakeTmux(["(3s · esc to interrupt)"])
    sess = TmuxAgentSession("c", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
    driver.submit(sess, "hello")
    keys = fake.sent_keys()
    assert ["tmux", "send-keys", "-t", sess.tmux_name, "-l", "--", "hello"] in keys
    enter_count = sum(1 for k in keys if k[-1] == "Enter")
    assert enter_count == 1


def test_claude_submit_resends_enter_when_text_stuck() -> None:
    # 首个 Enter 被粘贴检测吞掉：8 轮验证里文本一直滞留输入框（非空、非忙），
    # 重发 Enter 后输入框回空 → 共 2 个 Enter。
    from frago.agent_driver.drivers.claude import _SUBMIT_VERIFY_POLLS

    stuck = "  ❯ hello still in box"
    panes = [stuck] * _SUBMIT_VERIFY_POLLS + ["  ❯ ", "(2s · esc to interrupt)"]
    driver = load_driver("claude")
    fake = FakeTmux(panes)
    sess = TmuxAgentSession("c2", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
    driver.submit(sess, "hello still in box")
    enter_count = sum(1 for k in fake.sent_keys() if k[-1] == "Enter")
    assert enter_count == 2


def test_claude_submit_enter_retry_capped_at_two() -> None:
    # 文本永远滞留（极端情况）：初始 1 次 + 重试上限 2 次 = 最多 3 个 Enter，不无限重发。
    driver = load_driver("claude")
    fake = FakeTmux(["  ❯ forever stuck"])
    sess = TmuxAgentSession("c3", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
    driver.submit(sess, "forever stuck")
    enter_count = sum(1 for k in fake.sent_keys() if k[-1] == "Enter")
    assert enter_count == 3


def test_claude_extract_drops_launch_echo() -> None:
    # 首启横幅的 shell 命令回显不是答案，整行剔除。
    driver = load_driver("claude")
    delta = "❯ claude --dangerously-skip-permissions --session-id abc\nthe answer"
    assert driver.extract(delta) == "the answer"


def test_claude_extract_strips_border_chrome() -> None:
    driver = load_driver("claude")
    delta = "╭─────╮\n│ > q │\nthe answer\n— for shortcuts"
    assert driver.extract(delta) == "the answer"


# ── opencode driver ────────────────────────────────────────────────
def test_opencode_single_enter_submit() -> None:
    # 当前 opencode（1.17.10 / 1.18.0 实测）单次 Enter 即提交；旧版的双 Enter 结论
    # 已推翻——多敲的一次会落进下一轮输入框留下脏字符。
    driver = load_driver("opencode")
    fake = FakeTmux(["PONG42 typed into box"])
    sess = TmuxAgentSession("o", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
    driver.submit(sess, "PONG42 typed into box")
    enter_count = sum(1 for k in fake.sent_keys() if k[-1] == "Enter")
    assert enter_count == 1


def test_opencode_done_signal_matches_build_footer() -> None:
    driver = load_driver("opencode")
    assert driver.done_signal.matches("▣ Build · claude-opus · 3.7s")
    assert not driver.done_signal.matches("still working…")


def test_opencode_update_modal_handler_sends_escape() -> None:
    driver = load_driver("opencode")
    handler = driver.exception_handlers[0]
    assert handler.trigger.matches("A new Update is available now")
    fake = FakeTmux(["pane"])
    sess = TmuxAgentSession("o2", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
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
    driver = load_driver("opencode")
    sess = TmuxAgentSession("o3", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
    sess.open(ready_timeout_s=5)
    assert sess.status == "ready"
    assert any(k[-1] == "Escape" for k in fake.sent_keys())
    # 验证 new-session 带固定尺寸。
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert "-x" in new_sess and "-y" in new_sess


def test_open_injects_conv_key_env_when_given() -> None:
    """conv_key 给定时 new-session 注入 ``-e FRAGO_CONV_KEY=<干净 conv_key>``。

    Phase 8（spec 20260627）：会话内 ``frago agent attach`` 据此 env 自解析归属哪个
    conv。conv_key 是干净键（带冒号），原样进 env、NEVER sanitize。
    """
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession(
        "k1",
        _echo_driver(),
        cwd="/tmp",
        conv_key="feishu:oc_abc",
        runner=fake,
        sleep=_no_sleep,
    )
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert "-e" in new_sess
    assert "FRAGO_CONV_KEY=feishu:oc_abc" in new_sess


def test_open_omits_conv_key_env_when_absent() -> None:
    """conv_key 缺省（WebUI native 等非 PA 路径）时不注入 FRAGO_CONV_KEY。"""
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession(
        "k2", _echo_driver(), cwd="/tmp", runner=fake, sleep=_no_sleep
    )
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert not any("FRAGO_CONV_KEY" in tok for tok in new_sess)


def test_open_injects_driver_session_env() -> None:
    """driver 声明的基线环境变量进 new-session -e（spec 20260725 Phase 4）。"""
    import dataclasses

    driver = dataclasses.replace(
        _echo_driver(), session_env=lambda _ctx: {"BASELINE": "on"}
    )
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession("e1", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert "BASELINE=on" in new_sess


def test_open_caller_env_overrides_driver_session_env() -> None:
    """调用方传的 env 覆盖 driver 基线的同名键——profile 版配置盖掉裸基线。"""
    import dataclasses

    driver = dataclasses.replace(
        _echo_driver(),
        session_env=lambda _ctx: {"CFG": "baseline", "ONLY_BASE": "1"},
    )
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession(
        "e2",
        driver,
        cwd="/tmp",
        env={"CFG": "from-profile"},
        runner=fake,
        sleep=_no_sleep,
    )
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert "CFG=from-profile" in new_sess
    assert "CFG=baseline" not in new_sess
    # 调用方没覆盖的基线键照常注入。
    assert "ONLY_BASE=1" in new_sess


def test_open_without_session_env_unchanged() -> None:
    """未声明 session_env 的 driver 行为完全不变：只有调用方给的 env。"""
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession(
        "e3",
        _echo_driver(),
        cwd="/tmp",
        env={"X": "1"},
        runner=fake,
        sleep=_no_sleep,
    )
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert new_sess.count("-e") == 1
    assert "X=1" in new_sess


def test_open_raises_on_startup_failure_instead_of_blind_ready() -> None:
    """ready_signal 永不命中 → open() 抛 TmuxStartupError，NEVER 盲标 ready。

    旧行为：等不到就绪也无条件 status='ready'，死会话进池被当活会话复用→永久静默。
    新行为：显式抛异常，带 pane 末尾便于排查，并 kill 掉这具半死的 tmux 壳。
    """
    from frago.agent_driver.tmux_session import TmuxStartupError

    # ready 信号是 "READY"，所有 pane 都不含它 → 等待超时。
    fake = FakeTmux(["booting…\nauth failed: invalid api key"])
    clock = iter([0.0, 10.0, 10.0])  # deadline 锚点、超时判定、（兜底）
    sess = TmuxAgentSession(
        "fail1",
        _echo_driver(),
        cwd="/tmp",
        runner=fake,
        sleep=_no_sleep,
        clock=lambda: next(clock),
    )
    with pytest.raises(TmuxStartupError) as ei:
        sess.open(ready_timeout_s=1)
    assert sess.status == "dead"
    assert "invalid api key" in ei.value.tail
    # 抛错前 kill 掉死壳，不留孤儿。
    assert any(c[1:2] == ["kill-session"] for c in fake.commands)


def test_launch_command_receives_ctx() -> None:
    driver = load_driver("claude")
    cmd = driver.launch_command(LaunchCtx(cwd="/w", session_id="s"))
    assert cmd.startswith("claude")
    assert "--dangerously-skip-permissions" in cmd


# ── 会话中途消失：抓屏退非零 MUST 收口，NEVER 裸 CalledProcessError ────────
# 现场：`frago agent start opencode --name k3trainer` 整页栈追踪，末行是
# `tmux capture-pane ... returned non-zero exit status 1`。opencode 在等就绪期间
# 自己退了，tmux 会话随之消失，轮询的抓屏退非零一路穿透，把已有的启动失败处置
# （末屏 + 清半死会话 + 登记）整个绕开。

_FLAKE = object()  # 这一拍抓屏失败，但会话仍活着
_GONE = object()  # 这一拍抓屏失败，且会话已消失（此后 has-session 一律退非零）


class MortalTmux:
    """会死的 tmux 替身：抓屏按脚本吐文本或退非零，has-session 反映存活。"""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.alive = True
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        verb = argv[1] if len(argv) > 1 else ""
        if verb == "has-session":
            if not self.alive:
                raise subprocess.CalledProcessError(1, argv)
            return ""
        if verb == "capture-pane":
            frame = self._script.pop(0) if len(self._script) > 1 else self._script[0]
            if frame is _GONE:
                self.alive = False
                raise subprocess.CalledProcessError(1, argv)
            if frame is _FLAKE:
                raise subprocess.CalledProcessError(1, argv)
            return frame
        return ""

    def capture_calls(self) -> int:
        return len([c for c in self.commands if c[1:2] == ["capture-pane"]])


def _mortal_session(name: str, script: list) -> TmuxAgentSession:
    return TmuxAgentSession(
        name,
        _echo_driver(),
        cwd="/tmp",
        runner=MortalTmux(script),
        sleep=_no_sleep,
    )


def test_open_converts_vanished_session_into_startup_error() -> None:
    """就绪前会话消失 → TmuxStartupError（带最后一份末屏），NEVER 裸异常。"""
    from frago.agent_driver.tmux_session import TmuxStartupError

    sess = _mortal_session("k3trainer", ["booting…\nopencode: fatal: cannot start", _GONE])
    with pytest.raises(TmuxStartupError) as ei:
        sess.open(ready_timeout_s=5)
    assert "fatal: cannot start" in ei.value.tail
    assert sess.status == "dead"


def test_open_vanished_without_any_pane_says_so() -> None:
    """一帧都没抓到就消失 → 消息里写明会话在就绪前已消失。"""
    from frago.agent_driver.tmux_session import TmuxStartupError

    sess = _mortal_session("k3-instant", [_GONE])
    with pytest.raises(TmuxStartupError) as ei:
        sess.open(ready_timeout_s=5)
    assert "会话在就绪前已消失" in ei.value.tail


def test_open_survives_transient_capture_failures_while_alive() -> None:
    """抓屏偶发失败但会话仍活 → 轮询照常继续，NEVER 误判为已死。"""
    runner = MortalTmux(["booting…", _FLAKE, _FLAKE, "READY"])
    sess = TmuxAgentSession(
        "flaky", _echo_driver(), cwd="/tmp", runner=runner, sleep=_no_sleep
    )
    sess.open(ready_timeout_s=5)
    assert sess.status == "ready"
    # 失败的两拍确实复核过存活，且轮询没有提前收场。
    assert any(c[1:2] == ["has-session"] for c in runner.commands)
    assert runner.capture_calls() >= 4
    # 清死壳的动作 NEVER 在会话仍活时发生。
    assert not any(c[1:2] == ["kill-session"] for c in runner.commands)


def test_send_returns_error_when_session_dies_mid_turn() -> None:
    """send 途中会话消失 → 本轮 status='error'，NEVER 抛异常。"""
    sess = _mortal_session("dies-mid-turn", ["> ", _GONE])
    result = sess.send("hi", timeout_s=5)
    assert result.status == "error"
    assert "disappeared mid-turn" in result.text
    assert sess.status == "dead"


def test_send_survives_transient_capture_failure_and_completes() -> None:
    """send 轮询期抓屏偶发失败但会话仍活 → 继续轮询到 done，照常返回 ok。"""
    runner = MortalTmux(["> ", _FLAKE, "> hi\nhello world\nDONE", "> hi\nhello world\nDONE"])
    sess = TmuxAgentSession(
        "flaky-turn", _echo_driver(), cwd="/tmp", runner=runner, sleep=_no_sleep
    )
    result = sess.send("hi", timeout_s=5)
    assert result.status == "ok"
    assert result.text == "hello world"
