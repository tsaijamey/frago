"""5 内核统一 TurnSubmit Hook 搭便车、<=5500 字符结构化降级、原子认领防双投与 REST 接口测试。"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from frago.cli import agy_hook
from frago.cli.session_commands import session_group
from frago.server.services import session_observer, workbench_queue
from frago.session import async_dispatch, record_reader
from frago.session.unified_record import UnifiedRecord

TEST_SID = "550e8400-e29b-41d4-a716-446655440099"


@pytest.fixture(autouse=True)
def _isolated_inbox_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workbench_queue.reset_runtime_state()
    monkeypatch.setattr(workbench_queue, "_sender_override", None)
    monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
    sessions_root = tmp_path / "sessions"
    monkeypatch.setenv("FRAGO_SESSION_DIR", str(sessions_root))
    monkeypatch.setattr(
        session_observer,
        "session_dir",
        lambda sid, family: sessions_root / family / sid,
    )
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "claude-code")
    monkeypatch.setattr(async_dispatch, "frago_home", lambda: tmp_path)
    yield tmp_path
    workbench_queue.reset_runtime_state()


def _make_queued_job(
    job_id: str,
    *,
    caller_sid: str = TEST_SID,
    snippet: str = "worker completed",
    report_file: str = "/tmp/report.md",
    task_summary: str = "后台任务",
    delivery_state: str = "queued",
    status: str = "delivering",
    updated_at_override: str | None = None,
) -> async_dispatch.AsyncDispatchJob:
    job = async_dispatch.AsyncDispatchJob(
        job_id=job_id,
        kind="worker",
        mode="new",
        caller_session_id=caller_sid,
        caller_employee_id=None,
        caller_cwd="/repo",
        target_session_id=f"target-{job_id}",
        target_name=f"worker-{job_id}",
        employee_id=None,
        agent="claude",
        cwd="/repo",
        prompt="do task",
        task_summary=task_summary,
        status=status,
        exit_code=0,
        delivery_state=delivery_state,
        worker_finished_at="2026-11-27T00:00:00+00:00",
        output=snippet,
        report_file=report_file,
    )
    job_path = async_dispatch.save_dispatch_job(job)
    if updated_at_override is not None:
        raw = json.loads(job_path.read_text(encoding="utf-8"))
        raw["updated_at"] = updated_at_override
        job_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        job.updated_at = updated_at_override
    async_dispatch.register_active_callback_caller(caller_sid)
    return job


class TestSessionCallbackClaimCLI:
    """`frago session callback-claim` CLI 原子认领、防双投、<=5500 降级与失败回退。"""

    def test_for_hook_silent_when_empty_or_unresolved(self) -> None:
        runner = CliRunner()
        res_unresolved = runner.invoke(session_group, ["callback-claim", "--for-hook"])
        assert res_unresolved.exit_code == 0
        assert res_unresolved.output == ""

        res_empty = runner.invoke(
            session_group,
            ["callback-claim", "--for-hook", "--session-id", TEST_SID],
        )
        assert res_empty.exit_code == 0
        assert res_empty.output == ""

    def test_atomic_claim_and_anti_double_delivery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_queued_job("disp-hook-01", snippet="结论一：检查通过", report_file="/tmp/r1.md")
        _make_queued_job("disp-hook-02", snippet="结论二：构建完成", report_file="/tmp/r2.md")
        monkeypatch.setenv("FRAGO_SESSION_ID", TEST_SID)

        runner = CliRunner()
        res1 = runner.invoke(session_group, ["callback-claim", "--for-hook"])
        assert res1.exit_code == 0
        out = res1.output
        assert '<frago-async-callbacks count="2" delivery="turn-submit-hitchhike" priority="background-after-human">' in out
        assert "【优先主线声明】" in out
        assert "disp-hook-01" in out
        assert "disp-hook-02" in out
        assert out.strip().endswith("</frago-async-callbacks>")

        # 本体状态已收敛为 delivered + hook_piggyback + completed
        for jid in ("disp-hook-01", "disp-hook-02"):
            j = async_dispatch.load_dispatch_job(jid)
            assert j is not None
            assert j.delivery_state == "delivered"
            assert j.delivery_channel == "hook_piggyback"
            assert j.status == "completed"

        # 二次认领绝不双投
        res2 = runner.invoke(session_group, ["callback-claim", "--for-hook"])
        assert res2.exit_code == 0
        assert res2.output == ""

    def test_budget_degradation_under_5500_chars_preserves_closing_tags(self) -> None:
        huge_snippet = "X" * 3500
        for idx in range(1, 7):
            _make_queued_job(
                f"disp-huge-{idx:02d}",
                snippet=f"第{idx}条：{huge_snippet}",
                report_file=f"/tmp/huge-{idx:02d}.md",
                task_summary=f"超长报告 {idx}",
            )

        runner = CliRunner()
        res = runner.invoke(
            session_group,
            ["callback-claim", "--for-hook", "--session-id", TEST_SID, "--max-chars", "5500"],
        )
        assert res.exit_code == 0
        payload = res.output.strip()
        assert len(payload) <= 5500
        assert payload.startswith('<frago-async-callbacks count="6" delivery="turn-submit-hitchhike"')
        assert payload.endswith("</frago-async-callbacks>")
        for idx in range(1, 7):
            assert f"disp-huge-{idx:02d}" in payload
            assert f"/tmp/huge-{idx:02d}.md" in payload

    def test_stdout_write_failure_rolls_back_to_queued(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from frago.cli import session_commands

        _make_queued_job("disp-rollback-01")

        class _BrokenStdout:
            def write(self, _s: str) -> int:
                raise OSError("broken pipe")

            def flush(self) -> None:
                pass

        monkeypatch.setattr(session_commands.sys, "stdout", _BrokenStdout())
        session_commands.callback_claim_cmd.callback(
            for_hook=True,
            max_chars=5500,
            session_id=TEST_SID,
            json_output=False,
        )
        reloaded = async_dispatch.load_dispatch_job("disp-rollback-01")
        assert reloaded is not None
        assert reloaded.delivery_state == "queued"
        assert reloaded.status == "delivering"


class TestBuiltinRuleAndFiveKernelHooks:
    """5 内核统一 TurnSubmit 规则、agy_hook、opencode frago-hook.js 与 coreagent env 覆盖。"""

    def test_builtin_rules_has_user_prompt_submit_hitchhike(self) -> None:
        rules_path = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "frago"
            / "resources"
            / "hook"
            / "builtin-rules.json"
        )
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        matches = [r for r in data.get("rules", []) if r.get("id") == "builtin-prompt-async-callback-hitchhike"]
        assert len(matches) == 1
        rule = matches[0]
        assert rule["event"] == "UserPromptSubmit"
        assert rule["action"] == {
            "type": "run_command_and_inject_stdout",
            "command": ["session", "callback-claim", "--for-hook"],
            "execute_on_user_prompt": True,
        }

    @pytest.mark.parametrize(
        "harness_args,extra_event",
        [
            ([], {}),
            (["--harness", "codex"], {"turn_id": "codex-turn-001"}),
        ],
        ids=["claude_or_coreagent", "codex"],
    )
    def test_real_frago_core_engine_executes_callback_claim_with_session_id(
        self,
        tmp_path: Path,
        harness_args: list[str],
        extra_event: dict[str, Any],
    ) -> None:
        """P0-1 端到端集成测试：真实 frago-core --engine 在 UserPromptSubmit 上透传 FRAGO_SESSION_ID 执行认领且零指针泄漏。"""
        import sys

        from frago.init.hook_binary import get_bundled_binary_path

        binary = get_bundled_binary_path()
        if not binary.exists():
            pytest.skip(f"bundled frago-core binary not found: {binary}")

        repo_root = Path(__file__).resolve().parents[3]
        src_dir = repo_root / "src"
        builtin_rules_src = src_dir / "frago" / "resources" / "hook" / "builtin-rules.json"

        fake_home = tmp_path / "home"
        frago_dir = fake_home / ".frago"
        (frago_dir / "hook").mkdir(parents=True, exist_ok=True)
        shutil.copy2(builtin_rules_src, frago_dir / "hook" / "builtin-rules.json")

        # Wrap current checkout's python CLI as `frago` on PATH so frago-core spawns THIS repo's code.
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        frago_wrapper = fake_bin / "frago"
        frago_wrapper.write_text(
            "#!/bin/sh\n"
            f'export PYTHONPATH="{src_dir}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
            f'exec "{sys.executable}" -m frago.cli.main "$@"\n',
            encoding="utf-8",
        )
        frago_wrapper.chmod(0o755)

        probe_sid = "real-engine-probe-001"
        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        env["FRAGO_HOME"] = str(frago_dir)
        env["FRAGO_REVIEW_DISABLE"] = "1"
        env["FRAGO_ALLOW_CHECKOUT_CLI"] = "1"
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
        # Deliberately remove FRAGO_SESSION_ID so frago-core MUST forward event.session_id.
        env.pop("FRAGO_SESSION_ID", None)
        env.pop("CLAUDE_CODE_SESSION_ID", None)

        def _invoke_engine(prompt_text: str) -> dict[str, Any]:
            ev = {
                "session_id": probe_sid,
                "hook_event_name": "UserPromptSubmit",
                "prompt": prompt_text,
                **extra_event,
            }
            proc = subprocess.run(
                [str(binary), "--engine", *harness_args],
                input=json.dumps(ev) + "\n",
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(proc.stdout.strip()) if proc.stdout.strip() else {}

        # 1) 无待认领回执时：零指针噪音泄漏、不注入回调信封
        resp_empty = _invoke_engine("普通提问，无待认领回执")
        ctx_empty = (resp_empty.get("hookSpecificOutput") or {}).get("additionalContext") or ""
        assert "session callback-claim --for-hook" not in ctx_empty
        assert "<frago-async-callbacks" not in ctx_empty

        # 2) 在隔离 FRAGO_HOME 下写入一条 queued 回执
        dispatches_dir = frago_dir / "sessions" / "async_dispatches"
        dispatches_dir.mkdir(parents=True, exist_ok=True)
        job_id = "disp-real-engine-01"
        job_payload = async_dispatch.AsyncDispatchJob(
            job_id=job_id,
            kind="worker",
            mode="new",
            caller_session_id=probe_sid,
            caller_employee_id=None,
            caller_cwd="/repo",
            target_session_id="target-real-01",
            target_name="worker-real-01",
            employee_id=None,
            agent="claude",
            cwd="/repo",
            prompt="do task",
            task_summary="真实引擎集成核验",
            status="delivering",
            exit_code=0,
            delivery_state="queued",
            worker_finished_at="2026-11-27T00:00:00+00:00",
            output="真实 frago-core 透传成功",
            report_file="/tmp/real-engine-report.md",
        ).to_dict()
        (dispatches_dir / f"{job_id}.json").write_text(
            json.dumps(job_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (dispatches_dir / ".active-callback-callers.json").write_text(
            json.dumps({"seeded": True, "callers": [probe_sid]}),
            encoding="utf-8",
        )

        # 3) 首次 UserPromptSubmit：真实执行认领并注入 <frago-async-callbacks>，零指针噪音
        resp_claimed = _invoke_engine("主线新提问")
        ctx_claimed = (resp_claimed.get("hookSpecificOutput") or {}).get("additionalContext") or ""
        assert "【可查】`session callback-claim --for-hook`" not in ctx_claimed
        assert '<frago-async-callbacks count="1" delivery="turn-submit-hitchhike"' in ctx_claimed
        assert job_id in ctx_claimed
        assert "真实 frago-core 透传成功" in ctx_claimed

        saved = json.loads((dispatches_dir / f"{job_id}.json").read_text(encoding="utf-8"))
        assert saved["delivery_state"] == "delivered"
        assert saved["delivery_channel"] == "hook_piggyback"
        assert saved["status"] == "completed"

        # 4) 第二次 UserPromptSubmit：不重复投递且无指针噪音
        resp_second = _invoke_engine("继续下一步")
        ctx_second = (resp_second.get("hookSpecificOutput") or {}).get("additionalContext") or ""
        assert "【可查】`session callback-claim --for-hook`" not in ctx_second
        assert "<frago-async-callbacks" not in ctx_second

    def test_agy_hook_pre_invocation_hitchhikes_and_strips_stale_pointer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agy_cid = "82d53e1b-fe99-4d8a-888c-42c4c1936473"
        t_path = tmp_path / "agy-transcript.jsonl"
        t_path.write_text(
            json.dumps({"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>继续</USER_REQUEST>"})
            + "\n",
            encoding="utf-8",
        )
        _make_queued_job("disp-agy-hook-01", caller_sid=agy_cid, snippet="agy 后台任务完成")

        monkeypatch.setattr(
            agy_hook,
            "_call_engine",
            lambda _payload: {
                "hookSpecificOutput": {
                    "additionalContext": (
                        "【可查】`session callback-claim --for-hook`: 规则说明\n"
                        "【必守】保留正常规则"
                    )
                }
            },
        )
        payload = {
            "conversationId": agy_cid,
            "transcriptPath": str(t_path),
            "workspacePaths": [str(tmp_path)],
        }
        monkeypatch.setattr(agy_hook.sys, "stdin", io.StringIO(json.dumps(payload)))

        captured: list[str] = []
        monkeypatch.setattr(agy_hook.click, "echo", lambda msg: captured.append(str(msg)))

        rc = agy_hook.run("PreInvocation")
        assert rc == 0
        out = json.loads(captured[0])
        steps = out.get("injectSteps") or []
        assert len(steps) == 1
        eph = steps[0]["ephemeralMessage"]
        assert "【可查】`session callback-claim --for-hook`" not in eph
        assert "【必守】保留正常规则" in eph
        assert '<frago-async-callbacks count="1" delivery="turn-submit-hitchhike"' in eph
        assert "disp-agy-hook-01" in eph

        reloaded = async_dispatch.load_dispatch_job("disp-agy-hook-01")
        assert reloaded is not None
        assert reloaded.delivery_state == "delivered"

        # 同一会话第二次 PreInvocation 不会重复注入
        captured.clear()
        monkeypatch.setattr(agy_hook.sys, "stdin", io.StringIO(json.dumps(payload)))
        agy_hook.run("PreInvocation")
        out2 = json.loads(captured[0])
        steps2 = out2.get("injectSteps") or []
        assert len(steps2) == 1
        assert "<frago-async-callbacks" not in steps2[0]["ephemeralMessage"]

    def test_opencode_frago_hook_js_hitchhikes_and_strips_pointer(self, tmp_path: Path) -> None:
        node = shutil.which("node")
        if not node:
            pytest.skip("node not available in test environment")

        _make_queued_job("disp-oc-hook-01", caller_sid="ses_opencode_test1")

        hook_js = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "frago"
            / "resources"
            / "opencode"
            / "frago-hook.js"
        )
        stub_engine = tmp_path / "stub-core.sh"
        stub_engine.write_text(
            "#!/bin/sh\n"
            'printf \'{"hookSpecificOutput":{"additionalContext":"【可查】`session callback-claim --for-hook`: old\\\\n保留规则"}}\'\n',
            encoding="utf-8",
        )
        stub_engine.chmod(0o755)

        stub_launcher = tmp_path / "stub-frago.sh"
        stub_launcher.write_text(
            "#!/bin/sh\n"
            'printf \'<frago-async-callbacks count="1" delivery="turn-submit-hitchhike">ok-%s</frago-async-callbacks>\' "$5"\n',
            encoding="utf-8",
        )
        stub_launcher.chmod(0o755)

        driver = tmp_path / "run.mjs"
        driver.write_text(
            f'import {{ FragoHookPlugin }} from {json.dumps(hook_js.as_uri())};\n'
            'const hooks = await FragoHookPlugin({ directory: "/tmp" });\n'
            'const output = { parts: [{ type: "text", text: "请回答" }] };\n'
            'await hooks["chat.message"]({ sessionID: "ses_opencode_test1", model: { providerID: "x", modelID: "y" } }, output);\n'
            'console.log(JSON.stringify(output));\n',
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["FRAGO_HOOK_BINARY"] = str(stub_engine)
        env["FRAGO_LAUNCHER"] = str(stub_launcher)

        proc = subprocess.run([node, str(driver)], env=env, capture_output=True, text=True, check=True)
        parsed = json.loads(proc.stdout.strip())
        text = parsed["parts"][0]["text"]
        assert "【可查】`session callback-claim --for-hook`" not in text
        assert '<frago-async-callbacks count="1" delivery="turn-submit-hitchhike">ok-ses_opencode_test1</frago-async-callbacks>' in text
        assert "保留规则" in text
        assert "请回答" in text

    def test_opencode_frago_hook_js_tolerates_stdin_epipe_on_fast_exit(self, tmp_path: Path) -> None:
        node = shutil.which("node")
        if not node:
            pytest.skip("node not available in test environment")

        hook_js = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "frago"
            / "resources"
            / "opencode"
            / "frago-hook.js"
        )
        stub_engine = tmp_path / "stub-core-fast-exit.sh"
        stub_engine.write_text(
            "#!/bin/sh\n"
            "exec 0<&-\n"
            'printf \'{"hookSpecificOutput":{"additionalContext":"快速退出仍保留规则"}}\'\n',
            encoding="utf-8",
        )
        stub_engine.chmod(0o755)

        driver = tmp_path / "run-epipe.mjs"
        driver.write_text(
            f'import {{ FragoHookPlugin }} from {json.dumps(hook_js.as_uri())};\n'
            'const hooks = await FragoHookPlugin({ directory: "/tmp" });\n'
            'const output = { parts: [{ type: "text", text: "X".repeat(262144) }] };\n'
            'await hooks["chat.message"]({ sessionID: "ses_opencode_epipe", model: { providerID: "x", modelID: "y" } }, output);\n'
            'console.log(JSON.stringify({ ok: output.parts[0].text.includes("快速退出仍保留规则") }));\n',
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["FRAGO_HOOK_BINARY"] = str(stub_engine)

        proc = subprocess.run([node, str(driver)], env=env, capture_output=True, text=True, check=True)
        parsed = json.loads(proc.stdout.strip())
        assert parsed["ok"] is True

    def test_coreagent_runner_sets_frago_session_id_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from frago.server.services import coreagent_runner

        captured_env: dict[str, str] = {}

        class _FakeProc:
            pid = 99999
            stdin = io.StringIO()
            stdout = io.StringIO("")

            def poll(self) -> int | None:
                return 0

        def _fake_popen(cmd: list[str], **kwargs: Any) -> _FakeProc:
            captured_env.update(kwargs.get("env") or {})
            return _FakeProc()

        monkeypatch.setenv("FRAGO_SESSION_ID", "stale-parent-sid")
        monkeypatch.setattr(coreagent_runner, "_should_use_tmux", lambda: False)
        monkeypatch.setattr(
            coreagent_runner,
            "build_command",
            lambda *_a, **_k: ["frago-core"],
        )
        monkeypatch.setattr(coreagent_runner.subprocess, "Popen", _fake_popen)
        sess = coreagent_runner._Session(
            session_id="core_envtest001",
            cwd="/tmp",
            title=None,
            profile_id=None,
            surface=None,
            unattended=False,
        )
        with sess.lock:
            coreagent_runner._spawn(sess)
            sess.closed = True
            sess.pending.put_nowait(coreagent_runner._WAKE)
        for t in (sess.reader, sess.feeder, sess.janitor):
            if t is not None:
                t.join(timeout=1.0)
        assert captured_env.get("FRAGO_SESSION_ID") == "core_envtest001"


class TestCallbackInboxRestAndStaleRecovery:
    """只读与触发 REST 接口 + 60s 僵尸 delivering 状态自动回收。"""

    def test_stale_delivering_callback_recovered_to_queued(self) -> None:
        stale_ts = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
        _make_queued_job(
            "disp-stale-01",
            delivery_state="delivering",
            status="delivering",
            updated_at_override=stale_ts,
        )
        recovered = async_dispatch.recover_stale_delivering_callbacks(TEST_SID, stale_after_s=60.0)
        assert recovered == ["disp-stale-01"]
        reloaded = async_dispatch.load_dispatch_job("disp-stale-01")
        assert reloaded is not None
        assert reloaded.delivery_state == "queued"

    def test_workbench_callback_inbox_routes_and_drain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from frago.server.app import create_app

        client = TestClient(create_app(), client=("127.0.0.1", 50000))
        _make_queued_job("disp-rest-01", snippet="REST 摘要", task_summary="REST 任务")

        turn_records = [
            UnifiedRecord(
                id="r1",
                session_id=TEST_SID,
                seq=1,
                ts=1001,
                kind="user.say",
                agent_path=[],
                group_id="g1",
                payload={"text": "hello"},
            ),
            UnifiedRecord(
                id="r2",
                session_id=TEST_SID,
                seq=2,
                ts=1002,
                kind="agent.say",
                agent_path=[],
                group_id="g1",
                payload={"text": "done"},
            ),
        ]
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(turn_records))
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        sent: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "_send_prompt",
            lambda _sid, prompt, _cwd=None: sent.append(prompt) or True,
        )

        resp_get = client.get(f"/api/workbench/sessions/{TEST_SID}/callback-inbox")
        assert resp_get.status_code == 200
        body = resp_get.json()
        assert body["sid"] == TEST_SID
        assert body["count"] == 1
        assert body["blocked_reason"] is None
        assert body["items"][0]["job_id"] == "disp-rest-01"

        # 调 drain 路由时把 job 的 worker_finished_at 置为足够久远以通过默认防抖
        j = async_dispatch.load_dispatch_job("disp-rest-01")
        assert j is not None
        j.worker_finished_at = "2026-11-27T00:00:00+00:00"
        async_dispatch.save_dispatch_job(j)

        resp_drain = client.post(f"/api/workbench/sessions/{TEST_SID}/callback-inbox/drain")
        assert resp_drain.status_code == 200
        drain_body = resp_drain.json()
        assert drain_body["delivered"] is True
        assert drain_body["delivered_job_ids"] == ["disp-rest-01"]
        assert drain_body["items"] == []
        assert len(sent) == 1
        assert "disp-rest-01" in sent[0]

    def test_callback_inbox_drain_distinguishes_auto_debounce_and_manual_immediate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P1-1：POST /callback-inbox/drain 默认遵守防抖窗并合批，显式 ?immediate=true 则跳过防抖立即投递。"""
        import time
        from datetime import UTC, datetime

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from frago.server.routes import workbench as workbench_route
        from frago.server.services import callback_inbox_dispatcher, workbench_queue
        from frago.session import record_reader

        app = FastAPI()
        app.include_router(workbench_route.router, prefix="/api")
        client = TestClient(app)

        records = [
            {"id": "r1", "seq": 1, "kind": "user.say", "agent_path": [], "payload": {"text": "go"}},
            {"id": "r2", "seq": 2, "kind": "agent.say", "agent_path": [], "payload": {"text": "ok"}, "group_id": "g1"},
        ]
        monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "claude")
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records))
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)
        monkeypatch.setattr(async_dispatch, "CALLBACK_INBOX_DEBOUNCE_MS", 220)

        sent: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "_send_prompt",
            lambda _sid, prompt, _cwd=None: sent.append(prompt) or True,
        )

        # 1. 两个并发刚完成的子任务陆续唤醒默认 /drain（immediate=False）
        j1 = _make_queued_job("disp-rest-db-1", snippet="one", task_summary="task one")
        j1.worker_finished_at = datetime.now(UTC).isoformat()
        async_dispatch.save_dispatch_job(j1)
        resp1 = client.post(f"/api/workbench/sessions/{TEST_SID}/callback-inbox/drain")
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert body1["delivered"] is False
        assert body1["reason"] == "debouncing"
        assert body1["scheduled_retry_ms"] >= 20
        assert sent == []

        time.sleep(0.06)
        j2 = _make_queued_job("disp-rest-db-2", snippet="two", task_summary="task two")
        j2.worker_finished_at = datetime.now(UTC).isoformat()
        async_dispatch.save_dispatch_job(j2)
        resp2 = client.post(f"/api/workbench/sessions/{TEST_SID}/callback-inbox/drain")
        assert resp2.status_code == 200
        assert resp2.json()["reason"] == "debouncing"
        assert sent == []

        # 等待防抖定时器成熟，两次完成应合并成单条 count="2" 投递
        deadline = time.monotonic() + 3.0
        while not sent and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(sent) == 1
        assert '<frago-async-callbacks count="2" delivery="idle-batch"' in sent[0]
        assert "disp-rest-db-1" in sent[0]
        assert "disp-rest-db-2" in sent[0]

        # 2. 人工显式 immediate=true 跳过防抖窗立即投递
        j3 = _make_queued_job("disp-rest-imm-3", snippet="three", task_summary="task three")
        j3.worker_finished_at = datetime.now(UTC).isoformat()
        async_dispatch.save_dispatch_job(j3)
        resp_imm = client.post(
            f"/api/workbench/sessions/{TEST_SID}/callback-inbox/drain?immediate=true"
        )
        assert resp_imm.status_code == 200
        imm_body = resp_imm.json()
        assert imm_body["delivered"] is True
        assert imm_body["delivered_job_ids"] == ["disp-rest-imm-3"]
        assert len(sent) == 2
        callback_inbox_dispatcher.cancel_debounced_callback_drain(TEST_SID)
