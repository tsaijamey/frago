"""独立 ``CallbackInbox`` 空闲合并投递调度器（Option A 路径 1）。

与人类 ``Next Task`` 队列（``workbench_queue.py``）严格物理分轨：
- 唯一权威状态真源为 ``AsyncDispatchJob`` / ``CallbackDeliveryProcess``；
- 严格遵守三类优先级硬闸：
  ``Tier 1（人类主动输入 / Next Task） > Tier 2（待拍板交互决策卡） > Tier 3（子会话异步回执）``；
- 对满足闲态条件的发起方会话执行防抖合并（默认 400ms）、跨进程锁原子认领（``queued -> delivering``）、
  历史幂等去重、批量信封（``<frago-async-callbacks>``）投递，以及失败回退（``delivering -> queued``）。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Sequence
from typing import Any

from frago.server.services import workbench_queue
from frago.session import async_dispatch, record_reader

logger = logging.getLogger(__name__)

_DEBOUNCE_TIMERS_LOCK = threading.Lock()
_DEBOUNCE_TIMERS: dict[str, threading.Timer] = {}


def _record_field(rec: Any, key: str) -> Any:
    if isinstance(rec, dict):
        return rec.get(key)
    return getattr(rec, key, None)


def _record_text(rec: Any) -> str:
    payload = _record_field(rec, "payload")
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text
        content = payload.get("content")
        if isinstance(content, str):
            return content
    return ""


def _is_callback_already_in_history(
    session_id: str,
    job_id: str,
    *,
    records: Sequence[Any] | None = None,
) -> bool:
    """检查发起方会话历史里是否已真实收到过同 ``job_id`` 的回执（严格只看 user.say / context.inject）。"""
    jid = (job_id or "").strip()
    if not jid:
        return False
    if records is None:
        try:
            records = record_reader.read_records(session_id, limit=500)
        except Exception:  # noqa: BLE001
            return False

    single_pat = re.compile(rf'<frago-async-callback\b[^>]*\bjob_id="{re.escape(jid)}"')
    batch_id_pat = re.compile(
        rf'\bjob_id=(?:"{re.escape(jid)}"|{re.escape(jid)}(?![A-Za-z0-9_.-]))'
    )
    for rec in records:
        kind = str(_record_field(rec, "kind") or "")
        if kind not in ("user.say", "context.inject"):
            continue
        text = _record_text(rec)
        if not text:
            continue
        if single_pat.search(text):
            return True
        if "<frago-async-callbacks" in text and batch_id_pat.search(text):
            return True
    return False


def callback_inbox_blocked_reason(
    session_id: str,
    *,
    records: Sequence[Any] | None = None,
    check_inject_lock: bool = True,
) -> str | None:
    """评估此刻 ``CallbackInbox`` 是否被高优先级门禁阻塞。

    返回 ``None`` 表示安全空闲可投递；否则返回具体阻塞原因码：
    ``blocked_by_card`` / ``human_queue_pending`` / ``injecting`` / ``session_busy`` / ``not_stopped``。
    """
    sid = (session_id or "").strip()
    if not sid:
        return "invalid_session"

    if records is None:
        try:
            records = record_reader.read_records(sid, tail=True, limit=200)
        except Exception:  # noqa: BLE001
            records = []

    if workbench_queue.has_interactive_card_in_tail_turns(
        records, window=workbench_queue.TAIL_TURN_WINDOW
    ):
        return "blocked_by_card"

    if len(workbench_queue.list_queue(sid)) > 0:
        return "human_queue_pending"

    if check_inject_lock:
        directory = workbench_queue.queue_dir(sid)
        persisted_state = workbench_queue._read_queue_state(directory)
        if workbench_queue._is_cross_process_injecting(sid, persisted_state):
            return "injecting"

    if workbench_queue.is_session_busy(sid):
        return "session_busy"

    if records and workbench_queue.detect_stop_turn_id(records) is None:
        return "not_stopped"

    return None


def try_deliver_callback_inbox(
    caller_session_id: str,
    *,
    debounce_ms: int = async_dispatch.CALLBACK_INBOX_DEBOUNCE_MS,
    records: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """尝试在安全空闲窗口内原子认领并合并投递 ``caller_session_id`` 的 ``CallbackInbox``。"""
    sid = (caller_session_id or "").strip()
    if not sid:
        return {"delivered": False, "reason": "invalid_session", "delivered_job_ids": [], "count": 0}

    with workbench_queue.cross_process_inject_guard(sid) as acquired:
        if not acquired:
            return {"delivered": False, "reason": "injecting", "delivered_job_ids": [], "count": 0}

        if records is None:
            try:
                records = record_reader.read_records(sid, tail=True, limit=500)
            except Exception:  # noqa: BLE001
                records = []

        reason = callback_inbox_blocked_reason(
            sid,
            records=records,
            check_inject_lock=False,
        )
        if reason is not None:
            return {"delivered": False, "reason": reason, "delivered_job_ids": [], "count": 0}

        # 先尝试自愈超时卡在 delivering 的遗留项，再按防抖窗口原子认领 queued 批次
        async_dispatch.recover_stale_delivering_callbacks(sid)
        claimed = async_dispatch.claim_ready_callbacks_for_session(
            sid,
            delivery_channel="idle_batch",
            has_human_next_task=False,
            blocked_by_card=False,
            is_session_busy=False,
            debounce_ms=debounce_ms,
        )
        if not claimed:
            pending_queued = async_dispatch.list_callback_inbox_jobs(sid, states=("queued",))
            if pending_queued and debounce_ms > 0:
                now_ms = int(time.time() * 1000)
                newest_ms = max(
                    (
                        async_dispatch._iso_to_epoch_ms(j.worker_finished_at)
                        or async_dispatch._iso_to_epoch_ms(j.updated_at)
                        or async_dispatch._iso_to_epoch_ms(j.created_at)
                        or now_ms
                    )
                    for j in pending_queued
                )
                remaining_ms = max(1, debounce_ms - max(0, now_ms - newest_ms))
                return {
                    "delivered": False,
                    "reason": "debouncing",
                    "remaining_debounce_ms": remaining_ms,
                    "delivered_job_ids": [],
                    "count": 0,
                }
            return {
                "delivered": False,
                "reason": "debouncing" if pending_queued else "empty",
                "delivered_job_ids": [],
                "count": 0,
            }

        already_delivered: list[async_dispatch.AsyncDispatchJob] = []
        to_send: list[async_dispatch.AsyncDispatchJob] = []
        for job in claimed:
            if _is_callback_already_in_history(sid, job.job_id, records=records):
                already_delivered.append(job)
            else:
                to_send.append(job)

        if already_delivered:
            async_dispatch.finalize_claimed_callbacks(sid, already_delivered, success=True)

        if not to_send:
            return {
                "delivered": True,
                "deduped": True,
                "reason": "deduped_already_present",
                "delivered_job_ids": [j.job_id for j in already_delivered],
                "count": 0,
            }

        # 发送前再次确认没有在窗口期间突发写入人类 Next Task 或交互卡
        if len(workbench_queue.list_queue(sid)) > 0:
            async_dispatch.finalize_claimed_callbacks(
                sid, to_send, success=False, reason="Deferred: human Next Task arrived before send"
            )
            return {
                "delivered": False,
                "reason": "human_queue_pending",
                "delivered_job_ids": [j.job_id for j in already_delivered],
                "count": 0,
            }

        batch_prompt = async_dispatch.format_callback_batch_prompt(
            to_send,
            delivery="idle-batch",
        )
        cwd_hint = next((j.caller_cwd for j in to_send if j.caller_cwd), None)
        sent = False
        send_err: str | None = None
        try:
            sent = bool(workbench_queue._send_prompt(sid, batch_prompt, cwd_hint))
        except Exception as exc:  # noqa: BLE001
            sent = False
            send_err = str(exc)
            logger.warning(
                "CallbackInbox 合并投递失败，回退 queued（session=%s, count=%d, err=%s）",
                sid,
                len(to_send),
                send_err,
            )

        if sent:
            cancel_debounced_callback_drain(sid)
            async_dispatch.finalize_claimed_callbacks(sid, to_send, success=True)
            return {
                "delivered": True,
                "reason": "delivered",
                "delivered_job_ids": [j.job_id for j in claimed],
                "count": len(to_send),
            }

        async_dispatch.finalize_claimed_callbacks(
            sid,
            to_send,
            success=False,
            reason=send_err or "Target session did not accept callback batch",
        )
        return {
            "delivered": False,
            "reason": "send_failed",
            "error": send_err or "not_accepted",
            "delivered_job_ids": [j.job_id for j in already_delivered],
            "count": 0,
        }


def cancel_debounced_callback_drain(caller_session_id: str) -> None:
    """取消指定发起方会话尚未触发的防抖延迟合并投递定时器。"""
    sid = (caller_session_id or "").strip()
    if not sid:
        return
    with _DEBOUNCE_TIMERS_LOCK:
        timer = _DEBOUNCE_TIMERS.pop(sid, None)
    if timer is not None:
        timer.cancel()


def schedule_debounced_callback_drain(
    caller_session_id: str,
    *,
    delay_ms: int = async_dispatch.CALLBACK_INBOX_DEBOUNCE_MS,
    debounce_ms: int = async_dispatch.CALLBACK_INBOX_DEBOUNCE_MS,
) -> int:
    """为发起方会话调度单次防抖合并投递；窗口内新回执到达时重置计时器以自然合批。"""
    sid = (caller_session_id or "").strip()
    if not sid:
        return 0
    wait_ms = max(20, int(delay_ms) + 20)

    def _fire() -> None:
        with _DEBOUNCE_TIMERS_LOCK:
            if _DEBOUNCE_TIMERS.get(sid) is timer:
                _DEBOUNCE_TIMERS.pop(sid, None)
        try:
            outcome = try_deliver_callback_inbox(sid, debounce_ms=debounce_ms)
            if outcome.get("reason") == "debouncing":
                remaining = int(outcome.get("remaining_debounce_ms") or debounce_ms)
                schedule_debounced_callback_drain(
                    sid,
                    delay_ms=remaining,
                    debounce_ms=debounce_ms,
                )
        except Exception:  # noqa: BLE001
            logger.warning("防抖合并投递异常（session=%s）", sid, exc_info=True)

    timer = threading.Timer(wait_ms / 1000.0, _fire)
    timer.daemon = True
    with _DEBOUNCE_TIMERS_LOCK:
        old = _DEBOUNCE_TIMERS.pop(sid, None)
        _DEBOUNCE_TIMERS[sid] = timer
    if old is not None:
        old.cancel()
    timer.start()
    return wait_ms


def patrol_callback_inboxes(
    *,
    debounce_ms: int = async_dispatch.CALLBACK_INBOX_DEBOUNCE_MS,
) -> list[str]:
    """巡检所有存在待投递回执的发起方会话，安全空闲时合并投递。"""
    delivered_sids: list[str] = []
    callers = sorted(async_dispatch.list_active_callback_callers())
    for sid in callers:
        try:
            async_dispatch.recover_stale_delivering_callbacks(sid)
            pending = async_dispatch.list_callback_inbox_jobs(sid, states=("queued", "delivering"))
            if not pending:
                async_dispatch.unregister_active_callback_caller(sid)
                continue
            outcome = try_deliver_callback_inbox(
                sid,
                debounce_ms=debounce_ms,
            )
            if outcome.get("delivered"):
                delivered_sids.append(sid)
        except Exception:  # noqa: BLE001
            logger.warning("巡检 CallbackInbox 异常（session=%s）", sid, exc_info=True)
    return delivered_sids
