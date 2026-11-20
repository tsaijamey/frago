"""Regression tests for 2026-11-20 ontology five-state cutover, bloodline ledger, error non-folding, monotonic turn_seq, and file anti-reset guardrails."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from frago.file_guard import ProtectedFileReadError, lkg_path_for


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
