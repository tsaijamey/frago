"""Regression tests for 2026-11-20 ontology five-state cutover, bloodline ledger, error non-folding, monotonic turn_seq, and file anti-reset guardrails."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from frago.file_guard import (
    FileGuardError,
    FileLockTimeoutError,
    ProtectedFileReadError,
    lkg_path_for,
    locked_file,
)


class TestAgyZombieAndErrorNonFolding:
    def test_agy_stale_running_converges_and_error_never_folds_to_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.session import coreagent_store, record_reader, session_index, storage
        from frago.session.models import AgentType, SessionStatus
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        monkeypatch.setattr(coreagent_store, "sessions_root", lambda: tmp_path / "claude_projects")
        monkeypatch.setattr(
            session_index, "COREAGENT_CACHE_FILE", tmp_path / "coreagent-session-index.json"
        )
        monkeypatch.setattr(storage, "_live_tmux_session_ids", lambda: set())

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr("frago.session.store.get_default_session_store", lambda: store)

        # 1) Create stale >6h agy session with raw.jsonl only + ontology stuck at running
        agy_dir = tmp_path / "sessions" / "agy" / "agy_zombie_01"
        agy_dir.mkdir(parents=True)
        raw = agy_dir / "raw.jsonl"
        old_dt = datetime.now() - timedelta(hours=8)
        raw.write_text(
            json.dumps(
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "content": "hello",
                    "created_at": old_dt.isoformat(timespec="seconds"),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        old_ts = old_dt.timestamp()
        os.utime(raw, (old_ts, old_ts))

        store.save(
            SessionOntologyRecord(
                session_id="agy_zombie_01",
                agent_kernel="agy",
                lifecycle_state="running",
                updated_at=int(old_ts),
            )
        )

        # CLI storage.list_sessions(running) must NOT keep >6h disconnected zombie in running
        running_agy = storage.list_sessions(
            agent_type=AgentType.AGY, status=SessionStatus.RUNNING, limit=50
        )
        assert all(s.session_id != "agy_zombie_01" for s in running_agy)
        reconciled_onto = store.get("agy_zombie_01")
        assert reconciled_onto is not None
        assert reconciled_onto.lifecycle_state == "completed"

        # 2) Create core_7ef20ab9-style coreagent session ending with empty_answer error
        proj = tmp_path / "claude_projects" / "-tmp-demo"
        proj.mkdir(parents=True)
        err_sid = "core_7ef20ab9e7e2437bbc0cf58b890ef435"
        err_jsonl = proj / f"{err_sid}.jsonl"
        err_jsonl.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": "2026-11-20T08:00:00Z",
                            "message": {"role": "user", "content": "check status"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "system",
                            "subtype": "empty_answer",
                            "level": "error",
                            "content": "model returned empty response",
                            "timestamp": "2026-11-20T08:00:05Z",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        store.save(
            SessionOntologyRecord(
                session_id=err_sid,
                agent_kernel="coreagent",
                lifecycle_state="running",
            )
        )

        inspected = coreagent_store.inspect_session_file(err_jsonl)
        assert inspected.status == SessionStatus.ERROR

        cards = record_reader.list_sessions(liveness={})
        err_card = next(c for c in cards if c.session_id == err_sid)
        assert err_card.status == "error"
        assert err_card.lifecycle_state == "error"
        healed = store.get(err_sid)
        assert healed is not None
        assert healed.lifecycle_state == "error"


class TestEmployeeBloodlineCutover:
    def test_filmmaker_does_not_poach_keyword_sessions_and_cleans_legacy_pollution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.employee import (
            EmployeeLedger,
            EmployeeOntologyService,
            LedgerCursor,
            load_ledger,
            resolve_session_employee_id,
            save_ledger,
            sync_employee_ledger,
        )
        from frago.employee.store import get_post, save_post
        from frago.session import storage
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))
        monkeypatch.setattr(storage, "_live_tmux_session_ids", lambda: set())

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        onto_svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: onto_svc)
        monkeypatch.setattr("frago.session.store.get_default_session_store", lambda: store)

        # Create 3 historical sessions matching "电影 视频 短剧 剪辑" keywords without filmmaker bloodline
        for idx in range(3):
            sdir = tmp_path / "sessions" / "claude" / f"old_video_{idx}"
            sdir.mkdir(parents=True)
            (sdir / "metadata.json").write_text(
                json.dumps(
                    {
                        "session_id": f"old_video_{idx}",
                        "name": f"电影短剧剪辑脚本 #{idx}",
                        "started_at": "2026-11-18T10:00:00",
                        "last_activity": "2026-11-18T11:00:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (sdir / "steps.jsonl").write_text(
                json.dumps({"step_id": 1, "type": "user", "content_summary": "制作电影短剧分镜视频"})
                + "\n",
                encoding="utf-8",
            )

        # Create 1 genuine filmmaker bloodline session (terminated -> should prune from active_session_ids)
        own_dir = tmp_path / "sessions" / "claude" / "fm_own_01"
        own_dir.mkdir(parents=True)
        (own_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "session_id": "fm_own_01",
                    "name": "短剧分镜执行",
                    "started_at": "2026-11-20T09:00:00",
                    "last_activity": "2026-11-20T09:10:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (own_dir / "steps.jsonl").write_text(
            json.dumps(
                {
                    "step_id": 1,
                    "type": "user",
                    "content_summary": '<frago-employee id="filmmaker" />\n生成第一集分镜',
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        store.save(
            SessionOntologyRecord(
                session_id="fm_own_01",
                agent_kernel="claude",
                lifecycle_state="completed",
                employee_id="filmmaker",
            )
        )

        emp_svc = EmployeeOntologyService()
        post, _ = emp_svc.hire(
            "filmmaker",
            title="AI 电影制片人",
            description="负责电影、视频、短剧分镜与剪辑生产。",
            work_scope="电影 视频 短剧 剪辑 分镜",
        )
        post.active_session_ids = ["fm_own_01"]
        save_post(post)

        # Seed polluted legacy ledger (simulating old keyword poacher output)
        save_ledger(
            EmployeeLedger(
                member_post_id="filmmaker",
                work_scope_anchor="电影 视频 短剧 剪辑",
                cursor=LedgerCursor(
                    processed_session_ids=["old_video_0", "old_video_1", "old_video_2"]
                ),
                claimed_resources={
                    "data_slots": [],
                    "data_incremental_entries": [],
                    "recipes": [],
                    "knowledge_domains": [],
                    "matched_sessions": [
                        {"session_id": "old_video_0", "title": "旧视频0"},
                        {"session_id": "old_video_1", "title": "旧视频1"},
                    ],
                },
                active_topics=[
                    {"topic_key": "session:old_video_0", "title": "旧视频0", "status": "active"}
                ],
            )
        )

        sync_employee_ledger("filmmaker")
        cleaned = load_ledger("filmmaker")
        assert cleaned is not None
        matched_ids = {s["session_id"] for s in cleaned.claimed_resources["matched_sessions"]}
        assert matched_ids == {"fm_own_01"}
        assert cleaned.cursor.processed_session_ids == ["fm_own_01"]
        assert all(
            not str(t.get("topic_key", "")).startswith("session:old_video_")
            for t in cleaned.active_topics
        )

        updated_post = get_post("filmmaker")
        assert updated_post is not None
        assert "fm_own_01" not in updated_post.active_session_ids
        assert resolve_session_employee_id("fm_own_01") == "filmmaker"


class TestMonotonicTurnSeqGuard:
    def test_stale_turn_seq_is_dropped_across_service_dispatch_queue_and_runner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.server.services import coreagent_runner as cr
        from frago.server.services import workbench_queue
        from frago.session.async_dispatch import (
            AsyncDispatchJob,
            is_job_superseded,
            save_dispatch_job,
        )
        from frago.session.service import SessionOntologyService, StaleTurnEventError
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        store.save(
            SessionOntologyRecord(
                session_id="s_turn_guard",
                agent_kernel="coreagent",
                lifecycle_state="running",
                turn_seq=0,
            )
        )

        # Turn 1 starts -> seq 1; Turn 2 starts -> seq 2
        r1 = svc.start_turn("s_turn_guard")
        assert r1.turn_seq == 1
        r2 = svc.start_turn("s_turn_guard")
        assert r2.turn_seq == 2

        # Late completion callback from Turn 1 must be blocked and leave Turn 2 running
        rec_late, applied_late = svc.complete_turn_if_current("s_turn_guard", turn_seq=1)
        assert applied_late is False
        assert rec_late is not None and rec_late.lifecycle_state == "running"
        assert store.get("s_turn_guard").lifecycle_state == "running"  # type: ignore[union-attr]
        with pytest.raises(StaleTurnEventError):
            svc.transition_state("s_turn_guard", "completed", turn_seq=1)
        rec_ok, applied_ok = svc.complete_turn_if_current("s_turn_guard", turn_seq=2)
        assert applied_ok is True
        assert rec_ok is not None and rec_ok.lifecycle_state == "completed"
        assert store.get("s_turn_guard").lifecycle_state == "completed"  # type: ignore[union-attr]

        # async_dispatch supersedes older turn_seq
        job = AsyncDispatchJob(
            job_id="job_t1",
            kind="worker",
            mode="new",
            caller_session_id="p_1",
            caller_employee_id=None,
            caller_cwd="/tmp",
            target_session_id="s_turn_guard",
            target_name=None,
            employee_id=None,
            agent="claude",
            cwd="/tmp",
            prompt="test",
            task_summary="test",
            turn_seq=1,
        )
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        save_dispatch_job(job)
        superseded, reason = is_job_superseded(job)
        assert superseded is True
        assert reason and "turn_seq" in reason

        # workbench_queue drops stale settle callback
        called: list[str] = []
        monkeypatch.setattr(workbench_queue, "try_auto_inject", lambda sid, **_k: called.append(sid) or False)
        workbench_queue.bump_turn_seq("q_turn_1")  # seq=1
        workbench_queue.bump_turn_seq("q_turn_1")  # seq=2
        workbench_queue.schedule_auto_inject_after_settle("q_turn_1", turn_seq=1)
        assert called == []

        # coreagent_runner drops late result from Turn 1 when Turn 2 is active
        sess = cr._session_for("core_turn_guard", "/tmp", None)
        try:
            proc = type(
                "FakeProc",
                (),
                {
                    "stdin": type("S", (), {"closed": False, "close": lambda self: None})(),
                    "stdout": iter(
                        [
                            json.dumps(
                                {
                                    "type": "result",
                                    "subtype": "success",
                                    "is_error": False,
                                    "result": "late turn 1 result",
                                    "num_turns": 1,
                                    "session_id": "core_turn_guard",
                                }
                            )
                            + "\n"
                        ]
                    ),
                    "poll": lambda self: None,
                    "terminate": lambda self: None,
                    "kill": lambda self: None,
                },
            )()
            sess.proc = proc
            sess.state = "busy"
            sess.turn_seq = 2
            sess.in_flight = 2
            sess.in_flight_turns = [1, 2]
            cr._read_loop(sess)
            # Late turn 1 result must NOT overwrite last_result or clear turn 2
            assert sess.last_result == {}
        finally:
            cr._sessions.pop("core_turn_guard", None)


class TestFileGuardAntiReset:
    def test_corrupted_files_never_reset_to_empty_on_save_and_recover_from_lkg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from frago.employee import (
            EmployeeLedger,
            EmployeePostRecord,
            load_ledger,
            save_ledger,
            save_post,
        )
        from frago.init import config_manager, profile_manager
        from frago.init.models import Config
        from frago.init.profile_manager import APIProfile, ProfileStore
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))

        # 1) ProfileStore: valid save creates .lkg; corrupted profiles.json recovers from .lkg
        p_path = tmp_path / "profiles.json"
        monkeypatch.setattr(profile_manager, "PROFILES_PATH", p_path)
        profile_manager.save_profiles(
            ProfileStore(
                profiles=[
                    APIProfile(
                        id="p1",
                        name="Primary",
                        endpoint_type="custom",
                        url="https://api.example.com",
                        api_key="sk-test-secret",
                    )
                ]
            )
        )
        assert lkg_path_for(p_path).is_file()
        p_path.write_text("{corrupted json", encoding="utf-8")
        recovered = profile_manager.load_profiles()
        assert len(recovered.profiles) == 1
        assert recovered.profiles[0].id == "p1"

        # Without .lkg, corrupted profiles.json refuses overwrite on save/activate
        lkg_path_for(p_path).unlink()
        loaded_bad = profile_manager.load_profiles()
        assert loaded_bad.profiles == []
        with pytest.raises(ProtectedFileReadError):
            profile_manager.save_profiles(loaded_bad)
        with pytest.raises(ProtectedFileReadError):
            profile_manager.activate_profile("p1")
        assert p_path.read_text(encoding="utf-8") == "{corrupted json"

        # 2) Config: corrupted config.json without .lkg blocks save_config / update_config
        c_path = tmp_path / "config.json"
        monkeypatch.setattr(config_manager, "CONFIG_PATH", c_path)
        config_manager.save_config(Config())
        lkg_path_for(c_path).unlink()
        c_path.write_text("{bad config", encoding="utf-8")
        with pytest.raises(ProtectedFileReadError):
            config_manager.update_config(lambda c: setattr(c, "selected_agent_core", "codex"))
        assert c_path.read_text(encoding="utf-8") == "{bad config"

        # 3) SessionOntologyStore: corrupted store refuses save overwrite
        s_path = tmp_path / "session-ontology-store.json"
        s_store = SessionOntologyStore(store_path=s_path)
        s_store.save(SessionOntologyRecord(session_id="s1", agent_kernel="claude"))
        lkg_path_for(s_path).unlink()
        s_path.write_text("{corrupt store", encoding="utf-8")
        with pytest.raises(ProtectedFileReadError):
            s_store.save(SessionOntologyRecord(session_id="s2", agent_kernel="claude"))
        assert s_path.read_text(encoding="utf-8") == "{corrupt store"

        # 4) Employee post & ledger: corrupted file blocks read/save overwrite without .lkg
        from frago.employee import get_post, sync_employee_ledger

        emp_dir = tmp_path / "employees"
        post = EmployeePostRecord(member_post_id="demo", title="Demo", description="Desc")
        save_post(post, base_dir=emp_dir)
        post_path = emp_dir / "demo.json"
        lkg_path_for(post_path).unlink()
        post_path.write_text("{corrupt post", encoding="utf-8")
        with pytest.raises(ProtectedFileReadError):
            get_post("demo", base_dir=emp_dir)
        assert post_path.read_text(encoding="utf-8") == "{corrupt post"

        post_path.write_text(
            json.dumps(post.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
        ledger = EmployeeLedger(member_post_id="demo")
        save_ledger(ledger, base_dir=emp_dir)
        ledger_path = emp_dir / "demo.ledger.yaml"
        lkg_path_for(ledger_path).unlink()
        ledger_path.write_text(":::invalid: [yaml", encoding="utf-8")
        with pytest.raises(ProtectedFileReadError):
            load_ledger("demo", base_dir=emp_dir)
        with pytest.raises(ProtectedFileReadError):
            sync_employee_ledger("demo", base_dir=emp_dir)
        assert ledger_path.read_text(encoding="utf-8") == ":::invalid: [yaml"

        # 5) Concurrent writes under lock never corrupt JSON
        p_path.write_text(json.dumps({"version": 2, "profiles": []}), encoding="utf-8")
        errors: list[Exception] = []

        def _worker(idx: int) -> None:
            try:
                profile_manager.add_profile(
                    APIProfile(
                        id=f"conc_{idx}",
                        name=f"Concurrent {idx}",
                        endpoint_type="custom",
                        url="https://api.example.com",
                        api_key=f"sk-{idx}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        final_profiles = profile_manager.load_profiles()
        assert len(final_profiles.profiles) == 6


class TestReviewBlockingRegressions:
    def test_coreagent_enqueue_and_stream_bridge_do_not_double_increment_turn_seq(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blocking #1: coreagent_runner._enqueue + WorkbenchStreamBridge._on_new_records keep turn_seq=1 without dropping settle."""
        from frago.server.services import coreagent_runner as cr
        from frago.server.services import workbench_queue
        from frago.server.services.workbench_stream_bridge import WorkbenchStreamBridge

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        monkeypatch.setattr(workbench_queue, "is_server_process", lambda: True)
        scheduled: list[tuple[str, int | None]] = []

        # Enqueue a pending queued message so schedule_auto_inject_after_settle proceeds into timer scheduling
        sid = "core_no_double_seq"
        workbench_queue.enqueue(
            sid,
            text="follow-up queued prompt",
            prompt="follow-up queued prompt",
            auto_schedule=False,
        )
        monkeypatch.setattr(
            workbench_queue,
            "try_auto_inject",
            lambda s, **_kw: scheduled.append((s, workbench_queue.current_turn_seq(s)))
            or {"injected": False, "reason": "test"},
        )

        sess = cr._session_for(sid, "/tmp", None)
        bridge = WorkbenchStreamBridge(loop=None)
        monkeypatch.setattr(bridge, "_trigger_the_observer", lambda *_a, **_kw: None)
        monkeypatch.setattr(cr, "_spawn", lambda _s: None)
        try:
            # 1) coreagent_runner._enqueue bumps sess.turn_seq -> 1 and syncs queue -> 1
            cr._enqueue(sess, "first message")
            assert sess.turn_seq == 1
            assert workbench_queue.current_turn_seq(sid) == 1

            # 2) Native kernel writes user.say, WorkbenchStreamBridge sees it: must NOT double-increment to 2
            bridge._on_new_records(sid, [{"kind": "user.say", "seq": 1, "payload": {"text": "hi"}}])
            assert workbench_queue.current_turn_seq(sid) == 1

            # 3) On turn completion with turn_seq=1, settle scheduling MUST NOT be dropped
            workbench_queue.schedule_auto_inject_after_settle(
                sid, delay_s=5.0, max_retries=0, turn_seq=1
            )
            with workbench_queue._locks_guard:
                has_timer = sid in workbench_queue._settle_timers
                timer = workbench_queue._settle_timers.pop(sid, None)
            if timer is not None:
                timer.cancel()
            assert has_timer is True

            # 4) Once Turn 2 begins, stale turn_seq=1 completion from bridge is rejected
            cr._enqueue(sess, "second message")
            assert workbench_queue.current_turn_seq(sid) == 2
            bridge._on_turn_complete(sid, True, "end_turn", turn_seq=1)
            with workbench_queue._locks_guard:
                stale_timer = workbench_queue._settle_timers.get(sid)
            assert stale_timer is None
        finally:
            cr._sessions.pop(sid, None)
            bridge.stop_all()
            with workbench_queue._locks_guard:
                workbench_queue._active_turn_seq.pop(sid, None)
                t = workbench_queue._settle_timers.pop(sid, None)
                if t is not None:
                    t.cancel()

    def test_storage_list_sessions_handles_none_tmux_and_real_core_7ef20ab9_error_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blocking #2: _live_tmux_session_ids() returning None does not crash, and real core_7ef20ab9 format appears under status=ERROR."""
        from frago.session import coreagent_store, storage
        from frago.session.models import AgentType, SessionStatus
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        monkeypatch.setattr(storage, "_live_tmux_session_ids", lambda: None)

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr("frago.session.store.get_default_session_store", lambda: store)

        # 2a) >6h stale agy dir + ontology running when tmux is unavailable (None) -> no TypeError, converges to completed
        agy_dir = tmp_path / "sessions" / "agy" / "agy_no_tmux_01"
        agy_dir.mkdir(parents=True)
        raw_agy = agy_dir / "raw.jsonl"
        old_dt = datetime.now() - timedelta(hours=8)
        raw_agy.write_text(
            json.dumps({"step_index": 0, "type": "USER_INPUT", "content": "hi"}) + "\n",
            encoding="utf-8",
        )
        old_ts = old_dt.timestamp()
        os.utime(raw_agy, (old_ts, old_ts))
        store.save(
            SessionOntologyRecord(
                session_id="agy_no_tmux_01",
                agent_kernel="agy",
                lifecycle_state="running",
            )
        )
        running = storage.list_sessions(
            agent_type=AgentType.AGY, status=SessionStatus.RUNNING, limit=50
        )
        assert all(s.session_id != "agy_no_tmux_01" for s in running)
        assert store.get("agy_no_tmux_01").lifecycle_state == "completed"  # type: ignore[union-attr]

        # 2b) Real core_7ef20ab9 format: assistant + system(informational, warning) + system(turn_duration, warning)
        core_sid = "core_7ef20ab9e7e2437bbc0cf58b890ef435"
        core_dir = tmp_path / "sessions" / "coreagent" / core_sid
        core_dir.mkdir(parents=True)
        raw_core = core_dir / "raw.jsonl"
        raw_core.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": "2026-11-20T08:00:00Z",
                            "message": {"role": "user", "content": "run task"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "timestamp": "2026-11-20T08:00:04Z",
                            "message": {
                                "role": "assistant",
                                "content": "【收场交接】任务停下：为什么停（empty_answer）",
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "type": "system",
                            "subtype": "informational",
                            "level": "warning",
                            "content": "empty_answer: model returned empty output",
                            "timestamp": "2026-11-20T08:00:05Z",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "system",
                            "subtype": "turn_duration",
                            "level": "warning",
                            "durationMs": 5000,
                            "timestamp": "2026-11-20T08:00:05Z",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        inspected = coreagent_store.inspect_session_file(raw_core)
        assert inspected is not None
        assert inspected.status == SessionStatus.ERROR

        # Also test ontology-only error session with no error marker in transcript
        onto_err_sid = "core_onto_only_err"
        onto_err_dir = tmp_path / "sessions" / "coreagent" / onto_err_sid
        onto_err_dir.mkdir(parents=True)
        (onto_err_dir / "raw.jsonl").write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-11-20T08:00:00Z",
                    "message": {"role": "assistant", "content": "done"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        store.save(
            SessionOntologyRecord(
                session_id=onto_err_sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
            )
        )

        err_sessions = storage.list_sessions(
            agent_type=AgentType.COREAGENT, status=SessionStatus.ERROR, limit=50
        )
        err_ids = {s.session_id for s in err_sessions}
        assert core_sid in err_ids
        assert onto_err_sid in err_ids

    def test_file_guard_blocks_shared_to_exclusive_upgrade_and_config_recovers_lkg_on_validation_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blocking #3 & High #4: shared->exclusive lock upgrade fails loudly; config ValidationError recovers from .lkg; timeout raises FileLockTimeoutError."""
        from frago.init import config_manager
        from frago.init.models import Config

        guard_target = tmp_path / "guarded.json"
        # Same-thread shared -> exclusive nested lock must NOT silently proceed without exclusive lock
        with (
            locked_file(guard_target, exclusive=False),
            pytest.raises(FileGuardError, match="Cannot upgrade shared file lock"),
            locked_file(guard_target, exclusive=True),
        ):
            pass

        # Real timeout check across exclusive flock in two file descriptors
        lock_file = tmp_path / ".timeout_test.json.lock"
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (
                pytest.raises(FileLockTimeoutError),
                locked_file(tmp_path / "timeout_test.json", timeout_s=0.05, exclusive=True),
            ):
                pass
        finally:
            os.close(fd)

        # Config ValidationError tries .lkg recovery before partial field recovery; and legacy heal exits shared lock cleanly
        c_path = tmp_path / "config.json"
        monkeypatch.setattr(config_manager, "CONFIG_PATH", c_path)
        valid_cfg = Config(agent_core="codex")
        config_manager.save_config(valid_cfg)
        assert lkg_path_for(c_path).is_file()

        # Inject a Pydantic ValidationError into primary config.json while .lkg still holds codex
        c_path.write_text(
            json.dumps({"agent_core": "invalid_core_name"}),
            encoding="utf-8",
        )
        recovered = config_manager.load_config()
        assert recovered.agent_core == "codex"

        # Legacy config missing webui_sessions self-heals after exiting shared lock cleanly
        lkg_path_for(c_path).unlink()
        c_path.write_text(json.dumps({"agent_core": "claude"}), encoding="utf-8")
        healed = config_manager.load_config()
        assert healed.agent_core == "claude"
        on_disk = json.loads(c_path.read_text(encoding="utf-8"))
        assert "webui_sessions" in on_disk


class TestResumedErrorSessionTurnsRunning:
    """回归：前序轮次曾为 error 的会话重新启动/运行新一轮时，必须干净切回 running 而非残留旧 Error。"""

    def test_prior_error_followed_by_new_turn_transitions_to_running_across_store_stream_and_api(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio
        from types import SimpleNamespace

        from frago.server.routes import workbench as wb_route
        from frago.server.services import coreagent_runner, tmux_sessions_service, workbench_groups
        from frago.session import coreagent_store, record_reader, session_index, storage
        from frago.session.models import AgentType, SessionStatus
        from frago.session.opencode_stream import OpencodeStream
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore
        from frago.session.stream import SessionStream
        from frago.session.unified_record import UnifiedRecord

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        monkeypatch.setattr(coreagent_store, "sessions_root", lambda: tmp_path / "coreagent_projects")
        monkeypatch.setattr(
            session_index, "COREAGENT_CACHE_FILE", tmp_path / "coreagent-session-index.json"
        )
        monkeypatch.setattr(
            session_index, "CACHE_FILE", tmp_path / "claude-session-index.json"
        )
        monkeypatch.setattr(storage, "_live_tmux_session_ids", lambda: set())

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr("frago.session.store.get_default_session_store", lambda: store)

        # 1) 转录层：前序轮次为 informational+warning / api_error，随后发起新 user + tool_use（或仅 thinking）
        proj = tmp_path / "coreagent_projects" / "-tmp-resumed"
        proj.mkdir(parents=True)
        sid = "core_resumed_after_err_001"
        jsonl = proj / f"{sid}.jsonl"
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        jsonl_content = (
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": "2026-11-20T08:00:00Z",
                            "message": {"role": "user", "content": "turn 1"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "system",
                            "subtype": "informational",
                            "level": "warning",
                            "content": "empty_answer: prior failure",
                            "timestamp": "2026-11-20T08:00:05Z",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": now_iso,
                            "message": {"role": "user", "content": "turn 2 retry"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "timestamp": now_iso,
                            "message": {
                                "role": "assistant",
                                "content": [{"type": "thinking", "thinking": "analyzing..."}],
                            },
                        }
                    ),
                ]
            )
            + "\n"
        )
        jsonl.write_text(jsonl_content, encoding="utf-8")
        mirror_dir = tmp_path / "sessions" / "coreagent" / sid
        mirror_dir.mkdir(parents=True)
        (mirror_dir / "raw.jsonl").write_text(jsonl_content, encoding="utf-8")

        inspected = coreagent_store.inspect_session_file(jsonl)
        assert inspected is not None
        assert inspected.status == SessionStatus.RUNNING

        # 2) 本体此前停留在 error（且带旧 session_error 摘要），随后新轮次写入转录（mtime 晚于旧 error）
        store.save(
            SessionOntologyRecord(
                session_id=sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="session_error",
                step_count=10,
                turn_seq=0,
            )
        )
        new_mtime = datetime.now().timestamp() + 5.0
        os.utime(mirror_dir / "raw.jsonl", (new_mtime, new_mtime))
        os.utime(jsonl, (new_mtime, new_mtime))

        # storage.list_sessions 与 record_reader.list_sessions 都必须判为 running 并把本体从 error 恢复
        running_core = storage.list_sessions(
            agent_type=AgentType.COREAGENT, status=SessionStatus.RUNNING, limit=50
        )
        assert any(s.session_id == sid for s in running_core)
        cards = record_reader.list_sessions(liveness={sid: True})
        resumed_card = next(c for c in cards if c.session_id == sid)
        assert resumed_card.status == "running"
        assert resumed_card.lifecycle_state == "running"
        assert resumed_card.digest_stuck is None
        healed = store.get(sid)
        assert healed is not None
        assert healed.lifecycle_state == "running"
        assert healed.summary == ""

        # 3) SessionStream / OpencodeStream 观察到终态(error)会话有新活跃步骤时，必须先 start_turn 再记步
        stream_sid = "core_stream_resume_002"
        store.save(
            SessionOntologyRecord(
                session_id=stream_sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="api_error",
                step_count=5,
                turn_seq=1,
            )
        )
        stream_file = proj / f"{stream_sid}.jsonl"
        stream_file.write_text(
            json.dumps(
                {
                    "type": "user",
                    "timestamp": now_iso,
                    "message": {"role": "user", "content": "resume from stream"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        stream = SessionStream(
            project_path=str(proj),
            watch_dir=proj,
            ontology_service=svc,
            family="coreagent",
            origin="web",
        )
        stream.watch_session(stream_sid, watch_file=stream_file)
        stream._file_seqs[str(stream_file)] = -1
        stream._process_file(str(stream_file))
        stream_rec = store.get(stream_sid)
        assert stream_rec is not None
        assert stream_rec.lifecycle_state == "running"
        assert stream_rec.summary == ""
        assert stream_rec.turn_seq == 2
        assert stream_rec.step_count == 6

        oc_sid = "ses_opencode_resume_003"
        store.save(
            SessionOntologyRecord(
                session_id=oc_sid,
                agent_kernel="opencode",
                lifecycle_state="error",
                summary="model_error",
                step_count=3,
                turn_seq=1,
            )
        )
        oc_stream = OpencodeStream(ontology_service=svc, origin="web")
        oc_rec1 = UnifiedRecord(
            id="m1:0",
            session_id=oc_sid,
            group_id="m1",
            seq=0,
            ts=1000,
            kind="error",
            agent_path=[],
            payload={"message": "boom"},
            raw_available=False,
        )
        oc_rec2 = UnifiedRecord(
            id="m2:0",
            session_id=oc_sid,
            group_id="m2",
            seq=1,
            ts=2000,
            kind="user.say",
            agent_path=[],
            payload={"text": "retry"},
        )
        oc_stream._session_seqs[oc_sid] = 0
        oc_stream._session_done[oc_sid] = True
        monkeypatch.setattr("frago.session.opencode_stream._safe_translate", lambda _s: [oc_rec1, oc_rec2])
        monkeypatch.setattr("frago.session.opencode_stream.latest_turn", lambda _s: SimpleNamespace(done=False))
        monkeypatch.setattr(
            "frago.session.session_origin.load_origin_index",
            lambda: SimpleNamespace(is_worker=lambda _s: False),
        )
        oc_stream._process_session(oc_sid)
        oc_onto = store.get(oc_sid)
        assert oc_onto is not None
        assert oc_onto.lifecycle_state == "running"
        assert oc_onto.turn_seq == 2
        assert oc_onto.step_count == 4

        # 4) /api/workbench/sessions：即使转录尚停在前序 error，但 start_turn 已启动或 coreagent_runner 正忙，
        #    返回前端的必须是 status="running", lifecycle_state="running", digest_stuck=None；
        #    而真正以错误停下且未在跑的会话仍返回 status="error", lifecycle_state="error"。
        busy_after_err_sid = "core_busy_just_started"
        real_err_sid = "core_7ef20ab9e7e2437bbc0cf58b890ef435"
        store.save(
            SessionOntologyRecord(
                session_id=busy_after_err_sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="old error",
                turn_seq=1,
            )
        )
        svc.start_turn(busy_after_err_sid, agent_kernel_id="coreagent", origin="web")
        store.save(
            SessionOntologyRecord(
                session_id=real_err_sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="empty_answer",
                turn_seq=1,
            )
        )
        mock_cards = [
            record_reader.SessionCard(
                session_id=busy_after_err_sid,
                family="coreagent",
                title="Retrying after error",
                directory="/tmp",
                created_at=1000,
                last_active_at=int((datetime.now().timestamp() - 30) * 1000),
                status="error",
                digest_stuck="old error",
                last_kind="error",
                lifecycle_state="error",
            ),
            record_reader.SessionCard(
                session_id=real_err_sid,
                family="coreagent",
                title="Real failed session",
                directory="/tmp",
                created_at=1000,
                last_active_at=int((datetime.now().timestamp() - 30) * 1000),
                status="error",
                digest_stuck="empty_answer",
                last_kind="error",
                lifecycle_state="error",
            ),
        ]
        monkeypatch.setattr(record_reader, "list_sessions", lambda **_k: list(mock_cards))
        monkeypatch.setattr(tmux_sessions_service, "open_session_names", lambda: set())
        monkeypatch.setattr(
            coreagent_runner, "live_states", lambda: {busy_after_err_sid: True}
        )
        monkeypatch.setattr(workbench_groups, "local_ops_session_ids", lambda: set())
        monkeypatch.setattr(wb_route, "list_posts", lambda: [])
        monkeypatch.setattr(wb_route, "_dispatch_states_by_caller", lambda **_k: (set(), set()))
        monkeypatch.setattr(wb_route, "_observer_slots_state", lambda *_a: (False, False))
        monkeypatch.setattr(wb_route, "_keep_watching_only", lambda _sids: None)

        rows = asyncio.run(wb_route.list_workbench_sessions())
        by_id = {r["session_id"]: r for r in rows}
        assert by_id[busy_after_err_sid]["status"] == "running"
        assert by_id[busy_after_err_sid]["lifecycle_state"] == "running"
        assert by_id[busy_after_err_sid]["digest_stuck"] is None

        assert by_id[real_err_sid]["status"] == "error"
        assert by_id[real_err_sid]["lifecycle_state"] == "error"
        assert by_id[real_err_sid]["digest_stuck"] == "empty_answer"

    def test_tmux_fresh_start_turn_and_dead_90s_runner_error_via_real_record_reader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """端到端不打桩 record_reader.list_sessions：
        1) tmux 会话刚 start_turn()、旧转录末尾仍是 error 且新 user 尚未落盘时，
           调 /api/workbench/sessions 不得反手把本体写回 error，且必须返回 running；
        2) 外围运行器写入 error 且末尾无独立 error 行、距最后写入 < 90s 且 is_alive=False 时，
           不得被 90 秒窗口洗白成 running 或 completed。
        """
        import asyncio

        from frago.agent_driver.tmux_session import tmux_name_for
        from frago.server.routes import workbench as wb_route
        from frago.server.services import coreagent_runner, tmux_sessions_service, workbench_groups
        from frago.session import coreagent_store, record_reader, session_index
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        monkeypatch.setattr(coreagent_store, "sessions_root", lambda: tmp_path / "coreagent_projects")
        monkeypatch.setattr(
            session_index, "COREAGENT_CACHE_FILE", tmp_path / "coreagent-session-index.json"
        )
        # 不 monkeypatch record_reader.list_sessions，仅隔离其余四家扫描以避免扫描宿主机真实家目录
        monkeypatch.setattr(record_reader, "_claude_cards", lambda *_a, **_k: [])
        monkeypatch.setattr(record_reader, "_opencode_cards", lambda *_a, **_k: [])
        monkeypatch.setattr(record_reader, "_codex_cards", lambda *_a, **_k: [])
        monkeypatch.setattr(record_reader, "_agy_cards", lambda *_a, **_k: [])

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr("frago.session.store.get_default_session_store", lambda: store)

        proj = tmp_path / "coreagent_projects" / "-tmp-real-chain"
        proj.mkdir(parents=True)
        now_s = datetime.now().timestamp()

        # 场景 1：tmux 常驻会话刚 start_turn()，但新 user 尚未落盘，旧转录末尾仍是 error
        tmux_sid = "core_tmux_fresh_turn_001"
        tmux_jsonl = proj / f"{tmux_sid}.jsonl"
        old_err_content = (
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-11-20T09:00:00Z",
                    "message": {"role": "user", "content": "turn 1"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "system",
                    "subtype": "informational",
                    "level": "warning",
                    "content": "empty_answer",
                    "timestamp": "2026-11-20T09:00:05Z",
                }
            )
            + "\n"
        )
        tmux_jsonl.write_text(old_err_content, encoding="utf-8")
        os.utime(tmux_jsonl, (now_s - 30.0, now_s - 30.0))
        store.save(
            SessionOntologyRecord(
                session_id=tmux_sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="session_error",
                turn_seq=0,
                updated_at=int(now_s - 30),
            )
        )
        svc.start_turn(tmux_sid, agent_kernel_id="coreagent", origin="web")

        # 场景 2：外围运行器捕获错误写入 ontology=error，转录末条为 agent.say 且距今 < 90s（> rec.updated_at + 2s），已死亡
        dead_err_sid = "core_dead_runner_err_002"
        dead_jsonl = proj / f"{dead_err_sid}.jsonl"
        from datetime import UTC

        dead_msg_iso = datetime.fromtimestamp(now_s - 10.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        dead_content = (
            json.dumps(
                {
                    "type": "user",
                    "timestamp": dead_msg_iso,
                    "message": {"role": "user", "content": "turn 1"},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "timestamp": dead_msg_iso,
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "partial"}]},
                }
            )
            + "\n"
        )
        dead_jsonl.write_text(dead_content, encoding="utf-8")
        os.utime(dead_jsonl, (now_s - 5.0, now_s - 5.0))
        store.save(
            SessionOntologyRecord(
                session_id=dead_err_sid,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="runner_exit_nonzero",
                turn_seq=1,
                updated_at=int(now_s - 20),
            )
        )

        # 即使无参数调用 record_reader.list_sessions()（liveness=None），也不得把 tmux_sid 反写回 error，
        # 也不得把 dead_err_sid 洗白成 running 或 completed
        direct_cards = {c.session_id: c for c in record_reader.list_sessions()}
        assert direct_cards[tmux_sid].status == "running"
        assert direct_cards[tmux_sid].lifecycle_state == "running"
        assert store.get(tmux_sid).lifecycle_state == "running"
        assert direct_cards[dead_err_sid].status == "error"
        assert direct_cards[dead_err_sid].lifecycle_state == "error"
        assert store.get(dead_err_sid).lifecycle_state == "error"

        monkeypatch.setattr(
            tmux_sessions_service, "open_session_names", lambda: {tmux_name_for(tmux_sid)}
        )
        monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
        monkeypatch.setattr(workbench_groups, "local_ops_session_ids", lambda: set())
        monkeypatch.setattr(wb_route, "list_posts", lambda: [])
        monkeypatch.setattr(wb_route, "_dispatch_states_by_caller", lambda **_k: (set(), set()))
        monkeypatch.setattr(wb_route, "_observer_slots_state", lambda *_a: (False, False))
        monkeypatch.setattr(wb_route, "_keep_watching_only", lambda _sids: None)

        rows = asyncio.run(wb_route.list_workbench_sessions())
        by_id = {r["session_id"]: r for r in rows}

        assert by_id[tmux_sid]["status"] == "running"
        assert by_id[tmux_sid]["lifecycle_state"] == "running"
        assert by_id[tmux_sid]["in_tmux"] is True
        assert by_id[tmux_sid]["digest_stuck"] is None
        assert store.get(tmux_sid).lifecycle_state == "running"

        assert by_id[dead_err_sid]["status"] == "error"
        assert by_id[dead_err_sid]["lifecycle_state"] == "error"
        assert by_id[dead_err_sid]["alive"] is False
        assert store.get(dead_err_sid).lifecycle_state == "error"

    def test_send_when_idle_not_now_preserves_error_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        from frago.server.services import session_send, ui_session_runner
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)

        cc_sid = "11111111-2222-3333-4444-555555555555"
        store.save(
            SessionOntologyRecord(
                session_id=cc_sid,
                agent_kernel="claude",
                lifecycle_state="error",
                summary="previous_failure",
                turn_seq=2,
            )
        )
        monkeypatch.setattr(
            session_send,
            "resolve_target",
            lambda _sid, **_k: session_send.SendTarget(
                session_id=cc_sid,
                family="claude-code",
                agent_type="claude",
                cwd=str(tmp_path),
                is_new=False,
            ),
        )
        fake_runner = SimpleNamespace(submit_when_idle=lambda *_a, **_k: "not_now")
        monkeypatch.setattr(ui_session_runner, "get_runner", lambda: fake_runner)

        verdict = session_send.send_when_idle(cc_sid, "callback ping", landed=lambda: False)
        assert verdict == "not_now"
        rec_after = store.get(cc_sid)
        assert rec_after is not None
        assert rec_after.lifecycle_state == "error"
        assert rec_after.summary == "previous_failure"
        assert rec_after.turn_seq == 2

        # 确认真正 landed 时才推进为 running
        fake_runner_ok = SimpleNamespace(submit_when_idle=lambda *_a, **_k: "landed")
        monkeypatch.setattr(ui_session_runner, "get_runner", lambda: fake_runner_ok)
        verdict_ok = session_send.send_when_idle(cc_sid, "callback ok", landed=lambda: True)
        assert verdict_ok == "landed"
        rec_landed = store.get(cc_sid)
        assert rec_landed is not None
        assert rec_landed.lifecycle_state == "running"
        assert rec_landed.summary == ""
        assert rec_landed.turn_seq == 3

    def test_coreagent_runner_late_turn1_closeout_does_not_overwrite_turn2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io
        from types import SimpleNamespace

        from frago.server.services import coreagent_runner, workbench_queue
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyStore

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr(workbench_queue, "schedule_auto_inject_after_settle", lambda *_a, **_k: None)

        # 场景 A：Turn 1 刚释放 sess.lock 后 Turn 2 已入队（sess.turn_seq 推进、state=busy），
        # Turn 1 二次锁检查必须放弃收口，不得覆盖 Turn 2 的 running
        sid_a = "core_race_guard_001"
        started_t1 = svc.start_turn(sid_a, agent_kernel_id="coreagent", origin="web")
        fake_stdout_a = io.StringIO(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "result": "turn1_err",
                }
            )
            + "\n"
        )
        sess_a = coreagent_runner._Session(
            session_id=sid_a,
            cwd=str(tmp_path),
            state="busy",
            proc=SimpleNamespace(stdout=fake_stdout_a),
            in_flight=1,
            turn_seq=1,
            in_flight_turns=[1],
            onto_turn_seqs={1: started_t1.turn_seq},
        )
        t2_fired = False
        reconcile_calls_a = 0
        orig_reconcile_a = svc.reconcile_session_lifecycle

        def _count_reconcile_a(*args: object, **kwargs: object):
            nonlocal reconcile_calls_a
            reconcile_calls_a += 1
            return orig_reconcile_a(*args, **kwargs)

        monkeypatch.setattr(svc, "reconcile_session_lifecycle", _count_reconcile_a)

        def _get_svc_and_enqueue_t2():
            nonlocal t2_fired
            if not t2_fired:
                t2_fired = True
                with sess_a.lock:
                    sess_a.turn_seq = 2
                    sess_a.state = "busy"
                svc.start_turn(sid_a, agent_kernel_id="coreagent", origin="web")
            return svc

        monkeypatch.setattr("frago.session.service.get_default_session_service", _get_svc_and_enqueue_t2)
        coreagent_runner._read_loop(sess_a)
        assert reconcile_calls_a == 0
        rec_a = store.get(sid_a)
        assert rec_a is not None
        assert rec_a.lifecycle_state == "running"
        assert rec_a.turn_seq == 2

        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr(svc, "reconcile_session_lifecycle", orig_reconcile_a)

        # 场景 B：Turn 1 通过 sess.lock 检查后、写本体前 Turn 2 启动，
        # 单调 turn_seq 栅栏必须拦截 Turn 1 迟到的 error 收口
        sid_b = "core_race_fence_002"
        started_b1 = svc.start_turn(sid_b, agent_kernel_id="coreagent", origin="web")
        fake_stdout_b = io.StringIO(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "result": "turn1_err",
                }
            )
            + "\n"
        )
        sess_b = coreagent_runner._Session(
            session_id=sid_b,
            cwd=str(tmp_path),
            state="busy",
            proc=SimpleNamespace(stdout=fake_stdout_b),
            in_flight=1,
            turn_seq=1,
            in_flight_turns=[1],
            onto_turn_seqs={1: started_b1.turn_seq},
        )
        orig_reconcile = svc.reconcile_session_lifecycle
        reconcile_called = False

        def _turn2_starts_before_reconcile(*args: object, **kwargs: object):
            nonlocal reconcile_called
            reconcile_called = True
            svc.start_turn(sid_b, agent_kernel_id="coreagent", origin="web")
            return orig_reconcile(*args, **kwargs)

        monkeypatch.setattr(svc, "reconcile_session_lifecycle", _turn2_starts_before_reconcile)
        coreagent_runner._read_loop(sess_b)
        assert reconcile_called is True
        rec_b = store.get(sid_b)
        assert rec_b is not None
        assert rec_b.lifecycle_state == "running"
        assert rec_b.turn_seq == 2

    def test_stale_error_heals_after_newer_agent_reply_while_runner_error_stays_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """对照验证陈旧 error 自愈与运行器后发 error 保留：
        - 用例 A：本体 error 停在 T0，后续于 T0+60s 产出正常 agent.say（last_reply_at=T0+60s）→
          record_reader / storage / workbench 自愈为 completed / 非 error 并清空 session_error；
        - 用例 B：agent.say 停在 T0，运行器于 T0+1s 写入本体 error（last_reply_at <= updated_at+5s）→
          三层全部严格保留 error，绝不洗白。
        """
        import asyncio
        from datetime import UTC

        from frago.server.routes import workbench as wb_route
        from frago.server.services import coreagent_runner, tmux_sessions_service, workbench_groups
        from frago.session import coreagent_store, record_reader, session_index, storage
        from frago.session.models import AgentType, SessionStatus
        from frago.session.service import SessionOntologyService
        from frago.session.store import SessionOntologyRecord, SessionOntologyStore

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
        monkeypatch.setattr(coreagent_store, "sessions_root", lambda: tmp_path / "coreagent_projects")
        monkeypatch.setattr(
            session_index, "COREAGENT_CACHE_FILE", tmp_path / "coreagent-session-index.json"
        )
        monkeypatch.setattr(storage, "_live_tmux_session_ids", lambda: set())
        monkeypatch.setattr(record_reader, "_claude_cards", lambda *_a, **_k: [])
        monkeypatch.setattr(record_reader, "_opencode_cards", lambda *_a, **_k: [])
        monkeypatch.setattr(record_reader, "_codex_cards", lambda *_a, **_k: [])
        monkeypatch.setattr(record_reader, "_agy_cards", lambda *_a, **_k: [])

        store = SessionOntologyStore(store_path=tmp_path / "session-ontology-store.json")
        svc = SessionOntologyService(store=store)
        monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: svc)
        monkeypatch.setattr("frago.session.store.get_default_session_store", lambda: store)

        proj = tmp_path / "coreagent_projects" / "-tmp-heal-compare"
        proj.mkdir(parents=True)
        now_s = datetime.now().timestamp()

        # 用例 A：T0 = now - 120s 记入 error，T0 + 60s = now - 60s 完成新一轮正常 agent.say
        t0_a = int(now_s - 120)
        reply_a_s = float(t0_a + 60)
        reply_a_iso = datetime.fromtimestamp(reply_a_s, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        sid_a = "core_healed_after_reply_001"
        content_a = (
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": "2026-11-20T06:00:00Z",
                            "message": {"role": "user", "content": "turn 1"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "system",
                            "subtype": "informational",
                            "level": "warning",
                            "content": "empty_answer",
                            "timestamp": "2026-11-20T06:00:05Z",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": reply_a_iso,
                            "message": {"role": "user", "content": "turn 2"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "timestamp": reply_a_iso,
                            "message": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "正常完成新回复。"}],
                            },
                        }
                    ),
                ]
            )
            + "\n"
        )
        (proj / f"{sid_a}.jsonl").write_text(content_a, encoding="utf-8")
        os.utime(proj / f"{sid_a}.jsonl", (reply_a_s, reply_a_s))
        mirror_a = tmp_path / "sessions" / "coreagent" / sid_a
        mirror_a.mkdir(parents=True)
        (mirror_a / "raw.jsonl").write_text(content_a, encoding="utf-8")
        os.utime(mirror_a / "raw.jsonl", (reply_a_s, reply_a_s))
        from frago.session import store as onto_store_mod

        def _save_at(rec: SessionOntologyRecord, ts: float) -> None:
            with monkeypatch.context() as mp:
                mp.setattr(onto_store_mod.time, "time", lambda: ts)
                store.save(rec)

        _save_at(
            SessionOntologyRecord(
                session_id=sid_a,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="session_error",
                turn_seq=0,
                updated_at=t0_a,
            ),
            float(t0_a),
        )

        # 用例 B：T0 = now - 120s 产出 agent.say，随后 T0 + 1s 运行器写入本体 error
        t0_b = int(now_s - 120)
        reply_b_iso = datetime.fromtimestamp(float(t0_b), tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        sid_b = "core_runner_err_after_reply_002"
        content_b = (
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "user",
                            "timestamp": reply_b_iso,
                            "message": {"role": "user", "content": "turn 1"},
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "timestamp": reply_b_iso,
                            "message": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "partial reply"}],
                            },
                        }
                    ),
                ]
            )
            + "\n"
        )
        (proj / f"{sid_b}.jsonl").write_text(content_b, encoding="utf-8")
        os.utime(proj / f"{sid_b}.jsonl", (float(t0_b), float(t0_b)))
        mirror_b = tmp_path / "sessions" / "coreagent" / sid_b
        mirror_b.mkdir(parents=True)
        (mirror_b / "raw.jsonl").write_text(content_b, encoding="utf-8")
        os.utime(mirror_b / "raw.jsonl", (float(t0_b), float(t0_b)))
        _save_at(
            SessionOntologyRecord(
                session_id=sid_b,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="runner_failed_after_reply",
                turn_seq=1,
                updated_at=t0_b + 1,
            ),
            float(t0_b + 1),
        )

        # storage.list_sessions 在尚未被 record_reader 自愈前，也能正确区分 A 与 B
        storage_by_id = {
            s.session_id: s
            for s in storage.list_sessions(agent_type=AgentType.COREAGENT, limit=50)
        }
        assert storage_by_id[sid_a].status == SessionStatus.COMPLETED
        assert storage_by_id[sid_b].status == SessionStatus.ERROR

        # 复位 sid_a 本体回 error 以独立验证 record_reader + /api/workbench/sessions 自愈链路
        _save_at(
            SessionOntologyRecord(
                session_id=sid_a,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="session_error",
                turn_seq=0,
                updated_at=t0_a,
            ),
            float(t0_a),
        )
        cards = {c.session_id: c for c in record_reader.list_sessions(liveness={sid_a: False, sid_b: False})}
        assert cards[sid_a].status == "done"
        assert cards[sid_a].lifecycle_state == "completed"
        assert cards[sid_a].digest_stuck is None
        healed_a = store.get(sid_a)
        assert healed_a is not None
        assert healed_a.lifecycle_state == "completed"
        assert healed_a.summary == ""

        assert cards[sid_b].status == "error"
        assert cards[sid_b].lifecycle_state == "error"
        preserved_b = store.get(sid_b)
        assert preserved_b is not None
        assert preserved_b.lifecycle_state == "error"
        assert preserved_b.summary == "runner_failed_after_reply"

        # 再次复位 sid_a 本体回 error，验证 /api/workbench/sessions 端到端返回与自愈
        _save_at(
            SessionOntologyRecord(
                session_id=sid_a,
                agent_kernel="coreagent",
                lifecycle_state="error",
                summary="session_error",
                turn_seq=0,
                updated_at=t0_a,
            ),
            float(t0_a),
        )
        monkeypatch.setattr(tmux_sessions_service, "open_session_names", lambda: set())
        monkeypatch.setattr(coreagent_runner, "live_states", lambda: {})
        monkeypatch.setattr(workbench_groups, "local_ops_session_ids", lambda: set())
        monkeypatch.setattr(wb_route, "list_posts", lambda: [])
        monkeypatch.setattr(wb_route, "_dispatch_states_by_caller", lambda **_k: (set(), set()))
        monkeypatch.setattr(wb_route, "_observer_slots_state", lambda *_a: (False, False))
        monkeypatch.setattr(wb_route, "_keep_watching_only", lambda _sids: None)

        rows = {r["session_id"]: r for r in asyncio.run(wb_route.list_workbench_sessions())}
        assert rows[sid_a]["status"] == "done"
        assert rows[sid_a]["lifecycle_state"] == "completed"
        assert rows[sid_a]["digest_stuck"] is None
        assert store.get(sid_a).lifecycle_state == "completed"
        assert store.get(sid_a).summary == ""

        assert rows[sid_b]["status"] == "error"
        assert rows[sid_b]["lifecycle_state"] == "error"
        assert store.get(sid_b).lifecycle_state == "error"




