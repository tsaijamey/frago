"""任务区间实质报告提取、受管只读报告落盘与 14 天自动清理、以及跨内核无损分页读取。

设计目标（Top-4 ``20260826-worker-report-tails-only-full`` · 方案 4A）：
1. 统一经 :mod:`frago.session.record_reader` 提取当次任务区间内的全部实质 ``agent.say``
   正文，覆盖多轮工具调用穿插场景，五内核（``claude-code`` / ``codex`` / ``opencode`` /
   ``agy`` / ``coreagent``）口径完全一致。
2. 当任务区间输出超长（默认超过 ``600`` 字符）或包含多段实质输出时，自动原子写入
   ``~/.frago/dispatches/reports/``（受 ``FRAGO_HOME`` 约束），目录权限 ``0o700``、
   文件只读权限 ``0o444``，并在落盘时自动清理超过 ``14`` 天的过期报告文件。
3. 为 ``frago session read <sid>`` 提供跨 5 内核自动识别、前缀匹配与原样无损分页读取能力，
   不作 200 字符截断、不依赖大模型摘要。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.employee.store import frago_home
from frago.session import record_reader
from frago.session.unified_record import UnifiedRecord

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_REPORT_OFFLOAD_CHARS",
    "DEFAULT_REPORT_SUMMARY_HEAD_CHARS",
    "DEFAULT_REPORT_TTL_DAYS",
    "MAX_READ_PAGE_LIMIT",
    "MAX_TRANSCRIPT_SCAN_RECORDS",
    "SessionReadAmbiguous",
    "SessionReadError",
    "SessionReadItem",
    "SessionReadNotFound",
    "SessionReadPage",
    "TaskIntervalReport",
    "build_summary_text",
    "cleanup_expired_reports",
    "current_next_seq",
    "extract_latest_substantive_assistant_output",
    "extract_task_interval_report",
    "read_all_records",
    "read_session_messages",
    "reports_dir",
    "resolve_session_id",
    "write_managed_report",
]

DEFAULT_REPORT_OFFLOAD_CHARS = 600
DEFAULT_REPORT_SUMMARY_HEAD_CHARS = 420
DEFAULT_REPORT_TTL_DAYS = 14
MAX_TRANSCRIPT_SCAN_RECORDS = 20000
MAX_READ_PAGE_LIMIT = 500

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class SessionReadError(Exception):
    """Base error for deterministic session transcript reading."""


class SessionReadNotFound(SessionReadError):
    """Target session could not be located in any kernel store."""

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__(f"Session not found: {query}")


class SessionReadAmbiguous(SessionReadError):
    """Prefix matched more than one session across kernel stores."""

    def __init__(self, query: str, candidates: list[str]) -> None:
        self.query = query
        self.candidates = candidates
        super().__init__(
            f"Session prefix {query!r} matched {len(candidates)} sessions: "
            + ", ".join(candidates[:5])
        )


@dataclasses.dataclass(frozen=True)
class TaskIntervalReport:
    """Extraction and optional offload outcome for one task interval."""

    session_id: str
    family: str | None
    full_text: str
    summary_text: str
    total_chars: int
    block_count: int
    truncated: bool
    offloaded: bool
    report_file: str | None = None
    final_segment_text: str = ""


@dataclasses.dataclass(frozen=True)
class SessionReadItem:
    """Single lossless message/event entry returned by ``frago session read``."""

    index: int
    seq: int
    kind: str
    role: str
    ts: int
    text: str
    chars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "seq": self.seq,
            "kind": self.kind,
            "role": self.role,
            "ts": self.ts,
            "text": self.text,
            "chars": self.chars,
        }


@dataclasses.dataclass(frozen=True)
class SessionReadPage:
    """Paginated lossless read result across any of the 5 kernels."""

    session_id: str
    family: str
    role: str
    latest_turn: bool
    offset: int
    limit: int
    total_items: int
    returned: int
    has_more: bool
    next_offset: int | None
    total_chars: int
    items: list[SessionReadItem]
    char_offset: int = 0
    max_chars: int | None = None
    has_more_chars: bool = False
    next_char_offset: int | None = None
    sliced_text: str | None = None

    @property
    def text(self) -> str:
        """Full lossless text for this page (or sliced window when ``max_chars`` is set)."""
        if self.sliced_text is not None:
            return self.sliced_text
        return "\n\n".join(item.text for item in self.items)

    @property
    def char_has_more(self) -> bool:
        """Alias for ``has_more_chars``."""
        return self.has_more_chars

    def next_command(self, *, json_output: bool = False) -> str | None:
        parts: list[str]
        if self.max_chars is not None and self.has_more_chars and self.next_char_offset is not None:
            parts = [
                "frago",
                "session",
                "read",
                self.session_id,
                "--offset",
                str(self.offset),
                "--limit",
                str(self.limit),
                "--char-offset",
                str(self.next_char_offset),
                "--max-chars",
                str(self.max_chars),
                "--role",
                self.role,
            ]
        elif self.has_more and self.next_offset is not None:
            parts = [
                "frago",
                "session",
                "read",
                self.session_id,
                "--offset",
                str(self.next_offset),
                "--limit",
                str(self.limit),
                "--role",
                self.role,
            ]
        else:
            return None

        if self.latest_turn:
            parts.append("--latest-turn")
        if json_output:
            parts.append("--json")
        return " ".join(parts)

    def to_dict(self, *, json_output: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "family": self.family,
            "role": self.role,
            "latest_turn": self.latest_turn,
            "offset": self.offset,
            "limit": self.limit,
            "total_items": self.total_items,
            "returned": self.returned,
            "has_more": self.has_more,
            "next_offset": self.next_offset,
            "total_chars": self.total_chars,
            "text": self.text,
            "items": [item.to_dict() for item in self.items],
            "next_command": self.next_command(json_output=json_output),
        }
        if self.max_chars is not None:
            payload.update(
                {
                    "char_offset": self.char_offset,
                    "max_chars": self.max_chars,
                    "has_more_chars": self.has_more_chars,
                    "char_has_more": self.has_more_chars,
                    "next_char_offset": self.next_char_offset,
                    "text": self.sliced_text or "",
                }
            )
        return payload


def reports_dir(base_home: Path | None = None) -> Path:
    """Return managed report directory ``<frago_home>/dispatches/reports`` with ``0o700``."""
    root = base_home if base_home is not None else frago_home()
    dispatches = root / "dispatches"
    target = dispatches / "reports"
    dispatches.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(dispatches, 0o700)
    target.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(target, 0o700)
    return target


def cleanup_expired_reports(
    ttl_days: int = DEFAULT_REPORT_TTL_DAYS,
    *,
    base_home: Path | None = None,
    now_s: float | None = None,
) -> int:
    """Delete managed report files older than ``ttl_days`` (default 14 days).

    Fault-tolerant for zero-prior-setup machines: missing directories or locked
    individual files never raise.
    """
    if ttl_days < 0:
        return 0
    root = base_home if base_home is not None else frago_home()
    target = root / "dispatches" / "reports"
    if not target.is_dir():
        return 0

    cutoff = (now_s if now_s is not None else time.time()) - float(ttl_days) * 86400.0
    removed = 0
    try:
        entries = list(target.iterdir())
    except OSError:
        return 0

    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.name.startswith("."):
                # Ignore in-flight temp files unless also expired
                if entry.stat().st_mtime >= cutoff:
                    continue
            elif entry.stat().st_mtime >= cutoff:
                continue
            # Ensure writable on platforms where read-only blocks unlink
            with contextlib.suppress(OSError):
                os.chmod(entry, 0o600)
            entry.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _safe_filename_part(value: str | None, fallback: str, max_len: int = 40) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", str(value or "").strip()).strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len]


def write_managed_report(
    content: str,
    *,
    session_id: str,
    job_id: str | None = None,
    ttl_days: int = DEFAULT_REPORT_TTL_DAYS,
    base_home: Path | None = None,
) -> Path:
    """Atomically write a read-only (``0o444``) managed report and clean expired ones."""
    with contextlib.suppress(Exception):
        cleanup_expired_reports(ttl_days=ttl_days, base_home=base_home)

    target_dir = reports_dir(base_home=base_home)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sid_part = _safe_filename_part(session_id, "session", max_len=36)
    prefix = f"{_safe_filename_part(job_id, 'job', max_len=24)}-" if job_id else ""
    rand_part = uuid.uuid4().hex[:8]
    final_path = target_dir / f"{prefix}{sid_part}-{stamp}-{rand_part}.md"

    text = content if (not content or content.endswith("\n")) else f"{content}\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_dir,
            prefix=".tmp-report-",
            suffix=".md",
            delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
            fh.write(text)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o444)
        os.replace(tmp_path, final_path)
        tmp_path = None
        return final_path
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def read_all_records(
    session_id: str,
    *,
    after: int = 0,
    max_records: int = MAX_TRANSCRIPT_SCAN_RECORDS,
) -> list[UnifiedRecord]:
    """Read all unified records for ``session_id`` from ``after`` via paginated ``record_reader``."""
    out: list[UnifiedRecord] = []
    cur_after = max(int(after), 0)
    limit = record_reader.MAX_LIMIT
    while len(out) < max_records:
        batch = record_reader.read_records(session_id, after=cur_after, limit=limit)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < limit:
            break
        next_after = int(batch[-1].seq) + 1
        if next_after <= cur_after:
            break
        cur_after = next_after
    return out[:max_records]


def current_next_seq(session_id: str | None) -> int | None:
    """Capture the pre-turn transcript ``seq`` boundary for a session before executing a turn."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    try:
        tail_records = record_reader.read_records(sid, tail=True, limit=1)
    except record_reader.UnknownSessionFamily:
        return None
    except Exception:
        return None
    if not tail_records:
        return 0
    return max(0, int(tail_records[-1].seq) + 1)


def build_summary_text(
    full_text: str,
    *,
    threshold: int = DEFAULT_REPORT_OFFLOAD_CHARS,
    head_chars: int = DEFAULT_REPORT_SUMMARY_HEAD_CHARS,
) -> tuple[str, bool]:
    """Return ``(summary_text, truncated)``, closing dangling markdown code fences."""
    if len(full_text) <= threshold:
        return full_text, False
    head = full_text[:head_chars].rstrip()
    if head.count("```") % 2 == 1:
        head = f"{head}\n```"
    return head, True


def _is_substantive_assistant_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return not stripped.startswith("[dispatched]")


def _collect_interval_blocks(
    records: list[UnifiedRecord],
    *,
    baseline_seq: int | None,
) -> list[str]:
    if baseline_seq is not None:
        scoped = [r for r in records if int(r.seq) >= baseline_seq]
    else:
        last_user_idx = max(
            (idx for idx, rec in enumerate(records) if rec.kind == "user.say"),
            default=-1,
        )
        scoped = records[last_user_idx + 1 :] if last_user_idx >= 0 else records

    blocks: list[str] = []
    for rec in scoped:
        if rec.kind != "agent.say":
            continue
        payload = rec.payload if isinstance(rec.payload, dict) else {}
        text = str(payload.get("text") or "").strip()
        if not _is_substantive_assistant_text(text):
            continue
        if blocks and blocks[-1] == text:
            continue
        blocks.append(text)
    return blocks


def extract_task_interval_report(
    session_id: str | None,
    *,
    baseline_seq: int | None = None,
    fallback_text: str = "",
    threshold: int = DEFAULT_REPORT_OFFLOAD_CHARS,
    head_chars: int = DEFAULT_REPORT_SUMMARY_HEAD_CHARS,
    offload: bool = True,
    job_id: str | None = None,
    ttl_days: int = DEFAULT_REPORT_TTL_DAYS,
    base_home: Path | None = None,
) -> TaskIntervalReport:
    """Extract all substantive assistant text in the current task interval across all 5 kernels.

    If ``baseline_seq`` is given, reads from ``seq >= baseline_seq``; otherwise scopes to
    records after the last ``user.say``. Multi-turn tool-call loops with multiple
    ``agent.say`` emissions are preserved in full rather than clipped to ``final_text``.
    """
    sid = str(session_id or "").strip()
    family: str | None = None
    records: list[UnifiedRecord] = []
    if sid:
        try:
            family = str(record_reader.detect_family(sid))
            start_after = max(0, baseline_seq) if baseline_seq is not None else 0
            records = read_all_records(sid, after=start_after)
        except Exception:
            records = []

    blocks = _collect_interval_blocks(records, baseline_seq=baseline_seq)
    clean_fallback = str(fallback_text or "").strip()

    if blocks:
        if clean_fallback and _is_substantive_assistant_text(clean_fallback):
            joined = "\n\n".join(blocks)
            if clean_fallback not in joined:
                if blocks[-1] in clean_fallback:
                    blocks[-1] = clean_fallback
                else:
                    blocks.append(clean_fallback)
        full_text = "\n\n".join(blocks)
        final_seg = blocks[-1]
    else:
        full_text = clean_fallback
        blocks = [clean_fallback] if clean_fallback else []
        final_seg = clean_fallback

    total_chars = len(full_text)
    block_count = len(blocks)
    summary_text, truncated = build_summary_text(
        full_text,
        threshold=threshold,
        head_chars=head_chars,
    )
    needs_offload = bool(full_text) and (total_chars > threshold or block_count > 1)
    report_file: str | None = None
    if offload and needs_offload:
        try:
            written = write_managed_report(
                full_text,
                session_id=sid or "session",
                job_id=job_id,
                ttl_days=ttl_days,
                base_home=base_home,
            )
            report_file = str(written)
        except Exception as exc:  # noqa: BLE001 — fault-tolerant offload
            logger.warning("Failed to offload managed report for %s: %s", sid, exc)

    return TaskIntervalReport(
        session_id=sid,
        family=family,
        full_text=full_text,
        summary_text=summary_text,
        total_chars=total_chars,
        block_count=block_count,
        truncated=truncated,
        offloaded=report_file is not None,
        report_file=report_file,
        final_segment_text=final_seg,
    )


def extract_latest_substantive_assistant_output(session_id: str) -> str | None:
    """Extract the latest substantive task-interval assistant text via ``record_reader``."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    try:
        records = read_all_records(sid, after=0)
    except Exception:
        return None
    blocks = _collect_interval_blocks(records, baseline_seq=None)
    if blocks:
        return "\n\n".join(blocks)
    # Fallback across entire history if latest turn had only [dispatched] or non-user records
    for rec in reversed(records):
        if rec.kind != "agent.say":
            continue
        payload = rec.payload if isinstance(rec.payload, dict) else {}
        text = str(payload.get("text") or "").strip()
        if _is_substantive_assistant_text(text):
            return text
    return None


def resolve_session_id(session_id_or_prefix: str) -> tuple[str, str]:
    """Resolve full session ID or unique prefix across all 5 kernel stores via ``record_reader``."""
    needle = str(session_id_or_prefix or "").strip()
    if not needle:
        raise SessionReadNotFound(needle)

    # 1) Fast exact lookup without scanning all 5 stores
    with contextlib.suppress(record_reader.UnknownSessionFamily):
        family = str(record_reader.detect_family(needle))
        try:
            head = record_reader.read_records(needle, after=0, limit=1)
        except Exception:
            head = []
        if head or record_reader.locate_session_file(needle) is not None:
            return needle, family

    # 2) Unified list scan for prefix matching (and opencode exact fallback)
    try:
        cards = record_reader.list_sessions()
    except Exception:
        cards = []

    exact = [c for c in cards if c.session_id == needle]
    if exact:
        return exact[0].session_id, str(exact[0].family)

    matched = [c for c in cards if c.session_id.startswith(needle)]
    if len(matched) == 1:
        return matched[0].session_id, str(matched[0].family)
    if len(matched) > 1:
        raise SessionReadAmbiguous(needle, [c.session_id for c in matched])

    # 3) Direct filesystem prefix probe for freshly-started/unindexed sessions
    #    (e.g. agy brain dirs before conversation_summaries.db flushes, or claude/coreagent JSONLs)
    fallback_hits: dict[str, str] = {}

    def _scan_jsonl_root(root: Path, family_name: str) -> None:
        if not root.is_dir():
            return
        with contextlib.suppress(OSError):
            for proj_dir in root.iterdir():
                if not proj_dir.is_dir():
                    continue
                for f in proj_dir.glob(f"{needle}*.jsonl"):
                    if f.name.startswith("agent-"):
                        continue
                    fallback_hits.setdefault(f.stem, family_name)

    _scan_jsonl_root(Path.home() / ".claude" / "projects", "claude-code")
    with contextlib.suppress(Exception):
        from frago.session import coreagent_store

        _scan_jsonl_root(coreagent_store.sessions_root(), "coreagent")
    with contextlib.suppress(Exception):
        from frago.session import agy_store

        if agy_store.is_agy_present():
            b_root = agy_store.brain_root()
            if b_root.is_dir():
                for child in b_root.iterdir():
                    if (
                        child.is_dir()
                        and child.name.startswith(needle)
                        and agy_store.find_session_file(child.name) is not None
                    ):
                        fallback_hits.setdefault(child.name, "agy")

    if len(fallback_hits) == 1:
        sid, fam = next(iter(fallback_hits.items()))
        return sid, fam
    if len(fallback_hits) > 1:
        raise SessionReadAmbiguous(needle, sorted(fallback_hits))

    raise SessionReadNotFound(needle)


def _record_role_and_text(rec: UnifiedRecord) -> tuple[str, str]:
    payload = rec.payload if isinstance(rec.payload, dict) else {}
    if rec.kind == "user.say":
        return "user", str(payload.get("text") or "")
    if rec.kind == "agent.say":
        return "assistant", str(payload.get("text") or "")
    if rec.kind == "agent.think":
        return "thinking", str(payload.get("text") or "")
    if rec.kind in ("tool.call", "subagent.dispatch"):
        tool_name = str(payload.get("tool_name") or payload.get("tool") or payload.get("name") or rec.kind)
        args = payload.get("args") if "args" in payload else payload
        return "tool_call", f"[{tool_name}] {json.dumps(args, ensure_ascii=False)}"
    if rec.kind == "tool.result":
        return "tool_result", str(
            payload.get("output") or payload.get("text") or json.dumps(payload, ensure_ascii=False)
        )
    text = str(payload.get("text") or payload.get("message") or payload.get("reason") or "").strip()
    if not text:
        text = json.dumps(payload, ensure_ascii=False)
    return str(rec.kind), text


def read_session_messages(
    session_id_or_prefix: str,
    *,
    offset: int = 0,
    limit: int = 20,
    tail: bool = False,
    role: str = "assistant",
    latest_turn: bool = False,
    char_offset: int = 0,
    max_chars: int | None = None,
) -> SessionReadPage:
    """Losslessly read and paginate session records across all 5 kernels via ``record_reader``."""
    resolved_sid, family = resolve_session_id(session_id_or_prefix)
    records = read_all_records(resolved_sid, after=0)

    if latest_turn:
        last_user_idx = max(
            (idx for idx, rec in enumerate(records) if rec.kind == "user.say"),
            default=-1,
        )
        if last_user_idx >= 0:
            records = records[last_user_idx:]

    norm_role = (role or "assistant").strip().lower()
    if norm_role == "assistant":
        allowed_kinds: set[str] | None = {"agent.say"}
    elif norm_role == "user":
        allowed_kinds = {"user.say"}
    elif norm_role in ("conversation", "chat"):
        allowed_kinds = {"user.say", "agent.say"}
    else:
        norm_role = "all"
        allowed_kinds = None

    filtered_items: list[SessionReadItem] = []
    for rec in records:
        if allowed_kinds is not None and rec.kind not in allowed_kinds:
            continue
        item_role, item_text = _record_role_and_text(rec)
        if not item_text and rec.kind in ("agent.say", "user.say"):
            continue
        filtered_items.append(
            SessionReadItem(
                index=len(filtered_items),
                seq=int(rec.seq),
                kind=str(rec.kind),
                role=item_role,
                ts=int(rec.ts or 0),
                text=item_text,
                chars=len(item_text),
            )
        )

    total_items = len(filtered_items)
    total_chars = sum(item.chars for item in filtered_items)
    eff_limit = min(max(int(limit), 1), MAX_READ_PAGE_LIMIT)
    eff_offset = max(0, total_items - eff_limit) if tail else max(0, int(offset))

    page_items = filtered_items[eff_offset : eff_offset + eff_limit]
    returned = len(page_items)
    has_more = (eff_offset + returned) < total_items
    next_offset = (eff_offset + returned) if has_more else None

    eff_char_offset = max(0, int(char_offset))
    eff_max_chars = int(max_chars) if max_chars is not None and int(max_chars) > 0 else None
    has_more_chars = False
    next_char_offset: int | None = None
    sliced_text: str | None = None
    if eff_max_chars is not None:
        combined = "\n\n".join(item.text for item in page_items)
        sliced_text = combined[eff_char_offset : eff_char_offset + eff_max_chars]
        if eff_char_offset + len(sliced_text) < len(combined):
            has_more_chars = True
            next_char_offset = eff_char_offset + len(sliced_text)

    return SessionReadPage(
        session_id=resolved_sid,
        family=family,
        role=norm_role,
        latest_turn=bool(latest_turn),
        offset=eff_offset,
        limit=eff_limit,
        total_items=total_items,
        returned=returned,
        has_more=has_more,
        next_offset=next_offset,
        total_chars=total_chars,
        items=page_items,
        char_offset=eff_char_offset,
        max_chars=eff_max_chars,
        has_more_chars=has_more_chars,
        next_char_offset=next_char_offset,
        sliced_text=sliced_text,
    )
