"""会话工作台的三个只读接口（spec 20260729-session-workbench-webui Phase 2）。

这些用例盯的是接口这一层自己的承诺，不复验翻译层：两家的会话在同一份清单里、
一次拉不走整场、报错类的原文一律拿不到。翻译层怎么归类由 ``tests/unit/session/``
那三份用例把关，这里全部走打桩的翻译层，不碰真实档案。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from frago.session import adapters, record_reader
from frago.session.record_reader import MAX_LIMIT, SessionCard
from frago.session.unified_record import UnifiedRecord

# 三家的会话编号形状——``detect_family()`` 只认这几种形状，用例照真实形状写。
CC_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
OC_SID = "ses_058288655ffeYMxYC1AZKCcv56"
CORE_SID = "core_1b1a419957324f25a53914ede703c501"


def _card(sid: str, family: str, last_active: int) -> SessionCard:
    return SessionCard(
        session_id=sid,
        family=family,  # type: ignore[arg-type]
        title=f"{family} 的一场会话",
        directory="/tmp/somewhere",
        created_at=last_active - 1000,
        last_active_at=last_active,
    )


class _FakeAdapter:
    """一家翻译层的替身。记下自己被要了多少条，好验证上限确实卡在核心数据层。"""

    def __init__(self, total: int = 10_000, raw: dict | None = None) -> None:
        self.total = total
        self.raw = raw
        self.asked_limit: int | None = None
        self.asked_after: int | None = None

    def to_unified(
        self, session_id: str, after: int, limit: int, tail: bool = False
    ) -> list[UnifiedRecord]:
        self.asked_after = after
        self.asked_limit = limit
        if tail:
            start, end = max(self.total - limit, 0), self.total
        else:
            start, end = after, min(after + limit, self.total)
        return [
            UnifiedRecord(
                id=f"rec-{seq}",
                session_id=session_id,
                group_id=None,
                seq=seq,
                ts=1_700_000_000_000 + seq,
                kind="user.say",
                payload={"text": f"第 {seq} 条"},
            )
            for seq in range(start, end)
        ]

    def read_raw(self, session_id: str, record_id: str) -> dict | None:
        # 报错类在翻译层就已经返回空，这里照搬那个行为：编号带 error 标记的一律不给。
        if "error" in record_id:
            return None
        return self.raw


@pytest.fixture
def client():
    from frago.server.app import create_app

    # Loopback seat: the workbench is the owner's own UI. Non-local callers hit
    # the access-zone middleware first (see test_security.py).
    return TestClient(create_app(), client=("127.0.0.1", 50000))


@pytest.fixture
def adapter(monkeypatch):
    """两家都换成同一个替身，接口测试不碰真实档案。"""
    fake = _FakeAdapter(raw={"uuid": "rec-3", "type": "user", "message": "原文在此"})
    monkeypatch.setattr(adapters, "get_adapter", lambda _family: fake)
    return fake


class TestSessionList:
    def test_two_families_share_one_list(self, client, monkeypatch):
        """左栏一份清单要同时装下两家，只列一家等于另一家的会话不存在。"""
        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [_card(OC_SID, "opencode", 3000), _card(CC_SID, "claude-code", 2000)],
        )
        body = client.get("/api/workbench/sessions").json()
        assert [row["family"] for row in body] == ["opencode", "claude-code"]

    def test_every_row_carries_the_family(self, client, monkeypatch):
        """界面要按家族分样式，缺了这个字段就只能靠编号形状去猜。"""
        monkeypatch.setattr(
            record_reader, "list_sessions", lambda: [_card(CC_SID, "claude-code", 2000)]
        )
        row = client.get("/api/workbench/sessions").json()[0]
        assert set(row) == {
            "session_id",
            "family",
            "title",
            "raw_title",
            "custom_title",
            "directory",
            "created_at",
            "last_active_at",
            "last_reply_at",
            "agent_paths",
            "status",
            "lifecycle_state",
            "digest_done",
            "digest_stuck",
            # 这场是人开的还是 frago 派出去的 worker、以及谁派的。左栏据此把清单摆成
            # 两层，缺了就只能靠编号形状在界面上再猜一遍。
            "origin",
            "parent_session_id",
            # 作为子会话的种类（派活 / 分支 / 交接）与收口没有。分支算人开的，却也折在原会话下。
            "relation",
            # 此刻开在 tmux 里没有，左栏据此挂流光。
            "in_tmux",
            # 开着时那个 tmux 会话的名字，「关闭 tmux 会话」弹窗原样摆出来。
            "tmux_name",
            # 这一场此刻还活着（比 in_tmux 宽一格，含 CoreAgent 的常驻进程）。会话详情页
            # 照它决定推不推、轮不轮询，缺了它页面就会停在发出那句话的那一刻。
            "alive",
            # 这一场是否归在「本机管理」（定时任务等），左栏日常清单据此默认不混入主干。
            "local_ops",
            # 由员工岗位入口创建的会话所归属的岗位编号（如 stock），左栏据此展示非文字员工标识。
            "employee_id",
            # 岗位的中文名与配色：左栏按岗位编号标会话时，把这两样一起摆出来。
            # 编号是机器认的，名字才是人认的；只给编号，界面上就只剩一串字母。
            "employee_title",
            "employee_color",
            # 岗位的头像解析态（默认确定性 Micah / 内置选定 / 受控上传图及降级标记），
            # 左栏据此渲染员工头像并与员工页保持一致。
            "employee_avatar",
            # 异步派发聚合态：是否有运行中子 Worker、是否有排队/投递中回调、是否真有待拍板事项。
            "has_running_worker",
            "callback_queued",
            "callback_inbox",
            "need_decision",
        }

    def test_开在tmux里的那一场才标上(self, client, monkeypatch):
        """只按名字 ``frago-agent-<编号>`` 对；没有同名 tmux 会话的一律 false。"""
        from frago.server.services import tmux_sessions_service as tsvc

        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [_card(CC_SID, "claude-code", 3000), _card(OC_SID, "opencode", 2000)],
        )
        monkeypatch.setattr(
            tsvc, "open_session_names", lambda: {f"frago-agent-{CC_SID}", "feishu_oc_x"}
        )
        body = client.get("/api/workbench/sessions").json()
        assert [row["in_tmux"] for row in body] == [True, False]
        assert [row["tmux_name"] for row in body] == [f"frago-agent-{CC_SID}", None]

    def test_tmux没起来就全是false而不是报错(self, client, monkeypatch):
        from frago.server.services import tmux_sessions_service as tsvc

        monkeypatch.setattr(
            record_reader, "list_sessions", lambda: [_card(CC_SID, "claude-code", 2000)]
        )
        monkeypatch.setattr(tsvc, "_tmux", lambda *_a: "")
        response = client.get("/api/workbench/sessions")
        assert response.status_code == 200
        assert response.json()[0]["in_tmux"] is False

    def test_coreagent那一场不在tmux里也算活着(self, client, monkeypatch):
        """CoreAgent NEVER 开在 tmux 里，按 tmux 判它永远是死的。

        详情页的两条取数通道共用这一条判据，判成死的就等于页面停在发出那句话的那一刻
        （2026-10-08 修）。所以 ``alive`` 必须比 ``in_tmux`` 宽出这一格。
        """
        from frago.server.services import coreagent_runner
        from frago.server.services import tmux_sessions_service as tsvc

        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [
                _card(CORE_SID, "coreagent", 3000),
                _card(CC_SID, "claude-code", 2000),
            ],
        )
        # tmux 里一场都没有；CoreAgent 那一场常驻进程还在。
        monkeypatch.setattr(tsvc, "open_session_names", lambda: set())
        monkeypatch.setattr(coreagent_runner, "live_states", lambda: {CORE_SID: True})

        body = client.get("/api/workbench/sessions").json()

        assert [row["in_tmux"] for row in body] == [False, False]
        assert [row["alive"] for row in body] == [True, False], (
            "CoreAgent 活着要认，「不在 tmux 里又没常驻进程」的不能跟着算活着"
        )

    def test_dispatch_worker_and_callback_and_decision_flags(self, client, monkeypatch, tmp_path):
        """透出 has_running_worker / callback_queued / need_decision：在跑 Worker 不误报待拍板。"""
        from pathlib import Path

        from frago.server.routes import workbench as wb_route
        from frago.server.services import coreagent_runner, session_observer
        from frago.server.services import tmux_sessions_service as tsvc
        from frago.session.async_dispatch import AsyncDispatchJob, save_dispatch_job

        wb_route._OBSERVER_DECISION_CACHE.clear()
        wb_route._TRAILING_CARD_CACHE.clear()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))

        parent_running = "11111111-1111-1111-1111-111111111111"
        parent_cb = "22222222-2222-2222-2222-222222222222"
        parent_decision = "33333333-3333-3333-3333-333333333333"
        parent_plain = "44444444-4444-4444-4444-444444444444"
        worker_run = "core_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        # 1. parent_running 派发了一个 running 的 worker
        save_dispatch_job(
            AsyncDispatchJob(
                job_id="disp-run",
                kind="worker",
                mode="new",
                caller_session_id=parent_running,
                caller_employee_id=None,
                caller_cwd=str(tmp_path),
                target_session_id=worker_run,
                target_name=worker_run,
                employee_id=None,
                agent="coreagent",
                cwd=str(tmp_path),
                prompt="task",
                task_summary="task",
                resume=None,
                model=None,
                timeout=None,
                status="running",
                delivery_state="queued",
            )
        )
        # 2. parent_cb 的 worker 已结束，但 callback 仍在排队投递
        save_dispatch_job(
            AsyncDispatchJob(
                job_id="disp-cb",
                kind="worker",
                mode="new",
                caller_session_id=parent_cb,
                caller_employee_id=None,
                caller_cwd=str(tmp_path),
                target_session_id="core_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                target_name="core_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                employee_id=None,
                agent="coreagent",
                cwd=str(tmp_path),
                prompt="task",
                task_summary="task",
                resume=None,
                model=None,
                timeout=None,
                status="completed",
                delivery_state="queued",
            )
        )
        # 3. parent_decision 在 observer-slots.json 中有真实 waiting 事项与 decision
        dec_dir = session_observer.session_dir(parent_decision, "agy")
        dec_slots = session_observer.empty_slots(parent_decision, "agy")
        dec_slots["decision"] = "选方案 A 还是 B？"
        dec_slots["tasks"] = [{"id": "T1", "title": "拍板方案", "status": "waiting", "actor": "主会话", "conclusion": ""}]
        session_observer.save_slots(dec_dir, dec_slots)

        # 4. parent_plain 已办结且无待拍板事项
        plain_dir = session_observer.session_dir(parent_plain, "agy")
        plain_slots = session_observer.empty_slots(parent_plain, "agy")
        plain_slots["tasks"] = [{"id": "T1", "title": "回答问题", "status": "done", "actor": "主会话", "conclusion": "已完成"}]
        session_observer.save_slots(plain_dir, plain_slots)

        monkeypatch.setattr(tsvc, "open_session_names", lambda: set())
        monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [
                SessionCard(
                    session_id=parent_running,
                    family="agy",
                    title="运行中父会话",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=4000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=worker_run,
                    family="coreagent",
                    title="运行中 Worker",
                    directory=str(tmp_path),
                    created_at=1500,
                    last_active_at=4000,
                    status="running",
                    origin="worker",
                    parent_session_id=parent_running,
                ),
                SessionCard(
                    session_id=parent_cb,
                    family="agy",
                    title="待回传父会话",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=3000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=parent_decision,
                    family="agy",
                    title="真待拍板会话",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=parent_plain,
                    family="agy",
                    title="普通已答完会话",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=1500,
                    status="done",
                    origin="human",
                ),
            ],
        )

        body = {r["session_id"]: r for r in client.get("/api/workbench/sessions").json()}
        assert body[parent_running]["has_running_worker"] is True
        assert body[parent_running]["callback_queued"] is False
        assert body[parent_running]["need_decision"] is False

        assert body[parent_cb]["has_running_worker"] is False
        assert body[parent_cb]["callback_queued"] is True
        assert body[parent_cb]["need_decision"] is False

        assert body[parent_decision]["has_running_worker"] is False
        assert body[parent_decision]["callback_queued"] is False
        assert body[parent_decision]["need_decision"] is True

        assert body[parent_plain]["has_running_worker"] is False
        assert body[parent_plain]["callback_queued"] is False
        assert body[parent_plain]["need_decision"] is False

    def test_stale_zombie_dispatches_and_observer_done_converge_to_false(self, client, monkeypatch, tmp_path):
        """历史僵尸派发单（superseded+queued / 超期未活 running / 主会话已回复超越 / observer 全部 done）绝不污染左栏状态。"""
        from pathlib import Path

        from frago.server.routes import workbench as wb_route
        from frago.server.services import coreagent_runner, session_observer
        from frago.server.services import tmux_sessions_service as tsvc
        from frago.session.async_dispatch import AsyncDispatchJob, save_dispatch_job

        wb_route._OBSERVER_DECISION_CACHE.clear()
        wb_route._TRAILING_CARD_CACHE.clear()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))

        sid_superseded = "55555555-5555-5555-5555-555555555555"
        sid_overtaken = "66666666-6666-6666-6666-666666666666"
        sid_obs_done = "77777777-7777-7777-7777-777777777777"
        sid_stale_run = "88888888-8888-8888-8888-888888888888"
        sid_idle_tmux_worker = "99999999-9999-9999-9999-999999999999"
        worker_idle_tmux = "aaaa9999-9999-9999-9999-999999999999"
        worker_dead = "core_cccccccccccccccccccccccccccccccc"

        old_iso = "2026-11-10T01:00:00Z"
        old_ms = int(1794272400 * 1000)

        # 1. superseded + queued（Investigate 400 同款）
        save_dispatch_job(
            AsyncDispatchJob(
                job_id="disp-superseded-zombie",
                kind="worker",
                mode="new",
                caller_session_id=sid_superseded,
                caller_employee_id=None,
                caller_cwd=str(tmp_path),
                target_session_id=worker_dead,
                target_name=worker_dead,
                employee_id=None,
                agent="coreagent",
                cwd=str(tmp_path),
                prompt="task",
                task_summary="task",
                resume=None,
                model=None,
                timeout=None,
                status="superseded",
                delivery_state="queued",
                created_at=old_iso,
                completed_at=old_iso,
            )
        )
        # 2. completed + queued 但主会话 last_reply_at 明显晚于 completed_at（已被消化超越）
        save_dispatch_job(
            AsyncDispatchJob(
                job_id="disp-overtaken",
                kind="worker",
                mode="new",
                caller_session_id=sid_overtaken,
                caller_employee_id=None,
                caller_cwd=str(tmp_path),
                target_session_id="core_dddddddddddddddddddddddddddddddd",
                target_name="core_dddddddddddddddddddddddddddddddd",
                employee_id=None,
                agent="coreagent",
                cwd=str(tmp_path),
                prompt="task",
                task_summary="task",
                resume=None,
                model=None,
                timeout=None,
                status="completed",
                delivery_state="queued",
                created_at="2026-11-15T01:00:00Z",
                completed_at="2026-11-15T01:05:00Z",
            )
        )
        # 3. queued 单但在 observer-slots.json 中所有事项已 done
        save_dispatch_job(
            AsyncDispatchJob(
                job_id="disp-obs-done",
                kind="worker",
                mode="new",
                caller_session_id=sid_obs_done,
                caller_employee_id=None,
                caller_cwd=str(tmp_path),
                target_session_id="core_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                target_name="core_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                employee_id=None,
                agent="coreagent",
                cwd=str(tmp_path),
                prompt="task",
                task_summary="task",
                resume=None,
                model=None,
                timeout=None,
                status="completed",
                delivery_state="queued",
            )
        )
        done_dir = session_observer.session_dir(sid_obs_done, "agy")
        done_slots = session_observer.empty_slots(sid_obs_done, "agy")
        done_slots["tasks"] = [{"id": "T1", "title": "已办结事项", "status": "done", "actor": "主会话", "conclusion": "ok"}]
        session_observer.save_slots(done_dir, done_slots)

        # 4. 超期 >60s 且目标不存活的 running 僵尸单
        save_dispatch_job(
            AsyncDispatchJob(
                job_id="disp-stale-running",
                kind="worker",
                mode="new",
                caller_session_id=sid_stale_run,
                caller_employee_id=None,
                caller_cwd=str(tmp_path),
                target_session_id=worker_dead,
                target_name=worker_dead,
                employee_id=None,
                agent="coreagent",
                cwd=str(tmp_path),
                prompt="task",
                task_summary="task",
                resume=None,
                model=None,
                timeout=None,
                status="running",
                delivery_state="queued",
                created_at=old_iso,
            )
        )

        # 5. 常驻子会话在 tmux 中活着但状态已是 done，绝不能反推父会话 has_running_worker=True
        monkeypatch.setattr(tsvc, "open_session_names", lambda: {f"frago-agent-{worker_idle_tmux}"})
        monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
        monkeypatch.setattr(
            record_reader,
            "list_sessions",
            lambda: [
                SessionCard(
                    session_id=sid_superseded,
                    family="agy",
                    title="Superseded 残留",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=sid_overtaken,
                    family="agy",
                    title="主会话已有新回复",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=old_ms + 999_000_000,
                    last_reply_at=int(datetime.fromisoformat("2026-11-15T02:00:00+00:00").timestamp() * 1000),
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=sid_obs_done,
                    family="agy",
                    title="Observer 全已办结",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=sid_stale_run,
                    family="agy",
                    title="目标已死僵尸 running",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=worker_dead,
                    family="coreagent",
                    title="死掉的 Worker",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="idle",
                    origin="worker",
                    parent_session_id=sid_stale_run,
                ),
                SessionCard(
                    session_id=sid_idle_tmux_worker,
                    family="agy",
                    title="挂了空闲常驻子会话",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="done",
                    origin="human",
                ),
                SessionCard(
                    session_id=worker_idle_tmux,
                    family="agy",
                    title="闲置开着tmux的子员工",
                    directory=str(tmp_path),
                    created_at=1000,
                    last_active_at=2000,
                    status="done",
                    origin="worker",
                    parent_session_id=sid_idle_tmux_worker,
                ),
            ],
        )

        body = {r["session_id"]: r for r in client.get("/api/workbench/sessions").json()}
        for sid in (sid_superseded, sid_overtaken, sid_obs_done, sid_stale_run, sid_idle_tmux_worker):
            assert body[sid]["has_running_worker"] is False, f"{sid} should not have running worker"
            assert body[sid]["callback_queued"] is False, f"{sid} should not have callback_queued"

    def test_coreagent那一场收摊了就不算活着(self, client, monkeypatch):
        """空闲回收掉、真正关掉的那一场回落成不盯——省资源的本意不变。"""
        from frago.server.services import coreagent_runner
        from frago.server.services import tmux_sessions_service as tsvc

        monkeypatch.setattr(
            record_reader, "list_sessions", lambda: [_card(CORE_SID, "coreagent", 3000)]
        )
        monkeypatch.setattr(tsvc, "open_session_names", lambda: set())
        monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})

        row = client.get("/api/workbench/sessions").json()[0]
        assert row["alive"] is False

    def test_每行都带状态与摘要(self, client, monkeypatch):
        """左栏最值钱的是"一眼看出每场什么情况"。这三样不出接口，左栏就只能按来源分组。"""
        card = _card(CC_SID, "claude-code", 2000)
        card.status = "error"
        card.digest_done = "把镜头判断追加进了 verdict.jsonl"
        card.digest_stuck = "API Error: Connection closed mid-response."
        monkeypatch.setattr(record_reader, "list_sessions", lambda: [card])

        row = client.get("/api/workbench/sessions").json()[0]

        assert row["status"] == "error"
        assert row["digest_done"] == "把镜头判断追加进了 verdict.jsonl"
        assert row["digest_stuck"] == "API Error: Connection closed mid-response."

    def test_没有摘要时是空值而不是编一句(self, client, monkeypatch):
        """取不到就该露出取不到。塞一句占位的话，人会当成真的发生过。"""
        monkeypatch.setattr(
            record_reader, "list_sessions", lambda: [_card(CC_SID, "claude-code", 2000)]
        )
        row = client.get("/api/workbench/sessions").json()[0]
        assert row["digest_done"] is None
        assert row["digest_stuck"] is None

    def test_order_comes_from_the_data_layer_untouched(self, client, monkeypatch):
        """排序在核心数据层做完了，接口不许再排一次——两处各排一遍迟早各排各的。"""
        given = [_card("ses_a", "opencode", 9), _card("ses_b", "opencode", 5)]
        monkeypatch.setattr(record_reader, "list_sessions", lambda: given)
        body = client.get("/api/workbench/sessions").json()
        assert [row["session_id"] for row in body] == ["ses_a", "ses_b"]

    def test_empty_install_is_an_empty_list_not_an_error(self, client, monkeypatch):
        monkeypatch.setattr(record_reader, "list_sessions", list)
        response = client.get("/api/workbench/sessions")
        assert response.status_code == 200
        assert response.json() == []

    def test_schedule_origin_never_marks_need_decision_true(self, client, monkeypatch, tmp_path):
        """定时任务会话（origin='schedule' 或 local_ops）绝不标成 need_decision=True 幽灵挂起。"""
        from frago.server.routes import workbench as wb_route
        from frago.session import service as session_service_mod
        from frago.session import store as session_store_mod
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyStore

        wb_route._OBSERVER_DECISION_CACHE.clear()
        wb_route._TRAILING_CARD_CACHE.clear()

        store = SessionOntologyStore(
            tmp_path / "session-ontology-store.json",
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store)
        svc.launch_agent_session(
            session_id=CORE_SID,
            agent_kernel_id="coreagent",
            origin="schedule",
            initial_prompt="定时梳理",
            is_worker=False,
            cwd=str(tmp_path),
        )
        monkeypatch.setattr(session_store_mod, "_DEFAULT_SESSION_STORE", store)
        monkeypatch.setattr(session_service_mod, "_DEFAULT_SESSION_SERVICE", svc)
        monkeypatch.setattr(session_service_mod, "get_default_session_service", lambda: svc)

        card = _card(CORE_SID, "coreagent", 3000)
        card.origin = "schedule"
        assert wb_route._session_needs_decision(
            card,
            status="idle",
            is_alive=False,
            has_running_worker=False,
            callback_queued=False,
            now_ms=9_999_999,
            slots_need_decision=True,
        ) is False

        # 即使 card.origin 仍为 human，本体登记 origin='schedule' 也会在行构建中归位为 schedule 且 need_decision=False
        raw_card = _card(CORE_SID, "coreagent", 3000)
        monkeypatch.setattr(record_reader, "list_sessions", lambda: [raw_card])
        monkeypatch.setattr(wb_route, "_observer_slots_state", lambda _sid, _fam: (True, False))

        rows = client.get("/api/workbench/sessions").json()
        assert len(rows) == 1
        assert rows[0]["origin"] == "schedule"
        assert rows[0]["need_decision"] is False


class TestRecords:
    def test_first_page_starts_at_zero(self, client, adapter):
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?after=0&limit=5").json()
        assert [row["seq"] for row in body] == [0, 1, 2, 3, 4]

    def test_cursor_is_the_first_seq_of_this_batch(self, client, adapter):
        """``after`` 是闭区间起点。做成排他游标的话默认值 0 会把开口第一句吃掉。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?after=7&limit=3").json()
        assert [row["seq"] for row in body] == [7, 8, 9]

    def test_a_record_arrives_whole(self, client, adapter):
        row = client.get(f"/api/workbench/sessions/{CC_SID}/records?limit=1").json()[0]
        assert set(row) == {
            "id",
            "session_id",
            "group_id",
            "seq",
            "ts",
            "kind",
            "agent_path",
            "payload",
            "raw_available",
        }

    def test_default_page_is_two_hundred(self, client, adapter):
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records").json()
        assert len(body) == 200

    def test_asking_for_the_whole_session_still_gets_one_page(self, client, adapter):
        """单条工具结果见过 7.2 万字符。一次拉整场会把浏览器打死，上限硬卡。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?limit=99999").json()
        assert len(body) == MAX_LIMIT
        assert adapter.asked_limit == MAX_LIMIT

    def test_the_cap_is_not_an_error(self, client, adapter):
        """越界截断，不是 422——界面传大了不该让这一屏内容整个被扣下。"""
        assert client.get(f"/api/workbench/sessions/{CC_SID}/records?limit=99999").status_code == 200

    def test_opencode_session_reads_the_same_way(self, client, adapter):
        body = client.get(f"/api/workbench/sessions/{OC_SID}/records?limit=2").json()
        assert [row["session_id"] for row in body] == [OC_SID, OC_SID]

    def test_unknown_id_shape_is_not_found(self, client, adapter):
        """两家的形状都不像时回 404，NEVER 猜一家试试翻出个空的当「没记录」。"""
        assert client.get("/api/workbench/sessions/不像任何一家/records").status_code == 404

    def test_tail_returns_the_last_page(self, client, adapter):
        """中栏打开会话要直接落在最新内容上，而不是从头一页页翻到尾。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?tail=true&limit=5").json()
        assert [row["seq"] for row in body] == [9995, 9996, 9997, 9998, 9999]

    def test_tail_ignores_the_cursor(self, client, adapter):
        """tail 模式下 after 没有意义，给了也当被给。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?tail=true&after=7&limit=3").json()
        assert [row["seq"] for row in body] == [9997, 9998, 9999]

    def test_tail_still_caps_the_page(self, client, adapter):
        """尾部读取同样受上限硬卡，分页纪律对两个方向一视同仁。"""
        body = client.get(f"/api/workbench/sessions/{CC_SID}/records?tail=true&limit=99999").json()
        assert len(body) == MAX_LIMIT
        assert adapter.asked_limit == MAX_LIMIT


class TestRawIsWithheld:
    """报错类取原文必须在服务端拦。那条原文的响应头里带着登录凭据。"""

    def test_error_record_is_forbidden(self, client, adapter):
        response = client.get(
            f"/api/workbench/records/rec-9:error/raw?session_id={CC_SID}"
        )
        assert response.status_code == 403

    def test_error_record_leaks_nothing_in_the_body(self, client, adapter):
        body = client.get(f"/api/workbench/records/rec-9:error/raw?session_id={CC_SID}").text
        assert "原文在此" not in body

    def test_ordinary_record_comes_through(self, client, adapter):
        response = client.get(f"/api/workbench/records/rec-3/raw?session_id={CC_SID}")
        assert response.status_code == 200
        assert response.json()["message"] == "原文在此"

    def test_missing_record_is_withheld_too(self, client, monkeypatch):
        """只有真拿到原文才放行，其余一律不放行。"""
        fake = _FakeAdapter(raw=None)
        monkeypatch.setattr(adapters, "get_adapter", lambda _family: fake)
        assert (
            client.get(f"/api/workbench/records/rec-3/raw?session_id={CC_SID}").status_code == 403
        )

    def test_which_session_must_be_stated(self, client, adapter):
        """记录编号自己定位不到档案：Claude Code 要先找到会话文件，opencode 要先定位会话行。"""
        assert client.get("/api/workbench/records/rec-3/raw").status_code == 422

    def test_unknown_session_shape_is_not_found(self, client, adapter):
        response = client.get("/api/workbench/records/rec-3/raw?session_id=不像任何一家")
        assert response.status_code == 404


class TestSessionSearch:
    """搜会话这一层只做取用与序列化，怎么搜由 ``frago session search`` 那份用例把关。"""

    def _stub(self, monkeypatch, result):
        from frago.session import search

        seen: dict = {}

        def fake(query, **kwargs):
            seen.update(query=query, **kwargs)
            return result

        monkeypatch.setattr(search, "search_sessions", fake)
        return seen

    def _result(self, **overrides):
        from frago.session.search import KeywordPlan, SearchResult

        fields = {
            "query": "飞书",
            "plan": KeywordPlan(["飞书", "lark"], "中英两种叫法", "agent"),
            "hits": [],
            "corpus_root": "/tmp/sessions",
            "scanned_sessions": 7,
            "duration_ms": 12,
        }
        fields.update(overrides)
        return SearchResult(**fields)

    def test_命中的会话与摘要原样交出来(self, client, monkeypatch):
        from frago.session.search import SessionHit, Snippet

        hit = SessionHit(
            source="claude",
            session_id=CC_SID,
            title="飞书推送",
            cwd="/tmp/somewhere",
            last_activity=1_700_000_000.0,
            matched_terms=["飞书"],
            hit_lines=3,
            location="/tmp/sessions/claude/x/raw.jsonl",
            resume_command=f"claude --resume {CC_SID}",
            snippets=[Snippet(term="飞书", text="…把飞书那条推送修一下…")],
        )
        seen = self._stub(monkeypatch, self._result(hits=[hit]))
        body = client.get("/api/workbench/search?q=飞书&top=5").json()
        assert seen == {"query": "飞书", "top": 5}
        assert body["plan"]["terms"] == ["飞书", "lark"]
        assert body["scanned_sessions"] == 7
        (row,) = body["hits"]
        assert row["session_id"] == CC_SID
        assert row["hit_lines"] == 3
        assert row["snippets"][0]["text"] == "…把飞书那条推送修一下…"

    def test_没做全的地方必须报出来(self, client, monkeypatch):
        """做不全却不说，等于谎报覆盖面。"""
        self._stub(monkeypatch, self._result(warnings=["关键词扩展超时，退回原句切词"]))
        assert client.get("/api/workbench/search?q=x").json()["warnings"] == [
            "关键词扩展超时，退回原句切词"
        ]

    def test_不给要搜什么就不受理(self, client):
        assert client.get("/api/workbench/search").status_code == 422
        assert client.get("/api/workbench/search?q=").status_code == 422


class TestExistingRoutesUntouched:
    def test_claude_sessions_prefix_still_answers(self, client):
        """``/api/claude-sessions`` 背后有正在跑的 React 页面，新接口不许挡它的路。"""
        assert client.get("/api/claude-sessions?days=1").status_code == 200
