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


# ── 不设时间上限（长任务不该被墙钟腰斩）────────────────────────────
def _long_running_session(timeout_kwargs: dict) -> object:
    """一轮跑很久才答完：每一拍时钟跳一小时，done 到第 4 拍才出现。

    时钟跳得比任何历史缺省（120 / 180 / 600 秒）都远，只要还有上限就必然判 timeout。
    """
    ticks = iter([i * 3600.0 for i in range(50)])
    panes = [
        "> ",  # pre-snapshot
        "still working",
        "still working",
        "still working",
        "answer here\nDONE",  # 第 4 拍才答完
        "answer here\nDONE",  # full scrollback
    ]
    sess = TmuxAgentSession(
        "long",
        _echo_driver(),
        cwd="/tmp",
        runner=FakeTmux(panes),
        sleep=_no_sleep,
        clock=lambda: next(ticks),
    )
    return sess.send("hi", **timeout_kwargs)


def test_send_without_timeout_never_gives_up_on_a_long_turn() -> None:
    # 缺省不传 timeout_s = 不设上限：跑几个小时也要等到本轮真正答完。
    result = _long_running_session({})
    assert result.status == "ok"
    assert result.text == "answer here"


def test_send_timeout_zero_means_no_cap() -> None:
    # 调用方显式传 0（CLI 的 `--timeout 0` 就是这条路）同样等于不设上限。
    assert _long_running_session({"timeout_s": 0}).status == "ok"


def test_send_positive_timeout_still_caps_the_turn() -> None:
    # 显式给正数仍然按上限判 timeout——opt-in 的卡表没有被一起拿掉。
    assert _long_running_session({"timeout_s": 60}).status == "timeout"


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
    # ``_SUBMIT_VERIFY_POLLS + 1``：多出来的那一帧是**按 Enter 前的安全闸**读的
    # （``_tui_is_gone``，见 claude driver 的 ``_submit``）。FakeTmux 是按位置吐 pane
    # 的，少给这一帧，"输入框回空"那一帧就会提前落进第一轮验证窗口里，本用例要测的
    # "首个 Enter 被吞、重发第二个"根本不会发生——测的就不再是它声称测的东西了。
    panes = [stuck] * (_SUBMIT_VERIFY_POLLS + 1) + ["  ❯ ", "(2s · esc to interrupt)"]
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


# ── 借住模式：agent 跑在别人的 tmux 会话里（虚拟桌面的终端就是这么用的）──────
# 那个会话不归本对象所有：open() 不建、close() 不杀，只请里面的 agent 退场。
# 杀了它等于把桌面的终端窗口连根拔掉——人正看着的画面直接黑掉。


class _HostTmux:
    """借住场景的 tmux 替身：会话早就在，前台跑什么由脚本说了算。"""

    def __init__(self, panes: list[str], foreground: list[str]) -> None:
        self._panes = list(panes)
        self._fg = list(foreground)
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.commands.append(argv)
        verb = argv[1] if len(argv) > 1 else ""
        if verb == "capture-pane":
            return self._panes.pop(0) if len(self._panes) > 1 else self._panes[0]
        if verb == "display-message":
            return (self._fg.pop(0) if len(self._fg) > 1 else self._fg[0]) + "\n"
        return ""

    def verbs(self) -> list[str]:
        return [c[1] for c in self.commands if len(c) > 1]


def test_attach_mode_enters_existing_session_without_new_session() -> None:
    host = _HostTmux(panes=["READY"], foreground=["zsh"])
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/home/me", runner=host, sleep=_no_sleep,
        env={"FRAGO_AGENT_ROLE": "worker"}, tmux_target="frago-stage",
    )
    sess.open(ready_timeout_s=5)
    assert sess.status == "ready"
    assert sess.tmux_name == "frago-stage"
    assert "new-session" not in host.verbs()
    typed = [c for c in host.commands if c[1:2] == ["send-keys"] and "-l" in c][0]
    line = typed[-1]
    # 先进工作目录，再把环境变量以前缀方式带上启动命令——借住的会话早起好了，
    # new-session -e 那条路不存在。
    assert line.startswith("cd /home/me && clear && env FRAGO_AGENT_ROLE=worker echo-agent")
    assert all(c[3] == "frago-stage" for c in host.commands if c[1] == "send-keys")


def test_attach_mode_refuses_a_busy_foreground() -> None:
    from frago.agent_driver.tmux_session import TmuxStartupError

    host = _HostTmux(panes=["whatever"], foreground=["2.1.250"])
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/tmp", runner=host, sleep=_no_sleep, tmux_target="frago-stage"
    )
    with pytest.raises(TmuxStartupError) as ei:
        sess.open(ready_timeout_s=5)
    assert "不是空闲的 shell" in ei.value.tail
    # 拒绝之后也 NEVER 杀主人的会话。
    assert "kill-session" not in host.verbs()


def test_attach_mode_close_quits_agent_but_never_kills_session() -> None:
    # 前台先是 agent，两连击 C-c 之后回到 shell。
    host = _HostTmux(panes=["READY"], foreground=["2.1.250", "2.1.250", "zsh"])
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/tmp", runner=host, sleep=_no_sleep, tmux_target="frago-stage"
    )
    sess.close()
    assert sess.status == "dead"
    assert "kill-session" not in host.verbs()
    keys = [c[-1] for c in host.commands if c[1:2] == ["send-keys"]]
    # 退出是两连击：两个 C-c 连着发（中间只隔一拍），不是发一个等六秒再发一个。
    assert keys[:2] == ["C-c", "C-c"]
    # 回到 shell 之后不再发任何键：C-d 落在空 shell 上会让整个会话消失。
    assert "C-d" not in keys and "/exit" not in keys


def test_attach_mode_close_escalates_to_exit_command_then_ctrl_d() -> None:
    # C-c 两连击没让它退（还在跑），再打 /exit，还不退再 C-d 两连击。
    # 前台：C-c 步骤内 1 次 + 轮询 20 次都还是 agent，/exit 步骤内 1 次 + 20 次，C-d 步骤后回 shell。
    fg = ["2.1.250"] * (1 + 20 + 1 + 20 + 1) + ["zsh"]
    host = _HostTmux(panes=["READY"], foreground=fg)
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/tmp", runner=host, sleep=_no_sleep, tmux_target="frago-stage"
    )
    sess.close()
    sent = [c for c in host.commands if c[1:2] == ["send-keys"]]
    keys = [c[-1] for c in sent]
    assert keys[:2] == ["C-c", "C-c"]
    assert "/exit" in keys and keys[keys.index("/exit") + 1] == "Enter"
    assert keys[-2:] == ["C-d", "C-d"]
    assert "kill-session" not in host.verbs()


def test_attach_mode_close_does_nothing_when_shell_already_in_front() -> None:
    host = _HostTmux(panes=["READY"], foreground=["zsh"])
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/tmp", runner=host, sleep=_no_sleep, tmux_target="frago-stage"
    )
    sess.close()
    assert not any(c[1:2] == ["send-keys"] for c in host.commands)
    assert "kill-session" not in host.verbs()


def test_attach_mode_close_stops_when_foreground_is_unknown() -> None:
    # 问不出前台是什么 → 停手。宁可留一个开着的 TUI 给人关，也不拿主人的会话冒险。
    host = _HostTmux(panes=["READY"], foreground=[""])
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/tmp", runner=host, sleep=_no_sleep, tmux_target="frago-stage"
    )
    sess.close()
    assert not any(c[1:2] == ["send-keys"] for c in host.commands)


def test_attach_mode_startup_failure_never_kills_host_session() -> None:
    from frago.agent_driver.tmux_session import TmuxStartupError

    host = _HostTmux(panes=["never ready"], foreground=["zsh"])
    clock = iter([0.0, 10.0, 10.0])
    sess = TmuxAgentSession(
        "s", _echo_driver(), cwd="/tmp", runner=host, sleep=_no_sleep,
        clock=lambda: next(clock), tmux_target="frago-stage",
    )
    with pytest.raises(TmuxStartupError):
        sess.open(ready_timeout_s=1)
    assert "kill-session" not in host.verbs()


def test_concurrent_sends_do_not_interleave_keystrokes() -> None:
    """两个线程同时投喂同一场会话：打字 + 回车那一段互斥，两句话不会拼成一句。"""
    import threading

    order: list[str] = []
    gate = threading.Event()

    def slow_submit(s: TmuxAgentSession, p: str) -> None:
        order.append(f"begin {p}")
        gate.wait(timeout=2)
        s.send_text(p)
        s.send_keys("Enter")
        order.append(f"end {p}")

    driver = _echo_driver()
    driver = __import__("dataclasses").replace(driver, submit=slow_submit)
    fake = FakeTmux(["> ", "a\nDONE", "a\nDONE"])
    sess = TmuxAgentSession("s", driver, cwd="/tmp", runner=fake, sleep=_no_sleep)

    t1 = threading.Thread(target=lambda: sess.send("one", timeout_s=5))
    t2 = threading.Thread(target=lambda: sess.send("two", timeout_s=5))
    t1.start()
    t2.start()
    gate.set()
    t1.join(5)
    t2.join(5)
    # 每个 begin 后面紧跟它自己的 end：没有第二个 begin 插进来。
    for i in range(0, len(order), 2):
        assert order[i].startswith("begin ")
        assert order[i + 1] == order[i].replace("begin", "end")


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


# ── has_live_agent：三态，不是布尔 ──────────────────────────────────
class _PaneCommandTmux:
    """只回答 display-message 的替身：pane 前台跑的是什么，由用例说了算。"""

    def __init__(self, command: str | None) -> None:
        self._command = command

    def __call__(self, argv: list[str]) -> str:
        if argv[1:2] == ["display-message"]:
            if self._command is None:
                raise RuntimeError("tmux 这一拍不答")
            return self._command + "\n"
        return ""


def _session_with_pane_command(command: str | None):
    from frago.agent_driver.driver import load_driver

    return TmuxAgentSession(
        session_id="sid",
        driver=load_driver("opencode"),
        cwd="/tmp",
        runner=_PaneCommandTmux(command),
        sleep=_no_sleep,
    )


def test_a_running_agent_reports_true() -> None:
    """claude 把进程名设成自己的版本号——实测 pane_current_command 报的就是这个。

    所以判据只能是"前台跑的是不是登录 shell"，NEVER 按名字白名单认 agent：那要么
    每接一家改一次表，要么在 agent 换个版本号时集体失灵。
    """
    assert _session_with_pane_command("2.1.250").has_live_agent() is True
    assert _session_with_pane_command("node").has_live_agent() is True


def test_a_bare_shell_reports_false() -> None:
    """agent 退出后 tmux 窗口不会跟着消失，留下的是一个停在提示符上的空壳。"""
    for shell in ("zsh", "bash", "-zsh", "fish", "login"):
        assert _session_with_pane_command(shell).has_live_agent() is False, shell


def test_an_unanswerable_query_reports_none_not_false() -> None:
    """问不出来必须是第三态。

    两个调用点的安全方向正好相反：复用自己那场会话时，一次问不出来当成"死了"会把
    健康的常驻会话杀了重建（白等一次冷启动）；接管来路不明的孤儿时，当成"活着"会把
    用户的话打进一个没人接的窗口（永久静默）。合成布尔，必然在其中一边犯错。
    """
    assert _session_with_pane_command(None).has_live_agent() is None
    assert _session_with_pane_command("").has_live_agent() is None


# ── 原生 Windows 兼容（win32 tmux 移植版，2026-09-24 实测 3.6a-win32）────────
def test_open_on_windows_omits_dash_c_and_cds_in_shell(monkeypatch) -> None:
    """Windows 上 new-session 不带 ``-c``（移植版带 -c 一律 spawn failed）。

    工作目录改经 shell 落地：投喂的启动命令前缀 ``cd '<cwd>' &&``，与借住模式
    同一套做法。
    """
    from frago.agent_driver import tmux_session

    monkeypatch.setattr(tmux_session, "_WINDOWS", True)
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession(
        "w1", _echo_driver(), cwd="E:\Lenovo", runner=fake, sleep=_no_sleep
    )
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert "-c" not in new_sess
    # 启动文本是第一条 -l 字面投喂，形如 cd 'E:\Lenovo' && echo-agent。
    literal = [c for c in fake.sent_keys() if "-l" in c]
    assert literal and literal[0][-1] == "cd 'E:\Lenovo' && echo-agent"


def test_open_off_windows_keeps_dash_c(monkeypatch) -> None:
    """Linux/macOS 主路径不变：-c 原样带，启动命令不加 cd 前缀。"""
    from frago.agent_driver import tmux_session

    monkeypatch.setattr(tmux_session, "_WINDOWS", False)
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession(
        "w2", _echo_driver(), cwd="/tmp", runner=fake, sleep=_no_sleep
    )
    sess.open(ready_timeout_s=5)
    new_sess = [c for c in fake.commands if c[1:2] == ["new-session"]][0]
    assert new_sess[new_sess.index("-c") + 1] == "/tmp"
    literal = [c for c in fake.sent_keys() if "-l" in c]
    assert literal and literal[0][-1] == "echo-agent"


def test_a_truncated_windows_path_reports_none_not_true() -> None:
    """win32 移植版把前台进程名报成被空格截断的路径（bash 报 ``C:\Program``）。

    认不出本体时按"问不出来"降级：过 shell 名单必然判 True（路径不含纯 shell 名），
    把"只剩 shell 壳"误判成"agent 还活着"。斜杠与盘符两种形态都要拦。
    """
    assert _session_with_pane_command("C:\Program").has_live_agent() is None
    assert _session_with_pane_command("C:/Users/x/AppData").has_live_agent() is None
    assert _session_with_pane_command("/usr/bin/bash").has_live_agent() is None


def test_default_runner_decodes_utf8_explicitly(monkeypatch) -> None:
    """tmux 输出按 UTF-8 解码，不随系统 locale（Windows 默认 GBK 会解崩 pane 文本）。

    解码失败时 reader 线程把 stdout 记成 None，读屏返回 None 后一切 pane 正则判断
    全线 TypeError。
    """
    from frago.agent_driver.tmux_session import _default_runner

    captured: dict = {}

    class _Proc:
        stdout = "pane 文本"

    def _fake_run(argv, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr("frago.agent_driver.tmux_session.subprocess.run", _fake_run)
    assert _default_runner(["tmux", "capture-pane"]) == "pane 文本"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_send_text_non_ascii_on_ansi_windows_raises_instead_of_mojibake(
    monkeypatch,
) -> None:
    """win32 移植版按系统 ANSI 代码页收窄 argv，非 ASCII 必坏且不可逆（实测中文→
    U+FFFD、emoji→``?``）。与其把乱码喂给 agent，不如当场报错并给出切系统 UTF-8
    的修复指引；纯 ASCII 不受影响照常发送。
    """
    from frago.agent_driver import tmux_session
    from frago.agent_driver.tmux_session import TmuxTextEncodingError

    monkeypatch.setattr(tmux_session, "_WINDOWS", True)
    monkeypatch.setattr(tmux_session, "_ansi_codepage", lambda: 936)
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession("w3", _echo_driver(), cwd="/tmp", runner=fake, sleep=_no_sleep)
    with pytest.raises(TmuxTextEncodingError, match="UTF-8"):
        sess.send_text("你好 world")
    # 同样的代码页下，纯 ASCII 文本不受影响。
    sess.send_text("plain ascii only")
    assert fake.sent_keys()


def test_send_text_non_ascii_passes_when_system_ansi_is_utf8(monkeypatch) -> None:
    """系统 ANSI 代码页已是 65001（"Beta: Unicode UTF-8"）时收窄产物即正确 UTF-8，
    非 ASCII 照常放行——闸门只在确知会坏的代码页上拦。代码页问不出来（None）同样
    放行：真实 Windows 上 GetACP 不会失败，这个分支只服务测试/非 Windows 环境。
    """
    from frago.agent_driver import tmux_session

    monkeypatch.setattr(tmux_session, "_WINDOWS", True)
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession("w4", _echo_driver(), cwd="/tmp", runner=fake, sleep=_no_sleep)
    for cp in (65001, None):
        monkeypatch.setattr(tmux_session, "_ansi_codepage", lambda cp=cp: cp)
        sess.send_text("中文 mixed")
    assert any("中文 mixed" in c for c in fake.sent_keys())


def test_send_text_off_windows_never_gates(monkeypatch) -> None:
    """非 Windows 平台与代码页无关，任何文本直接走发送。"""
    from frago.agent_driver import tmux_session

    monkeypatch.setattr(tmux_session, "_WINDOWS", False)
    # Linux 上 _ansi_codepage 直接短路返回 None，但闸门先看 _WINDOWS，根本不会问。
    fake = FakeTmux(["READY"])
    sess = TmuxAgentSession("w5", _echo_driver(), cwd="/tmp", runner=fake, sleep=_no_sleep)
    sess.send_text("中文 mixed")
    assert any("中文 mixed" in c for c in fake.sent_keys())
