"""opencode driver 的信号与身份认领单测（spec 20260725 Phase 1）。

用 fake tmux 替身，不拉真实 tmux、不跑真实 opencode。会话库由 conftest 隔离到
临时路径，需要真实读库行为的用例自建临时库。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.agent_driver.driver import LaunchCtx, load_driver
from frago.agent_driver.drivers import opencode as opencode_driver
from frago.agent_driver.tmux_session import TmuxAgentSession
from frago.session import opencode_store
from tests.agent_driver.test_tmux_session import FakeTmux

_SCHEMA = """
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    time_created integer NOT NULL
);
CREATE TABLE message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
CREATE TABLE part (
    id text PRIMARY KEY,
    message_id text NOT NULL,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
"""

# 认领的时间窗锚在提交前一刻（真实毫秒时钟），故测试库里的会话行必须"落在未来"
# 才稳定命中，否则用例会随执行时刻抖动。
_FUTURE_MS = 4_000_000_000_000


@pytest.fixture
def live_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """一个可写的临时会话库（driver 侧仍然只读打开它）。"""
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    yield conn
    conn.close()


def _add_session(conn: sqlite3.Connection, sid: str, directory: str, created: int) -> None:
    conn.execute(
        "INSERT INTO session (id, directory, title, time_created) VALUES (?,?,'',?)",
        (sid, directory, created),
    )
    conn.commit()


def _add_message(
    conn: sqlite3.Connection, mid: str, sid: str, created: int, data: dict[str, Any]
) -> None:
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, data) VALUES (?,?,?,?)",
        (mid, sid, created, json.dumps(data)),
    )
    conn.commit()


def _add_part(
    conn: sqlite3.Connection, pid: str, mid: str, sid: str, created: int, data: dict[str, Any]
) -> None:
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?,?,?,?,?)",
        (pid, mid, sid, created, json.dumps(data)),
    )
    conn.commit()


class _VirtualClock:
    """睡多久就把时钟推进多久的虚拟时钟。

    落地校验按**时间截止**轮询而不是数拍数，真实时钟配上不睡的 sleep 会让用例空转
    满整个窗口的真实时间。这里让 sleep 只推进虚拟时钟，用例因此能表达"第 8 秒才
    出现"这种时序而不真的等 8 秒。
    """

    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _session(fake: FakeTmux, session_id: str = "o1", **kw: Any) -> TmuxAgentSession:
    clock = kw.pop("clock", None) or _VirtualClock()
    return TmuxAgentSession(
        session_id,
        load_driver("opencode"),
        cwd=kw.pop("cwd", "/w"),
        runner=fake,
        sleep=kw.pop("sleep", clock.sleep),
        clock=clock,
        **kw,
    )


def _enters(fake: FakeTmux) -> int:
    return sum(1 for k in fake.sent_keys() if k[-1] == "Enter")


class _SwallowingTmux(FakeTmux):
    """前若干次 Enter 被粘贴检测吞掉的 tmux 替身。

    复刻真实时序：吞掉期间整段提示词一直卡在输入框里，真正落地的那一次之后输入框
    才清空、提示词回显进消息区。
    """

    def __init__(self, prompt: str, swallow: int) -> None:
        super().__init__([_stuck_pane(prompt)])
        self._prompt = prompt
        self._swallow = swallow
        self.enters = 0

    def __call__(self, argv: list[str]) -> str:
        if argv[1:2] == ["send-keys"] and argv[-1] == "Enter":
            self.enters += 1
            if self.enters > self._swallow:
                self._panes = [_submitted_pane(self._prompt)]
        return super().__call__(argv)


class _ClockedTmux(FakeTmux):
    """按虚拟时钟切屏的 tmux 替身：到点之前给前一张，到点之后给后一张。"""

    def __init__(
        self, before: str, after: str, clock: _VirtualClock, switch_at: float
    ) -> None:
        super().__init__([before])
        self._before = before
        self._after = after
        self._clock = clock
        self._switch_at = switch_at
        self.enters = 0

    def __call__(self, argv: list[str]) -> str:
        self._panes = [
            self._after if self._clock.now >= self._switch_at else self._before
        ]
        if argv[1:2] == ["send-keys"] and argv[-1] == "Enter":
            self.enters += 1
        return super().__call__(argv)


# ── 提交：单次 Enter ────────────────────────────────────────────────
def test_submit_sends_exactly_one_enter() -> None:
    """当前 opencode 单次 Enter 即提交；多敲的一次会落进下一轮输入框。"""
    driver = load_driver("opencode")
    fake = FakeTmux(["PONG42 typed into box"])
    sess = _session(fake)
    driver.submit(sess, "PONG42 typed into box")
    assert sum(1 for k in fake.sent_keys() if k[-1] == "Enter") == 1


def test_submit_resends_text_when_not_rendered_in_box() -> None:
    """渲染时序：重抓 pane 没看到文本就补发一次，Enter 仍只发一次。"""
    driver = load_driver("opencode")
    fake = FakeTmux(["empty box"])
    sess = _session(fake)
    driver.submit(sess, "hello there")
    literal = [k for k in fake.sent_keys() if "-l" in k and k[-1] == "hello there"]
    assert len(literal) == 2
    assert sum(1 for k in fake.sent_keys() if k[-1] == "Enter") == 1


# ── 启动命令 ────────────────────────────────────────────────────────
def test_launch_bare_when_unbound() -> None:
    driver = load_driver("opencode")
    assert driver.launch_command(LaunchCtx(cwd="/w", session_id="fresh")) == "opencode"


def test_launch_resumes_bound_session() -> None:
    opencode_store.put_binding("known", "ses_abc", "/w")
    driver = load_driver("opencode")
    cmd = driver.launch_command(LaunchCtx(cwd="/w", session_id="known"))
    assert cmd == "opencode -s ses_abc"


def test_launch_falls_back_to_bare_when_bound_session_deleted(
    live_db: sqlite3.Connection,
) -> None:
    """绑定指向已被用户删除的会话 → 清掉映射、裸起。

    否则 ``opencode -s <已删除 id>`` 立刻退出，等满超时才失败，且下次启动再犯。
    """
    opencode_store.put_binding("stale", "ses_deadbeef", "/w")
    _add_session(live_db, "ses_other", "/w", 1)
    driver = load_driver("opencode")
    assert driver.launch_command(LaunchCtx(cwd="/w", session_id="stale")) == "opencode"
    assert opencode_store.get_binding("stale") is None


def test_launch_keeps_binding_when_db_unreadable() -> None:
    """库不可读时保留绑定、照旧续接——读失败不是"会话没了"的证据。"""
    opencode_store.put_binding("kept", "ses_keep", "/w")
    driver = load_driver("opencode")
    cmd = driver.launch_command(LaunchCtx(cwd="/w", session_id="kept"))
    assert cmd == "opencode -s ses_keep"
    assert opencode_store.get_binding("kept") == "ses_keep"


def test_launch_native_deleted_session_falls_back_without_writing_binding(
    live_db: sqlite3.Connection,
) -> None:
    """native id 也可能已被删除；回落裸起，且 NEVER 写映射文件。"""
    _add_session(live_db, "ses_present", "/w", 1)
    driver = load_driver("opencode")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/w", session_id="ses_gone", native_session_id=True)
    )
    assert cmd == "opencode"
    assert opencode_store.get_binding("ses_gone") is None
    assert not opencode_store.BINDINGS_PATH.exists()


def test_launch_native_resumes_when_session_present(
    live_db: sqlite3.Connection,
) -> None:
    _add_session(live_db, "ses_native", "/w", 1)
    driver = load_driver("opencode")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/w", session_id="ses_native", native_session_id=True)
    )
    assert cmd == "opencode -s ses_native"
    assert not opencode_store.BINDINGS_PATH.exists()


def test_launch_native_session_id_used_verbatim() -> None:
    """native：调用方给的就是 opencode 原生 id，直接续接、不查映射。"""
    driver = load_driver("opencode")
    cmd = driver.launch_command(
        LaunchCtx(cwd="/w", session_id="ses_native", native_session_id=True)
    )
    assert cmd == "opencode -s ses_native"


# ── 身份认领 ────────────────────────────────────────────────────────
def test_submit_claims_session_and_persists_binding(live_db: sqlite3.Connection) -> None:
    _add_session(live_db, "ses_claimed", "/w", _FUTURE_MS)
    driver = load_driver("opencode")
    fake = FakeTmux(["hi"])
    sess = _session(fake, "claim-me")
    driver.submit(sess, "hi")
    assert opencode_store.get_binding("claim-me") == "ses_claimed"


def test_submit_ignores_session_in_other_directory(live_db: sqlite3.Connection) -> None:
    _add_session(live_db, "ses_elsewhere", "/other", _FUTURE_MS)
    driver = load_driver("opencode")
    fake = FakeTmux(["hi"])
    sess = _session(fake, "no-claim")
    driver.submit(sess, "hi")
    assert opencode_store.get_binding("no-claim") is None


def test_submit_does_not_reclaim_when_already_bound(live_db: sqlite3.Connection) -> None:
    """映射一旦建立不再重认，否则两个会话的记录会互串。"""
    opencode_store.put_binding("bound", "ses_first", "/w")
    _add_session(live_db, "ses_second", "/w", _FUTURE_MS)
    driver = load_driver("opencode")
    fake = FakeTmux(["hi"])
    sess = _session(fake, "bound")
    driver.submit(sess, "hi")
    assert opencode_store.get_binding("bound") == "ses_first"


def test_submit_survives_unclaimable_turn() -> None:
    """库都不存在时提交照常完成，NEVER 因认领失败让本轮失败。"""
    driver = load_driver("opencode")
    fake = FakeTmux(["hi"])
    sess = _session(fake, "orphan")
    driver.submit(sess, "hi")
    assert sum(1 for k in fake.sent_keys() if k[-1] == "Enter") == 1
    assert opencode_store.get_binding("orphan") is None


# ── 提交落地校验 ────────────────────────────────────────────────────
# 判据只有一个：提示词的尾段还在不在输入框里。会话库那边等的东西（认领 / 本轮用户
# 消息）延迟随提示词长度浮动到几十秒，掺进落地判定就是把赌局搬进提交路径。


# 一条够长、尾段有判别力的提示词（现场故障就是长提示词触发的）。
_PROMPT = "请把这份任务书通读一遍再动手，最后回答我：2 的十次方是多少 PONG42"


def _stuck_pane(prompt: str) -> str:
    """整段提示词还卡在输入框里的 pane（每行以 ``┃`` 起头）。"""
    return f"┃\n┃  {prompt}\n┃\n┃  Build · DeepSeek V4 Flash DeepSeek\n╹▀▀▀▀▀▀▀\n"


def _submitted_pane(prompt: str) -> str:
    """已提交的 pane：提示词回显进消息区（不带 ``┃``），输入框空着。"""
    return (
        f"     {prompt}\n"
        "\n"
        "     + Thought: 395ms\n"
        "┃\n"
        "┃\n"
        "┃  Build · DeepSeek V4 Flash DeepSeek\n"
        "╹▀▀▀▀▀▀▀\n"
    )


def _seed_bound_turn(conn: sqlite3.Connection, frago_id: str, sid: str) -> None:
    """一个已有绑定、已答完一轮的会话——第二轮的起点。"""
    opencode_store.put_binding(frago_id, sid, "/w")
    _add_session(conn, sid, "/w", 1)
    _add_message(conn, "m_u1", sid, 10, {"role": "user", "parentID": None})
    _add_message(
        conn, "m_a1", sid, 20, {"role": "assistant", "parentID": "m_u1", "finish": "stop"}
    )


def test_submit_first_turn_lands_on_empty_input_box(live_db: sqlite3.Connection) -> None:
    """首轮：输入框已空即判落地，只按一次 Enter；会话行已在库里就顺手认掉。"""
    _add_session(live_db, "ses_first", "/w", _FUTURE_MS)
    driver = load_driver("opencode")
    fake = FakeTmux(["hi"])
    driver.submit(_session(fake, "first-turn"), "hi")
    assert opencode_store.get_binding("first-turn") == "ses_first"
    assert _enters(fake) == 1


def test_submit_ignores_session_store_lag(live_db: sqlite3.Connection) -> None:
    """第二轮：会话库整段时间毫无动静，输入框空着就是落地 → 恰好一次 Enter。

    落地判定 MUST 与会话库彻底解耦：库里那条用户消息实测可以晚到 33 秒，拿它当
    判据就会把"库还没写完"误判成"回车没落地"，补发的空回车落进下一轮。
    """
    _seed_bound_turn(live_db, "t2", "ses_t")
    driver = load_driver("opencode")
    fake = FakeTmux([_submitted_pane(_PROMPT)])
    driver.submit(_session(fake, "t2"), _PROMPT)
    assert _enters(fake) == 1
    # 库里仍是上一轮那条用户消息——本轮压根没等过它。
    turn = opencode_store.latest_turn("ses_t")
    assert turn is not None
    assert turn.parent_id == "m_u1"


def test_submit_resends_enter_when_swallowed() -> None:
    """第一次 Enter 被粘贴检测吞掉：文本仍卡在输入框 → 重发；框一空即停。"""
    driver = load_driver("opencode")
    fake = _SwallowingTmux(_PROMPT, swallow=1)
    driver.submit(_session(fake, "t3"), _PROMPT)
    # 第二次 Enter 落地即停：既证明重发过，也证明框空之后不再多敲。
    assert fake.enters == 2


def test_submit_gives_up_after_retry_budget(live_db: sqlite3.Connection) -> None:
    """文本一直卡着：Enter 次数不超过 1 + 重试上限，照常返回不抛。"""
    _seed_bound_turn(live_db, "t4", "ses_stuck")
    driver = load_driver("opencode")
    fake = _SwallowingTmux(_PROMPT, swallow=99)
    driver.submit(_session(fake, "t4"), _PROMPT)
    assert fake.enters == 3
    # 绑定没被改写——认领只读会话库，NEVER 顺手改已有状态。
    assert opencode_store.get_binding("t4") == "ses_stuck"


def test_no_fixed_claim_window_remains() -> None:
    """认领那边 MUST 一个固定窗口常量都不剩；结算窗口只覆盖 TUI 重绘，MUST 短。"""
    assert not hasattr(opencode_driver, "_CLAIM_POLLS")
    assert not hasattr(opencode_driver, "_CLAIM_WINDOW_S")
    assert not hasattr(opencode_driver, "_SUBMIT_VERIFY_WINDOW_S")
    assert opencode_driver._INPUT_SETTLE_WINDOW_S <= 5.0


def test_settle_window_absorbs_a_late_repaint() -> None:
    """回车之后输入框晚一拍才重绘：结算窗口内看见框空了就不补发。

    立刻抓屏可能撞上尚未重绘的那一帧；那一帧上补发的空回车会落进下一轮，把下一次
    send 变成什么都不返回。
    """
    clock = _VirtualClock()
    fake = _ClockedTmux(_stuck_pane(_PROMPT), _submitted_pane(_PROMPT), clock, 0.5)
    driver = load_driver("opencode")
    driver.submit(_session(fake, "repaint", sleep=clock.sleep, clock=clock), _PROMPT)
    assert fake.enters == 1


# ── 认领贯穿整轮：没有任何固定窗口 ──────────────────────────────────
# 实测「按下回车 → 会话行出现在会话库」：31 字 0.4 秒、2176 字 4.8 秒、3519 字 33 秒。
# 没有哪个固定秒数是安全的，故认领改挂在整轮生命周期上：起算点锚在提交前，之后每次
# 完成探针再试一次，会话行什么时候出现就什么时候认到。


def _seed_answered_turn(conn: sqlite3.Connection, sid: str, text: str) -> None:
    """一条已答完的会话：会话行 + 用户消息 + finish=stop 的助手消息 + 正文片段。"""
    _add_session(conn, sid, "/w", _FUTURE_MS)
    _add_message(conn, "m_u", sid, 10, {"role": "user", "parentID": None})
    _add_message(
        conn,
        "m_a",
        sid,
        20,
        {
            "role": "assistant",
            "parentID": "m_u",
            "finish": "stop",
            "time": {"created": 20, "completed": 25},
        },
    )
    _add_part(conn, "pt", "m_a", sid, 21, {"type": "text", "text": text})


def test_probe_claims_session_row_appearing_long_after_submit(
    live_db: sqlite3.Connection,
) -> None:
    """会话行第 45 秒才出现（远超任何固定窗口）：探针在下一次调用里认到并落盘。

    认到之后本轮继续走权威判定，答案取自会话库而不是读屏——现场那次失败就是这条
    链断了，交出去的是 TUI 的页脚与状态栏。
    """
    clock = _VirtualClock()
    born: list[str] = []

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= 45.0 and not born:
            _seed_answered_turn(live_db, "ses_late", "2 的十次方是 1024")
            born.append("ses_late")

    fake = FakeTmux([_submitted_pane(_PROMPT)])
    sess = _session(fake, "late-row", sleep=sleep, clock=clock)
    result = sess.send(_PROMPT, timeout_s=600.0)

    assert opencode_store.get_binding("late-row") == "ses_late"
    assert result.status == "ok"
    assert result.text == "2 的十次方是 1024"
    assert clock.now >= 45.0
    # 整轮只按过一次 Enter：认领认不到 NEVER 触发补发。
    assert _enters(fake) == 1
    # 认到之后锚点即刻清掉，不留残留。
    assert sess not in opencode_driver._CLAIM_ANCHORS


@pytest.mark.usefixtures("live_db")
def test_turn_completes_when_session_row_never_appears() -> None:
    """会话行始终不出现：本轮照常跑完（退回读屏），不抛异常、不补发 Enter。"""
    clock = _VirtualClock()
    done_pane = "     banana\n\n     ▣  Build · DeepSeek V4 Flash · 1.7s\n┃\n"
    fake = _ClockedTmux(_submitted_pane(_PROMPT), done_pane, clock, 5.0)
    sess = _session(fake, "no-row", sleep=clock.sleep, clock=clock)
    result = sess.send(_PROMPT, timeout_s=600.0)

    assert result.status == "ok"
    assert "banana" in result.text
    assert opencode_store.get_binding("no-row") is None
    assert fake.enters == 1


def test_probe_does_not_claim_when_already_bound(
    live_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已有绑定：探针一次认领查询都不做——重认会让两个会话的记录互串。"""
    _seed_bound_turn(live_db, "bound-probe", "ses_bound")
    calls: list[Any] = []

    def _spy(*args: Any) -> None:
        calls.append(args)
        return None

    monkeypatch.setattr(opencode_store, "claim_session", _spy)
    driver = load_driver("opencode")
    verdict = driver.completion_probe(_session(FakeTmux(["pane"]), "bound-probe"))
    assert verdict is not None
    assert calls == []


def test_claim_anchor_stays_at_first_submit(live_db: sqlite3.Connection) -> None:
    """锚点只记首次提交那一刻：会话行是首轮建的，锚点往后挪就再也罩不住它。"""
    driver = load_driver("opencode")
    sess = _session(FakeTmux([_submitted_pane("hi")]), "anchor")
    driver.submit(sess, "hi")  # 首轮：库里还没有会话行，认不到
    assert opencode_store.get_binding("anchor") is None
    first = opencode_driver._CLAIM_ANCHORS[sess]

    # 会话行恰好落在首轮那个锚点上：第二轮提交之后仍认得到 = 锚点没被刷新过。
    _add_session(live_db, "ses_anchor", "/w", first)
    driver.submit(sess, "again")
    assert opencode_store.get_binding("anchor") == "ses_anchor"
    assert sess not in opencode_driver._CLAIM_ANCHORS


# ── 空输入框闸门：补发 Enter 之前 MUST 有正面证据 ────────────────────
# 上一版直接采信会话库的否定判据，认领超窗就补发两次 Enter；那时输入框其实已空，
# 两次回车变成两个空提交落进下一轮，下一次 send 什么都不返回。


def test_no_resend_when_prompt_left_the_input_box(live_db: sqlite3.Connection) -> None:
    """会话库确认不了、但输入框已空 → 判为已落地，NEVER 补发。"""
    _seed_bound_turn(live_db, "g1", "ses_gate")
    driver = load_driver("opencode")
    fake = FakeTmux([_submitted_pane(_PROMPT)])
    driver.submit(_session(fake, "g1"), _PROMPT)
    assert _enters(fake) == 1


def test_echo_in_message_area_does_not_count_as_stuck() -> None:
    """提交后提示词会原样回显进消息区；只看整屏会把回显当残留，一路补发空回车。"""
    pane = _submitted_pane(_PROMPT)
    assert _PROMPT in pane  # 屏上确实还有这段文字……
    assert not opencode_driver._still_in_input_box(
        _session(FakeTmux([pane]), "echo"), opencode_driver._tail_marker(_PROMPT)
    )  # ……但它不在输入框里。


def test_resend_when_prompt_still_in_input_box(live_db: sqlite3.Connection) -> None:
    """输入框里仍看得见尾段 → Enter 确实被吞了，补发。"""
    _seed_bound_turn(live_db, "g2", "ses_gate2")
    driver = load_driver("opencode")
    fake = FakeTmux([_stuck_pane(_PROMPT)])
    driver.submit(_session(fake, "g2"), _PROMPT)
    assert _enters(fake) == 1 + opencode_driver._ENTER_RETRIES


def test_gate_sees_tail_across_wrapped_box_lines() -> None:
    """输入框按框宽折行，尾段被切成两行：去空白后仍认得出来，NEVER 因折行漏判。"""
    tail = opencode_driver._tail_marker(_PROMPT)
    head, rest = tail[: len(tail) // 2], tail[len(tail) // 2 :]
    pane = f"┃  ……{head}\n┃  {rest}\n┃  Build · m provider\n"
    sess = _session(FakeTmux([pane]), "wrap")
    assert opencode_driver._still_in_input_box(sess, tail)


def test_gate_treats_unreadable_pane_as_not_stuck() -> None:
    """抓屏失败 = 没有正面证据 = NEVER 补发。"""

    class _BlindTmux(FakeTmux):
        def __call__(self, argv: list[str]) -> str:
            if argv[1:2] == ["capture-pane"]:
                raise RuntimeError("capture-pane failed")
            return super().__call__(argv)

    sess = _session(_BlindTmux(["x"]), "blind")
    assert not opencode_driver._still_in_input_box(
        sess, opencode_driver._tail_marker(_PROMPT)
    )


@pytest.mark.usefixtures("live_db")
def test_first_turn_claim_failure_with_empty_box_sends_one_enter() -> None:
    """首轮认领失败但输入框已空：只按一次 Enter。

    现场那两个空提交就是从这里来的——认领超窗被当成"回车没落地"。
    """
    driver = load_driver("opencode")
    fake = FakeTmux([_submitted_pane(_PROMPT)])
    driver.submit(_session(fake, "first-empty"), _PROMPT)
    assert _enters(fake) == 1
    assert opencode_store.get_binding("first-empty") is None


@pytest.mark.usefixtures("live_db")
def test_first_turn_claim_failure_with_residue_resends_within_budget() -> None:
    """首轮认领失败且输入框仍有残留：补发，且总次数不超过上限。"""
    driver = load_driver("opencode")
    fake = FakeTmux([_stuck_pane(_PROMPT)])
    driver.submit(_session(fake, "first-stuck"), _PROMPT)
    assert _enters(fake) == 1 + opencode_driver._ENTER_RETRIES


def test_submit_survives_missing_store() -> None:
    """会话库不可用（库不存在）：单次 Enter、绑定不动，不抛。"""
    opencode_store.put_binding("t5", "ses_nodb", "/w")
    driver = load_driver("opencode")
    fake = FakeTmux(["hi"])
    driver.submit(_session(fake, "t5"), "hi")
    assert _enters(fake) == 1
    assert opencode_store.get_binding("t5") == "ses_nodb"


# ── 完成探针 ────────────────────────────────────────────────────────
def test_probe_returns_none_without_binding() -> None:
    """尚未认领 → 探针不可用，driver 当帧退回屏幕信号。"""
    driver = load_driver("opencode")
    assert driver.completion_probe is not None
    sess = _session(FakeTmux(["pane"]), "unbound")
    assert driver.completion_probe(sess) is None


def test_probe_not_done_on_tool_calls_only(live_db: sqlite3.Connection) -> None:
    opencode_store.put_binding("p1", "ses_p", "/w")
    _add_session(live_db, "ses_p", "/w", 1)
    _add_message(live_db, "m_u", "ses_p", 10, {"role": "user", "parentID": None})
    _add_message(
        live_db,
        "m_t",
        "ses_p",
        20,
        {"role": "assistant", "parentID": "m_u", "finish": "tool-calls"},
    )
    _add_part(live_db, "pt1", "m_t", "ses_p", 21, {"type": "text", "text": "half"})
    driver = load_driver("opencode")
    verdict = driver.completion_probe(_session(FakeTmux(["pane"]), "p1"))
    assert verdict is not None
    assert verdict.done is False
    assert verdict.text is None
    assert verdict.marker is None


def test_probe_done_on_stop_with_aggregated_text(live_db: sqlite3.Connection) -> None:
    opencode_store.put_binding("p2", "ses_q", "/w")
    _add_session(live_db, "ses_q", "/w", 1)
    _add_message(live_db, "m_u", "ses_q", 10, {"role": "user", "parentID": None})
    _add_message(
        live_db,
        "m_t",
        "ses_q",
        20,
        {"role": "assistant", "parentID": "m_u", "finish": "tool-calls"},
    )
    _add_message(
        live_db,
        "m_s",
        "ses_q",
        30,
        {"role": "assistant", "parentID": "m_u", "finish": "stop",
         "time": {"created": 30, "completed": 35}},
    )
    _add_part(live_db, "pt1", "m_t", "ses_q", 21, {"type": "text", "text": "looking"})
    _add_part(live_db, "pt2", "m_s", "ses_q", 31, {"type": "reasoning", "text": "hmm"})
    _add_part(live_db, "pt3", "m_s", "ses_q", 32, {"type": "text", "text": "done: 3"})
    driver = load_driver("opencode")
    verdict = driver.completion_probe(_session(FakeTmux(["pane"]), "p2"))
    assert verdict is not None
    assert verdict.done is True
    assert verdict.marker == "m_s"
    assert verdict.text == "looking\ndone: 3"
    assert "hmm" not in (verdict.text or "")


# ── 屏幕信号 ────────────────────────────────────────────────────────
def test_ready_signal_matches_placeholder() -> None:
    assert load_driver("opencode").ready_signal.matches("│ Ask anything")


# 真实 pane 取证：全新启动（占位提示 + 输入框页脚都在）。
_PANE_FRESH = """\
┃
┃  Ask anything... "Fix broken tests"
┃
┃  Build · DeepSeek V4 Flash DeepSeek
╹▀▀▀▀▀▀▀▀▀...
"""

# 真实 pane 取证：``opencode -s`` 续接回放后（占位提示消失，上一轮完成行还留在屏上）。
_PANE_RESUMED = """\
     + Thought: 395ms

     banana

     ▣  Build · DeepSeek V4 Flash · 1.7s

┃
┃
┃
┃  Build · DeepSeek V4 Flash DeepSeek
╹▀▀▀▀▀▀▀▀▀...
"""

# shell 阶段：启动命令刚回显，TUI 还没起来。
_PANE_SHELL = """\
frago@mac ~ % opencode -s ses_abc123
"""


def test_ready_signal_matches_fresh_pane() -> None:
    assert load_driver("opencode").ready_signal.matches(_PANE_FRESH)


def test_ready_signal_matches_resumed_pane() -> None:
    assert load_driver("opencode").ready_signal.matches(_PANE_RESUMED)


def test_ready_signal_rejects_shell_pane() -> None:
    assert not load_driver("opencode").ready_signal.matches(_PANE_SHELL)


def test_ready_signal_rejects_done_footer_alone() -> None:
    assert not load_driver("opencode").ready_signal.matches(
        "     ▣  Build · DeepSeek V4 Flash · 1.7s"
    )


def test_done_signal_matches_build_footer() -> None:
    driver = load_driver("opencode")
    assert driver.done_signal.matches("▣ Build · claude-opus · 3.1s")
    assert not driver.done_signal.matches("still working…")


def test_update_modal_handler_sends_escape() -> None:
    driver = load_driver("opencode")
    handler = driver.exception_handlers[0]
    assert handler.trigger.matches("A new Update is available now")
    fake = FakeTmux(["pane"])
    handler.action(_session(fake, "modal"))
    assert any(k[-1] == "Escape" for k in fake.sent_keys())


# ── needs_input 门 ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    "pane",
    [
        "Error: invalid api key",
        "API key is expired",
        "401 Unauthorized",
        "authentication failed",
        "Your credit balance is too low to continue",
        "insufficient quota for this model",
        "not logged in",
        "please sign in to continue",
    ],
)
def test_needs_input_hits_real_failures(pane: str) -> None:
    signal = load_driver("opencode").needs_input_signal
    assert signal is not None
    assert signal.matches(pane)


@pytest.mark.parametrize(
    "pane",
    [
        # 良性提示词：裸 login / sign in 出现在横幅与答案正文里，NEVER 当认证墙。
        "Run /login to switch providers",
        "You are logged in as jamey",
        "here is how you sign in to the dashboard",
        "▣ Build · claude-opus · 3.1s",
        "Ask anything",
        "the answer is 42",
    ],
)
def test_needs_input_does_not_misfire_on_benign_text(pane: str) -> None:
    signal = load_driver("opencode").needs_input_signal
    assert signal is not None
    assert not signal.matches(pane)


# ── 授权框：opencode 自己弹的权限门 ──────────────────────────────────
# 现场原文（跨目录访问 recipe 工作区时弹出）。这个框停在屏幕上等人选，屏幕再无
# 别的变化，判不出来本轮就一路空等到超时，调用方拿不到"该你介入了"的信号。
_PERMISSION_PANE = """\
┃  △ Permission required
┃    ← Access external directory ~/.frago/recipes/workflows/kline_blind_trainer
┃  Patterns
┃  - /Users/frago/.frago/recipes/workflows/kline_blind_trainer/*
┃   Allow once   Allow always   Reject
"""


def test_needs_input_hits_real_permission_prompt() -> None:
    """现场原文整屏 MUST 命中。"""
    signal = load_driver("opencode").needs_input_signal
    assert signal is not None
    assert signal.matches(_PERMISSION_PANE)


@pytest.mark.parametrize(
    "pane",
    [
        # 标题特征单独出现（三选一菜单被截在屏幕外/换了措辞）。
        "┃  △ Permission required\n┃  Patterns\n",
        # 三选一菜单单独出现（标题被滚出可见区）。
        "┃   Allow once   Allow always   Reject\n",
        # 菜单项被分行渲染时仍是同一组特征。
        "Allow once\nAllow always\nReject\n",
    ],
)
def test_needs_input_hits_permission_title_and_menu_independently(pane: str) -> None:
    """两组特征各自单独出现也算撞门——只命中其一就够判"该找人了"。"""
    signal = load_driver("opencode").needs_input_signal
    assert signal is not None
    assert signal.matches(pane)


@pytest.mark.parametrize(
    "pane",
    [
        # 答案正文里谈论权限：有 permission 一词，但没有"required"也没有三选一菜单。
        "You need write permission on that directory before the build can run.",
        "⏺ 我检查了文件权限 (permission)，755 是对的，不用改。",
        # 只有菜单三项中的一项，不构成菜单。
        "I will allow once the tests pass.",
    ],
)
def test_needs_input_does_not_misfire_on_permission_talk(pane: str) -> None:
    """普通答案里出现 permission 一词 NEVER 判成授权框——误判会让本轮刚提交就返回。"""
    signal = load_driver("opencode").needs_input_signal
    assert signal is not None
    assert not signal.matches(pane)
