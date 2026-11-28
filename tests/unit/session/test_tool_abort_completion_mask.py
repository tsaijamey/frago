"""Wave A · Top5 方案 5A 回归单元测试：工具调用异常中止不被 completed 掩盖 & awaiting_input 永不洗白。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.session.coreagent_store import inspect_session_file
from frago.session.models import SessionStatus
from frago.session.record_reader import SessionCard
from frago.session.service import (
    SessionOntologyService,
    evaluate_session_liveness_and_state,
)
from frago.session.store import SessionOntologyRecord, SessionOntologyStore


def _write_coreagent_jsonl(path: Path, events: list[dict], *, mtime_offset_sec: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    if mtime_offset_sec:
        ts = time.time() - mtime_offset_sec
        os.utime(path, (ts, ts))


def _make_onto_rec(
    session_id: str,
    *,
    lifecycle_state: str,
    updated_at: float,
    summary: str = "",
    turn_seq: int = 1,
) -> SessionOntologyRecord:
    return SessionOntologyRecord(
        session_id=session_id,
        agent_kernel="claude",
        lifecycle_state=lifecycle_state,
        origin="terminal",
        created_at=int(updated_at - 60.0),
        updated_at=int(updated_at),
        summary=summary,
        turn_seq=turn_seq,
    )


def _backdate_store_record(store_path: Path, session_id: str, updated_at: int) -> None:
    data = json.loads(store_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
        data["sessions"][session_id]["updated_at"] = updated_at
    elif isinstance(data, dict) and session_id in data:
        data[session_id]["updated_at"] = updated_at
    store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TestCoreAgentInspectToolAbort:
    """CoreAgent transcript 末事件状态判定边界。"""

    @pytest.mark.parametrize(
        "tail_event,expected_kind",
        [
            (
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "pytest"}}
                        ],
                    },
                },
                "assistant_tool",
            ),
            (
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "thinking", "thinking": "analyzing migration plan"}],
                    },
                },
                "assistant_think",
            ),
            (
                {
                    "type": "user",
                    "message": {"role": "user", "content": "run migration now"},
                },
                "user",
            ),
        ],
    )
    def test_in_progress_event_beyond_90s_marks_error_not_completed(
        self, tmp_path: Path, tail_event: dict, expected_kind: str
    ) -> None:
        jsonl = tmp_path / "sess_abort.jsonl"
        _write_coreagent_jsonl(
            jsonl,
            [
                {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "start"}},
                tail_event,
            ],
            mtime_offset_sec=180.0,
        )
        info = inspect_session_file(jsonl)
        assert info is not None
        assert info.last_event_kind == expected_kind
        assert info.status == SessionStatus.ERROR

    def test_assistant_tool_within_90s_stays_running(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "sess_live.jsonl"
        _write_coreagent_jsonl(
            jsonl,
            [
                {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "long build"}},
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {"command": "make"}}],
                    },
                },
            ],
            mtime_offset_sec=10.0,
        )
        info = inspect_session_file(jsonl)
        assert info is not None
        assert info.last_event_kind == "assistant_tool"
        assert info.status == SessionStatus.RUNNING

    @pytest.mark.parametrize(
        "tail_event,expected_kind",
        [
            ({"type": "system", "subtype": "turn_duration", "durationMs": 4200}, "turn_end"),
            (
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "all green"}]},
                },
                "assistant_text",
            ),
        ],
    )
    def test_settled_event_beyond_90s_marks_completed(
        self, tmp_path: Path, tail_event: dict, expected_kind: str
    ) -> None:
        jsonl = tmp_path / "sess_done.jsonl"
        _write_coreagent_jsonl(
            jsonl,
            [
                {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "check status"}},
                tail_event,
            ],
            mtime_offset_sec=240.0,
        )
        info = inspect_session_file(jsonl)
        assert info is not None
        assert info.last_event_kind == expected_kind
        assert info.status == SessionStatus.COMPLETED

    def test_in_progress_event_beyond_90s_stays_running_when_is_alive_true(
        self, tmp_path: Path
    ) -> None:
        jsonl = tmp_path / "sess_long_live_tool.jsonl"
        _write_coreagent_jsonl(
            jsonl,
            [
                {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "long build"}},
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "tu_live", "name": "Bash", "input": {"command": "sleep 600"}}],
                    },
                },
            ],
            mtime_offset_sec=420.0,
        )
        live_info = inspect_session_file(jsonl, is_alive=True)
        assert live_info is not None
        assert live_info.last_event_kind == "assistant_tool"
        assert live_info.status == SessionStatus.RUNNING
        assert live_info.ended_at is None
        assert live_info.has_transcript_error is False

    def test_in_progress_event_within_90s_marks_error_when_is_alive_false(
        self, tmp_path: Path
    ) -> None:
        jsonl = tmp_path / "sess_dead_fast.jsonl"
        _write_coreagent_jsonl(
            jsonl,
            [
                {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "run"}},
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "tu_dead", "name": "Bash", "input": {"command": "exit 1"}}],
                    },
                },
            ],
            mtime_offset_sec=15.0,
        )
        dead_info = inspect_session_file(jsonl, is_alive=False)
        assert dead_info is not None
        assert dead_info.last_event_kind == "assistant_tool"
        assert dead_info.status == SessionStatus.ERROR
        assert dead_info.has_transcript_error is False

    def test_real_transcript_error_stays_error_even_when_is_alive_true(
        self, tmp_path: Path
    ) -> None:
        jsonl = tmp_path / "sess_real_err.jsonl"
        _write_coreagent_jsonl(
            jsonl,
            [
                {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "ask"}},
                {"type": "system", "subtype": "api_error", "level": "error", "content": "502 bad gateway"},
            ],
            mtime_offset_sec=10.0,
        )
        err_info = inspect_session_file(jsonl, is_alive=True)
        assert err_info is not None
        assert err_info.last_event_kind == "error"
        assert err_info.status == SessionStatus.ERROR
        assert err_info.has_transcript_error is True


class TestEvaluateSessionLivenessAndState:
    """`evaluate_session_liveness_and_state()` 正反边界与存量纠偏。"""

    def test_dead_process_stopped_at_tool_call_marks_error_and_tool_aborted(self) -> None:
        now = time.time()
        onto = _make_onto_rec("sess-abort-1", lifecycle_state="running", updated_at=now - 600.0)
        ev = evaluate_session_liveness_and_state(
            session_id="sess-abort-1",
            onto_rec=onto,
            card_status="idle",
            last_kind="tool.call",
            last_active_s=now - 600.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "error"
        assert ev.ui_status == "error"
        assert ev.tool_aborted is True
        assert ev.heal_target == "error"
        assert ev.heal_summary == "process_terminated_mid_turn"

    def test_zombie_6h_with_tool_call_collapses_to_error_not_completed(self) -> None:
        now = time.time()
        onto = _make_onto_rec("sess-zombie-tool", lifecycle_state="running", updated_at=now - 7 * 3600.0)
        ev = evaluate_session_liveness_and_state(
            session_id="sess-zombie-tool",
            onto_rec=onto,
            card_status="running",
            last_kind="tool.call",
            last_active_s=now - 7 * 3600.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "error"
        assert ev.ui_status == "error"
        assert ev.tool_aborted is True
        assert ev.heal_target == "error"
        assert ev.heal_summary == "process_terminated_mid_turn"

    def test_long_running_live_tool_process_is_not_false_aborted(self) -> None:
        now = time.time()
        onto = _make_onto_rec("sess-live-tool", lifecycle_state="running", updated_at=now - 180.0)
        ev = evaluate_session_liveness_and_state(
            session_id="sess-live-tool",
            onto_rec=onto,
            card_status="running",
            last_kind="tool.call",
            last_active_s=now - 180.0,
            in_tmux=True,
            liveness_flag=True,
            now_s=now,
        )
        assert ev.lifecycle_state == "running"
        assert ev.ui_status == "running"
        assert ev.tool_aborted is False
        assert ev.heal_target is None

    def test_legacy_false_completed_with_dangling_tool_call_self_heals_to_error(self) -> None:
        now = time.time()
        onto = _make_onto_rec("sess-legacy-masked", lifecycle_state="completed", updated_at=now - 400.0)
        ev = evaluate_session_liveness_and_state(
            session_id="sess-legacy-masked",
            onto_rec=onto,
            card_status="done",
            last_kind="assistant_tool",
            last_active_s=now - 500.0,
            last_reply_s=now - 560.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "error"
        assert ev.ui_status == "error"
        assert ev.tool_aborted is True
        assert ev.heal_target == "error"
        assert ev.heal_summary == "process_terminated_mid_turn"

    def test_normal_completed_with_agent_say_is_not_misclassified(self) -> None:
        now = time.time()
        onto = _make_onto_rec("sess-normal-done", lifecycle_state="completed", updated_at=now - 1200.0)
        ev = evaluate_session_liveness_and_state(
            session_id="sess-normal-done",
            onto_rec=onto,
            card_status="done",
            last_kind="agent.say",
            last_active_s=now - 1200.0,
            last_reply_s=now - 1200.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "completed"
        assert ev.ui_status == "done"
        assert ev.tool_aborted is False
        assert ev.heal_target is None

    def test_cancelled_session_is_never_overwritten(self) -> None:
        now = time.time()
        onto = _make_onto_rec("sess-cancelled", lifecycle_state="cancelled", updated_at=now - 800.0)
        ev = evaluate_session_liveness_and_state(
            session_id="sess-cancelled",
            onto_rec=onto,
            card_status="idle",
            last_kind="tool.call",
            last_active_s=now - 800.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "cancelled"
        assert ev.ui_status == "idle"
        assert ev.tool_aborted is False
        assert ev.heal_target is None

    @pytest.mark.parametrize(
        "card_status,last_kind,expected_ui",
        [
            ("error", "assistant_tool", "idle"),
            ("error", "tool.call", "idle"),
            ("error", "error", "idle"),
            ("error", "agent.say", "done"),
            ("running", "assistant_tool", "idle"),
        ],
    )
    def test_cancelled_session_protected_from_error_card_and_transcript_signals(
        self, card_status: str, last_kind: str, expected_ui: str
    ) -> None:
        """D1: 人工 cancelled 终态面对 card_status='error' / last_kind='error' 绝不被篡改或触发自愈写库。"""
        now = time.time()
        onto = _make_onto_rec(
            "sess-cancelled-d1",
            lifecycle_state="cancelled",
            updated_at=now - 500.0,
            summary="user_cancelled",
        )
        ev = evaluate_session_liveness_and_state(
            session_id="sess-cancelled-d1",
            onto_rec=onto,
            card_status=card_status,
            last_kind=last_kind,
            last_active_s=now - 500.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "cancelled"
        assert ev.ui_status == expected_ui
        assert ev.tool_aborted is False
        assert ev.heal_target is None
        assert ev.heal_summary is None

    def test_awaiting_input_protected_from_heuristic_error_card_without_transcript_error(
        self,
    ) -> None:
        now = time.time()
        onto = _make_onto_rec(
            "sess-await-heuristic",
            lifecycle_state="awaiting_input",
            updated_at=now - 600.0,
        )
        ev = evaluate_session_liveness_and_state(
            session_id="sess-await-heuristic",
            onto_rec=onto,
            card_status="error",
            last_kind="assistant_tool",
            last_active_s=now - 600.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "awaiting_input"
        assert ev.tool_aborted is False
        assert ev.heal_target is None

    def test_awaiting_input_never_washed_to_completed_even_after_7_days(self) -> None:
        now = time.time()
        onto = _make_onto_rec(
            "sess-wait-7d", lifecycle_state="awaiting_input", updated_at=now - 7 * 86400.0
        )
        ev = evaluate_session_liveness_and_state(
            session_id="sess-wait-7d",
            onto_rec=onto,
            card_status="done",
            last_kind="agent.say",
            last_active_s=now - 7 * 86400.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "awaiting_input"
        assert ev.tool_aborted is False
        assert ev.heal_target is None

    def test_previously_washed_awaiting_input_safely_recovers(self) -> None:
        now = time.time()
        onto = _make_onto_rec(
            "sess-wait-recover", lifecycle_state="completed", updated_at=now - 8 * 3600.0
        )
        ev = evaluate_session_liveness_and_state(
            session_id="sess-wait-recover",
            onto_rec=onto,
            card_status="awaiting_input",
            last_kind="agent.say",
            last_active_s=now - 8 * 3600.0,
            last_reply_s=now - 8 * 3600.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "awaiting_input"
        assert ev.tool_aborted is False
        assert ev.heal_target == "awaiting_input"

    def test_unmanaged_dead_session_at_tool_call_marks_tool_aborted(self) -> None:
        now = time.time()
        ev = evaluate_session_liveness_and_state(
            session_id="sess-unmanaged-tool",
            onto_rec=None,
            card_status="idle",
            last_kind="tool.call",
            last_active_s=now - 900.0,
            in_tmux=False,
            liveness_flag=False,
            now_s=now,
        )
        assert ev.lifecycle_state == "error"
        assert ev.ui_status == "error"
        assert ev.tool_aborted is True


class TestReconcileAndWorkbenchApi:
    """`reconcile_session_lifecycle` 与 `/api/workbench/sessions` 透出校验。"""

    def test_reconcile_preserves_awaiting_input_beyond_6h(self, tmp_path: Path) -> None:
        store = SessionOntologyStore(
            tmp_path / "session-ontology-store.json",
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store=store)
        svc.launch_agent_session(
            session_id="sess-wait-keep",
            agent_kernel_id="claude",
            origin="web",
            initial_prompt="need decision",
            cwd=str(tmp_path),
        )
        svc.yield_awaiting_input(session_id="sess-wait-keep", waiting_reason="awaiting approval")
        # 回拨 updated_at 到 10 小时前，模拟长时等待
        store_path = tmp_path / "session-ontology-store.json"
        old_ts = int(time.time() - 10 * 3600.0)
        _backdate_store_record(store_path, "sess-wait-keep", old_ts)

        result = svc.reconcile_session_lifecycle(
            session_id="sess-wait-keep",
            is_alive=False,
            last_activity_ts=old_ts,
        )
        assert result is not None
        assert result.lifecycle_state == "awaiting_input"
        after = svc.get_session("sess-wait-keep")
        assert after is not None
        assert after.lifecycle_state == "awaiting_input"

    def test_workbench_collect_rows_exposes_tool_aborted_and_awaiting_input(
        self, tmp_path: Path
    ) -> None:
        from frago.server.routes import workbench as wb_route
        from frago.server.services import tmux_sessions_service as tsvc
        from frago.session import service as sess_service

        store_path = tmp_path / "session-ontology-store.json"
        store = SessionOntologyStore(
            store_path,
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store=store)
        now = time.time()
        now_ms = int(now * 1000)

        # 会话 1：运行中断于 tool.call，进程离线超过 300s → error + tool_aborted=True
        store.save(
            _make_onto_rec("sess-api-abort", lifecycle_state="running", updated_at=now - 600.0)
        )
        _backdate_store_record(store_path, "sess-api-abort", int(now - 600.0))
        # 会话 2：等待输入超过 7 天 → 仍保持 awaiting_input + tool_aborted=False
        store.save(
            _make_onto_rec("sess-api-wait", lifecycle_state="awaiting_input", updated_at=now - 7 * 86400.0)
        )
        _backdate_store_record(store_path, "sess-api-wait", int(now - 7 * 86400.0))

        abort_card = SessionCard(
            session_id="sess-api-abort",
            family="claude",
            title="Abort mid-tool",
            directory="/tmp/demo",
            created_at=now_ms - 600_000,
            last_active_at=now_ms - 500_000,
            last_reply_at=now_ms - 550_000,
            agent_paths=[],
            status="idle",
            digest_done=None,
            digest_stuck=None,
            last_kind="tool.call",
            lifecycle_state="running",
        )
        wait_card = SessionCard(
            session_id="sess-api-wait",
            family="claude",
            title="Need human input",
            directory="/tmp/demo",
            created_at=now_ms - 7 * 86400_000,
            last_active_at=now_ms - 7 * 86400_000,
            last_reply_at=now_ms - 7 * 86400_000,
            agent_paths=[],
            status="done",
            digest_done="Please confirm option A or B",
            digest_stuck=None,
            last_kind="agent.say",
            lifecycle_state="awaiting_input",
        )

        with (
            patch.object(tsvc, "open_session_names", return_value=set()),
            patch.object(wb_route.coreagent_runner, "live_states", return_value={}),
            patch.object(wb_route.record_reader, "list_sessions", return_value=[abort_card, wait_card]),
            patch.object(sess_service, "get_default_session_service", return_value=svc),
            patch.object(wb_route.workbench_titles, "load", return_value={}),
            patch.object(wb_route.workbench_groups, "local_ops_session_ids", return_value=set()),
            patch.object(wb_route, "list_posts", return_value=[]),
            patch.object(wb_route, "_observer_slots_state", return_value=(False, False)),
            patch.object(wb_route, "_dispatch_states_by_caller", return_value=(set(), set())),
            patch.object(wb_route, "_keep_watching_only"),
        ):
            rows = asyncio.run(wb_route.collect_workbench_session_rows())

        by_id = {row["session_id"]: row for row in rows}
        assert by_id["sess-api-abort"]["lifecycle_state"] == "error"
        assert by_id["sess-api-abort"]["status"] == "error"
        assert by_id["sess-api-abort"]["tool_aborted"] is True
        assert by_id["sess-api-abort"]["abort_reason"] == "process_terminated_mid_turn"
        assert by_id["sess-api-abort"]["last_kind"] == "tool.call"

        assert by_id["sess-api-wait"]["lifecycle_state"] == "awaiting_input"
        assert by_id["sess-api-wait"]["tool_aborted"] is False
        assert by_id["sess-api-wait"]["abort_reason"] is None
        assert by_id["sess-api-wait"]["last_kind"] == "agent.say"


class TestCliSessionShowLifecycleMapping:
    """CLI `frago session show` 生命周期映射不折叠 awaiting_input 与 error。"""

    def test_show_maps_awaiting_input_and_error_explicitly(self) -> None:
        from frago.cli import session_commands as sc

        now_ms = int(time.time() * 1000)
        for lc, expected in [
            ("error", SessionStatus.ERROR),
            ("awaiting_input", SessionStatus.AWAITING_INPUT),
            ("running", SessionStatus.RUNNING),
            ("queued", SessionStatus.QUEUED),
            ("cancelled", SessionStatus.CANCELLED),
            ("completed", SessionStatus.COMPLETED),
        ]:
            card = SessionCard(
                session_id=f"sess-cli-{lc}",
                family="claude",
                title=f"CLI {lc}",
                directory="/tmp/demo",
                created_at=now_ms - 10_000,
                last_active_at=now_ms - 5_000,
                last_reply_at=now_ms - 5_000,
                agent_paths=[],
                status="idle",
                digest_done=None,
                digest_stuck=None,
                lifecycle_state=lc,
            )
            with (
                patch("frago.session.record_reader.list_sessions", return_value=[card]),
                patch("frago.session.record_reader.read_records", return_value=[]),
            ):
                loaded = sc._resolve_session_via_record_reader(f"sess-cli-{lc}")
            assert loaded is not None
            session_obj = loaded[0]
            assert session_obj.status == expected

    def test_show_prioritizes_cancelled_ontology_lifecycle_over_error_card_status(self) -> None:
        """D1: 即使底层卡片 status='error'，只要本体 lifecycle_state='cancelled'，CLI 必须映射为 CANCELLED。"""
        from frago.cli import session_commands as sc

        now_ms = int(time.time() * 1000)
        card = SessionCard(
            session_id="core_f4_cancelled_cli",
            family="coreagent",
            title="Cancelled mid-tool",
            directory="/tmp/demo",
            created_at=now_ms - 300_000,
            last_active_at=now_ms - 240_000,
            last_reply_at=None,
            agent_paths=[],
            status="error",
            digest_done=None,
            digest_stuck=None,
            last_kind="tool.call",
            lifecycle_state="cancelled",
        )
        with (
            patch("frago.session.record_reader.list_sessions", return_value=[card]),
            patch("frago.session.record_reader.read_records", return_value=[]),
        ):
            loaded = sc._resolve_session_via_record_reader("core_f4_cancelled_cli")
        assert loaded is not None
        assert loaded[0].status == SessionStatus.CANCELLED


class TestCancelledEndToEndReadPathProtection:
    """D1 端到端防回归：cancelled 终态经 inspect/storage/list/show/batch_reconcile 后存储零污染。"""

    def test_cancelled_coreagent_session_survives_storage_list_show_and_record_reader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.session import coreagent_store, record_reader, storage
        from frago.session import service as sess_service
        from frago.session.models import AgentType

        sid = "core_f4_cancelled_not_overwritten"
        # 1. 真实搭建持久化本体存储：人工 cancelled 终态
        store_path = tmp_path / "session-ontology-store.json"
        store = SessionOntologyStore(
            store_path,
            legacy_ledger_path=tmp_path / "agent-launches.json",
        )
        svc = SessionOntologyService(store=store)
        now = time.time()
        store.save(
            _make_onto_rec(
                sid,
                lifecycle_state="cancelled",
                updated_at=now - 300.0,
                summary="user_cancelled",
            )
        )
        _backdate_store_record(store_path, sid, int(now - 300.0))

        # 2. 真实搭建 CoreAgent 原生转录与 session storage 镜像（末帧 tool_use 且静默 300s > 90s）
        events = [
            {"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "run long task"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu_f4", "name": "Bash", "input": {"command": "sleep 999"}}],
                },
            },
        ]
        core_root = tmp_path / "coreagent_sessions"
        native_jsonl = core_root / "-tmp-demo" / f"{sid}.jsonl"
        _write_coreagent_jsonl(native_jsonl, events, mtime_offset_sec=300.0)

        sessions_base = tmp_path / "frago_sessions"
        mirror_jsonl = sessions_base / "coreagent" / sid / "raw.jsonl"
        _write_coreagent_jsonl(mirror_jsonl, events, mtime_offset_sec=300.0)

        # 验证前置条件：无 is_alive 参数直接 inspect 会判定为 ERROR（正是触发 F4 缺陷的诱因）
        raw_stats = coreagent_store.inspect_session_file(mirror_jsonl)
        assert raw_stats is not None
        assert raw_stats.last_event_kind == "assistant_tool"
        assert raw_stats.status == SessionStatus.ERROR

        monkeypatch.setattr(storage, "get_session_base_dir", lambda: sessions_base)
        monkeypatch.setattr(storage, "_live_tmux_session_ids", lambda: set())
        monkeypatch.setattr(storage, "_live_coreagent_states", lambda: {})
        monkeypatch.setattr(coreagent_store, "sessions_root", lambda: core_root)
        monkeypatch.setattr(sess_service, "get_default_session_service", lambda: svc)
        monkeypatch.setattr(sess_service, "can_write_ontology_store", lambda _s: True)
        monkeypatch.setattr(record_reader, "_claude_cards", lambda *a, **k: [])
        monkeypatch.setattr(record_reader, "_opencode_cards", lambda *a, **k: [])
        monkeypatch.setattr(record_reader, "_codex_cards", lambda *a, **k: [])
        monkeypatch.setattr(record_reader, "_agy_cards", lambda *a, **k: [])

        # 3. 依次走 storage.find_session_by_prefix / storage.list_sessions / record_reader.list_sessions
        found = storage.find_session_by_prefix(sid, AgentType.COREAGENT)
        assert found is not None
        assert found.status == SessionStatus.CANCELLED

        listed = storage.list_sessions(agent_type=AgentType.COREAGENT, limit=20)
        assert any(s.session_id == sid and s.status == SessionStatus.CANCELLED for s in listed)

        cards = record_reader.list_sessions()
        matched_cards = [c for c in cards if c.session_id == sid]
        assert len(matched_cards) == 1
        assert matched_cards[0].lifecycle_state == "cancelled"
        assert matched_cards[0].status != "error"

        # 4. Click CLI 端到端：frago session show / list 必须展示 Cancelled 而非 Error
        from click.testing import CliRunner

        from frago.cli.session_commands import session_group

        runner = CliRunner()
        show_res = runner.invoke(session_group, ["show", sid, "--agent-type", "coreagent"])
        assert show_res.exit_code == 0, show_res.output
        assert "Cancelled" in show_res.output
        assert "Status: Error" not in show_res.output

        list_res = runner.invoke(session_group, ["list", "--agent-type", "coreagent"])
        assert list_res.exit_code == 0, list_res.output
        assert "Cancelled" in list_res.output

        # 5. 纵深守卫：reconcile_session_lifecycle 与 batch_reconcile_states 均不得覆写 cancelled
        reconciled = svc.reconcile_session_lifecycle(
            session_id=sid,
            is_alive=False,
            observed_error="process_terminated_mid_turn",
            observed_terminal_state="error",
        )
        assert reconciled is not None
        assert reconciled.lifecycle_state == "cancelled"

        changed = store.batch_reconcile_states([(sid, "error", "process_terminated_mid_turn")])
        assert changed == 0

        # 6. 落盘回读持久化本体存储：cancelled 与原 summary 毫发无损
        disk_data = json.loads(store_path.read_text(encoding="utf-8"))
        disk_rec = disk_data["sessions"][sid]
        assert disk_rec["lifecycle_state"] == "cancelled"
        assert disk_rec["summary"] == "user_cancelled"
