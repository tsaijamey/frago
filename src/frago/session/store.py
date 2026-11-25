"""frago session — unified ontology store for `AgentSessionProcess` (+R), `SessionLifecycleState` (~R), and `SessionOriginState` (~R).

Manages session persistence, cross-process advisory file locking (cross-platform,
Unix fcntl / Windows msvcrt), and bidirectional compatibility with legacy
``agent-launches.json`` records.

Layer: domain storage — imports only Python standard library and `frago.ontology.*`.
NEVER imports `frago.server` or `frago.cli`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from frago.file_guard import (
    FileGuardError,
    ProtectedFileReadError,
    atomic_write_text,
    backup_corrupted_file,
    has_nonempty_file,
    lkg_path_for,
    locked_file,
)
from frago.ontology.runtime import (
    normalize_session_lifecycle_state,
    normalize_session_origin,
)

logger = logging.getLogger(__name__)

DEFAULT_WORKBENCH_DIR = Path.home() / ".frago" / "workbench"
DEFAULT_SESSION_STORE_PATH = DEFAULT_WORKBENCH_DIR / "session-ontology-store.json"
DEFAULT_LEGACY_LEDGER_PATH = DEFAULT_WORKBENCH_DIR / "agent-launches.json"

# 与 `session_origin.LEDGER_LIMIT` 取同一个上限：回写老账本时按时间序保留最近这么多条。
# 这里不导入 `session_origin`（会成环），所以数值就地写一份，改上限时两处一起改。
LEDGER_LIMIT = 4000

# 老账本只记「关系」。没有关系的普通会话（人自己开的那一场）不该出现在里面——
# 一旦出现，出身判定就会把它当成派出去的活。
LEGACY_RELATION_KINDS: frozenset[str] = frozenset({"dispatch", "branch", "handoff"})


class StaleTurnSeqError(ValueError):
    """Raised when a late completion/transition event carries an outdated turn_seq."""


@dataclass
class SessionOntologyRecord:
    """Persistent domain record for an `AgentSessionProcess` and its state bindings."""

    session_id: str
    agent_kernel: str
    origin: str = "terminal"
    lifecycle_state: str = "running"
    is_worker: bool = False
    parent_session_id: str | None = None
    relation_kind: str | None = None  # dispatch | branch | handoff；普通会话为 None
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    cwd: str = ""
    transcript_uri: str = ""
    step_count: int = 0
    turn_seq: int = 0
    employee_id: str | None = None
    prompt_head: str = ""
    summary: str | None = None
    waiting_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.session_id = str(self.session_id).strip()
        self.agent_kernel = str(self.agent_kernel).strip().lower()
        self.origin = normalize_session_origin(self.origin, is_worker=self.is_worker)
        self.lifecycle_state = normalize_session_lifecycle_state(self.lifecycle_state)
        self.turn_seq = max(0, int(self.turn_seq or 0))
        self.employee_id = str(self.employee_id).strip() or None if self.employee_id else None
        # 先认 worker 身份：worker 就是 worker，出身一律写 worker。
        if self.is_worker or self.origin == "worker":
            self.is_worker = True
            self.origin = "worker"
        elif self.relation_kind == "dispatch":
            # 没有 worker 身份却带着「派活」的关系，只可能是旧字段默认值漏进来的。
            # 关系要由调用方明说，NEVER 由默认值替一场人类会话安上。
            self.relation_kind = None

    def has_legacy_relation(self) -> bool:
        """这条记录是否该出现在老账本（`agent-launches.json`）里。

        老账本记的是关系：谁派了谁、从哪场分出分支、把活交给谁。普通人类会话没有关系，
        写进去只会让出身判定把它误当 worker，所以这里明确排除。
        """
        if self.relation_kind not in LEGACY_RELATION_KINDS:
            return False
        if self.relation_kind == "dispatch":
            # 「派活」必然意味着有 worker，认不出父亲也仍然是 worker。
            return bool(self.is_worker)
        return True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_legacy_entry(self) -> dict[str, Any]:
        """Convert into the legacy dictionary format expected by `session_origin.py`."""
        legacy: dict[str, Any] = {
            "child": self.session_id,
            "parent": self.parent_session_id or None,
            "kind": self.relation_kind,
            "agent_type": self.agent_kernel,
            "cwd": self.cwd,
            "prompt_head": (self.prompt_head or "").strip()[:120],
            "at": int(self.created_at),
        }
        if self.relation_kind == "dispatch":
            # 出身判定看这一项：dispatch 一律 worker，哪怕没有父会话。
            legacy["origin"] = "worker"
        if self.relation_kind == "branch":
            legacy.update({
                "anchor": self.extra.get("anchor"),
                "note": self.extra.get("note", ""),
                "closed_at": self.extra.get("closed_at"),
                "closed_by": self.extra.get("closed_by"),
            })
        return legacy

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionOntologyRecord:
        d = dict(data)
        sid = str(d.get("session_id") or d.get("child") or "").strip()
        kernel = str(d.get("agent_kernel") or d.get("agent_type") or d.get("agent_family") or "claude").strip().lower()
        origin = str(d.get("origin") or d.get("source") or "terminal")
        # 关系字段两套键名都要认：本体存储用 `relation_kind`，老账本用 `kind`。
        # 两边都没有就是没有关系，NEVER 替它补一个「派活」上去。
        raw_rel_kind = d.get("relation_kind") or d.get("kind") or None
        rel_kind = str(raw_rel_kind).strip() or None if raw_rel_kind is not None else None
        # 「派活」本身就是 worker 的证据，认不出父亲也一样：命令行与定时任务派出去的活
        # 常常没有上级会话，但它们绝不是人自己开的那一场。
        is_worker = bool(
            d.get("is_worker")
            or rel_kind == "dispatch"
            or normalize_session_origin(origin) == "worker"
        )
        if is_worker:
            origin = "worker"
        lifecycle = str(d.get("lifecycle_state") or d.get("status") or "running")
        created_at = int(d.get("created_at") or d.get("at") or time.time())
        updated_at = int(d.get("updated_at") or created_at)
        parent_id = d.get("parent_session_id") or d.get("parent") or None

        # 分支那几项在老账本里是顶层键（`anchor` / `note` / `closed_at` / `closed_by`），
        # 在本体存储里归 `extra`。读老账本时不并进来，收口信息在这一步就丢了，
        # 后面无论怎么保护都无从判断「这条分支已经收过口」。
        extra = dict(d.get("extra") or {})
        for key in ("anchor", "note", "closed_at", "closed_by"):
            if key in d and key not in extra:
                extra[key] = d[key]

        raw_employee = d.get("employee_id") or extra.get("employee_id")
        clean_employee = str(raw_employee).strip() or None if raw_employee else None

        return cls(
            session_id=sid,
            agent_kernel=kernel,
            origin=origin,
            lifecycle_state=lifecycle,
            is_worker=is_worker,
            parent_session_id=str(parent_id) if parent_id else None,
            relation_kind=rel_kind,
            created_at=created_at,
            updated_at=updated_at,
            cwd=str(d.get("cwd") or ""),
            transcript_uri=str(d.get("transcript_uri") or d.get("source_file") or ""),
            step_count=int(d.get("step_count", 0)),
            turn_seq=max(0, int(d.get("turn_seq") or 0)),
            employee_id=clean_employee,
            prompt_head=str(d.get("prompt_head") or ""),
            summary=d.get("summary"),
            waiting_reason=d.get("waiting_reason"),
            extra=extra,
        )


def _keep_closed_branch(legacy_rec: SessionOntologyRecord | None, store_rec: SessionOntologyRecord) -> None:
    """老账本已经收口的分支，不许被本体存储里还没收口的那份冲回未收口。

    收口是人在页面上点出来的动作。老账本记得那次点击，本体存储可能还停在点击之前
    （收口只改了老账本、没同步过来）。两边一合，若拿没收口的那份当准，虚线的分支会
    重新变实，看起来像收口根本没生效。

    一并护住 ``anchor`` 与 ``note``：这两项与收口状态同源，都只由老账本那份带着
    （分支的锚点与备注是老账本的原生字段，本体存储里归 ``extra``）。收口只补
    ``closed_at`` / ``closed_by`` 的话，合并出来的那条分支会有收口时刻却没有锚点——
    页面画这条分支时锚点为空，虚线画不出来，看起来像这条分支从来没存在过。
    """
    if legacy_rec is None or store_rec is None:
        return
    if legacy_rec.relation_kind != "branch" or store_rec.relation_kind != "branch":
        return
    if not legacy_rec.extra.get("closed_at"):
        return
    if store_rec.extra.get("closed_at"):
        return
    store_rec.extra["closed_at"] = legacy_rec.extra.get("closed_at")
    store_rec.extra["closed_by"] = legacy_rec.extra.get("closed_by")
    # 锚点与备注：老账本那份有、本体存储这份空着才补，绝不覆盖已有的值。
    for key in ("anchor", "note"):
        if key not in store_rec.extra and key in legacy_rec.extra:
            store_rec.extra[key] = legacy_rec.extra[key]


class SessionOntologyStore:
    """Thread-safe and process-safe persistent store for session ontology records."""

    _process_lock = threading.Lock()

    def __init__(
        self,
        store_path: Path | None = None,
        *,
        legacy_ledger_path: Path | None = None,
    ) -> None:
        self.store_path = (
            Path(store_path)
            if store_path is not None
            else Path(os.environ.get("FRAGO_SESSION_STORE_PATH", str(DEFAULT_SESSION_STORE_PATH)))
        )
        self.legacy_ledger_path = (
            Path(legacy_ledger_path)
            if legacy_ledger_path is not None
            else Path(os.environ.get("FRAGO_LAUNCH_LEDGER_PATH", str(DEFAULT_LEGACY_LEDGER_PATH)))
        )
        self._cache_lock = threading.Lock()
        self._cache_sig: (
            tuple[tuple[int, int, int] | None, tuple[int, int, int] | None] | None
        ) = None
        self._cache_records: dict[str, SessionOntologyRecord] | None = None

    @staticmethod
    def _file_sig(path: Path) -> tuple[int, int, int] | None:
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None

    def _stat_signature(
        self,
    ) -> tuple[tuple[int, int, int] | None, tuple[int, int, int] | None]:
        return (self._file_sig(self.legacy_ledger_path), self._file_sig(self.store_path))

    @staticmethod
    def _clone_record(rec: SessionOntologyRecord) -> SessionOntologyRecord:
        return replace(rec, extra=dict(rec.extra))

    def _read_cached(self) -> dict[str, SessionOntologyRecord]:
        sig = self._stat_signature()
        with self._cache_lock:
            if self._cache_records is not None and self._cache_sig == sig:
                return self._cache_records
        with self._locked():
            sig = self._stat_signature()
            with self._cache_lock:
                if self._cache_records is not None and self._cache_sig == sig:
                    return self._cache_records
            records = self._read_disk_unlocked(raise_on_error=False)
            sig_after = self._stat_signature()
            with self._cache_lock:
                self._cache_sig = sig_after
                self._cache_records = records
            return records

    def _lock_path(self) -> Path:
        from frago.file_guard import lock_path_for

        return lock_path_for(self.store_path)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Cross-thread and cross-process safe file locking context via file_guard."""
        with locked_file(self.store_path, exclusive=True):
            yield

    def _load_json_with_lkg(
        self,
        path: Path,
        *,
        expected_type: type,
        raise_on_error: bool,
    ) -> Any:
        if not path.exists():
            return None
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, expected_type):
                return parsed
            raise ValueError(f"Expected {expected_type.__name__}, got {type(parsed).__name__}")
        except Exception as exc:
            lkg = lkg_path_for(path)
            if lkg.is_file():
                try:
                    lkg_parsed = json.loads(lkg.read_text(encoding="utf-8"))
                    if isinstance(lkg_parsed, expected_type):
                        backup_corrupted_file(path, reason="read_fallback_lkg")
                        logger.warning(
                            "Primary store %s unreadable (%s); recovered from LKG backup %s",
                            path,
                            exc,
                            lkg,
                        )
                        return lkg_parsed
                except Exception:
                    pass
            if raise_on_error and has_nonempty_file(path):
                raise ProtectedFileReadError(
                    f"Refusing destructive write because existing store {path} could not be read safely: {exc}"
                ) from exc
            logger.warning("Failed to read session store file %s: %s", path, exc)
            return None

    def _read_disk_unlocked(self, *, raise_on_error: bool = False) -> dict[str, SessionOntologyRecord]:
        records: dict[str, SessionOntologyRecord] = {}

        # 1. Read legacy ledger entries if exists
        raw_legacy = self._load_json_with_lkg(
            self.legacy_ledger_path,
            expected_type=list,
            raise_on_error=raise_on_error,
        )
        if isinstance(raw_legacy, list):
            for item in raw_legacy:
                if isinstance(item, dict):
                    rec = SessionOntologyRecord.from_dict(item)
                    if rec.session_id:
                        records[rec.session_id] = rec

        # 2. Read ontology store (overrides/enriches legacy entries)
        raw_store = self._load_json_with_lkg(
            self.store_path,
            expected_type=dict,
            raise_on_error=raise_on_error,
        )
        if isinstance(raw_store, dict):
            raw_items = raw_store.get("sessions", {})
            if isinstance(raw_items, dict):
                for sid, val in raw_items.items():
                    if isinstance(val, dict):
                        rec = SessionOntologyRecord.from_dict(val)
                        _keep_closed_branch(records.get(sid), rec)
                        records[sid] = rec
            elif isinstance(raw_items, list):
                for val in raw_items:
                    if isinstance(val, dict):
                        rec = SessionOntologyRecord.from_dict(val)
                        if rec.session_id:
                            _keep_closed_branch(records.get(rec.session_id), rec)
                            records[rec.session_id] = rec

        return records

    def _write_disk_unlocked(self, records: Mapping[str, SessionOntologyRecord]) -> bool:
        try:
            payload = {
                "version": 1,
                "updated_at": int(time.time()),
                "sessions": {sid: rec.to_dict() for sid, rec in records.items()},
            }
            atomic_write_text(
                self.store_path,
                json.dumps(payload, ensure_ascii=False, indent=2),
                save_lkg=True,
            )

            # 老账本只记关系，按时间序保留最近 LEDGER_LIMIT 条。
            # 两条约束缺一不可：写进没有关系的会话会让出身判定把它误当 worker；
            # 不截断则这份账会一直涨，越往后读越慢。
            legacy_entries = [
                rec.to_legacy_entry()
                for rec in sorted(records.values(), key=lambda r: r.created_at)
                if rec.has_legacy_relation()
            ][-LEDGER_LIMIT:]
            atomic_write_text(
                self.legacy_ledger_path,
                json.dumps(legacy_entries, ensure_ascii=False, indent=2),
                save_lkg=True,
            )
            sig_after = self._stat_signature()
            cached_copy = {sid: self._clone_record(rec) for sid, rec in records.items()}
            with self._cache_lock:
                self._cache_sig = sig_after
                self._cache_records = cached_copy
            return True
        except Exception:
            with self._cache_lock:
                self._cache_sig = None
                self._cache_records = None
            logger.debug("Failed to write session ontology store", exc_info=True)
            return False

    def get(self, session_id: str) -> SessionOntologyRecord | None:
        """Fetch a session record by session_id."""
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return None
        rec = self._read_cached().get(clean_id)
        return self._clone_record(rec) if rec is not None else None

    def save(self, record: SessionOntologyRecord) -> bool:
        """Upsert a session record."""
        if not record.session_id:
            return False
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            existing = records.get(record.session_id)
            if existing is not None and record.turn_seq < existing.turn_seq:
                record.turn_seq = existing.turn_seq
            if existing is not None and not record.employee_id and existing.employee_id:
                record.employee_id = existing.employee_id
            record.updated_at = int(time.time())
            records[record.session_id] = record
            return self._write_disk_unlocked(records)

    def upsert_relation(self, record: SessionOntologyRecord) -> bool:
        """Insert a relation record or incrementally merge lineage fields without clobbering lifecycle_state."""
        if not record.session_id:
            return False
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            existing = records.get(record.session_id)
            if existing is None:
                record.updated_at = int(time.time())
                records[record.session_id] = record
                return self._write_disk_unlocked(records)

            changed = False
            if (
                record.parent_session_id
                and record.parent_session_id != existing.session_id
                and not existing.parent_session_id
            ):
                existing.parent_session_id = record.parent_session_id
                changed = True
            if record.relation_kind and not existing.relation_kind:
                existing.relation_kind = record.relation_kind
                changed = True
            elif (
                record.relation_kind == "dispatch"
                and existing.relation_kind not in ("dispatch", "branch", "handoff")
            ):
                existing.relation_kind = "dispatch"
                changed = True
            if record.is_worker or record.relation_kind == "dispatch":
                if not existing.is_worker:
                    existing.is_worker = True
                    changed = True
                if existing.origin != "worker":
                    existing.origin = "worker"
                    changed = True
            if record.cwd and not existing.cwd:
                existing.cwd = record.cwd
                changed = True
            if record.prompt_head and not existing.prompt_head:
                existing.prompt_head = record.prompt_head
                changed = True
            if record.agent_kernel and not existing.agent_kernel:
                existing.agent_kernel = record.agent_kernel
                changed = True
            if record.employee_id and not existing.employee_id:
                existing.employee_id = record.employee_id
                changed = True
            if record.relation_kind == "branch" and record.extra:
                for key in ("anchor", "note", "closed_at", "closed_by"):
                    if (
                        key in record.extra
                        and record.extra[key] is not None
                        and key not in existing.extra
                    ):
                        existing.extra[key] = record.extra[key]
                        changed = True

            # NEVER overwrite lifecycle_state, turn_seq, summary, waiting_reason, step_count, created_at
            raw_store = self._load_json_with_lkg(
                self.store_path,
                expected_type=dict,
                raise_on_error=True,
            )
            store_sessions = (
                raw_store.get("sessions") if isinstance(raw_store, dict) else None
            )
            in_primary_store = (
                isinstance(store_sessions, dict) and record.session_id in store_sessions
            ) or (
                isinstance(store_sessions, list)
                and any(
                    isinstance(item, dict)
                    and str(item.get("session_id") or "").strip() == record.session_id
                    for item in store_sessions
                )
            )
            if not changed and in_primary_store:
                return True
            return self._write_disk_unlocked(records)

    def list_all(self) -> list[SessionOntologyRecord]:
        """List all active session ontology records ordered by updated_at desc."""
        records = self._read_cached()
        return [
            self._clone_record(r)
            for r in sorted(records.values(), key=lambda r: r.updated_at, reverse=True)
        ]

    def start_turn(
        self,
        session_id: str,
        *,
        summary: str | None = None,
    ) -> SessionOntologyRecord | None:
        """Atomically increment monotonic ``turn_seq`` and mark session ``running``."""
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return None
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            rec = records.get(clean_id)
            if rec is None:
                return None
            rec.turn_seq = max(0, int(rec.turn_seq)) + 1
            was_error = rec.lifecycle_state == "error"
            rec.lifecycle_state = "running"
            rec.waiting_reason = None
            rec.updated_at = int(time.time())
            if summary is not None:
                rec.summary = str(summary)
            elif was_error:
                rec.summary = ""
            if not self._write_disk_unlocked(records):
                raise FileGuardError(f"Failed to persist start_turn for session '{clean_id}'")
            return rec

    def update_lifecycle_state(
        self,
        session_id: str,
        new_state: str,
        *,
        waiting_reason: str | None = None,
        summary: str | None = None,
        expected_turn_seq: int | None = None,
    ) -> SessionOntologyRecord | None:
        """Update the lifecycle state of an existing session record.

        When ``expected_turn_seq`` is supplied and older than ``rec.turn_seq``,
        raises :class:`StaleTurnSeqError` so late completion events cannot cancel
        or overwrite a newer active turn.
        """
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return None
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            rec = records.get(clean_id)
            if rec is None:
                return None
            if expected_turn_seq is not None and int(expected_turn_seq) < int(rec.turn_seq):
                raise StaleTurnSeqError(
                    f"Late turn event rejected for '{clean_id}': "
                    f"event turn_seq={expected_turn_seq} < current turn_seq={rec.turn_seq}"
                )
            normalized = normalize_session_lifecycle_state(new_state)
            rec.lifecycle_state = normalized
            rec.updated_at = int(time.time())
            if waiting_reason is not None:
                rec.waiting_reason = str(waiting_reason)
            elif normalized in {"running", "completed", "error", "cancelled"}:
                rec.waiting_reason = None
            if summary is not None:
                rec.summary = str(summary)
            if not self._write_disk_unlocked(records):
                raise FileGuardError(
                    f"Failed to persist lifecycle state '{new_state}' for session '{clean_id}'"
                )
            return rec

    def batch_reconcile_states(
        self,
        updates: list[tuple[Any, ...]],
    ) -> int:
        """Apply multiple `(session_id, target_state, summary[, waiting_reason])` reconciliations atomically."""
        if not updates:
            return 0
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            now_ts = int(time.time())
            changed = 0
            for item in updates:
                raw_sid = item[0]
                raw_state = item[1]
                raw_summary = item[2] if len(item) > 2 else None
                raw_waiting_reason = item[3] if len(item) > 3 else None
                clean_id = str(raw_sid or "").strip()
                if not clean_id:
                    continue
                rec = records.get(clean_id)
                if rec is None:
                    continue
                target = normalize_session_lifecycle_state(raw_state)
                if (
                    rec.lifecycle_state == target
                    and (raw_summary is None or rec.summary == raw_summary)
                    and (
                        raw_waiting_reason is None
                        or rec.waiting_reason == raw_waiting_reason
                    )
                ):
                    continue
                was_error = rec.lifecycle_state == "error"
                rec.lifecycle_state = target
                rec.updated_at = now_ts
                if raw_summary is not None:
                    rec.summary = str(raw_summary)
                elif was_error and target == "running":
                    rec.summary = ""
                if raw_waiting_reason is not None:
                    rec.waiting_reason = str(raw_waiting_reason)
                elif target != "awaiting_input":
                    rec.waiting_reason = None
                changed += 1
            if changed and not self._write_disk_unlocked(records):
                raise FileGuardError("Failed to persist batch lifecycle state reconciliations")
            return changed

    def increment_step(self, session_id: str) -> int:
        """Atomically increment step_count for a session, returning new step_count."""
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return 0
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            rec = records.get(clean_id)
            if rec is None:
                return 0
            rec.step_count += 1
            rec.updated_at = int(time.time())
            self._write_disk_unlocked(records)
            return rec.step_count

    def close_branch(
        self,
        session_id: str,
        *,
        closed_at: int,
        closed_by: str,
    ) -> SessionOntologyRecord | None:
        """把一条分支记为已收口；本体里没有这条记录就返回 None。

        收口原先只改老账本，本体存储停在收口之前，下一次任何会话落盘都会把老账本整份
        覆写回去，已收口的分支重新变回未收口。这里让收口同时落到本体存储，两边一致。

        已经收口过的不再改写时刻与来路：第一次收口才是事实，重复点击不该把它冲掉。
        """
        clean_id = str(session_id or "").strip()
        if not clean_id:
            return None
        with self._locked():
            records = self._read_disk_unlocked(raise_on_error=True)
            rec = records.get(clean_id)
            if rec is None:
                return None
            if rec.extra.get("closed_at"):
                return rec
            rec.extra["closed_at"] = int(closed_at)
            rec.extra["closed_by"] = str(closed_by)
            rec.updated_at = int(time.time())
            self._write_disk_unlocked(records)
            return rec


_DEFAULT_SESSION_STORE = SessionOntologyStore()


def get_default_session_store() -> SessionOntologyStore:
    return _DEFAULT_SESSION_STORE
