"""Domain-level insight CRUD (Phase 2 of run-as-domain-knowledge-base).

A *domain insight* is a piece of knowledge attached to a domain (the new run
instance). Insights live in ``~/.frago/projects/{domain}/insight.jsonl`` as an
append-only JSONL log. Updates are modelled as new versions of an existing
insight ``id``: readers collapse by id and surface the latest version only.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .exceptions import FileSystemError, RunNotFoundError
from .utils import ensure_directory_exists, normalize_domain_name

INSIGHT_FILENAME = "insight.jsonl"


class DomainInsightType(str, Enum):
    """Domain insight type (Phase 2 schema)."""

    FACT = "fact"
    DECISION = "decision"
    FORESHADOW = "foreshadow"
    STATE = "state"
    LESSON = "lesson"


VALID_TYPES = {t.value for t in DomainInsightType}


class DomainInsight(BaseModel):
    """A single domain-level insight entry."""

    id: str = Field(..., min_length=1)
    type: DomainInsightType
    payload: str = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    related_session_ids: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    version: int = Field(default=1, ge=1)
    superseded: bool = Field(default=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "payload": self.payload,
            "confidence": self.confidence,
            "related_session_ids": list(self.related_session_ids),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "superseded": self.superseded,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainInsight":
        d = dict(data)
        if isinstance(d.get("type"), str):
            d["type"] = DomainInsightType(d["type"])
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(
                d["created_at"].replace("Z", "+00:00")
            )
        if isinstance(d.get("updated_at"), str):
            d["updated_at"] = datetime.fromisoformat(
                d["updated_at"].replace("Z", "+00:00")
            )
        return cls(**d)


def _generate_id() -> str:
    """Generate a sortable, unique insight id (time-prefixed)."""
    millis = int(time.time() * 1000)
    return f"{millis:013x}-{uuid.uuid4().hex[:8]}"


def _domain_dir(projects_dir: Path, domain: str) -> Path:
    normalized = normalize_domain_name(domain)
    if not normalized:
        raise ValueError("domain cannot be empty")
    return projects_dir / normalized


def _insight_file(projects_dir: Path, domain: str) -> Path:
    return _domain_dir(projects_dir, domain) / INSIGHT_FILENAME


def _read_all_raw(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines silently — corruption is rare and
                    # we don't want to brick the whole domain on one bad row.
                    continue
    except OSError as e:
        raise FileSystemError("read", str(path), str(e)) from e
    return out


def _collapse_to_latest(rows: List[Dict[str, Any]]) -> List[DomainInsight]:
    """Group rows by id and keep only the latest version per id."""
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        rid = row.get("id")
        if not rid:
            continue
        existing = latest.get(rid)
        if existing is None or row.get("version", 1) >= existing.get("version", 1):
            latest[rid] = row
    insights: List[DomainInsight] = []
    for row in latest.values():
        try:
            insights.append(DomainInsight.from_dict(row))
        except Exception:
            continue
    return insights


def _append_row(path: Path, row: Dict[str, Any]) -> None:
    ensure_directory_exists(path.parent)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    except OSError as e:
        raise FileSystemError("write", str(path), str(e)) from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_insight(
    projects_dir: Path,
    domain: str,
    *,
    type: str,
    payload: str,
    confidence: float = 0.5,
    related_session_ids: Optional[List[str]] = None,
) -> DomainInsight:
    """Append a new insight to ``{domain}/insight.jsonl``.

    The caller is responsible for ensuring the domain exists (typically via
    :func:`RunManager.ensure_domain` + :func:`RunManager.bump_insight_count`).
    """
    if type not in VALID_TYPES:
        raise ValueError(
            f"invalid insight type {type!r}; must be one of {sorted(VALID_TYPES)}"
        )
    if not payload or not payload.strip():
        raise ValueError("payload cannot be empty")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be between 0.0 and 1.0")

    now = datetime.now()
    insight = DomainInsight(
        id=_generate_id(),
        type=DomainInsightType(type),
        payload=payload,
        confidence=confidence,
        related_session_ids=related_session_ids or [],
        created_at=now,
        updated_at=now,
        version=1,
        superseded=False,
    )
    _append_row(_insight_file(projects_dir, domain), insight.to_dict())
    return insight


def list_insights(
    projects_dir: Path,
    domain: str,
    *,
    type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[DomainInsight]:
    """List insights for a domain (latest version per id, newest first)."""
    rows = _read_all_raw(_insight_file(projects_dir, domain))
    insights = _collapse_to_latest(rows)
    if type:
        if type not in VALID_TYPES:
            raise ValueError(f"invalid insight type {type!r}")
        insights = [i for i in insights if i.type.value == type]
    insights.sort(key=lambda i: i.updated_at, reverse=True)
    if limit and limit > 0:
        insights = insights[:limit]
    return insights


def query_insights(
    projects_dir: Path,
    domain: str,
    *,
    keyword: str,
    type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[DomainInsight]:
    """Substring-search insights' payloads for a keyword (case-insensitive)."""
    if not keyword:
        return list_insights(projects_dir, domain, type=type, limit=limit)
    needle = keyword.lower()
    matches: List[DomainInsight] = []
    for entry in list_insights(projects_dir, domain, type=type):
        if needle in entry.payload.lower():
            matches.append(entry)
    if limit and limit > 0:
        matches = matches[:limit]
    return matches


def find_insight(
    projects_dir: Path,
    domain: str,
    insight_id: str,
) -> Optional[DomainInsight]:
    for entry in list_insights(projects_dir, domain):
        if entry.id == insight_id:
            return entry
    return None


def update_insight(
    projects_dir: Path,
    domain: str,
    insight_id: str,
    *,
    payload: Optional[str] = None,
    confidence: Optional[float] = None,
    type: Optional[str] = None,
    related_session_ids: Optional[List[str]] = None,
) -> DomainInsight:
    """Append a new version of an existing insight.

    The previous version row is left in place (append-only); readers collapse
    by id and surface only the highest ``version``.
    """
    existing = find_insight(projects_dir, domain, insight_id)
    if existing is None:
        raise RunNotFoundError(f"insight {insight_id} (domain={domain})")

    new_payload = payload if payload is not None else existing.payload
    new_confidence = confidence if confidence is not None else existing.confidence
    new_type = DomainInsightType(type) if type is not None else existing.type
    new_related = (
        related_session_ids
        if related_session_ids is not None
        else list(existing.related_session_ids)
    )

    if type is not None and type not in VALID_TYPES:
        raise ValueError(f"invalid insight type {type!r}")
    if not new_payload or not new_payload.strip():
        raise ValueError("payload cannot be empty")
    if not (0.0 <= new_confidence <= 1.0):
        raise ValueError("confidence must be between 0.0 and 1.0")

    now = datetime.now()
    bumped = DomainInsight(
        id=existing.id,
        type=new_type,
        payload=new_payload,
        confidence=new_confidence,
        related_session_ids=new_related,
        created_at=existing.created_at,
        updated_at=now,
        version=existing.version + 1,
        superseded=False,
    )
    _append_row(_insight_file(projects_dir, domain), bumped.to_dict())
    return bumped


def search_insights_across_domains(
    projects_dir: Path,
    keyword: str,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Search insight payloads across every domain under ``projects_dir``."""
    if not projects_dir.exists():
        return []
    needle = keyword.lower() if keyword else ""
    hits: List[Dict[str, Any]] = []
    for domain_dir in projects_dir.iterdir():
        if not domain_dir.is_dir():
            continue
        if domain_dir.name.startswith("_"):
            continue
        path = domain_dir / INSIGHT_FILENAME
        if not path.exists():
            continue
        for entry in _collapse_to_latest(_read_all_raw(path)):
            if not needle or needle in entry.payload.lower():
                hits.append({
                    "domain": domain_dir.name,
                    "insight": entry.to_dict(),
                })
    hits.sort(key=lambda h: h["insight"]["updated_at"], reverse=True)
    if limit and limit > 0:
        hits = hits[:limit]
    return hits


def count_insights(projects_dir: Path, domain: str) -> int:
    """Count latest-version insights for a domain (cheap re-computation)."""
    return len(list_insights(projects_dir, domain))
