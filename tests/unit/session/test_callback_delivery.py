"""Unit tests for callback delivery ontological contracts, systemized delivery link,
and autonomous server queue patrol (Gate 1–4 verification).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from frago.server.services import session_observer, workbench_queue
from frago.server.services.workbench_queue_patrol_service import (
    WorkbenchQueuePatrolService,
)
from frago.session import async_dispatch, record_reader
from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

TEST_SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"


def _join_background_queue_threads(timeout: float = 5.0) -> None:
    """等后台注入线程收尾，别让它活过本用例。

    哪个环节出事：`try_auto_inject(sync=False)` 会起一条 `queue-inject-*` 守护线程去发送，
    用例一返回，pytest 就把这一轮的 monkeypatch 全撤了——包括把
    `session_observer.session_dir` 换回真身。线程还在跑，它随后调 `queue_dir()` 时就会沿
    `get_session_base_dir()` 落回 import 期算死的 `DEFAULT_SESSION_DIR`，也就是真人的
    `~/.frago/sessions`，在那里写 `workbench-queue-state.json.tmp*`。

    当事人看到什么现象：这不是用例失败，而是一条 `PytestUnhandledThreadExceptionWarning`——
    线程里的异常不会让测试红。当前由 `tests/conftest.py` 的守门人拦下那次写入并抛错，
    所以真人数据没被写脏；但这条通道确实通着，护栏一失效就重演 20260725 那次事故。

    注意 `FRAGO_HOME` 打桩对这条路无效：`get_session_base_dir()` 读的是 `FRAGO_SESSION_DIR`，
    所以夹具里两个都设，而这里等线程真正跑完，才是把窗口关死的那一下。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        leftover = [
            t
            for t in threading.enumerate()
            if t is not threading.current_thread()
            and (t.name.startswith("queue-inject-") or t.name.startswith("workbench-queue-patrol"))
        ]
        if not leftover:
            return
        for t in leftover:
            t.join(timeout=max(0.01, deadline - time.monotonic()))
    logger.warning(
        "仍有后台队列线程没能在 %.1fs 内收尾：%s",
        timeout,
        [t.name for t in threading.enumerate() if t.name.startswith("queue-inject-")],
    )


def _make_record(
    index: int,
    record_type: str,
    payload: dict[str, Any],
    group_id: str = "turn-01",
) -> UnifiedRecord:
    return UnifiedRecord(
        id=f"rec-{index}",
        session_id=TEST_SID,
        seq=index,
        ts=1000 + index,
        kind=record_type,  # type: ignore[arg-type]
        agent_path=[],
        group_id=group_id,
        payload=payload,
    )


def _ready_turn(turn_idx: int = 1) -> list[UnifiedRecord]:
    gid = f"turn-{turn_idx:02d}"
    return [
        _make_record(1, "user.say", {"text": "hello"}, group_id=gid),
        _make_record(2, "agent.say", {"text": "done"}, group_id=gid),
    ]


class TestCallbackDeliverySystemizedFixes:
    """Covers Gate 4 requirements and regression guards."""

    @pytest.fixture(autouse=True)
    def _setup_queue_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        workbench_queue.reset_runtime_state()
        monkeypatch.setattr(workbench_queue, "_sender_override", None)
        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        sessions_root = tmp_path / "sessions"
        monkeypatch.setattr(
            session_observer,
            "session_dir",
            lambda sid, family: sessions_root / family / sid,
        )
        # 会话库根目录另有环境变量：`get_session_base_dir()` 认的是 `FRAGO_SESSION_DIR`，
        # 不认 `FRAGO_HOME`。上面那个 `session_dir` 打桩只在用例活着时有效，后台线程
        # 跑过用例边界时就得靠这一条兜住。两处都设，路径才没有一条通向真人数据。
        monkeypatch.setenv("FRAGO_SESSION_DIR", str(sessions_root))
        monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "claude-code")
        monkeypatch.setattr(async_dispatch, "frago_home", lambda: tmp_path)
        WorkbenchQueuePatrolService.reset_instance()
        yield tmp_path
        # 收尾顺序要紧：先等后台线程跑完（此刻打桩还在），再撤状态。
        # 反过来做，线程就会在打桩撤掉之后才去算路径，那时只能落到真人目录。
        _join_background_queue_threads()
        workbench_queue.reset_runtime_state()

    def test_try_auto_inject_failure_returns_false_and_prepends_item(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1. 注入失败时，返回值不得为已送达，必须返回 injected: False 并退回队首。"""
        records = _ready_turn(1)
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        def mock_failing_send(_sid: str, _prompt: str, _cwd: str | None = None) -> None:
            raise RuntimeError("Connection to agent socket timed out after 180s")

        monkeypatch.setattr(workbench_queue, "_send_prompt", mock_failing_send)

        item = workbench_queue.enqueue(TEST_SID, text="回传结果", prompt="回传结果")
        assert len(workbench_queue.list_queue(TEST_SID)) == 1

        res = workbench_queue.try_auto_inject(TEST_SID, records=records, sync=True)
        assert res["injected"] is False
        assert res["delivered"] is False
        assert res["status"] == "failed"
        assert res["reason"] == "send_failed"
        assert "timed out" in str(res.get("error"))

        # 消息放回队首，未丢失
        remaining = workbench_queue.list_queue(TEST_SID)
        assert len(remaining) == 1
        assert remaining[0]["id"] == item["id"]

        # 本轮 stop 标记未被污染，不会阻碍后续正常注入
        assert TEST_SID not in workbench_queue._last_injected_turn

    def test_try_auto_inject_async_mode_distinguishes_delivering(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1b. sync=False 异步触发时，返回值必须区分「已受理/送达中」与「已送达」。"""
        records = _ready_turn(1)
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        send_barrier = threading.Event()

        def slow_send(_sid: str, _prompt: str, _cwd: str | None = None) -> None:
            send_barrier.wait(timeout=2.0)

        monkeypatch.setattr(workbench_queue, "_send_prompt", slow_send)
        workbench_queue.enqueue(TEST_SID, text="异步待投消息", prompt="异步待投消息")

        # 异步调用 try_auto_inject
        res = workbench_queue.try_auto_inject(TEST_SID, records=records, sync=False)
        try:
            assert res["injected"] is False  # 尚未真正送达，绝不能伪报 injected: True
            assert res["accepted"] is True
            assert res["delivering"] is True
            assert res["status"] == "delivering"
            assert res["reason"] == "delivering"
        finally:
            send_barrier.set()

    def test_watcher_delivery_failure_keeps_dispatch_job_failed_and_not_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2 & 3. 回传送达失败时，派发单不得记为 completed；worker_rc 为 0 但 delivery_state 为 failed。"""
        job = async_dispatch.AsyncDispatchJob(
            job_id="disp-failed-deliv-01",
            kind="worker",
            mode="new",
            caller_session_id=TEST_SID,
            caller_employee_id=None,
            caller_cwd="/repo",
            target_session_id="worker-sess-01",
            target_name="worker-1",
            employee_id=None,
            agent="claude",
            cwd="/repo",
            prompt="do task",
            task_summary="task",
        )
        job_file = async_dispatch.save_dispatch_job(job)

        # Worker 执行成功 (rc=0)
        monkeypatch.setattr(
            async_dispatch,
            "_execute_worker_job",
            lambda _j: (0, "worker finished cleanly", ""),
        )

        # 回传投递模拟失败
        monkeypatch.setattr(
            async_dispatch,
            "deliver_callback_to_session",
            lambda _sid, _prompt, cwd_hint=None: False,
        )

        final_job = async_dispatch.execute_dispatch_job(job_file)
        assert final_job is not None
        # 核心契约验证：两个维度彻底分离
        assert final_job.exit_code == 0
        assert final_job.delivery_state == "failed"
        assert final_job.status == "failed"  # 绝不能记为 completed！

    def test_server_autonomous_patrol_injects_ready_sessions_without_frontend_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """4. 服务端自驱巡检在零前端请求时把可注入的会话送出。"""
        records = _ready_turn(1)
        monkeypatch.setattr(
            record_reader,
            "read_records",
            lambda *_a, **_k: list(records),
        )
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        injected_prompts: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "_send_prompt",
            lambda _sid, prompt, _cwd: injected_prompts.append(prompt),
        )

        # 模拟外部跨进程/后台直接入队
        workbench_queue.enqueue(TEST_SID, text="跨进程后台回传", prompt="跨进程后台回传")

        # 启动自驱巡检服务，快速节拍 0.05s
        patrol_service = WorkbenchQueuePatrolService.get_instance(interval_seconds=0.05)

        async def _run() -> None:
            await patrol_service.start()
            assert patrol_service.is_running is True

            # 等待巡检自动发现并完成注入
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not injected_prompts:
                await asyncio.sleep(0.02)

            await patrol_service.stop()
            assert patrol_service.is_running is False

        import asyncio

        asyncio.run(_run())

        assert injected_prompts == ["跨进程后台回传"]
        assert workbench_queue.list_queue(TEST_SID) == []

    def test_server_patrol_respects_blocked_by_card(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5. 被交互卡挡住的会话不投递。"""
        card_turn: list[UnifiedRecord] = [
            _make_record(1, "user.say", {"text": "hello"}),
            _make_record(
                2,
                "agent.say",
                {"text": "```answer-needed-by-human\ntype: single-choice\n```"},
            ),
        ]
        monkeypatch.setattr(
            record_reader,
            "read_records",
            lambda *_a, **_k: list(card_turn),
        )
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        injected_prompts: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "_send_prompt",
            lambda _sid, prompt, _cwd: injected_prompts.append(prompt),
        )

        workbench_queue.enqueue(TEST_SID, text="卡片阻塞待发", prompt="卡片阻塞待发")

        # 触发一次巡检
        injected_sids = workbench_queue.patrol_active_queues(sync=True)
        assert injected_sids == []
        assert injected_prompts == []
        # 仍然留在队列等待
        assert len(workbench_queue.list_queue(TEST_SID)) == 1

    def test_concurrent_lock_prevents_duplicate_injection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """6. 并发巡检加 watcher 时跨进程注入锁互斥，不重复投递。"""
        records = _ready_turn(1)
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        injected_count = 0
        lock = threading.Lock()

        def counting_send(_sid: str, _prompt: str, _cwd: str | None = None) -> None:
            nonlocal injected_count
            with lock:
                injected_count += 1
            time.sleep(0.05)

        monkeypatch.setattr(workbench_queue, "_send_prompt", counting_send)
        workbench_queue.enqueue(TEST_SID, text="并发防重测试", prompt="并发防重测试")

        # 两个线程同时调用 try_auto_inject
        t1_res: dict[str, Any] = {}
        t2_res: dict[str, Any] = {}

        def _worker1():
            nonlocal t1_res
            t1_res = workbench_queue.try_auto_inject(TEST_SID, records=records, sync=True)

        def _worker2():
            nonlocal t2_res
            t2_res = workbench_queue.try_auto_inject(TEST_SID, records=records, sync=True)

        th1 = threading.Thread(target=_worker1)
        th2 = threading.Thread(target=_worker2)
        th1.start()
        th2.start()
        th1.join()
        th2.join()

        # 只有一个线程成功注入
        assert injected_count == 1
        results = [t1_res.get("injected"), t2_res.get("injected")]
        assert results.count(True) == 1
        assert results.count(False) == 1

    def test_watcher_writes_logs_to_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """3b. watcher 子进程的 stdout/stderr 写进日志文件，且父进程立即关闭文件句柄无泄漏。"""
        job = async_dispatch.AsyncDispatchJob(
            job_id="disp-log-test-01",
            kind="worker",
            mode="new",
            caller_session_id=TEST_SID,
            caller_employee_id=None,
            caller_cwd="/repo",
            target_session_id="worker-sess-log",
            target_name="worker-log",
            employee_id=None,
            agent="claude",
            cwd="/repo",
            prompt="do task",
            task_summary="task",
        )
        job_file = async_dispatch.save_dispatch_job(job)

        captured_kwargs: dict[str, Any] = {}

        def mock_popen(_cmd: list[str], **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        monkeypatch.setattr("subprocess.Popen", mock_popen)

        async_dispatch._spawn_detached_watcher(
            job_file,
            target_session_id="worker-sess-log",
        )

        assert "stdout" in captured_kwargs
        log_fp = captured_kwargs["stdout"]
        assert log_fp is not None
        assert log_fp is not subprocess.DEVNULL
        log_path = Path(log_fp.name)
        assert log_path.name == "disp-log-test-01.log"
        assert "logs" in log_path.parts
        # 验证父进程句柄已自动关闭，零泄漏（绝不需要手工 close 来掩盖）
        assert log_fp.closed is True

    def test_integrated_retry_cycle_without_mocking_deliver_callback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P2-1.1: 不 Mock deliver_callback_to_session，真实跑通 execute_dispatch_job 首次注入失败退回队首，
        经历 queued -> delivering -> queued，再由服务端巡检成功送达收敛为 delivered / completed。
        """
        records = _ready_turn(1)
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records))
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        job = async_dispatch.AsyncDispatchJob(
            job_id="disp-real-retry-01",
            kind="worker",
            mode="new",
            caller_session_id=TEST_SID,
            caller_employee_id=None,
            caller_cwd="/repo",
            target_session_id="worker-sess-retry",
            target_name="worker-retry",
            employee_id=None,
            agent="claude",
            cwd="/repo",
            prompt="do task",
            task_summary="task",
        )
        job_file = async_dispatch.save_dispatch_job(job)

        # Worker 执行成功 (rc=0)
        monkeypatch.setattr(
            async_dispatch,
            "_execute_worker_job",
            lambda _j: (0, "worker success output", ""),
        )

        failing = True

        def flaky_send(_sid: str, _prompt: str, _cwd: str | None = None) -> bool:
            if failing:
                raise RuntimeError("Transient driver socket busy")
            return True

        monkeypatch.setattr(workbench_queue, "_send_prompt", flaky_send)

        # 真实运行 execute_dispatch_job（通过 monkeypatch 短轮询窗口 0.15s 快速结束）
        orig_deliver = async_dispatch.deliver_callback_to_session

        def _quick_deliver(sid: str, prompt: str, **kwargs: Any) -> bool:
            kwargs["max_wait_s"] = 0.15
            kwargs["poll_interval_s"] = 0.05
            return orig_deliver(sid, prompt, **kwargs)

        monkeypatch.setattr(async_dispatch, "deliver_callback_to_session", _quick_deliver)

        first_run_job = async_dispatch.execute_dispatch_job(job_file)
        assert first_run_job is not None

        # 磁盘上的派发单真实经历跃迁：退回 queued，delivery_attempts 记录增加，且绝对不能被记为 completed！
        disk_job = async_dispatch.load_dispatch_job("disp-real-retry-01")
        assert disk_job is not None
        assert disk_job.delivery_state == "queued"
        assert disk_job.delivery_attempts >= 1
        assert disk_job.status != "completed"
        # 消息安全退回队首，未丢失
        q = workbench_queue.list_queue(TEST_SID)
        assert len(q) == 1
        assert "disp-real-retry-01" in q[0].get("text", "") or q[0].get("job_id") == "disp-real-retry-01"

        # 随后底层恢复正常，服务端自驱巡检介入，成功送达
        failing = False
        injected = workbench_queue.patrol_active_queues(sync=True)
        assert TEST_SID in injected
        assert workbench_queue.list_queue(TEST_SID) == []

        # 派发单自动收敛为 delivered / completed！
        final_disk_job = async_dispatch.load_dispatch_job("disp-real-retry-01")
        assert final_disk_job is not None
        assert final_disk_job.delivery_state == "delivered"
        assert final_disk_job.status == "completed"

    def test_concurrency_inflight_not_misjudged_as_delivered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P2-1.2: 并发竞态测试：巡检线程弹出消息正在执行耗时发送并最终失败退回队首期间，
        并发轮询的 watcher 绝不能仅凭 list_queue 暂时看不到条目就误判为 delivered。
        """
        records = _ready_turn(1)
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records))
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        job = async_dispatch.AsyncDispatchJob(
            job_id="disp-inflight-race-01",
            kind="worker",
            mode="new",
            caller_session_id=TEST_SID,
            caller_employee_id=None,
            caller_cwd="/repo",
            target_session_id="worker-sess-race",
            target_name="worker-race",
            employee_id=None,
            agent="claude",
            cwd="/repo",
            prompt="do race task",
            task_summary="task",
        )
        async_dispatch.save_dispatch_job(job)

        # 构造一条带 job_id 的回传报文
        cb_prompt = f'<frago-async-callback job_id="{job.job_id}">result</frago-async-callback>'
        item = workbench_queue.enqueue(TEST_SID, text=cb_prompt, prompt=cb_prompt, job_id=job.job_id)
        item_id = item["id"]

        in_flight_barrier = threading.Event()
        finish_failing_send = threading.Event()

        def slow_failing_send(_sid: str, _prompt: str, _cwd: str | None = None) -> bool:
            in_flight_barrier.set()
            finish_failing_send.wait(timeout=2.0)
            raise RuntimeError("Backend connection refused")

        monkeypatch.setattr(workbench_queue, "_send_prompt", slow_failing_send)

        # 启动后台线程执行 try_auto_inject 模拟巡检弹出条目并进入耗时发送
        patrol_thread = threading.Thread(
            target=lambda: workbench_queue.try_auto_inject(TEST_SID, records=records, sync=True),
            daemon=True,
        )
        patrol_thread.start()

        # 等待巡检线程已弹出 item 并在发送中
        assert in_flight_barrier.wait(timeout=1.0) is True

        # 验证此时队列中已看不到 item_id
        assert not any(it["id"] == item_id for it in workbench_queue.list_queue(TEST_SID))

        # 此时 watcher 进行轮询：断言 watcher 绝不误判为 delivered！
        receipt = workbench_queue.get_queue_delivery_receipt(TEST_SID)
        assert receipt.get("inflight_item_id") == item_id
        assert item_id not in (receipt.get("delivered_items") or [])

        # 让巡检发送失败并退回队首
        finish_failing_send.set()
        patrol_thread.join(timeout=1.0)

        # 验证消息已安全放回队首
        q_after = workbench_queue.list_queue(TEST_SID)
        assert len(q_after) == 1
        assert q_after[0]["id"] == item_id

        # 之后恢复正常发送，watcher 最终能真正送达并返回 True
        monkeypatch.setattr(workbench_queue, "_send_prompt", lambda _sid, _p, _c: True)
        delivered_ok = async_dispatch.deliver_callback_to_session(
            TEST_SID, cb_prompt, job_id=job.job_id, max_wait_s=1.0, poll_interval_s=0.05
        )
        assert delivered_ok is True

    def test_long_turn_no_timeout_and_historical_dedup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P2-1.3:
        1. 投喂确认秒级返回，不等待目标代理后续数分钟的长回合思考，绝不把消息重塞回队首；
        2. 历史幂等去重：当目标会话历史记录中已存在同 job_id 回传时，直接出队消纳，底层发送调用为 0，派发单同步收敛为 delivered。
        """
        records = _ready_turn(1)
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records))
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        send_called = 0

        def instant_submit_ok(_sid: str, _prompt: str, _cwd: str | None = None) -> bool:
            nonlocal send_called
            send_called += 1
            # 立即返回成功，代表输入已被空闲终端接收并落盘
            return True

        monkeypatch.setattr(workbench_queue, "_send_prompt", instant_submit_ok)

        # 1. 验证正常投递秒级确认且出队
        workbench_queue.enqueue(TEST_SID, text="一次性长任务", prompt="一次性长任务")
        res1 = workbench_queue.try_auto_inject(TEST_SID, records=records, sync=True)
        assert res1["injected"] is True
        assert res1["delivered"] is True
        assert workbench_queue.list_queue(TEST_SID) == []
        assert send_called == 1

        # 2. 幂等防重测试：创建包含该 job_id 的已有历史会话记录
        dedup_job_id = "disp-dedup-99"
        dedup_job = async_dispatch.AsyncDispatchJob(
            job_id=dedup_job_id,
            kind="worker",
            mode="new",
            caller_session_id=TEST_SID,
            caller_employee_id=None,
            caller_cwd="/repo",
            target_session_id="worker-sess-dedup",
            target_name="worker-dedup",
            employee_id=None,
            agent="claude",
            cwd="/repo",
            prompt="dedup task",
            task_summary="task",
            delivery_state="queued",
            status="running",
        )
        async_dispatch.save_dispatch_job(dedup_job)

        historical_records = list(records) + [
            _make_record(
                3,
                "user.say",
                {"text": f'<frago-async-callback job_id="{dedup_job_id}">cached</frago-async-callback>'},
                group_id="turn-02",
            ),
            _make_record(
                4,
                "agent.say",
                {"text": "Processed callback successfully"},
                group_id="turn-02",
            ),
        ]
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(historical_records))

        # 入队一条带有相同 job_id 的滞留条目（模拟历史死循环 bug 遗留在队列里的条目）
        workbench_queue.enqueue(
            TEST_SID,
            text=f'<frago-async-callback job_id="{dedup_job_id}">cached</frago-async-callback>',
            prompt=f'<frago-async-callback job_id="{dedup_job_id}">cached</frago-async-callback>',
            job_id=dedup_job_id,
        )
        assert len(workbench_queue.list_queue(TEST_SID)) == 1

        # 重置底层发送调用计数
        send_called = 0
        res2 = workbench_queue.try_auto_inject(TEST_SID, records=historical_records, sync=True)

        # 命中幂等防重：直接消费出队，底层发送次数为 0，派发单同步收敛为 delivered！
        assert res2["injected"] is True
        assert res2["delivered"] is True
        assert res2.get("deduped") is True
        assert res2.get("reason") == "deduped_already_present"
        assert send_called == 0  # 绝对未向终端二次灌水！
        assert workbench_queue.list_queue(TEST_SID) == []

        # 验证派发单在磁盘上已被安全收敛为 delivered
        reloaded_dedup = async_dispatch.load_dispatch_job(dedup_job_id)
        assert reloaded_dedup is not None
        assert reloaded_dedup.delivery_state == "delivered"

    def test_active_queue_index_zero_full_disk_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P1-1: 活跃队列索引机制确保 patrol_active_queues 运行时零全盘 glob 扫描。"""
        scan_count = 0
        orig_scan = workbench_queue.scan_persisted_queued_sessions

        def counting_scan():
            nonlocal scan_count
            scan_count += 1
            return orig_scan()

        monkeypatch.setattr(workbench_queue, "scan_persisted_queued_sessions", counting_scan)

        # 初始首次巡检（若索引不存在做唯一一次建索引）
        workbench_queue.patrol_active_queues(sync=True)
        assert scan_count == 1  # 唯一一次初始化扫盘

        # 后续无论巡检多少次，扫描全盘的计数恒定不再增加！
        for _ in range(5):
            workbench_queue.patrol_active_queues(sync=True)
        assert scan_count == 1  # 彻底杜绝每 2 秒遍历上万目录！

        # 当新消息通过 enqueue 入队时，自动加入轻量索引，无需全盘扫描即可被巡检捕获
        monkeypatch.setattr(workbench_queue, "_send_prompt", lambda _sid, _p, _c: True)
        records = _ready_turn(1)
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records))
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)

        workbench_queue.enqueue(TEST_SID, text="索引发现消息", prompt="索引发现消息")
        assert TEST_SID in workbench_queue._read_active_queues_index()

        injected = workbench_queue.patrol_active_queues(sync=True)
        assert TEST_SID in injected
        assert scan_count == 1  # 依然零全盘扫描！
        # 队列消费排空后，自动从轻量索引中移出
        assert TEST_SID not in workbench_queue._read_active_queues_index()

    def test_idempotent_dedup_deep_history_and_role_strictness(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试历史去重深度窗口（limit=500）与严格限定 user.say 角色。"""
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: False)
        send_count = 0

        def mock_send(_sid: str, _prompt: str, _cwd: str | None = None) -> bool:
            nonlocal send_count
            send_count += 1
            return True

        monkeypatch.setattr(workbench_queue, "_send_prompt", mock_send)

        # 场景 1：user.say 位于倒数第 120 条，后面跟 119 条 agent.say / tool.result
        deep_job_id = "disp-deep-120"
        records_deep: list[UnifiedRecord] = [
            _make_record(
                1,
                "user.say",
                {"text": f'<frago-async-callback job_id="{deep_job_id}">cached</frago-async-callback>'},
                group_id="turn-01",
            )
        ]
        for idx in range(2, 121):
            kind = "agent.say" if idx % 2 == 0 else "tool.result"
            records_deep.append(
                _make_record(
                    idx,
                    kind,
                    {"text": f"intermediate step {idx}"},
                    group_id="turn-01",
                )
            )
        assert len(records_deep) == 120

        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records_deep))
        cb_text_deep = f'<frago-async-callback job_id="{deep_job_id}">cached</frago-async-callback>'
        workbench_queue.enqueue(
            TEST_SID,
            text=cb_text_deep,
            prompt=cb_text_deep,
            job_id=deep_job_id,
        )
        assert len(workbench_queue.list_queue(TEST_SID)) == 1

        res1 = workbench_queue.try_auto_inject(TEST_SID, records=records_deep, sync=True)
        assert res1["injected"] is True
        assert res1["delivered"] is True
        assert res1.get("deduped") is True
        assert res1.get("reason") == "deduped_already_present"
        assert send_count == 0  # 命中深度去重，0 次发送
        assert workbench_queue.list_queue(TEST_SID) == []

        # 场景 2：会话记录中仅有 agent.say 与 tool.result 提及 callback（无 user.say 包含）
        agent_mention_job_id = "disp-agent-mention"
        records_agent_only: list[UnifiedRecord] = [
            _make_record(
                1,
                "user.say",
                {"text": "initial user command"},
                group_id="turn-01",
            ),
            _make_record(
                2,
                "tool.result",
                {"text": f'Dispatched job: <frago-async-callback job_id="{agent_mention_job_id}">pending</frago-async-callback>'},
                group_id="turn-01",
            ),
            _make_record(
                3,
                "agent.say",
                {"text": f'I received job info for <frago-async-callback job_id="{agent_mention_job_id}">'},
                group_id="turn-01",
            ),
        ]
        monkeypatch.setattr(record_reader, "read_records", lambda *_a, **_k: list(records_agent_only))
        cb_text_agent = f'<frago-async-callback job_id="{agent_mention_job_id}">real result</frago-async-callback>'
        workbench_queue.enqueue(
            TEST_SID,
            text=cb_text_agent,
            prompt=cb_text_agent,
            job_id=agent_mention_job_id,
        )
        assert len(workbench_queue.list_queue(TEST_SID)) == 1

        res2 = workbench_queue.try_auto_inject(TEST_SID, records=records_agent_only, sync=True)
        assert res2["injected"] is True
        assert res2["delivered"] is True
        assert not res2.get("deduped")
        assert send_count == 1  # 绝未误判为已送达，正常调用发送！
        assert workbench_queue.list_queue(TEST_SID) == []

    def test_unseeded_partial_index_triggers_one_time_bootstrap_merge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """存量索引未带 seeded=true 时，首次巡检触发唯一一次全盘存量扫描建索引并合并保留历史会话。"""
        sessions_root = tmp_path / "sessions"
        # 预置存量非空队列（会话 A）
        session_a_dir = sessions_root / "claude-code" / "session-a"
        session_a_dir.mkdir(parents=True, exist_ok=True)
        q_file_a = session_a_dir / "workbench-queue.json"
        q_file_a.write_text(
            json.dumps({
                "version": 1,
                "items": [
                    {"id": "item-a1", "text": "task a", "prompt": "task a", "created_at_ms": 1000}
                ],
            }),
            encoding="utf-8",
        )

        # 预置会话 B（若非空则合并保留）
        session_b_dir = sessions_root / "claude-code" / "session-b"
        session_b_dir.mkdir(parents=True, exist_ok=True)
        q_file_b = session_b_dir / "workbench-queue.json"
        q_file_b.write_text(
            json.dumps({
                "version": 1,
                "items": [
                    {"id": "item-b1", "text": "task b", "prompt": "task b", "created_at_ms": 1001}
                ],
            }),
            encoding="utf-8",
        )

        # 预置未带 seeded: true 的局部 active-workbench-queues.json
        index_file = sessions_root / "active-workbench-queues.json"
        index_file.write_text(
            json.dumps({
                "version": 1,
                "session_ids": ["session-b"],
            }),
            encoding="utf-8",
        )

        scan_count = 0
        orig_scan = workbench_queue.scan_persisted_queued_sessions

        def counting_scan():
            nonlocal scan_count
            scan_count += 1
            return orig_scan()

        monkeypatch.setattr(workbench_queue, "scan_persisted_queued_sessions", counting_scan)
        # 避免巡检直接把队列消费掉，以便观察索引与状态
        monkeypatch.setattr(workbench_queue, "is_session_busy", lambda _sid: True)

        # 首次调用巡检：触发 bootstrap 合并扫描
        workbench_queue.patrol_active_queues(sync=True)
        assert scan_count == 1

        # 验证索引中已扫入 session-a 且保留 session-b，并升级为 seeded: true
        sids, seeded = workbench_queue._read_active_queues_index_with_meta()
        assert "session-a" in sids
        assert "session-b" in sids
        assert seeded is True

        # 验证磁盘文件内容包含 "seeded": true
        disk_data = json.loads(index_file.read_text(encoding="utf-8"))
        assert disk_data.get("seeded") is True

        # 随后连续调用 3 次巡检，验证 scan_persisted_queued_sessions 零次额外调用
        for _ in range(3):
            workbench_queue.patrol_active_queues(sync=True)
        assert scan_count == 1
