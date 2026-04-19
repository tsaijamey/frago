"""Thread organization service.

Thread = forest of timeline entries organized by shared thread_id.
ThreadStore maintains the index (metadata) for each thread; the full entry
content lives in trace.jsonl files.

Index storage: ~/.frago/threads/index.jsonl (append-only, latest-wins dedup on load).

See spec 20260418-thread-organization for the design rationale.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

THREADS_DIR = Path.home() / ".frago" / "threads"
INDEX_FILE = THREADS_DIR / "index.jsonl"

STATUS_ACTIVE = "active"
STATUS_IDLE = "idle"
STATUS_ARCHIVED = "archived"
VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_IDLE, STATUS_ARCHIVED})


@dataclass
class ThreadIndex:
    """Lightweight index entry for a thread.

    thread_id == root timeline entry id (ulid).
    """

    thread_id: str
    origin: str          # "external" | "internal"
    subkind: str         # channel name or trigger type
    created_at: str
    last_active_ts: str
    status: str = STATUS_ACTIVE
    root_summary: str = ""
    tags: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    run_instance_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ThreadIndex:
        """Forgiving deserialization: drop unknown keys, fill defaults."""
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


class ThreadStore:
    """In-memory index of all threads, backed by append-only JSONL file."""

    def __init__(self, index_file: Path | None = None) -> None:
        self._index_file = index_file or INDEX_FILE
        self._by_id: dict[str, ThreadIndex] = {}
        self._lock = threading.RLock()
        self._load()

    # ---- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self._index_file.exists():
            return
        try:
            with open(self._index_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("skipping malformed thread index line: %r", line[:80])
                        continue
                    try:
                        idx = ThreadIndex.from_dict(d)
                    except (TypeError, KeyError):
                        logger.warning("skipping unrecognized thread index entry: %r", d)
                        continue
                    # Latest write wins per thread_id
                    self._by_id[idx.thread_id] = idx
        except OSError as e:
            logger.warning("failed to read thread index %s: %s", self._index_file, e)

    def _persist(self, idx: ThreadIndex) -> None:
        try:
            self._index_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._index_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(idx.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("failed to persist thread index %s: %s", idx.thread_id, e)

    # ---- reads -------------------------------------------------------------

    def get(self, thread_id: str) -> ThreadIndex | None:
        with self._lock:
            return self._by_id.get(thread_id)

    def get_all(self) -> list[ThreadIndex]:
        with self._lock:
            return list(self._by_id.values())

    def count(self) -> int:
        with self._lock:
            return len(self._by_id)

    def search(
        self,
        query: str | None = None,
        *,
        status: str | None = None,
        origin: str | None = None,
        subkind: str | None = None,
        task_id: str | None = None,
        required_tags: list[str] | None = None,
    ) -> list[ThreadIndex]:
        """Filter threads by criteria. Returns sorted by last_active_ts desc.

        `query` is a substring match (case-insensitive) against thread_id,
        root_summary, and tags. `required_tags` requires exact membership of
        all listed tags (used for structured refs like channelref:*).
        """
        results: list[ThreadIndex] = []
        ql = query.lower() if query else None
        with self._lock:
            for idx in self._by_id.values():
                if status and idx.status != status:
                    continue
                if origin and idx.origin != origin:
                    continue
                if subkind and idx.subkind != subkind:
                    continue
                if task_id and task_id not in idx.task_ids:
                    continue
                if required_tags and not all(t in idx.tags for t in required_tags):
                    continue
                if ql:
                    in_summary = ql in idx.root_summary.lower()
                    in_tags = any(ql in t.lower() for t in idx.tags)
                    in_id = ql in idx.thread_id.lower()
                    if not (in_summary or in_tags or in_id):
                        continue
                results.append(idx)
        results.sort(key=lambda x: x.last_active_ts, reverse=True)
        return results

    # ---- mutations ---------------------------------------------------------

    def create(
        self,
        thread_id: str,
        *,
        origin: str,
        subkind: str,
        root_summary: str = "",
        tags: list[str] | None = None,
        task_ids: list[str] | None = None,
        created_at: str | None = None,
    ) -> ThreadIndex:
        """Idempotent create. If thread_id exists, returns existing without modification."""
        with self._lock:
            existing = self._by_id.get(thread_id)
            if existing is not None:
                return existing
            ts = created_at or datetime.now().isoformat()
            idx = ThreadIndex(
                thread_id=thread_id,
                origin=origin,
                subkind=subkind,
                created_at=ts,
                last_active_ts=ts,
                status=STATUS_ACTIVE,
                root_summary=root_summary,
                tags=list(tags or []),
                task_ids=list(task_ids or []),
                run_instance_id=None,
            )
            self._by_id[thread_id] = idx
            self._persist(idx)
            return idx

    def touch(self, thread_id: str, ts: str | None = None) -> ThreadIndex | None:
        """Update last_active_ts and revive idle thread. No-op if ts is older."""
        with self._lock:
            idx = self._by_id.get(thread_id)
            if idx is None:
                return None
            new_ts = ts or datetime.now().isoformat()
            # Idempotence: only advance
            if new_ts <= idx.last_active_ts and idx.status == STATUS_ACTIVE:
                return idx
            changed = False
            if new_ts > idx.last_active_ts:
                idx.last_active_ts = new_ts
                changed = True
            if idx.status == STATUS_IDLE:
                idx.status = STATUS_ACTIVE
                changed = True
            if changed:
                self._persist(idx)
            return idx

    def bind_run(self, thread_id: str, run_instance_id: str) -> ThreadIndex | None:
        """Attach a run_instance to this thread. Idempotent."""
        with self._lock:
            idx = self._by_id.get(thread_id)
            if idx is None:
                return None
            if idx.run_instance_id == run_instance_id:
                return idx
            idx.run_instance_id = run_instance_id
            self._persist(idx)
            return idx

    def set_status(self, thread_id: str, status: str) -> ThreadIndex | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; expected one of {sorted(VALID_STATUSES)}")
        with self._lock:
            idx = self._by_id.get(thread_id)
            if idx is None:
                return None
            if idx.status == status:
                return idx
            idx.status = status
            self._persist(idx)
            return idx

    def add_task(self, thread_id: str, task_id: str) -> ThreadIndex | None:
        with self._lock:
            idx = self._by_id.get(thread_id)
            if idx is None:
                return None
            if task_id in idx.task_ids:
                return idx
            idx.task_ids.append(task_id)
            self._persist(idx)
            return idx

    def add_tag(self, thread_id: str, tag: str) -> ThreadIndex | None:
        with self._lock:
            idx = self._by_id.get(thread_id)
            if idx is None:
                return None
            if tag in idx.tags:
                return idx
            idx.tags.append(tag)
            self._persist(idx)
            return idx

    def set_summary(self, thread_id: str, summary: str) -> ThreadIndex | None:
        with self._lock:
            idx = self._by_id.get(thread_id)
            if idx is None:
                return None
            if idx.root_summary == summary:
                return idx
            idx.root_summary = summary
            self._persist(idx)
            return idx


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_thread_store: ThreadStore | None = None
_singleton_lock = threading.Lock()


def get_thread_store() -> ThreadStore:
    """Return the process-wide ThreadStore singleton."""
    global _thread_store
    if _thread_store is None:
        with _singleton_lock:
            if _thread_store is None:
                _thread_store = ThreadStore()
    return _thread_store


def _reset_for_tests(index_file: Path | None = None) -> ThreadStore:
    """Test hook: reset singleton with optional custom index file."""
    global _thread_store
    with _singleton_lock:
        _thread_store = ThreadStore(index_file=index_file)
    return _thread_store
