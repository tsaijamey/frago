"""跨 claude / opencode 两个原始会话库的语义检索。

## 解决什么问题

"上个月那次把浏览器扩展桥接调通的会话"——人记得的是这么一句话，而两个会话库里
存的是 JSONL 记录和 SQLite 片段。一句话和一堆记录之间隔着一步：得先想清楚这件事
在当时的会话里会以哪些字面量出现（``extension bridge``、``桥接``、``chrome
extension``、``ws://``、报错原文……），才谈得上检索。

这一步恰恰是代码做不好而模型做得好的。所以分工是：**模型负责把一句话摊成关键词
组合，代码负责拿着关键词把两个库翻个底朝天**。反过来（让模型自己去 grep）会退化成
一轮一轮的试探，慢且不可复现。

## 两个库的差别

claude 的会话是 ``~/.claude/projects/<项目>/<会话 id>.jsonl``，一条记录一行，
2.6 GB 量级——ripgrep 扫一遍不到一秒，Python 逐行读要几分钟，所以搜索这一步交给
ripgrep，只有排进前几名的那几个文件才由 Python 打开取元数据和上下文。

opencode 的会话在 SQLite 里（``part`` 表一行一个片段），30 MB 量级，直接
``LIKE`` 查询即可，只读打开，NEVER 写。

## 计数口径

排序看的是**命中了几个不同的关键词**，其次才是命中密度。原因是 JSONL 的一行是
一整条记录，动辄几万字符，同一个词在一行里出现一百次不代表这个会话更相关；
而同时命中五个不同的关键词，几乎一定就是要找的那场会话。所以密度按"命中的
不同行数"算，不按原始匹配数算。

ripgrep 侧对每个文件设了匹配行数上限（见 :data:`RG_MAX_LINES_PER_FILE`）——
上限触顶的会话会在结果里标出来，NEVER 让"数到这就不数了"看起来像"总共就这些"。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR, _scan_file
from frago.session.opencode_store import _connect, db_path

logger = logging.getLogger(__name__)

# 每个文件最多计多少个匹配行。够用来排序，又不至于让 ripgrep 把一个巨型会话的
# 每一行都吐出来。触顶会在结果里标注。
RG_MAX_LINES_PER_FILE = 40

# 一次 ripgrep 调用最多带多少个文件路径，超出就分批。命令行长度有上限，
# 而这里的路径列表可以上千条。
RG_PATH_CHUNK = 400

# opencode 侧每个关键词最多取多少个片段。
OPENCODE_PART_LIMIT = 3000

# 每个会话最多留几段上下文。
MAX_SNIPPETS_PER_SESSION = 3

# 一段上下文在命中词两侧各取多少字符。
SNIPPET_RADIUS = 140

# 关键词扩展这一轮给模型多少秒。扩展只是产出十来个词，超时说明这条路不通，
# 退回字面量而不是干等。
EXPAND_TIMEOUT_S = 180

# 太短或太通用的词会匹配到一切，扩展结果里出现就丢掉。
MIN_TERM_LEN_ASCII = 3
MIN_TERM_LEN_CJK = 2

_ASCII_ONLY = re.compile(r"^[\x00-\x7f]+$")

_EXPAND_PROMPT = """\
你是关键词扩展器。把下面这句自然语言检索意图，扩展成用于 ripgrep 与 SQL LIKE \
的**字面量子串**，用来在我本地的 AI 编程会话记录里做全文检索。

检索意图：{query}

规则：
- 只输出一个 JSON 对象，不要解释、不要 markdown 代码块、不要前后缀。
- 形如 {{"terms": ["...", "..."], "note": "一句话说明扩展思路"}}
- terms 是**字面量子串**（不是正则），匹配时大小写不敏感，给 8 到 14 个。
- 中文与英文变体都要给——会话里两种语言混用。
- 覆盖这几类：核心名词、同义说法、相关技术名词、可能出现的命令名 / 文件名 / \
函数名 / 报错原文。
- NEVER 给单字或过于通用的词（"的"、"the"、"code"、"file"、"问题"），它们会匹配到一切。
- 每个词至少 2 个汉字或 3 个英文字母。

现在只输出那个 JSON 对象。"""


@dataclass(frozen=True)
class KeywordPlan:
    """一次检索用的关键词集合及其来历。"""

    terms: list[str]
    note: str
    source: str
    """``agent`` 模型扩展 / ``explicit`` 调用方直接给 / ``literal`` 退回原句切词。"""


@dataclass
class Snippet:
    term: str
    text: str


@dataclass
class SessionHit:
    """一个命中的会话。"""

    source: str
    """``claude`` 或 ``opencode``。"""

    session_id: str
    title: str | None
    cwd: str | None
    last_activity: float
    """最后活动时刻（epoch 秒）。"""

    matched_terms: list[str]
    hit_lines: int
    """命中的不同记录数（claude 是行，opencode 是片段）。"""

    location: str
    resume_command: str
    capped: bool = False
    """该会话触到了每文件计数上限，实际命中量只多不少。"""

    snippets: list[Snippet] = field(default_factory=list)

    @property
    def rank(self) -> tuple[int, int, float]:
        """命中的不同关键词数 > 命中密度 > 最近活动。"""
        return (len(self.matched_terms), self.hit_lines, self.last_activity)


@dataclass
class SearchResult:
    query: str
    plan: KeywordPlan
    hits: list[SessionHit]
    scanned_claude_files: int
    opencode_available: bool
    duration_ms: int
    warnings: list[str] = field(default_factory=list)


# ── 关键词扩展 ──────────────────────────────────────────────────────
def _clean_terms(raw: Any) -> list[str]:
    """把模型给的 terms 洗成可用的字面量：去重、去空白、按长度下限过滤。"""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if not term:
            continue
        floor = MIN_TERM_LEN_ASCII if _ASCII_ONLY.match(term) else MIN_TERM_LEN_CJK
        if len(term) < floor:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(term)
    return cleaned


def _parse_expansion(text: str) -> tuple[list[str], str] | None:
    """从模型输出里抠出那个 JSON 对象。抠不出来返回 None。"""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    terms = _clean_terms(parsed.get("terms"))
    if not terms:
        return None
    note = parsed.get("note")
    return terms, note if isinstance(note, str) else ""


def literal_terms(query: str) -> list[str]:
    """退路：把原句按非文字字符切开当关键词。

    模型不可用时它保证命令仍然出结果——差的检索远好过没有检索。
    """
    pieces = re.split(r"[^\w一-鿿]+", query)
    return _clean_terms([p for p in pieces if p])


def expand_query(
    query: str,
    *,
    agent_type: str | None = None,
    model: str | None = None,
    timeout_s: float = EXPAND_TIMEOUT_S,
) -> KeywordPlan:
    """让模型把一句话摊成关键词组合。

    任何一步不成（没配 agent、tmux 起不来、超时、输出不是 JSON）都退回
    :func:`literal_terms`，并在 ``source`` 上写明这次是退回来的——NEVER 因为
    扩展失败就让整条命令失败。
    """
    from frago.agent_driver import SessionLauncher

    if agent_type is None:
        try:
            from frago.init.config_manager import get_agent_core

            agent_type = get_agent_core()
        except Exception as exc:  # noqa: BLE001 - 配置读不出来不该拖垮检索
            logger.debug("agent core lookup failed: %s", exc)
            agent_type = "claude"

    env = {"FRAGO_AGENT_ROLE": "worker"}
    if model:
        env["ANTHROPIC_MODEL"] = model

    try:
        result = SessionLauncher().run(
            _EXPAND_PROMPT.format(query=query),
            agent_type=agent_type,
            session_id=str(uuid.uuid4()),
            cwd=os.getcwd(),
            env=env,
            timeout_s=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - driver/tmux 层任何失败都只是退路条件
        logger.debug("keyword expansion driver failed: %s", exc)
        return KeywordPlan(literal_terms(query), f"关键词扩展没跑成（{exc}），退回原句切词", "literal")

    if result.status != "ok":
        return KeywordPlan(
            literal_terms(query),
            f"关键词扩展返回 {result.status}，退回原句切词",
            "literal",
        )
    parsed = _parse_expansion(result.text or "")
    if parsed is None:
        return KeywordPlan(literal_terms(query), "关键词扩展的输出不是 JSON，退回原句切词", "literal")
    terms, note = parsed
    return KeywordPlan(terms, note, "agent")


# ── claude 侧：ripgrep ──────────────────────────────────────────────
def _claude_files(root: Path, since_ts: float | None) -> list[Path]:
    """待搜的会话文件，按最后修改时间倒序（新的先排）。"""
    if not root.exists():
        return []
    files: list[tuple[float, Path]] = []
    for proj in root.iterdir():
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            if since_ts is not None and mtime < since_ts:
                continue
            files.append((mtime, jsonl))
    files.sort(key=lambda pair: pair[0], reverse=True)
    return [path for _, path in files]


def _rg_command(terms: list[str], paths: list[Path]) -> list[str]:
    cmd = [
        "rg",
        "--null",            # 文件名后跟 NUL，路径里有冒号也不会切错
        "--only-matching",   # 只吐命中的那一小段，NEVER 吐几万字符的整行
        "--fixed-strings",   # 关键词是字面量，里面的 . ( + 不当正则解释
        "--ignore-case",
        "--no-heading",
        "--with-filename",
        "--line-number",
        "--no-messages",
        "--no-config",
        "--no-ignore",
        "--max-count",
        str(RG_MAX_LINES_PER_FILE),
    ]
    for term in terms:
        cmd += ["-e", term]
    cmd += [str(p) for p in paths]
    return cmd


def _run_rg(terms: list[str], paths: list[Path]) -> tuple[dict[str, dict[str, set[int]]], bool]:
    """跑一批文件，返回 ``{文件: {关键词: 命中行号集合}}`` 与"是否跑成了"。"""
    per_file: dict[str, dict[str, set[int]]] = {}
    lookup = {t.lower(): t for t in terms}
    try:
        proc = subprocess.run(  # noqa: S603 - 参数全部由本模块构造
            _rg_command(terms, paths),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("ripgrep invocation failed: %s", exc)
        return per_file, False
    # 0=有命中，1=无命中，都是正常结果；2 才是真出错。
    if proc.returncode not in (0, 1):
        logger.debug("ripgrep exited %s: %s", proc.returncode, proc.stderr[:400])
        return per_file, False

    for raw in proc.stdout.splitlines():
        path, sep, rest = raw.partition("\0")
        if not sep:
            continue
        lineno_text, sep2, matched = rest.partition(":")
        if not sep2 or not lineno_text.isdigit():
            continue
        term = lookup.get(matched.lower())
        if term is None:
            continue
        per_file.setdefault(path, {}).setdefault(term, set()).add(int(lineno_text))
    return per_file, True


def _snippet_from_line(line: str, term: str) -> str | None:
    """从一条 JSONL 记录里取命中词周边的一段可读文本。

    先按 JSON 解析、拼出文本内容再取窗口；解析不了就直接在原始行上开窗——
    读得懂的优先，读不懂也 NEVER 什么都不给。
    """
    haystack = line
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        record = None
    if isinstance(record, dict):
        flattened = _flatten_record(record)
        if term.lower() in flattened.lower():
            haystack = flattened
    idx = haystack.lower().find(term.lower())
    if idx < 0:
        return None
    start = max(0, idx - SNIPPET_RADIUS)
    end = min(len(haystack), idx + len(term) + SNIPPET_RADIUS)
    text = haystack[start:end].replace("\n", " ").strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(haystack) else ""
    return f"{prefix}{text}{suffix}"


def _flatten_record(record: dict[str, Any]) -> str:
    """把一条会话记录里的可读文本摊平成一串。"""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = record.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                for key in ("text", "thinking"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                if block.get("type") == "tool_use":
                    parts.append(f"[tool_use {block.get('name', '')}] {block.get('input')}")
                if block.get("type") == "tool_result":
                    result = block.get("content")
                    parts.append(f"[tool_result] {result}")
    for key in ("summary", "content", "lastPrompt", "customTitle"):
        value = record.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _collect_claude_snippets(
    path: Path, term_lines: dict[str, set[int]]
) -> list[Snippet]:
    """打开命中的会话文件，按行号取几段上下文。每个关键词至多一段。"""
    wanted: dict[int, str] = {}
    for term, lines in term_lines.items():
        for lineno in sorted(lines)[:1]:
            wanted.setdefault(lineno, term)
    if not wanted:
        return []
    snippets: list[Snippet] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, start=1):
                term = wanted.get(lineno)
                if term is None:
                    continue
                text = _snippet_from_line(line, term)
                if text:
                    snippets.append(Snippet(term=term, text=text))
                if len(snippets) >= MAX_SNIPPETS_PER_SESSION:
                    break
    except OSError as exc:
        logger.debug("snippet read failed for %s: %s", path, exc)
    return snippets


def search_claude(
    terms: list[str],
    *,
    since_ts: float | None = None,
    top: int = 10,
    projects_root: Path | None = None,
) -> tuple[list[SessionHit], int, list[str]]:
    """搜 claude 会话。返回 ``(命中, 扫过的文件数, 告警)``。"""
    warnings: list[str] = []
    if shutil.which("rg") is None:
        return [], 0, ["ripgrep (rg) 不在 PATH 上，claude 会话这一半没搜"]

    root = projects_root or CLAUDE_PROJECTS_DIR
    files = _claude_files(root, since_ts)
    if not files:
        return [], 0, [f"{root} 下没有可搜的会话文件"]

    merged: dict[str, dict[str, set[int]]] = {}
    for start in range(0, len(files), RG_PATH_CHUNK):
        chunk = files[start : start + RG_PATH_CHUNK]
        per_file, ok = _run_rg(terms, chunk)
        if not ok:
            warnings.append(f"ripgrep 在第 {start // RG_PATH_CHUNK + 1} 批文件上失败，该批已跳过")
            continue
        for path, term_lines in per_file.items():
            target = merged.setdefault(path, {})
            for term, lines in term_lines.items():
                target.setdefault(term, set()).update(lines)

    ranked = sorted(
        merged.items(),
        key=lambda item: (
            len(item[1]),
            sum(len(v) for v in item[1].values()),
        ),
        reverse=True,
    )

    hits: list[SessionHit] = []
    for path_text, term_lines in ranked[:top]:
        path = Path(path_text)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        data = _scan_file(path) or {}
        distinct_lines = {ln for lines in term_lines.values() for ln in lines}
        title = data.get("custom_title") or data.get("ai_title") or data.get("slug")
        hits.append(
            SessionHit(
                source="claude",
                session_id=path.stem,
                title=title,
                cwd=data.get("cwd"),
                last_activity=mtime,
                matched_terms=sorted(term_lines),
                hit_lines=len(distinct_lines),
                location=str(path),
                resume_command=f"claude --resume {path.stem}",
                capped=len(distinct_lines) >= RG_MAX_LINES_PER_FILE,
                snippets=_collect_claude_snippets(path, term_lines),
            )
        )
    return hits, len(files), warnings


# ── opencode 侧：SQLite ─────────────────────────────────────────────
_LIKE_ESCAPE = str.maketrans({"\\": r"\\", "%": r"\%", "_": r"\_"})


def _like_pattern(term: str) -> str:
    return f"%{term.translate(_LIKE_ESCAPE)}%"


def _opencode_part_text(raw: str) -> str:
    """片段 JSON 里的可读文本。解析不了就退回原始串。"""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(data, dict):
        return raw
    pieces: list[str] = []
    for key in ("text", "output", "error"):
        value = data.get(key)
        if isinstance(value, str):
            pieces.append(value)
    state = data.get("state")
    if isinstance(state, dict):
        for key in ("input", "output", "error"):
            value = state.get(key)
            if isinstance(value, str):
                pieces.append(value)
            elif isinstance(value, dict):
                pieces.append(json.dumps(value, ensure_ascii=False))
    return "\n".join(pieces) if pieces else raw


def search_opencode(
    terms: list[str],
    *,
    since_ts: float | None = None,
    top: int = 10,
) -> tuple[list[SessionHit], bool, list[str]]:
    """搜 opencode 会话库。返回 ``(命中, 库是否可读, 告警)``。"""
    conn = _connect()
    if conn is None:
        return [], False, [f"opencode 会话库读不到（{db_path()}），这一半没搜"]

    since_ms = int(since_ts * 1000) if since_ts is not None else None
    per_session: dict[str, dict[str, list[str]]] = {}
    warnings: list[str] = []
    try:
        for term in terms:
            sql = (
                "SELECT p.session_id, p.data FROM part p "
                r"WHERE p.data LIKE ? ESCAPE '\' LIMIT ?"
            )
            try:
                rows = conn.execute(sql, (_like_pattern(term), OPENCODE_PART_LIMIT)).fetchall()
            except Exception as exc:  # noqa: BLE001 - 单个词查失败不该毁掉整轮
                logger.debug("opencode search failed for %r: %s", term, exc)
                warnings.append(f"opencode 侧查询关键词 {term!r} 失败：{exc}")
                continue
            for session_id, raw in rows:
                per_session.setdefault(str(session_id), {}).setdefault(term, []).append(
                    raw if isinstance(raw, str) else ""
                )

        if not per_session:
            return [], True, warnings

        placeholders = ",".join("?" * len(per_session))
        meta_rows = conn.execute(
            f"SELECT id, title, directory, time_updated FROM session "  # noqa: S608
            f"WHERE id IN ({placeholders})",
            tuple(per_session),
        ).fetchall()
    finally:
        conn.close()

    meta = {
        str(sid): (
            title if isinstance(title, str) else "",
            directory if isinstance(directory, str) else "",
            updated if isinstance(updated, int) else 0,
        )
        for sid, title, directory, updated in meta_rows
    }

    hits: list[SessionHit] = []
    for session_id, term_parts in per_session.items():
        title, directory, updated_ms = meta.get(session_id, ("", "", 0))
        if since_ms is not None and updated_ms < since_ms:
            continue
        snippets: list[Snippet] = []
        for term, raws in sorted(term_parts.items()):
            if len(snippets) >= MAX_SNIPPETS_PER_SESSION:
                break
            text = _opencode_part_text(raws[0])
            idx = text.lower().find(term.lower())
            if idx < 0:
                continue
            start = max(0, idx - SNIPPET_RADIUS)
            end = min(len(text), idx + len(term) + SNIPPET_RADIUS)
            body = text[start:end].replace("\n", " ").strip()
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(text) else ""
            snippets.append(Snippet(term=term, text=f"{prefix}{body}{suffix}"))
        hits.append(
            SessionHit(
                source="opencode",
                session_id=session_id,
                title=title or None,
                cwd=directory or None,
                last_activity=updated_ms / 1000 if updated_ms else 0.0,
                matched_terms=sorted(term_parts),
                hit_lines=sum(len(v) for v in term_parts.values()),
                location=str(db_path()),
                resume_command=f"opencode -s {session_id}",
                capped=any(len(v) >= OPENCODE_PART_LIMIT for v in term_parts.values()),
                snippets=snippets,
            )
        )
    hits.sort(key=lambda h: h.rank, reverse=True)
    return hits[:top], True, warnings


# ── 编排 ────────────────────────────────────────────────────────────
def search_sessions(
    query: str,
    *,
    terms: list[str] | None = None,
    expand: bool = True,
    days: int | None = None,
    top: int = 10,
    agent_type: str | None = None,
    model: str | None = None,
    expand_timeout_s: float = EXPAND_TIMEOUT_S,
    projects_root: Path | None = None,
) -> SearchResult:
    """一句话 → 关键词 → 两个库都搜 → 合并排序。

    ``terms`` 显式给出时跳过模型扩展；``expand=False`` 则直接用原句切词。
    """
    started = time.time()
    if terms:
        plan = KeywordPlan(_clean_terms(terms), "调用方直接给的关键词", "explicit")
    elif expand:
        plan = expand_query(
            query, agent_type=agent_type, model=model, timeout_s=expand_timeout_s
        )
    else:
        plan = KeywordPlan(literal_terms(query), "未做扩展，按原句切词", "literal")

    if not plan.terms:
        return SearchResult(
            query=query,
            plan=plan,
            hits=[],
            scanned_claude_files=0,
            opencode_available=False,
            duration_ms=int((time.time() - started) * 1000),
            warnings=["没有可用的关键词——原句里全是过短或过于通用的词"],
        )

    since_ts = time.time() - days * 86400 if days else None
    claude_hits, scanned, warnings = search_claude(
        plan.terms, since_ts=since_ts, top=top, projects_root=projects_root
    )
    opencode_hits, opencode_ok, oc_warnings = search_opencode(
        plan.terms, since_ts=since_ts, top=top
    )

    hits = sorted(claude_hits + opencode_hits, key=lambda h: h.rank, reverse=True)[:top]
    return SearchResult(
        query=query,
        plan=plan,
        hits=hits,
        scanned_claude_files=scanned,
        opencode_available=opencode_ok,
        duration_ms=int((time.time() - started) * 1000),
        warnings=warnings + oc_warnings,
    )
