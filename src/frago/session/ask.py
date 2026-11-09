"""单场历史会话的轻量模型单轮定向提取（``frago session ask``）。

## 解决什么问题

``frago session search`` 解决了"在成千上万场历史会话里找到哪一场"，但找到那场会话之后，
``raw.jsonl`` 动辄数兆到数十兆字节（夹杂着几万字符的工具原始输出、``<frago-employee>``
岗位注入块、``<must-use-skill>`` 技能块与系统提醒）。主代理若直接 ``Read`` 或手写
``uv run python`` 切片硬读，两三轮就会把主会话上下文撑涨数万 token。

本模块把"读旧会话提结论"拆成两步：

1. **代码层清洗、切窗与脱敏**：定位会话记录（优先 ``~/.frago/sessions`` 备份库，兼顾本机
   实时会话存储），剥离注入块与超长噪音，对连接串和密钥做脱敏，再按显式参数（``--range`` /
   ``--grep`` / ``--tail``）或问句里的范围与关键词切出高相关记录段；
2. **``frago-core`` 单轮无状态提炼**：把清洗后的记录片段与问句通过标准输入交给
   ``frago-core --mode chat --as-role lightagent`` 单轮回答——不带工具、不起 tmux、
   不在 ``~/.frago/coreagent/sessions/`` 留任何新会话，几秒内只把提炼后的结论返给主代理。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from frago.session.search import (
    _CORE_DIRS,
    RAW_FILENAME,
    STEPS_FILENAME,
    _record_epoch,
    _record_text,
    backup_root,
    literal_terms,
)
from frago.session.session_index import split_employee_block

logger = logging.getLogger(__name__)

# 单轮轻量提取默认超时（秒）。
ASK_TIMEOUT_S = 60.0

# 调用 lightagent 单轮提取时必须剥离的父进程内核覆盖与工作目录同步环境变量，
# 防止在 CoreAgent 子会话中执行 frago session ask 时把父会话的模型覆盖传给 lightagent。
_STRIPPED_KERNEL_ENV = (
    "FRAGO_KERNEL_MODEL",
    "FRAGO_KERNEL_ENDPOINT",
    "FRAGO_KERNEL_API_KEY",
    "FRAGO_KERNEL_WIRE",
    "FRAGO_COREAGENT_CWD_FILE",
)

# 喂给轻量模型的会话记录总字符预算（约 1.5~2 万 token，flash 模型数秒可读完）。
MAX_CONTEXT_CHARS = 32_000

# 单条记录的最大保留字符数：模型总结/回答完整保留（上限 12000 字），工具原始输出压在 4000 字。
MAX_RECORD_CHARS = 12_000
MAX_TOOL_RECORD_CHARS = 4_000

_SKILL_BLOCK_RE = re.compile(
    r"<must-use-skill\b[^>]*>[\s\S]*?</must-use-skill>\s*",
    re.IGNORECASE,
)
_SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>[\s\S]*?</system-reminder>\s*",
    re.IGNORECASE,
)
_RANGE_IN_QUESTION_RE = re.compile(
    r"第\s*(\d+)\s*(?:至|到|-|~|—|\.\.)\s*(\d+)\s*(?:条|步|行|个)?"
)
_TAIL_IN_QUESTION_RE = re.compile(r"(?:最后|末尾|最新|收尾|最终)")

# 基础敏感信息脱敏：数据库连接串密码、Bearer 令牌、常见 sk- 密钥与 password/token 赋值。
_URI_CRED_RE = re.compile(
    r"\b((?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqp|amqps|clickhouse)"
    r"://[^:/@\s]+:)([^@\s]+)(@)",
    re.IGNORECASE,
)
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_BEARER_RE = re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)
_KV_SECRET_RE = re.compile(
    r"(\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
    r"\s*[:=]\s*['\"]?)([^'\"\s,;]{6,})(['\"]?)",
    re.IGNORECASE,
)

_ASK_PROMPT = """\
你是历史会话记录提取助手。请严格根据下方提供的会话记录片段，回答调用方的问题。

要求：
1. 直接给出提炼后的结论或目标内容，不要寒暄、不要复述规则。
2. 引用具体事实、结论、报错或输出时，标明对应的记录序号（如 `[#482]`）。
3. 关键代码、命令、文件路径、配置项、数字与结论原文保持准确，不要改写。
4. 凡涉及数据库连接串、密码、API Key、Token 等敏感凭据，一律保持脱敏状态（`***`）。
5. 如果提供的记录片段中没有包含问题所需的信息，直接说明「当前命中记录段内未找到该信息」，并指出最接近的记录序号与内容，NEVER 编造。

会话信息：
- 会话 ID：{session_id}（来源：{source}，共 {total_records} 条有效记录，本次选取 {selected_count} 条）
- 提取问题：{question}

=== 会话记录片段 ===
{transcript}
=== 记录片段结束 ===

请直接回答「{question}」："""


class SessionAskError(RuntimeError):
    """会话提取业务异常基类。"""


class SessionAskNotFound(SessionAskError):
    """找不到对应的会话。"""


class SessionAskAmbiguous(SessionAskError):
    """会话前缀匹配到了多场不同的会话。"""

    def __init__(self, prefix: str, candidates: list[str]) -> None:
        self.prefix = prefix
        self.candidates = candidates
        joined = "、".join(candidates[:8])
        super().__init__(f"会话前缀「{prefix}」匹配到多场会话：{joined}。请给更长的前缀或完整 ID。")


@dataclass(frozen=True)
class AskRecord:
    """清洗后的单条会话记录。"""

    seq: int
    """1-based 记录序号（与文件中的非空记录行对齐）。"""

    role: str
    """``user`` / ``assistant`` / ``tool`` / ``record``。"""

    timestamp: str
    """可读时间（取不到时为空串）。"""

    text: str
    """清洗并脱敏后的文本。"""


@dataclass
class AskResult:
    """一次 ``frago session ask`` 的完整产出。"""

    session_id: str
    source: str
    question: str
    answer: str
    answer_source: str
    """``lightagent``（模型单轮提炼）或 ``fallback``（模型未通，直接回传命中的脱敏记录段）。"""

    total_records: int
    selected_seqs: list[int] = field(default_factory=list)
    location: str = ""
    duration_ms: int = 0
    note: str = ""


def redact_secrets(text: str) -> str:
    """对文本中的连接串口令、Bearer Token 与 API Key 做脱敏。"""
    if not text:
        return ""
    out = _URI_CRED_RE.sub(r"\1***\3", text)
    out = _SK_KEY_RE.sub("sk-***REDACTED***", out)
    out = _BEARER_RE.sub(r"\1***REDACTED***", out)
    out = _KV_SECRET_RE.sub(r"\1***\3", out)
    return out


def clean_record_text(text: str) -> str:
    """剥离员工本体注入块、技能块与系统提醒，并做敏感串脱敏。"""
    if not text:
        return ""
    _, stripped = split_employee_block(text)
    stripped = _SKILL_BLOCK_RE.sub("", stripped)
    stripped = _SYSTEM_REMINDER_RE.sub("", stripped)
    stripped = redact_secrets(stripped)
    return stripped.strip()


def _detect_role(record: dict[str, Any]) -> str:
    rec_type = record.get("type")
    if isinstance(rec_type, str) and rec_type in ("user", "assistant", "tool", "system"):
        return rec_type
    msg = record.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("role"), str):
        return msg["role"]
    payload = record.get("payload")
    if isinstance(payload, dict):
        role = payload.get("role") or payload.get("type")
        if isinstance(role, str):
            return role
    if "step_index" in record and isinstance(record.get("role"), str):
        return str(record["role"])
    return str(rec_type or "record")


def _truncate_record(text: str, terms: list[str], max_chars: int = MAX_RECORD_CHARS) -> str:
    """单条记录过长时保留头尾及首个命中词周边窗口。"""
    if len(text) <= max_chars:
        return text
    lower = text.lower()
    hit_pos = -1
    for term in terms:
        pos = lower.find(term.lower())
        if pos >= 0:
            hit_pos = pos
            break
    if hit_pos >= 0:
        half = max_chars // 3
        head = text[:half]
        w_start = max(half, hit_pos - half // 2)
        w_end = min(len(text), w_start + half)
        mid = text[w_start:w_end]
        tail = text[-half:]
        return f"{head}\n...[中间省略，命中片段]...\n{mid}\n...[中间省略]...\n{tail}"
    head_len = int(max_chars * 0.6)
    tail_len = max_chars - head_len
    return f"{text[:head_len]}\n...[单条过长已省略 {len(text) - max_chars} 字]...\n{text[-tail_len:]}"


def parse_range_spec(spec: str | None, question: str = "") -> tuple[int, int] | None:
    """解析 ``--range 450:520``（或 ``450-520``），未传时尝试识别问句里的「第 X 至 Y 条」。"""
    if spec and spec.strip():
        cleaned = spec.strip()
        m = re.match(r"^(\d+)\s*[:\-~.]+\s*(\d+)$", cleaned)
        if not m:
            raise ValueError(f"无法解析范围参数「{spec}」，请用 --range 起:止（如 --range 450:520）")
        start, end = int(m.group(1)), int(m.group(2))
        return (min(start, end), max(start, end))

    m_q = _RANGE_IN_QUESTION_RE.search(question or "")
    if m_q:
        start, end = int(m_q.group(1)), int(m_q.group(2))
        return (min(start, end), max(start, end))
    return None


def locate_session_file(
    session_id_or_prefix: str,
    *,
    root: Path | None = None,
) -> tuple[str, str, Path] | None:
    """在 ``~/.frago/sessions`` 备份树里按完整 ID 或唯一前缀定位会话文件。

    返回 ``(source, full_session_id, path)``；优先 ``raw.jsonl``，次选 ``steps.jsonl``。
    """
    needle = session_id_or_prefix.strip()
    if not needle:
        return None
    corpus = root or backup_root()
    if not corpus.is_dir():
        return None

    matches: dict[str, tuple[str, Path]] = {}
    for core_dir, canonical_core in _CORE_DIRS.items():
        base = corpus / core_dir
        if not base.is_dir():
            continue
        # 精确匹配优先走直达路径，无需扫目录。
        exact_dir = base / needle
        if exact_dir.is_dir():
            candidate_file = exact_dir / RAW_FILENAME
            if not candidate_file.is_file():
                candidate_file = exact_dir / STEPS_FILENAME
            if candidate_file.is_file():
                return canonical_core, needle, candidate_file

        try:
            with os.scandir(base) as entries:
                for entry in entries:
                    if not entry.is_dir() or not entry.name.startswith(needle):
                        continue
                    sid = entry.name
                    raw_path = Path(entry.path) / RAW_FILENAME
                    steps_path = Path(entry.path) / STEPS_FILENAME
                    chosen = raw_path if raw_path.is_file() else (steps_path if steps_path.is_file() else None)
                    if chosen is None:
                        continue
                    prev = matches.get(sid)
                    if prev is None or (prev[1].name != RAW_FILENAME and chosen.name == RAW_FILENAME):
                        matches[sid] = (canonical_core, chosen)
        except OSError as exc:
            logger.debug("scan failed in %s: %s", base, exc)

    if not matches:
        return None
    if len(matches) > 1:
        raise SessionAskAmbiguous(needle, sorted(matches.keys()))
    sid, (core, path) = next(iter(matches.items()))
    return core, sid, path


def load_records_from_jsonl(path: Path, *, terms: list[str] | None = None) -> list[AskRecord]:
    """从备份 ``raw.jsonl`` 或 ``steps.jsonl`` 读取并清洗全部记录。

    ``seq`` 与文件中的行号（1-based）保持一致：调用方说「第 450 至 520 条记录」时，
    对应的正是文件中的第 450~520 行记录。
    """
    records: list[AskRecord] = []
    search_terms = terms or []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except (ValueError, TypeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                raw_text = _record_text(obj)
                cleaned = clean_record_text(raw_text)
                if not cleaned:
                    continue
                epoch = _record_epoch(obj)
                stamp = ""
                if epoch:
                    try:
                        from datetime import datetime

                        stamp = datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
                    except (OSError, OverflowError, ValueError):
                        stamp = ""
                role = _detect_role(obj)
                cap = (
                    MAX_TOOL_RECORD_CHARS
                    if role.lower() in ("tool", "tool_result", "generic", "function_call_output")
                    else MAX_RECORD_CHARS
                )
                records.append(
                    AskRecord(
                        seq=lineno,
                        role=role,
                        timestamp=stamp,
                        text=_truncate_record(cleaned, search_terms, max_chars=cap),
                    )
                )
    except OSError as exc:
        logger.debug("failed reading %s: %s", path, exc)
    return records


def _load_records_from_live_store(
    session_id_or_prefix: str,
    *,
    terms: list[str] | None = None,
) -> tuple[str, str, str, list[AskRecord]] | None:
    """备份库里还没有（如刚启动不到 30 秒的会话）时，退到本机实时会话层按前缀读取。"""
    from frago.session import record_reader

    needle = session_id_or_prefix.strip()
    try:
        cards = record_reader.list_sessions()
    except Exception as exc:  # noqa: BLE001
        logger.debug("live list_sessions failed: %s", exc)
        return None

    matched = [c for c in cards if c.session_id == needle or c.session_id.startswith(needle)]
    if not matched:
        return None
    unique_ids = sorted({c.session_id for c in matched})
    if len(unique_ids) > 1:
        raise SessionAskAmbiguous(needle, unique_ids)

    card = matched[0]
    try:
        unified = record_reader.read_records(card.session_id, after=0, limit=record_reader.MAX_LIMIT)
    except Exception as exc:  # noqa: BLE001
        logger.debug("live read_records failed for %s: %s", card.session_id, exc)
        return None

    search_terms = terms or []
    out: list[AskRecord] = []
    for idx, rec in enumerate(unified, start=1):
        payload = getattr(rec, "payload", None)
        payload_dict = payload if isinstance(payload, dict) else {}
        chunks = [
            getattr(rec, "text", None) or payload_dict.get("text") or "",
            getattr(rec, "summary", None) or payload_dict.get("summary") or "",
            getattr(rec, "command", None) or payload_dict.get("command") or "",
            getattr(rec, "output", None) or payload_dict.get("output") or "",
            getattr(rec, "error", None) or payload_dict.get("message") or "",
        ]
        cleaned = clean_record_text("\n".join(c for c in chunks if c))
        if not cleaned:
            continue
        out.append(
            AskRecord(
                seq=rec.seq if rec.seq > 0 else idx,
                role=rec.kind,
                timestamp="",
                text=_truncate_record(cleaned, search_terms),
            )
        )
    return card.family, card.session_id, f"live:{card.family}/{card.session_id}", out


def select_records_for_ask(
    records: list[AskRecord],
    question: str,
    *,
    grep: str | None = None,
    tail: int | None = None,
    range_spec: str | None = None,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> list[AskRecord]:
    """按显式条件（``--range`` / ``--grep`` / ``--tail``）与问句关键词挑出送给轻量模型的记录段。"""
    if not records:
        return []

    seq_range = parse_range_spec(range_spec, question)
    grep_terms = [t.strip() for t in (grep or "").split(",") if t.strip()]
    question_terms = literal_terms(question)

    # 1. 若调用方（或问句本身）明确指定了范围、关键词或末尾条数，先按显式条件取候选集。
    explicit_indices: set[int] = set()
    has_explicit_filter = bool(seq_range or grep_terms or (tail and tail > 0))

    if seq_range is not None:
        lo, hi = seq_range
        for i, rec in enumerate(records):
            if lo <= rec.seq <= hi:
                explicit_indices.add(i)
        # 若文件里有效记录的 seq 因空行/过滤有偏移，同時用列表下标兜底。
        if not explicit_indices:
            for i in range(max(0, lo - 1), min(len(records), hi)):
                explicit_indices.add(i)

    if grep_terms:
        for i, rec in enumerate(records):
            hay = rec.text.lower()
            if any(term.lower() in hay for term in grep_terms):
                for neighbor in range(max(0, i - 2), min(len(records), i + 3)):
                    explicit_indices.add(neighbor)

    if tail and tail > 0:
        for i in range(max(0, len(records) - tail), len(records)):
            explicit_indices.add(i)

    if has_explicit_filter:
        chosen = [records[i] for i in sorted(explicit_indices)]
        # 若显式过滤（如仅 --range）还带有 --grep，再在范围内优先保留命中行。
        return _fit_budget(chosen, grep_terms + question_terms, max_chars=max_chars)

    # 2. 未给显式过滤时：若整场都在字符预算内，整场直接喂给轻量模型。
    total_len = sum(len(r.text) + 32 for r in records)
    if total_len <= max_chars:
        return list(records)

    # 3. 超长会话智能切窗：保留开场背景（前 3 条）+ 末尾结论段（最后 25 条，若问句问"最后/末尾"则优先）
    #    + 按问句字面量命中数排序的高相关记录及其邻近上下文。
    wants_tail = bool(_TAIL_IN_QUESTION_RE.search(question or ""))

    tail_indices = list(range(max(0, len(records) - 25), len(records)))
    head_indices = list(range(min(3, len(records))))

    scored: list[tuple[int, int, int]] = []
    for i, rec in enumerate(records):
        hay = rec.text.lower()
        hits = sum(1 for t in question_terms if t.lower() in hay)
        if hits > 0:
            scored.append((hits, i, i))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    hit_with_neighbors: list[int] = []
    for _, idx, _ in scored:
        for neighbor in (idx - 1, idx, idx + 1):
            if 0 <= neighbor < len(records):
                hit_with_neighbors.append(neighbor)

    if wants_tail:
        order = tail_indices + hit_with_neighbors + head_indices
    else:
        order = hit_with_neighbors + tail_indices + head_indices

    seen: set[int] = set()
    budget = 0
    for idx in order:
        if idx in seen:
            continue
        cost = len(records[idx].text) + 32
        if budget + cost > max_chars and seen:
            continue
        seen.add(idx)
        budget += cost

    return [records[i] for i in sorted(seen)]


def _fit_budget(
    records: list[AskRecord],
    terms: list[str],
    *,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> list[AskRecord]:
    """把已选记录控制在 ``max_chars`` 内，保持原有时间顺序。"""
    total = sum(len(r.text) + 32 for r in records)
    if total <= max_chars:
        return records

    scored_indices = sorted(
        range(len(records)),
        key=lambda i: (
            sum(1 for t in terms if t.lower() in records[i].text.lower()),
            i,
        ),
        reverse=True,
    )
    kept: set[int] = set()
    budget = 0
    for idx in scored_indices:
        cost = len(records[idx].text) + 32
        if budget + cost > max_chars and kept:
            continue
        kept.add(idx)
        budget += cost
    return [records[i] for i in sorted(kept)]


def format_records_block(records: list[AskRecord]) -> str:
    """将记录列表拼成带序号与角色的紧凑文本块。"""
    lines: list[str] = []
    for rec in records:
        stamp_part = f" {rec.timestamp}" if rec.timestamp else ""
        lines.append(f"[#{rec.seq} {rec.role}{stamp_part}]\n{rec.text}")
    return "\n\n".join(lines)


def ask_session(
    session_id: str,
    question: str,
    *,
    grep: str | None = None,
    tail: int | None = None,
    range_spec: str | None = None,
    model: str | None = None,
    timeout_s: float = ASK_TIMEOUT_S,
    root: Path | None = None,
) -> AskResult:
    """对指定历史会话执行一次清洗切窗 + ``frago-core`` 单轮轻量模型提取。"""
    started = time.monotonic()
    terms = [t.strip() for t in (grep or "").split(",") if t.strip()] + literal_terms(question)

    located = locate_session_file(session_id, root=root)
    if located is not None:
        source, full_sid, path = located
        location = str(path)
        records = load_records_from_jsonl(path, terms=terms)
    else:
        live = _load_records_from_live_store(session_id, terms=terms)
        if live is None:
            raise SessionAskNotFound(
                f"找不到会话「{session_id}」（已查 ~/.frago/sessions 备份库与本机实时会话）。"
                f"可先跑 frago session search \"<关键词>\" 确认会话 ID。"
            )
        source, full_sid, location, records = live

    if not records:
        return AskResult(
            session_id=full_sid,
            source=source,
            question=question,
            answer="该会话没有任何可读文本记录（可能仅包含空壳元数据）。",
            answer_source="fallback",
            total_records=0,
            selected_seqs=[],
            location=location,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    selected = select_records_for_ask(
        records,
        question,
        grep=grep,
        tail=tail,
        range_spec=range_spec,
    )
    if not selected:
        return AskResult(
            session_id=full_sid,
            source=source,
            question=question,
            answer="按当前过滤条件（--range / --grep / --tail）未匹配到任何记录，请放宽条件重试。",
            answer_source="fallback",
            total_records=len(records),
            selected_seqs=[],
            location=location,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    transcript = format_records_block(selected)
    prompt = _ASK_PROMPT.format(
        session_id=full_sid,
        source=source,
        total_records=len(records),
        selected_count=len(selected),
        question=question,
        transcript=transcript,
    )

    from frago.agent_driver import kernel_backend

    note = ""
    clean_env = dict(os.environ)
    saved_kernel_env: dict[str, str] = {}
    for key in _STRIPPED_KERNEL_ENV:
        clean_env.pop(key, None)
        if key in os.environ:
            saved_kernel_env[key] = os.environ.pop(key)
    try:
        turn = kernel_backend.run_chat_turn(
            prompt,
            cwd=os.getcwd(),
            role="lightagent",
            model=model,
            timeout_s=timeout_s,
            env=clean_env,
        )
        status, text = turn.status, (turn.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - 轻量模型不可用时退回直接展示切窗后的脱敏片段
        logger.debug("session ask chat turn failed: %s", exc)
        status, text = "error", str(exc)
    finally:
        os.environ.update(saved_kernel_env)

    duration_ms = int((time.monotonic() - started) * 1000)
    if status == "ok" and text:
        return AskResult(
            session_id=full_sid,
            source=source,
            question=question,
            answer=redact_secrets(text),
            answer_source="lightagent",
            total_records=len(records),
            selected_seqs=[r.seq for r in selected],
            location=location,
            duration_ms=duration_ms,
        )

    note = f"轻量模型单轮提取返回 {status}（{text or '无详情'}），已退回直接输出命中的脱敏记录片段"
    fallback_body = format_records_block(selected[:15])
    return AskResult(
        session_id=full_sid,
        source=source,
        question=question,
        answer=fallback_body,
        answer_source="fallback",
        total_records=len(records),
        selected_seqs=[r.seq for r in selected],
        location=location,
        duration_ms=duration_ms,
        note=note,
    )
