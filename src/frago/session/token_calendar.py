"""Per-day token usage aggregation for the Claude sessions calendar.

Walks ``~/.claude/projects/**/*.jsonl`` and sums assistant ``usage`` tokens
into per-day buckets. Each assistant record is attributed to the LOCAL date of
its own ``timestamp`` — a session file spanning midnight contributes to both
days (never attributed wholesale by file mtime).

Duplicate usage guard: one API response may be split across several assistant
records (one per content block), each repeating the same ``usage``. Records
are de-duplicated by ``message.id``, falling back to ``requestId``, then the
record ``uuid``.

Results are cached per file in ``~/.frago/cache/token_calendar.json`` keyed by
(mtime, size): a finished session's file never changes, so past days are never
re-parsed. ``projects_root`` / ``cache_path`` are injectable for tests.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR

CACHE_VERSION = 1

DEFAULT_CACHE_PATH = Path.home() / ".frago" / "cache" / "token_calendar.json"

_USAGE_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_creation": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}


def _empty_day() -> dict[str, int]:
    return {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0, "total": 0}


def _parse_file_days(path: Path) -> dict[str, dict[str, int]]:
    """Aggregate one jsonl into {local YYYY-MM-DD: token buckets}."""
    days: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if record.get("type") != "assistant":
                    continue
                message = record.get("message") or {}
                usage = message.get("usage") or {}
                if not usage:
                    continue
                ts = record.get("timestamp")
                if not ts:
                    continue
                try:
                    moment = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    continue
                # De-dup: one API response can appear as several records.
                dedup_key = message.get("id") or record.get("requestId") or record.get("uuid")
                if dedup_key:
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                day = moment.astimezone().strftime("%Y-%m-%d")
                bucket = days.setdefault(day, _empty_day())
                for field, usage_key in _USAGE_KEYS.items():
                    value = usage.get(usage_key)
                    if isinstance(value, (int, float)):
                        bucket[field] += int(value)
                bucket["total"] = (
                    bucket["input"]
                    + bucket["output"]
                    + bucket["cache_creation"]
                    + bucket["cache_read"]
                )
    except OSError:
        return {}
    return days


def _load_cache(cache_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"version": CACHE_VERSION, "files": {}}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "files": {}}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    return data


def _save_cache(cache_path: Path, cache: dict[str, Any]) -> None:
    """Atomic write: tmp file in the same dir, then rename."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_name(cache_path.name + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cache_path)


def compute_calendar(
    projects_root: Path | None = None,
    cache_path: Path | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, dict[str, int]]:
    """Return {YYYY-MM-DD: {input,output,cache_creation,cache_read,total}} over all files.

    ``progress_cb(done, total)`` fires after each file (cache hits included, so
    the progress bar advances truthfully).
    """
    root = projects_root or CLAUDE_PROJECTS_DIR
    cpath = cache_path or DEFAULT_CACHE_PATH
    cache = _load_cache(cpath)
    files_cache: dict[str, Any] = cache["files"]

    jsonl_files: list[Path] = []
    if root.exists():
        for proj_dir in sorted(root.iterdir()):
            if proj_dir.is_dir():
                jsonl_files.extend(sorted(proj_dir.glob("*.jsonl")))

    total = len(jsonl_files)
    done = 0
    alive_keys: set[str] = set()
    daily: dict[str, dict[str, int]] = {}

    for path in jsonl_files:
        key = str(path)
        alive_keys.add(key)
        try:
            st = path.stat()
        except OSError:
            files_cache.pop(key, None)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            continue
        entry = files_cache.get(key)
        if (
            not isinstance(entry, dict)
            or entry.get("mtime") != st.st_mtime
            or entry.get("size") != st.st_size
        ):
            entry = {
                "mtime": st.st_mtime,
                "size": st.st_size,
                "days": _parse_file_days(path),
            }
            files_cache[key] = entry
        for day, bucket in entry["days"].items():
            agg = daily.setdefault(day, _empty_day())
            for field in agg:
                agg[field] += int(bucket.get(field, 0))
        done += 1
        if progress_cb:
            progress_cb(done, total)

    # Drop cache entries for files no longer on disk.
    for key in list(files_cache):
        if key not in alive_keys:
            del files_cache[key]

    _save_cache(cpath, cache)
    return daily
