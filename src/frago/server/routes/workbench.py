"""会话工作台的接口：四个只读 + 一个发送（spec 20260729-session-workbench-webui）。

只读那四个只做取用与序列化：把 :mod:`frago.session.record_reader` 给的数据类拍成
JSON，把它抛的异常翻成状态码。记录归类、字段推导、家族判定这些全在核心数据层做完了，
本模块 NEVER 重做一遍——重做两份判据迟早会各走各的。

发送那一个（``POST /workbench/sessions/{sid}/send``）从 ``/api/claude-sessions`` 那边
搬了过来，同时补上了另外两家。搬家的理由是名字得说真话：那条路的名字写着 claude，
而工作台的清单里躺着三家的会话，人对着 codex 的一行说话，请求却发去一个叫
claude-sessions 的地方，谁读都会以为发错了。判家族、查工作目录、挑 driver 都在
``services.session_send`` 里做完，本模块只做解码图片与翻状态码。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import stat
import subprocess
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from frago.agent_driver.tmux_session import TmuxSendError
from frago.employee import (
    EmployeeOntologyService,
    default_employee_color,
    employees_dir,
    get_post,
    list_posts,
    resolve_avatar_state,
    resolve_session_employee_id,
    save_post,
)
from frago.server.services import (
    callback_inbox_dispatcher,
    coreagent_runner,
    file_history,
    session_send,
    workbench_agents,
    workbench_branch,
    workbench_groups,
    workbench_handoff,
    workbench_new_session,
    workbench_pins,
    workbench_queue,
    workbench_titles,
    workbench_today,
    workbench_views,
)
from frago.server.services.system_service import SystemService, UnsupportedPlatformError
from frago.server.services.webui_uploads import (
    ImageUploadError,
    build_prompt_with_attachments,
    resolve_uploaded_image,
    save_uploaded_documents,
    save_uploaded_images,
)
from frago.session import record_reader, session_files
from frago.session import search as session_search
from frago.session.engine_cli import EngineCliFailed, EngineCliMissing
from frago.session.record_reader import DEFAULT_LIMIT, UnknownSessionFamily
from frago.skills.skill_prompt import UnknownSkill, embed_skills, load_skills

router = APIRouter()

_OBSERVER_DECISION_CACHE: dict[str, tuple[tuple[int, int], tuple[bool, bool]]] = {}
_TRAILING_CARD_CACHE: dict[str, tuple[int, bool]] = {}
_RECENT_DECISION_WINDOW_MS = 24 * 60 * 60 * 1000
_DISPATCH_STARTUP_GRACE_MS = 60_000
_DISPATCH_STALE_DELIVERING_MS = 1_800_000
_DISPATCH_REPLY_OVERTAKEN_GRACE_MS = 5_000


def _iso_to_epoch_ms(raw: str | None) -> int | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


logger = logging.getLogger(__name__)


def _callback_inbox_summaries_by_caller() -> dict[str, dict[str, Any]]:
    """构建每个存在待消化异步回执的发起方会话 ``CallbackInbox`` 只读摘要映射。"""
    try:
        from frago.session.async_dispatch import list_dispatch_jobs

        jobs = list_dispatch_jobs(active_only=False)
        grouped: dict[str, list[Any]] = {}
        for job in jobs:
            if (job.status or "").strip().lower() != "delivering":
                continue
            ds = (getattr(job, "delivery_state", "queued") or "queued").strip().lower()
            if ds not in ("queued", "delivering"):
                continue
            cid = (job.caller_session_id or "").strip()
            if cid:
                grouped.setdefault(cid, []).append(job)

        summaries: dict[str, dict[str, Any]] = {}
        for cid, items in grouped.items():
            items.sort(
                key=lambda j: (
                    getattr(j, "worker_finished_at", None) or j.updated_at or j.created_at,
                    j.created_at,
                    j.job_id,
                )
            )
            blocked_reason = None
            with contextlib.suppress(Exception):
                blocked_reason = callback_inbox_dispatcher.callback_inbox_blocked_reason(cid)
            summaries[cid] = {
                "count": len(items),
                "blocked_reason": blocked_reason,
                "items": [
                    {
                        "job_id": j.job_id,
                        "kind": j.kind,
                        "mode": j.mode,
                        "target_session_id": j.target_session_id,
                        "target_name": j.target_name,
                        "employee_id": j.employee_id,
                        "task_summary": j.task_summary,
                        "exit_code": j.exit_code,
                        "delivery_state": (getattr(j, "delivery_state", "queued") or "queued"),
                        "worker_finished_at": getattr(j, "worker_finished_at", None),
                        "updated_at": j.updated_at,
                    }
                    for j in items
                ],
            }
        return summaries
    except Exception:  # noqa: BLE001
        logger.debug("构建 CallbackInbox 只读摘要失败", exc_info=True)
        return {}


def _dispatch_states_by_caller(
    active_target_ids: set[str] | None = None,
    caller_last_reply_ms: dict[str, int] | None = None,
    now_ms: int | None = None,
) -> tuple[set[str], set[str]]:
    """一次扫描异步派发单并校验真实活性与时序，返回 (有运行中子任务的主会话集合, 有排队/送达中回调的主会话集合)。"""
    try:
        from frago.session.async_dispatch import list_dispatch_jobs

        jobs = list_dispatch_jobs(active_only=False)
        if not jobs:
            return set(), set()

        live_targets = active_target_ids or set()
        reply_map = caller_last_reply_ms or {}
        cur_ms = now_ms if now_ms is not None else int(time.time() * 1000)

        def _is_live_running(job: Any) -> bool:
            tid = (job.target_session_id or "").strip()
            if tid and tid in live_targets:
                return True
            wpid = getattr(job, "watcher_pid", None)
            if isinstance(wpid, int) and wpid > 0:
                from frago.session.service import _pid_is_alive

                if _pid_is_alive(wpid):
                    return True
            created_ms = _iso_to_epoch_ms(getattr(job, "created_at", None))
            return created_ms is not None and (cur_ms - created_ms) <= _DISPATCH_STARTUP_GRACE_MS

        # 1. 识别真正活跃的 pending/running 任务，并沿两级嵌套派发链向上传递活性
        running_callers: set[str] = set()
        for job in jobs:
            st = (job.status or "").strip().lower()
            cid = (job.caller_session_id or "").strip()
            if cid and st in ("pending", "running") and _is_live_running(job):
                running_callers.add(cid)

        changed = True
        while changed:
            changed = False
            for job in jobs:
                st = (job.status or "").strip().lower()
                if st not in ("pending", "running"):
                    continue
                cid = (job.caller_session_id or "").strip()
                tid = (job.target_session_id or "").strip()
                if cid and tid in running_callers and cid not in running_callers:
                    running_callers.add(cid)
                    changed = True

        # 2. 识别真正待投递的 callback（严格排除 superseded/failed/cancelled、僵尸 delivering 与已被主会话新回复超越的单据）
        callback_callers: set[str] = set()
        for job in jobs:
            st = (job.status or "").strip().lower()
            if st in ("superseded", "failed", "cancelled"):
                continue
            cid = (job.caller_session_id or "").strip()
            if not cid:
                continue
            ds = (getattr(job, "delivery_state", None) or "").strip().lower()
            is_cb = st == "delivering" or (st == "completed" and ds in ("queued", "delivering"))
            if not is_cb:
                continue

            tid = (job.target_session_id or "").strip()
            completed_ms = _iso_to_epoch_ms(getattr(job, "completed_at", None))
            updated_ms = _iso_to_epoch_ms(getattr(job, "updated_at", None))
            if (
                st == "delivering"
                and completed_ms is None
                and updated_ms is not None
                and (cur_ms - updated_ms) > _DISPATCH_STALE_DELIVERING_MS
                and tid not in live_targets
            ):
                continue

            job_ts_ms = completed_ms or updated_ms
            last_reply = reply_map.get(cid)
            if (
                job_ts_ms is not None
                and last_reply is not None
                and last_reply > job_ts_ms + _DISPATCH_REPLY_OVERTAKEN_GRACE_MS
            ):
                continue

            callback_callers.add(cid)
        return running_callers, callback_callers
    except Exception:  # noqa: BLE001 — 读取派发账本异常不阻断工作台清单
        return set(), set()


def _observer_slots_state(session_id: str, family: str) -> tuple[bool, bool]:
    """从已落盘的 observer-slots.json 返回 (need_decision, all_tasks_done)。"""
    try:
        from frago.server.services import session_observer

        if family not in session_observer._FAMILY_DIR:
            return False, False
        slots_path = (
            session_observer.session_dir(session_id, family)
            / session_observer.SLOTS_FILENAME
        )
        if not slots_path.is_file():
            return False, False
        st = slots_path.stat()
        key = (st.st_mtime_ns, st.st_size)
        cached = _OBSERVER_DECISION_CACHE.get(str(slots_path))
        if cached is not None and cached[0] == key:
            return cached[1]
        slots = session_observer.load_slots(slots_path.parent, session_id, family)
        fallback_at = (
            slots.get("updated_at") or slots.get("tail_at") or slots.get("anchor_at")
        )
        raw_tasks = slots.get("tasks")
        if isinstance(raw_tasks, list) and raw_tasks:
            tasks = [
                session_observer._normalize_task_item(t, fallback_at)
                for t in raw_tasks
                if isinstance(t, dict)
            ]
        else:
            raw_runs = slots.get("runs")
            base_runs = (
                list(raw_runs)
                if isinstance(raw_runs, list) and raw_runs
                else session_observer._fallback_runs(slots)
            )
            tasks = session_observer._synthesize_tasks(
                slots, session_observer._normalize_runs(base_runs)
            )
        reconciled = session_observer._reconcile_decision_consistency(
            tasks, slots.get("decision")
        )
        doing_cnt = sum(
            1
            for t in tasks
            if isinstance(t, dict) and t.get("status") == session_observer.TASK_STATUS_DOING
        )
        waiting_cnt = sum(
            1
            for t in tasks
            if isinstance(t, dict) and t.get("status") == session_observer.TASK_STATUS_WAITING
        )
        done_cnt = sum(
            1
            for t in tasks
            if isinstance(t, dict) and t.get("status") == session_observer.TASK_STATUS_DONE
        )
        need_dec = bool(reconciled) or waiting_cnt > 0
        all_done = bool(tasks) and doing_cnt == 0 and waiting_cnt == 0 and done_cnt > 0
        result = (need_dec, all_done)
        _OBSERVER_DECISION_CACHE[str(slots_path)] = (key, result)
        return result
    except Exception:  # noqa: BLE001
        return False, False


def _has_trailing_unanswered_card(session_id: str, last_active_at: int) -> bool:
    """检查会话末轮是否存在尚未被人类回答的交互决策卡（带 last_active_at 缓存）。"""
    cached = _TRAILING_CARD_CACHE.get(session_id)
    if cached is not None and cached[0] == last_active_at:
        return cached[1]
    verdict = False
    try:
        from frago.server.services import session_observer, workbench_queue

        recs = record_reader.read_records(session_id, limit=25)
        for rec in reversed(recs):
            if rec.agent_path:
                continue
            if rec.kind == "user.say" and session_observer.spoken_text(rec.payload) is not None:
                break
            if workbench_queue.record_has_interactive_card(rec, recs):
                verdict = True
                break
    except Exception:  # noqa: BLE001
        verdict = False
    _TRAILING_CARD_CACHE[session_id] = (last_active_at, verdict)
    return verdict


def _session_needs_decision(
    card: Any,
    *,
    status: str,
    is_alive: bool,
    has_running_worker: bool,
    callback_queued: bool,
    now_ms: int,
    slots_need_decision: bool | None = None,
    origin: str | None = None,
    is_local_ops: bool = False,
) -> bool:
    """判定会话此刻是否真正存在等待人类拍板的未决事项。"""
    resolved_origin = origin if origin is not None else getattr(card, "origin", "human")
    if (
        has_running_worker
        or callback_queued
        or resolved_origin in {"worker", "schedule"}
        or is_local_ops
        or status == "error"
    ):
        return False
    need_from_slots = (
        slots_need_decision
        if slots_need_decision is not None
        else _observer_slots_state(card.session_id, card.family)[0]
    )
    if need_from_slots:
        return True
    if is_alive or (now_ms - int(getattr(card, "last_active_at", 0) or 0)) <= _RECENT_DECISION_WINDOW_MS:
        return _has_trailing_unanswered_card(
            card.session_id, int(getattr(card, "last_active_at", 0) or 0)
        )
    return False


class _WorkbenchLiveness(Mapping[str, bool]):
    """实时存活视图：tmux 在开或 CoreAgent 正忙即 True，其余明确为 False（避免落回 90 秒窗）。"""

    def __init__(
        self, open_names: set[str], core_alive: Mapping[str, bool], tmux_name_fn: Any
    ) -> None:
        self._open_names = open_names
        self._core_alive = core_alive
        self._tmux_name_fn = tmux_name_fn

    def __getitem__(self, session_id: str) -> bool:
        return (self._tmux_name_fn(session_id) in self._open_names) or (
            self._core_alive.get(session_id) is True
        )

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for name in self._open_names:
            if name.startswith("frago-agent-"):
                sid = name[len("frago-agent-") :]
                if sid and sid not in seen:
                    seen.add(sid)
                    yield sid
        for sid, busy in self._core_alive.items():
            if busy and sid not in seen:
                seen.add(sid)
                yield sid

    def __len__(self) -> int:
        return sum(1 for _ in self)


@router.get("/workbench/sessions")
async def list_workbench_sessions() -> list[dict[str, Any]]:
    """两家的会话合并成一份清单，按最后活动时刻倒序。

    每条卡片带四档状态与两格摘要（已完成 / 卡在）。这三样在核心数据层跟会话索引一起算、
    一起缓存，本模块一个字都不推导——判据摆在两处迟早各走各的。「要你做」那一格判不出来，
    连字段都不给。

    落盘扫描是同步的，丢进工作线程跑，免得清单一慢整个事件循环跟着停。

    ``in_tmux``：这一场此刻开在某个 tmux 会话里，左栏据此给卡片挂流光。**不进核心数据层
    的缓存**——它是 tmux 此刻的样子，不是记录文件推出来的，缓存一轮就不准了。只按名字
    对（``frago-agent-<编号>``），名字是业务把手的飞书、语音会话开着也是 false。

    ``alive``：这一场此刻还活着，判据见 :func:`_still_alive`。会话详情页照它决定要不要
    盯住记录文件、要不要持续取增量。它比 ``in_tmux`` 宽一格，**不要用它替 ``in_tmux``**：
    左栏的流光说的是"终端还开着"，CoreAgent 没有终端、流光不该亮。
    """
    return await collect_workbench_session_rows()


async def collect_workbench_session_rows(
    *,
    filter_employee_id: str | None = None,
) -> list[dict[str, Any]]:
    """复用工作台同源状态机与四级血缘判定，构建会话行；可选按 `employee_id` 过滤以跳过无关卡片开销。"""
    from frago.agent_driver.tmux_session import tmux_name_for
    from frago.server.services import tmux_sessions_service as tsvc
    from frago.session.service import (
        can_write_ontology_store,
        collect_live_runtime_probes,
        evaluate_session_liveness_and_state,
        get_default_session_service,
    )

    # 一次问清哪些 tmux 会话与 CoreAgent 场次还活着，并作为真实存活映射传入 record_reader，
    # 防止无 liveness 调用把刚 start_turn() 的新轮次反手覆写回 error 或被 90 秒窗口吞掉 error。
    open_names, core_alive = await asyncio.gather(
        asyncio.to_thread(tsvc.open_session_names),
        asyncio.to_thread(coreagent_runner.live_states),
    )
    now_s = time.time()
    live_tmux_ids = {
        n[len("frago-agent-") :] for n in open_names if n.startswith("frago-agent-")
    }
    probes = await asyncio.to_thread(
        collect_live_runtime_probes,
        live_tmux_ids=live_tmux_ids,
        core_alive=core_alive,
        now_s=now_s,
    )
    liveness = _WorkbenchLiveness(open_names, core_alive, tmux_name_for)
    sig = inspect.signature(record_reader.list_sessions)
    accepts_liveness = "liveness" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    cards = await asyncio.to_thread(
        record_reader.list_sessions,
        **({"liveness": liveness} if accepts_liveness else {}),
    )
    onto_svc = get_default_session_service()
    onto_by_sid = {
        rec.session_id: rec
        for rec in await asyncio.to_thread(onto_svc.list_sessions)
        if rec.session_id
    }
    now_s = time.time()
    # ``tmux_name``：开着时那个 tmux 会话的名字，页面「关闭 tmux 会话」的弹窗原样摆出来，
    # 命名规则不在前端再抄一份。没开着为 null。
    # 会话页上起过的名字盖在各家自己的标题上（见 ``workbench_titles``）。
    titles = await asyncio.to_thread(workbench_titles.load)
    local_ops_ids = await asyncio.to_thread(workbench_groups.local_ops_session_ids)
    employee_posts = await asyncio.to_thread(list_posts)
    posts_by_id = {post.member_post_id: post for post in employee_posts}
    active_employee_by_sid: dict[str, str] = {
        sid: post.member_post_id
        for post in employee_posts
        for sid in post.active_session_ids
        if sid
    }
    direct_employee_by_sid: dict[str, str] = {}
    parent_by_sid: dict[str, str | None] = {}
    computed_states: list[tuple[Any, str, bool, str, bool, str, bool, str | None]] = []
    running_worker_parents: set[str] = set()
    active_target_ids: set[str] = set()
    caller_last_reply_ms: dict[str, int] = {}
    pending_onto_heals: list[tuple[Any, ...]] = []
    seen_card_sids: set[str] = set()
    for card in cards:
        if not card.session_id or card.session_id in seen_card_sids:
            continue
        seen_card_sids.add(card.session_id)
        parent_by_sid[card.session_id] = card.parent_session_id
        onto_rec = onto_by_sid.get(card.session_id)
        emp_id = (
            card.employee_id
            or (onto_rec.employee_id if onto_rec is not None else None)
            or active_employee_by_sid.get(card.session_id)
        )
        if emp_id:
            direct_employee_by_sid[card.session_id] = emp_id
        name = tmux_name_for(card.session_id)
        alive = name in open_names
        reply_ts = getattr(card, "last_reply_at", None)
        last_reply_s = (
            (reply_ts / 1000.0) if isinstance(reply_ts, int | float) and reply_ts > 0 else None
        )
        ev = evaluate_session_liveness_and_state(
            session_id=card.session_id,
            onto_rec=onto_rec,
            card_status=card.status,
            last_kind=getattr(card, "last_kind", None),
            last_active_s=float(getattr(card, "last_active_at", 0) or 0) / 1000.0,
            last_reply_s=last_reply_s,
            digest_stuck=getattr(card, "digest_stuck", None),
            in_tmux=alive,
            liveness_flag=liveness[card.session_id],
            core_alive=core_alive,
            probes=probes,
            now_s=now_s,
            collapse_unmanaged_dead=True,
        )
        status = ev.ui_status
        lifecycle_state = ev.lifecycle_state
        is_alive = _still_alive(card.session_id, in_tmux=alive, core_alive=core_alive) or (
            ev.actively_running
        )
        if ev.heal_target is not None:
            pending_onto_heals.append(
                (card.session_id, ev.heal_target, ev.heal_summary, ev.heal_waiting_reason)
            )
        if status == "running" or (card.family == "coreagent" and is_alive):
            active_target_ids.add(card.session_id)
        reply_ts = getattr(card, "last_reply_at", None)
        if isinstance(reply_ts, int) and reply_ts > 0:
            caller_last_reply_ms[card.session_id] = reply_ts
        if (
            getattr(card, "origin", "human") == "worker"
            and card.parent_session_id
            and status == "running"
        ):
            running_worker_parents.add(card.parent_session_id)
        abort_reason = (
            ev.heal_summary
            or (getattr(onto_rec, "summary", None) if onto_rec is not None else None)
            or getattr(card, "digest_stuck", None)
        ) if lifecycle_state == "error" else None
        computed_states.append(
            (
                card,
                name,
                alive,
                status,
                is_alive,
                str(lifecycle_state or "completed"),
                bool(ev.tool_aborted),
                str(abort_reason).strip() or None if abort_reason else None,
            )
        )
    if pending_onto_heals and can_write_ontology_store(onto_svc):
        with contextlib.suppress(Exception):
            await asyncio.to_thread(onto_svc.store.batch_reconcile_states, pending_onto_heals)

    def _resolve_employee_id(card: Any) -> str | None:
        direct = direct_employee_by_sid.get(card.session_id)
        if direct:
            return direct
        if getattr(card, "origin", "human") == "worker":
            return None
        cur = getattr(card, "parent_session_id", None)
        visited: set[str] = {card.session_id}
        for _ in range(8):
            if not cur or cur in visited:
                break
            visited.add(cur)
            found = direct_employee_by_sid.get(cur)
            if found:
                return found
            cur = parent_by_sid.get(cur)
        return None

    now_ms = int(time.time() * 1000)

    def _build_rows() -> list[dict[str, Any]]:
        running_callers, callback_callers = _dispatch_states_by_caller(
            active_target_ids=active_target_ids,
            caller_last_reply_ms=caller_last_reply_ms,
            now_ms=now_ms,
        )
        callback_inbox_map = _callback_inbox_summaries_by_caller()
        effective_running_parents = running_worker_parents | running_callers
        built: list[dict[str, Any]] = []
        for (
            card,
            name,
            alive,
            status,
            is_alive,
            lifecycle_state,
            tool_aborted,
            abort_reason,
        ) in computed_states:
            employee_id = _resolve_employee_id(card)
            if filter_employee_id is not None and employee_id != filter_employee_id:
                continue
            slots_need_decision, all_tasks_done = _observer_slots_state(
                card.session_id, card.family
            )
            has_running_worker = card.session_id in effective_running_parents
            callback_queued = card.session_id in callback_callers
            # 与右侧 Observer 进展账本强一致收敛：若总控表全为已办结且会话当前未在跑，强制清零残留的在跑/待回传状态
            if all_tasks_done and status != "running":
                has_running_worker = False
                callback_queued = False
            onto_rec = onto_by_sid.get(card.session_id)
            is_local_ops = card.session_id in local_ops_ids
            effective_origin = getattr(card, "origin", "human")
            if effective_origin != "worker" and (
                (onto_rec is not None and getattr(onto_rec, "origin", None) == "schedule")
                or (is_local_ops and effective_origin == "human")
            ):
                effective_origin = "schedule"
            need_decision = _session_needs_decision(
                card,
                status=status,
                is_alive=is_alive,
                has_running_worker=has_running_worker,
                callback_queued=callback_queued,
                now_ms=now_ms,
                slots_need_decision=slots_need_decision,
                origin=effective_origin,
                is_local_ops=is_local_ops,
            )
            card_data = asdict(card)
            last_kind_val = card_data.pop("last_kind", None)
            matched_post = posts_by_id.get(employee_id) if employee_id else None
            employee_title = (
                matched_post.title if matched_post is not None else employee_id
            )
            employee_color = (
                matched_post.color
                if matched_post is not None
                else (default_employee_color(employee_id) if employee_id else None)
            )
            employee_avatar = (
                resolve_avatar_state(
                    employee_id,
                    matched_post.avatar if matched_post is not None else None,
                    employees_base_dir=employees_dir(),
                )
                if employee_id
                else None
            )
            row = {
                **card_data,
                "origin": effective_origin,
                "status": status,
                "digest_stuck": card.digest_stuck if status == "error" else None,
                "lifecycle_state": lifecycle_state or (
                    "error"
                    if status == "error"
                    else ("running" if status == "running" else "completed")
                ),
                "last_kind": last_kind_val,
                "tool_aborted": tool_aborted,
                "abort_reason": abort_reason,
                "employee_id": employee_id,
                "employee_title": employee_title,
                "employee_color": employee_color,
                "employee_avatar": employee_avatar,
                "raw_title": card.title,
                "custom_title": titles.get(card.session_id),
                "in_tmux": alive,
                "tmux_name": name if alive else None,
                "alive": is_alive,
                "local_ops": is_local_ops,
                "has_running_worker": has_running_worker,
                "callback_queued": callback_queued,
                "callback_inbox": callback_inbox_map.get(card.session_id)
                or {"count": 0, "blocked_reason": None, "items": []},
                "need_decision": need_decision,
            }
            if card.session_id in titles:
                row["title"] = titles[card.session_id]
            built.append(row)
        return built

    rows = await asyncio.to_thread(_build_rows)
    if filter_employee_id is None:
        # 这一场还活着的才盯它的文件（主人 09-30 定的省法：不开着的、点开那一刻取一次最新内容
        # 就够）。清单本来就每 15 秒取一次、手上正好有 tmux 此刻的样子，顺带收一道。
        still_alive = {row["session_id"] for row in rows if row["alive"]}
        await asyncio.to_thread(_keep_watching_only, still_alive)
    return rows


@router.get("/workbench/agents")
async def list_workbench_agents() -> dict[str, Any]:
    """新建会话时能挑哪几家 CLI，各是什么状况。

    **挑不了的也回。** 藏起来等于告诉人"frago 不支持 codex"，而真相往往只是没装；
    每一行都带着挑不了的理由，界面原样转述。判据全在
    :mod:`~frago.server.services.workbench_agents`，本模块一个字都不推导——
    前端再写一张 agent 名单，接新家的人改完 driver 会发现界面上它根本不出现。

    ``default`` 是这台机器上该默认挑哪一家；一家都挑不了时为 null。
    """
    agents = await asyncio.to_thread(workbench_agents.list_agents)
    return {
        "agents": [asdict(agent) for agent in agents],
        "default": workbench_agents.default_agent(agents),
    }


class Document(BaseModel):
    """一份随这条消息附上的文档。

    ``name`` 是用户那边的原文件名，只用来给落盘文件起个有意义的名字——agent 在提示词
    里看到的是路径，路径上带着原名它才知道自己要打开的是什么。

    新建会话与发送共用这一份形状：两条路收的是同一种东西，各写一份迟早各走各的。
    """

    name: str = ""
    data: str = ""


class CreateSessionRequest(BaseModel):
    """``POST /workbench/sessions`` 的请求体。

    ``agent`` 是挑中的那一家（``/workbench/agents`` 里的 ``agent_type``）；
    ``cwd`` 是会话的起始目录；``text`` 是第一句话。

    ``employee`` 是点哪张员工卡片起的这一场。给了编号，服务端就把该员工的业务语境块
    拼在第一句话最前面（见 :func:`_with_employee_context`），人不必每开一场都重述
    「我是谁、我手上有哪些数据」。默认空串，老的调用方一个字都不用改。

    ``images`` 与 ``documents`` 走的是与发送那条接口完全相同的一条路：内容以 base64
    传上来，服务端落盘成真实文件，绝对路径拼进投给 agent 的第一句话。第一句话最需要
    附件——人往往一上来就要交代"照着这张图改"，而从前这里只收文字，那张图只能等会话
    起来之后再补发一次。允许文字为空但带附件。
    """

    agent: str
    cwd: str
    text: str = ""
    images: list[str] = []
    documents: list[Document] = []
    skills: list[str] = []
    employee: str = ""


def _with_employee_context(prompt: str, employee_id: str) -> str:
    """点员工卡片起会话：把该员工的业务语境块拼在这句话最前面。

    排在 skill 块之前，顺序是「员工语境 → skill 正文 → 人的原话」：员工块讲的是这一场
    归谁管、手上有什么，是最外层的框；skill 是这一场具体要用的做法；人的原话收尾。

    编号对不上任何员工就回 400，NEVER 当成没写照样发——人以为这一场带着员工画像起来的，
    实际它什么都没带，等到 agent 答偏了才发现，那时已经查不回原因。
    """
    cleaned = employee_id.strip()
    if not cleaned:
        return prompt
    try:
        block = EmployeeOntologyService().build_business_context_block(cleaned)
    except KeyError as e:
        raise HTTPException(
            status_code=400, detail=f"员工编号 '{cleaned}' 不存在：{e}"
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return f"{block}\n\n{prompt}"


def _with_skills(prompt: str, skills: list[str], user_text: str) -> str:
    """人在输入框里挑了 skill：把每个 skill 的文档路径与全文嵌到这句话前面。

    不走任何一家 agent 的原生点名写法：那些写法四家各不相同，codex 还会把 ``/名字``
    当成它自己的斜杠命令拦下，那句话根本进不了会话。嵌正文四家都认。
    挑中的 skill 在集中副本里找不到就回 400，NEVER 悄悄丢掉它照发——人以为 agent
    在照那个 skill 做，其实它根本没见过。
    """
    if not skills:
        return prompt
    try:
        loaded = load_skills(skills)
    except UnknownSkill as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return embed_skills(prompt, loaded, user_text=user_text)


@router.post("/workbench/sessions", status_code=201)
async def create_workbench_session(request: CreateSessionRequest) -> dict[str, Any]:
    """起一场新会话并投进第一句话，**不等它答完**。

    回的东西有两种形状，因为三家的会话编号来路本来就是两种：

    - ``session_id`` 有值（claude）——编号是页面这边定的，界面直接跳进那一场；
    - ``session_id`` 为 null（codex / opencode）——编号由 agent 自己分配，frago 要等会话
      起来后认领，界面拿 ``handle`` 去 ``/workbench/sessions/pending/{handle}`` 问。

    那段空窗 MUST 如实呈现。假装编号已经有了，界面会跳进一场并不存在的会话，看到的是
    一片空记录流，而人以为自己刚开的会话丢了。

    挑不了的那一家回 400（带上为什么），NEVER 起了再说：人要等上一分钟才看得出这一场
    根本不会出现在左栏。
    """
    if (
        not request.text.strip()
        and not request.images
        and not request.documents
        and not request.skills
    ):
        raise HTTPException(status_code=400, detail="第一句话和附件不能都是空的")

    # 员工自己配了起始目录、而这一场又没另指定，就用员工那一栏：点卡片起会话的场景里
    # 人往往不填目录，期望的是"到那个员工的领地里去"。请求里显式给了目录则以请求为准——
    # 人手上写下的路径比岗位的默认值更贴近这一场要做的事。
    #
    # 这一段排在上面那条「目录不能为空」之前：员工配了目录的场合，请求里那一栏本来就该
    # 允许空着。顺序反了的话，人点卡片起会话会先撞上一个 400，而那个 400 说的正是
    # 岗位已经替他填好的那一栏。
    #
    # 岗位也没配目录时，落到 ``~/.frago``：员工本来就是 frago 自己的一支人马，它的领地
    # 就是 frago 家目录。从前这一档回 400「起始目录不能是空的」，人点卡片起会话、什么都没
    # 填，看到的是一句要他先去填一栏的话——而这一栏本来就该有默认值。
    session_cwd = request.cwd
    employee_record = None
    if request.employee.strip():
        try:
            employee_record = get_post(request.employee.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if employee_record is None:
            raise HTTPException(
                status_code=400, detail=f"员工编号 '{request.employee.strip()}' 不存在"
            )
        if not session_cwd.strip() and employee_record.cwd:
            session_cwd = employee_record.cwd
        if not session_cwd.strip():
            fallback = Path.home() / ".frago"
            # 先建出来再用：这一栏空着就往下传的话，起会话那一步会拿着一个不存在的目录
            # 去挂 TUI，而失败的样子是"会话没起来"，与这一栏的关系谁都看不出来。
            fallback.mkdir(parents=True, exist_ok=True)
            session_cwd = str(fallback)

    if not session_cwd.strip():
        raise HTTPException(status_code=400, detail="起始目录不能是空的")

    # ``~`` 是给人写的，起会话那一步认的是绝对路径。展开放在这一栏的最后一步：前面几处
    # 判空、回退、拼接都按人写下的原样比，展开只做一次，谁都别再各展开一遍。
    session_cwd = str(Path(session_cwd.strip()).expanduser())

    # 这一栏的目录必须在起会话之前真的在盘上。``tmux new-session -c <目录>`` 碰到不存在的
    # 目录不报错，而是静默退回 ``$HOME`` 起会话（见 ``agent_driver/tmux_session.py``）。对
    # 认领型内核（codex / opencode / agy）来说，会话把工作区记成了 ``$HOME``，而认领器一直
    # 拿原来那个目录去比对，两边永远对不上，人看到的只是等 30 秒后一句「会话没起来」，与
    # 这一栏的关系谁都看不出来。
    #
    # frago 家目录下与家目录外分两档处置。家目录下的（``~/.frago``、员工领地
    # ``~/.frago/data/<员工>``、数据槽位）是随用随建的：人点卡片起会话时这些目录多半还
    # 没建过，而这本来就是 frago 自己的地盘。家目录外的一律不替人做主，不存在就当场回
    # 400——把「目录写错了」这句话留在它该出现的地方，而不是让它变形为一次认领超时。
    cwd_path = Path(session_cwd)
    frago_root = (Path.home() / ".frago").resolve()
    resolved_cwd = cwd_path.resolve()
    under_frago = resolved_cwd == frago_root or frago_root in resolved_cwd.parents
    if under_frago:
        if cwd_path.exists() and not cwd_path.is_dir():
            raise HTTPException(status_code=400, detail=f"起始目录不是文件夹：{session_cwd}")
        cwd_path.mkdir(parents=True, exist_ok=True)
    else:
        if not cwd_path.exists():
            raise HTTPException(status_code=400, detail=f"起始目录不存在：{session_cwd}")
        if not cwd_path.is_dir():
            raise HTTPException(status_code=400, detail=f"起始目录不是文件夹：{session_cwd}")

    # 附件要落盘，落盘要有个目录名，而目录名该是这场会话自己的编号——事后回头看
    # ``~/.frago/webui_uploads/`` 时，一眼就知道这几张图是哪一场的。编号在这里先 mint
    # 出来：编号由页面定的那一家（claude）拿它当真编号，由 agent 自己分配编号的那两家
    # （codex / opencode）用不上它，附件目录仍归在这个名字下。
    launch_id = str(uuid.uuid4())
    try:
        image_paths = save_uploaded_images(request.images, launch_id)
        doc_paths = save_uploaded_documents([d.model_dump() for d in request.documents], launch_id)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e
    effective_skills: list[str] = []
    for sk in (*(employee_record.skills if employee_record is not None else ()), *request.skills):
        cleaned_sk = str(sk).strip()
        if cleaned_sk and cleaned_sk not in effective_skills:
            effective_skills.append(cleaned_sk)

    prompt = _with_skills(
        _with_employee_context(
            build_prompt_with_attachments(request.text.strip(), image_paths, doc_paths),
            request.employee,
        ),
        effective_skills,
        request.text,
    )

    try:
        launch = await asyncio.to_thread(
            workbench_new_session.start_with_id,
            request.agent,
            session_cwd,
            prompt,
            session_id=launch_id,
        )
    except workbench_agents.AgentUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if employee_record is not None:
        await asyncio.to_thread(
            workbench_new_session.bind_employee,
            launch.handle,
            employee_record.member_post_id,
        )
        if (
            launch.session_id
            and launch.session_id not in employee_record.active_session_ids
        ):
            employee_record.active_session_ids.append(launch.session_id)
            await asyncio.to_thread(save_post, employee_record)
        from frago.server.services.employee_usage import invalidate_employee_usage_cache

        invalidate_employee_usage_cache(employee_record.member_post_id)

    return _launch_payload(launch)


def _resolve_parent_employee_record(sid: str):
    """解析父会话 `sid` 归属的员工岗位记录（用于从 Employee 会话起分支或交接时保持员工语境幂等）。"""
    clean_sid = str(sid or "").strip()
    if not clean_sid:
        return None
    employee_id = resolve_session_employee_id(clean_sid)
    if not employee_id:
        with workbench_new_session._lock:
            for launch in workbench_new_session._launches.values():
                if launch.employee_id and (
                    launch.session_id == clean_sid or launch.handle == clean_sid
                ):
                    employee_id = launch.employee_id
                    break
    if not employee_id:
        return None
    try:
        return get_post(employee_id)
    except ValueError:
        return None


@router.post("/workbench/sessions/{sid}/handoff", status_code=201)
async def handoff_workbench_session(sid: str) -> dict[str, Any]:
    """把这场会话交接给一场新会话：同一家、同一目录，第一句话由服务端拼好。

    拼法见 :mod:`~frago.server.services.workbench_handoff`。起会话走的是与新建会话完全
    相同的一条路，回的形状也相同——页面接过去就是一次普通的「正在启动」。原会话不动。

    拒绝的几档与发送那条接口同义：编号不认 404；记录没了、问不出目录、接不上话、还没有
    任何记录或同一会话此刻正在交接中 409；那一家此刻挑不了 400。

    **两场各起一个带序号的名字**（原会话「甲 #1」、新会话「甲 #2」），不然左栏并排两场
    说同一件事的会话，人分不清。起名只写 frago 自己那份名字表，原会话的档案一个字不动。
    编号要等认领的那两家（codex / opencode），新会话的名字等认到编号再起。
    """
    try:
        workbench_handoff.acquire_handoff(sid)
    except workbench_handoff.HandoffInProgress as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    try:
        try:
            handoff = await asyncio.to_thread(workbench_handoff.compose, sid)
        except UnknownSessionFamily as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except (
            session_send.SessionGone,
            session_send.SessionNotResumable,
            workbench_handoff.HandoffUnavailable,
        ) as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

        employee_record = await asyncio.to_thread(_resolve_parent_employee_record, sid)
        if employee_record is not None:
            effective_skills = [
                str(sk).strip() for sk in employee_record.skills if str(sk).strip()
            ]
            wrapped_text = _with_skills(
                _with_employee_context(handoff.text, employee_record.member_post_id),
                effective_skills,
                "",
            )
            if wrapped_text != handoff.text:
                handoff = replace(handoff, text=wrapped_text)

        try:
            launch = await asyncio.to_thread(
                workbench_new_session.start_with_id,
                handoff.agent_type,
                handoff.cwd,
                handoff.text,
                session_id=str(uuid.uuid4()),
            )
        except workbench_agents.AgentUnavailable as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        if employee_record is not None:
            await asyncio.to_thread(
                workbench_new_session.bind_employee,
                launch.handle,
                employee_record.member_post_id,
            )
            if (
                launch.session_id
                and launch.session_id not in employee_record.active_session_ids
            ):
                employee_record.active_session_ids.append(launch.session_id)
                await asyncio.to_thread(save_post, employee_record)
            from frago.server.services.employee_usage import invalidate_employee_usage_cache

            invalidate_employee_usage_cache(employee_record.member_post_id)

        old_title, new_title = await asyncio.to_thread(
            workbench_handoff.name_pair, sid, launch, handoff=handoff
        )
        return {
            **_launch_payload(launch),
            "text": handoff.text,
            "old_title": old_title,
            "new_title": new_title,
        }
    finally:
        workbench_handoff.release_handoff(sid)


class UpdateTitleRequest(BaseModel):
    """``PUT /workbench/sessions/{sid}/title`` 的请求体：人改过的标题。"""

    title: str


@router.put("/workbench/sessions/{sid}/title")
async def update_workbench_session_title(sid: str, request: UpdateTitleRequest) -> dict[str, Any]:
    """把人改过的会话标题写进该会话在 ``~/.frago/sessions`` 下的同目录数据文件里。

    编号不属于任何一家回 404；空标题回 400。
    """
    try:
        family = await asyncio.to_thread(record_reader.detect_family, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        saved = await asyncio.to_thread(
            workbench_titles.set_title, sid, request.title, family=family
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"session_id": sid, "title": saved}


@router.post("/workbench/sessions/{sid}/title/generate")
async def generate_workbench_session_title(sid: str) -> dict[str, Any]:
    """点星号按钮：用 CoreAgent 单轮对话生成这场会话的标题，落盘到会话备份目录并返回。

    编号不认回 404；这场会话还没有对话内容回 409；CoreAgent 调用失败回 503。
    """
    try:
        saved = await asyncio.to_thread(workbench_titles.generate_title, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except workbench_titles.TitleGenerationUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except workbench_titles.TitleGenerationFailed as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"session_id": sid, "title": saved}



class BranchRequest(BaseModel):
    """``POST /workbench/sessions/{sid}/branch`` 的请求体：从主线哪段原文分出去、人写的那句话。

    ``record_id`` / ``text`` / ``occurrence`` 与标注同一套（见 ``workbench_marks``）；
    ``images`` / ``documents`` / ``skills`` / ``employee`` 与新建会话及发送接口同一套。
    """

    record_id: str
    text: str
    occurrence: int = 0
    note: str = ""
    images: list[str] = []
    documents: list[Document] = []
    skills: list[str] = []
    employee: str = ""


@router.post("/workbench/sessions/{sid}/branch", status_code=201)
async def branch_workbench_session(sid: str, request: BranchRequest) -> dict[str, Any]:
    """从这场会话圈的一段原文起一场分支会话：同一家、同一目录，第一句话由服务端拼好。

    拼法与记账见 :mod:`~frago.server.services.workbench_branch`。起会话走的是与新建会话、
    交接完全相同的一条路，回的形状也相同，外加几项：

    - ``title``：原地提示里这场分支叫什么（新会话还没有常规标题，先用人写的那句话开头）；
    - ``recorded``：关系账记上没有。编号要等认领的那两家起的时候还不知道，为 null；
    - ``mark_saved``：主线的分支标注存下没有（CoreAgent 那一家存不了，为假）。

    **原会话不改名，页面也不跳**——这是与交接的分别。拒绝的几档与交接同义：编号不认 404；
    记录没了、问不出目录、接不上话、还没有任何记录 409；没写那句话、那一家此刻挑不了 400。
    """
    try:
        anchor, note = workbench_branch.validate(
            request.record_id,
            request.text,
            request.occurrence,
            request.note,
            skills=request.skills,
            employee=request.employee,
            has_attachments=bool(request.images or request.documents),
        )
    except workbench_branch.BranchRequestInvalid as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        branch = await asyncio.to_thread(workbench_branch.compose, sid, anchor, note)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (
        session_send.SessionGone,
        session_send.SessionNotResumable,
        workbench_branch.BranchUnavailable,
    ) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    launch_id = str(uuid.uuid4())
    try:
        image_paths = save_uploaded_images(request.images, launch_id)
        doc_paths = save_uploaded_documents([d.model_dump() for d in request.documents], launch_id)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e

    base_note = request.note.strip() or note
    prompt_note = build_prompt_with_attachments(base_note, image_paths, doc_paths)
    rendered = workbench_branch.render(sid, anchor.text, prompt_note)

    explicit_employee = request.employee.strip()
    if explicit_employee:
        try:
            employee_record = await asyncio.to_thread(get_post, explicit_employee)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if employee_record is None:
            raise HTTPException(
                status_code=400, detail=f"员工编号 '{explicit_employee}' 不存在"
            )
        from frago.ontology.projectors import list_agent_kernels

        if employee_record.agent_kernel in list_agent_kernels():
            branch = replace(branch, agent_type=employee_record.agent_kernel)
    else:
        employee_record = await asyncio.to_thread(_resolve_parent_employee_record, sid)

    effective_skills: list[str] = []
    for sk in (*(employee_record.skills if employee_record is not None else ()), *request.skills):
        cleaned_sk = str(sk).strip()
        if cleaned_sk and cleaned_sk not in effective_skills:
            effective_skills.append(cleaned_sk)

    prompt = _with_skills(
        _with_employee_context(
            rendered,
            employee_record.member_post_id if employee_record is not None else "",
        ),
        effective_skills,
        request.note,
    )
    if prompt != branch.text:
        branch = replace(branch, text=prompt)

    try:
        launch = await asyncio.to_thread(
            workbench_new_session.start_with_id,
            branch.agent_type,
            branch.cwd,
            branch.text,
            session_id=launch_id,
        )
    except workbench_agents.AgentUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if employee_record is not None:
        await asyncio.to_thread(
            workbench_new_session.bind_employee,
            launch.handle,
            employee_record.member_post_id,
        )
        if (
            launch.session_id
            and launch.session_id not in employee_record.active_session_ids
        ):
            employee_record.active_session_ids.append(launch.session_id)
            await asyncio.to_thread(save_post, employee_record)
        from frago.server.services.employee_usage import invalidate_employee_usage_cache

        invalidate_employee_usage_cache(employee_record.member_post_id)

    recorded: bool | None = None
    mark_saved: bool | None = None
    mark_id: str | None = None
    if launch.session_id:
        result = await asyncio.to_thread(workbench_branch.record, branch, launch.session_id)
        recorded, mark_saved, mark_id = result.relation, result.mark_saved, result.mark_id
    else:
        workbench_branch.record_when_claimed(branch, launch.handle)

    return {
        **_launch_payload(launch),
        "text": branch.text,
        "title": workbench_branch.title_for(note),
        "recorded": recorded,
        "mark_saved": mark_saved,
        "mark_id": mark_id,
    }


class CloseBranchRequest(BaseModel):
    """``by``：``bring-back``（分支里带回主线后发出）或 ``manual``（主线上手动标记）。"""

    by: str


@router.post("/workbench/sessions/{sid}/branches/{child}/close")
async def close_workbench_branch(sid: str, child: str, request: CloseBranchRequest) -> dict:
    """把 ``sid`` 分到 ``child`` 的那条分支记为已收口。关系账与主线标注在这一次请求里一起改。

    关系账上没有这条分支 404；来路不认得 400；关系账写不进去 500。标注改没改上看
    ``mark_updated``——那一家存不了标注时为假，不算失败。
    """
    try:
        return await asyncio.to_thread(workbench_branch.close, sid, child, request.by)
    except workbench_branch.BranchRequestInvalid as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except workbench_branch.BranchNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"没记上收口：{e}") from e


@router.get("/workbench/sessions/pending/{handle}")
async def read_pending_session(handle: str) -> dict[str, Any]:
    """这次新建到哪一步了：认到会话编号没有、还是已经起失败了。

    把手过期或压根没有过这么一次时回 404——界面据此停下来说"这次新建跟丢了"，
    比无限轮询一个永远不会有答案的把手强。
    """
    launch = await asyncio.to_thread(workbench_new_session.status, handle)
    if launch is None:
        raise HTTPException(status_code=404, detail=f"没有编号为 {handle} 的新建记录")
    return _launch_payload(launch)


def _launch_payload(launch: workbench_new_session.PendingLaunch) -> dict[str, Any]:
    """一次新建的对外形状。两条路共用一份，NEVER 各拍各的。"""
    return {
        "handle": launch.handle,
        "agent": launch.agent_type,
        "display_name": launch.display_name,
        "cwd": launch.cwd,
        "session_id": launch.session_id,
        "error": launch.error,
        "finished": launch.finished,
    }


@router.get("/workbench/sessions/{sid}/records")
async def read_workbench_records(
    sid: str,
    after: int = Query(0, description="本批第一条的 seq，闭区间起点"),
    limit: int = Query(
        DEFAULT_LIMIT,
        description=f"本批最多几条。默认 {DEFAULT_LIMIT}，超过 {record_reader.MAX_LIMIT} 一律截到上限",
    ),
    tail: bool = Query(False, description="为真时忽略 after，取整场最后 limit 条"),
) -> list[dict[str, Any]]:
    """取这场会话从 ``after`` 起的统一记录；``tail`` 为真时取整场最后 ``limit`` 条。

    ``limit`` 越界不报错，直接截到 :data:`~frago.session.record_reader.MAX_LIMIT`——
    界面传大了是它自己的事，服务端不该因此把这一屏内容整个扣下。截断本身由核心数据层
    执行，这里一个数字都不算，NEVER 在两处各写一遍上限。

    会话编号两家的形状都不像时回 404，NEVER 猜一家试试。
    """
    try:
        records = await asyncio.to_thread(record_reader.read_records, sid, after, limit, tail)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 开在 tmux 里的才登记监听，此后文件一动就经 WebSocket 推增量；不开在 tmux 里的只有
    # 这一次取回的内容，不盯它的文件（主人 09-30 定）。
    await asyncio.to_thread(_ensure_watching, sid)

    return [asdict(record) for record in records]


@router.get("/workbench/sessions/{sid}/children")
async def read_workbench_session_children(sid: str) -> dict[str, Any]:
    """探测这场会话的启动来源、派生子会话与运行中子进程。

    同时汇聚 ``session_origin`` 关系账、``async_dispatch`` 异步派发单，以及本机
    tmux 窗格 / ``ps`` 进程树（含外部终端 ``claude --resume <sid>``）三路实况，
    避免详情页看着安静而后台仍有派生任务在运行。
    """
    from frago.server.services import session_children

    try:
        return await asyncio.to_thread(session_children.probe_session_children, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class RevealPathRequest(BaseModel):
    """要打开的路径。界面一律传绝对路径。"""

    path: str


def _session_directory(sid: str) -> str | None:
    """这场会话自己的工作目录。认不出这场、或它没留下工作目录，都返回 None——
    NEVER 退回当前进程的目录顶替，那等于给任意路径开了口子。

    走 O(1) 单场定位接口（优先读取本体唯一真源 cwd），不触发 ``list_sessions()`` 全量扫描。"""
    return record_reader.get_session_directory(sid)


def _session_root(sid: str) -> str | None:
    """这场会话自己的工作目录，对齐成可比的样子（``~`` 展开、软链与 ``..`` 消掉）。

    认不出这场、或它没留下工作目录，都返回 None——这正是 :func:`_session_directory` 记下
    的那条规矩：相对路径少了一个基准时，NEVER 拿当前进程的目录顶替。"""
    directory = _session_directory(sid)
    if not directory:
        return None
    try:
        return str(Path(os.path.expanduser(directory)).resolve())
    except OSError:
        return None


def _resolve_path(
    path: str, base: str | None
) -> tuple[str | None, Literal["missing-cwd", "path-escaped"] | None]:
    """把路径对齐成可比的样子，并显式区分「缺少会话工作目录」与「越界逃逸」。

    - 绝对路径：展开 ``~`` 后对称 ``resolve()``（兼顾 macOS ``/var`` <-> ``/private/var`` 等软链）。
    - 相对路径：缺失 ``base`` 时返回 ``(None, "missing-cwd")``；拼出并解析软链后不在
      ``base`` 底下时返回 ``(None, "path-escaped")``。
    """
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        try:
            return str(Path(expanded).resolve()), None
        except OSError:
            return None, "path-escaped"
    if not base:
        return None, "missing-cwd"
    try:
        base_path = Path(base).resolve()
        inside = (base_path / expanded).resolve()
    except OSError:
        return None, "path-escaped"
    if not inside.is_relative_to(base_path):
        return None, "path-escaped"
    return str(inside), None


def _norm(path: str, base: str | None) -> str | None:
    """把路径对齐成可比的样子：``~`` 展开、软链与 ``..`` 消掉。对不上返回 None。"""
    resolved, _ = _resolve_path(path, base)
    return resolved


def _path_rejection_error(path: str, reason: Literal["missing-cwd", "path-escaped"] | None) -> HTTPException:
    if reason == "missing-cwd":
        return HTTPException(
            status_code=403,
            detail=(
                f"Refused: {path} is relative and this session has no working "
                "directory (missing-cwd)"
            ),
        )
    return HTTPException(
        status_code=403,
        detail=(
            f"Refused: {path} resolves outside this session's working "
            "directory (path-escaped)"
        ),
    )


async def _touched(sid: str) -> list[session_files.SessionFile]:
    """这场会话改过的文件。认不出这场会话时翻成 404，别的异常照原样抛。"""
    try:
        return await asyncio.to_thread(session_files.session_files, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/workbench/sessions/{sid}/path")
async def probe_session_path(
    sid: str,
    path: str = Query(..., description="选区里那一段，问它是不是一份真文件"),
) -> dict[str, Any]:
    """这条路径在这台机器上是不是一份真文件：只回答在不在，**不读内容**。

    人在记录流里圈中一段文字，界面先粗筛一遍「这看着像不像一条路径」（纯文本规则，在
    界面那一侧），再拿这里问一句「真有这么一份吗」。判定只有一条：存在且是文件。不看
    内容、不猜扩展名能不能渲染——渲染不了的自然会在打开时按打不开说。

    **相对路径按这场会话自己的工作目录解**（见 :func:`_norm`），与这场会话的文件清单同一
    把尺子：同一个字符串在界面那一侧和清单那一侧永远指到同一份文件。基准缺了、或拼出来
    爬出了工作目录，都算「没有这条路径」，NEVER 退回当前进程的目录顶替。
    """
    base = await asyncio.to_thread(_session_root, sid)
    resolved = await asyncio.to_thread(_norm, path, base)
    if resolved is None:
        return {
            "path": path,
            "resolved": None,
            "exists": False,
            "is_file": False,
            "is_dir": False,
            "size": None,
        }

    target = Path(resolved)
    size: int | None = None
    is_dir = False
    try:
        is_file = target.is_file()
        is_dir = target.is_dir()
        # 字节数一并带上：界面那一侧拿它挡住过大的文件，省得为了一份读不完的东西
        # 先把内容拉下来。
        if is_file:
            size = target.stat().st_size
    except OSError:
        is_file = False
        is_dir = False
    return {
        "path": path,
        "resolved": resolved,
        "exists": target.exists(),
        "is_file": is_file,
        "is_dir": is_dir,
        "size": size,
    }


@router.get("/workbench/sessions/{sid}/files")
async def read_session_files(sid: str) -> list[dict[str, Any]]:
    """这场会话写或改过的文件：路径、新建还是改、动过几次。

    清单从这场会话自己的记录里读出来（见 :mod:`frago.session.session_files`）：经 shell
    命令改的文件哪一家都不留结构化字段，所以它是**下界**不是全集；会话工具自己的临时区
    不算，那些回答不了「它在我项目里改了什么」。
    """
    return [asdict(f) for f in await _touched(sid)]


_PREVIEW_MAX_BYTES = 512 * 1024


async def _listed_target(sid: str, path: str) -> Path:
    """这份文件在磁盘上的位置。「看内容」与「做对照」两条路共用的一套门。

    **只认清单里的路径**：请求的路径与这场会话改过的某一条指向同一份文件才给读，别的一律
    403。这条比「在工作目录底下」更紧——目录名读不到东西，文件内容读得到，所以白名单按
    文件一个个列，不按目录放。

    清单里那些**相对**路径按这场会话自己的工作目录解释（见 :func:`_norm`）：两边同一个
    基准，请求与清单才不会各偏各的。基准缺了、或相对路径爬出了工作目录，都当成「这一条
    解释不了」拒掉，NEVER 退回当前进程的目录。
    """
    base = await asyncio.to_thread(_session_root, sid)
    allowed = {n for f in await _touched(sid) if (n := _resolve_path(f.path, base)[0]) is not None}
    resolved, err_reason = _resolve_path(path, base)
    if resolved is None:
        raise _path_rejection_error(path, err_reason)
    if resolved not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Refused: {path} is not a file this session changed",
        )
    return Path(resolved)


def _read_body(target: Path, path: str) -> dict[str, Any]:
    """把这一份读成给界面的那几格。

    过大的（``too-large``）、编码不是文本的（``not-text``）、无权限/不可读的（``unreadable``）
    都不返回内容，而是返回一个准确原因，界面照实写出来，NEVER 悄悄给半份或混为一谈。
    """
    try:
        st = target.stat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=f"File is gone: {target}") from exc
    except OSError:
        return {"path": path, "size": 0, "text": None, "reason": "unreadable"}

    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(status_code=404, detail=f"File is gone: {target}")

    size = st.st_size
    if size > _PREVIEW_MAX_BYTES:
        return {"path": path, "size": size, "text": None, "reason": "too-large"}
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"path": path, "size": size, "text": None, "reason": "not-text"}
    except OSError:
        return {"path": path, "size": size, "text": None, "reason": "unreadable"}
    return {"path": path, "size": size, "text": text, "reason": None}


async def _read_text(sid: str, path: str) -> dict[str, Any]:
    """取这份文件的正文。门的规矩见 :func:`_listed_target`。"""
    return _read_body(await _listed_target(sid, path), path)


class WriteSessionFileRequest(BaseModel):
    """``PUT /workbench/sessions/{sid}/file`` 的请求体：要改的那份文件路径与新正文。"""

    path: str
    text: str


@router.get("/workbench/sessions/{sid}/file")
async def read_session_file(
    sid: str,
    path: str = Query(..., description="要取内容的那一份文件，必须是本会话改过的其中之一"),
) -> dict[str, Any]:
    """取清单里某一份文件的内容，给浮窗预览用。门的规矩见 :func:`_listed_target`。"""
    return await _read_text(sid, path)


# 对照最多摆这么多行。两列并排，行数再往上没人会一行行看了；而算对齐要两边都在手上，
# 这个数也顺带挡住了把一份几万行的文件塞进浏览器的那种请求。
_DIFF_MAX_LINES = 3000


async def _compute_file_diff(
    sid: str, listed: Path, current: dict[str, Any]
) -> dict[str, Any]:
    """根据当前文件内容与上一版（git HEAD 或会话内编辑前快照）计算对齐后的左右对照行。

    人类给的那个相对路径不再单独收一个形参：``current`` 里已经带着它，收两份迟早会分叉。
    """
    body: dict[str, Any] = {
        "path": current["path"],
        "size": current["size"],
        "reason": current["reason"],
        "before": None,
        "source": None,
        "rows": None,
    }
    if current["text"] is None:
        # 现在这一份就读不出来（太大、不是文本）：没有可对照的东西，界面照 `/file` 那套说。
        return body
    after = current["text"]
    if after.count("\n") + 1 > _DIFF_MAX_LINES:
        body["reason"] = "too-many-lines"
        return body

    before = await asyncio.to_thread(
        file_history.before_at_head, str(listed), max_bytes=_PREVIEW_MAX_BYTES
    )
    body["before"] = before.reason
    body["source"] = before.source
    if before.text is None:
        # 若 git HEAD 没有上一版（如不在 git 仓库里或本会话新建未提交），但人类在本会话中
        # 通过 Edit 保存过该文件，则拿首次编辑前的快照作为左边基线，展示最新修改对比。
        edit_baseline = file_history.get_edit_baseline(sid, str(listed))
        if edit_baseline is not None:
            if edit_baseline.count("\n") + 1 > _DIFF_MAX_LINES:
                body["reason"] = "too-many-lines"
                return body
            body["before"] = None
            body["source"] = file_history.EDIT_BASELINE_SOURCE
            body["rows"] = await asyncio.to_thread(file_history.diff_rows, edit_baseline, after)
            return body
        # 没有左边：整份当新增摆，左边整列空着。为什么没有写在 `before` 那一格上。
        body["rows"] = file_history.added_rows(after)
        return body
    if before.text.count("\n") + 1 > _DIFF_MAX_LINES:
        body["reason"] = "too-many-lines"
        return body
    body["rows"] = await asyncio.to_thread(file_history.diff_rows, before.text, after)
    return body


@router.put("/workbench/sessions/{sid}/file")
async def write_session_file(sid: str, request: WriteSessionFileRequest) -> dict[str, Any]:
    """保存人类在 FileViewer Edit 模式中修改的文本文件，并返回最新内容与最新版本比较结果。"""
    listed = await _listed_target(sid, request.path)
    encoded = request.text.encode("utf-8")
    if len(encoded) > _PREVIEW_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File content exceeds {_PREVIEW_MAX_BYTES} bytes",
        )

    def _save_and_read() -> dict[str, Any]:
        if listed.is_file():
            try:
                old_text = listed.read_text(encoding="utf-8")
                file_history.record_edit_baseline(sid, str(listed), old_text)
            except (UnicodeDecodeError, OSError):
                pass
        listed.parent.mkdir(parents=True, exist_ok=True)
        listed.write_text(request.text, encoding="utf-8")
        return _read_body(listed, request.path)

    current = await asyncio.to_thread(_save_and_read)
    diff = await _compute_file_diff(sid, listed, current)
    return {
        **current,
        "diff": diff,
    }


@router.get("/workbench/sessions/{sid}/file/diff")
async def read_session_file_diff(
    sid: str,
    path: str = Query(..., description="要看改动的那一份文件，必须是本会话改过的其中之一"),
) -> dict[str, Any]:
    """这份文件「改动之前」与「现在」对齐好的两列，给浮窗的 Changes 那一档用。

    左边那一侧取自 **git 的 HEAD**（为什么是它、它不是什么，都写在
    :mod:`frago.server.services.file_history` 的模块说明里）。取不到左边时 `before` 说出
    缘由（`new` 是这一场新建的、`not-git` 是它不在仓库里），界面照实写，NEVER 把「不知道」
    装成「新建的」。

    对齐在服务端算：左边那一侧本来就只有这里有。`rows` 每一行是一对格子，左边空着表示那一行
    这一侧没有东西（整行删掉、或整份都是新增）。

    门与 `/file` 是同一套（:func:`_listed_target`）；拿到的是**解析好的绝对路径**，左边那一
    侧也照它去 git 里取——拿请求里那个相对的原样去取，git 会按服务进程的目录算，摆出来的
    又是另一个文件的历史。
    """
    listed = await _listed_target(sid, path)
    current = await asyncio.to_thread(_read_body, listed, path)
    return await _compute_file_diff(sid, listed, current)


def _inside_frago_data(target: str) -> bool:
    """产物目录（``~/.frago/data``）下的真实路径。

    宪法要求运行时数据与产出物落入 ``~/.frago/data/<project>/``，而图片、PDF、脚本产物等
    往往经由命令或脚本生成、不在 Write/Edit 的结构化工具记录里；在会话详情里点「打开所在目录」
    应当允许直接定位这些产物。
    """
    try:
        data_root = (Path.home() / ".frago" / "data").resolve()
        return target == str(data_root) or Path(target).is_relative_to(data_root)
    except OSError:
        return False


@router.post("/workbench/sessions/{sid}/reveal")
async def reveal_session_path(sid: str, request: RevealPathRequest) -> dict[str, Any]:
    """在系统文件管理器里打开这个路径：是文件就选中它，是目录就打开它。

    **只认三处**：这场会话自己的工作目录底下的东西、``~/.frago/data`` 下的产物，以及它改过
    的那些文件。路径由页面给过来，服务端不校验就成了一个「随便开哪个目录」的口子；会话详情里
    这个按钮挨着本会话改过的文件与产出物，够不着那之外的地方。

    跨平台怎么开在 :meth:`~frago.server.services.system_service.SystemService.reveal_or_open`
    里，本模块不重复一遍平台判断。
    """
    base = await asyncio.to_thread(_session_root, sid)
    target, err_reason = _resolve_path(request.path, base)
    if target is None:
        raise _path_rejection_error(request.path, err_reason)
    inside_root = base is not None and (target == base or Path(target).is_relative_to(base))
    inside_data = _inside_frago_data(target)
    if (
        not inside_root
        and not inside_data
        and target not in {n for f in await _touched(sid) if (n := _resolve_path(f.path, base)[0]) is not None}
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Refused: {target} is neither in this session's working directory nor a file it changed",
        )
    if not Path(target).exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {target}")

    try:
        if Path(target).is_dir():
            await asyncio.to_thread(SystemService.open_directory, target)
        else:
            await asyncio.to_thread(SystemService.reveal_or_open, target, True)
    except UnsupportedPlatformError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except (subprocess.CalledProcessError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to open {target}: {e}") from e

    return {"status": "ok", "opened": target}


@router.get("/workbench/search")
async def search_workbench_sessions(
    q: str = Query(..., min_length=1, description="要找的一句话，照人话写，不必是关键词"),
    top: int = Query(20, ge=1, le=50, description="最多报几场"),
) -> dict[str, Any]:
    """搜会话，与 ``frago session search`` 是同一条路：模型先把这句话摊成一组关键词，再扫遍
    ``~/.frago/sessions`` 的会话备份，按命中的不同关键词数排序。

    界面与命令行必须搜出同一批结果——人在终端里搜到过的那一场，在网页上换个入口就该还在，
    所以这里不另写检索，只把 :func:`frago.session.search.search_sessions` 的结果原样交出去。

    一趟里模型扩展要十几秒，界面据此只在人按下回车时才发，不边敲边搜。

    ``warnings`` 里是这一趟没做全的地方（扩展失败退回原句切词、有几场只剩加工副本）。
    **NEVER 把它当可选字段丢掉**——做不全却不说，等于谎报覆盖面。
    """
    result = await asyncio.to_thread(session_search.search_sessions, q, top=top)
    return asdict(result)


@router.get("/workbench/pins")
async def list_workbench_pins() -> dict[str, list[str]]:
    """当前置顶了哪几场，最近置顶的在最前。

    只回编号，不回会话本身：清单那一条接口已经把每场的标题、状态、摘要都取齐了，这里
    再回一份等于同一份数据摆两处，迟早各说各的。界面拿编号去清单里对号入座。

    名单里的编号**不与清单核对**。会话档案随时可能被删或被滚删，核对过的名单会因为
    一次滚删悄悄变短，而人根本不知道自己的置顶被清了。
    """
    return {"pinned": await asyncio.to_thread(workbench_pins.list_pins)}


@router.put("/workbench/pins/{sid}")
async def pin_workbench_session(sid: str) -> dict[str, list[str]]:
    """把这场会话置顶，回置顶后的完整名单。

    回整份名单而不是"成功"：置顶会改次序（已经在名单里的会被挪到最前），只说一句成功
    的话，界面得自己猜新次序长什么样，猜错就是两边不一致。

    **不设数量上限。** 上限是替人做决定，而左栏本来就是窗口化渲染，多几行不额外花什么。

    编号三家的形状都不像时回 404：置顶一个不存在的编号，名单里会永远躺着一行谁都对不
    上的记录。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        pinned = await asyncio.to_thread(workbench_pins.pin, sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"pinned": pinned}


@router.delete("/workbench/pins/{sid}")
async def unpin_workbench_session(sid: str) -> dict[str, list[str]]:
    """取消置顶，回剩下的名单。

    本来就不在名单里也回 200：这条接口承诺的是"结束时它不在名单里"，那个结果已经成立。
    为此回 404 只会让界面在连点两下时弹一句没有意义的报错。同理，这里**不校验编号属于
    哪一家**——不管什么形状，把它从名单里去掉都是对的。
    """
    return {"pinned": await asyncio.to_thread(workbench_pins.unpin, sid)}


class FilePinBody(BaseModel):
    path: str
    is_dir: bool = False


class FilePinMergeBody(BaseModel):
    pins: list[FilePinBody]


class RecipeAppPinBody(BaseModel):
    id: str


class RecipeAppPinMergeBody(BaseModel):
    pins: list[str]


@router.get("/workbench/file-pins")
async def list_workbench_file_pins() -> dict[str, list[dict[str, Any]]]:
    """Files 菜单下固定的目录与文件清单（后端 ~/.frago/workbench_pins.json 真源）。"""
    return {"pins": await asyncio.to_thread(workbench_pins.list_file_pins)}


@router.put("/workbench/file-pins")
async def put_workbench_file_pin(body: FilePinBody) -> dict[str, list[dict[str, Any]]]:
    """将绝对路径固定到 Files 菜单下（幂等），返回完整清单。"""
    try:
        pins = await asyncio.to_thread(workbench_pins.pin_file, body.path, body.is_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"pins": pins}


@router.delete("/workbench/file-pins")
async def delete_workbench_file_pin(path: str = Query(...)) -> dict[str, list[dict[str, Any]]]:
    """取消 Files 菜单下的某项固定（幂等），返回剩下的完整清单。"""
    return {"pins": await asyncio.to_thread(workbench_pins.unpin_file, path)}


@router.post("/workbench/file-pins/merge")
async def merge_workbench_file_pins(body: FilePinMergeBody) -> dict[str, list[dict[str, Any]]]:
    """首次迁移或合并本地缓存中的固定文件/目录，忽略非绝对路径并返回合并后清单。"""
    items = [{"path": item.path, "is_dir": item.is_dir} for item in body.pins]
    pins = await asyncio.to_thread(workbench_pins.merge_file_pins, items)
    return {"pins": pins}


@router.get("/workbench/recipe-app-pins")
async def list_workbench_recipe_app_pins() -> dict[str, list[str]]:
    """Recipes 菜单下已打开的配方 UI 清单（后端 ~/.frago/workbench_pins.json 真源）。"""
    return {"pins": await asyncio.to_thread(workbench_pins.list_recipe_app_pins)}


@router.put("/workbench/recipe-app-pins")
async def put_workbench_recipe_app_pin(body: RecipeAppPinBody) -> dict[str, Any]:
    """固定某个配方 UI：同配方已存在时返回既有条目（kept），不新增或覆写槽位。"""
    try:
        kept, pins = await asyncio.to_thread(workbench_pins.pin_recipe_app, body.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"kept": kept, "pins": pins}


@router.delete("/workbench/recipe-app-pins")
async def delete_workbench_recipe_app_pin(id: str = Query(...)) -> dict[str, list[str]]:
    """摘掉 Recipes 菜单下的已打开配方 UI（幂等），返回剩下的完整清单。"""
    return {"pins": await asyncio.to_thread(workbench_pins.unpin_recipe_app, id)}


@router.post("/workbench/recipe-app-pins/merge")
async def merge_workbench_recipe_app_pins(body: RecipeAppPinMergeBody) -> dict[str, list[str]]:
    """首次迁移或合并本地缓存中的已打开配方 UI，返回合并后完整清单。"""
    pins = await asyncio.to_thread(workbench_pins.merge_recipe_app_pins, body.pins)
    return {"pins": pins}


@router.get("/workbench/views")
async def list_workbench_views() -> dict[str, dict[str, int]]:
    """每场会话你上次点开它的毫秒时刻。没点开过的不在里面。

    左栏拿它与清单里「最后一句回复的时刻」相比，判这一场有没有你还没看过的新回复。
    """
    return {"viewed": await asyncio.to_thread(workbench_views.list_views)}


@router.put("/workbench/views/{sid}")
async def mark_workbench_viewed(sid: str) -> dict[str, Any]:
    """记下此刻点开了这场会话。

    时刻由服务端取而不收页面给的：它要和会话记录里的时刻比大小，两边必须出自同一个钟。

    编号三家的形状都不像时回 404：记录里躺一行谁都对不上的编号，从此没人清得掉。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        return await asyncio.to_thread(workbench_views.mark_viewed, sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/workbench/today")
async def list_workbench_today() -> dict[str, object]:
    """今天从 timeline 捡回来用的会话编号，外加今天是哪一天。

    左栏的口径是「今天有过真正回复的会话」，这份名单是那之外的唯一例外：人今天还要接着
    用的旧会话，从 timeline 里捡回来，当天留在左栏。

    回 ``today`` 而不只是编号，是因为**过期判定以服务端为准**：页面那边的钟快一天慢一天
    时，界面至少能从这一格看出服务端认为今天是哪天。

    名单里的编号**不与清单核对**——与置顶同一个理由，一次滚删不该悄悄撤销人捡它的动作。
    """
    return await asyncio.to_thread(workbench_today.snapshot)


@router.put("/workbench/today/{sid}")
async def pick_workbench_today(sid: str) -> dict[str, object]:
    """把这场旧会话捡到今天，回今天的完整名单。

    编号三家的形状都不像时回 404：捡一场不存在的会话，名单里会躺一条谁都对不上的记录。
    有效期只有今天——第二天它若没有真的动静，自然就不在名单里了。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        await asyncio.to_thread(workbench_today.pick, sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await asyncio.to_thread(workbench_today.snapshot)


@router.delete("/workbench/today/{sid}")
async def unpick_workbench_today(sid: str) -> dict[str, object]:
    """把这场会话从今天的名单里去掉，回剩下的。

    本来就不在名单里也回 200：这条接口承诺的是"结束时它不在今天的名单里"。这里不校验
    编号属于哪一家——不管什么形状，把它从名单里去掉都是对的。
    """
    await asyncio.to_thread(workbench_today.unpick, sid)
    return await asyncio.to_thread(workbench_today.snapshot)


def _groups_payload(state: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    """分组的对外形状：整份分组，外加 AI 分组那一趟走到哪了。每条接口都回这一份。"""
    return {**state, "ai_job": job if job is not None else workbench_groups.job_state()}


@router.get("/workbench/groups")
async def list_workbench_groups() -> dict[str, Any]:
    """有哪些标签、每个标签下挂哪些会话编号，外加 AI 分组的进度。

    与置顶一样只回编号：会话本身由清单那条接口给，界面拿编号去对号入座。编号**不与清单
    核对**——Claude Code 清理掉原文件的会话备份里还在，一核对就会被悄悄踢出分组。
    """
    return _groups_payload(await asyncio.to_thread(workbench_groups.load))


class CreateTagRequest(BaseModel):
    name: str


@router.post("/workbench/groups/tags")
async def create_workbench_tag(request: CreateTagRequest) -> dict[str, Any]:
    """人建一个标签。重名回 409：两个同名分区，人分不清该往哪个里放。"""
    try:
        state = await asyncio.to_thread(workbench_groups.create_tag, request.name)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _groups_payload(state)


@router.delete("/workbench/groups/tags/{tag_id}")
async def delete_workbench_tag(tag_id: str) -> dict[str, Any]:
    """删一个标签，里面的会话回到未分组。本来就没有也回 200。"""
    return _groups_payload(await asyncio.to_thread(workbench_groups.delete_tag, tag_id))


class AssignRequest(BaseModel):
    """``tag_id`` 为 null 就是移出分组。"""

    tag_id: str | None = None


@router.put("/workbench/groups/sessions/{sid}")
async def assign_workbench_session(sid: str, request: AssignRequest) -> dict[str, Any]:
    """把这场会话放进某个组（从原来那组搬走），或移出分组。

    编号三家的形状都不像时回 404，标签不存在也回 404：分组里躺一行谁都对不上的记录，
    从此没人清得掉。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        state = await asyncio.to_thread(workbench_groups.assign, sid, request.tag_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"没有这个标签：{request.tag_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _groups_payload(state)


@router.post("/workbench/groups/ai")
async def start_workbench_ai_grouping() -> dict[str, Any]:
    """让 AI 把还没分组的主会话归进标签。在后台跑，立刻回进度，页面轮询取分组看它走到哪。

    已经在跑就不再起第二趟，照样回当前进度。
    """
    cards = await asyncio.to_thread(record_reader.list_sessions)
    job = workbench_groups.start_ai_grouping(cards)
    return _groups_payload(await asyncio.to_thread(workbench_groups.load), job)


class SendRequest(BaseModel):
    """``POST /workbench/sessions/{sid}/send`` 的请求体。

    ``images`` 与 ``documents`` 都是可选附件，内容以 base64 传上来，落盘后其绝对路径
    被拼进投给 agent 的提示词。浏览器读不到本机文件的真实路径（那是浏览器的安全边界，
    拖拽也拿不到），所以只能走这条"内容上传、路径下发"的路——agent 拿到的是一条它
    真的打得开的服务端路径。允许 text 为空但带附件。

    ``skills`` 是人在输入框里敲 ``/`` 挑中的 skill 名（``/api/skills`` 里的 ``name``），
    服务端把它们的文档全文嵌进这句话前面（见 ``_with_skills``）。只挑 skill、不写字也能发。

    ``cwd`` 只在页面**新建**一场会话时给：那个编号是页面自己 mint 的，还没有任何
    记录，所以读不出目录。已经有记录的会话一律以档案里记着的目录为准。

    ``wait`` 为假时只排队不等答：判完落点就回 ``status: "queued"``。虚拟桌面上的人类
    输入行走这条路——人追加的那句话要排进主 agent 的队列，而主 agent 那一轮可能还要
    跑几十分钟。
    """

    text: str = ""
    images: list[str] = []
    documents: list[Document] = []
    skills: list[str] = []
    employees: list[str] = []
    cwd: str | None = None
    wait: bool = True


def _apply_employees_and_skills(
    base_prompt: str,
    user_text: str,
    skills: list[str],
    employees: list[str],
) -> tuple[str, list[str]]:
    """把 `@` 挑中的员工语境块、岗位自带技能与 `/` 挑中的技能依次合并进提示词。"""
    effective_skills: list[str] = []
    cleaned_employees: list[str] = []
    for emp_id in employees or []:
        cid = str(emp_id or "").strip()
        if cid and cid not in cleaned_employees:
            cleaned_employees.append(cid)
            try:
                rec = get_post(cid)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            if rec is None:
                raise HTTPException(status_code=400, detail=f"员工编号 '{cid}' 不存在")
            for sk in rec.skills:
                csk = str(sk).strip()
                if csk and csk not in effective_skills:
                    effective_skills.append(csk)
    for sk in skills or []:
        csk = str(sk).strip()
        if csk and csk not in effective_skills:
            effective_skills.append(csk)
    prompt = base_prompt
    for cid in reversed(cleaned_employees):
        prompt = _with_employee_context(prompt, cid)
    prompt = _with_skills(prompt, effective_skills, user_text)
    return prompt, effective_skills


@router.post("/workbench/sessions/{sid}/send")
async def send_to_session(sid: str, request: SendRequest) -> dict:
    """把这段话投进那场会话（Claude Code / opencode / codex / CoreAgent 都走这里）。

    前三家：会话已经常驻就直接投喂（上下文原样保留），冷的那些由会话池按各家自己的续接
    命令重建之后再投。CoreAgent 每一轮新起一个进程，靠把那一场的记录读回来接上前文。
    返回激活态，页面据此在冷启动那一轮显示进度条。

    五类拒绝各有各的意思，NEVER 合并成一个 500：

    - 编号三家的形状都不像 → 404，这不是一场会话；
    - 记录已经不在了（用户删了那场会话）→ 409。**这一档最要紧**：驱动层遇到续不上的
      目标会自愈成裸起一场新的，那正是页面上最不该发生的事——人以为在跟原来那场说话；
    - CoreAgent 那一场还在跑 → 409，等它答完就能发；
    - 内核不在或者 CoreAgent 没配连接 → 503，这一轮连记录都没留下，理由只能从这里带出去；
    - 一个字没有也没有附件 → 400，空轮次投进去只会白占一次冷启动。

    ``status: "queued"`` 是两种情形共用的答复：人点名只排队（``wait`` 为假），或者
    CoreAgent 那一场此刻正在干活——后者要等当前这一步结束才被读到，页面据此把这句话
    标成排队中。
    """
    if (
        not request.text.strip()
        and not request.images
        and not request.documents
        and not request.skills
        and not request.employees
    ):
        raise HTTPException(status_code=400, detail="要发的话和附件不能都是空的")

    try:
        image_paths = save_uploaded_images(request.images, sid)
        doc_paths = save_uploaded_documents([d.model_dump() for d in request.documents], sid)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e
    prompt, _ = _apply_employees_and_skills(
        build_prompt_with_attachments(request.text, image_paths, doc_paths),
        request.text,
        request.skills,
        request.employees,
    )

    try:
        if not request.wait:
            if (
                "how-frago-agent-runs-an-agent-os" in (request.skills or [])
                or coreagent_runner._is_desktop_operator_session(sid, "")
            ):
                from frago.server.services import stage_orchestrator

                dispatch_res = await asyncio.to_thread(
                    stage_orchestrator.dispatch_desktop_voice_command,
                    request.text,
                    session_id=sid,
                    cwd=request.cwd,
                )
                _ensure_watching(dispatch_res["session_id"])
                return {"sid": dispatch_res["session_id"], "status": "queued", "text": ""}
            # 只排队：判落点仍会读盘，照样进工作线程；投喂本身由它自己开的线程做。
            await asyncio.to_thread(session_send.send_queued, sid, prompt, cwd_hint=request.cwd)
            return {"sid": sid, "status": "queued", "text": ""}
        # CoreAgent 那一场正在干活：这一句会写进它的 stdin，内核在这一轮的下一个回合边界
        # 接上（见 coreagent_runner._feed_loop 与内核的「中途插话」），不必等整件事做完。
        # 仍然当场回「排队中」：它确实要等到那个边界才被读到，这一刻还没进模型的历史。
        # 这一趟不等它，页面据此把这句话标成排队，而不是一路显示「已发送」。
        #
        # 忙的时候不等，丢不掉失败信号：同步能出的错只剩「队列满」（send_queued 照样
        # 当场抛），而「内核不在」「没配连接」那几种——它正跑着，不可能碰得上。
        if coreagent_runner.busy(sid):
            await asyncio.to_thread(session_send.send_queued, sid, prompt, cwd_hint=request.cwd)
            return {"sid": sid, "status": "queued", "text": ""}
        # tmux + 轮询是阻塞的，丢进工作线程，免得一轮投喂把整个事件循环停住。
        activation = await asyncio.to_thread(session_send.send, sid, prompt, cwd_hint=request.cwd)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (
        session_send.SessionGone,
        # 这一家的会话接不上话。照实说，NEVER 让它落进下面那个 500——那在页面上只剩
        # 一句"没发出去"，人会以为是出了故障。
        session_send.SessionNotResumable,
        # CoreAgent 那一场还在跑：等它答完就能发，跟"发失败"不是一回事。
        coreagent_runner.CoreAgentBusy,
    ) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except coreagent_runner.CoreAgentUnavailable as e:
        # 内核不在、或者 CoreAgent 还没配连接：这一轮在会话记录里一行都没留下，
        # 页面上除了这句话没有别的线索，所以理由必须原样带出去。
        raise HTTPException(status_code=503, detail=str(e)) from e
    except TmuxSendError as e:
        # 驱动层确认投喂未落地（重试耗尽仍未写入会话记录）：立即向页面显式报错，
        # 绝不静默假装已发送或落入完成轮询空等超时。
        logger.warning("workbench send TmuxSendError (sid=%s): %s", sid, e)
        raise HTTPException(status_code=500, detail=f"没发出去：{e}") from e
    except Exception as e:  # noqa: BLE001 — 驱动失败照实交代，NEVER 吞成"发出去了"
        logger.warning("workbench send failed (sid=%s): %s", sid, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"没发出去：{e}") from e

    return {
        "sid": activation.session_id,
        "status": activation.status,
        "text": activation.text,
    }


class QueueReorderRequest(BaseModel):
    """``PUT /workbench/sessions/{sid}/queue`` 的请求体：按给定顺序重排队列项编号。"""

    item_ids: list[str] = []


@router.get("/workbench/sessions/{sid}/queue")
async def get_workbench_session_queue(sid: str) -> dict[str, Any]:
    """读取会话自有的消息队列与当前自动注入门控状态。"""
    try:
        items = await asyncio.to_thread(workbench_queue.list_queue, sid)
        state = await asyncio.to_thread(workbench_queue.evaluate_queue_state, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "sid": sid,
        "items": items,
        **state,
    }


@router.post("/workbench/sessions/{sid}/queue")
async def enqueue_workbench_session_message(sid: str, request: SendRequest) -> dict[str, Any]:
    """把一条消息（支持文本、图片、文档、skills）加入会话自有的消息队列。

    与直接发送不同，入队不会在 agent 执行过程中向其原生运行队列插话打断流程，而是持久化在
    会话自有队列中；若入队时会话恰好已处于 stop 状态且末尾 ``[end, end-5]`` 轮无交互卡，
    也会按规则自动触发队首注入。
    """
    if (
        not request.text.strip()
        and not request.images
        and not request.documents
        and not request.skills
        and not request.employees
    ):
        raise HTTPException(status_code=400, detail="要入队的话和附件不能都是空的")

    try:
        await asyncio.to_thread(record_reader.detect_family, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        image_paths = save_uploaded_images(request.images, sid)
        doc_paths = save_uploaded_documents([d.model_dump() for d in request.documents], sid)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e

    prompt, effective_skills = _apply_employees_and_skills(
        build_prompt_with_attachments(request.text, image_paths, doc_paths),
        request.text,
        request.skills,
        request.employees,
    )

    try:
        item = await asyncio.to_thread(
            workbench_queue.enqueue,
            sid,
            text=request.text,
            prompt=prompt,
            skills=effective_skills,
            image_paths=image_paths,
            doc_paths=doc_paths,
            cwd=request.cwd,
        )
        items = await asyncio.to_thread(workbench_queue.list_queue, sid)
    except workbench_queue.QueueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "sid": sid,
        "item": item,
        "items": items,
    }


@router.delete("/workbench/sessions/{sid}/queue/{item_id}")
async def delete_workbench_session_queue_item(sid: str, item_id: str) -> dict[str, Any]:
    """从会话自有消息队列中删除指定的一条消息。"""
    try:
        items = await asyncio.to_thread(workbench_queue.remove_item, sid, item_id)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"sid": sid, "items": items}


@router.put("/workbench/sessions/{sid}/queue")
async def reorder_workbench_session_queue(
    sid: str, request: QueueReorderRequest
) -> dict[str, Any]:
    """重排或批量更新会话自有消息队列中的条目顺序。"""
    try:
        items = await asyncio.to_thread(workbench_queue.reorder_queue, sid, request.item_ids)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"sid": sid, "items": items}


@router.post("/workbench/sessions/{sid}/queue/drain")
async def drain_workbench_session_queue(sid: str) -> dict[str, Any]:
    """检查会话是否满足「已 stop 且 [end, end-5] 轮无交互卡」，满足则自动弹出最早一条并注入。"""
    try:
        outcome = await asyncio.to_thread(workbench_queue.try_auto_inject, sid, sync=True)
        items = await asyncio.to_thread(workbench_queue.list_queue, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "sid": sid,
        "items": items,
        **outcome,
    }


@router.get("/workbench/sessions/{sid}/callback-inbox")
async def get_workbench_session_callback_inbox(sid: str) -> dict[str, Any]:
    """只读返回会话当前 ``CallbackInbox`` 待消化回执摘要与门控阻塞状态。"""
    try:
        await asyncio.to_thread(record_reader.detect_family, sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    summary = await asyncio.to_thread(lambda: _callback_inbox_summaries_by_caller().get(sid))
    payload = summary or {"count": 0, "blocked_reason": None, "items": []}
    return {"sid": sid, **payload}


@router.post("/workbench/sessions/{sid}/callback-inbox/drain")
async def drain_workbench_session_callback_inbox(
    sid: str,
    immediate: bool = False,
) -> dict[str, Any]:
    """在安全空闲窗口内原子认领并合并投递 ``CallbackInbox`` 中的待消化回执。

    - ``immediate=False``（默认，供后台子任务完成唤醒）：遵守 ``CALLBACK_INBOX_DEBOUNCE_MS``（400ms）
      空闲防抖窗口；窗口未满时在服务端挂单次可重置延迟定时器，令并发完成的多个子任务合批投递。
    - ``immediate=True``（供人工显式触发）：跳过防抖等待（``debounce_ms=0``），在满足门禁时立即投递。
    """
    from frago.session import async_dispatch

    effective_debounce_ms = 0 if immediate else async_dispatch.CALLBACK_INBOX_DEBOUNCE_MS
    try:
        outcome = await asyncio.to_thread(
            callback_inbox_dispatcher.try_deliver_callback_inbox,
            sid,
            debounce_ms=effective_debounce_ms,
        )
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not immediate and outcome.get("reason") == "debouncing":
        remaining = int(outcome.get("remaining_debounce_ms") or effective_debounce_ms)
        scheduled_ms = callback_inbox_dispatcher.schedule_debounced_callback_drain(
            sid,
            delay_ms=remaining,
            debounce_ms=effective_debounce_ms,
        )
        outcome = {**outcome, "scheduled_retry_ms": scheduled_ms}
    summary = await asyncio.to_thread(lambda: _callback_inbox_summaries_by_caller().get(sid))
    return {
        "sid": sid,
        **(summary or {"count": 0, "blocked_reason": None, "items": []}),
        **outcome,
    }


@router.get("/workbench/uploads/{folder}/{name}")
async def read_uploaded_image(folder: str, name: str) -> FileResponse:
    """取回人随某句话发过的一张图，会话页据此把「附带图片」那几行路径摆成缩略图。

    只认 ``~/.frago/webui_uploads/`` 里的图片；文档、目录外的路径、形状不对的名字一律 404，
    与「文件已经不在了」同一个答复——页面照样只需知道「这张取不到」。
    """
    path = resolve_uploaded_image(folder, name)
    if path is None:
        raise HTTPException(status_code=404, detail="这张图已经不在了")
    return FileResponse(path)


class StopRunRequest(BaseModel):
    """``POST /workbench/sessions/{sid}/stop`` 的请求体。

    ``force`` 是人第二次按下去时才带的：第一次按下若发现屏上还在干活，服务端不动它，
    把「还在干活」如实回给页面，由人自己决定要不要打断。
    ``stage_reset`` 为真时，表示由虚拟桌面「重置」按钮触发，一并销毁所有驻场主持人守护线程与旧舞台会话进程。
    """

    force: bool = False
    stage_reset: bool = False


@router.post("/workbench/sessions/{sid}/stop")
async def stop_session_run(sid: str, request: StopRunRequest) -> dict[str, Any]:
    """结束这一场会话此刻在 tmux 里的运行。

    **按下去才去找那具 tmux，页面不预先探测。** 打开一场会话是个高频动作，为了让按钮
    亮或灭而每次都去问一趟 tmux，代价摊在每一次点击上；而这个按钮一天按不了几次。
    代价是按钮恒亮，按下去才知道有没有关到——那句话由返回值如实说出来。

    **NEVER 拿会话卡片上那个「在跑」当判据。** 那一档是从记录文件推的，与 tmux 里
    有没有一具活着的会话是两回事：一场昨天的会话记录停在昨天而 tmux 早没了，反过来
    也有 tmux 活着、记录看着已终结的。

    关闭本身一个字都不新写，走的是清点浮窗那条既有的路：池子管着的交给池子驱逐
    （池的内存状态得跟着变，否则页面下次投喂会拿着一个死掉的把手去 send），池外的
    才落到单场 ``kill-session``。**NEVER kill-server。**

    三种结局，页面各说各的话：

    - ``alive`` 为假——这一场此刻没有在跑的会话，什么都没动；
    - ``alive`` 为真而 ``stopped`` 为假且 ``busy`` 为真——屏上还在干活，没动它，
      等人带 ``force`` 再按一次；
    - ``stopped`` 为真——关掉了，``via`` 说明走的是池的驱逐还是 tmux。
    """
    from frago.server.services import stage_orchestrator
    from frago.server.services import tmux_sessions_service as svc

    def _bump_abort_epoch_safe(target_sid: str) -> None:
        with contextlib.suppress(Exception):
            from frago.session.service import get_default_session_service

            get_default_session_service().bump_abort_epoch(target_sid)

    def _stop() -> dict[str, Any]:
        if request.stage_reset or sid == "__stage_reset__":
            target_sid = None if sid == "__stage_reset__" else sid
            stage_info = stage_orchestrator.reset_stage_sessions(target_sid)
            stopped_any = bool(
                stage_info["stopped_presenters"] or stage_info["stopped_sessions"]
            )
            if stopped_any and target_sid:
                _bump_abort_epoch_safe(target_sid)
            return {
                "sid": sid,
                "alive": stopped_any,
                "busy": False,
                "stopped": stopped_any,
                "dropped": 0,
                "name": None,
                "via": "stage_reset" if stopped_any else None,
                "stage_reset": stage_info,
                "error": None,
            }

        stage_orchestrator.cleanup_presenter(sid)
        stage_orchestrator.cleanup_speech_summarizer(sid)

        # CoreAgent 有两类运行承载：① frago 服务进程内由 coreagent_runner 托管的实例；
        # ② CLI（如 frago agent 派发的 Worker）经 TmuxCoreProcess 拉起跑在独立
        # frago-agent-core_<sid> tmux 会话里的池外实例。因此先查进程内 coreagent_runner：
        # 若进程内确有活跃运行（running=True）直接就地停机返回；否则保留排队作废计数
        # core_dropped，继续向下回退查找并关闭同名 tmux 会话。
        is_core = False
        try:
            is_core = record_reader.detect_family(sid) == "coreagent"
        except UnknownSessionFamily:
            is_core = sid.startswith("core_")
        core_dropped = 0
        if is_core or coreagent_runner.live_cwd(sid) is not None:
            outcome = coreagent_runner.stop(sid, by="页面上的人")
            core_dropped = int(outcome.get("dropped", 0))
            if outcome.get("running"):
                if outcome.get("stopped"):
                    _bump_abort_epoch_safe(sid)
                return {
                    "sid": sid,
                    # `alive` 与另外几家同义：**按下去之前**有没有活着的运行，不是「现在还在不在」。
                    # 它与 `stopped` 一起读——两个都真，说的是「本来在跑，这一按停掉了」。
                    "alive": True,
                    "busy": bool(outcome["busy"]),
                    "stopped": bool(outcome["stopped"]),
                    # 排队里还没轮到、被这一按连带作废的条数。人刚发出去的话不见了，得有个数：
                    # 从前它悄没声地丢了，返回值里一个字都没有（这一场的记录里补了那一行）。
                    "dropped": core_dropped,
                    "name": None,
                    "via": "coreagent" if outcome["stopped"] else None,
                    "error": None,
                }

        link = svc.find_for_session(sid)
        if link is None:
            return {
                "sid": sid,
                "alive": False,
                "busy": False,
                "stopped": False,
                "dropped": core_dropped,
                "name": None,
                "via": None,
                "error": None,
            }
        if link.busy and not request.force:
            return {
                "sid": sid,
                "alive": True,
                "busy": True,
                "stopped": False,
                "dropped": core_dropped,
                "name": link.name,
                "via": None,
                "error": None,
            }
        result = svc.close_sessions([link.name])[0]
        if result["ok"]:
            _bump_abort_epoch_safe(sid)
        return {
            "sid": sid,
            "alive": True,
            "busy": link.busy,
            "stopped": bool(result["ok"]),
            "dropped": core_dropped,
            "name": link.name,
            "via": result["via"],
            "error": result["error"],
        }

    # 找会话要跑 tmux、读屏，关闭要跑 ps 与 kill，整趟都是阻塞 IO。
    return await asyncio.to_thread(_stop)


@router.get("/workbench/sessions/{sid}/terminal")
async def get_workbench_session_terminal(
    sid: str,
    lines: int = Query(500, ge=50, le=5000, description="抓取的最大行数"),
) -> dict[str, Any]:
    """抓取指定会话此刻的 tmux 终端屏幕（或已结束 CoreAgent 会话的留底终端输出）。"""
    from frago.server.services import tmux_sessions_service as svc

    return await asyncio.to_thread(svc.capture_session_terminal, sid, lines=lines)


@router.delete("/workbench/sessions/{sid}")
async def delete_workbench_session(sid: str) -> dict[str, Any]:
    """把一场会话从本机删掉，让它不再出现在会话清单里。

    三家都删，删法两家不同（详见 :func:`frago.session.record_reader.delete_session`）：
    Claude Code 的记录就是一个 JSONL 加一个同名目录，直接删干净；opencode 与 codex
    借引擎自己的删除命令。删完这一场从左栏消失，记录流也打不开。frago 在
    ``~/.frago/sessions/`` 下另存的副本不跟着动，命令行检索仍找得到它。

    **正在跑的会话不删，回 409。** 判据是 tmux 里此刻有没有一具活着的会话，与「结束运行」
    那个按钮问的是同一件事：那具壳还活着的话，它接着往新写出来的同名文件里落记录，人会
    以为删除没生效。NEVER 拿卡片上那个从记录文件推出来的「在跑」当判据——那条路和 tmux
    的真实情况对不上，一场昨天的会话记录还热着，tmux 早就没了。

    四种拒绝各有各的意思，NEVER 合并成一个 500：

    - 编号不属于任何一家 → 404；
    - 本机已经没有这场会话 → 404，要的结果已经成立，把人引到"失败"上是错的；
    - 这一场还在跑 → 409；
    - 引擎拒绝动手（没装那个命令、命令超时、它自己报错）→ 500，把它的话原样带出去。

    还有一条正常走不到的 400（``SessionDeleteUnsupported``）：将来 ``detect_family``
    多加一家而删除这条路还没跟上时，让它明着说不支持，好过落进别家的删法里。

    删掉之后再摘分组、置顶里那个编号，以及 frago 这边指着它的身份映射（后一件在
    ``delete_session`` 里做）。这些失败**不回滚删除也不报成失败**——会话已经不在盘上了，
    那句实话进 ``warnings`` 带回去，比假装整件事没做成有用。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    from frago.server.services import coreagent_runner
    from frago.server.services import tmux_sessions_service as tsvc

    # 读屏是阻塞 IO，且这条问路与「结束运行」共用同一份判据，两处 MUST 给出同一个答案。
    link = await asyncio.to_thread(tsvc.find_for_session, sid)
    if link is not None:
        raise HTTPException(
            status_code=409,
            detail=f"这一场还在跑（{link.name}），先结束运行再删",
        )
    if await asyncio.to_thread(coreagent_runner.running, sid):
        raise HTTPException(
            status_code=409,
            detail=f"这一场还在跑（coreagent: {sid}），先结束运行再删",
        )

    try:
        removed = await asyncio.to_thread(record_reader.delete_session, sid)
    except record_reader.SessionDeleteUnsupported as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except record_reader.SessionFilesMissing as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (EngineCliMissing, EngineCliFailed) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"没删掉：{e}") from e

    warnings = list(removed.problems)
    try:
        await asyncio.to_thread(workbench_groups.remove_session, sid)
    except Exception as e:  # noqa: BLE001 — 收尾没做干净要说出来，NEVER 吞掉
        warnings.append(f"分组里那个编号没摘掉：{e}")
    try:
        await asyncio.to_thread(workbench_pins.unpin, sid)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"置顶名单里那个编号没摘掉：{e}")

    return {
        "sid": removed.session_id,
        "family": removed.family,
        "removed": removed.removed,
        "warnings": warnings,
    }


@router.get("/workbench/records/{rid}/raw")
async def read_workbench_record_raw(
    rid: str,
    session_id: str = Query(..., description="这条记录属于哪一场会话"),
) -> dict[str, Any]:
    """取单条记录的原文。

    **报错类恒 403。** 那条原文的响应头里带着 Cloudflare 的登录凭据，服务端直接拒，
    NEVER 靠前端自觉不去点。上游对报错类返回空，这里把空翻成 403 而不是 200 加空值——
    200 加空值会让界面以为「这条没原文」而照常展开，判断权就又回到了前端手上。

    取不到的记录同样回 403 而不是 404：只有拿到原文才算放行，其余一律不放行。
    """
    try:
        raw = await asyncio.to_thread(record_reader.read_raw, session_id, rid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if raw is None:
        raise HTTPException(status_code=403, detail=f"记录 {rid} 的原文不予提供")
    return raw


# ── internal helpers ─────────────────────────────────────────────────


def _still_alive(
    session_id: str, *, in_tmux: bool, core_alive: dict[str, bool] | None = None
) -> bool:
    """这一场此刻还活着吗——两种活法，任一成立即算活着。

    * **开在 tmux 里**：另外三家（claude / codex / opencode）由 WebUI 或 ``frago agent``
      起在 tmux 里，终端开着就是活着。
    * **它是 CoreAgent 那一场、常驻进程还在**：CoreAgent **NEVER 开在 tmux 里**，它是
      frago 服务自己的子进程，拿 tmux 判它永远判成死的。

    为什么这一条必须有：会话详情页的两条取数通道共用这个判据——服务端照它决定盯不盯记录
    文件（实时推送），页面照它决定要不要持续取增量（兜底轮询）。CoreAgent 落在"死的"那一
    侧时，实时推送一次都不会建立、轮询又会在静默 15 分钟后自己关掉，于是那一轮明明在跑、
    结果也写进了记录，页面却永久停在发出那句话的那一刻，人只能刷新或切走再切回来才看得见
    （2026-10-08 实测：当前这一轮服务里 CoreAgent 目录的监听启动记录 0 条，同日志里 claude
    目录 21 条）。

    判据取 ``coreagent_runner.live_states()`` 而不是 ``busy()``：**跑完等人打字的那些也还
    开着**，人下一秒还要往里说话，此刻正是页面最该跟住的时候。空闲回收掉了、真正关了的
    那一场 ``state == "absent"``，自然回落成不盯——省资源的本意不变。

    ``core_alive`` 可以整批传进来（清单那一趟上百张卡片共用一次查询），不传就现问一场。
    """
    if in_tmux:
        return True
    if core_alive is not None:
        return core_alive.get(session_id, False)
    try:
        return coreagent_runner.running(session_id)
    except Exception:  # noqa: BLE001 — 判活着 NEVER 因为一次查询失败而炸，宁可不盯
        import logging

        logging.getLogger(__name__).warning(
            "Failed to check coreagent liveness for %s", session_id, exc_info=True
        )
        return False


def _ensure_watching(session_id: str) -> None:
    """这一场还活着就登记它的记录文件监听，否则撤掉可能留着的登记。

    Claude Code sessions (UUID-shaped) start a ``SessionStream`` per project;
    opencode sessions (``ses_`` prefix) start a shared ``OpencodeStream``.

    判据见 :func:`_still_alive`——**不止"开在 tmux 里"**，CoreAgent 那一场没有终端，要按它
    自己的常驻进程判。一条 ``list-sessions`` 加一次 ``live_states``，发话后一秒一趟的快
    节拍下也扛得住。不活着的照样补一次旁路观察的「打开」——右栏要靠它把早就答完的会话读
    一遍。
    """
    try:
        from frago.agent_driver.tmux_session import tmux_name_for
        from frago.server.services import tmux_sessions_service as tsvc
        from frago.server.services.workbench_stream_bridge import (
            WorkbenchStreamBridge,
        )

        bridge = WorkbenchStreamBridge.get_instance()
        in_tmux = tmux_name_for(session_id) in tsvc.open_session_names()
        if _still_alive(session_id, in_tmux=in_tmux):
            bridge.ensure_watching(session_id)
        else:
            bridge.release(session_id)
            bridge.note_opened(session_id)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Failed to start workbench watching for %s", session_id, exc_info=True
        )


def _keep_watching_only(session_ids: set[str]) -> None:
    """只留这几场的监听，其余撤掉，并顺带巡检存在待发队列的后台会话。撤不掉不打断取清单。"""
    try:
        from frago.server.services.workbench_stream_bridge import (
            WorkbenchStreamBridge,
        )

        bridge = WorkbenchStreamBridge.get_instance()
        bridge.keep_only(session_ids)
        workbench_queue._seed_queued_sessions_once()
        with workbench_queue._locks_guard:
            queued_alive = [
                sid for sid in workbench_queue._queued_sessions if sid in session_ids
            ]
        for sid in queued_alive:
            bridge.ensure_watching(sid)
        workbench_queue.patrol_active_queues_async()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Failed to prune workbench watching", exc_info=True)


class DesktopVoiceTranscribeRequest(BaseModel):
    """桌面右下角花瓣麦克风监听器提交的语音转写与投喂请求。"""

    audio_base64: str
    mime_type: str = "audio/webm"
    filename: str = "speech.webm"
    language: str | None = None
    session_id: str | None = None
    auto_send: bool = True
    cwd: str | None = None
    agent: str | None = None


class DesktopVoiceDispatchRequest(BaseModel):
    """直接将文本指令投喂给 desktop-operator 员工并开启旁路语音总结。"""

    text: str
    session_id: str | None = None
    cwd: str | None = None
    agent: str | None = None


class DesktopVoiceSummarizeRequest(BaseModel):
    """触发指定 desktop-operator 会话的 LightAgent 增量语音总结。"""

    session_id: str
    previous_summary: str = ""
    human_asr: str = ""
    max_turns: int = 3
    speak: bool = True


@router.post("/workbench/desktop-voice/transcribe")
async def transcribe_desktop_voice(request: DesktopVoiceTranscribeRequest) -> dict[str, Any]:
    """接收花瓣监听器录制的音频，经 Groq Whisper 转写后自动投喂给 desktop-operator 员工。"""
    import base64

    from frago.server.services import stage_orchestrator

    raw_b64 = (request.audio_base64 or "").strip()
    if "," in raw_b64 and raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1].strip()
    if not raw_b64:
        raise HTTPException(status_code=400, detail="未收到有效的录音数据。")

    try:
        audio_bytes = base64.b64decode(raw_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"音频 base64 解码失败：{e}") from e

    if len(audio_bytes) < 64:
        return {
            "text": "",
            "dispatched": False,
            "session_id": request.session_id,
            "reason": "audio_too_short",
        }

    try:
        asr_res = await asyncio.to_thread(
            stage_orchestrator.transcribe_audio_with_groq,
            audio_bytes,
            filename=request.filename,
            mime_type=request.mime_type,
            language=request.language,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    raw_text = str(asr_res.get("text") or "").strip()
    text = stage_orchestrator.clean_whisper_transcription(raw_text)
    if not text or not request.auto_send:
        resp_payload: dict[str, Any] = {
            "text": text,
            "language": asr_res.get("language"),
            "model": asr_res.get("model"),
            "dispatched": False,
            "session_id": request.session_id,
        }
        if (raw_text and not text) or asr_res.get("hallucination_filtered"):
            resp_payload["reason"] = "hallucination_filtered"
        return resp_payload

    from frago.server.services import workbench_agents

    try:
        dispatch_res = await asyncio.to_thread(
            stage_orchestrator.dispatch_desktop_voice_command,
            text,
            session_id=request.session_id,
            cwd=request.cwd,
            agent=request.agent,
        )
    except workbench_agents.AgentUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"投喂给 desktop-operator 失败：{e}") from e

    if dispatch_res.get("session_id"):
        _ensure_watching(dispatch_res["session_id"])
    return {
        "text": text,
        "language": asr_res.get("language"),
        "model": asr_res.get("model"),
        "dispatched": True,
        "session_id": dispatch_res.get("session_id"),
        "handle": dispatch_res.get("handle"),
        "agent": dispatch_res.get("agent"),
        "employee": dispatch_res["employee"],
        "status": dispatch_res["status"],
    }


@router.get("/workbench/desktop-voice/active-session")
async def get_active_desktop_voice_session(agent: str | None = None) -> dict[str, Any]:
    """查询 desktop-operator 最近活跃的存量会话 ID，并自动在当前服务进程中预挂载旁路语音提炼器。"""
    from frago.server.services import stage_orchestrator

    res = await asyncio.to_thread(
        stage_orchestrator.resolve_active_desktop_operator_session,
        ensure_summarizer=True,
        preferred_agent=agent,
    )
    active_sid = res.get("session_id")
    if isinstance(active_sid, str) and active_sid.strip():
        _ensure_watching(active_sid.strip())
    return res


@router.post("/workbench/desktop-voice/dispatch")
async def dispatch_desktop_voice_text(request: DesktopVoiceDispatchRequest) -> dict[str, Any]:
    """将文本请求直接派发给 desktop-operator 员工，并确保旁路语音总结器在线。"""
    from frago.server.services import stage_orchestrator, workbench_agents

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="发送内容不能为空。")
    try:
        res = await asyncio.to_thread(
            stage_orchestrator.dispatch_desktop_voice_command,
            request.text,
            session_id=request.session_id,
            cwd=request.cwd,
            agent=request.agent,
        )
    except workbench_agents.AgentUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"投喂给 desktop-operator 失败：{e}") from e

    if res.get("session_id"):
        _ensure_watching(res["session_id"])
    return res


@router.post("/workbench/desktop-voice/summarize")
async def summarize_desktop_operator_speech(request: DesktopVoiceSummarizeRequest) -> dict[str, Any]:
    """调用 LightAgent 单轮总结提炼 desktop-operator 的最近响应，并可选择立即合成语音播报。"""
    from frago.desktop import voice
    from frago.server.services import stage_orchestrator

    sid = request.session_id.strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id 不能为空。")

    spoken = await asyncio.to_thread(
        stage_orchestrator.summarize_operator_for_speech,
        sid,
        request.previous_summary,
        human_asr=request.human_asr,
        max_turns=request.max_turns,
    )
    chosen_voice = voice.resolve_emotional_voice(spoken) if spoken else voice.DEFAULT_VOICE
    spoke_on_desktop = False
    if spoken and request.speak:
        daemon = stage_orchestrator.ensure_speech_summarizer(sid, max_turns=request.max_turns)
        daemon.previous_summary = spoken
        spoke_on_desktop = await asyncio.to_thread(
            daemon._speak_on_desktop, spoken, chosen_voice
        )

    return {
        "session_id": sid,
        "spoken_text": spoken,
        "voice": chosen_voice,
        "spoke_on_desktop": spoke_on_desktop,
    }

