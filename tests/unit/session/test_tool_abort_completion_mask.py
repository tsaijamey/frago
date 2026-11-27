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
