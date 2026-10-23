"""会话工作台用量月历的按日聚合。

汇总本机五种内核的会话用量，归入本地日期（``YYYY-MM-DD``）桶：

1. **Claude Code**：``~/.claude/projects/*/*.jsonl`` 里的 ``assistant.message.usage``
2. **CoreAgent**：``~/.frago/coreagent/sessions/*/*.jsonl`` 里的 ``assistant.message.usage``
3. **Antigravity (agy)**：``~/.gemini/antigravity-cli/brain/*/.system_generated/logs/transcript.jsonl``
   里的 ``PLANNER_RESPONSE`` 顶层 token 字段
4. **Codex**：``~/.codex/sessions/**/rollout-*.jsonl`` 里的 ``event_msg.token_count``
5. **OpenCode**：``~/.local/share/opencode/opencode.db`` 的 ``part`` 表 ``step-finish`` 片段

每条记录按**自身的时间戳**转为本地日期归日（跨午夜会话按单条记录切分，绝不按文件
``mtime`` 整场归属）。四个分项的换算全部复用 :mod:`frago.session.usage_tick`，保证
月历与单场会话记录流（``usage.tick``）报出的数字逐字一致。

结果按每个源文件（及 SQLite WAL）的 ``(mtime, size)`` 增量缓存在
``~/.frago/cache/token_calendar.json``，历史会话无需重复解析。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session import agy_store, codex_store, coreagent_store, opencode_store
from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.usage_tick import (
    CLAUDE_USAGE_KEYS,
    USAGE_FIELDS,
    breakdown_from_agy_record,
    breakdown_from_claude_usage,
    breakdown_from_codex_usage,
    breakdown_from_opencode_tokens,
)

CACHE_VERSION = 2

DEFAULT_CACHE_PATH = Path.home() / ".frago" / "cache" / "token_calendar.json"

_DEFAULT_CLAUDE_PROJECTS_DIR = CLAUDE_PROJECTS_DIR
COREAGENT_SESSIONS_DIR: Path | None = None
AGY_BRAIN_DIR: Path | None = None
CODEX_SESSIONS_DIR: Path | None = None
OPENCODE_DB_PATH: Path | None = None

# Shared with the per-session usage ticks shown in the workbench stream: the
# calendar and the stream must never disagree about what a token count means.
_USAGE_KEYS = CLAUDE_USAGE_KEYS


def _empty_day() -> dict[str, int]:
    return {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0, "total": 0}


def _iso_to_local_day(ts: Any) -> str | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone().strftime("%Y-%m-%d")


def _add_breakdown(
    days: dict[str, dict[str, int]], day: str, breakdown: dict[str, int]
) -> None:
    bucket = days.setdefault(day, _empty_day())
    for field in USAGE_FIELDS:
        bucket[field] += int(breakdown.get(field, 0))
    bucket["total"] = sum(bucket[field] for field in USAGE_FIELDS)


def _parse_file_days(path: Path) -> dict[str, dict[str, int]]:
    """Aggregate one Claude Code / CoreAgent jsonl into {local YYYY-MM-DD: token buckets}."""
    days: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(record, dict) or record.get("type") != "assistant":
                    continue
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict) or not usage:
                    continue
                day = _iso_to_local_day(record.get("timestamp"))
                if not day:
                    continue
                # De-dup: one API response can appear as several records.
                dedup_key = message.get("id") or record.get("requestId") or record.get("uuid")
                if dedup_key:
                    key_str = str(dedup_key)
                    if key_str in seen:
                        continue
                    seen.add(key_str)
                _add_breakdown(days, day, breakdown_from_claude_usage(usage))
    except OSError:
        return {}
    return days


def _parse_agy_file_days(path: Path) -> dict[str, dict[str, int]]:
    """Aggregate one Antigravity (agy) transcript.jsonl into {local YYYY-MM-DD: token buckets}."""
    days: dict[str, dict[str, int]] = {}
    seen_steps: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                breakdown = breakdown_from_agy_record(record)
                if breakdown is None:
                    continue
                day = _iso_to_local_day(record.get("created_at"))
                if not day:
                    continue
                step = record.get("step_index")
                if step is not None:
                    step_key = str(step)
                    if step_key in seen_steps:
                        continue
                    seen_steps.add(step_key)
                _add_breakdown(days, day, breakdown)
    except OSError:
        return {}
    return days


def _parse_codex_file_days(path: Path) -> dict[str, dict[str, int]]:
    """Aggregate one Codex rollout jsonl into {local YYYY-MM-DD: token buckets}."""
    days: dict[str, dict[str, int]] = {}
    last_total: Any = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(record, dict) or record.get("type") != "event_msg":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                last = info.get("last_token_usage")
                total = info.get("total_token_usage")
                if not isinstance(last, dict) or not isinstance(total, dict):
                    continue
                # De-dup repeated token_count events within the same turn where
                # cumulative total_tokens did not advance (matches codex_records).
                total_tokens = total.get("total_tokens")
                if total_tokens is not None and total_tokens == last_total:
                    continue
                last_total = total_tokens
                day = _iso_to_local_day(record.get("timestamp"))
                if not day:
                    continue
                _add_breakdown(days, day, breakdown_from_codex_usage(last))
    except OSError:
        return {}
    return days


def _parse_opencode_db_days(db_path: Path) -> dict[str, dict[str, int]]:
    """Aggregate OpenCode SQLite part table step-finish tokens into {local YYYY-MM-DD: token buckets}."""
    days: dict[str, dict[str, int]] = {}
    if not db_path.is_file():
        return days
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT time_created, data FROM part WHERE json_extract(data, '$.type') = 'step-finish'"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        if conn is not None:
            conn.close()

    for time_created, raw_data in rows:
        if not isinstance(time_created, int | float):
            continue
        if isinstance(raw_data, str):
            try:
                part = json.loads(raw_data)
            except (json.JSONDecodeError, ValueError):
                continue
        elif isinstance(raw_data, dict):
            part = raw_data
        else:
            continue
        if not isinstance(part, dict):
            continue
        tokens = part.get("tokens")
        if not isinstance(tokens, dict):
            continue
        breakdown = breakdown_from_opencode_tokens(tokens)
        if breakdown is None:
            continue
        try:
            day = datetime.fromtimestamp(float(time_created) / 1000.0).astimezone().strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            continue
        _add_breakdown(days, day, breakdown)
    return days


def _stat_signature(path: Path, *, include_wal: bool = False) -> tuple[float, int] | None:
    """Return (mtime, size) for cache invalidation; includes SQLite -wal when requested."""
    try:
        st = path.stat()
    except OSError:
        return None
    mtime = st.st_mtime
    size = st.st_size
    if include_wal:
        wal = Path(str(path) + "-wal")
        try:
            wal_st = wal.stat()
            mtime = max(mtime, wal_st.st_mtime)
            size += wal_st.st_size
        except OSError:
            pass
    return mtime, size


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


def _resolve_sources(
    projects_root: Path | None,
    coreagent_root: Path | None,
    agy_brain_root: Path | None,
    codex_root: Path | None,
    opencode_db_path: Path | None,
) -> tuple[Path | None, Path | None, Path | None, Path | None, Path | None]:
    """Resolve the five session stores.

    When any root is explicitly passed (or monkeypatched on the module), only
    the explicitly provided / monkeypatched stores are scanned so unit tests
    never leak into the real home directory. In production (no overrides), all
    five native stores are scanned.
    """
    explicit_arg = any(
        p is not None
        for p in (projects_root, coreagent_root, agy_brain_root, codex_root, opencode_db_path)
    )
    if explicit_arg:
        return (
            projects_root,
            coreagent_root,
            agy_brain_root,
            codex_root,
            opencode_db_path,
        )

    monkeypatched = (
        CLAUDE_PROJECTS_DIR != _DEFAULT_CLAUDE_PROJECTS_DIR
        or COREAGENT_SESSIONS_DIR is not None
        or AGY_BRAIN_DIR is not None
        or CODEX_SESSIONS_DIR is not None
        or OPENCODE_DB_PATH is not None
    )
    if monkeypatched:
        claude_dir = (
            CLAUDE_PROJECTS_DIR
            if CLAUDE_PROJECTS_DIR != _DEFAULT_CLAUDE_PROJECTS_DIR
            else None
        )
        return (
            claude_dir,
            COREAGENT_SESSIONS_DIR,
            AGY_BRAIN_DIR,
            CODEX_SESSIONS_DIR,
            OPENCODE_DB_PATH,
        )

    return (
        CLAUDE_PROJECTS_DIR,
        coreagent_store.sessions_root(),
        agy_store.brain_root(),
        codex_store.sessions_root(),
        opencode_store.db_path(),
    )


def _collect_targets(
    claude_root: Path | None,
    coreagent_root: Path | None,
    agy_root: Path | None,
    codex_root: Path | None,
    opencode_db: Path | None,
) -> list[tuple[Path, Callable[[Path], dict[str, dict[str, int]]], bool]]:
    """Return [(path, parser, include_wal)] across all configured stores."""
    targets: list[tuple[Path, Callable[[Path], dict[str, dict[str, int]]], bool]] = []

    for root in (claude_root, coreagent_root):
        if root is not None and root.is_dir():
            for proj_dir in sorted(root.iterdir()):
                if proj_dir.is_dir():
                    for path in sorted(proj_dir.glob("*.jsonl")):
                        targets.append((path, _parse_file_days, False))

    if agy_root is not None and agy_root.is_dir():
        for conv_dir in sorted(agy_root.iterdir()):
            if not conv_dir.is_dir():
                continue
            logs_dir = conv_dir / ".system_generated" / "logs"
            transcript = logs_dir / "transcript.jsonl"
            if not transcript.is_file():
                transcript = logs_dir / "transcript_full.jsonl"
            if transcript.is_file():
                targets.append((transcript, _parse_agy_file_days, False))

    if codex_root is not None and codex_root.is_dir():
        for path in sorted(codex_root.rglob("rollout-*.jsonl")):
            if path.is_file():
                targets.append((path, _parse_codex_file_days, False))

    if opencode_db is not None and opencode_db.is_file():
        targets.append((opencode_db, _parse_opencode_db_days, True))

    return targets


def compute_calendar(
    projects_root: Path | None = None,
    cache_path: Path | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    *,
    coreagent_root: Path | None = None,
    agy_brain_root: Path | None = None,
    codex_root: Path | None = None,
    opencode_db_path: Path | None = None,
) -> dict[str, dict[str, int]]:
    """Return {YYYY-MM-DD: {input,output,cache_creation,cache_read,total}} over all stores.

    ``progress_cb(done, total)`` fires after each source file (cache hits
    included, so the progress bar advances truthfully).
    """
    sources = _resolve_sources(
        projects_root, coreagent_root, agy_brain_root, codex_root, opencode_db_path
    )
    cpath = cache_path or DEFAULT_CACHE_PATH
    cache = _load_cache(cpath)
    files_cache: dict[str, Any] = cache["files"]

    targets = _collect_targets(*sources)
    total = len(targets)
    done = 0
    alive_keys: set[str] = set()
    daily: dict[str, dict[str, int]] = {}

    for path, parser, include_wal in targets:
        key = str(path)
        alive_keys.add(key)
        sig = _stat_signature(path, include_wal=include_wal)
        if sig is None:
            files_cache.pop(key, None)
            done += 1
            if progress_cb:
                progress_cb(done, total)
            continue
        mtime, size = sig
        entry = files_cache.get(key)
        if (
            not isinstance(entry, dict)
            or entry.get("mtime") != mtime
            or entry.get("size") != size
        ):
            entry = {
                "mtime": mtime,
                "size": size,
                "days": parser(path),
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
