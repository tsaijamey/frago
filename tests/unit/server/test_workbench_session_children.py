"""会话详情「派生子会话与运行中子进程」探测服务与路由测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from frago.server.services import (
    coreagent_runner,
    session_children,
    tmux_sessions_service,
    workbench_groups,
    workbench_titles,
)
from frago.session import async_dispatch, record_reader, session_origin
from frago.session.async_dispatch import AsyncDispatchJob
from frago.session.record_reader import SessionCard, SessionRelation
from frago.session.session_origin import OriginIndex

PARENT_SID = "49aac63e-2b76-4639-921f-0e294e33e9c4"
CHILD_SID = "cc1f28d6-a6f2-55f9-8680-b4313d310584"
GRAND_SID = "dd2e39e7-b703-460a-9791-c5424e421695"
BRANCH_SID = "ee3f40f8-c814-471b-a802-d6535f532706"


def _card(
    sid: str,
    *,
    title: str = "测试会话",
    status: str = "done",
    last_active: int = 1_700_000_000_000,
    family: str = "claude-code",
) -> SessionCard:
    return SessionCard(
        session_id=sid,
        family=family,  # type: ignore[arg-type]
        title=title,
        directory="/tmp/work",
        created_at=last_active - 5_000,
        last_active_at=last_active,
        last_reply_at=last_active,
        status=status,  # type: ignore[arg-type]
    )


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def _patch_clean_env(monkeypatch, cards: list[SessionCard]):
    monkeypatch.setattr(record_reader, "list_sessions", lambda: cards)
    monkeypatch.setattr(workbench_titles, "load", lambda: {})
    monkeypatch.setattr(workbench_groups, "local_ops_session_ids", lambda: set())
    monkeypatch.setattr(async_dispatch, "list_dispatch_jobs", lambda active_only=False: [])
    monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
    monkeypatch.setattr(coreagent_runner, "live_snapshot", lambda: [])
    monkeypatch.setattr(tmux_sessions_service, "open_session_names", lambda: set())
    monkeypatch.setattr(tmux_sessions_service, "find_for_session", lambda _sid: None)
    monkeypatch.setattr(session_children, "_tmux_panes", lambda: {})
    monkeypatch.setattr(session_children, "_snapshot_processes", lambda: ({}, {}))
    monkeypatch.setattr(session_origin, "_ledger_entries", lambda: [])


class TestSessionChildrenProbe:
    def test_unknown_session_returns_404(self, client):
        resp = client.get("/api/workbench/sessions/not-a-valid-sid/children")
        assert resp.status_code == 404

    def test_origin_hierarchy_and_launched_by(self, client, monkeypatch):
        cards = [
            _card(PARENT_SID, title="主控会话：清理 todo", status="done", last_active=1_700_000_010_000),
            _card(CHILD_SID, title="Worker 1：核实任务细节\n附带多行长提示", status="running", last_active=1_700_000_020_000),
            _card(GRAND_SID, title="二级 Worker：跑单测", status="done", last_active=1_700_000_025_000),
            _card(BRANCH_SID, title="分支：排查报错", status="done", last_active=1_700_000_030_000),
        ]
        _patch_clean_env(monkeypatch, cards)
        monkeypatch.setattr(
            tmux_sessions_service,
            "open_session_names",
            lambda: {session_children.tmux_name_for(CHILD_SID)},
        )
        monkeypatch.setattr(
            session_origin,
            "load_origin_index",
            lambda: OriginIndex(
                workers=frozenset({CHILD_SID, GRAND_SID}),
                parents={CHILD_SID: PARENT_SID, GRAND_SID: CHILD_SID, BRANCH_SID: PARENT_SID},
                relations={
                    CHILD_SID: SessionRelation(kind="dispatch", closed=False),
                    GRAND_SID: SessionRelation(kind="dispatch", closed=False),
                    BRANCH_SID: SessionRelation(kind="branch", closed=False),
                },
            ),
        )

        # 父会话视角：能看到子 Worker、二级 Worker 和分支，且知道谁是 running
        resp = client.get(f"/api/workbench/sessions/{PARENT_SID}/children")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == PARENT_SID
        assert body["launched_by"] is None
        assert body["summary"]["total_children"] == 3
        assert body["summary"]["running_children"] == 1
        assert body["summary"]["has_running"] is True

        by_id = {c["session_id"]: c for c in body["child_sessions"]}
        assert by_id[CHILD_SID]["is_running"] is True
        assert by_id[CHILD_SID]["launched_by_session_id"] == PARENT_SID
        assert by_id[CHILD_SID]["launched_by_label"] == "由当前会话派发"
        assert by_id[GRAND_SID]["launched_by_session_id"] == CHILD_SID
        assert by_id[GRAND_SID]["is_running"] is False
        assert "由子会话「Worker 1：核实任务细节 附带多行长提示」派发" == by_id[GRAND_SID]["launched_by_label"]
        assert by_id[BRANCH_SID]["relation_kind"] == "branch"
        assert by_id[BRANCH_SID]["launched_by_label"] == "由当前会话分出分支"

        # 子会话视角：清楚标明自己由谁启动
        child_resp = client.get(f"/api/workbench/sessions/{CHILD_SID}/children")
        assert child_resp.status_code == 200
        child_body = child_resp.json()
        assert child_body["launched_by"]["session_id"] == PARENT_SID
        assert "主控会话：清理 todo" in child_body["launched_by"]["label"]
        assert child_body["summary"]["total_children"] == 1

    def test_async_dispatch_pending_visible_before_transcript_flush(self, client, monkeypatch):
        now_iso = datetime.now(timezone.utc).isoformat()
        cards = [_card(PARENT_SID, title="主控会话", status="done")]
        _patch_clean_env(monkeypatch, cards)
        monkeypatch.setattr(session_origin, "load_origin_index", lambda: OriginIndex(parents={}, workers=frozenset()))
        monkeypatch.setattr(
            session_origin,
            "_ledger_entries",
            lambda: [
                {
                    "child": CHILD_SID,
                    "parent": PARENT_SID,
                    "kind": "dispatch",
                    "origin": "worker",
                    "prompt_head": "执行独立业务评审",
                }
            ],
        )
        monkeypatch.setattr(
            async_dispatch,
            "list_dispatch_jobs",
            lambda active_only=False: [
                AsyncDispatchJob(
                    job_id="job-1",
                    kind="employee",
                    mode="invoke",
                    caller_session_id=PARENT_SID,
                    caller_employee_id=None,
                    caller_cwd="/tmp/work",
                    target_session_id=CHILD_SID,
                    target_name="dev-reviewer",
                    employee_id="dev-reviewer",
                    agent="claude",
                    cwd="/tmp/work",
                    prompt="执行独立业务评审",
                    task_summary="执行独立业务评审",
                    status="running",
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            ],
        )

        resp = client.get(f"/api/workbench/sessions/{PARENT_SID}/children")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["running_children"] == 1
        assert body["summary"]["has_running"] is True
        child = body["child_sessions"][0]
        assert child["session_id"] == CHILD_SID
        assert child["status"] == "running"
        assert child["is_running"] is True
        assert child["employee_id"] == "dev-reviewer"
        assert child["launched_by_label"] == "由当前会话调用员工"

    def test_external_claude_resume_process_tree_detected(self, client, monkeypatch):
        """即使外部终端直接运行 `claude --resume <sid>`（不在 tmux 里），也能探测到宿主和子进程。"""
        cards = [_card(PARENT_SID, title="外部终端会话", status="done")]
        _patch_clean_env(monkeypatch, cards)
        monkeypatch.setattr(session_origin, "load_origin_index", lambda: OriginIndex(parents={}, workers=frozenset()))

        Proc = session_children._ProcInfo
        procs = {
            1000: Proc(1000, 1, "Ss", "10:00", "zsh", "-zsh"),
            2000: Proc(2000, 1000, "S+", "05:12", "claude", f"claude --resume {PARENT_SID}"),
            2001: Proc(2001, 2000, "S", "01:05", "bash", "/bin/bash -c pytest tests/unit"),
            2002: Proc(2002, 2001, "R", "00:45", "pytest", f"python3 -m pytest --resume {CHILD_SID}"),
            2003: Proc(2003, 2000, "Z", "00:01", "defunct", "<defunct>"),  # 僵尸进程应跳过
            2004: Proc(2004, 2000, "S", "00:00", "ps", "ps -eo pid=,ppid=,state=,etime=,ucomm=,args="),
        }
        children_by_pid = {
            1000: [2000],
            2000: [2001, 2003, 2004],
            2001: [2002],
        }
        monkeypatch.setattr(session_children, "_snapshot_processes", lambda: (procs, children_by_pid))

        resp = client.get(f"/api/workbench/sessions/{PARENT_SID}/children")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["host_alive"] is True
        assert body["summary"]["running_processes"] == 2
        assert body["summary"]["has_running"] is True

        proc_by_pid = {p["pid"]: p for p in body["child_processes"]}
        assert set(proc_by_pid.keys()) == {2001, 2002}
        assert proc_by_pid[2001]["is_running"] is True
        assert proc_by_pid[2001]["kind"] == "subshell"
        assert "claude · PID 2000" in proc_by_pid[2001]["launched_by_label"]
        assert proc_by_pid[2002]["linked_session_id"] == CHILD_SID
        assert "bash (PID 2001)" in proc_by_pid[2002]["launched_by_label"]

    def test_tmux_pane_host_child_processes_detected(self, client, monkeypatch):
        cards = [_card(PARENT_SID, title="Tmux 会话", status="running")]
        _patch_clean_env(monkeypatch, cards)
        monkeypatch.setattr(session_origin, "load_origin_index", lambda: OriginIndex(parents={}, workers=frozenset()))

        Proc = session_children._ProcInfo
        Pane = session_children._PaneInfo
        tname = session_children.tmux_name_for(PARENT_SID)
        procs = {
            3000: Proc(3000, 1, "Ss", "20:00", "zsh", "-zsh"),
            3001: Proc(3001, 3000, "S+", "18:00", "2.1.281", "claude"),
            3002: Proc(3002, 3001, "S", "00:30", "python3", "python3 long_job.py"),
        }
        children_by_pid = {3000: [3001], 3001: [3002]}
        monkeypatch.setattr(
            session_children,
            "_tmux_panes",
            lambda: {tname: [Pane(session_name=tname, pane_pid=3000, pane_command="2.1.281")]},
        )
        monkeypatch.setattr(session_children, "_snapshot_processes", lambda: (procs, children_by_pid))

        resp = client.get(f"/api/workbench/sessions/{PARENT_SID}/children")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["host_alive"] is True
        assert body["summary"]["running_processes"] == 1
        p = body["child_processes"][0]
        assert p["pid"] == 3002
        assert p["source"] == "tmux_pane"
        assert p["tmux_name"] == tname
        assert p["is_running"] is True

    def test_idle_resident_coreagent_not_reported_as_running(self, client, monkeypatch):
        """常驻 CoreAgent 在回答完毕进入 idle 等待态时，不应把宿主或已完结子会话误报为运行中。"""
        core_parent = "core_11111111111111111111111111111111"
        core_child = "core_22222222222222222222222222222222"
        cards = [
            _card(core_parent, title="CoreAgent 主控", status="done", family="coreagent"),
            _card(core_child, title="CoreAgent 派发子会话", status="done", family="coreagent"),
        ]
        _patch_clean_env(monkeypatch, cards)
        monkeypatch.setattr(
            session_origin,
            "load_origin_index",
            lambda: OriginIndex(
                workers=frozenset({core_child}),
                parents={core_child: core_parent},
                relations={core_child: SessionRelation(kind="dispatch", closed=False)},
            ),
        )
        Proc = session_children._ProcInfo
        procs = {
            4001: Proc(4001, 1, "S", "03:00", "frago-core", f"frago-core --session-id {core_parent}"),
            4002: Proc(4002, 1, "S", "02:00", "frago-core", f"frago-core --session-id {core_child}"),
        }
        monkeypatch.setattr(session_children, "_snapshot_processes", lambda: (procs, {}))
        monkeypatch.setattr(
            coreagent_runner,
            "live_states",
            lambda: {core_parent: False, core_child: False},
        )
        monkeypatch.setattr(
            coreagent_runner,
            "live_snapshot",
            lambda: [
                coreagent_runner.LiveSessionSnapshot(
                    session_id=core_parent,
                    state="idle",
                    pid=4001,
                    cwd="/tmp/work",
                    title="CoreAgent 主控",
                    touched_at=1_700_000_000.0,
                ),
                coreagent_runner.LiveSessionSnapshot(
                    session_id=core_child,
                    state="idle",
                    pid=4002,
                    cwd="/tmp/work",
                    title="CoreAgent 派发子会话",
                    touched_at=1_700_000_000.0,
                ),
            ],
        )

        resp = client.get(f"/api/workbench/sessions/{core_parent}/children")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"]["host_alive"] is False
        assert body["summary"]["running_children"] == 0
        assert body["summary"]["has_running"] is False
        assert body["child_sessions"][0]["status"] == "done"
        assert body["child_sessions"][0]["is_running"] is False
