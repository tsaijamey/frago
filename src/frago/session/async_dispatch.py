"""Frago 原生非阻塞派发与跨内核会话流回投引擎 (Async Dispatch & Session Callback)。

设计目标：
1. 调用方身份自识别：屏蔽 5 套 CLI Agent（claude / codex / opencode / agy / coreagent）环境变量差异，
   自动识别发起命令的父会话 ID（``caller_session_id``）。
2. 默认秒级非阻塞回执：``frago employee invoke/ask`` 与 Employee 会话发起的 ``frago agent`` / ``frago agent send``
   默认不阻塞当前 CLI 工具调用，秒级返回 ``[dispatched]`` 回执并立即退出 0。
3. 后台独立守护盯梢与多跳屏障：由脱离父进程会话组的后台 watcher 进程执行目标会话回合；
   若目标会话（如同侪员工 B）在回合内又异步派发了下属 Worker，则自动等待子派发收口后再提取最终结论。
4. 跨内核会话流回投：通过 ``workbench_queue`` + ``session_send`` 将结构化回传报文投递回发起方会话流，
   在发起方回合空闲时自动唤醒新回合。
"""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.employee.store import frago_home
from frago.file_guard import atomic_write_text
from frago.ontology import (
    ActionContractError,
    build_claim_callback_inbox_contract,
    build_finalize_dispatch_job_contract,
    build_record_callback_delivery_outcome_contract,
    ontological_action,
)
from frago.session.report_offload import (
    current_next_seq,
    extract_latest_substantive_assistant_output,
    extract_task_interval_report,
)
from frago.session.self_id import (
    SESSION_IDENTITY_ENV,
    _resolve_bound_session_id,
    resolve_self,
)

# 测试钩子：允许单测拦截后台进程拉起与回投动作
_async_spawner_override: Callable[[Path], None] | None = None
_callback_sender_override: Callable[[str, str, str | None], bool] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dispatch_store_dir() -> Path:
    """异步派发任务账本目录：``~/.frago/sessions/async_dispatches``。"""
    d = frago_home() / "sessions" / "async_dispatches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dispatch_logs_dir() -> Path:
    """异步派发 watcher 日志目录：``~/.frago/logs/async_dispatches``。"""
    d = frago_home() / "logs" / "async_dispatches"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclasses.dataclass
class AsyncDispatchJob:
    """单次异步派发任务记录。"""

    job_id: str
    kind: str  # "employee" | "worker" | "drive_send"
    mode: str  # "invoke" | "ask" | "new" | "resume" | "send"
    caller_session_id: str
    caller_employee_id: str | None
    caller_cwd: str | None
    target_session_id: str
    target_name: str | None
    employee_id: str | None
    agent: str
    cwd: str
    prompt: str
    task_summary: str
    resume: str | None = None
    model: str | None = None
    profile_id: str | None = None
    timeout: int | None = None
    env_list: list[str] = dataclasses.field(default_factory=list)
    status: str = "pending"  # "pending" | "running" | "delivering" | "completed" | "failed" | "superseded"
    turn_seq: int = 0
    superseded_by: str | None = None
    watcher_pid: int | None = None
    exit_code: int = 0
    output: str = ""
    error: str = ""
    report_file: str | None = None
    report_total_chars: int | None = None
    report_truncated: bool = False
    delivery_state: str = "queued"  # "queued" | "delivering" | "delivered" | "failed"
    delivery_channel: str | None = None  # "idle_batch" | "hook_piggyback"
    delivery_attempts: int = 0
    delivery_error: str | None = None
    worker_finished_at: str | None = None
    delivered_at: str | None = None
    created_at: str = dataclasses.field(default_factory=_utc_now)
    updated_at: str = dataclasses.field(default_factory=_utc_now)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AsyncDispatchJob:
        fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in fields}
        if "delivery_state" not in filtered and "status" in data:
            st = str(data.get("status") or "").strip().lower()
            if st == "completed":
                filtered["delivery_state"] = "delivered"
            elif st in {"failed", "superseded", "cancelled"}:
                filtered["delivery_state"] = "failed"
            elif st in {"pending", "running", "delivering"}:
                filtered["delivery_state"] = "queued"
        return cls(**filtered)


def save_dispatch_job(job: AsyncDispatchJob) -> Path:
    """持久化异步派发任务单（fsync 原子写盘）。"""
    job.updated_at = _utc_now()
    path = dispatch_store_dir() / f"{job.job_id}.json"
    atomic_write_text(
        path,
        json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n",
        save_lkg=False,
    )
    return path


def load_dispatch_job(job_id_or_path: str | Path) -> AsyncDispatchJob | None:
    """读取异步派发任务单。"""
    path = (
        Path(job_id_or_path)
        if isinstance(job_id_or_path, Path) or str(job_id_or_path).endswith(".json")
        else dispatch_store_dir() / f"{job_id_or_path}.json"
    )
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return AsyncDispatchJob.from_dict(data)
    except Exception:
        return None
    return None


_RECORD_DELIVERY_OUTCOME_CONTRACT = build_record_callback_delivery_outcome_contract()
_FINALIZE_DISPATCH_JOB_CONTRACT = build_finalize_dispatch_job_contract()
_CLAIM_CALLBACK_INBOX_CONTRACT = build_claim_callback_inbox_contract()

_ACTIVE_CALLBACK_CALLERS_FILENAME = ".active-callback-callers.json"
_ACTIVE_CALLBACK_CALLERS_LOCK_FILENAME = ".active-callback-callers.lock"
_CALLBACK_CLAIM_LOCKS_GUARD = threading.Lock()
_CALLBACK_CLAIM_THREAD_LOCKS: dict[str, threading.Lock] = {}
CALLBACK_INBOX_DEBOUNCE_MS = 400
CALLBACK_DELIVERING_STALE_S = 60.0
CALLBACK_HOOK_MAX_CHARS = 5500


def _iso_to_epoch_ms(raw: str | None) -> int | None:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return None


def _safe_lock_token(session_id: str) -> str:
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in (session_id or "default"))


@contextlib.contextmanager
def _flock_path(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


@contextlib.contextmanager
def callback_claim_lock(caller_session_id: str) -> Iterator[None]:
    """跨线程 + 跨进程 OS 级排他锁：保护同一发起方会话的 CallbackInbox 认领与回滚。"""
    key = (caller_session_id or "").strip() or "_default"
    with _CALLBACK_CLAIM_LOCKS_GUARD:
        tlock = _CALLBACK_CLAIM_THREAD_LOCKS.get(key)
        if tlock is None:
            tlock = threading.Lock()
            _CALLBACK_CLAIM_THREAD_LOCKS[key] = tlock
    lock_path = dispatch_store_dir() / f".callback-claim-{_safe_lock_token(key)}.lock"
    with tlock, _flock_path(lock_path):
        yield


def _read_active_callback_callers_raw() -> tuple[set[str], bool]:
    index_path = dispatch_store_dir() / _ACTIVE_CALLBACK_CALLERS_FILENAME
    if not index_path.is_file():
        return set(), False
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return set(), False
        raw_callers = data.get("callers") or []
        callers = {str(c).strip() for c in raw_callers if isinstance(c, str) and c.strip()}
        return callers, bool(data.get("seeded"))
    except Exception:
        return set(), False


def _write_active_callback_callers_raw(callers: set[str], *, seeded: bool = True) -> None:
    index_path = dispatch_store_dir() / _ACTIVE_CALLBACK_CALLERS_FILENAME
    payload = {
        "version": 1,
        "seeded": seeded,
        "callers": sorted(c for c in callers if c),
    }
    atomic_write_text(
        index_path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        save_lkg=False,
    )


def _rebuild_active_callback_callers() -> set[str]:
    callers: set[str] = set()
    for job in list_dispatch_jobs(active_only=False):
        if job.status != "delivering":
            continue
        ds = (getattr(job, "delivery_state", "queued") or "queued").strip().lower()
        if ds in ("queued", "delivering") and job.caller_session_id:
            callers.add(job.caller_session_id)
    return callers


def register_active_callback_caller(caller_session_id: str) -> None:
    """将待投递回执的发起方会话登记到可重建轻索引 ``.active-callback-callers.json``。"""
    sid = (caller_session_id or "").strip()
    if not sid:
        return
    lock_path = dispatch_store_dir() / _ACTIVE_CALLBACK_CALLERS_LOCK_FILENAME
    with _flock_path(lock_path):
        callers, seeded = _read_active_callback_callers_raw()
        if not seeded:
            callers |= _rebuild_active_callback_callers()
        if sid not in callers or not seeded:
            callers.add(sid)
            _write_active_callback_callers_raw(callers, seeded=True)


def unregister_active_callback_caller(caller_session_id: str) -> None:
    """将已无可投递回执的发起方会话移出 ``.active-callback-callers.json``。"""
    sid = (caller_session_id or "").strip()
    if not sid:
        return
    lock_path = dispatch_store_dir() / _ACTIVE_CALLBACK_CALLERS_LOCK_FILENAME
    with _flock_path(lock_path):
        callers, seeded = _read_active_callback_callers_raw()
        if not seeded:
            callers |= _rebuild_active_callback_callers()
        if sid in callers or not seeded:
            callers.discard(sid)
            _write_active_callback_callers_raw(callers, seeded=True)


def list_active_callback_callers() -> set[str]:
    """读取存在待消化或投递中回执的发起方会话集合（未建索引时自动自愈重建一次）。"""
    callers, seeded = _read_active_callback_callers_raw()
    if seeded:
        return callers
    lock_path = dispatch_store_dir() / _ACTIVE_CALLBACK_CALLERS_LOCK_FILENAME
    with _flock_path(lock_path):
        callers, seeded = _read_active_callback_callers_raw()
        if seeded:
            return callers
        rebuilt = _rebuild_active_callback_callers()
        _write_active_callback_callers_raw(rebuilt, seeded=True)
        return rebuilt


def _refresh_caller_callback_index(caller_session_id: str) -> None:
    pending = list_callback_inbox_jobs(caller_session_id, states=("queued", "delivering"))
    if pending:
        register_active_callback_caller(caller_session_id)
    else:
        unregister_active_callback_caller(caller_session_id)


def list_callback_inbox_jobs(
    caller_session_id: str,
    *,
    states: tuple[str, ...] = ("queued",),
) -> list[AsyncDispatchJob]:
    """``CallbackInbox`` 权威视图投影：直接由 ``AsyncDispatchJob`` 账本投影，零影子状态机。

    只投影已结束后台执行进入 ``status == "delivering"``（或历史未收口的 queued/delivering 单据，
    严格排除仍在跑的 ``pending`` / ``running`` 以及终态 ``completed`` / ``failed`` / ``superseded`` /
    ``cancelled``）。
    """
    sid = (caller_session_id or "").strip()
    if not sid:
        return []
    allowed = {s.strip().lower() for s in states}
    matched: list[AsyncDispatchJob] = []
    for job in list_dispatch_jobs(caller_session_id=sid, active_only=False):
        st = (job.status or "").strip().lower()
        if st != "delivering":
            continue
        ds = (getattr(job, "delivery_state", "queued") or "queued").strip().lower()
        if ds not in allowed:
            continue
        matched.append(job)
    matched.sort(
        key=lambda j: (
            j.worker_finished_at or j.updated_at or j.created_at,
            j.created_at,
            j.job_id,
        )
    )
    return matched


@ontological_action(_CLAIM_CALLBACK_INBOX_CONTRACT)
def claim_callback_inbox(
    caller_session_id: str,  # noqa: ARG001 — 契约谓词校验 caller_session_id
    delivery_channel: str,
    job_ids: list[str],
    *,
    prior_states: Mapping[str, str],  # noqa: ARG001 — 契约谓词校验已持久化态
    has_human_next_task: bool = False,  # noqa: ARG001 — 契约谓词校验三类优先级硬闸
    blocked_by_card: bool = False,  # noqa: ARG001
    is_session_busy: bool = False,  # noqa: ARG001
    enqueue_to_next_task: bool = False,  # noqa: ARG001 — 物理分轨硬不变量
) -> list[str]:
    """挂载 Ring 3 ``claim_callback_inbox`` 契约护栏的原子批量认领动作（``queued → delivering``）。"""
    claimed: list[str] = []
    for raw_jid in job_ids:
        jid = str(raw_jid).strip()
        job = load_dispatch_job(jid)
        if job is None:
            raise ActionContractError(f"Dispatch job '{jid}' does not exist; cannot claim callback.")
        cur_ds = (getattr(job, "delivery_state", "queued") or "queued").strip().lower()
        record_callback_delivery_outcome(
            jid,
            from_state="queued",
            to_state="delivering",
            prior_delivery_state=cur_ds,
        )
        updated = load_dispatch_job(jid)
        if updated is not None:
            updated.delivery_channel = delivery_channel
            save_dispatch_job(updated)
        claimed.append(jid)
    return claimed


def recover_stale_delivering_callbacks(
    caller_session_id: str,
    *,
    stale_after_s: float = CALLBACK_DELIVERING_STALE_S,
) -> list[str]:
    """对超时停留在 ``delivering``（进程崩毁/卡死）的回执执行安全自愈退回 ``queued``。"""
    now_ms = int(time.time() * 1000)
    threshold_ms = int(max(1.0, stale_after_s) * 1000)
    recovered: list[str] = []
    for job in list_callback_inbox_jobs(caller_session_id, states=("delivering",)):
        updated_ms = _iso_to_epoch_ms(job.updated_at)
        if updated_ms is None or (now_ms - updated_ms) < threshold_ms:
            continue
        record_callback_delivery_outcome(
            job.job_id,
            from_state="delivering",
            to_state="queued",
            reason=f"Recovered stale delivering state after {int(stale_after_s)}s",
            prior_delivery_state="delivering",
        )
        recovered.append(job.job_id)
    return recovered


def claim_ready_callbacks_for_session(
    caller_session_id: str,
    *,
    delivery_channel: str,
    has_human_next_task: bool = False,
    blocked_by_card: bool = False,
    is_session_busy: bool = False,
    debounce_ms: int = 0,
    stale_after_s: float = CALLBACK_DELIVERING_STALE_S,
) -> list[AsyncDispatchJob]:
    """在跨进程 ``flock`` 保护下原子认领当前发起方会话就绪的 ``CallbackInbox`` 批次。"""
    sid = (caller_session_id or "").strip()
    if not sid:
        return []
    with callback_claim_lock(sid):
        recover_stale_delivering_callbacks(sid, stale_after_s=stale_after_s)
        queued = list_callback_inbox_jobs(sid, states=("queued",))
        if not queued:
            _refresh_caller_callback_index(sid)
            return []
        if delivery_channel == "idle_batch" and debounce_ms > 0:
            now_ms = int(time.time() * 1000)
            newest_ms = max(
                (
                    _iso_to_epoch_ms(j.worker_finished_at)
                    or _iso_to_epoch_ms(j.updated_at)
                    or _iso_to_epoch_ms(j.created_at)
                    or now_ms
                )
                for j in queued
            )
            if (now_ms - newest_ms) < debounce_ms:
                return []
        job_ids = [j.job_id for j in queued]
        prior_states = {j.job_id: (j.delivery_state or "queued") for j in queued}
        claim_callback_inbox(
            sid,
            delivery_channel,
            job_ids,
            prior_states=prior_states,
            has_human_next_task=has_human_next_task,
            blocked_by_card=blocked_by_card,
            is_session_busy=is_session_busy,
            enqueue_to_next_task=False,
        )
        claimed_jobs: list[AsyncDispatchJob] = []
        for jid in job_ids:
            reloaded = load_dispatch_job(jid)
            if reloaded is not None:
                claimed_jobs.append(reloaded)
        return claimed_jobs


def finalize_claimed_callbacks(
    caller_session_id: str,
    jobs: Sequence[AsyncDispatchJob],
    *,
    success: bool,
    reason: str | None = None,
) -> None:
    """将已认领的 ``delivering`` 回执批次统一推进至 ``delivered`` 终态，或失败回滚为 ``queued``。"""
    sid = (caller_session_id or "").strip()
    if not sid or not jobs:
        return
    with callback_claim_lock(sid):
        for item in jobs:
            cur = load_dispatch_job(item.job_id)
            if cur is None:
                continue
            cur_ds = (getattr(cur, "delivery_state", "queued") or "queued").strip().lower()
            if success:
                if cur_ds == "queued":
                    record_callback_delivery_outcome(
                        cur.job_id,
                        from_state="queued",
                        to_state="delivering",
                        prior_delivery_state=cur_ds,
                    )
                    cur = load_dispatch_job(cur.job_id) or cur
                    cur_ds = (cur.delivery_state or "delivering").strip().lower()
                if cur_ds == "delivering":
                    record_callback_delivery_outcome(
                        cur.job_id,
                        from_state="delivering",
                        to_state="delivered",
                        prior_delivery_state=cur_ds,
                    )
                    cur = load_dispatch_job(cur.job_id) or cur
                if (cur.delivery_state or "").strip().lower() == "delivered":
                    target_status = "completed" if cur.exit_code == 0 else "failed"
                    finalize_dispatch_job(
                        cur.job_id,
                        exit_code=cur.exit_code,
                        delivery_state="delivered",
                        job_status=target_status,
                        prior_delivery_state="delivered",
                    )
            else:
                if cur_ds == "delivering":
                    record_callback_delivery_outcome(
                        cur.job_id,
                        from_state="delivering",
                        to_state="queued",
                        reason=reason or "Deferred back to CallbackInbox",
                        prior_delivery_state=cur_ds,
                    )
        _refresh_caller_callback_index(sid)


@ontological_action(_RECORD_DELIVERY_OUTCOME_CONTRACT)
def record_callback_delivery_outcome(
    job_id: str,
    from_state: str,
    to_state: str,
    reason: str | None = None,
    *,
    # `prior_delivery_state` 只给契约谓词读（调用方注入的持久态）；函数体不读它——
    # 它管的是「这次跃迁准不准」，不是「这份任务单怎么写」。
    prior_delivery_state: str | None = None,  # noqa: ARG001
) -> str:
    """挂载 Ring 3 契约护栏的送达结果跃迁记录动作。

    ``prior_delivery_state`` 是**调用方从持久化派发单上读到的当前态**，必须由调用方注入：
    本体层不认业务落点，不自己去磁盘上找这份任务单（那是 ``load_dispatch_job`` 的事，
    落点也只此一处）。不注入或与 ``from_state`` 对不上，契约当场拒绝——这正是「谁都可以
    声称自己是从 queued 来的」这类伪造跃迁的拦截点。
    """
    job = load_dispatch_job(job_id)
    if job is None:
        # 「这份任务单得在」这条判据从前由本体层读盘时顺手兜住；本体层改成纯函数之后，
        # 它落到这里——有存储访问权的是本函数，不是契约谓词。少了它，对一份不存在的
        # 任务单调用本动作会静默返回，看起来像成功。
        raise ActionContractError(
            f"Dispatch job '{job_id}' does not exist; cannot record a delivery outcome for it."
        )
    job.delivery_state = to_state
    if from_state == "delivering":
        job.delivery_attempts = getattr(job, "delivery_attempts", 0) + 1
    if reason:
        job.delivery_error = reason
    if to_state == "delivered":
        job.delivered_at = _utc_now()
    save_dispatch_job(job)
    return to_state


@ontological_action(_FINALIZE_DISPATCH_JOB_CONTRACT)
def finalize_dispatch_job(
    job_id: str,
    exit_code: int | None,
    delivery_state: str,
    job_status: str,
    *,
    prior_delivery_state: str | None = None,  # noqa: ARG001 — 同上：只给契约谓词读
) -> str:
    """挂载 Ring 3 契约护栏的派发单终态收口动作。

    ``prior_delivery_state`` 同 :func:`record_callback_delivery_outcome`：由调用方从
    ``load_dispatch_job`` 读到的持久态注入，本体层不读盘。
    """
    job = load_dispatch_job(job_id)
    if job is None:
        # 同 record_callback_delivery_outcome：任务单必须在，这条判据随本体层去读盘
        # 一起移到了这里（有存储访问权的地方）。
        raise ActionContractError(
            f"Dispatch job '{job_id}' does not exist; cannot finalize it."
        )
    job.exit_code = int(exit_code or 0)
    job.delivery_state = delivery_state
    job.status = job_status
    job.completed_at = _utc_now()
    save_dispatch_job(job)
    return job_status


def _mark_job_superseded(
    job: AsyncDispatchJob,
    *,
    superseded_by: str | None = None,
    reason: str | None = None,
    close_stale_agy: bool = True,
) -> AsyncDispatchJob:
    """将派发单统一收口为 ``superseded``，并通过本体契约将 ``delivery_state`` 收敛为 ``failed``。"""
    if load_dispatch_job(job.job_id) is None:
        save_dispatch_job(job)

    persisted = load_dispatch_job(job.job_id) or job
    sup_by = (superseded_by or persisted.superseded_by or job.superseded_by or "").strip() or None
    err_msg = (
        (reason or "").strip()
        or (f"Superseded by {sup_by}" if sup_by else "")
        or (persisted.error or "").strip()
        or (job.error or "").strip()
        or "Superseded"
    )

    cur_delivery = getattr(persisted, "delivery_state", "queued") or "queued"
    if cur_delivery in ("queued", "delivering"):
        record_callback_delivery_outcome(
            persisted.job_id,
            from_state=cur_delivery,
            to_state="failed",
            reason=err_msg,
            prior_delivery_state=cur_delivery,
        )
        persisted = load_dispatch_job(persisted.job_id) or persisted

    persisted.status = "superseded"
    persisted.superseded_by = sup_by
    persisted.completed_at = persisted.completed_at or _utc_now()
    persisted.error = err_msg
    save_dispatch_job(persisted)

    if close_stale_agy:
        _maybe_terminate_superseded_agy_session(persisted)

    return persisted


def _maybe_terminate_superseded_agy_session(job: AsyncDispatchJob) -> bool:
    """被顶替的旧 ``agy`` 会话若最新回合已完结且未处于活跃工具调用中，经本体服务收口状态。"""
    raw_sid = (job.target_session_id or "").strip()
    if not raw_sid:
        return False
    resolved_sid, _ = _resolve_bound_session_id(raw_sid)
    target_sid = (resolved_sid or raw_sid).strip()

    with contextlib.suppress(Exception):
        from frago.session.service import TERMINAL_STATES, get_default_session_service

        onto_svc = get_default_session_service()
        rec = onto_svc.get_session(target_sid)
        if rec is None and raw_sid != target_sid:
            rec = onto_svc.get_session(raw_sid)
            if rec is not None:
                target_sid = raw_sid

        is_agy = (str(job.agent or "").strip().lower() == "agy") or (
            rec is not None and rec.agent_kernel == "agy"
        )
        if not is_agy or rec is None or rec.lifecycle_state in TERMINAL_STATES:
            return False

        # 若仍有同一目标会话的活跃派发单在跑（如刚入队的续跑新单），禁止提前终结
        for active in list_dispatch_jobs(active_only=True, _reconcile=False):
            if active.job_id == job.job_id:
                continue
            active_raw = (active.target_session_id or "").strip()
            active_resolved, _ = _resolve_bound_session_id(active_raw)
            if active_raw in (raw_sid, target_sid) or (
                active_resolved and active_resolved in (raw_sid, target_sid)
            ):
                return False

        # 确认目标 agy 会话不在忙态 / 工具调用队列中
        with contextlib.suppress(Exception):
            from frago.server.services import workbench_queue

            if workbench_queue.is_session_busy(target_sid):
                return False

        from frago.session.agy_store import latest_turn

        turn = latest_turn(target_sid)
        if turn is None or not turn.done:
            return False

        onto_svc.terminate_agent_session(
            session_id=target_sid,
            terminal_status="completed",
            summary=f"Superseded by {job.superseded_by or 'newer_turn'} (latest agy turn done)",
        )
        return True
    return False


def reconcile_superseded_dispatch_jobs() -> list[str]:
    """幂等扫描并自愈存量 ``superseded + queued/delivering`` 派发单与已完结旧 ``agy`` 会话。"""
    reconciled: list[str] = []
    root = dispatch_store_dir()
    for p in sorted(root.glob("*.json")):
        if p.name.startswith("."):
            continue
        job = load_dispatch_job(p)
        if job is None or job.status != "superseded":
            continue
        cur_delivery = getattr(job, "delivery_state", "queued") or "queued"
        if cur_delivery in ("queued", "delivering"):
            _mark_job_superseded(
                job,
                superseded_by=job.superseded_by,
                reason=job.error or None,
                close_stale_agy=True,
            )
            reconciled.append(job.job_id)
        else:
            _maybe_terminate_superseded_agy_session(job)
    return reconciled


def list_dispatch_jobs(
    *,
    caller_session_id: str | None = None,
    target_session_id: str | None = None,
    active_only: bool = False,
    _reconcile: bool = True,
) -> list[AsyncDispatchJob]:
    """按条件检索异步派发任务单。"""
    root = dispatch_store_dir()
    jobs: list[AsyncDispatchJob] = []
    for p in sorted(root.glob("*.json")):
        if p.name.startswith("."):
            continue
        job = load_dispatch_job(p)
        if job is None:
            continue
        if (
            _reconcile
            and job.status == "superseded"
            and (getattr(job, "delivery_state", "queued") or "queued") in ("queued", "delivering")
        ):
            job = _mark_job_superseded(
                job,
                superseded_by=job.superseded_by,
                reason=job.error or None,
                close_stale_agy=True,
            )
        if caller_session_id and job.caller_session_id != caller_session_id:
            continue
        if target_session_id and job.target_session_id != target_session_id:
            continue
        if active_only and job.status not in ("pending", "running", "delivering"):
            continue
        jobs.append(job)
    return jobs


def has_pending_async_work(session_id: str) -> bool:
    """判断指定会话是否仍有尚未收口的子异步派发任务。"""
    if not session_id:
        return False
    active = list_dispatch_jobs(caller_session_id=session_id, active_only=True)
    return len(active) > 0


def sync_claimed_target_session_id(
    handle_or_old_sid: str,
    claimed_session_id: str,
    *,
    agent_type: str | None = None,
    cwd: str | None = None,
) -> list[str]:
    """当认领型内核（agy / codex / opencode）将预分配把手绑定到真实原生会话 ID 时，
    立即同步更新对应 AsyncDispatchJob 的 target_session_id 并落盘。
    """
    old_sid = (handle_or_old_sid or "").strip()
    new_sid = (claimed_session_id or "").strip()
    if not old_sid or not new_sid or old_sid == new_sid:
        return []
    updated_job_ids: list[str] = []
    root = dispatch_store_dir()
    for p in sorted(root.glob("*.json")):
        if p.name.startswith("."):
            continue
        job = load_dispatch_job(p)
        if job is None or job.target_session_id != old_sid:
            continue
        job.target_session_id = new_sid
        if job.target_name == old_sid:
            job.target_name = new_sid
        save_dispatch_job(job)
        updated_job_ids.append(job.job_id)
        with contextlib.suppress(Exception):
            from frago.session.session_origin import record_relation

            record_relation(
                kind="dispatch",
                child_session_id=new_sid,
                parent_session_id=job.caller_session_id,
                agent_type=agent_type or job.agent,
                cwd=cwd or job.cwd,
                prompt_head=job.task_summary,
            )
        if job.employee_id:
            with contextlib.suppress(Exception):
                from frago.employee import get_post, save_post

                rec = get_post(job.employee_id)
                if rec is not None:
                    cleaned = [s for s in rec.active_session_ids if s and s != old_sid]
                    if new_sid not in cleaned:
                        cleaned.append(new_sid)
                    if cleaned != rec.active_session_ids:
                        rec.active_session_ids = cleaned
                        save_post(rec)
    return updated_job_ids


def supersede_active_jobs_for_target(
    target_session_id: str,
    *,
    new_job_id: str,
    caller_session_id: str | None = None,
) -> list[str]:
    """当对同一 target_session_id 发起新的异步派发（如追派续跑）时，将尚未收口的旧派发单标记为 superseded。"""
    if not target_session_id:
        return []
    superseded_ids: list[str] = []
    for old_job in list_dispatch_jobs(
        caller_session_id=caller_session_id,
        target_session_id=target_session_id,
        active_only=True,
    ):
        if old_job.job_id == new_job_id:
            continue
        _mark_job_superseded(
            old_job,
            superseded_by=new_job_id,
            reason=f"Superseded by {new_job_id}",
        )
        superseded_ids.append(old_job.job_id)
    return superseded_ids


def _can_write_ontology(svc: Any) -> bool:
    from frago.session.store import DEFAULT_SESSION_STORE_PATH

    return (
        svc.store.store_path != DEFAULT_SESSION_STORE_PATH
        or not os.environ.get("PYTEST_CURRENT_TEST")
    )


def _next_turn_seq_for_target(
    target_session_id: str,
    *,
    agent_kernel: str = "claude",
    origin: str = "worker",
    employee_id: str | None = None,
) -> int:
    """Allocate a strictly monotonic ``turn_seq`` for ``target_session_id`` and start turn in ontology."""
    clean_sid = str(target_session_id or "").strip()
    max_seq = 0
    if clean_sid:
        for existing in list_dispatch_jobs(target_session_id=clean_sid, active_only=False):
            max_seq = max(max_seq, int(getattr(existing, "turn_seq", 0) or 0))
        with contextlib.suppress(Exception):
            from frago.session.service import get_default_session_service

            svc = get_default_session_service()
            if _can_write_ontology(svc):
                rec = svc.get_session(clean_sid)
                kernel = rec.agent_kernel if rec is not None else (agent_kernel or "claude")
                orig = rec.origin if rec is not None else (origin or "worker")
                updated = svc.start_turn(clean_sid, agent_kernel_id=kernel, origin=orig)
                if employee_id and not updated.employee_id:
                    from frago.session.store import SessionOntologyRecord

                    svc.store.upsert_relation(
                        SessionOntologyRecord(
                            session_id=clean_sid,
                            agent_kernel=updated.agent_kernel,
                            origin=updated.origin,
                            is_worker=updated.is_worker,
                            relation_kind=updated.relation_kind,
                            employee_id=employee_id,
                        )
                    )
                return max(max_seq + 1, int(updated.turn_seq))
    return max_seq + 1


def _is_resident_interactive_alive(session_id: str) -> bool:
    """Return True if ``session_id`` still has a live interactive tmux/resident shell after turn end."""
    if not session_id:
        return False
    with contextlib.suppress(Exception):
        from frago.agent_driver.tmux_session import tmux_name_for
        from frago.server.services import coreagent_runner, tmux_sessions_service

        if coreagent_runner.running(session_id):
            return True
        if tmux_name_for(session_id) in tmux_sessions_service.open_session_names():
            return True
    return False


def _closeout_dispatch_target(
    job: AsyncDispatchJob,
    *,
    turn_status: str,
    answer_text: str = "",
    error_text: str = "",
    old_target: str | None = None,
) -> None:
    """Close out target worker/employee session in SessionOntologyService immediately after execution."""
    clean_sid = str(job.target_session_id or "").strip()
    if not clean_sid:
        return
    with contextlib.suppress(Exception):
        from frago.session.service import get_default_session_service

        svc = get_default_session_service()
        if not _can_write_ontology(svc):
            return

        if old_target and old_target.strip() and old_target.strip() != clean_sid:
            old_rec = svc.get_session(old_target.strip())
            if old_rec is not None and old_rec.lifecycle_state in ("running", "queued"):
                svc.complete_turn_if_current(
                    old_target.strip(),
                    turn_seq=int(getattr(job, "turn_seq", 0) or old_rec.turn_seq or 1),
                    target_state="completed",
                )

        default_origin = "worker" if job.kind == "worker" else "terminal"
        svc.ensure_managed_session(
            clean_sid,
            agent_kernel_id=job.agent or "claude",
            origin=default_origin,
            initial_state="running",
        )

        norm_status = str(turn_status or "ok").strip().lower()
        target_state: str
        waiting_reason: str | None = None
        summary: str | None = None
        if norm_status == "needs_input":
            target_state = "awaiting_input"
            waiting_reason = "needs_input"
        elif norm_status in ("error", "timeout"):
            target_state = "error"
            summary = (
                (error_text or answer_text or f"{job.kind} turn ended with status '{norm_status}'")
                .strip()[:500]
            )
        elif job.kind == "drive_send" or (
            job.kind == "employee" and _is_resident_interactive_alive(clean_sid)
        ):
            target_state = "awaiting_input"
            waiting_reason = "end_turn"
        else:
            target_state = "completed"

        svc.complete_turn_if_current(
            clean_sid,
            turn_seq=int(getattr(job, "turn_seq", 0) or 1),
            target_state=target_state,
            waiting_reason=waiting_reason,
            summary=summary,
        )


def is_job_superseded(job: AsyncDispatchJob) -> tuple[bool, str | None]:
    """检查当前派发单是否已被同一目标会话的后续派发单或更新轮次 (`turn_seq`) 抢占取代。"""
    on_disk = load_dispatch_job(job.job_id)
    if on_disk is not None and (on_disk.status == "superseded" or on_disk.superseded_by):
        return True, on_disk.superseded_by
    if not job.target_session_id:
        return False, None
    job_seq = int(getattr(job, "turn_seq", 0) or 0)
    if job_seq > 0:
        with contextlib.suppress(Exception):
            from frago.session.service import get_default_session_service

            rec = get_default_session_service().get_session(job.target_session_id)
            if rec is not None and int(rec.turn_seq) > job_seq:
                return True, f"turn_seq:{rec.turn_seq}"
    for other in list_dispatch_jobs(
        caller_session_id=job.caller_session_id,
        target_session_id=job.target_session_id,
        active_only=True,
    ):
        if other.job_id == job.job_id:
            continue
        other_seq = int(getattr(other, "turn_seq", 0) or 0)
        if (job_seq > 0 and other_seq > job_seq) or (other.created_at >= job.created_at and other_seq >= job_seq):
            return True, other.job_id
    return False, None


def resolve_caller_session_id(explicit_caller_sid: str | None = None) -> str | None:
    """解析当前 CLI 命令发起方的会话 ID（跨 5 套 CLI Agent 统一识别）。

    优先级：
    1. 显式传入的 ``--callback-session <sid>``
    2. 环境变量 ``FRAGO_CALLBACK_SESSION_ID``
    3. ``resolve_self()``（覆盖 CLAUDE_CODE_SESSION_ID / ANTIGRAVITY_CONVERSATION_ID /
       CODEX_THREAD_ID / OPENCODE_SESSION_ID / FRAGO_SESSION_ID / FRAGO_LAUNCH_HANDLE）

    注：在 pytest 运行期间，为防止外层宿主会话环境变量污染无关单测，除非显式传入
    ``explicit_caller_sid``、设置了 ``FRAGO_CALLBACK_SESSION_ID`` 或
    ``FRAGO_TEST_ALLOW_ASYNC_DISPATCH=1``，否则默认不读取外层环境身份。
    """
    if explicit_caller_sid and explicit_caller_sid.strip():
        resolved, _ = _resolve_bound_session_id(explicit_caller_sid.strip())
        return resolved or explicit_caller_sid.strip()

    env_cb = os.environ.get("FRAGO_CALLBACK_SESSION_ID", "").strip()
    if env_cb:
        resolved, _ = _resolve_bound_session_id(env_cb)
        return resolved or env_cb

    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("FRAGO_TEST_ALLOW_ASYNC_DISPATCH") != "1":
        return None

    found = resolve_self()
    return found.session_id if found is not None else None


def is_employee_caller_session(caller_session_id: str | None) -> tuple[bool, str | None]:
    """判断发起方会话是否绑定了数字员工（Employee），返回 ``(is_employee, employee_id)``。"""
    env_emp = os.environ.get("FRAGO_EMPLOYEE_ID", "").strip()
    if env_emp:
        return True, env_emp
    if not caller_session_id:
        return False, None
    with contextlib.suppress(Exception):
        from frago.employee import resolve_session_employee_id

        emp_id = resolve_session_employee_id(caller_session_id)
        if emp_id:
            return True, emp_id
    return False, None


def _in_synchronous_recipe_context() -> bool:
    """判断当前是否处于 ``frago recipe run`` 或配方沙箱的同步脚本上下文中。"""
    return bool(
        os.environ.get("FRAGO_CURRENT_RUN", "").strip()
        or os.environ.get("FRAGO_EXECUTION_ID", "").strip()
        or os.environ.get("FRAGO_RECIPE_DATA_DIR", "").strip()
    )


def should_dispatch_employee_async(
    caller_session_id: str | None,
    *,
    wait_for_answer: bool = False,
    force_async: bool = False,
    dry_run: bool = False,
    force_spawn: bool = False,
    explicit_caller_sid: str | None = None,
) -> bool:
    """判定 ``frago employee invoke/ask`` 是否走非阻塞异步派发 + 会话流回投。"""
    if dry_run or force_spawn or wait_for_answer:
        return False
    if not caller_session_id:
        return False
    return not (_in_synchronous_recipe_context() and not (force_async or explicit_caller_sid))


def should_dispatch_worker_async(
    caller_session_id: str | None,
    *,
    wait_for_answer: bool = False,
    force_async: bool = False,
    dry_run: bool = False,
    explicit_caller_sid: str | None = None,
    target_session_id: str | None = None,
) -> bool:
    """判定 ``frago agent`` / ``frago agent send`` 是否走非阻塞异步派发 + 会话流回投。

    触发条件：
    - 未指定 ``--wait`` 且非 ``--dry-run``；
    - 存在有效的 ``caller_session_id``（且不等于目标会话自身）；
    - 调用方是数字员工会话（Employee），或显式指定了 ``--async`` / ``--callback-session``。
    """
    if dry_run or wait_for_answer:
        return False
    if not caller_session_id:
        return False
    if target_session_id and caller_session_id == target_session_id:
        return False
    if _in_synchronous_recipe_context() and not (force_async or explicit_caller_sid):
        return False
    if force_async or explicit_caller_sid:
        return True
    is_emp, _ = is_employee_caller_session(caller_session_id)
    return is_emp


def sanitize_child_env(
    base_env: dict[str, str] | None = None,
    *,
    target_session_id: str | None = None,
    target_employee_id: str | None = None,
) -> dict[str, str]:
    """清洗子进程环境，剥离父会话的身份变量，注入子会话自身身份。"""
    env = dict(base_env if base_env is not None else os.environ)
    for k in SESSION_IDENTITY_ENV:
        env.pop(k, None)
    for extra_k in (
        "FRAGO_CALLBACK_SESSION_ID",
        "FRAGO_EMPLOYEE_ID",
        "FRAGO_LAUNCH_HANDLE",
    ):
        env.pop(extra_k, None)
    if target_session_id:
        env["FRAGO_SESSION_ID"] = target_session_id
    if target_employee_id:
        env["FRAGO_EMPLOYEE_ID"] = target_employee_id
        env["FRAGO_AGENT_ROLE"] = "employee"
    elif env.get("FRAGO_AGENT_ROLE") == "employee":
        env.pop("FRAGO_AGENT_ROLE", None)
    env["FRAGO_ASYNC_DISPATCH_CHILD"] = "1"
    return env


def format_dispatched_receipt(job: AsyncDispatchJob, *, output_format: str = "text") -> str:
    """生成秒级返回的 ``[dispatched]`` 派发回执文本或 JSON。"""
    if output_format == "json":
        payload = {
            "status": "dispatched",
            "job_id": job.job_id,
            "kind": job.kind,
            "mode": job.mode,
            "session_id": job.target_session_id,
            "target_session_id": job.target_session_id,
            "caller_session_id": job.caller_session_id,
            "employee_id": job.employee_id,
            "agent": job.agent,
            "cwd": job.cwd,
            "message": (
                f"Task dispatched in background (job_id={job.job_id}, "
                f"target_session_id={job.target_session_id}). "
                f"Final output will be automatically injected into caller session "
                f"{job.caller_session_id} when completed."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    if job.kind == "employee":
        return (
            f"[dispatched] job_id={job.job_id} mode=employee_{job.mode} "
            f"employee_id={job.employee_id} target_session_id={job.target_session_id} "
            f"caller_session_id={job.caller_session_id}\n"
            f"status: running_in_background\n"
            f"callback: 同侪员工 {job.employee_id}（会话 {job.target_session_id}）已在后台处理，"
            f"最终结论将在完成后自动投递回当前会话（{job.caller_session_id}）的消息流。"
            f"请先向人类简要同步派发状态并结束当前回合，等待回传报文唤醒。"
        )
    return (
        f"[dispatched] job_id={job.job_id} mode=worker_{job.mode} "
        f"worker_session_id={job.target_session_id} caller_session_id={job.caller_session_id}\n"
        f"status: running_in_background\n"
        f"callback: 下属 Worker 会话（{job.target_session_id}）已在后台执行任务书，"
        f"执行结果将在完成后自动投递回当前会话（{job.caller_session_id}）的消息流。"
        f"请先向人类简要同步派发状态并结束当前回合，等待回传报文唤醒。"
    )


#: 回传正文超过此长度即改为「摘要 + 查全指引」，避免把整篇长报告灌进父会话上下文。
_CALLBACK_BODY_MAX_CHARS = 600
#: 截断时保留的前段字数（核心结论通常开篇即出，尾部多为铺陈与附录）。
_CALLBACK_BODY_HEAD_CHARS = 420


def summarize_callback_body(
    body: str,
    target_session_id: str,
    *,
    report_file: str | None = None,
    total_chars: int | None = None,
) -> str:
    """把回传正文压成「前段核心内容 + 省略字数提示 + 查全指引」。

    短正文（不超过 ``_CALLBACK_BODY_MAX_CHARS``）原样返回，不丢任何信息；超长正文保留前段
    ``_CALLBACK_BODY_HEAD_CHARS`` 字，并明确告知省略了多少字、到哪里取全文。截断只作用于正文，
    不影响 ``<frago-async-callback>`` 的属性行与小节标题，因此前端解析器不受影响。
    """
    if len(body) <= _CALLBACK_BODY_MAX_CHARS:
        return body
    head = body[:_CALLBACK_BODY_HEAD_CHARS].rstrip()
    omitted = len(body) - len(head)
    # 前段若正好切在 ``` 代码围栏中间，补一个闭合围栏：否则 Markdown 会把省略提示与查全指引
    # 一并当成代码块内容吞掉，父会话反而看不到「去哪里取全文」。
    if head.count("```") % 2 == 1:
        head = f"{head}\n```"
    effective_total = total_chars if total_chars is not None else len(body)
    if report_file:
        return (
            f"{head}\n\n"
            f"……（正文过长，此处省略 {omitted} 字，总计 {effective_total} 字。"
            f"完整内容已写入落盘的交付报告 `{report_file}`；"
            f"也可使用 `frago session read {target_session_id}` 分页无损读取，"
            f"或 `frago session ask {target_session_id} 「要提取的问题」` 查询目标会话。）"
        )
    return (
        f"{head}\n\n"
        f"……（正文过长，此处省略 {omitted} 字，总计 {effective_total} 字。完整内容请用 "
        f"`frago session read {target_session_id}` 分页无损读取，"
        f"或 `frago session ask {target_session_id} 「要提取的问题」` 读取目标会话，"
        f"或直接查阅该会话落盘的交付报告。）"
    )


def format_callback_prompt(job: AsyncDispatchJob) -> str:
    """将子任务（同侪员工或下属 Worker）的最终产出封装为回投给父会话的结构化报文。"""
    status_label = "completed" if job.exit_code == 0 and job.status != "failed" else "failed"
    body = (job.output or "").strip()
    if not body and job.error:
        body = f"[执行异常] {job.error.strip()}"
    if not body:
        body = "（目标会话已完成回合，未捕获到额外文本输出，请按需核查目标会话记录。）"
    total_chars = job.report_total_chars if job.report_total_chars is not None else len(body)
    body = summarize_callback_body(
        body,
        job.target_session_id,
        report_file=job.report_file,
        total_chars=total_chars,
    )
    report_line = ""
    if job.report_file:
        report_line = (
            f"- 交付报告：`{job.report_file}`（总计 {total_chars} 字，"
            f"分页读取：`frago session read {job.target_session_id}`）\n"
        )

    if job.kind == "employee":
        mode_zh = "任务移交 (invoke)" if job.mode == "invoke" else "协查提问 (ask)"
        return (
            f"<frago-async-callback kind=\"employee\" mode=\"{job.mode}\" "
            f"job_id=\"{job.job_id}\" employee_id=\"{job.employee_id or ''}\" "
            f"session_id=\"{job.target_session_id}\" status=\"{status_label}\">\n"
            f"【同侪员工异步回传】来自 `{job.employee_id}`（会话 `{job.target_session_id}`，模式：{mode_zh}）\n"
            f"- 派发单号：`{job.job_id}`\n"
            f"- 原始诉求：{job.task_summary}\n"
            f"- 执行状态：`{status_label}` (exit_code={job.exit_code})\n"
            f"{report_line}\n"
            f"### 同侪员工返回结论\n"
            f"{body}\n\n"
            f"---\n"
            f"请基于上述同侪员工回传结论，结合你掌握的领域背景与事务围栏进行复核：\n"
            f"若结论已向人类汇报且内容一致，仅需一句话确认收口，严禁全文复述；"
            f"否则请精炼提炼要点并向人类给出最终结果与决策建议。\n"
            f"</frago-async-callback>"
        )

    mode_zh = {
        "new": "新建 Worker 执行",
        "resume": "复用已有 Worker 续跑",
        "send": "驱动已有 Worker 会话",
    }.get(job.mode, job.mode)
    return (
        f"<frago-async-callback kind=\"worker\" mode=\"{job.mode}\" "
        f"job_id=\"{job.job_id}\" worker_session_id=\"{job.target_session_id}\" "
        f"status=\"{status_label}\">\n"
        f"【下属 Worker 异步回传】来自 Worker 会话 `{job.target_session_id}`（模式：{mode_zh}，内核：`{job.agent}`）\n"
        f"- 派发单号：`{job.job_id}`\n"
        f"- 任务摘要：{job.task_summary}\n"
        f"- 执行状态：`{status_label}` (exit_code={job.exit_code})\n"
        f"{report_line}\n"
        f"### Worker 交付结果\n"
        f"{body}\n\n"
        f"---\n"
        f"请作为管理者（Employee）结合领域知识与执行准则审核上述 Worker 产出：\n"
        f"1. 若结论已向人类汇报且内容一致，仅需一句话确认收口，严禁全文复述；"
        f"否则请精炼提炼要点并向人类给出最终结果与决策建议；\n"
        f"2. 若发现遗漏或需补充验证，可继续向该 Worker（`frago agent --resume {job.target_session_id} ...`）追派任务书。\n"
        f"</frago-async-callback>"
    )


def _format_compact_callback_item(
    job: AsyncDispatchJob,
    *,
    body_limit: int = 160,
    summary_limit: int = 100,
) -> str:
    """将单条派发单压成保留结构化元数据的紧凑 ``<frago-async-callback>`` 摘要。"""
    status_label = "completed" if job.exit_code == 0 and job.status != "failed" else "failed"
    summary = " ".join((job.task_summary or "").split())
    if len(summary) > summary_limit:
        summary = summary[: max(1, summary_limit - 1)] + "…"
    body = " ".join((job.output or job.error or "").split())
    snippet_line = ""
    if body and body_limit > 0:
        snippet = body[:body_limit].rstrip()
        if len(body) > body_limit:
            snippet += "…"
        snippet_line = f"- 摘要：{snippet}\n"
    report_ref = (
        f"`{job.report_file}`（或 `frago session read {job.target_session_id}`）"
        if job.report_file
        else f"`frago session read {job.target_session_id}`"
    )
    if job.kind == "employee":
        attrs = (
            f'kind="employee" mode="{job.mode}" job_id="{job.job_id}" '
            f'employee_id="{job.employee_id or ""}" session_id="{job.target_session_id}" '
            f'status="{status_label}"'
        )
        source_desc = f"同侪 `{job.employee_id or job.target_session_id}`"
    else:
        attrs = (
            f'kind="worker" mode="{job.mode}" job_id="{job.job_id}" '
            f'worker_session_id="{job.target_session_id}" status="{status_label}"'
        )
        source_desc = f"Worker `{job.target_session_id}`"
    return (
        f"<frago-async-callback {attrs}>\n"
        f"- 来源：{source_desc} | 派发单号：`{job.job_id}` | 状态：`{status_label}` (exit_code={job.exit_code})\n"
        f"- 诉求：{summary}\n"
        f"{snippet_line}"
        f"- 完整交付：{report_ref}\n"
        f"</frago-async-callback>"
    )


def format_callback_batch_prompt(
    jobs: Sequence[AsyncDispatchJob],
    *,
    delivery: str = "idle-batch",
    max_chars: int | None = None,
) -> str:
    """将一批就绪的 ``CallbackInbox`` 回执合并组装为带优先级隔离信封的批量投递报文。

    当 ``max_chars`` 给定（如 ``TurnSubmit`` 搭便车 ``<= 5500`` 字符上限）时，按结构化降级阶梯
    压缩正文，始终保留 ``job_id``、``report_file`` 与合法闭合标签 ``</frago-async-callbacks>``，
    绝不粗暴切片破坏 XML/隔离标签。
    """
    job_list = list(jobs)
    if not job_list:
        return ""
    count = len(job_list)
    open_tag = (
        f'<frago-async-callbacks count="{count}" delivery="{delivery}" '
        f'priority="background-after-human">'
    )
    close_tag = "</frago-async-callbacks>"
    if delivery == "turn-submit-hitchhike":
        header = (
            "【优先主线声明】主人的本轮当前请求是唯一最高优先级主线；请先直接、完整回应主人本轮请求。\n"
            "以下是在此之前由后台完成的异步派发回执，仅作附带参考信息；"
            "严禁让后台回执劫持你当前回应主人主线的议程（除非主人本轮正好在询问该任务）。"
        )
    else:
        header = (
            f"【后台异步派发回执汇总】以下 {count} 项后台异步任务已完成且当前会话处于空闲安全窗口，"
            "请结合领域上下文复核关键结论并按需向人类汇报。"
        )

    def _wrap(items: Sequence[str], *, footer: str = "") -> str:
        body_parts = [open_tag, header, *items]
        if footer:
            body_parts.append(footer)
        body_parts.append(close_tag)
        return "\n\n".join(body_parts)

    full_items = [format_callback_prompt(j) for j in job_list]
    full_text = _wrap(full_items)
    if max_chars is None or len(full_text) <= max_chars:
        return full_text

    # 结构化逐级降级：优先缩减单条正文片段，保留全部 job_id 与 report_file；仍超限时再按条数省略尾项
    for body_limit in (180, 80, 0):
        compact_items = [
            _format_compact_callback_item(j, body_limit=body_limit, summary_limit=80)
            for j in job_list
        ]
        candidate = _wrap(compact_items)
        if len(candidate) <= max_chars:
            return candidate

    # 极端多条并发时保留尽可能多的完整元数据条目，并显式标出省略数，保证闭合标签完整
    kept: list[str] = []
    for idx, job in enumerate(job_list):
        item = _format_compact_callback_item(job, body_limit=0, summary_limit=48)
        remaining = count - (idx + 1)
        footer = (
            f"（因上下文预算上限，其余 {remaining} 条回执已省略详情；"
            "请查阅 `~/.frago/sessions/async_dispatches/` 或按 `job_id` / `frago session read` 取全。）"
            if remaining > 0
            else ""
        )
        trial = _wrap([*kept, item], footer=footer)
        if len(trial) <= max_chars:
            kept.append(item)
        else:
            break

    if not kept:
        kept.append(_format_compact_callback_item(job_list[0], body_limit=0, summary_limit=24))
    omitted_count = max(0, count - len(kept))
    final_footer = (
        f"（因上下文预算上限，其余 {omitted_count} 条回执已省略详情；"
        "请查阅 `~/.frago/sessions/async_dispatches/`。）"
        if omitted_count > 0
        else ""
    )
    res = _wrap(kept, footer=final_footer)
    if len(res) <= max_chars:
        return res
    # 最极端窄预算兜底（如测试传入极小 max_chars）：输出纯索引行并严保闭合标签
    min_lines = "\n".join(
        f"- job_id={j.job_id} status={'completed' if j.exit_code == 0 else 'failed'} report={j.report_file or '-'}"
        for j in job_list[:3]
    )
    overhead = len(open_tag) + len(close_tag) + 4
    budget = max(0, max_chars - overhead)
    trimmed_lines = min_lines[:budget].rstrip()
    return f"{open_tag}\n{trimmed_lines}\n{close_tag}"


def _extract_latest_assistant_output(session_id: str) -> str | None:
    """从目标会话的记录中提取最新一条实质性 assistant 文本（排除纯 [dispatched] 过渡回执）。"""
    return extract_latest_substantive_assistant_output(session_id)


def wait_for_pending_child_dispatches(
    target_session_id: str,
    *,
    timeout_s: float = 1800.0,
    poll_interval_s: float = 0.5,
) -> str | None:
    """若目标会话在执行过程中又发起了子异步派发（如 Employee B -> Worker W），
    等待所有子派发完成回投且目标会话自身回合再次收口后，返回其最新结论。
    """
    bound_sid = _resolve_bound_session_id(target_session_id)[0]
    if bound_sid:
        target_session_id = bound_sid
    if not has_pending_async_work(target_session_id) and not list_dispatch_jobs(
        caller_session_id=target_session_id, active_only=False
    ):
        return None

    from frago.server.services import workbench_queue

    deadline = time.monotonic() + max(timeout_s, 10.0)
    idle_streak = 0
    while time.monotonic() < deadline:
        pending_children = has_pending_async_work(target_session_id)
        queued_items = False
        with contextlib.suppress(Exception):
            queued_items = len(workbench_queue.list_queue(target_session_id)) > 0 or bool(
                list_callback_inbox_jobs(target_session_id, states=("queued", "delivering"))
            )
        busy = False
        with contextlib.suppress(Exception):
            busy = workbench_queue.is_session_busy(target_session_id)
        if not pending_children and not queued_items and not busy:
            idle_streak += 1
            if idle_streak >= 2:
                break
        else:
            idle_streak = 0
        time.sleep(poll_interval_s)

    # 提取最新 assistant 文本；若会话记录尚未刷新，也汇总子派发任务单的产出兜底
    latest_text = _extract_latest_assistant_output(target_session_id)
    if latest_text:
        return latest_text

    child_jobs = list_dispatch_jobs(caller_session_id=target_session_id, active_only=False)
    child_outputs = [
        j.output.strip()
        for j in child_jobs
        if j.output and j.output.strip()
    ]
    if child_outputs:
        return "\n\n".join(child_outputs)
    return None


def _local_server_wakeup_port() -> int | None:
    """若本机常驻 ``frago server`` 正在运行且当前处于外部子进程（非测试隔离桩），返回服务端口。"""
    from frago.server.services import workbench_queue

    if workbench_queue.is_server_process():
        return None
    if getattr(workbench_queue, "_sender_override", None) is not None:
        return None
    if os.environ.get("FRAGO_ASYNC_DISPATCH_NO_SERVER") == "1":
        return None
    if "PYTEST_CURRENT_TEST" in os.environ and os.environ.get("FRAGO_ASYNC_DISPATCH_ALLOW_SERVER") != "1":
        return None
    try:
        from frago.server.daemon import get_server_port, is_server_running

        running, _pid = is_server_running()
        if running:
            return get_server_port()
    except Exception:
        pass
    return None


def _poke_server_callback_drain(port: int, session_id: str) -> dict[str, Any] | None:
    """唤醒常驻 ``frago server`` 在其自身进程上下文内安全消费 ``CallbackInbox``。"""
    import urllib.parse
    import urllib.request

    url = (
        f"http://127.0.0.1:{port}/api/workbench/sessions/"
        f"{urllib.parse.quote(session_id, safe='')}/callback-inbox/drain"
    )
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=35.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def deliver_callback_to_session(
    caller_session_id: str,
    callback_prompt: str,
    *,
    job_id: str | None = None,
    cwd_hint: str | None = None,
    max_wait_s: float = 1800.0,  # noqa: ARG001 — 保留入参兼容旧签名；Option A 不再阻塞等待
    poll_interval_s: float = 0.5,  # noqa: ARG001
) -> bool:
    """非阻塞将完成回执挂入 ``CallbackInbox`` 并尝试立即空闲投递（绝不写入 ``workbench-queue.json``）。"""
    if not caller_session_id or not callback_prompt.strip():
        return False

    if _callback_sender_override is not None:
        return bool(_callback_sender_override(caller_session_id, callback_prompt, cwd_hint))

    from frago.server.services import callback_inbox_dispatcher, workbench_queue

    jid = job_id
    if not jid and isinstance(callback_prompt, str):
        m = re.search(r'<frago-async-callback[^>]*job_id="([^"]+)"', callback_prompt)
        if m:
            jid = m.group(1)

    job = load_dispatch_job(jid) if jid else None
    if job is not None:
        if (job.delivery_state or "").strip().lower() == "delivered":
            return True
        dirty = False
        if job.status in ("pending", "running"):
            job.status = "delivering"
            dirty = True
        if not job.worker_finished_at:
            job.worker_finished_at = _utc_now()
            dirty = True
        if not job.delivery_state:
            job.delivery_state = "queued"
            dirty = True
        if dirty:
            save_dispatch_job(job)
        register_active_callback_caller(caller_session_id)

    server_port = _local_server_wakeup_port()
    if server_port is not None:
        outcome = _poke_server_callback_drain(server_port, caller_session_id)
        if jid:
            reloaded = load_dispatch_job(jid)
            if reloaded is not None and (reloaded.delivery_state or "").strip().lower() == "delivered":
                return True
        if isinstance(outcome, dict) and outcome.get("delivered"):
            deliv_ids = outcome.get("delivered_job_ids")
            if not jid or not isinstance(deliv_ids, list) or jid in deliv_ids:
                return True
        return False

    if job is not None:
        debounce_ms = CALLBACK_INBOX_DEBOUNCE_MS
        outcome = callback_inbox_dispatcher.try_deliver_callback_inbox(
            caller_session_id,
            debounce_ms=debounce_ms,
        )
        # 无常驻 server 的独立 watcher 场景：同样遵守 300–500ms 空闲合批窗口，
        # 等待防抖窗口成熟后再尝试单次合并认领（防止并发完成子任务各自抢先单条唤醒主控）。
        for _ in range(4):
            reason = outcome.get("reason")
            if reason == "debouncing":
                remaining_ms = int(outcome.get("remaining_debounce_ms") or debounce_ms)
                time.sleep(min(max(remaining_ms + 20, 20), 600) / 1000.0)
            elif reason == "injecting":
                # 同会话另一并发 watcher 正在合批投递，短暂让出后回查是否已随批送达
                time.sleep(0.05)
            else:
                break
            reloaded_check = load_dispatch_job(jid) if jid else None
            if reloaded_check is not None and (reloaded_check.delivery_state or "").strip().lower() == "delivered":
                return True
            outcome = callback_inbox_dispatcher.try_deliver_callback_inbox(
                caller_session_id,
                debounce_ms=debounce_ms,
            )
        reloaded = load_dispatch_job(jid) if jid else None
        if reloaded is not None and (reloaded.delivery_state or "").strip().lower() == "delivered":
            return True
        if isinstance(outcome, dict) and outcome.get("delivered"):
            deliv_ids = outcome.get("delivered_job_ids") or []
            if jid in deliv_ids:
                return True
        return False

    # 无持久化 AsyncDispatchJob 的直发兜底（保持与 Next Task 物理隔离，直接尝试空闲直投）
    with workbench_queue.cross_process_inject_guard(caller_session_id) as acquired:
        if not acquired:
            return False
        try:
            return bool(
                workbench_queue._send_prompt(
                    caller_session_id,
                    callback_prompt,
                    cwd_hint,
                )
            )
        except Exception:
            return False


def _spawn_detached_watcher(job_path: Path, *, target_session_id: str, target_employee_id: str | None = None) -> None:
    """拉起脱离父进程会话组的后台 watcher 进程。"""
    if _async_spawner_override is not None:
        _async_spawner_override(job_path)
        return

    if os.environ.get("FRAGO_ASYNC_DISPATCH_INLINE") == "1":
        execute_dispatch_job(job_path)
        return

    child_env = sanitize_child_env(
        os.environ,
        target_session_id=target_session_id,
        target_employee_id=target_employee_id,
    )
    log_file = dispatch_logs_dir() / f"{job_path.stem}.log"
    with open(log_file, "a", encoding="utf-8") as log_fp:
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": log_fp,
            "close_fds": True,
            "env": child_env,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            )
        else:
            popen_kwargs["start_new_session"] = True

        subprocess.Popen(
            [sys.executable, "-m", "frago.session.async_dispatch", "--job-file", str(job_path)],
            **popen_kwargs,
        )


def dispatch_employee_turn_async(
    *,
    mode: str,
    caller_session_id: str,
    caller_cwd: str | None,
    employee_id: str,
    target_session_id: str,
    agent: str,
    cwd: str,
    prompt: str,
    task_summary: str,
    resume: str | None,
    model: str | None,
) -> AsyncDispatchJob:
    """登记同侪员工异步派发任务并拉起后台 watcher。"""
    _, caller_emp_id = is_employee_caller_session(caller_session_id)
    job = AsyncDispatchJob(
        job_id=f"disp-{uuid.uuid4().hex[:12]}",
        kind="employee",
        mode=mode,
        caller_session_id=caller_session_id,
        caller_employee_id=caller_emp_id,
        caller_cwd=caller_cwd or os.getcwd(),
        target_session_id=target_session_id,
        target_name=employee_id,
        employee_id=employee_id,
        agent=agent,
        cwd=cwd,
        prompt=prompt,
        task_summary=task_summary[:240],
        resume=resume,
        model=model,
        status="running",
        turn_seq=_next_turn_seq_for_target(
            target_session_id,
            agent_kernel=agent,
            origin="worker",
            employee_id=employee_id,
        ),
    )
    job_path = save_dispatch_job(job)
    supersede_active_jobs_for_target(
        target_session_id,
        new_job_id=job.job_id,
        caller_session_id=caller_session_id,
    )
    _spawn_detached_watcher(
        job_path,
        target_session_id=target_session_id,
        target_employee_id=employee_id,
    )
    return job


def dispatch_worker_turn_async(
    *,
    mode: str,
    caller_session_id: str,
    caller_cwd: str | None,
    target_session_id: str,
    agent: str,
    cwd: str,
    prompt: str,
    task_summary: str,
    resume: str | None = None,
    model: str | None = None,
    profile_id: str | None = None,
    timeout: int | None = None,
    env_list: list[str] | None = None,
) -> AsyncDispatchJob:
    """登记下属 Worker 异步派发任务并拉起后台 watcher。"""
    _, caller_emp_id = is_employee_caller_session(caller_session_id)
    job = AsyncDispatchJob(
        job_id=f"disp-{uuid.uuid4().hex[:12]}",
        kind="worker",
        mode=mode,
        caller_session_id=caller_session_id,
        caller_employee_id=caller_emp_id,
        caller_cwd=caller_cwd or os.getcwd(),
        target_session_id=target_session_id,
        target_name=target_session_id,
        employee_id=None,
        agent=agent,
        cwd=cwd,
        prompt=prompt,
        task_summary=task_summary[:240],
        resume=resume,
        model=model,
        profile_id=profile_id,
        timeout=timeout,
        env_list=list(env_list or []),
        status="running",
        turn_seq=_next_turn_seq_for_target(
            target_session_id,
            agent_kernel=agent,
            origin="worker",
        ),
    )
    job_path = save_dispatch_job(job)
    supersede_active_jobs_for_target(
        target_session_id,
        new_job_id=job.job_id,
        caller_session_id=caller_session_id,
    )
    _spawn_detached_watcher(
        job_path,
        target_session_id=target_session_id,
        target_employee_id=None,
    )
    return job


def dispatch_drive_send_async(
    *,
    caller_session_id: str,
    caller_cwd: str | None,
    target_session_id: str,
    target_name: str,
    agent: str,
    cwd: str,
    prompt: str,
    timeout: float = 600.0,
) -> AsyncDispatchJob:
    """登记 ``frago agent send`` 异步派发任务并拉起后台 watcher。"""
    _, caller_emp_id = is_employee_caller_session(caller_session_id)
    job = AsyncDispatchJob(
        job_id=f"disp-{uuid.uuid4().hex[:12]}",
        kind="drive_send",
        mode="send",
        caller_session_id=caller_session_id,
        caller_employee_id=caller_emp_id,
        caller_cwd=caller_cwd or os.getcwd(),
        target_session_id=target_session_id,
        target_name=target_name,
        employee_id=None,
        agent=agent,
        cwd=cwd,
        prompt=prompt,
        task_summary=prompt[:240],
        timeout=int(timeout),
        status="running",
        turn_seq=_next_turn_seq_for_target(
            target_session_id,
            agent_kernel=agent,
            origin="terminal",
        ),
    )
    job_path = save_dispatch_job(job)
    supersede_active_jobs_for_target(
        target_session_id,
        new_job_id=job.job_id,
        caller_session_id=caller_session_id,
    )
    _spawn_detached_watcher(
        job_path,
        target_session_id=target_session_id,
        target_employee_id=None,
    )
    return job


def _execute_employee_job(job: AsyncDispatchJob) -> tuple[int, str, str]:
    """在后台 watcher 中执行同侪员工回合。"""
    import inspect

    import frago.cli.employee_commands as emp_cli
    from frago.employee import get_post, save_post
    from frago.session.session_origin import record_relation

    fn = emp_cli._run_agent_turn_for_employee
    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {
        "cwd": job.cwd,
        "timeout_s": float(job.timeout or 0.0),
    }
    if "session_id" in sig.parameters:
        kwargs["session_id"] = job.target_session_id
    if "employee_id" in sig.parameters:
        kwargs["employee_id"] = job.employee_id

    old_target = job.target_session_id
    real_sid, turn_status, answer_text = fn(job.agent, job.prompt, **kwargs)
    resolved_sid = (
        (_resolve_bound_session_id(real_sid)[0] if real_sid else None)
        or _resolve_bound_session_id(old_target)[0]
        or real_sid
        or old_target
    )
    if resolved_sid and resolved_sid != old_target:
        job.target_session_id = resolved_sid
        if job.target_name == old_target:
            job.target_name = resolved_sid
        save_dispatch_job(job)
    elif resolved_sid:
        job.target_session_id = resolved_sid

    with contextlib.suppress(Exception):
        record_relation(
            kind="dispatch",
            child_session_id=job.target_session_id,
            parent_session_id=job.caller_session_id,
            agent_type=job.agent,
            cwd=job.cwd,
            prompt_head=job.task_summary,
        )

    if job.employee_id and job.target_session_id:
        with contextlib.suppress(Exception):
            rec = get_post(job.employee_id)
            if rec is not None:
                cleaned_ids = [
                    s for s in rec.active_session_ids if s and s != old_target
                ]
                if job.target_session_id not in cleaned_ids:
                    cleaned_ids.append(job.target_session_id)
                if cleaned_ids != rec.active_session_ids:
                    rec.active_session_ids = cleaned_ids
                    save_post(rec)

    ok = turn_status == "ok"
    clean_ans = str(answer_text or "").strip()
    if ok:
        err = ""
    else:
        err = (
            f"Employee turn ended with status '{turn_status}': {clean_ans}"
            if clean_ans
            else f"Employee turn ended with status '{turn_status}'"
        )
    _closeout_dispatch_target(
        job,
        turn_status=turn_status,
        answer_text=clean_ans,
        error_text=err,
        old_target=old_target,
    )
    rc = 0 if ok else (2 if turn_status == "needs_input" else 1)
    return rc, clean_ans, err


def _execute_worker_job(job: AsyncDispatchJob) -> tuple[int, str, str]:
    """在后台 watcher 中执行下属 Worker 回合。"""
    import inspect

    import frago.cli.agent_command as agent_cli
    from frago.session.session_origin import record_relation

    old_target = job.target_session_id
    fn = agent_cli._run_worker_turn_sync
    sig = inspect.signature(fn)
    worker_kwargs: dict[str, Any] = {
        "agent_type": job.agent,
        "session_id": job.target_session_id,
        "native_session_id": bool(job.resume),
        "cwd": job.cwd,
        "timeout": int(job.timeout or 0),
        "model": job.model,
        "env_list": job.env_list,
    }
    if "profile_id" in sig.parameters:
        worker_kwargs["profile_id"] = job.profile_id
    real_sid, turn_status, answer_text = fn(
        job.prompt,
        **worker_kwargs,
    )
    resolved_sid = (
        (_resolve_bound_session_id(real_sid)[0] if real_sid else None)
        or _resolve_bound_session_id(old_target)[0]
        or real_sid
        or old_target
    )
    if resolved_sid and resolved_sid != old_target:
        job.target_session_id = resolved_sid
        if job.target_name == old_target:
            job.target_name = resolved_sid
        save_dispatch_job(job)
    elif resolved_sid:
        job.target_session_id = resolved_sid

    with contextlib.suppress(Exception):
        record_relation(
            kind="dispatch",
            child_session_id=job.target_session_id,
            parent_session_id=job.caller_session_id,
            agent_type=job.agent,
            cwd=job.cwd,
            prompt_head=job.task_summary,
        )

    ok = turn_status == "ok"
    clean_ans = str(answer_text or "").strip()
    if ok:
        err = ""
    else:
        err = (
            f"Worker turn ended with status '{turn_status}': {clean_ans}"
            if clean_ans
            else f"Worker turn ended with status '{turn_status}'"
        )
    _closeout_dispatch_target(
        job,
        turn_status=turn_status,
        answer_text=clean_ans,
        error_text=err,
        old_target=old_target,
    )
    rc = 0 if ok else (2 if turn_status == "needs_input" else 1)
    return rc, clean_ans, err


def _execute_drive_send_job(job: AsyncDispatchJob) -> tuple[int, str, str]:
    """在后台 watcher 中执行 ``frago agent send`` 并等待目标回合完成。"""
    from frago.agent_driver.driver import load_driver
    from frago.cli.drive_command import (
        _bind_session,
        _refresh_tmux_name,
        _resolve_or_die,
        _try_clear_residual_input,
        make_runner,
    )

    name = job.target_name or job.target_session_id
    try:
        entry = _resolve_or_die(name)
        runner = make_runner()
        driver = load_driver(entry.agent_type)
        session = _bind_session(entry, driver, runner)
        pane = session.capture_pane()
        healed = False
        if not driver.ready_signal.matches(pane):
            pane, healed = _try_clear_residual_input(session, driver, pane)
        if not (healed or driver.ready_signal.matches(pane)):
            err_msg = f"Session {name!r} is not ready for input"
            _closeout_dispatch_target(job, turn_status="error", error_text=err_msg)
            return 1, "", err_msg
        result = session.send(
            job.prompt,
            timeout_s=float(job.timeout) if job.timeout and job.timeout > 0 else None,
        )
        _refresh_tmux_name(entry, session)
        norm_status = str(result.status or "ok").strip().lower()
        ok = norm_status == "ok"
        ans = str(result.text or "").strip()
        err_msg = "" if ok else f"status={norm_status}"
        _closeout_dispatch_target(
            job,
            turn_status=norm_status,
            answer_text=ans,
            error_text=err_msg,
        )
        rc = 0 if ok else (2 if norm_status == "needs_input" else 1)
        return rc, ans, err_msg
    except Exception as exc:
        _closeout_dispatch_target(job, turn_status="error", error_text=str(exc))
        return 1, "", str(exc)


def _apply_task_interval_report(
    job: AsyncDispatchJob,
    raw_output: str,
    *,
    baseline_seq: int | None,
) -> str:
    """统一提取当次任务区间全部实质 assistant 正文，并在超限/多轮时旁路落盘只读报告。"""
    resolved_sid = _resolve_bound_session_id(job.target_session_id)[0] or job.target_session_id
    report = extract_task_interval_report(
        resolved_sid,
        baseline_seq=baseline_seq,
        fallback_text=raw_output,
        threshold=_CALLBACK_BODY_MAX_CHARS,
        head_chars=_CALLBACK_BODY_HEAD_CHARS,
        offload=True,
        job_id=job.job_id,
        base_home=frago_home(),
    )
    job.report_file = report.report_file
    job.report_total_chars = report.total_chars
    job.report_truncated = report.truncated
    return report.full_text


def execute_dispatch_job(job_path: Path) -> AsyncDispatchJob | None:
    """后台 watcher 主流程：执行目标回合 -> 等待子级联任务 -> 组装报文并回投父会话。"""
    job = load_dispatch_job(job_path)
    if job is None:
        return None

    superseded, sup_by = is_job_superseded(job)
    if superseded:
        return _mark_job_superseded(job, superseded_by=sup_by)

    orig_env = dict(os.environ)
    try:
        # 清洗当前后台进程环境变量，确保子回合内 resolve_self() 指向 target_session_id
        cleaned = sanitize_child_env(
            os.environ,
            target_session_id=job.target_session_id,
            target_employee_id=job.employee_id,
        )
        for k in list(os.environ.keys()):
            if k in SESSION_IDENTITY_ENV or k in ("FRAGO_CALLBACK_SESSION_ID", "FRAGO_EMPLOYEE_ID", "FRAGO_LAUNCH_HANDLE"):
                os.environ.pop(k, None)
        for k, v in cleaned.items():
            os.environ[k] = v

        job.watcher_pid = os.getpid()
        job.status = "running"
        save_dispatch_job(job)

        if job.kind == "worker" and job.mode == "new":
            baseline_seq: int | None = 0
        else:
            pre_sid = _resolve_bound_session_id(job.target_session_id)[0] or job.target_session_id
            baseline_seq = current_next_seq(pre_sid)

        try:
            if job.kind == "employee":
                rc, out, err = _execute_employee_job(job)
            elif job.kind == "drive_send":
                rc, out, err = _execute_drive_send_job(job)
            else:
                rc, out, err = _execute_worker_job(job)

            superseded, sup_by = is_job_superseded(job)
            if superseded:
                return _mark_job_superseded(job, superseded_by=sup_by)

            # 多跳屏障：若目标会话（如同侪员工 B）在回合内又发起了子异步派发，等待其收口并提取最终结论
            cascaded_out = wait_for_pending_child_dispatches(
                job.target_session_id,
                timeout_s=float(job.timeout or 1800.0),
            )
            if cascaded_out:
                out = cascaded_out

            full_out = _apply_task_interval_report(
                job,
                out or "",
                baseline_seq=baseline_seq,
            )

            job.exit_code = int(rc)
            job.output = full_out
            job.error = err or ""
            job.status = "running"
            save_dispatch_job(job)
        except Exception as exc:
            superseded, sup_by = is_job_superseded(job)
            if superseded:
                return _mark_job_superseded(job, superseded_by=sup_by)
            _closeout_dispatch_target(
                job,
                turn_status="error",
                error_text=str(exc),
            )
            job.exit_code = 1
            job.error = str(exc)
            job.status = "running"
            save_dispatch_job(job)

        superseded, sup_by = is_job_superseded(job)
        if superseded:
            return _mark_job_superseded(job, superseded_by=sup_by)

        # 后台子任务已完成：立刻让出执行态，进入独立的 CallbackInbox（status="delivering", delivery_state="queued"）
        job.status = "delivering"
        job.delivery_state = "queued"
        job.worker_finished_at = job.worker_finished_at or _utc_now()
        save_dispatch_job(job)
        register_active_callback_caller(job.caller_session_id)

        callback_prompt = format_callback_prompt(job)
        delivered = False
        delivery_err: str | None = None
        try:
            delivered = deliver_callback_to_session(
                job.caller_session_id,
                callback_prompt,
                job_id=job.job_id,
                cwd_hint=job.caller_cwd,
            )
        except Exception as exc:
            delivered = False
            delivery_err = str(exc)

        cur_job = load_dispatch_job(job.job_id) or job
        if delivered:
            if cur_job.delivery_state != "delivered":
                if cur_job.delivery_state == "queued":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="queued",
                        to_state="delivering",
                        prior_delivery_state=cur_job.delivery_state,
                    )
                    cur_job = load_dispatch_job(job.job_id) or cur_job
                if cur_job.delivery_state == "delivering":
                    record_callback_delivery_outcome(
                        job.job_id,
                        from_state="delivering",
                        to_state="delivered",
                        prior_delivery_state=cur_job.delivery_state,
                    )
            target_status = "completed" if job.exit_code == 0 else "failed"
            finalize_dispatch_job(
                job.job_id,
                exit_code=job.exit_code,
                delivery_state="delivered",
                job_status=target_status,
                prior_delivery_state="delivered",
            )
            _refresh_caller_callback_index(job.caller_session_id)
        else:
            if cur_job.delivery_state == "delivering":
                record_callback_delivery_outcome(
                    job.job_id,
                    from_state="delivering",
                    to_state="queued",
                    reason=delivery_err or "Deferred in CallbackInbox for idle batch or TurnSubmit hitchhike",
                    prior_delivery_state=cur_job.delivery_state,
                )
            register_active_callback_caller(job.caller_session_id)

        reloaded = load_dispatch_job(job.job_id)
        if reloaded is not None:
            job = reloaded
        sys.stderr.write(
            f"[{_utc_now()}] [watcher-finalize] job={job.job_id} worker_rc={job.exit_code} "
            f"delivery_state={job.delivery_state} job_status={job.status} error={job.delivery_error or job.error}\n"
        )
        sys.stderr.flush()
        return job
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    job_file: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--job-file" and i + 1 < len(args):
            job_file = args[i + 1]
            i += 2
        else:
            i += 1
    if not job_file:
        return 2
    job = execute_dispatch_job(Path(job_file))
    return 0 if job is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
