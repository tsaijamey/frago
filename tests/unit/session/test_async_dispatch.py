"""Frago 原生非阻塞派发与跨内核会话流回投（async_dispatch）端到端单测。

覆盖四大支柱：
1. 跨 5 套 CLI Agent（claude / codex / opencode / agy / coreagent）及 WebUI 认领把手（FRAGO_LAUNCH_HANDLE）的调用方会话自识别；
2. `frago employee invoke` / `frago employee ask` 默认秒级非阻塞返回 `[dispatched]` 并在后台完成后自动回投 `<frago-async-callback>` 至父会话流；
3. Employee 会话内 `frago agent`（新建 Worker 与 `--resume` 续接已有 Worker）默认非阻塞返回 `[dispatched]` 并回投结果至 Employee 会话流（同时保证 Recipe 同步上下文隔离）；
4. 多跳级联屏障（Employee A -> 同侪 Employee B -> 下属 Worker W -> Employee B 汇总 -> 回投 Employee A）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import frago.cli.agent_command as agent_cli
import frago.cli.employee_commands as emp_cli
from frago.employee import EmployeeOntologyService, get_post, save_post
from frago.server.services import session_send, workbench_queue
from frago.session import async_dispatch, session_origin


@pytest.fixture()
def isolated_frago_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 FRAGO_HOME、员工目录、派发账本与会话关系账本。"""
    monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
    monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))
    monkeypatch.setenv("FRAGO_TEST_ALLOW_ASYNC_DISPATCH", "1")
    for k in (
        "CLAUDE_CODE_SESSION_ID",
        "ANTIGRAVITY_CONVERSATION_ID",
        "CODEX_THREAD_ID",
        "OPENCODE_SESSION_ID",
        "FRAGO_SESSION_ID",
        "FRAGO_LAUNCH_HANDLE",
        "FRAGO_CALLBACK_SESSION_ID",
        "FRAGO_EMPLOYEE_ID",
        "FRAGO_CURRENT_RUN",
        "FRAGO_EXECUTION_ID",
    ):
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setattr(
        session_origin,
        "LAUNCH_LEDGER",
        tmp_path / "sessions" / "launches.jsonl",
    )
    monkeypatch.setattr(
        session_origin,
        "PARENT_SCAN_CACHE",
        tmp_path / "sessions" / "parent-scan.json",
    )
    session_origin.clear_cache()
    for sub in ("data", "recipes", "books", "sessions", "employees"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_resolve_caller_session_id_across_all_five_cli_agents_and_launch_handles(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支柱 1：5 套 CLI Agent 环境变量与 WebUI 启动把手绑定均能准确解析出 caller_session_id。"""
    from frago.session import agy_store, codex_store, opencode_store

    env_cases = [
        ("CLAUDE_CODE_SESSION_ID", "claude-sess-101"),
        ("ANTIGRAVITY_CONVERSATION_ID", "agy-conv-202"),
        ("CODEX_THREAD_ID", "codex-thread-303"),
        ("OPENCODE_SESSION_ID", "ses_opencode_404"),
        ("FRAGO_SESSION_ID", "core_kernel_505"),
    ]
    for env_key, expected_sid in env_cases:
        for k, _ in env_cases:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv(env_key, expected_sid)
        assert async_dispatch.resolve_caller_session_id() == expected_sid

    for k, _ in env_cases:
        monkeypatch.delenv(k, raising=False)

    # WebUI 启动时 codex / opencode / agy 先注入 FRAGO_LAUNCH_HANDLE=webui-xxx，认领后通过 store 绑定还原真实会话 ID
    monkeypatch.setattr(
        codex_store,
        "get_binding",
        lambda h: "codex-claimed-999" if h == "webui-codex-handle" else None,
    )
    monkeypatch.setattr(
        opencode_store,
        "get_binding",
        lambda h: "ses_opencode_claimed_888" if h == "webui-opencode-handle" else None,
    )
    monkeypatch.setattr(
        agy_store,
        "get_binding",
        lambda h: "agy-claimed-777" if h == "webui-agy-handle" else None,
    )

    monkeypatch.setenv("FRAGO_LAUNCH_HANDLE", "webui-codex-handle")
    assert async_dispatch.resolve_caller_session_id() == "codex-claimed-999"

    monkeypatch.setenv("FRAGO_LAUNCH_HANDLE", "webui-opencode-handle")
    assert async_dispatch.resolve_caller_session_id() == "ses_opencode_claimed_888"

    monkeypatch.setenv("FRAGO_LAUNCH_HANDLE", "webui-agy-handle")
    assert async_dispatch.resolve_caller_session_id() == "agy-claimed-777"


def test_employee_invoke_and_ask_default_nonblocking_with_session_stream_callback(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支柱 2：`frago employee invoke` 与 `frago employee ask` 在会话中默认非阻塞返回 `[dispatched]`，
    后台完成后通过 `workbench_queue` + `session_send` 将 `<frago-async-callback>` 自动注入调用方员工会话流。
    """
    svc = EmployeeOntologyService()
    risk_rec, _ = svc.hire(
        "risk-observer",
        title="风险观察员",
        agent_kernel="claude",
        description="负责代理风险与脱敏巡检",
        work_scope="审查代理出口与仓库敏感信息",
    )
    dev_rec, _ = svc.hire(
        "frago-developer",
        title="frago开发专家",
        agent_kernel="agy",
        description="负责维护和开发 frago 核心代码",
        work_scope="管理 frago 架构重构、性能优化与测试验收",
    )
    caller_sid = "11111111-2222-3333-4444-555555555555"
    (isolated_frago_env / "sessions" / "claude-code" / caller_sid).mkdir(parents=True, exist_ok=True)
    workbench_queue.reset_runtime_state()
    risk_rec.active_session_ids.append(caller_sid)
    save_post(risk_rec)

    # 模拟当前处于风险观察员的 Claude Code 会话中
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", caller_sid)

    spawned_jobs: list[Path] = []
    monkeypatch.setattr(
        async_dispatch,
        "_async_spawner_override",
        lambda job_path: spawned_jobs.append(job_path),
    )

    delivered_callbacks: list[tuple[str, str]] = []

    def fake_send(session_id: str, text: str, *, cwd_hint: str | None = None):
        delivered_callbacks.append((session_id, text))
        return {"status": "ok", "session_id": session_id}

    monkeypatch.setattr(session_send, "send", fake_send)
    monkeypatch.setattr(workbench_queue, "is_session_busy", lambda sid: False)
    monkeypatch.setattr(
        workbench_queue,
        "detect_stop_turn_id",
        lambda sid: f"turn-stop-{len(delivered_callbacks) + 1}",
    )

    def fake_emp_turn(
        agent_kernel: str,
        prompt: str,
        *,
        cwd: str,
        timeout_s: float = 0.0,
        session_id: str | None = None,
    ) -> tuple[str, str, str]:
        return (
            session_id or "sess-dev-peer-801",
            "ok",
            "已完成派发链路非阻塞改造，168 项单测全部通过。",
        )

    monkeypatch.setattr(emp_cli, "_run_agent_turn_for_employee", fake_emp_turn)

    runner = CliRunner()
    # 1. 不带 --wait 调用 frago employee invoke -> 立即秒级返回 [dispatched]，且此时尚未阻塞执行子回合
    res = runner.invoke(
        emp_cli.employee_group,
        ["invoke", "frago-developer", "请优化会话派发链路为默认非阻塞回调"],
    )
    assert res.exit_code == 0, res.output
    assert "[dispatched]" in res.output
    assert "mode=employee_invoke" in res.output
    assert "employee_id=frago-developer" in res.output
    assert f"caller_session_id={caller_sid}" in res.output
    assert len(spawned_jobs) == 1
    assert delivered_callbacks == []  # 命令返回那一刻后台尚未回投，证明主命令零阻塞

    # 2. 推进后台 watcher 执行该任务单 -> 自动通过 workbench_queue + session_send 投递回 caller_sid
    completed_job = async_dispatch.execute_dispatch_job(spawned_jobs[0])
    assert completed_job is not None
    assert completed_job.status == "completed"
    assert len(delivered_callbacks) == 1
    cb_sid, cb_text = delivered_callbacks[0]
    assert cb_sid == caller_sid
    assert '<frago-async-callback kind="employee" mode="invoke"' in cb_text
    assert "frago-developer" in cb_text
    assert "已完成派发链路非阻塞改造，168 项单测全部通过。" in cb_text

    # 目标员工的 active_session_ids 与父子派发账本均已落盘
    dev_after = get_post("frago-developer")
    assert dev_after is not None
    assert completed_job.target_session_id in dev_after.active_session_ids

    # 3. 同样验证 frago employee ask 默认非阻塞 + 回投
    ask_res = runner.invoke(
        emp_cli.employee_group,
        ["ask", "frago-developer", "当前重构影响了哪些模块？"],
    )
    assert ask_res.exit_code == 0, ask_res.output
    assert "[dispatched]" in ask_res.output
    assert "mode=employee_ask" in ask_res.output
    assert len(spawned_jobs) == 2

    async_dispatch.execute_dispatch_job(spawned_jobs[1])
    assert len(delivered_callbacks) == 2
    assert '<frago-async-callback kind="employee" mode="ask"' in delivered_callbacks[1][1]


def test_employee_worker_dispatch_new_and_resume_nonblocking_with_callback(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支柱 3：Employee 会话中执行 `frago agent --prompt-file` 与 `frago agent --resume` 默认秒级返回 `[dispatched]`，
    后台完成后将 Worker 产出封装为 `<frago-async-callback kind="worker">` 投递回 Employee 会话流；
    而在 Recipe 同步上下文（`FRAGO_CURRENT_RUN`）中则保持同步执行。
    """
    svc = EmployeeOntologyService()
    emp_rec, _ = svc.hire(
        "frago-developer",
        title="frago开发专家",
        agent_kernel="claude",
        description="负责 frago 核心研发",
        work_scope="管理 frago 源码与测试",
    )
    emp_sid = "sess-emp-dev-main-001"
    emp_rec.active_session_ids.append(emp_sid)
    save_post(emp_rec)

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", emp_sid)

    spawned_jobs: list[Path] = []
    monkeypatch.setattr(
        async_dispatch,
        "_async_spawner_override",
        lambda job_path: spawned_jobs.append(job_path),
    )

    delivered_callbacks: list[tuple[str, str]] = []
    monkeypatch.setattr(
        async_dispatch,
        "_callback_sender_override",
        lambda sid, prompt, cwd: (delivered_callbacks.append((sid, prompt)) or True),
    )

    def fake_worker_sync(
        prompt_text: str,
        *,
        agent_type: str,
        session_id: str | None,
        native_session_id: bool,
        cwd: str,
        timeout: int,
        model: str | None = None,
        env_list: list[str] | None = None,
    ) -> tuple[str, str, str]:
        mode_tag = "RESUMED" if native_session_id else "NEW"
        return (
            session_id or "worker-sid-001",
            "ok",
            f"[{mode_tag}] 任务书已执行完毕，核查报告已写入 notebook.md。",
        )

    monkeypatch.setattr(agent_cli, "_run_worker_turn_sync", fake_worker_sync)
    monkeypatch.setattr(agent_cli, "should_use_ccr", lambda cfg, force=False: (False, None))

    task_md = isolated_frago_env / "task-brief.md"
    task_md.write_text("# 任务书\n请扫描 session 子系统并生成审计摘要", encoding="utf-8")

    runner = CliRunner()
    # 1. 新开 Worker：默认非阻塞返回 [dispatched]
    res_new = runner.invoke(
        agent_cli.agent,
        ["--prompt-file", str(task_md), "--agent-type", "claude"],
    )
    assert res_new.exit_code == 0, res_new.output
    assert "[dispatched]" in res_new.output
    assert "mode=worker_new" in res_new.output
    assert f"caller_session_id={emp_sid}" in res_new.output
    assert len(spawned_jobs) == 1

    job_new = async_dispatch.execute_dispatch_job(spawned_jobs[0])
    assert job_new is not None
    assert job_new.status == "completed"
    assert len(delivered_callbacks) == 1
    assert delivered_callbacks[0][0] == emp_sid
    assert '<frago-async-callback kind="worker" mode="new"' in delivered_callbacks[0][1]
    assert "[NEW] 任务书已执行完毕" in delivered_callbacks[0][1]

    # 2. 续接已有 Worker（--resume）：默认非阻塞返回 [dispatched]
    existing_worker_sid = job_new.target_session_id
    res_resume = runner.invoke(
        agent_cli.agent,
        ["--resume", existing_worker_sid, "--prompt-file", str(task_md), "--agent-type", "claude"],
    )
    assert res_resume.exit_code == 0, res_resume.output
    assert "[dispatched]" in res_resume.output
    assert "mode=worker_resume" in res_resume.output
    assert f"worker_session_id={existing_worker_sid}" in res_resume.output
    assert len(spawned_jobs) == 2

    job_resume = async_dispatch.execute_dispatch_job(spawned_jobs[1])
    assert job_resume is not None
    assert len(delivered_callbacks) == 2
    assert '<frago-async-callback kind="worker" mode="resume"' in delivered_callbacks[1][1]
    assert "[RESUMED] 任务书已执行完毕" in delivered_callbacks[1][1]

    # 3. Recipe 同步隔离：当 FRAGO_CURRENT_RUN 存在时，should_dispatch_worker_async 为 False
    monkeypatch.setenv("FRAGO_CURRENT_RUN", "recipe-run-001")
    assert (
        async_dispatch.should_dispatch_worker_async(
            emp_sid,
            wait_for_answer=False,
            force_async=False,
            dry_run=False,
        )
        is False
    )


def test_multihop_cascade_barrier_waits_for_child_worker_before_employee_callback(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支柱 4：多跳级联屏障（Employee A -> Peer Employee B -> Worker W -> Employee B -> Employee A）。
    当同侪员工 B 在其首轮中异步派发了下属 Worker W 时，盯梢员工 B 的 watcher 会等待 Worker W 完成并汇总后，
    才将最终结论回投给发起方员工 A，绝不会把员工 B 中间的 `[dispatched]` 过渡消息误当成最终结论回传给 A。
    """
    svc = EmployeeOntologyService()
    svc.hire("emp-a", title="员工A", agent_kernel="claude")
    svc.hire("emp-b", title="员工B", agent_kernel="agy")

    sid_a = "sess-emp-a-100"
    sid_b = "sess-emp-b-200"
    sid_w = "sess-worker-w-300"

    # 模拟员工 A 已向员工 B 发起了一次异步 invoke
    job_ab = async_dispatch.AsyncDispatchJob(
        job_id="disp-ab-001",
        kind="employee",
        mode="invoke",
        caller_session_id=sid_a,
        caller_employee_id="emp-a",
        caller_cwd=str(isolated_frago_env),
        target_session_id=sid_b,
        target_name="emp-b",
        employee_id="emp-b",
        agent="agy",
        cwd=str(isolated_frago_env),
        prompt="请核查并修复架构问题",
        task_summary="请核查并修复架构问题",
        status="running",
    )
    job_ab_path = async_dispatch.save_dispatch_job(job_ab)

    # 模拟员工 B 在首轮执行时，没有直接干活，而是向自己的下属 Worker W 发起了一张子异步任务单，
    # 然后员工 B 的首轮立即返回了 "[dispatched] 已派发给 Worker W"
    def fake_emp_b_turn(
        agent_kernel: str,
        prompt: str,
        *,
        cwd: str,
        timeout_s: float = 0.0,
        session_id: str | None = None,
    ) -> tuple[str, str, str]:
        child_job = async_dispatch.AsyncDispatchJob(
            job_id="disp-bw-002",
            kind="worker",
            mode="new",
            caller_session_id=sid_b,
            caller_employee_id="emp-b",
            caller_cwd=cwd,
            target_session_id=sid_w,
            target_name=sid_w,
            employee_id=None,
            agent="claude",
            cwd=cwd,
            prompt="执行具体代码修复",
            task_summary="执行具体代码修复",
            status="completed",
            exit_code=0,
            output="【员工B复核后的最终结论】Worker W 已完成全部 3 处模块重构并通过回归测试。",
        )
        async_dispatch.save_dispatch_job(child_job)
        # 同时写入员工 B 会话在收到 Worker 回传后的最终 assistant 结论记录
        b_dir = isolated_frago_env / "sessions" / "agy" / sid_b
        b_dir.mkdir(parents=True, exist_ok=True)
        (b_dir / "raw.jsonl").write_text(
            json.dumps(
                {
                    "step_index": 0,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-11-06T15:00:00Z",
                    "content": "[dispatched] 已派发 Worker W 执行",
                },
                ensure_ascii=False,
            )
            + "\n"
            + json.dumps(
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-11-06T15:02:00Z",
                    "content": "【员工B复核后的最终结论】Worker W 已完成全部 3 处模块重构并通过回归测试。",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return sid_b, "ok", "[dispatched] 已派发 Worker W 执行"

    monkeypatch.setattr(emp_cli, "_run_agent_turn_for_employee", fake_emp_b_turn)

    # 让 wait_for_pending_child_dispatches 能感知到子任务并提取最终结论
    orig_has_pending = async_dispatch.has_pending_async_work
    check_calls = {"n": 0}

    def fake_has_pending(session_id: str) -> bool:
        if session_id == sid_b:
            check_calls["n"] += 1
            # 第一次检查时模拟子任务刚收口，触发级联提取
            return check_calls["n"] == 1
        return orig_has_pending(session_id)

    monkeypatch.setattr(async_dispatch, "has_pending_async_work", fake_has_pending)
    monkeypatch.setattr(workbench_queue, "is_session_busy", lambda sid: False)

    delivered_to_a: list[tuple[str, str]] = []
    monkeypatch.setattr(
        async_dispatch,
        "_callback_sender_override",
        lambda sid, prompt, cwd: (delivered_to_a.append((sid, prompt)) or True),
    )

    finished = async_dispatch.execute_dispatch_job(job_ab_path)
    assert finished is not None
    assert finished.status == "completed"
    assert len(delivered_to_a) == 1
    assert delivered_to_a[0][0] == sid_a
    assert "【员工B复核后的最终结论】Worker W 已完成全部 3 处模块重构并通过回归测试。" in delivered_to_a[0][1]


def test_worker_resume_supersedes_running_job_and_suppresses_bogus_failed_callback(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归（disp-0c1150941a47 / disp-580a86cdc45c）：当首轮 Worker 派发仍在运行时，
    员工因人类追加指令对同一 worker_session_id 发起 --resume 追派，前序派发单必须被标记为
    superseded，且前序 watcher 被抢占退出后严禁向父会话发送虚假的 status="failed" 回传报文。
    """
    caller_sid = "98dae23a-483c-45a1-b335-5464cb994225"
    worker_sid = "core_167b99d9aafc4e2f9a7401c02f69c989"

    spawned_jobs: list[Path] = []
    monkeypatch.setattr(
        async_dispatch,
        "_async_spawner_override",
        lambda job_path: spawned_jobs.append(job_path),
    )

    delivered_callbacks: list[tuple[str, str]] = []
    monkeypatch.setattr(
        async_dispatch,
        "_callback_sender_override",
        lambda sid, prompt, cwd: (delivered_callbacks.append((sid, prompt)) or True),
    )

    # 1. 首轮派发（mode="new"），此时处于 running 状态尚未完成
    job1 = async_dispatch.dispatch_worker_turn_async(
        mode="new",
        caller_session_id=caller_sid,
        caller_cwd=str(isolated_frago_env),
        target_session_id=worker_sid,
        agent="coreagent",
        cwd=str(isolated_frago_env),
        prompt="# 任务书：排查 3D 桌宠语音识别",
        task_summary="# 任务书：排查 3D 桌宠语音识别",
    )
    assert job1.status == "running"

    # 2. 首轮执行期间，对同一 worker_sid 发起追派（mode="resume"）
    job2 = async_dispatch.dispatch_worker_turn_async(
        mode="resume",
        caller_session_id=caller_sid,
        caller_cwd=str(isolated_frago_env),
        target_session_id=worker_sid,
        agent="coreagent",
        cwd=str(isolated_frago_env),
        prompt="【用户紧急追加红线指令】修完别直接装机重启",
        task_summary="【用户紧急追加红线指令】修完别直接装机重启",
        resume=worker_sid,
    )

    # 追派单落盘时，前序仍在 running 的 job1 已被标记为 superseded
    reloaded_job1 = async_dispatch.load_dispatch_job(job1.job_id)
    assert reloaded_job1 is not None
    assert reloaded_job1.status == "superseded"
    assert reloaded_job1.superseded_by == job2.job_id

    # 模拟 job1 的后台 watcher 在运行中被抢占（即便底层返回 error，也必须在收尾时识别 superseded 并静默退出）
    def fake_worker_sync(
        prompt_text: str,
        *,
        agent_type: str,
        session_id: str | None,
        native_session_id: bool,
        cwd: str,
        timeout: int,
        model: str | None = None,
        env_list: list[str] | None = None,
    ) -> tuple[str, str, str]:
        if not native_session_id:
            return worker_sid, "error", "frago-core: 会话记录 .../core_167b99d9.jsonl"
        return worker_sid, "ok", "已完成 Whisper 防噪修复并通过 24 项单元测试。"

    monkeypatch.setattr(agent_cli, "_run_worker_turn_sync", fake_worker_sync)

    res1 = async_dispatch.execute_dispatch_job(spawned_jobs[0])
    assert res1 is not None
    assert res1.status == "superseded"
    assert delivered_callbacks == []

    res2 = async_dispatch.execute_dispatch_job(spawned_jobs[1])
    assert res2 is not None
    assert res2.status == "completed"
    assert len(delivered_callbacks) == 1
    assert f'job_id="{job2.job_id}"' in delivered_callbacks[0][1]
    assert 'status="completed"' in delivered_callbacks[0][1]


def test_tmux_core_process_marks_previous_run_superseded_without_killing_new_pane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 TmuxCoreProcess 启动同名新轮次时，会向旧 run_dir 写入 superseded 标记并更新 .active_run，
    使旧实例 is_alive() 立即变为 False，且旧实例 wait() 退出时不会误杀新轮次的 tmux 窗格。
    """
    from frago.agent_driver import coreagent_pane_host as pane_host

    monkeypatch.setenv("FRAGO_COREAGENT_PANES_DIR", str(tmp_path / "panes"))
    killed_targets: list[str] = []

    def fake_subprocess_run(argv: list[str], **_kwargs: Any):
        if len(argv) >= 3 and argv[0] == "tmux" and argv[1] == "kill-session":
            killed_targets.append(argv[-1])

        class _Res:
            returncode = 0
            stdout = "12345\n"
            stderr = ""

        return _Res()

    monkeypatch.setattr(pane_host.subprocess, "run", fake_subprocess_run)

    sid = "core_167b99d9aafc4e2f9a7401c02f69c989"
    proc1 = pane_host.TmuxCoreProcess(
        session_id=sid,
        cmd=["frago-core"],
        cwd=str(tmp_path),
        env={},
        mode="oneshot",
        prompt_text="turn 1",
    )
    assert proc1.is_superseded() is False
    assert proc1.is_alive() is True

    # 同一 session_id 启动第二轮 TmuxCoreProcess，抢占同名窗格
    proc2 = pane_host.TmuxCoreProcess(
        session_id=sid,
        cmd=["frago-core"],
        cwd=str(tmp_path),
        env={},
        mode="oneshot",
        prompt_text="turn 2",
    )
    assert proc1.is_superseded() is True
    assert proc1.is_alive() is False
    assert proc1.returncode == 130
    assert proc2.is_superseded() is False
    assert proc2.is_alive() is True

    kills_before_wait = len(killed_targets)
    rc1 = proc1.wait(timeout=0.5)
    assert rc1 == 130
    # proc1 已被抢占取代，wait() 退出时绝不可调用 _kill_tmux_quietly 误杀 proc2 的窗格
    assert len(killed_targets) == kills_before_wait

    proc1.cleanup_runtime_dir()
    # proc1 清理自身目录时，不能删掉指向 proc2 的 .active_run 登记文件
    assert pane_host.active_run_marker_path(sid).is_file()
    proc2.cleanup_runtime_dir()
    assert not pane_host.active_run_marker_path(sid).is_file()


def test_employee_role_env_isolation_and_builtin_worker_rule(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """修复 1（问题 1 · P0）：数字员工会话必须注入 FRAGO_AGENT_ROLE=employee 与 FRAGO_EMPLOYEE_ID，
    且 builtin-session-start-worker-role 仅匹配 FRAGO_AGENT_ROLE == 'worker' 且无 FRAGO_EMPLOYEE_ID。
    """
    # 1. sanitize_child_env 针对 employee 与 worker 的角色变量隔离
    emp_env = async_dispatch.sanitize_child_env(
        {"FRAGO_AGENT_ROLE": "worker", "PATH": "/usr/bin"},
        target_session_id="sess-emp-1",
        target_employee_id="lenovo",
    )
    assert emp_env["FRAGO_AGENT_ROLE"] == "employee"
    assert emp_env["FRAGO_EMPLOYEE_ID"] == "lenovo"
    assert emp_env["FRAGO_SESSION_ID"] == "sess-emp-1"

    worker_env = async_dispatch.sanitize_child_env(
        {"FRAGO_AGENT_ROLE": "employee", "FRAGO_EMPLOYEE_ID": "lenovo", "PATH": "/usr/bin"},
        target_session_id="sess-worker-1",
        target_employee_id=None,
    )
    assert "FRAGO_EMPLOYEE_ID" not in worker_env
    assert worker_env.get("FRAGO_AGENT_ROLE") != "employee"

    # 2. _run_agent_turn_for_employee 向 SessionLauncher 传递 FRAGO_AGENT_ROLE=employee 与 FRAGO_EMPLOYEE_ID
    captured_env: dict[str, str] = {}

    class _FakeLauncher:
        def run(self, prompt: str, **kwargs: Any):
            captured_env.update(kwargs.get("env") or {})

            class _Res:
                status = "ok"
                text = "done"

            return _Res()

    import frago.agent_driver as ad_mod

    monkeypatch.setattr(ad_mod, "SessionLauncher", _FakeLauncher)
    emp_cli._run_agent_turn_for_employee(
        "agy",
        "check apexp",
        cwd=str(isolated_frago_env),
        session_id="pre-handle-1",
        employee_id="lenovo",
    )
    assert captured_env.get("FRAGO_AGENT_ROLE") == "employee"
    assert captured_env.get("FRAGO_EMPLOYEE_ID") == "lenovo"

    # 3. builtin-rules.json 中的 builtin-session-start-worker-role 仅匹配 worker 且排除 FRAGO_EMPLOYEE_ID
    rules_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "frago"
        / "resources"
        / "hook"
        / "builtin-rules.json"
    )
    rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
    worker_rule = next(
        r for r in rules_data["rules"] if r["id"] == "builtin-session-start-worker-role"
    )
    assert worker_rule["match"]["type"] == "all_of"
    clauses = worker_rule["match"]["clauses"]
    assert any(
        c.get("type") == "not"
        and c.get("clause", {}).get("type") == "env_ne"
        and c.get("clause", {}).get("name") == "FRAGO_AGENT_ROLE"
        and c.get("clause", {}).get("value") == "worker"
        for c in clauses
    )
    assert any(
        c.get("type") == "not"
        and c.get("clause", {}).get("type") == "env_exists"
        and c.get("clause", {}).get("name") == "FRAGO_EMPLOYEE_ID"
        for c in clauses
    )


def test_agy_claimed_session_id_dynamically_updates_dispatch_job_and_error_message_fails_fast(
    isolated_frago_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """修复 2（问题 2 · P0）：当 agy 认领绑定原生 conversation_id 时，立即动态回写 AsyncDispatchJob.target_session_id；
    当子会话遭遇 SYSTEM ERROR_MESSAGE 异常终止时，派发单收口为 status='failed' 并回投 status='failed' 报文。
    """
    from frago.session import agy_store

    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(isolated_frago_env / "agy_app"))
    svc = EmployeeOntologyService()
    svc.hire("lenovo", title="Lenovo专员", agent_kernel="agy")

    caller_sid = "c8ba0e28-c613-4839-8513-77a88bd17952"
    pre_handle = "c3c907bf-abfa-43ad-a5c2-7136bcf51d81"
    claimed_cid = "3c6325da-af04-4597-bbbc-a6b15538423e"

    job = async_dispatch.AsyncDispatchJob(
        job_id="disp-d11ea754712f",
        kind="employee",
        mode="invoke",
        caller_session_id=caller_sid,
        caller_employee_id="personal-assistant",
        caller_cwd=str(isolated_frago_env),
        target_session_id=pre_handle,
        target_name="lenovo",
        employee_id="lenovo",
        agent="agy",
        cwd=str(isolated_frago_env),
        prompt="推进三张 Jira 卡",
        task_summary="推进三张 Jira 卡",
        status="running",
    )
    job_path = async_dispatch.save_dispatch_job(job)

    # 模拟在回合运行期间 agy_store.put_binding 认领了真实会话 ID，断言磁盘上的派发单立即同步更新
    def fake_emp_turn_with_claim_and_error(
        agent_kernel: str,
        prompt: str,
        *,
        cwd: str,
        timeout_s: float = 0.0,
        session_id: str | None = None,
        employee_id: str | None = None,
    ) -> tuple[str, str, str]:
        assert session_id == pre_handle
        assert employee_id == "lenovo"
        agy_store.put_binding(pre_handle, claimed_cid, cwd)
        mid_disk = async_dispatch.load_dispatch_job(job_path)
        assert mid_disk is not None
        assert mid_disk.target_session_id == claimed_cid
        return (
            claimed_cid,
            "error",
            "UNAUTHENTICATED (code 401): Request had invalid authentication credentials.",
        )

    monkeypatch.setattr(emp_cli, "_run_agent_turn_for_employee", fake_emp_turn_with_claim_and_error)

    delivered_callbacks: list[tuple[str, str]] = []
    monkeypatch.setattr(
        async_dispatch,
        "_callback_sender_override",
        lambda sid, prompt, cwd: (delivered_callbacks.append((sid, prompt)) or True),
    )

    finished = async_dispatch.execute_dispatch_job(job_path)
    assert finished is not None
    assert finished.target_session_id == claimed_cid
    assert finished.exit_code == 1
    assert finished.status == "failed"
    assert "UNAUTHENTICATED (code 401)" in finished.error

    assert len(delivered_callbacks) == 1
    cb_sid, cb_text = delivered_callbacks[0]
    assert cb_sid == caller_sid
    assert f'session_id="{claimed_cid}"' in cb_text
    assert 'status="failed"' in cb_text
    assert "UNAUTHENTICATED (code 401)" in cb_text


