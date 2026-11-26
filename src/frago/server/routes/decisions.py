"""统一决策收件箱 REST API（``/api/workbench/decisions``）。

双源聚合唯一真源：
1. ``source="schedule"``：读取 :class:`DecisionInboxService` 管理的异步提案（``~/.frago/decision-inbox/``）；
2. ``source="session"``：同源复用 :func:`workbench.collect_workbench_session_rows` 中处于
   「Waiting decision」（``need_decision=True`` 且非运行中/错误/待回传）的今日在线会话，
   与 ``SessionRail`` 的「待决 (decision)」计数严格一致，绝不另算第二套会话计数器。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from frago.decision_inbox import (
    DecisionInboxError,
    DecisionNotFoundError,
    InvalidDecisionTransitionError,
    UndoNotAllowedError,
    extract_decision_card_detail,
    get_decision_inbox_service,
)
from frago.server.routes.workbench import (
    SendRequest,
    collect_workbench_session_rows,
    send_to_session,
)
from frago.server.services import workbench_today
from frago.server.websocket import broadcast_decision_inbox_update
from frago.session import record_reader

router = APIRouter()

_TODAY_WINDOW_MS = 24 * 60 * 60 * 1000
_SESSION_PREFIX = "session:"


class ResolveDecisionBody(BaseModel):
    choice: str | None = None
    choices: list[str] | None = None
    answer_text: str | None = None
    note: str | None = None
    actor: str = "human"


class RejectDecisionBody(BaseModel):
    note: str | None = None
    actor: str = "human"


class TransitionDecisionBody(BaseModel):
    actor: str = "human"


def _is_session_waiting(row: dict[str, Any]) -> bool:
    """与前端 ``sessionLifecycleOf`` 保持 1:1 等价的在线等待判定。"""
    status = str(row.get("status") or "")
    onto_state = str(row.get("lifecycle_state") or "").lower()
    if (
        status == "running"
        or bool(row.get("has_running_worker"))
        or (onto_state in {"running", "queued"} and status not in {"done", "idle", "error"})
    ):
        return False
    if status == "error" or (onto_state == "error" and status not in {"done", "idle"}):
        return False
    if bool(row.get("callback_queued")):
        return False
    return bool(row.get("need_decision"))


def _dedupe_session_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """与前端 ``dedupeSessions`` 保持一致，按 ``session_id`` 保留首条记录。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        sid = str(row.get("session_id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(row)
    return out


def _is_scheduled_row(row: dict[str, Any]) -> bool:
    """与前端 ``SessionRail.isScheduledSession`` 保持一致（local_ops 或 origin === 'schedule'）。"""
    return bool(row.get("local_ops")) or str(row.get("origin") or "") == "schedule"


def _expand_picked_group_ids(rows: list[dict[str, Any]]) -> set[str]:
    """与前端 ``expandSessionGroupIds(sessions, pickedToday)`` 对齐：将今日捡回会话扩成家族整组。"""
    try:
        picked = workbench_today.list_picked()
    except Exception:  # noqa: BLE001
        return set()
    seeds = [str(sid) for sid in picked if str(sid).strip()]
    if not seeds:
        return set()

    by_id: dict[str, dict[str, Any]] = {}
    parent_of: dict[str, str | None] = {}
    kids_of: dict[str, list[str]] = {}
    for row in rows:
        sid = str(row.get("session_id") or "")
        if not sid:
            continue
        by_id[sid] = row
        pid = row.get("parent_session_id")
        parent_of[sid] = str(pid) if pid else None
        if pid:
            kids_of.setdefault(str(pid), []).append(sid)

    out: set[str] = set()
    visited_roots: set[str] = set()
    for seed in seeds:
        out.add(seed)
        if seed not in by_id:
            continue
        cur = seed
        guard: set[str] = set()
        while parent_of.get(cur) and parent_of[cur] in by_id and cur not in guard:
            guard.add(cur)
            cur = str(parent_of[cur])
        if cur in visited_roots:
            continue
        visited_roots.add(cur)
        stack = [cur]
        seen_sub: set[str] = set()
        while stack:
            node = stack.pop()
            if node in seen_sub:
                continue
            seen_sub.add(node)
            out.add(node)
            for child in kids_of.get(node, ()):
                if child not in seen_sub:
                    stack.append(child)
    return out


def _in_today_window(
    row: dict[str, Any],
    *,
    floor_ms: int,
    scheduled_ids: set[str],
    picked_group_ids: set[str],
) -> bool:
    """与前端 ``useWorkbenchSessions.withinToday`` 及 ``SessionRail`` ``decision`` 口径严格对齐：
    1. 严格排除定时任务 / 本机管理会话（含其子会话），避免混入 ``source='session'``；
    2. 无条件保留今日捡回家族整组（``picked_group_ids``）；
    3. 滚动 24 小时窗口（``startOfToday(now) = now - 24h``）判定 ``last_reply_at`` / ``created_at``。
    """
    if _is_scheduled_row(row):
        return False
    parent_id = row.get("parent_session_id")
    if parent_id and str(parent_id) in scheduled_ids:
        return False
    sid = str(row.get("session_id") or "")
    if sid in picked_group_ids:
        return True
    last_reply = row.get("last_reply_at")
    created_at = row.get("created_at")
    if last_reply is not None:
        return int(last_reply) >= floor_ms
    if created_at is not None:
        return int(created_at) >= floor_ms
    last_active = row.get("last_active_at")
    return int(last_active) >= floor_ms if last_active is not None else False


def _extract_session_card_sync(session_id: str) -> dict[str, Any] | None:
    """同步读取最近记录中最后一条助手决策卡明细。"""
    try:
        recs = record_reader.read_records(session_id, limit=25)
    except Exception:  # noqa: BLE001
        return None
    for rec in reversed(recs):
        if rec.agent_path:
            continue
        payload = rec.payload if isinstance(rec.payload, dict) else {}
        text_candidates: list[str] = []
        if isinstance(payload.get("text"), str):
            text_candidates.append(payload["text"])
        content = payload.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    text_candidates.append(block["text"])
        elif isinstance(content, str):
            text_candidates.append(content)
        for txt in reversed(text_candidates):
            detail = extract_decision_card_detail(txt)
            if detail is not None:
                return detail
    return None


def _to_epoch_sec(raw_ts: Any, fallback_sec: float) -> float:
    if raw_ts is None:
        return fallback_sec
    val = float(raw_ts)
    if val > 1e11:
        val = val / 1000.0
    return val


def _synthesize_session_item(
    row: dict[str, Any],
    card_detail: dict[str, Any] | None,
    *,
    snoozed_record: dict[str, Any] | None,
    now_sec: float,
) -> dict[str, Any]:
    sid = str(row["session_id"])
    title = (
        (card_detail or {}).get("question")
        or str(row.get("title") or "").strip()
        or sid
    )
    why = str((card_detail or {}).get("why") or "").strip()
    options = list((card_detail or {}).get("options") or [])
    recommended = (card_detail or {}).get("recommended")
    if recommended is None and options:
        recommended = next((o["key"] for o in options if o.get("recommended")), None)
    irreversible = any(opt.get("reversible") is False for opt in options)
    action_type = str((card_detail or {}).get("action_type") or "text-answer")
    if action_type == "choice-and-text":
        action_type = "single-choice" if options else "text-answer"
    created_sec = _to_epoch_sec(
        row.get("last_reply_at") or row.get("last_active_at") or row.get("created_at"),
        now_sec,
    )
    digest = str(row.get("digest_done") or "").strip()
    summary = why or digest or title
    risk = "high" if irreversible else "medium"
    risk_label = "高危不可逆" if irreversible else "阻塞主线程"
    status = str(snoozed_record["status"]) if snoozed_record else "pending"
    return {
        "proposal_id": f"{_SESSION_PREFIX}{sid}",
        "dedup_key": f"{_SESSION_PREFIX}{sid}",
        "source": "session",
        "source_label": "在线等待",
        "action_type": action_type,
        "risk": risk,
        "risk_label": risk_label,
        "irreversible": irreversible,
        "title": title,
        "summary": summary,
        "why": why,
        "skip_reason": (
            f"在线会话调用交互决策卡（{action_type}），等待主理人确认。"
            if card_detail
            else "在线会话当前处于待决策状态，等待主理人回复。"
        ),
        "impact_scope": f"在线会话 · {row.get('title') or sid}",
        "evidence": digest or title,
        "options": options,
        "recommended": recommended,
        "selected_opt": recommended or (options[0]["key"] if options else None),
        "draft": (card_detail or {}).get("draft"),
        "suggestion": ((card_detail or {}).get("suggestions") or [None])[0],
        "session_id": sid,
        "session_title": row.get("title") or sid,
        "schedule_id": None,
        "schedule_name": f"在线对话 · {row.get('title') or sid}",
        "employee_id": row.get("employee_id"),
        "employee_name": row.get("employee_title") or row.get("employee_id") or "会话主控",
        "employee_color": row.get("employee_color") or "amber",
        "status": status,
        "ttl_hours": None,
        "created_at": created_sec,
        "updated_at": float(snoozed_record["updated_at"]) if snoozed_record else created_sec,
        "last_seen_at": created_sec,
        "expires_at": None,
        "occurrence_count": 1,
        "last_reversible_from_state": (
            snoozed_record.get("last_reversible_from_state") if snoozed_record else None
        ),
        "resolution": None,
    }


async def _collect_all_items() -> list[dict[str, Any]]:
    svc = get_decision_inbox_service()
    now_sec = time.time()
    schedule_items = svc.list_items(
        statuses=("pending", "snoozed", "resolved", "rejected", "expired", "superseded"),
        now=now_sec,
    )
    # 过滤出 schedule 项及仅用于在线会话搁置状态的影子记录（避免在线会话重复计数）
    snoozed_by_session: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for item in schedule_items:
        dk = str(item.get("dedup_key") or "")
        if item.get("source") == "session" and dk.startswith(_SESSION_PREFIX):
            sid = dk[len(_SESSION_PREFIX) :]
            if item.get("status") in {"pending", "snoozed"}:
                snoozed_by_session[sid] = item
            continue
        items.append(item)

    rows = _dedupe_session_rows(await collect_workbench_session_rows())
    picked_group_ids = _expand_picked_group_ids(rows)
    scheduled_ids = {str(r["session_id"]) for r in rows if _is_scheduled_row(r)}
    floor_ms = int((now_sec * 1000) - _TODAY_WINDOW_MS)
    waiting_rows = [
        r
        for r in rows
        if _in_today_window(
            r,
            floor_ms=floor_ms,
            scheduled_ids=scheduled_ids,
            picked_group_ids=picked_group_ids,
        )
        and _is_session_waiting(r)
    ]
    waiting_by_sid = {str(r["session_id"]): r for r in waiting_rows}

    # 清理跨轮次滞留的在线会话影子记录（经由 DecisionInboxService.supersede 本体跃迁）：
    # 1) 会话已脱离 waiting（如直接在原会话回复）；
    # 2) 或同一会话产生了晚于影子更新时间的新回复轮次。
    for sid, shadow in list(snoozed_by_session.items()):
        waiting_row = waiting_by_sid.get(sid)
        stale_reason: str | None = None
        if waiting_row is None:
            stale_reason = "在线会话已脱离待决状态，原搁置记录自动失效"
        else:
            latest_reply_sec = _to_epoch_sec(waiting_row.get("last_reply_at"), 0.0)
            shadow_updated_sec = float(shadow.get("updated_at") or 0.0)
            if latest_reply_sec > shadow_updated_sec:
                stale_reason = "在线会话产生新回复轮次，原搁置记录自动失效"
        if stale_reason is not None:
            with contextlib.suppress(
                DecisionInboxError, DecisionNotFoundError, InvalidDecisionTransitionError
            ):
                svc.supersede(
                    str(shadow["proposal_id"]),
                    reason=stale_reason,
                    actor="system",
                    now=now_sec,
                )
            snoozed_by_session.pop(sid, None)

    if waiting_rows:
        card_details = await asyncio.gather(
            *[
                asyncio.to_thread(_extract_session_card_sync, str(r["session_id"]))
                for r in waiting_rows
            ]
        )
        for row, detail in zip(waiting_rows, card_details, strict=True):
            sid = str(row["session_id"])
            items.append(
                _synthesize_session_item(
                    row,
                    detail,
                    snoozed_record=snoozed_by_session.get(sid),
                    now_sec=now_sec,
                )
            )

    items.sort(key=lambda i: float(i.get("updated_at") or i.get("created_at") or 0.0), reverse=True)
    return items


def _compute_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    pending_items = [i for i in items if i.get("status") == "pending"]
    snoozed_items = [i for i in items if i.get("status") == "snoozed"]
    return {
        "pending": len(pending_items),
        "schedule": sum(1 for i in pending_items if i.get("source") == "schedule"),
        "session": sum(1 for i in pending_items if i.get("source") == "session"),
        "snoozed": len(snoozed_items),
    }


def _format_session_reply(
    item: dict[str, Any],
    *,
    approved: bool,
    choice: str | None = None,
    choices: list[str] | None = None,
    answer_text: str | None = None,
    note: str | None = None,
) -> str:
    options = {str(o.get("key")): o for o in (item.get("options") or []) if isinstance(o, dict)}
    clean_note = (note or "").strip()
    clean_answer = (answer_text or "").strip()

    if not approved:
        base = f"驳回执行「{item.get('title') or ''}」"
        return f"{base}（备注：{clean_note}）" if clean_note else base

    if choices:
        parts = []
        for c in choices:
            opt = options.get(c)
            parts.append(f"{c}（{opt['label']}）" if opt and opt.get("label") else c)
        base = f"已选择：{', '.join(parts)}"
    elif choice:
        opt = options.get(choice)
        base = f"已选择：{choice}（{opt['label']}）" if opt and opt.get("label") else f"已选择：{choice}"
    elif clean_answer:
        base = clean_answer
    else:
        base = f"确认批准执行「{item.get('title') or ''}」"

    if clean_note and clean_note != base:
        return f"{base}\n备注：{clean_note}"
    return base


async def _find_session_item(sid: str) -> dict[str, Any] | None:
    items = await _collect_all_items()
    target_id = f"{_SESSION_PREFIX}{sid}"
    return next((i for i in items if i["proposal_id"] == target_id), None)


@router.get("/workbench/decisions")
async def list_workbench_decisions(
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> dict[str, Any]:
    """返回统一决策收件箱聚合清单与同源计数。"""
    all_items = await _collect_all_items()
    counts = _compute_counts(all_items)

    filtered = all_items
    if status and status != "all":
        filtered = [i for i in filtered if i.get("status") == status]
    else:
        filtered = [i for i in filtered if i.get("status") in {"pending", "snoozed"}]
    if source and source != "all":
        filtered = [i for i in filtered if i.get("source") == source]

    return {
        "items": filtered,
        "counts": counts,
    }


@router.post("/workbench/decisions/{proposal_id}/resolve")
async def resolve_workbench_decision(
    proposal_id: str, body: ResolveDecisionBody
) -> dict[str, Any]:
    """批复（批准执行 / 选定方案）指定提案或在线等待会话。"""
    if proposal_id.startswith(_SESSION_PREFIX):
        sid = proposal_id[len(_SESSION_PREFIX) :]
        item = await _find_session_item(sid)
        if item is None:
            raise HTTPException(status_code=404, detail=f"未找到待决会话 {sid}")
        reply_text = _format_session_reply(
            item,
            approved=True,
            choice=body.choice,
            choices=body.choices,
            answer_text=body.answer_text,
            note=body.note,
        )
        send_res = await send_to_session(sid, SendRequest(text=reply_text, wait=False))
        svc = get_decision_inbox_service()
        shadow = svc.store.find_active_by_dedup_key(proposal_id)
        if shadow is not None:
            svc.resolve(
                shadow["proposal_id"],
                choice=body.choice,
                choices=body.choices,
                answer_text=body.answer_text,
                note=body.note,
                actor=body.actor,
            )
        all_items = await _collect_all_items()
        counts = _compute_counts(all_items)
        await broadcast_decision_inbox_update(
            counts, action="resolve", proposal_id=proposal_id
        )
        return {
            "item": {**item, "status": "resolved"},
            "counts": counts,
            "dispatch": send_res,
        }

    svc = get_decision_inbox_service()
    try:
        updated = svc.resolve(
            proposal_id,
            choice=body.choice,
            choices=body.choices,
            answer_text=body.answer_text,
            note=body.note,
            actor=body.actor,
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDecisionTransitionError, DecisionInboxError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    all_items = await _collect_all_items()
    counts = _compute_counts(all_items)
    await broadcast_decision_inbox_update(counts, action="resolve", proposal_id=proposal_id)
    return {"item": updated, "counts": counts}


@router.post("/workbench/decisions/{proposal_id}/reject")
async def reject_workbench_decision(
    proposal_id: str, body: RejectDecisionBody
) -> dict[str, Any]:
    """驳回指定提案或在线等待会话。"""
    if proposal_id.startswith(_SESSION_PREFIX):
        sid = proposal_id[len(_SESSION_PREFIX) :]
        item = await _find_session_item(sid)
        if item is None:
            raise HTTPException(status_code=404, detail=f"未找到待决会话 {sid}")
        reply_text = _format_session_reply(item, approved=False, note=body.note)
        send_res = await send_to_session(sid, SendRequest(text=reply_text, wait=False))
        svc = get_decision_inbox_service()
        shadow = svc.store.find_active_by_dedup_key(proposal_id)
        if shadow is not None:
            svc.reject(shadow["proposal_id"], note=body.note, actor=body.actor)
        all_items = await _collect_all_items()
        counts = _compute_counts(all_items)
        await broadcast_decision_inbox_update(counts, action="reject", proposal_id=proposal_id)
        return {
            "item": {**item, "status": "rejected"},
            "counts": counts,
            "dispatch": send_res,
        }

    svc = get_decision_inbox_service()
    try:
        updated = svc.reject(proposal_id, note=body.note, actor=body.actor)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDecisionTransitionError, DecisionInboxError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    all_items = await _collect_all_items()
    counts = _compute_counts(all_items)
    await broadcast_decision_inbox_update(counts, action="reject", proposal_id=proposal_id)
    return {"item": updated, "counts": counts}


@router.post("/workbench/decisions/{proposal_id}/snooze")
async def snooze_workbench_decision(
    proposal_id: str, body: TransitionDecisionBody | None = None
) -> dict[str, Any]:
    """搁置指定提案（可撤销）。"""
    actor = body.actor if body else "human"
    svc = get_decision_inbox_service()

    if proposal_id.startswith(_SESSION_PREFIX):
        sid = proposal_id[len(_SESSION_PREFIX) :]
        item = await _find_session_item(sid)
        if item is None:
            raise HTTPException(status_code=404, detail=f"未找到待决会话 {sid}")
        shadow = svc.store.find_active_by_dedup_key(proposal_id)
        if shadow is None:
            shadow = svc.propose(
                question=item["title"],
                action_type=item["action_type"],
                options=item.get("options"),
                recommended=item.get("recommended"),
                why=item.get("why") or "",
                impact_scope=item.get("impact_scope") or "",
                evidence=item.get("evidence") or "",
                risk=item.get("risk") or "low",
                irreversible=bool(item.get("irreversible")),
                dedup_key=proposal_id,
                source="session",
                session_id=sid,
                employee_id=item.get("employee_id"),
                employee_name=item.get("employee_name"),
                employee_color=item.get("employee_color"),
            )
        if shadow["status"] == "pending":
            shadow = svc.snooze(shadow["proposal_id"], actor=actor)
        all_items = await _collect_all_items()
        counts = _compute_counts(all_items)
        await broadcast_decision_inbox_update(counts, action="snooze", proposal_id=proposal_id)
        return {"item": {**item, "status": "snoozed"}, "counts": counts}

    try:
        updated = svc.snooze(proposal_id, actor=actor)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDecisionTransitionError, DecisionInboxError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    all_items = await _collect_all_items()
    counts = _compute_counts(all_items)
    await broadcast_decision_inbox_update(counts, action="snooze", proposal_id=proposal_id)
    return {"item": updated, "counts": counts}


@router.post("/workbench/decisions/{proposal_id}/unsnooze")
async def unsnooze_workbench_decision(
    proposal_id: str, body: TransitionDecisionBody | None = None
) -> dict[str, Any]:
    """恢复已搁置提案为待处理（可撤销）。"""
    actor = body.actor if body else "human"
    svc = get_decision_inbox_service()

    if proposal_id.startswith(_SESSION_PREFIX):
        sid = proposal_id[len(_SESSION_PREFIX) :]
        shadow = svc.store.find_active_by_dedup_key(proposal_id)
        if shadow is None:
            raise HTTPException(status_code=404, detail=f"会话 {sid} 未处于搁置状态")
        if shadow["status"] == "snoozed":
            svc.unsnooze(shadow["proposal_id"], actor=actor)
        item = await _find_session_item(sid)
        all_items = await _collect_all_items()
        counts = _compute_counts(all_items)
        await broadcast_decision_inbox_update(counts, action="unsnooze", proposal_id=proposal_id)
        return {"item": item or {**shadow, "status": "pending"}, "counts": counts}

    try:
        updated = svc.unsnooze(proposal_id, actor=actor)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDecisionTransitionError, DecisionInboxError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    all_items = await _collect_all_items()
    counts = _compute_counts(all_items)
    await broadcast_decision_inbox_update(counts, action="unsnooze", proposal_id=proposal_id)
    return {"item": updated, "counts": counts}


@router.post("/workbench/decisions/{proposal_id}/undo")
async def undo_workbench_decision(
    proposal_id: str, body: TransitionDecisionBody | None = None
) -> dict[str, Any]:
    """撤销最近一次可逆状态切换（仅 pending ↔ snoozed；已批复/已驳回严禁伪撤销）。"""
    actor = body.actor if body else "human"
    svc = get_decision_inbox_service()

    if proposal_id.startswith(_SESSION_PREFIX):
        sid = proposal_id[len(_SESSION_PREFIX) :]
        shadow = svc.store.find_active_by_dedup_key(proposal_id)
        if shadow is None:
            raise HTTPException(status_code=409, detail="该会话条目当前没有可撤销的状态切换。")
        try:
            updated_shadow = svc.undo(shadow["proposal_id"], actor=actor)
        except UndoNotAllowedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        item = await _find_session_item(sid)
        all_items = await _collect_all_items()
        counts = _compute_counts(all_items)
        await broadcast_decision_inbox_update(counts, action="undo", proposal_id=proposal_id)
        return {
            "item": item or {**updated_shadow, "proposal_id": proposal_id},
            "counts": counts,
        }

    try:
        updated = svc.undo(proposal_id, actor=actor)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (UndoNotAllowedError, InvalidDecisionTransitionError, DecisionInboxError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    all_items = await _collect_all_items()
    counts = _compute_counts(all_items)
    await broadcast_decision_inbox_update(counts, action="undo", proposal_id=proposal_id)
    return {"item": updated, "counts": counts}
