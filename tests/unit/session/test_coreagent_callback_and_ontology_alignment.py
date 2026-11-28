"""回归测试：CoreAgent 跨进程异步回传链路修复 & Agent Ontology 全量内核矩阵对齐。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from frago.agent_driver.driver import runs_on_kernel
from frago.init import profile_targets
from frago.ontology import (
    AGENT_CAPABILITY_MATRIX,
    OntologyIntrospector,
    get_agent_capability_level,
    get_agent_kernel_metadata,
    list_agent_kernels,
    runs_in_tmux,
    supports_for_you,
    supports_profile_binding,
)
from frago.server.services import (
    coreagent_runner,
    session_observer,
    session_send,
    tmux_sessions_service,
    workbench_queue,
)
from frago.session import async_dispatch, record_reader, usage_tick
from frago.session.adapters.kernel_adapters import (
    CodexSessionAdapter,
    OpencodeSessionAdapter,
    TurnCompletionVerdict,
)
from frago.session.models import ACTIVE_AGENT_TYPES, RESERVED_AGENT_TYPES, AgentType
from frago.session.opencode_stream import OpencodeStream
from frago.session.unified_record import UnifiedRecord


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workbench_queue.reset_runtime_state()
    workbench_queue.mark_server_process(False)
    monkeypatch.setattr(workbench_queue, "_sender_override", None)
    monkeypatch.setattr(
        session_observer,
        "session_dir",
        lambda sid, family: tmp_path / "sessions" / family / sid,
    )
    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(tmp_path / "panes"))
    with coreagent_runner._sessions_lock:
        coreagent_runner._sessions.clear()
    yield tmp_path
    workbench_queue.reset_runtime_state()
    workbench_queue.mark_server_process(False)
    with coreagent_runner._sessions_lock:
        coreagent_runner._sessions.clear()


class TestCoreAgentCallbackChainFix:
    """事项 1：CoreAgent 跨进程异步回传断链与 handed 假送达门禁测试。"""

    def test_workbench_queue_rejects_handed_without_landed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: [])
        monkeypatch.setattr(session_send, "send_when_idle", lambda *_a, **_k: "handed")
        assert workbench_queue._send_prompt("core_test123", "hello", "/tmp") is False

        monkeypatch.setattr(session_send, "send_when_idle", lambda *_a, **_k: "not_now")
        assert workbench_queue._send_prompt("core_test123", "hello", "/tmp") is False

        monkeypatch.setattr(session_send, "send_when_idle", lambda *_a, **_k: "landed")
        assert workbench_queue._send_prompt("core_test123", "hello", "/tmp") is True

    def test_send_when_idle_waits_for_landed_on_coreagent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = "core_landedcheck0001"
        monkeypatch.setattr(
            session_send,
            "resolve_target",
            lambda _sid, **_k: session_send.SendTarget(
                session_id=sid,
                family="coreagent",
                agent_type="coreagent",
                cwd="/tmp",
                is_new=False,
            ),
        )
        monkeypatch.setattr(coreagent_runner, "busy", lambda _sid: False)
        monkeypatch.setattr(coreagent_runner, "has_external_live_session", lambda _sid: False)
        queued_calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            coreagent_runner,
            "send_queued",
            lambda s, p, **_k: queued_calls.append((s, p)) or "feeder",
        )
        monkeypatch.setattr(coreagent_runner, "running", lambda _sid: True)

        checks = {"n": 0}
        now = {"t": 0.0}

        def fake_clock() -> float:
            return now["t"]

        def fake_sleep(dt: float) -> None:
            now["t"] += dt

        def landed_on_third() -> bool:
            checks["n"] += 1
            return checks["n"] >= 3

        verdict = session_send.send_when_idle(
            sid,
            "<frago-async-callback job_id=\"disp-1\">ok</frago-async-callback>",
            landed=landed_on_third,
            confirm_s=5.0,
            poll_s=0.1,
            sleep=fake_sleep,
            clock=fake_clock,
        )
        assert verdict == "landed"
        assert len(queued_calls) == 1

        # 若始终未落盘，超时必须返回 not_now，绝不返回 handed
        now["t"] = 0.0
        verdict_timeout = session_send.send_when_idle(
            sid,
            "never lands",
            landed=lambda: False,
            confirm_s=1.0,
            poll_s=0.25,
            sleep=fake_sleep,
            clock=fake_clock,
        )
        assert verdict_timeout == "not_now"

    def test_send_when_idle_and_enqueue_refuse_killing_external_live_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = "core_externalowned01"
        workbench_queue.mark_server_process(False)
        monkeypatch.setattr(
            session_send,
            "resolve_target",
            lambda _sid, **_k: session_send.SendTarget(
                session_id=sid,
                family="coreagent",
                agent_type="coreagent",
                cwd="/tmp",
                is_new=False,
            ),
        )
        monkeypatch.setattr(coreagent_runner, "busy", lambda _sid: False)
        monkeypatch.setattr(coreagent_runner, "has_external_live_session", lambda _sid: True)

        # send_when_idle 在非服务端进程里见到外部托管活会话，必须返回 not_now
        verdict = session_send.send_when_idle(sid, "hi", landed=lambda: False)
        assert verdict == "not_now"

        # 直接调 coreagent_runner.send_queued 也必须被护栏拦住，绝不新起 TmuxCoreProcess 杀旧会话
        with pytest.raises(coreagent_runner.CoreAgentBusy):
            coreagent_runner.send_queued(sid, "hi", cwd="/tmp")

    def test_deliver_callback_delegates_to_running_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = "core_serverdeleg0001"
        job_id = "disp-deleg-01"
        monkeypatch.setattr(async_dispatch, "frago_home", lambda: tmp_path)
        monkeypatch.setattr(record_reader, "detect_family", lambda _s: "coreagent")
        monkeypatch.setattr(async_dispatch, "_local_server_wakeup_port", lambda: 8093)

        job = async_dispatch.AsyncDispatchJob(
            job_id=job_id,
            kind="worker",
            mode="new",
            caller_session_id=sid,
            caller_employee_id=None,
            caller_cwd="/tmp",
            target_session_id="worker-deleg-01",
            target_name="worker-deleg",
            employee_id=None,
            agent="claude",
            cwd="/tmp",
            prompt="do work",
            task_summary="work",
            status="delivering",
            delivery_state="queued",
        )
        async_dispatch.save_dispatch_job(job)

        poked: list[tuple[int, str]] = []

        def fake_poke(port: int, target_sid: str):
            poked.append((port, target_sid))
            claimed = async_dispatch.claim_ready_callbacks_for_session(
                target_sid, delivery_channel="idle_batch", debounce_ms=0
            )
            async_dispatch.finalize_claimed_callbacks(target_sid, claimed, success=True)
            return {"delivered": True, "claimed": len(claimed), "job_ids": [job_id]}

        monkeypatch.setattr(async_dispatch, "_poke_server_callback_drain", fake_poke)
        # 确保短命 watcher 子进程绝不会在本地直接触发 coreagent_runner.send_queued
        monkeypatch.setattr(
            coreagent_runner,
            "send_queued",
            lambda *_a, **_k: pytest.fail("watcher 不应直接在子进程内调用 send_queued"),
        )

        ok = async_dispatch.deliver_callback_to_session(
            sid,
            f'<frago-async-callback job_id="{job_id}">done</frago-async-callback>',
            job_id=job_id,
        )
        assert ok is True
        assert poked == [(8093, sid)]
        # Option A 物理分轨：workbench_queue (Next Task 人类队列) 保持绝对纯净为空
        assert workbench_queue.list_queue(sid) == []
        reloaded = async_dispatch.load_dispatch_job(job_id)
        assert reloaded is not None
        assert reloaded.delivery_state == "delivered"


class TestAgentOntologyAlignment:
    """事项 2 & 3：AgentKernel 本体矩阵与跨内核功能缺口对齐回归测试。"""

    def test_schema_integrity_and_kernel_metadata_consistency(self) -> None:
        assert OntologyIntrospector().validate_schema_integrity() == []
        assert set(list_agent_kernels()) == {"claude", "agy", "opencode", "codex", "coreagent"}
        assert set(AGENT_CAPABILITY_MATRIX.keys()) == {
            "claude",
            "agy",
            "opencode",
            "codex",
            "coreagent",
        }

        core = get_agent_kernel_metadata("coreagent")
        assert core["execution_mode"] == "tmux_kernel_host"
        assert core["runs_in_tmux"] is True
        assert core["supports_resume"] is True
        assert core["supports_branch"] is True
        assert core["supports_for_you"] is True
        assert runs_in_tmux("coreagent") is True
        assert runs_on_kernel("coreagent") is True
        assert supports_profile_binding("coreagent") is True
        assert supports_for_you("coreagent") is True

        for k in list_agent_kernels():
            assert get_agent_kernel_metadata(k)["supports_branch"] is True

        assert get_agent_capability_level("codex", "hook_injection") == "adapted"
        assert get_agent_capability_level("codex", "identity_probe") == "adapted"
        assert get_agent_capability_level("agy", "identity_probe") == "adapted"
        assert get_agent_capability_level("opencode", "identity_probe") == "adapted"
        assert get_agent_capability_level("opencode", "transcript_sync") == "adapted"
        assert get_agent_capability_level("coreagent", "awaiting_input_probe") == "adapted"

    def test_profile_targets_includes_agy(self) -> None:
        assert "agy" in profile_targets.AGENT_TARGETS
        assert set(profile_targets.AGENT_TARGETS) == {
            "claude",
            "opencode",
            "codex",
            "agy",
            "coreagent",
        }

    def test_delete_session_blocks_running_headless_coreagent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        from frago.server.app import create_app

        sid = "core_runningdelete001"
        monkeypatch.setattr(record_reader, "detect_family", lambda _s: "coreagent")
        monkeypatch.setattr(tmux_sessions_service, "find_for_session", lambda _s: None)
        monkeypatch.setattr(coreagent_runner, "running", lambda s: s == sid)

        client = TestClient(create_app(), client=("127.0.0.1", 50000))
        res = client.delete(f"/api/workbench/sessions/{sid}")
        assert res.status_code == 409
        assert "还在跑" in res.json()["detail"]

    def test_opencode_stream_drives_session_ontology_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ont = MagicMock()
        stream = OpencodeStream(ontology_service=ont, origin="web")

        # 第一趟对齐水位（不推送历史）
        rec1 = UnifiedRecord(
            id="m1:0",
            session_id="ses_ont1",
            group_id="m1",
            seq=0,
            ts=1000,
            kind="user.say",
            agent_path=[],
            payload={"text": "hi"},
        )
        monkeypatch.setattr("frago.session.opencode_stream._safe_translate", lambda _s: [rec1])
        monkeypatch.setattr("frago.session.opencode_stream.latest_turn", lambda _s: SimpleNamespace(done=False))
        monkeypatch.setattr("frago.session.session_origin.load_origin_index", lambda: SimpleNamespace(is_worker=lambda _s: False))

        stream._process_session("ses_ont1")
        ont.ensure_managed_session.assert_not_called()

        # 第二趟增量到达并结束轮次
        rec2 = UnifiedRecord(
            id="m2:0",
            session_id="ses_ont1",
            group_id="m2",
            seq=1,
            ts=2000,
            kind="agent.say",
            agent_path=[],
            payload={"text": "hello"},
        )
        monkeypatch.setattr(
            "frago.session.opencode_stream._safe_translate",
            lambda _s: [rec1, rec2],
        )
        monkeypatch.setattr(
            "frago.session.opencode_stream.latest_turn",
            lambda _s: SimpleNamespace(done=True),
        )
        stream._process_session("ses_ont1")

        ont.ensure_managed_session.assert_called_with(
            session_id="ses_ont1", agent_kernel_id="opencode", origin="web"
        )
        ont.record_session_step.assert_called_once()
        ont.yield_awaiting_input.assert_called_once_with(
            session_id="ses_ont1", waiting_reason="end_turn"
        )

    def test_codex_and_opencode_busy_probe_crop_scrollback_and_check_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scrollback_noise = (
            "Earlier docs mentioned press esc to cancel if needed.\n"
            "⠋ Old step…\n"
            + "\n".join(f"line {i}" for i in range(15))
            + "\n› \n"
        )

        codex = CodexSessionAdapter()
        monkeypatch.setattr(
            codex,
            "probe_turn_completion",
            lambda _sid: TurnCompletionVerdict(done=False, stop_reason=None, unknown=True),
        )
        assert codex.probe_harness_idle("cx-1", pane_text=scrollback_noise).is_busy is False

        opencode = OpencodeSessionAdapter()
        monkeypatch.setattr(
            opencode,
            "probe_turn_completion",
            lambda _sid: TurnCompletionVerdict(done=False, stop_reason=None, unknown=True),
        )
        assert opencode.probe_harness_idle("ses_1", pane_text=scrollback_noise).is_busy is False

        # 即便底部仍有残余提示，只要转录明确已 done，交叉校验应判定空闲
        monkeypatch.setattr(
            opencode,
            "probe_turn_completion",
            lambda _sid: TurnCompletionVerdict(done=True, stop_reason="end_turn", unknown=False),
        )
        assert opencode.probe_harness_idle("ses_1", pane_text="esc to interrupt").is_busy is False

    def test_coreagent_awaiting_input_and_transcript_path_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        core_sid = "core_waitprobe00001"
        tfile = tmp_path / f"{core_sid}.jsonl"
        tfile.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-11-15T10:00:00Z",
                    "message": {
                        "role": "assistant",
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "任务已完成"}],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "frago.session.coreagent_store.find_session_file",
            lambda s: tfile if s == core_sid else None,
        )
        assert tmux_sessions_service._transcript_path(core_sid) == tfile
        assert (
            tmux_sessions_service._awaiting_input(
                "", True, kernel="coreagent", session_id=core_sid
            )
            is True
        )

        monkeypatch.setattr(coreagent_runner, "busy", lambda s: s == core_sid)
        assert (
            tmux_sessions_service._awaiting_input(
                "", True, kernel="coreagent", session_id=core_sid
            )
            is False
        )

    def test_usage_tick_infers_context_window(self) -> None:
        tick_claude = usage_tick.build_tick(
            {"input": 100, "output": 20, "cache_creation": 0, "cache_read": 50},
            model="claude-sonnet-4-6",
        )
        assert tick_claude["context_window"] == 200_000

        tick_gemini = usage_tick.build_tick(
            {"input": 100, "output": 20, "cache_creation": 0, "cache_read": 0},
            model="gemini-2.5-pro",
        )
        assert tick_gemini["context_window"] == 1_000_000

        tick_explicit = usage_tick.build_tick(
            {"input": 100, "output": 20, "cache_creation": 0, "cache_read": 0},
            model="claude-sonnet-4-6",
            context_window=512_000,
        )
        assert tick_explicit["context_window"] == 512_000

    def test_active_and_reserved_agent_type_partition(self) -> None:
        assert {t.value for t in ACTIVE_AGENT_TYPES} == {
            "claude",
            "opencode",
            "codex",
            "coreagent",
            "agy",
        }
        assert set(RESERVED_AGENT_TYPES) == {AgentType.CURSOR, AgentType.CLINE}
