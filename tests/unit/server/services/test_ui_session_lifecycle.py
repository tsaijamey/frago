"""Phase 2 单测：UI 会话空闲回收的判定与巡检。

spec 20260625-webui-session-lifecycle-mediator / Phase 2。验证：
- UiSessionRunner.evict_idle 分两问判空闲：「最新一轮终结没有」按会话所属的那一家问
  各自的档案（claude 的 jsonl 完成探针 + 真空闲四信号、codex 的 task_complete、
  opencode 会话库里的终结标记），「静默了多久」一律从 ``session.last_active_at`` 起算。
- **冷启动窗口不许被当空闲收掉**：``--resume`` 一场几小时前的旧会话时，档案里最后那条
  记录本来就是几小时前的终结记录，而会话是这一刻才起来的。
- 判不出是哪一家（会话对象没带 driver）时不回收，NEVER 拿别家的档案去断它。
- UiSessionLifecycleService 巡检从 config 取阈值并交给 runner 回收。
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from frago.server.services.ui_session_runner import UiSessionRunner
from frago.session import codex_store, opencode_store
from frago.session import transcript_completion as tc
from frago.session.opencode_store import OpencodeTurn
from frago.session.transcript_completion import TurnCompletion

# 一场闲着的 claude：底部只有空输入框，没有 spinner、没有后台 shell 提示。
# claude driver 的 ``is_truly_idle`` 认的就是这一屏。
IDLE_PANE = "上一轮的答案\n────────────\n❯ \n────────────\n"


class FakeDriver:
    """driver 替身。会话是拿哪个 driver 起来的，它就属于哪一家。"""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class FakeSession:
    """常驻会话替身。

    带齐空闲判定真正会读的那几样：``status``（本进程此刻在不在驱动它）、
    ``last_active_at``（这场会话在本池里自己的最后活动时刻，也就是静默时长的锚点）、
    以及 claude 那一支要读的屏。缺一样都会测出替身的形状而不是真会话的行为。
    """

    def __init__(
        self,
        session_id: str,
        agent_type: str = "claude",
        *,
        idle_for_s: float = 7200.0,
        status: str = "idle",
        pane: str = IDLE_PANE,
    ) -> None:
        self.session_id = session_id
        self.cwd = "/tmp"
        self.closed = False
        self.driver = FakeDriver(agent_type)
        # 工作台列的都是各家真实会话编号，driver 原样拿去定位档案。
        self.native_session_id = True
        self.status = status
        self.last_active_at = datetime.now(UTC) - timedelta(seconds=idle_for_s)
        self._pane = pane

    def capture_pane(self, **_kw) -> str:
        return self._pane

    def close(self) -> None:
        self.closed = True


def _transcript(tmp_path: Path, session_id: str, *, age_s: float = 7200.0) -> Path:
    """造一个 claude transcript 文件，并把它的 mtime 推到 ``age_s`` 秒前。

    mtime 是 ``is_truly_idle`` 四信号里的最后一道（记录静默）；刚写出来的文件会被判成
    "这一秒还在动"，那不是这些用例要测的东西。
    """
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


class FakePool:
    """支持 has + evict_idle（按真实语义应用传入的 idle_age_fn）。"""

    def __init__(self, sessions: list[FakeSession]) -> None:
        self._sessions = {s.session_id: s for s in sessions}

    def has(self, sid: str) -> bool:
        return sid in self._sessions

    def evict_idle(self, idle_age_fn, timeout_s):
        evicted = []
        for sid, sess in list(self._sessions.items()):
            age = idle_age_fn(sess)
            if age is not None and age > timeout_s:
                del self._sessions[sid]
                sess.close()
                evicted.append(sid)
        return evicted


def _completion(done: bool, ts: datetime | None) -> TurnCompletion:
    return TurnCompletion(
        done=done,
        stop_reason="end_turn" if done else "tool_use",
        final_text="",
        request_id=None,
        last_uuid="u",
        pending_tool_use=not done,
        session_id=None,
        source_path=None,
        last_terminal_ts=ts,
    )


def _stub_claude_transcripts(monkeypatch, tmp_path, verdicts, *, age_s=7200.0):
    """把这几个会话编号接到真实的临时 transcript 文件与给定的完成判定上。"""
    paths = {sid: _transcript(tmp_path, sid, age_s=age_s) for sid in verdicts}
    monkeypatch.setattr(tc, "locate_transcript", lambda sid, **_: paths.get(sid))
    monkeypatch.setattr(
        tc, "evaluate_file", lambda path: verdicts[Path(path).stem]
    )
    return paths


def test_evict_idle_reclaims_done_and_old_skips_busy(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    verdicts = {
        # 已说完、这场会话在池里也静默了 2 小时 → 该回收。
        "old-done": _completion(True, now - timedelta(hours=2)),
        # 已说完、但一分钟前刚在池里活动过 → 不到阈值。
        "fresh-done": _completion(True, now - timedelta(minutes=1)),
        # 仍在干活（not done）→ 永不回收。
        "busy": _completion(False, None),
    }
    _stub_claude_transcripts(monkeypatch, tmp_path, verdicts)
    pool = FakePool(
        [
            FakeSession("old-done", idle_for_s=7200),
            FakeSession("fresh-done", idle_for_s=60),
            FakeSession("busy", idle_for_s=7200),
        ]
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    evicted = runner.evict_idle(timeout_s=1800.0)  # 30min

    assert evicted == ["old-done"]
    assert not pool.has("old-done")
    assert pool.has("fresh-done") and pool.has("busy")


def test_resumed_session_is_not_reclaimed_during_cold_start(monkeypatch, tmp_path):
    """**本次修复钉住的竞态。**

    工作台点开一场三小时前的旧 claude 会话：tmux 起来、``--resume`` 接回旧 transcript、
    提示词一块块投喂进去，前后十几秒。这十几秒里那份 transcript 一个字没变——最后一条
    记录就是三小时前那条终结记录。锚点若取它，巡检当场判「已说完 + 闲了三小时」，把
    刚起来的会话 kill 掉；人看到的是点了发送、转十几秒、会话没了。

    锚点必须是这场会话在池里自己的最后活动时刻（``open()`` 刚刚把它刷成"此刻"）。
    """
    three_hours_ago = datetime.now(UTC) - timedelta(hours=3)
    _stub_claude_transcripts(
        monkeypatch,
        tmp_path,
        {"resumed": _completion(True, three_hours_ago)},
        age_s=3 * 3600,
    )
    # 会话是这一刻才起来的：last_active_at 由 open() 刷成此刻，status 还没进 busy。
    pool = FakePool([FakeSession("resumed", idle_for_s=0.0, status="idle")])

    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=1800.0) == []
    assert pool.has("resumed")


def test_session_being_driven_right_now_is_never_reclaimed(monkeypatch, tmp_path):
    """本进程正驱动着这一轮（status=busy）→ 一个字都不用问档案，绝不回收。

    档案此刻还停在上一轮的终结记录上（本轮第一条记录尚未落盘），那条记录可以任意老。
    内存里的 status 是比档案新的事实。
    """
    _stub_claude_transcripts(
        monkeypatch,
        tmp_path,
        {"feeding": _completion(True, datetime.now(UTC) - timedelta(hours=2))},
    )
    pool = FakePool([FakeSession("feeding", idle_for_s=7200, status="busy")])

    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=1800.0) == []
    assert pool.has("feeding")


def test_claude_session_with_background_shells_is_never_reclaimed(monkeypatch, tmp_path):
    """答完了但派出去的后台 shell 还在跑 → 不是空闲（复用 PA 的 is_truly_idle 判据）。

    只问完成探针的话，这种会话会连着还在跑的 worker 一起被回收。
    """
    _stub_claude_transcripts(
        monkeypatch,
        tmp_path,
        {"bg": _completion(True, datetime.now(UTC) - timedelta(hours=2))},
    )
    pool = FakePool(
        [
            FakeSession(
                "bg",
                idle_for_s=7200,
                pane=IDLE_PANE + "\n  ⎿  2 shells still running\n",
            )
        ]
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=1800.0) == []
    assert pool.has("bg")


def test_evict_idle_skips_when_no_transcript(monkeypatch):
    pool = FakePool([FakeSession("x")])
    monkeypatch.setattr(tc, "locate_transcript", lambda *_a, **_k: None)
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=0.0) == []
    assert pool.has("x")


def test_codex_session_is_reclaimed_by_its_own_rollout(monkeypatch):
    """codex 的常驻会话也要参与回收——从前它的编号在 claude 档案里定位不到文件，
    一律判不出空闲，于是 tmux 白占着直到被数量 LRU 挤掉。

    「停没停」问 codex 自己的 rollout（``task_complete``），「停了多久」与三家共用一个
    锚点：这场会话在池里的最后活动时刻。"""
    pool = FakePool([FakeSession("codex-sid", agent_type="codex", idle_for_s=7200)])
    monkeypatch.setattr(
        codex_store,
        "latest_turn",
        lambda _sid: codex_store.CodexTurn(turn_id="t1", done=True, text="ok", error=None),
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    assert runner.evict_idle(timeout_s=1800.0) == ["codex-sid"]


def test_codex_resumed_session_is_not_reclaimed_during_cold_start(monkeypatch, tmp_path):
    """codex 那一支同样不许在冷启动窗口里被收掉。

    ``codex resume`` 接回的 rollout 里最后一轮本来就是 ``task_complete``，而锚点从前取
    rollout 文件的修改时刻——那个时刻可以是任意久之前。这里的 rollout 就是两小时前
    动过的，而会话是这一刻才起来的。"""
    rollout = _transcript(tmp_path, "rollout-codex", age_s=7200)
    pool = FakePool([FakeSession("codex-sid", agent_type="codex", idle_for_s=0.0)])
    monkeypatch.setattr(
        codex_store,
        "latest_turn",
        lambda _sid: codex_store.CodexTurn(turn_id="t1", done=True, text="ok", error=None),
    )
    monkeypatch.setattr(codex_store, "find_rollout", lambda _sid: rollout)

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    assert runner.evict_idle(timeout_s=1800.0) == []
    assert pool.has("codex-sid")


def test_codex_session_still_working_is_never_reclaimed(monkeypatch):
    pool = FakePool([FakeSession("codex-sid", agent_type="codex")])
    monkeypatch.setattr(
        codex_store,
        "latest_turn",
        lambda _sid: codex_store.CodexTurn(turn_id="t1", done=False, text="", error=None),
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    assert runner.evict_idle(timeout_s=0.0) == []
    assert pool.has("codex-sid")


def _opencode_turn(done: bool, completed_at_ms: int | None) -> OpencodeTurn:
    return OpencodeTurn(
        parent_id="msg_u",
        final_message_id="msg_a" if done else None,
        done=done,
        text="ok" if done else "",
        completed_at=completed_at_ms,
    )


def test_opencode_session_is_reclaimed_when_finished_and_long_quiet(monkeypatch):
    two_hours_ago_ms = int((datetime.now(UTC).timestamp() - 7200) * 1000)
    pool = FakePool([FakeSession("ses_abc", agent_type="opencode", idle_for_s=7200)])
    monkeypatch.setattr(
        opencode_store, "latest_turn", lambda _sid: _opencode_turn(True, two_hours_ago_ms)
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    assert runner.evict_idle(timeout_s=1800.0) == ["ses_abc"]


def test_opencode_resumed_session_is_not_reclaimed_during_cold_start(monkeypatch):
    """opencode 那一支同样不许在冷启动窗口里被收掉。

    ``opencode -s <id>`` 接回的会话，库里最后一轮的 ``time.completed`` 是两小时前——
    从前那就是锚点。会话本身却是这一刻才起来的。"""
    two_hours_ago_ms = int((datetime.now(UTC).timestamp() - 7200) * 1000)
    pool = FakePool([FakeSession("ses_abc", agent_type="opencode", idle_for_s=0.0)])
    monkeypatch.setattr(
        opencode_store, "latest_turn", lambda _sid: _opencode_turn(True, two_hours_ago_ms)
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    assert runner.evict_idle(timeout_s=1800.0) == []
    assert pool.has("ses_abc")


def test_opencode_session_still_working_is_kept(monkeypatch):
    """最新一轮还没终结 → 判不出停没停，不回收。"""
    pool = FakePool([FakeSession("ses_abc", agent_type="opencode", idle_for_s=7200)])
    monkeypatch.setattr(
        opencode_store, "latest_turn", lambda _sid: _opencode_turn(False, None)
    )

    runner = UiSessionRunner(pool=pool, cwd="/tmp")
    assert runner.evict_idle(timeout_s=0.0) == []
    assert pool.has("ses_abc")


def test_session_without_a_driver_is_never_reclaimed():
    """判不出是哪一家时不回收：不知道该翻谁的档案，就不能断它的生死。"""

    class Anonymous(FakeSession):
        def __init__(self) -> None:
            super().__init__("mystery")
            del self.driver

    pool = FakePool([Anonymous()])
    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=0.0) == []
    assert pool.has("mystery")


def test_session_without_last_active_anchor_is_never_reclaimed(monkeypatch, tmp_path):
    """没有 last_active_at 就没有锚点，算不出静默多久——算不出就不回收。"""
    _stub_claude_transcripts(
        monkeypatch,
        tmp_path,
        {"anchorless": _completion(True, datetime.now(UTC) - timedelta(hours=2))},
    )
    session = FakeSession("anchorless", idle_for_s=7200)
    session.last_active_at = None
    pool = FakePool([session])

    runner = UiSessionRunner(pool=pool, cwd="/tmp")

    assert runner.evict_idle(timeout_s=0.0) == []
    assert pool.has("anchorless")


def test_lifecycle_scan_uses_config_threshold(monkeypatch):
    from frago.server.services import ui_session_lifecycle as life

    calls: list[float] = []

    class StubRunner:
        def evict_idle(self, timeout_s):
            calls.append(timeout_s)
            return []

    class StubCfg:
        class webui_sessions:  # noqa: N801
            idle_timeout_secs = 1234

    monkeypatch.setattr("frago.init.config_manager.load_config", lambda: StubCfg)
    monkeypatch.setattr(
        "frago.server.services.ui_session_runner.get_runner", lambda: StubRunner()
    )

    svc = life.UiSessionLifecycleService(scan_interval_s=0.01)
    asyncio.run(svc._scan_once())

    assert calls == [1234.0]


def test_get_instance_is_singleton(monkeypatch):
    from frago.server.services import ui_session_lifecycle as life

    monkeypatch.setattr(life.UiSessionLifecycleService, "_instance", None)
    a = life.UiSessionLifecycleService.get_instance()
    b = life.UiSessionLifecycleService.get_instance()
    assert a is b
    assert isinstance(a, life.UiSessionLifecycleService)


def test_start_is_idempotent_and_stop_cancels(monkeypatch):
    from frago.server.services import ui_session_lifecycle as life

    monkeypatch.setattr(
        life.UiSessionLifecycleService,
        "reconcile_startup_orphans",
        lambda self, **_kw: {"markers_cleaned": 0, "tmux_killed": 0, "onto_reconciled": 0},
    )

    async def scenario():
        svc = life.UiSessionLifecycleService(scan_interval_s=100.0)
        # No task before start.
        assert svc._task is None
        await svc.start()
        first = svc._task
        assert first is not None and not first.done()
        # A second start must not spawn a new task.
        await svc.start()
        assert svc._task is first
        # Stop cancels and clears.
        await svc.stop()
        assert svc._task is None
        assert first.cancelled()

    asyncio.run(scenario())


def test_stop_is_noop_when_never_started():
    from frago.server.services import ui_session_lifecycle as life

    svc = life.UiSessionLifecycleService()
    # Must not raise even though start was never called.
    asyncio.run(svc.stop())
    assert svc._task is None


def test_start_after_done_task_spawns_new_one(monkeypatch):
    from frago.server.services import ui_session_lifecycle as life

    monkeypatch.setattr(
        life.UiSessionLifecycleService,
        "reconcile_startup_orphans",
        lambda self, **_kw: {"markers_cleaned": 0, "tmux_killed": 0, "onto_reconciled": 0},
    )

    async def scenario():
        svc = life.UiSessionLifecycleService(scan_interval_s=100.0)

        async def already_done():
            return None

        svc._task = asyncio.ensure_future(already_done())
        await svc._task  # drive it to completion
        assert svc._task.done()

        await svc.start()
        assert svc._task is not None and not svc._task.done()
        await svc.stop()

    asyncio.run(scenario())


def test_loop_survives_scan_exception(monkeypatch):
    """A failing _scan_once must be swallowed so the loop keeps running."""
    from frago.server.services import ui_session_lifecycle as life

    sleeps: list[float] = []
    scans = {"n": 0}

    async def fake_sleep(_secs):
        sleeps.append(_secs)
        # Let two iterations run, then cancel to break the infinite loop.
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    async def boom(self):
        scans["n"] += 1
        raise RuntimeError("scan failed")

    monkeypatch.setattr(life.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(life.UiSessionLifecycleService, "_scan_once", boom)

    svc = life.UiSessionLifecycleService(scan_interval_s=7.0)

    async def scenario():
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await svc._loop()

    asyncio.run(scenario())

    # Scan was attempted and its exception did not propagate out of the loop.
    assert scans["n"] >= 1
    assert sleeps[0] == 7.0


def test_v4_reconcile_startup_orphans_cleans_dead_panes_and_spares_live(monkeypatch, tmp_path):
    """V4: 服务启动期清理孤立死窗格与死 marker 并收敛陈旧本体，同时放过附着/活跃会话。"""
    from frago.agent_driver import coreagent_pane_host as host
    from frago.server.services import coreagent_runner
    from frago.server.services import ui_session_lifecycle as life
    from frago.session import service as session_service_mod
    from frago.session.service import LiveRuntimeProbes, SessionOntologyService
    from frago.session.store import SessionOntologyStore

    panes_root = tmp_path / "panes"
    panes_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(panes_root))

    dead_marker = panes_root / "core_orphan_dead.active_run"
    dead_marker.write_text(str(tmp_path / "missing_run"), encoding="utf-8")

    store = SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    onto_svc = SessionOntologyService(store=store)
    monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: onto_svc)
    onto_svc.start_turn("core_orphan_dead", agent_kernel_id="coreagent", origin="web")
    onto_svc.start_turn("core_attached_live", agent_kernel_id="coreagent", origin="web")

    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(
        session_service_mod,
        "collect_live_runtime_probes",
        lambda **_kw: LiveRuntimeProbes(),
    )
    monkeypatch.setattr(
        life,
        "_list_coreagent_tmux_panes",
        lambda: [
            life._OrphanTmuxPane(
                tmux_name="frago-agent-core_orphan_dead",
                session_id="core_orphan_dead",
                attached_count=0,
                activity_ts=100.0,
                pane_cmd="zsh",
                pane_dead=True,
            ),
            life._OrphanTmuxPane(
                tmux_name="frago-agent-core_attached_live",
                session_id="core_attached_live",
                attached_count=1,
                activity_ts=100.0,
                pane_cmd="python3",
                pane_dead=False,
            ),
        ],
    )
    killed: list[str] = []
    monkeypatch.setattr(
        life,
        "_kill_tmux_session",
        lambda name: killed.append(name) or True,
    )
    monkeypatch.setattr(host, "panes_dir", lambda: panes_root)

    svc = life.UiSessionLifecycleService()
    summary = svc.reconcile_startup_orphans(now_s=time.time() + 10)

    assert summary["markers_cleaned"] == 1
    assert not dead_marker.exists()
    assert killed == ["frago-agent-core_orphan_dead"]
    assert summary["tmux_killed"] == 1
    dead_rec = onto_svc.get_session("core_orphan_dead")
    assert dead_rec is not None and dead_rec.lifecycle_state == "completed"
    live_rec = onto_svc.get_session("core_attached_live")
    assert live_rec is not None and live_rec.lifecycle_state == "running"


def _seed_coreagent_jsonl(path, events, *, mtime_s: float) -> None:
    import json
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(ev, ensure_ascii=False) for ev in events) + "\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime_s, mtime_s))


def _seed_live_marker(panes_root, run_root, sid: str, pid: int):
    import json

    run_dir = run_root / f"run_{sid}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "core.pid").write_text(str(pid), encoding="utf-8")
    (run_dir / "launch.json").write_text(
        json.dumps({"session_id": sid}, ensure_ascii=False), encoding="utf-8"
    )
    marker = panes_root / f"{sid}.active_run"
    marker.write_text(str(run_dir), encoding="utf-8")
    return marker


def test_d2_reconcile_startup_orphans_spares_live_long_tool_session_beyond_90s_and_worker_idle(
    monkeypatch, tmp_path
):
    """D2: 运行超过 90s（且超过 worker_idle_timeout_s=300s）的长耗时工具活会话不被误杀或误标 startup_orphan_error。"""
    import json
    import os

    from frago.agent_driver import coreagent_pane_host as host
    from frago.server.services import coreagent_runner
    from frago.server.services import ui_session_lifecycle as life
    from frago.session import coreagent_store
    from frago.session import service as session_service_mod
    from frago.session.service import LiveRuntimeProbes, SessionOntologyService
    from frago.session.store import SessionOntologyStore

    now_s = time.time()
    panes_root = tmp_path / "panes"
    panes_root.mkdir(parents=True, exist_ok=True)
    runs_root = tmp_path / "runs"
    core_root = tmp_path / "coreagent_sessions"
    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(panes_root))
    monkeypatch.setattr(host, "panes_dir", lambda: panes_root)
    monkeypatch.setattr(coreagent_store, "sessions_root", lambda: core_root)

    sid_web = "core_d2_long_tool_web"
    sid_worker = "core_d2_long_tool_worker"
    marker_web = _seed_live_marker(panes_root, runs_root, sid_web, os.getpid())
    marker_worker = _seed_live_marker(panes_root, runs_root, sid_worker, os.getpid())

    tool_events = [
        {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "long build"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_long_1",
                        "name": "Bash",
                        "input": {"command": "pytest --full"},
                    }
                ],
            },
        },
    ]
    # 静默 420s：远超 90s 中断窗，也超过 worker_idle_timeout_s=300s
    _seed_coreagent_jsonl(core_root / "-tmp-demo" / f"{sid_web}.jsonl", tool_events, mtime_s=now_s - 420.0)
    _seed_coreagent_jsonl(core_root / "-tmp-demo" / f"{sid_worker}.jsonl", tool_events, mtime_s=now_s - 420.0)

    store_path = tmp_path / "session-ontology-store.json"
    store = SessionOntologyStore(
        store_path,
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    onto_svc = SessionOntologyService(store=store)
    monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: onto_svc)
    onto_svc.start_turn(sid_web, agent_kernel_id="coreagent", origin="web")
    onto_svc.start_turn(sid_worker, agent_kernel_id="coreagent", origin="worker")

    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(
        session_service_mod,
        "collect_live_runtime_probes",
        lambda **_kw: LiveRuntimeProbes(),
    )
    monkeypatch.setattr(
        life,
        "_list_coreagent_tmux_panes",
        lambda: [
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid_web}",
                session_id=sid_web,
                attached_count=0,
                activity_ts=now_s - 420.0,
                pane_cmd="python3",
                pane_dead=False,
            ),
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid_worker}",
                session_id=sid_worker,
                attached_count=0,
                activity_ts=now_s - 420.0,
                pane_cmd="python3",
                pane_dead=False,
            ),
        ],
    )
    killed: list[str] = []
    monkeypatch.setattr(life, "_kill_tmux_session", lambda name: killed.append(name) or True)

    svc = life.UiSessionLifecycleService()
    summary = svc.reconcile_startup_orphans(now_s=now_s, worker_idle_timeout_s=300.0)

    assert summary["markers_cleaned"] == 0
    assert summary["tmux_killed"] == 0
    assert summary["onto_reconciled"] == 0
    assert killed == []
    assert marker_web.exists()
    assert marker_worker.exists()

    disk = json.loads(store_path.read_text(encoding="utf-8"))["sessions"]
    assert disk[sid_web]["lifecycle_state"] == "running"
    assert disk[sid_web].get("summary") != "startup_orphan_error"
    assert disk[sid_worker]["lifecycle_state"] == "running"
    assert disk[sid_worker].get("summary") != "startup_orphan_error"


def test_d2_reconcile_startup_orphans_marks_live_session_with_real_transcript_error(
    monkeypatch, tmp_path
):
    """D2: 活会话出现真实转录报错（api_error）时应准确标记 error + startup_orphan_error。"""
    import os

    from frago.agent_driver import coreagent_pane_host as host
    from frago.server.services import coreagent_runner
    from frago.server.services import ui_session_lifecycle as life
    from frago.session import coreagent_store
    from frago.session import service as session_service_mod
    from frago.session.service import LiveRuntimeProbes, SessionOntologyService
    from frago.session.store import SessionOntologyStore

    now_s = time.time()
    panes_root = tmp_path / "panes"
    panes_root.mkdir(parents=True, exist_ok=True)
    core_root = tmp_path / "coreagent_sessions"
    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(panes_root))
    monkeypatch.setattr(host, "panes_dir", lambda: panes_root)
    monkeypatch.setattr(coreagent_store, "sessions_root", lambda: core_root)

    sid = "core_d2_real_api_error"
    _seed_live_marker(panes_root, tmp_path / "runs", sid, os.getpid())
    _seed_coreagent_jsonl(
        core_root / "-tmp-demo" / f"{sid}.jsonl",
        [
            {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "hi"}},
            {"type": "system", "subtype": "api_error", "error": "rate_limit_exceeded"},
        ],
        mtime_s=now_s - 30.0,
    )

    store = SessionOntologyStore(
        tmp_path / "session-ontology-store.json",
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    onto_svc = SessionOntologyService(store=store)
    monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: onto_svc)
    onto_svc.start_turn(sid, agent_kernel_id="coreagent", origin="web")

    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(
        session_service_mod,
        "collect_live_runtime_probes",
        lambda **_kw: LiveRuntimeProbes(),
    )
    monkeypatch.setattr(
        life,
        "_list_coreagent_tmux_panes",
        lambda: [
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid}",
                session_id=sid,
                attached_count=0,
                activity_ts=now_s - 30.0,
                pane_cmd="python3",
                pane_dead=False,
            )
        ],
    )
    killed: list[str] = []
    monkeypatch.setattr(life, "_kill_tmux_session", lambda name: killed.append(name) or True)

    svc = life.UiSessionLifecycleService()
    summary = svc.reconcile_startup_orphans(now_s=now_s)

    assert killed == []
    assert summary["onto_reconciled"] == 1
    rec = onto_svc.get_session(sid)
    assert rec is not None
    assert rec.lifecycle_state == "error"
    assert rec.summary == "startup_orphan_error"


def test_d2_reconcile_startup_orphans_reaps_truly_dead_and_zombie_mid_tool_orphans(
    monkeypatch, tmp_path
):
    """D2: 真正死亡的孤儿（死 pane / 退回 shell / 零活进程陈旧记录）以及超过 6h 僵尸上限的会话仍会被准确回收。"""
    import json
    import os

    from frago.agent_driver import coreagent_pane_host as host
    from frago.server.services import coreagent_runner
    from frago.server.services import ui_session_lifecycle as life
    from frago.session import coreagent_store
    from frago.session import service as session_service_mod
    from frago.session.service import LiveRuntimeProbes, SessionOntologyService
    from frago.session.store import SessionOntologyStore

    now_s = time.time()
    panes_root = tmp_path / "panes"
    panes_root.mkdir(parents=True, exist_ok=True)
    core_root = tmp_path / "coreagent_sessions"
    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(panes_root))
    monkeypatch.setattr(host, "panes_dir", lambda: panes_root)
    monkeypatch.setattr(coreagent_store, "sessions_root", lambda: core_root)

    sid_dead_pane = "core_d2_dead_pane"
    sid_shell_exit = "core_d2_shell_exited"
    sid_stale_no_pane = "core_d2_stale_no_pane"
    sid_zombie_tool = "core_d2_zombie_tool"

    # dead pid marker for shell_exit; live pid marker for zombie (>6h)
    _seed_live_marker(panes_root, tmp_path / "runs", sid_shell_exit, 999_999_999)
    _seed_live_marker(panes_root, tmp_path / "runs", sid_zombie_tool, os.getpid())

    tool_events = [
        {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "run"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "tu_dead", "name": "Bash", "input": {"command": "sleep 999"}}],
            },
        },
    ]
    _seed_coreagent_jsonl(core_root / "-tmp-demo" / f"{sid_dead_pane}.jsonl", tool_events, mtime_s=now_s - 200.0)
    _seed_coreagent_jsonl(core_root / "-tmp-demo" / f"{sid_shell_exit}.jsonl", tool_events, mtime_s=now_s - 200.0)
    _seed_coreagent_jsonl(core_root / "-tmp-demo" / f"{sid_stale_no_pane}.jsonl", tool_events, mtime_s=now_s - 200.0)
    _seed_coreagent_jsonl(
        core_root / "-tmp-demo" / f"{sid_zombie_tool}.jsonl",
        tool_events,
        mtime_s=now_s - 7 * 3600.0,
    )

    store_path = tmp_path / "session-ontology-store.json"
    store = SessionOntologyStore(
        store_path,
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    onto_svc = SessionOntologyService(store=store)
    monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: onto_svc)
    for sid in (sid_dead_pane, sid_shell_exit, sid_stale_no_pane, sid_zombie_tool):
        onto_svc.start_turn(sid, agent_kernel_id="coreagent", origin="web")

    # 回拨 sid_stale_no_pane 的 updated_at 以满足步骤 3 的 >60s 条件
    raw_store = json.loads(store_path.read_text(encoding="utf-8"))
    raw_store["sessions"][sid_stale_no_pane]["updated_at"] = int(now_s - 200.0)
    store_path.write_text(json.dumps(raw_store, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(
        session_service_mod,
        "collect_live_runtime_probes",
        lambda **_kw: LiveRuntimeProbes(),
    )
    monkeypatch.setattr(host, "_pid_is_alive", lambda pid: pid == os.getpid())
    monkeypatch.setattr(
        life,
        "_list_coreagent_tmux_panes",
        lambda: [
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid_dead_pane}",
                session_id=sid_dead_pane,
                attached_count=0,
                activity_ts=now_s - 200.0,
                pane_cmd="python3",
                pane_dead=True,
            ),
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid_shell_exit}",
                session_id=sid_shell_exit,
                attached_count=0,
                activity_ts=now_s - 200.0,
                pane_cmd="zsh",
                pane_dead=False,
            ),
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid_zombie_tool}",
                session_id=sid_zombie_tool,
                attached_count=0,
                activity_ts=now_s - 7 * 3600.0,
                pane_cmd="python3",
                pane_dead=False,
            ),
        ],
    )
    killed: list[str] = []
    monkeypatch.setattr(life, "_kill_tmux_session", lambda name: killed.append(name) or True)

    svc = life.UiSessionLifecycleService()
    summary = svc.reconcile_startup_orphans(now_s=now_s)

    assert set(killed) == {
        f"frago-agent-{sid_dead_pane}",
        f"frago-agent-{sid_shell_exit}",
        f"frago-agent-{sid_zombie_tool}",
    }
    assert summary["markers_cleaned"] == 1
    assert summary["tmux_killed"] == 3
    assert summary["onto_reconciled"] == 4

    for sid in (sid_dead_pane, sid_shell_exit, sid_stale_no_pane, sid_zombie_tool):
        rec = onto_svc.get_session(sid)
        assert rec is not None
        assert rec.lifecycle_state == "error", f"{sid} expected error, got {rec.lifecycle_state}"
        assert rec.summary == "startup_orphan_interrupted", f"{sid} expected startup_orphan_interrupted, got {rec.summary}"


def test_d2_reconcile_startup_orphans_never_overwrites_cancelled_session(monkeypatch, tmp_path):
    """D1+D2 联动：人工 cancelled 终态经启动孤儿巡检后不被覆写为 error。"""
    import json

    from frago.agent_driver import coreagent_pane_host as host
    from frago.server.services import coreagent_runner
    from frago.server.services import ui_session_lifecycle as life
    from frago.session import coreagent_store
    from frago.session import service as session_service_mod
    from frago.session.service import LiveRuntimeProbes, SessionOntologyService
    from frago.session.store import SessionOntologyStore

    now_s = time.time()
    panes_root = tmp_path / "panes"
    panes_root.mkdir(parents=True, exist_ok=True)
    core_root = tmp_path / "coreagent_sessions"
    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(panes_root))
    monkeypatch.setattr(host, "panes_dir", lambda: panes_root)
    monkeypatch.setattr(coreagent_store, "sessions_root", lambda: core_root)

    sid = "core_d2_cancelled_protected"
    _seed_coreagent_jsonl(
        core_root / "-tmp-demo" / f"{sid}.jsonl",
        [
            {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "stop me"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu_cancel", "name": "Bash", "input": {"command": "sleep 999"}}],
                },
            },
        ],
        mtime_s=now_s - 300.0,
    )

    store_path = tmp_path / "session-ontology-store.json"
    store = SessionOntologyStore(
        store_path,
        legacy_ledger_path=tmp_path / "agent-launches.json",
    )
    onto_svc = SessionOntologyService(store=store)
    monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: onto_svc)
    onto_svc.start_turn(sid, agent_kernel_id="coreagent", origin="web")
    onto_svc.terminate_agent_session(
        session_id=sid, terminal_status="cancelled", summary="user_cancelled"
    )

    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(
        session_service_mod,
        "collect_live_runtime_probes",
        lambda **_kw: LiveRuntimeProbes(),
    )
    monkeypatch.setattr(
        life,
        "_list_coreagent_tmux_panes",
        lambda: [
            life._OrphanTmuxPane(
                tmux_name=f"frago-agent-{sid}",
                session_id=sid,
                attached_count=0,
                activity_ts=now_s - 300.0,
                pane_cmd="zsh",
                pane_dead=True,
            )
        ],
    )
    monkeypatch.setattr(life, "_kill_tmux_session", lambda _name: True)

    svc = life.UiSessionLifecycleService()
    summary = svc.reconcile_startup_orphans(now_s=now_s)

    assert summary["onto_reconciled"] == 0
    disk = json.loads(store_path.read_text(encoding="utf-8"))["sessions"][sid]
    assert disk["lifecycle_state"] == "cancelled"
    assert disk["summary"] == "user_cancelled"


