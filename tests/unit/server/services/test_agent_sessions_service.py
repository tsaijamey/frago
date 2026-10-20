"""合并清单的判据。

锁住的是两件产品语义：这个入口管的是全部 agent 会话进程，不是 tmux 会话列表；
CoreAgent 没有 tmux 名字，但它照样是清单里的一行，也照样算进左下角那个数字。
"""

import time
from unittest.mock import patch

from frago.server.services import agent_sessions_service as svc
from frago.server.services.coreagent_runner import LiveSessionSnapshot
from frago.server.services.tmux_sessions_service import TmuxSessionInfo
from frago.session.record_reader import SessionCard

SID = "core_0123456789abcdef0123456789abcdef"


def _tmux_row(**over):
    base = {
        "name": "frago-agent-tmux-1",
        "label": "tmux-1",
        "session_id": "sid-tmux-1",
        "stop_reason": "end_turn",
        "last_stop_at": "2026-10-19T00:00:00+00:00",
        "idle_secs": 7200.0,
        "excerpt": "tmux 行",
        "memory_mb": 100,
        "busy": False,
        "managed": False,
    }
    base.update(over)
    return TmuxSessionInfo(**base)


def _core_card(**over):
    base = {
        "session_id": SID,
        "family": "coreagent",
        "title": "CoreAgent 那一场",
        "directory": "/Users/frago/Repos/frago",
        "created_at": 0,
        "last_active_at": 0,
        "digest_done": "把这件事做完了",
    }
    base.update(over)
    return SessionCard(**base)


def _snap(**over):
    base = {
        "session_id": SID,
        "state": "idle",
        "pid": 4242,
        "cwd": "/Users/frago/Repos/frago",
        "title": None,
        "touched_at": time.time() - 60,
    }
    base.update(over)
    return LiveSessionSnapshot(**base)


class TestMergedList:
    def test_a_live_coreagent_process_is_a_row_of_its_own(self):
        with (
            patch.object(svc.tsvc, "list_sessions", return_value=[_tmux_row()]),
            patch.object(svc.coreagent_runner, "live_snapshot", return_value=[_snap()]),
            patch.object(svc.record_reader, "list_sessions", return_value=[_core_card()]),
            patch.object(svc.tsvc, "memory_by_pid", return_value={4242: 320}),
        ):
            rows = svc.list_sessions()

        assert {r["kind"] for r in rows} == {"tmux", "coreagent"}
        core = next(r for r in rows if r["kind"] == "coreagent")
        assert core["name"] == SID
        assert core["session_id"] == SID
        assert core["label"] == "CoreAgent 那一场"
        assert core["excerpt"] == "把这件事做完了"
        assert core["memory_mb"] == 320
        assert core["busy"] is False
        assert core["awaiting_input"] is True
        assert core["directory"] == "/Users/frago/Repos/frago"

    def test_a_busy_coreagent_process_is_marked_busy(self):
        with (
            patch.object(svc.tsvc, "list_sessions", return_value=[]),
            patch.object(svc.coreagent_runner, "live_snapshot", return_value=[_snap(state="busy")]),
            patch.object(svc.record_reader, "list_sessions", return_value=[_core_card()]),
            patch.object(svc.tsvc, "memory_by_pid", return_value={}),
        ):
            (row,) = svc.list_sessions()

        assert row["busy"] is True
        assert row["awaiting_input"] is False

    def test_a_session_without_a_record_yet_still_shows_up(self):
        # 刚起、索引还没写上这一场时，不能让它从清单里消失。
        with (
            patch.object(svc.tsvc, "list_sessions", return_value=[]),
            patch.object(
                svc.coreagent_runner,
                "live_snapshot",
                return_value=[_snap(title="命令行起的名字")],
            ),
            patch.object(svc.record_reader, "list_sessions", return_value=[]),
            patch.object(svc.tsvc, "memory_by_pid", return_value={}),
        ):
            (row,) = svc.list_sessions()

        assert row["label"] == "命令行起的名字"
        assert row["memory_mb"] == 0

    def test_rows_stay_sorted_by_idle_desc(self):
        with (
            patch.object(svc.tsvc, "list_sessions", return_value=[_tmux_row(idle_secs=7200.0)]),
            patch.object(
                svc.coreagent_runner,
                "live_snapshot",
                return_value=[_snap(touched_at=time.time() - 60)],
            ),
            patch.object(svc.record_reader, "list_sessions", return_value=[_core_card()]),
            patch.object(svc.tsvc, "memory_by_pid", return_value={}),
        ):
            rows = svc.list_sessions()

        assert [r["kind"] for r in rows] == ["tmux", "coreagent"]


class TestCount:
    def test_the_rail_number_includes_coreagent_processes(self):
        with (
            patch.object(svc.tsvc, "count_sessions", return_value={"total": 2, "total_memory_mb": 500}),
            patch.object(
                svc.coreagent_runner,
                "live_snapshot",
                return_value=[_snap(pid=1), _snap(session_id="core_b", pid=2)],
            ),
            patch.object(svc.tsvc, "memory_by_pid", return_value={1: 300, 2: 200}),
        ):
            assert svc.count_sessions() == {"total": 4, "total_memory_mb": 1000}

    def test_no_coreagent_processes_leaves_the_tmux_count_alone(self):
        with (
            patch.object(svc.tsvc, "count_sessions", return_value={"total": 2, "total_memory_mb": 500}),
            patch.object(svc.coreagent_runner, "live_snapshot", return_value=[]),
        ):
            assert svc.count_sessions() == {"total": 2, "total_memory_mb": 500}
