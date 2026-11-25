"""Compute each employee post's most-recent session usage timestamp from real session history.

Truth source hierarchy (no fragile sidecar state):
1. Real session cards from :func:`frago.session.record_reader.list_sessions`
   (direct `employee_id`, `post.active_session_ids`, and human branch/handoff parent inheritance).
2. In-process recent-launch marks recorded when workbench creates/branches/handoffs an employee
   session, bridging the short window before claimed-ID engines flush session transcripts to disk.
"""

from __future__ import annotations

import inspect
import os
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from frago.employee import EmployeePostRecord
from frago.session import record_reader

_CACHE_TTL_S = 15.0
_lock = threading.Lock()
_cached_at: float = 0.0
_cached_env_key: tuple[str, str, str] | None = None
_cached_records_sig: tuple[tuple[str, tuple[str, ...]], ...] | None = None
_cached_ms_by_emp: dict[str, int] = {}
_cached_counts_by_emp: dict[str, dict[str, int]] = {}
_recent_selection_ms: dict[tuple[str, str, str], dict[str, int]] = {}


def _env_key() -> tuple[str, str, str]:
    return (
        os.environ.get("HOME", ""),
        os.environ.get("FRAGO_HOME", ""),
        os.environ.get("FRAGO_EMPLOYEES_DIR", ""),
    )


def _records_signature(
    records: Sequence[EmployeePostRecord],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((r.member_post_id, tuple(r.active_session_ids)) for r in records)


def epoch_ms_to_iso(ts_ms: int | None) -> str | None:
    """Convert epoch milliseconds to a millisecond-precision UTC ISO-8601 string."""
    if ts_ms is None or ts_ms <= 0:
        return None
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def invalidate_employee_usage_cache(member_post_id: str | None = None) -> None:
    """Clear the usage cache and optionally record an immediate launch timestamp for `member_post_id`."""
    global _cached_at, _cached_env_key, _cached_records_sig, _cached_ms_by_emp, _cached_counts_by_emp
    env = _env_key()
    now_ms = int(time.time() * 1000)
    with _lock:
        _cached_at = 0.0
        _cached_env_key = None
        _cached_records_sig = None
        _cached_ms_by_emp = {}
        _cached_counts_by_emp = {}
        if member_post_id and member_post_id.strip():
            bucket = _recent_selection_ms.setdefault(env, {})
            pid = member_post_id.strip()
            bucket[pid] = max(bucket.get(pid, 0), now_ms)


class _UsageLiveness(Mapping[str, bool]):
    """实时存活视图：tmux 在开或 CoreAgent 在运行即 True，与工作台口径一致。"""

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


def _resolve_card_state_for_usage(
    card: Any,
    *,
    onto_rec: Any | None,
    is_alive: bool,
    is_busy_core: bool,
    now_s: float,
    core_alive: Mapping[str, bool] | None = None,
    probes: Any | None = None,
) -> tuple[str, str]:
    """复刻工作台同源状态机收敛，产出 ``(status, lifecycle_state)``。"""
    from frago.session.service import evaluate_session_liveness_and_state

    reply_ts = getattr(card, "last_reply_at", None)
    last_reply_s = (
        (float(reply_ts) / 1000.0)
        if isinstance(reply_ts, int | float) and reply_ts > 0
        else None
    )
    eff_core_alive = (
        core_alive
        if core_alive is not None
        else ({card.session_id: True} if is_busy_core else {})
    )
    ev = evaluate_session_liveness_and_state(
        session_id=str(getattr(card, "session_id", "") or ""),
        onto_rec=onto_rec,
        card_status=str(getattr(card, "status", "done") or "done"),
        last_kind=getattr(card, "last_kind", None),
        last_active_s=float(getattr(card, "last_active_at", 0) or 0) / 1000.0,
        last_reply_s=last_reply_s,
        digest_stuck=getattr(card, "digest_stuck", None),
        in_tmux=bool(is_alive and not is_busy_core),
        liveness_flag=is_alive,
        core_alive=eff_core_alive,
        probes=probes,
        now_s=now_s,
        collapse_unmanaged_dead=True,
    )
    return ev.ui_status, ev.lifecycle_state


def _compute_usage_and_counts_from_sessions(
    records: Sequence[EmployeePostRecord],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    active_employee_by_sid: dict[str, str] = {
        sid: post.member_post_id
        for post in records
        for sid in post.active_session_ids
        if sid
    }

    try:
        from frago.agent_driver.tmux_session import tmux_name_for
        from frago.server.services import coreagent_runner
        from frago.server.services import tmux_sessions_service as tsvc

        open_names = tsvc.open_session_names()
        core_alive = coreagent_runner.live_states()
    except Exception:  # noqa: BLE001 — 探测失败时降级为空集合，不阻断员工清单
        tmux_name_for = lambda sid: f"frago-agent-{sid}"  # noqa: E731
        open_names = set()
        core_alive = {}

    liveness = _UsageLiveness(open_names, core_alive, tmux_name_for)
    try:
        sig = inspect.signature(record_reader.list_sessions)
        accepts_liveness = "liveness" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        cards = record_reader.list_sessions(
            **({"liveness": liveness} if accepts_liveness else {}),
        )
    except Exception:  # noqa: BLE001 — 会话目录不可读时降级，不阻断员工清单
        cards = []

    try:
        from frago.session.service import get_default_session_service

        onto_by_sid: dict[str, Any] = {
            rec.session_id: rec
            for rec in get_default_session_service().list_sessions()
            if getattr(rec, "session_id", None)
        }
    except Exception:  # noqa: BLE001
        onto_by_sid = {}

    try:
        from frago.server.routes.workbench import (
            _dispatch_states_by_caller,
            _observer_slots_state,
            _still_alive,
        )
    except Exception:  # noqa: BLE001
        _dispatch_states_by_caller = None
        _observer_slots_state = None
        _still_alive = None

    now_s = time.time()
    now_ms = int(now_s * 1000)

    probes = None
    try:
        from frago.session.service import collect_live_runtime_probes

        live_tmux_ids = {
            n[len("frago-agent-") :] for n in open_names if n.startswith("frago-agent-")
        }
        probes = collect_live_runtime_probes(
            live_tmux_ids=live_tmux_ids,
            core_alive=core_alive,
            now_s=now_s,
        )
    except Exception:  # noqa: BLE001
        probes = None

    direct_employee_by_sid: dict[str, str] = {}
    parent_by_sid: dict[str, str | None] = {}
    deduped_cards: list[Any] = []
    seen_sids: set[str] = set()
    computed_cards: list[tuple[Any, Any | None, str, str, bool, bool]] = []
    running_worker_parents: set[str] = set()
    active_target_ids: set[str] = set()
    caller_last_reply_ms: dict[str, int] = {}

    for card in cards:
        sid = getattr(card, "session_id", "")
        if not sid or sid in seen_sids:
            continue
        seen_sids.add(sid)
        deduped_cards.append(card)
        parent_by_sid[sid] = getattr(card, "parent_session_id", None)
        onto_rec = onto_by_sid.get(sid)
        emp_id = (
            getattr(card, "employee_id", None)
            or (getattr(onto_rec, "employee_id", None) if onto_rec is not None else None)
            or active_employee_by_sid.get(sid)
        )
        if emp_id:
            direct_employee_by_sid[sid] = emp_id

        in_tmux = tmux_name_for(sid) in open_names
        if _still_alive is not None:
            is_alive = _still_alive(sid, in_tmux=in_tmux, core_alive=core_alive)
        else:
            is_alive = in_tmux or bool(core_alive.get(sid, False))
        is_busy_core = core_alive.get(sid) is True
        resolved_status, resolved_lifecycle = _resolve_card_state_for_usage(
            card,
            onto_rec=onto_rec,
            is_alive=is_alive,
            is_busy_core=is_busy_core,
            now_s=now_s,
            core_alive=core_alive,
            probes=probes,
        )
        if resolved_status == "running" or (getattr(card, "family", None) == "coreagent" and is_alive):
            active_target_ids.add(sid)
        reply_ts = getattr(card, "last_reply_at", None)
        if isinstance(reply_ts, int) and reply_ts > 0:
            caller_last_reply_ms[sid] = reply_ts
        if (
            getattr(card, "origin", "human") == "worker"
            and getattr(card, "parent_session_id", None)
            and resolved_status == "running"
        ):
            running_worker_parents.add(card.parent_session_id)

        computed_cards.append((card, onto_rec, resolved_status, resolved_lifecycle, is_alive, is_busy_core))

    if _dispatch_states_by_caller is not None:
        try:
            running_callers, _callback_callers = _dispatch_states_by_caller(
                active_target_ids=active_target_ids,
                caller_last_reply_ms=caller_last_reply_ms,
                now_ms=now_ms,
            )
        except Exception:  # noqa: BLE001
            running_callers, _callback_callers = set(), set()
    else:
        running_callers, _callback_callers = set(), set()
    effective_running_parents = running_worker_parents | running_callers

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

    usage: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {
        post.member_post_id: {"active": 0, "total": 0} for post in records
    }
    for card, _onto_rec, resolved_status, resolved_lifecycle, _is_alive, _is_busy_core in computed_cards:
        emp_id = _resolve_employee_id(card)
        if not emp_id:
            continue
        ts_ms = max(
            int(getattr(card, "last_active_at", 0) or 0),
            int(getattr(card, "created_at", 0) or 0),
            int(getattr(card, "last_reply_at", 0) or 0),
        )
        if ts_ms > usage.get(emp_id, 0):
            usage[emp_id] = ts_ms
        bucket = counts.setdefault(emp_id, {"active": 0, "total": 0})
        bucket["total"] += 1

        sid = card.session_id
        has_running_worker = sid in effective_running_parents
        if _observer_slots_state is not None:
            try:
                _slots_need_decision, all_tasks_done = _observer_slots_state(
                    sid, getattr(card, "family", "")
                )
                if all_tasks_done and resolved_status != "running":
                    has_running_worker = False
            except Exception:  # noqa: BLE001
                pass

        if (
            resolved_status == "running"
            or resolved_lifecycle in ("running", "queued")
            or has_running_worker
        ):
            bucket["active"] += 1

    # 尚在创建落盘窗口、尚未出现在 record_reader 中的 active_session_ids 也计入在办数与总数
    from frago.session.service import _parse_iso_epoch

    env_recent = _recent_selection_ms.get(_env_key(), {})
    for post in records:
        bucket = counts.setdefault(post.member_post_id, {"active": 0, "total": 0})
        recent_ts = env_recent.get(post.member_post_id, 0)
        post_updated_s = _parse_iso_epoch(getattr(post, "updated_at", None))
        within_flush_window = (
            (recent_ts > 0 and (now_ms - recent_ts) <= 60_000)
            or (post_updated_s is not None and (now_s - post_updated_s) <= 60.0)
        )
        for sid in post.active_session_ids:
            if sid and sid not in seen_sids:
                seen_sids.add(sid)
                onto_rec = onto_by_sid.get(sid)
                if onto_rec is not None:
                    is_unflushed_active = (
                        getattr(onto_rec, "lifecycle_state", None) in ("running", "queued")
                    )
                else:
                    is_unflushed_active = bool(
                        sid in probes.live_drive_pids
                        or sid in probes.live_core_markers
                        or sid in probes.live_dispatch_targets
                        or core_alive.get(sid) is True
                        or (
                            _still_alive is not None
                            and _still_alive(
                                sid,
                                in_tmux=tmux_name_for(sid) in open_names,
                                core_alive=core_alive,
                            )
                        )
                        or within_flush_window
                    )
                if is_unflushed_active:
                    bucket["active"] += 1
                    bucket["total"] += 1

    return usage, counts


def _compute_usage_from_sessions(records: Sequence[EmployeePostRecord]) -> dict[str, int]:
    usage, _ = _compute_usage_and_counts_from_sessions(records)
    return usage


def get_employee_usage_summary(
    records: Sequence[EmployeePostRecord],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Return `({member_post_id: last_used_ms}, {member_post_id: {'active': n, 'total': m}})`."""
    global _cached_at, _cached_env_key, _cached_records_sig, _cached_ms_by_emp, _cached_counts_by_emp
    env = _env_key()
    sig = _records_signature(records)
    now_mono = time.monotonic()

    with _lock:
        if (
            _cached_env_key == env
            and _cached_records_sig == sig
            and (now_mono - _cached_at) < _CACHE_TTL_S
        ):
            merged_ms = dict(_cached_ms_by_emp)
            for pid, ts_ms in _recent_selection_ms.get(env, {}).items():
                if ts_ms > merged_ms.get(pid, 0):
                    merged_ms[pid] = ts_ms
            merged_counts = {
                pid: dict(cnt) for pid, cnt in _cached_counts_by_emp.items()
            }
            for post in records:
                merged_counts.setdefault(post.member_post_id, {"active": 0, "total": 0})
            return merged_ms, merged_counts

    computed_ms, computed_counts = _compute_usage_and_counts_from_sessions(records)
    with _lock:
        _cached_env_key = env
        _cached_records_sig = sig
        _cached_at = time.monotonic()
        _cached_ms_by_emp = dict(computed_ms)
        _cached_counts_by_emp = {
            pid: dict(cnt) for pid, cnt in computed_counts.items()
        }
        merged_ms = dict(computed_ms)
        for pid, ts_ms in _recent_selection_ms.get(env, {}).items():
            if ts_ms > merged_ms.get(pid, 0):
                merged_ms[pid] = ts_ms
        merged_counts = {
            pid: dict(cnt) for pid, cnt in computed_counts.items()
        }
        for post in records:
            merged_counts.setdefault(post.member_post_id, {"active": 0, "total": 0})
        return merged_ms, merged_counts


def get_employee_last_used_ms(records: Sequence[EmployeePostRecord]) -> dict[str, int]:
    """Return `{member_post_id: last_used_ms}` merged from real sessions and recent launches."""
    merged_ms, _ = get_employee_usage_summary(records)
    return merged_ms
