"""Phase 1 单测：UiSessionRunner 透传纠偏 + 配置缺省自愈。

spec 20260625-webui-session-lifecycle-mediator / Phase 1。验证：
- 同一 session_id 第二次 send 复用常驻会话（未重建）。
- 冷会话触发 pool resume 重建（acquire 重新建会话）。
- UI runner 的 pool 与 PA PaTmuxRunner 的 pool 实例隔离。
- config.json 缺 webui_sessions 段时由 load_config 缺省自愈补 10/1800 并回写。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from frago.agent_driver.tmux_session import TurnResult
from frago.server.services.pa_tmux_runner import PaTmuxRunner
from frago.server.services.ui_session_runner import UiSessionRunner


class FakePool:
    """WarmSessionPool 替身：记录 run/resume，跟踪活会话 key。"""

    def __init__(self) -> None:
        self.live: set[str] = set()
        self.runs: list[tuple[str, str]] = []  # (session_id, prompt)
        self.builds: list[str] = []  # 触发冷启动重建的 session_id
        self.native_flags: list[bool] = []  # 每轮 run 收到的 native_session_id
        self.origins: list[str | None] = []  # 每轮 run 收到的会话出身
        # session_id → 会话替身。只需带一个 adopted 标志：runner 据此分辨"接管"与
        # "冷启动"，两者都是零等待与十几秒等待的差别。
        self.sessions: dict[str, SimpleNamespace] = {}
        self.reply_text = "ok"

    def has(self, session_id: str) -> bool:
        return session_id in self.live

    def peek(self, session_id: str):
        """与 WarmSessionPool 同名同义：取常驻会话对象，无则 None。

        runner 靠它问"这一场是接管来的还是冷启动来的"，好把激活态报准。替身缺这个
        方法的话，测出来的是替身的形状，不是真 pool 的行为。
        """
        return self.sessions.get(session_id)

    def run(
        self,
        prompt,
        *,
        agent_type,
        session_id,
        cwd,
        native_session_id=False,
        timeout_s=120.0,
        resume_hook=None,
        origin=None,
    ):  # noqa: ARG002
        if session_id not in self.live:
            # 冷会话：pool 会 resume 重建。
            self.builds.append(session_id)
            self.live.add(session_id)
            self.sessions[session_id] = SimpleNamespace(adopted=False)
        self.runs.append((session_id, prompt))
        self.native_flags.append(native_session_id)
        self.origins.append(origin)
        return TurnResult(text=self.reply_text, raw_delta="", status="ok", duration_ms=1)

    def evict(self, session_id: str) -> bool:
        existed = session_id in self.live
        self.live.discard(session_id)
        self.sessions.pop(session_id, None)
        return existed

    def shutdown(self) -> None:
        self.live.clear()
        self.sessions.clear()


def test_second_send_reuses_resident_session_without_rebuild():
    pool = FakePool()
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    a1 = runner.send("sess-A", "msg-1")
    a2 = runner.send("sess-A", "msg-2")

    # 两轮都打到同一 session_id；只在首轮触发一次冷启动重建。
    assert [sid for sid, _ in pool.runs] == ["sess-A", "sess-A"]
    assert pool.builds == ["sess-A"]
    # 首轮冷启动 → activating；次轮命中常驻 → ready。
    assert a1.status == "activating"
    assert a2.status == "ready"
    assert a2.text == "ok"


def test_send_passes_native_session_id_true():
    """UI 列的是真实 claude jsonl 会话 id，必须以 native 透传给 pool，
    冷启动才会用真实 id 续上原会话、而非另起新会话写进别的 jsonl。"""
    pool = FakePool()
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    runner.send("real-claude-sid", "hi")

    assert pool.native_flags == [True]
    assert pool.origins == ["human"]


def test_cold_session_triggers_resume_rebuild():
    pool = FakePool()
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    activation = runner.send("cold-X", "hello")

    assert pool.builds == ["cold-X"]  # 冷会话经 pool resume 重建
    assert activation.status == "activating"


def test_send_raises_on_synchronous_timeout_or_error_turn_result():
    """回归（12792dfe 契约后置条件）：同步等待（timeout_s > 0）下 TurnResult.status 为 timeout 或 error 时，
    必须抛出异常，禁止包装为成功的 SessionActivation 返回 200 OK 吞掉用户草稿；
    而 timeout_s == 0.0（首轮异步起跑/后台队列）允许 timeout 状态正常返回。
    """
    import pytest

    class _StatusPool(FakePool):
        def __init__(self, status: str, text: str = "") -> None:
            super().__init__()
            self._status = status
            self.reply_text = text

        def run(self, prompt, **kwargs):
            super().run(prompt, **kwargs)
            return TurnResult(text=self.reply_text, raw_delta="", status=self._status, duration_ms=100)

    timeout_runner = UiSessionRunner(pool=_StatusPool("timeout"), cwd="/tmp")
    with pytest.raises(TimeoutError, match="等待会话响应超时"):
        timeout_runner.send("sess-timeout", "msg", timeout_s=180.0)

    # timeout_s=0.0 为 fire-and-forget 异步起跑，不抛 TimeoutError
    async_act = timeout_runner.send("sess-async", "msg", timeout_s=0.0)
    assert async_act.session_id == "sess-async"

    error_runner = UiSessionRunner(pool=_StatusPool("error", text="UNAUTHENTICATED"), cwd="/tmp")
    with pytest.raises(RuntimeError, match="UNAUTHENTICATED"):
        error_runner.send("sess-err", "msg", timeout_s=180.0)


def test_ui_runner_pool_isolated_from_pa_pool():
    ui = UiSessionRunner(max_size=10)
    pa = PaTmuxRunner()

    # 各持独立 WarmSessionPool 实例，UI 驾驶不会驱逐/串扰 PA 的常驻会话。
    assert ui._pool is not pa._pool
    assert ui._pool._max_size == 10


def test_load_config_self_heals_missing_webui_sessions(monkeypatch, tmp_path):
    from frago.init import config_manager

    cfg_path = tmp_path / "config.json"
    # 写一个不含 webui_sessions 段的旧 config.json。
    cfg_path.write_text(
        json.dumps({"schema_version": "1.0", "auth_method": "official"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_manager, "CONFIG_PATH", cfg_path)
    # 屏蔽 api_endpoint 迁移副作用（标志文件路径）。
    monkeypatch.setattr(config_manager, "_MIGRATION_PERFORMED_FLAG", tmp_path / ".migrated")

    config = config_manager.load_config()

    assert config.webui_sessions.max_resident == 10
    assert config.webui_sessions.idle_timeout_secs == 1800
    # 缺省自愈：补默认后回写，磁盘上现在带有 webui_sessions 段。
    persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert persisted["webui_sessions"]["max_resident"] == 10
    assert persisted["webui_sessions"]["idle_timeout_secs"] == 1800


# ── 替别人投话：空闲才送、送完看记录 ────────────────────────────────────
#
# 2026-09-29：队友消息在对方 agent 干活时被打进输入框，回车被吞，字在输入框里停了
# 四十分钟，最后跟主人自己打的一句拼成一条发言交了出去。


class _AcquirePool:
    """只会 acquire 的 pool 替身：交出同一个会话替身。"""

    def __init__(self, session) -> None:
        self.session = session

    def acquire(
        self, agent_type, session_id, cwd, *, native_session_id=False, origin=None
    ):  # noqa: ARG002
        return self.session


def _fake_session(*, finished: bool, clear=True):
    import threading

    typed: list[str] = []
    cleared: list[bool] = []

    def submit(_session, text):
        typed.append(text)

    def clear_input(_session):
        cleared.append(True)
        return True

    driver = SimpleNamespace(
        agent_type="claude",
        submit=submit,
        clear_input=clear_input if clear else None,
    )
    session = SimpleNamespace(
        status="idle", driver=driver, _submit_lock=threading.Lock(), last_active_at=None
    )
    return session, typed, cleared


def _runner_for(monkeypatch, session, *, finished: bool):
    monkeypatch.setattr(
        "frago.server.services.ui_session_runner._turn_finished", lambda _s: finished
    )
    return UiSessionRunner(pool=_AcquirePool(session), cwd="/tmp")


def test_会话在忙一个字都不打(monkeypatch):
    session, typed, _ = _fake_session(finished=False)
    runner = _runner_for(monkeypatch, session, finished=False)

    got = runner.submit_when_idle("s", "队友的话", landed=lambda: True, sleep=lambda _s: None)

    assert got == "not_now"
    assert typed == [], "会话在忙时打进去的字，回车会被吞，留在输入框里等着跟别人的话拼起来"


def test_本进程正驱动着一轮也算忙(monkeypatch):
    session, typed, _ = _fake_session(finished=True)
    session.status = "busy"
    runner = _runner_for(monkeypatch, session, finished=True)

    assert runner.submit_when_idle("s", "x", landed=lambda: True) == "not_now"
    assert typed == []


def test_空闲时送进去且记录里看到了才算到(monkeypatch):
    session, typed, cleared = _fake_session(finished=True)
    runner = _runner_for(monkeypatch, session, finished=True)
    seen = iter([False, False, True])

    got = runner.submit_when_idle("s", "队友的话", landed=lambda: next(seen), sleep=lambda _s: None)

    assert got == "landed"
    assert typed == ["队友的话"]
    assert cleared == []


def test_等不到就把自己打的字清掉(monkeypatch):
    session, typed, cleared = _fake_session(finished=True)
    runner = _runner_for(monkeypatch, session, finished=True)
    now = [0.0]

    def tick(seconds):
        now[0] += seconds

    got = runner.submit_when_idle(
        "s",
        "队友的话",
        landed=lambda: False,
        confirm_s=5,
        poll_s=1,
        sleep=tick,
        clock=lambda: now[0],
    )

    assert got == "not_now"
    assert typed == ["队友的话"]
    assert cleared == [True], "留在输入框里，下一个按回车的人会把它连同自己的话一起交出去"


def test_agy的会话收尾了才算空闲(monkeypatch):
    """agy 那一档：先把手把换成真编号（认领映射），再问转录里最新一轮收没收尾。

    手把（``webui-…`` / 命令行的 ``--name``）直接拿去问转录是问不到的——真编号要等
    认领之后才写进映射。少了这一步，agy 会话永远判不出空闲、永远不回收。
    """
    from frago.server.services import ui_session_runner as usr

    monkeypatch.setattr(
        usr.agy_store, "get_binding", lambda sid: "conv-1" if sid == "webui-x" else None
    )
    monkeypatch.setattr(
        usr.agy_store, "latest_turn", lambda cid: SimpleNamespace(done=(cid == "conv-1"))
    )

    claimed = SimpleNamespace(driver=SimpleNamespace(agent_type="agy"), session_id="webui-x")
    assert usr._turn_finished(claimed) is True

    unknown = SimpleNamespace(driver=SimpleNamespace(agent_type="agy"), session_id="webui-y")
    assert usr._turn_finished(unknown) is False


def test_codex的会话收尾也要先把手把换成真编号(monkeypatch):
    """codex 那一档：与 agy 对称，取 sid 时必须先问绑定表把手把换成真编号。

    手把（``webui-…``）直接拿去问转录是问不到的，绑定表里才有真编号。
    少了这一跳，codex 会话永远判不出空闲、消息永远投不进去。
    """
    from frago.server.services import ui_session_runner as usr
    from frago.session import codex_store

    seen: list[str] = []

    class _Adapter:
        def probe_turn_completion(self, sid):
            seen.append(sid)
            return SimpleNamespace(done=True)

        def probe_harness_idle(self, sid, pane):
            return SimpleNamespace(is_terminal_idle=True, has_running_subshells=False)

    monkeypatch.setattr(
        "frago.session.adapters.kernel_adapters.get_kernel_session_adapter",
        lambda family: _Adapter(),
    )
    monkeypatch.setattr(
        codex_store, "get_binding", lambda sid: "real-codex-1" if sid == "webui-x" else None
    )

    claimed = SimpleNamespace(driver=SimpleNamespace(agent_type="codex"), session_id="webui-x")
    assert usr._turn_finished(claimed) is True
    assert seen == ["real-codex-1"], "必须把 sid 解析成真编号再问转录，而不是拿手把去问"


def test_opencode的会话收尾也要先把手把换成真编号(monkeypatch):
    """opencode 那一档：与 agy 对称，取 sid 时必须先问绑定表把手把换成真编号。"""
    from frago.server.services import ui_session_runner as usr
    from frago.session import opencode_store

    seen: list[str] = []

    class _Adapter:
        def probe_turn_completion(self, sid):
            seen.append(sid)
            return SimpleNamespace(done=True)

        def probe_harness_idle(self, sid, pane):
            return SimpleNamespace(is_terminal_idle=True, has_running_subshells=False)

    monkeypatch.setattr(
        "frago.session.adapters.kernel_adapters.get_kernel_session_adapter",
        lambda family: _Adapter(),
    )
    monkeypatch.setattr(
        opencode_store,
        "get_binding",
        lambda sid: "ses_real_opencode" if sid == "webui-y" else None,
    )

    claimed = SimpleNamespace(driver=SimpleNamespace(agent_type="opencode"), session_id="webui-y")
    assert usr._turn_finished(claimed) is True
    assert seen == ["ses_real_opencode"]


def test_绑定表里查不到时退回手把原值(monkeypatch):
    """绑定表里没有这一场时，退回原手把（不抛异常），保持与 agy 同样的「取不到就退回原值」语义。"""
    from frago.server.services import ui_session_runner as usr
    from frago.session import codex_store

    seen: list[str] = []

    class _Adapter:
        def probe_turn_completion(self, sid):
            seen.append(sid)
            return SimpleNamespace(done=True)

        def probe_harness_idle(self, sid, pane):
            return SimpleNamespace(is_terminal_idle=True, has_running_subshells=False)

    monkeypatch.setattr(
        "frago.session.adapters.kernel_adapters.get_kernel_session_adapter",
        lambda family: _Adapter(),
    )
    monkeypatch.setattr(codex_store, "get_binding", lambda sid: None)

    claimed = SimpleNamespace(driver=SimpleNamespace(agent_type="codex"), session_id="webui-z")
    assert usr._turn_finished(claimed) is True
    assert seen == ["webui-z"]
