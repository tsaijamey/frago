"""Compute each employee post's most-recent session usage timestamp from real session history.

Truth source hierarchy (no fragile sidecar state):
1. Real session cards from :func:`frago.session.record_reader.list_sessions`
   (direct `employee_id`, `post.active_session_ids`, and human branch/handoff parent inheritance).
2. In-process recent-launch marks recorded when workbench creates/branches/handoffs an employee
   session, bridging the short window before claimed-ID engines flush session transcripts to disk.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from frago.employee import EmployeePostRecord
from frago.session import record_reader

_CACHE_TTL_S = 15.0
_lock = threading.Lock()
_cached_at: float = 0.0
_cached_env_key: tuple[str, str, str] | None = None
_cached_ms_by_emp: dict[str, int] = {}
_recent_selection_ms: dict[tuple[str, str, str], dict[str, int]] = {}


def _env_key() -> tuple[str, str, str]:
    return (
        os.environ.get("HOME", ""),
        os.environ.get("FRAGO_HOME", ""),
        os.environ.get("FRAGO_EMPLOYEES_DIR", ""),
    )


def epoch_ms_to_iso(ts_ms: int | None) -> str | None:
    """Convert epoch milliseconds to a millisecond-precision UTC ISO-8601 string."""
    if ts_ms is None or ts_ms <= 0:
        return None
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def invalidate_employee_usage_cache(member_post_id: str | None = None) -> None:
    """Clear the usage cache and optionally record an immediate launch timestamp for `member_post_id`."""
    global _cached_at, _cached_env_key, _cached_ms_by_emp
    env = _env_key()
    now_ms = int(time.time() * 1000)
    with _lock:
        _cached_at = 0.0
        _cached_env_key = None
        _cached_ms_by_emp = {}
        if member_post_id and member_post_id.strip():
            bucket = _recent_selection_ms.setdefault(env, {})
            pid = member_post_id.strip()
            bucket[pid] = max(bucket.get(pid, 0), now_ms)


def _compute_usage_from_sessions(records: Sequence[EmployeePostRecord]) -> dict[str, int]:
    active_employee_by_sid: dict[str, str] = {
        sid: post.member_post_id
        for post in records
        for sid in post.active_session_ids
        if sid
    }

    try:
        cards = record_reader.list_sessions()
    except Exception:  # noqa: BLE001 — 会话目录不可读时降级，不阻断员工清单
        cards = []

    direct_employee_by_sid: dict[str, str] = {}
    parent_by_sid: dict[str, str | None] = {}
    for card in cards:
        parent_by_sid[card.session_id] = card.parent_session_id
        emp_id = card.employee_id or active_employee_by_sid.get(card.session_id)
        if emp_id:
            direct_employee_by_sid[card.session_id] = emp_id

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
    for card in cards:
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
    return usage


def get_employee_last_used_ms(records: Sequence[EmployeePostRecord]) -> dict[str, int]:
    """Return `{member_post_id: last_used_ms}` merged from real sessions and recent launches."""
    global _cached_at, _cached_env_key, _cached_ms_by_emp
    env = _env_key()
    now_mono = time.monotonic()

    with _lock:
        if (
            _cached_env_key == env
            and (now_mono - _cached_at) < _CACHE_TTL_S
        ):
            merged = dict(_cached_ms_by_emp)
            for pid, ts_ms in _recent_selection_ms.get(env, {}).items():
                if ts_ms > merged.get(pid, 0):
                    merged[pid] = ts_ms
            return merged

    computed = _compute_usage_from_sessions(records)
    with _lock:
        _cached_env_key = env
        _cached_at = time.monotonic()
        _cached_ms_by_emp = dict(computed)
        merged = dict(computed)
        for pid, ts_ms in _recent_selection_ms.get(env, {}).items():
            if ts_ms > merged.get(pid, 0):
                merged[pid] = ts_ms
        return merged
