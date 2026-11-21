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
from frago.session.session_index import IN_PROGRESS_KINDS

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


def _is_card_active(
    card: Any,
    *,
    is_alive: bool,
    is_busy_core: bool,
    need_decision: bool = False,
) -> bool:
    status = getattr(card, "status", None)
    lifecycle = getattr(card, "lifecycle_state", None)
    last_kind = getattr(card, "last_kind", None)
    is_transcript_running = (
        is_alive
        and last_kind != "error"
        and (
            last_kind in IN_PROGRESS_KINDS
            or (last_kind != "agent.say" and status == "running")
        )
    )

    if is_busy_core or is_transcript_running:
        resolved_status = "running"
        resolved_lifecycle = "running"
    elif status == "error" or lifecycle == "error":
        resolved_status = "error"
        resolved_lifecycle = "error"
    else:
        if not is_alive and status == "running":
            resolved_status = "done" if last_kind == "agent.say" else "idle"
            resolved_lifecycle = "completed"
        else:
            resolved_status = status
            resolved_lifecycle = lifecycle or (
                "completed" if status in ("done", "idle") else None
            )

    return (
        resolved_status == "running"
        or resolved_lifecycle in ("running", "queued", "awaiting_input")
        or bool(getattr(card, "need_decision", False))
        or need_decision
    )


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

    direct_employee_by_sid: dict[str, str] = {}
    parent_by_sid: dict[str, str | None] = {}
    deduped_cards: list[Any] = []
    seen_sids: set[str] = set()
    for card in cards:
        sid = getattr(card, "session_id", "")
        if not sid or sid in seen_sids:
            continue
        seen_sids.add(sid)
        deduped_cards.append(card)
        parent_by_sid[sid] = getattr(card, "parent_session_id", None)
        emp_id = getattr(card, "employee_id", None) or active_employee_by_sid.get(sid)
        if emp_id:
            direct_employee_by_sid[sid] = emp_id

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

    try:
        from frago.server.routes.workbench import (
            _observer_slots_state,
            _session_needs_decision,
        )
    except Exception:  # noqa: BLE001
        _observer_slots_state = None
        _session_needs_decision = None

    now_ms = int(time.time() * 1000)
    usage: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {
        post.member_post_id: {"active": 0, "total": 0} for post in records
    }
    for card in deduped_cards:
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
        in_tmux = tmux_name_for(sid) in open_names
        is_alive = in_tmux or bool(core_alive.get(sid, False))
        is_busy_core = core_alive.get(sid) is True

        need_decision = False
        if (
            _session_needs_decision is not None
            and _observer_slots_state is not None
            and getattr(card, "status", None) != "error"
            and getattr(card, "origin", "human") != "worker"
        ):
            try:
                slots_need_decision, _all_done = _observer_slots_state(
                    sid, getattr(card, "family", "")
                )
                need_decision = _session_needs_decision(
                    card,
                    status=str(getattr(card, "status", "done")),
                    is_alive=is_alive,
                    has_running_worker=False,
                    callback_queued=False,
                    now_ms=now_ms,
                    slots_need_decision=slots_need_decision,
                )
            except Exception:  # noqa: BLE001
                need_decision = False

        if _is_card_active(
            card,
            is_alive=is_alive,
            is_busy_core=is_busy_core,
            need_decision=need_decision,
        ):
            bucket["active"] += 1

    # 尚在创建落盘窗口、尚未出现在 record_reader 中的 active_session_ids 也计入在办数与总数
    for post in records:
        bucket = counts.setdefault(post.member_post_id, {"active": 0, "total": 0})
        for sid in post.active_session_ids:
            if sid and sid not in seen_sids:
                seen_sids.add(sid)
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
