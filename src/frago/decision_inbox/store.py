"""统一决策收件箱受管持久化底座（SQLite WAL + append-only events.jsonl）。

默认落盘在 ``~/.frago/decision-inbox/``（支持 ``FRAGO_DECISION_INBOX_DIR`` 环境变量覆盖以便
测试隔离）。遵循零先验配置原则：在空目录或全新环境执行只读查询时直接返回空集合，不报错也不
预先污染磁盘；仅在首次写入提案或状态跃迁时按需建目录建表。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ENV_INBOX_DIR = "FRAGO_DECISION_INBOX_DIR"


def resolve_decision_inbox_dir(root_dir: Path | None = None) -> Path:
    if root_dir is not None:
        return Path(root_dir)
    override = os.environ.get(ENV_INBOX_DIR, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".frago" / "decision-inbox"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    dedup_key TEXT NOT NULL,
    source TEXT NOT NULL,
    source_label TEXT NOT NULL,
    action_type TEXT NOT NULL,
    risk TEXT NOT NULL,
    risk_label TEXT NOT NULL,
    irreversible INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    why TEXT NOT NULL DEFAULT '',
    skip_reason TEXT NOT NULL DEFAULT '',
    impact_scope TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '[]',
    recommended TEXT,
    selected_opt TEXT,
    draft TEXT,
    suggestion TEXT,
    session_id TEXT,
    schedule_id TEXT,
    schedule_name TEXT,
    employee_id TEXT,
    employee_name TEXT,
    employee_color TEXT,
    status TEXT NOT NULL,
    ttl_hours REAL NOT NULL DEFAULT 72.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    last_reversible_from_state TEXT,
    resolution_json TEXT,
    schedule_notified_at REAL
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_dedup ON proposals(dedup_key, status);
CREATE INDEX IF NOT EXISTS idx_proposals_schedule ON proposals(schedule_id, status);
CREATE INDEX IF NOT EXISTS idx_proposals_session ON proposals(session_id, status);
"""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    options_raw = row["options_json"] or "[]"
    try:
        options = json.loads(options_raw)
        if not isinstance(options, list):
            options = []
    except json.JSONDecodeError:
        options = []

    res_raw = row["resolution_json"]
    resolution: dict[str, Any] | None = None
    if res_raw:
        try:
            parsed = json.loads(res_raw)
            if isinstance(parsed, dict):
                resolution = parsed
        except json.JSONDecodeError:
            resolution = None

    return {
        "proposal_id": str(row["proposal_id"]),
        "dedup_key": str(row["dedup_key"]),
        "source": str(row["source"]),
        "source_label": str(row["source_label"]),
        "action_type": str(row["action_type"]),
        "risk": str(row["risk"]),
        "risk_label": str(row["risk_label"]),
        "irreversible": bool(row["irreversible"]),
        "title": str(row["title"]),
        "summary": str(row["summary"] or ""),
        "why": str(row["why"] or ""),
        "skip_reason": str(row["skip_reason"] or ""),
        "impact_scope": str(row["impact_scope"] or ""),
        "evidence": str(row["evidence"] or ""),
        "options": options,
        "recommended": row["recommended"],
        "selected_opt": row["selected_opt"],
        "draft": row["draft"],
        "suggestion": row["suggestion"],
        "session_id": row["session_id"],
        "schedule_id": row["schedule_id"],
        "schedule_name": row["schedule_name"],
        "employee_id": row["employee_id"],
        "employee_name": row["employee_name"],
        "employee_color": row["employee_color"],
        "status": str(row["status"]),
        "ttl_hours": float(row["ttl_hours"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "last_seen_at": float(row["last_seen_at"]),
        "expires_at": float(row["expires_at"]),
        "occurrence_count": int(row["occurrence_count"]),
        "last_reversible_from_state": row["last_reversible_from_state"],
        "resolution": resolution,
        "schedule_notified_at": (
            float(row["schedule_notified_at"])
            if row["schedule_notified_at"] is not None
            else None
        ),
    }


class DecisionInboxStore:
    """SQLite WAL + JSONL 审计日志受管存储。"""

    def __init__(self, root_dir: Path | None = None) -> None:
        self._explicit_root = Path(root_dir) if root_dir is not None else None
        self._lock = threading.RLock()

    @property
    def root_dir(self) -> Path:
        return resolve_decision_inbox_dir(self._explicit_root)

    @property
    def db_path(self) -> Path:
        return self.root_dir / "inbox.db"

    @property
    def events_path(self) -> Path:
        return self.root_dir / "events.jsonl"

    def _connect_existing(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _connect_init(self) -> sqlite3.Connection:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_SQL)
        return conn

    def append_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            payload = {"ts": time.time(), **event}
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect_existing()
            if conn is None:
                return None
            try:
                row = conn.execute(
                    "SELECT * FROM proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                return _row_to_dict(row) if row is not None else None
            except sqlite3.OperationalError:
                return None
            finally:
                conn.close()

    def find_active_by_dedup_key(self, dedup_key: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect_existing()
            if conn is None:
                return None
            try:
                row = conn.execute(
                    """
                    SELECT * FROM proposals
                    WHERE dedup_key = ? AND status IN ('pending', 'snoozed')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (dedup_key,),
                ).fetchone()
                return _row_to_dict(row) if row is not None else None
            except sqlite3.OperationalError:
                return None
            finally:
                conn.close()

    def list_all(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
        source: str | None = None,
        schedule_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect_existing()
            if conn is None:
                return []
            try:
                clauses: list[str] = []
                params: list[Any] = []
                if statuses:
                    placeholders = ",".join("?" for _ in statuses)
                    clauses.append(f"status IN ({placeholders})")
                    params.extend(statuses)
                if source:
                    clauses.append("source = ?")
                    params.append(source)
                if schedule_id:
                    clauses.append("schedule_id = ?")
                    params.append(schedule_id)
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                sql = f"SELECT * FROM proposals {where} ORDER BY updated_at DESC, created_at DESC"
                rows = conn.execute(sql, params).fetchall()
                return [_row_to_dict(r) for r in rows]
            except sqlite3.OperationalError:
                return []
            finally:
                conn.close()

    def upsert(self, item: dict[str, Any], *, event_type: str, event_detail: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            conn = self._connect_init()
            try:
                conn.execute(
                    """
                    INSERT INTO proposals (
                        proposal_id, dedup_key, source, source_label, action_type,
                        risk, risk_label, irreversible, title, summary, why,
                        skip_reason, impact_scope, evidence, options_json,
                        recommended, selected_opt, draft, suggestion,
                        session_id, schedule_id, schedule_name,
                        employee_id, employee_name, employee_color,
                        status, ttl_hours, created_at, updated_at, last_seen_at,
                        expires_at, occurrence_count, last_reversible_from_state,
                        resolution_json, schedule_notified_at
                    ) VALUES (
                        :proposal_id, :dedup_key, :source, :source_label, :action_type,
                        :risk, :risk_label, :irreversible, :title, :summary, :why,
                        :skip_reason, :impact_scope, :evidence, :options_json,
                        :recommended, :selected_opt, :draft, :suggestion,
                        :session_id, :schedule_id, :schedule_name,
                        :employee_id, :employee_name, :employee_color,
                        :status, :ttl_hours, :created_at, :updated_at, :last_seen_at,
                        :expires_at, :occurrence_count, :last_reversible_from_state,
                        :resolution_json, :schedule_notified_at
                    )
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        dedup_key=excluded.dedup_key,
                        source=excluded.source,
                        source_label=excluded.source_label,
                        action_type=excluded.action_type,
                        risk=excluded.risk,
                        risk_label=excluded.risk_label,
                        irreversible=excluded.irreversible,
                        title=excluded.title,
                        summary=excluded.summary,
                        why=excluded.why,
                        skip_reason=excluded.skip_reason,
                        impact_scope=excluded.impact_scope,
                        evidence=excluded.evidence,
                        options_json=excluded.options_json,
                        recommended=excluded.recommended,
                        selected_opt=excluded.selected_opt,
                        draft=excluded.draft,
                        suggestion=excluded.suggestion,
                        session_id=excluded.session_id,
                        schedule_id=excluded.schedule_id,
                        schedule_name=excluded.schedule_name,
                        employee_id=excluded.employee_id,
                        employee_name=excluded.employee_name,
                        employee_color=excluded.employee_color,
                        status=excluded.status,
                        ttl_hours=excluded.ttl_hours,
                        updated_at=excluded.updated_at,
                        last_seen_at=excluded.last_seen_at,
                        expires_at=excluded.expires_at,
                        occurrence_count=excluded.occurrence_count,
                        last_reversible_from_state=excluded.last_reversible_from_state,
                        resolution_json=excluded.resolution_json,
                        schedule_notified_at=excluded.schedule_notified_at
                    """,
                    {
                        "proposal_id": item["proposal_id"],
                        "dedup_key": item["dedup_key"],
                        "source": item["source"],
                        "source_label": item["source_label"],
                        "action_type": item["action_type"],
                        "risk": item["risk"],
                        "risk_label": item["risk_label"],
                        "irreversible": 1 if item.get("irreversible") else 0,
                        "title": item["title"],
                        "summary": item.get("summary") or "",
                        "why": item.get("why") or "",
                        "skip_reason": item.get("skip_reason") or "",
                        "impact_scope": item.get("impact_scope") or "",
                        "evidence": item.get("evidence") or "",
                        "options_json": json.dumps(item.get("options") or [], ensure_ascii=False),
                        "recommended": item.get("recommended"),
                        "selected_opt": item.get("selected_opt"),
                        "draft": item.get("draft"),
                        "suggestion": item.get("suggestion"),
                        "session_id": item.get("session_id"),
                        "schedule_id": item.get("schedule_id"),
                        "schedule_name": item.get("schedule_name"),
                        "employee_id": item.get("employee_id"),
                        "employee_name": item.get("employee_name"),
                        "employee_color": item.get("employee_color"),
                        "status": item["status"],
                        "ttl_hours": float(item.get("ttl_hours", 72.0)),
                        "created_at": float(item["created_at"]),
                        "updated_at": float(item["updated_at"]),
                        "last_seen_at": float(item["last_seen_at"]),
                        "expires_at": float(item["expires_at"]),
                        "occurrence_count": int(item.get("occurrence_count", 1)),
                        "last_reversible_from_state": item.get("last_reversible_from_state"),
                        "resolution_json": (
                            json.dumps(item["resolution"], ensure_ascii=False)
                            if item.get("resolution") is not None
                            else None
                        ),
                        "schedule_notified_at": item.get("schedule_notified_at"),
                    },
                )
                conn.commit()
            finally:
                conn.close()

        self.append_event(
            {
                "event_type": event_type,
                "proposal_id": item["proposal_id"],
                "dedup_key": item["dedup_key"],
                "status": item["status"],
                **(event_detail or {}),
            }
        )
        saved = self.get(item["proposal_id"])
        assert saved is not None
        return saved

    def mark_schedule_notified(self, proposal_ids: list[str], notified_at: float) -> None:
        if not proposal_ids:
            return
        with self._lock:
            conn = self._connect_existing()
            if conn is None:
                return
            try:
                placeholders = ",".join("?" for _ in proposal_ids)
                conn.execute(
                    f"UPDATE proposals SET schedule_notified_at = ? WHERE proposal_id IN ({placeholders})",
                    [notified_at, *proposal_ids],
                )
                conn.commit()
            finally:
                conn.close()
