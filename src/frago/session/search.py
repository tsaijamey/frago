"""跨 claude / opencode 两套会话备份的语义检索。

## 解决什么问题

"上个月那次把浏览器扩展桥接调通的会话"——人记得的是这么一句话，而备份里存的是
一堆 JSONL 记录。一句话和一堆记录之间隔着一步：得先想清楚这件事在当时的会话里
会以哪些字面量出现（``extension bridge``、``桥接``、``chrome extension``、
``ws://``、报错原文……），才谈得上检索。

这一步恰恰是代码做不好而模型做得好的。所以分工是：**模型负责把一句话摊成关键词
组合，代码负责拿着关键词把备份翻个底朝天**。反过来（让模型自己去 grep）会退化成
一轮一轮的试探，慢且不可复现。

## 为什么搜备份而不搜 Claude 自己的目录

``~/.claude/projects`` 会随时间滚动删除旧会话——那里现存的只是历史的一小截，
搜它等于宣布几个月前的事没发生过。``~/.frago/sessions`` 是 frago 的备份，只增
不减，30 秒一轮跟到最新，对还活着的会话与源文件逐字节相等。所以检索的语料是
备份，不是原目录。

备份里有两代格式，都搜：

  ``<核>/<会话 id>/raw.jsonl``     原文逐字节副本，claude 侧是原转录、
                                  opencode 侧是一行一个原始片段
  ``<核>/<会话 id>/steps.jsonl``   早期的加工副本，工具返回值等内容已被摘掉

老会话往往只剩 steps.jsonl，而它们的原文已随 Claude 的滚动删除永久消失。这类
会话在结果里标 ``摘要副本``——在那儿搜不到 NEVER 等于那件事没发生过。

## 时间从记录里取，不看文件时间

备份文件的 mtime 是"什么时候备的"，批量回填过的文件全是同一个时刻，跟会话什么
时候发生的毫无关系。所以 ``--days`` 读的是记录自己带的时间：claude 记录是
``timestamp``，opencode 片段是 ``time.start/end``。从文件尾往回扫，遇到第一条
带时间的就停——实测中位数退 2 条记录、p99 退 5 条。

极少数会话（只有 ``mode`` / ``permission-mode`` 这类元数据记录的空壳）文件里
根本没有时间。给了 ``--days`` 时它们被排除，并在告警里报数——NEVER 让"判不出
时间"悄悄消失成"不在范围内"。

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
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.session.claude_sessions import _scan_file
from frago.session.storage import get_session_base_dir

logger = logging.getLogger(__name__)

# 每个文件最多计多少个匹配行。够用来排序，又不至于让 ripgrep 把一个巨型会话的
# 每一行都吐出来。触顶会在结果里标注。
RG_MAX_LINES_PER_FILE = 40

# 每个会话最多留几段上下文。
MAX_SNIPPETS_PER_SESSION = 3

# 一段上下文在命中词两侧各取多少字符。
SNIPPET_RADIUS = 140

# 从文件尾往回找时间戳，一次读多少字节。实测一个块就覆盖 p99。
TAIL_BLOCK_BYTES = 64 * 1024

# 往回找的总上限。超过这个还没找到，就当这个文件没有时间。
TAIL_MAX_BYTES = 4 * 1024 * 1024

# 关键词扩展这一轮给模型多少秒。扩展只是产出十来个词，超时说明这条路不通，
# 退回字面量而不是干等。
EXPAND_TIMEOUT_S = 180

# 太短或太通用的词会匹配到一切，扩展结果里出现就丢掉。
MIN_TERM_LEN_ASCII = 3
MIN_TERM_LEN_CJK = 2

# 备份里的两代文件名。两个都搜。
RAW_FILENAME = "raw.jsonl"
STEPS_FILENAME = "steps.jsonl"

# 备份根下的一级目录 → 会话所属的核。``claude-misc`` 是早期归档出来的一批
# claude 会话，同源同格式，归到 claude 下。
_CORE_DIRS = {"claude": "claude", "claude-misc": "claude", "opencode": "opencode"}

_ASCII_ONLY = re.compile(r"^[\x00-\x7f]+$")

_EXPAND_PROMPT = """\
你是关键词扩展器。把下面这句自然语言检索意图，扩展成用于 ripgrep 的**字面量\
子串**，用来在我本地的 AI 编程会话记录里做全文检索。

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
    """最后活动时刻（epoch 秒），从记录自己带的时间取；判不出时为 0。"""

    matched_terms: list[str]
    hit_lines: int
    """命中的不同记录数（claude 是行，opencode 是片段）。"""

    location: str
    resume_command: str
    capped: bool = False
    """该会话触到了每文件计数上限，实际命中量只多不少。"""

    degraded: bool = False
    """这场只剩早期的加工副本，工具返回值等内容已被摘掉，搜不到 NEVER 等于没发生。"""

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
    corpus_root: str
    scanned_sessions: int
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


# ── 记录里的时间 ────────────────────────────────────────────────────
def _record_epoch(record: dict[str, Any]) -> float | None:
    """一条记录自己带的时刻（epoch 秒）。取不到返回 None。

    claude 转录用 ``timestamp``（ISO-8601，带 Z 或不带时区）；opencode 片段用
    ``time``，是 ``{"start": 毫秒, "end": 毫秒}``。早期加工副本沿用 ``timestamp``，
    写的是不带时区的本地时间，按本地时区解释正是它的原意。
    """
    stamp = record.get("timestamp")
    if isinstance(stamp, str) and stamp:
        try:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    moment = record.get("time")
    if isinstance(moment, dict):
        value = moment.get("end") or moment.get("start")
        if isinstance(value, (int, float)) and value:
            return value / 1000
    elif isinstance(moment, (int, float)) and moment:
        return moment / 1000
    return None


def last_activity_of(path: Path) -> float | None:
    """这个会话文件里最后一条带时间的记录是什么时候。

    从尾往回读块，每块内倒着解析。绝大多数文件退两三条记录就够，所以这比从头
    读一遍便宜几个数量级。整个文件都没有时间时返回 None——那是数据本身没有，
    NEVER 拿文件 mtime 顶替（备份的 mtime 是"什么时候备的"，不是会话时间）。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None

    buf = b""
    pos = size
    try:
        with open(path, "rb") as fh:
            while pos > 0 and (size - pos) < TAIL_MAX_BYTES:
                step = min(TAIL_BLOCK_BYTES, pos)
                pos -= step
                fh.seek(pos)
                buf = fh.read(step) + buf
                lines = buf.split(b"\n")
                # 块的第一段可能是半条记录，除非已经读到文件头。
                candidates = lines if pos == 0 else lines[1:]
                for line in reversed(candidates):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(record, dict):
                        continue
                    moment = _record_epoch(record)
                    if moment:
                        return moment
    except OSError as exc:
        logger.debug("tail read failed for %s: %s", path, exc)
    return None


# ── 记录里的可读文本 ────────────────────────────────────────────────
def _record_text(record: dict[str, Any]) -> str:
    """把一条记录里的可读文本摊平成一串，三种格式都认。"""
    parts: list[str] = []

    # claude 转录：正文挂在 message.content 或 content 下。
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = record.get("content")
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
                    parts.append(f"[tool_result] {block.get('content')}")

    # opencode 片段：正文在顶层 text/output/error，工具调用在 state 下。
    state = record.get("state")
    if isinstance(state, dict):
        for key in ("input", "output", "error"):
            value = state.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                parts.append(json.dumps(value, ensure_ascii=False))

    # 早期加工副本用 content_summary；其余是各格式的零散文本字段。
    for key in ("content_summary", "summary", "text", "output", "error", "lastPrompt", "customTitle"):
        value = record.get(key)
        if isinstance(value, str):
            parts.append(value)

    return "\n".join(parts)


def _snippet_from_line(line: str, term: str) -> str | None:
    """从一条记录里取命中词周边的一段可读文本。

    先按 JSON 解析、拼出文本内容再取窗口；解析不了、或摊平后反而找不到这个词
    （命中的是结构字段而非正文），就直接在原始行上开窗——读得懂的优先，读不懂
    也 NEVER 什么都不给。
    """
    haystack = line
    try:
        record = json.loads(line)
    except (ValueError, TypeError):
        record = None
    if isinstance(record, dict):
        flattened = _record_text(record)
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


def _collect_snippets(path: Path, term_lines: dict[str, set[int]]) -> list[Snippet]:
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


# ── ripgrep ─────────────────────────────────────────────────────────
def _rg_command(terms: list[str], root: Path) -> list[str]:
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
        "--glob",
        RAW_FILENAME,
        "--glob",
        STEPS_FILENAME,
    ]
    for term in terms:
        cmd += ["-e", term]
    cmd.append(str(root))
    return cmd


def _run_rg(terms: list[str], root: Path) -> tuple[dict[str, dict[str, set[int]]], bool]:
    """一趟扫完整棵备份树，返回 ``{文件: {关键词: 命中行号集合}}`` 与"是否跑成了"。

    整棵树 4.5 GB 量级，ripgrep 跑一遍两三秒——不必再像从前那样把路径列表分批
    喂进去，让它自己走目录更快也更短。
    """
    per_file: dict[str, dict[str, set[int]]] = {}
    lookup = {t.lower(): t for t in terms}
    try:
        proc = subprocess.run(  # noqa: S603 - 参数全部由本模块构造
            _rg_command(terms, root),
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


# ── 语料 ────────────────────────────────────────────────────────────
def backup_root() -> Path:
    """检索语料的根：frago 的会话备份目录。"""
    return get_session_base_dir()


def _split_location(root: Path, path: Path) -> tuple[str, str] | None:
    """把备份里的文件路径拆成 ``(核, 会话 id)``。不是备份布局就返回 None。"""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if len(rel.parts) != 3:
        return None
    core = _CORE_DIRS.get(rel.parts[0])
    if core is None:
        return None
    return core, rel.parts[1]


def count_sessions(root: Path) -> int:
    """语料里有多少场会话——报给用户看"这一趟翻了多大的堆"。"""
    total = 0
    for core_dir in _CORE_DIRS:
        path = root / core_dir
        if not path.is_dir():
            continue
        try:
            with os.scandir(path) as entries:
                total += sum(1 for e in entries if e.is_dir())
        except OSError as exc:
            logger.debug("session count failed for %s: %s", path, exc)
    return total


# ── 命中会话的元数据 ────────────────────────────────────────────────
def _opencode_titles(session_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """命中的 opencode 会话叫什么、在哪个目录跑的。

    片段本身不带这两样，只有会话库的 ``session`` 表有。这里只为命中的那几场查
    一次，查不到（库不在、或这场已从库里滚掉）就留空，NEVER 因此让检索失败。
    """
    if not session_ids:
        return {}
    try:
        from frago.session.opencode_store import _connect

        conn = _connect()
    except Exception as exc:  # noqa: BLE001 - 元数据可有可无，不该拖垮检索
        logger.debug("opencode metadata lookup failed: %s", exc)
        return {}
    if conn is None:
        return {}
    try:
        placeholders = ",".join("?" * len(session_ids))
        rows = conn.execute(
            f"SELECT id, title, directory FROM session WHERE id IN ({placeholders})",  # noqa: S608
            tuple(session_ids),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.debug("opencode metadata query failed: %s", exc)
        return {}
    finally:
        conn.close()
    return {
        str(sid): (
            title if isinstance(title, str) and title else None,
            directory if isinstance(directory, str) and directory else None,
        )
        for sid, title, directory in rows
    }


def _resume_command(core: str, session_id: str) -> str:
    return f"opencode -s {session_id}" if core == "opencode" else f"claude --resume {session_id}"


# ── 搜索 ────────────────────────────────────────────────────────────
@dataclass
class _Candidate:
    """一场会话在这轮检索里攒下的东西。两代文件的命中合并在这里。"""

    core: str
    session_id: str
    files: dict[Path, dict[str, set[int]]] = field(default_factory=dict)

    @property
    def matched_terms(self) -> list[str]:
        terms: set[str] = set()
        for term_lines in self.files.values():
            terms.update(term_lines)
        return sorted(terms)

    @property
    def hit_lines(self) -> int:
        return sum(len({ln for lines in tl.values() for ln in lines}) for tl in self.files.values())

    @property
    def capped(self) -> bool:
        return any(
            len({ln for lines in tl.values() for ln in lines}) >= RG_MAX_LINES_PER_FILE
            for tl in self.files.values()
        )

    @property
    def primary(self) -> Path:
        """代表这场会话的文件：有原文副本就用原文，没有才退到加工副本。"""
        for path in self.files:
            if path.name == RAW_FILENAME:
                return path
        return next(iter(self.files))


def search_backup(
    terms: list[str],
    *,
    since_ts: float | None = None,
    top: int = 10,
    root: Path | None = None,
) -> tuple[list[SessionHit], int, list[str]]:
    """在会话备份里搜这批关键词。返回 ``(命中, 语料里的会话数, 告警)``。

    顺序是**先扫后筛**：ripgrep 一趟扫完整棵树，再只对命中的那几个文件去取时间、
    标题、上下文。反过来（先按时间筛出文件再扫）要把上万个文件挨个打开读时间，
    为了一个可能根本没人给的 ``--days`` 付全量代价。
    """
    warnings: list[str] = []
    if shutil.which("rg") is None:
        return [], 0, ["ripgrep (rg) 不在 PATH 上，检索没跑"]

    corpus = root or backup_root()
    if not corpus.is_dir():
        return [], 0, [f"会话备份目录不在：{corpus}"]

    scanned = count_sessions(corpus)
    per_file, ok = _run_rg(terms, corpus)
    if not ok:
        return [], scanned, ["ripgrep 跑失败了，这一趟没有结果"]

    # 同一场会话的两代文件合并成一个候选。
    candidates: dict[tuple[str, str], _Candidate] = {}
    for path_text, term_lines in per_file.items():
        path = Path(path_text)
        split = _split_location(corpus, path)
        if split is None:
            continue
        core, session_id = split
        candidate = candidates.setdefault(
            (core, session_id), _Candidate(core=core, session_id=session_id)
        )
        candidate.files[path] = term_lines

    ranked = sorted(
        candidates.values(),
        key=lambda c: (len(c.matched_terms), c.hit_lines),
        reverse=True,
    )

    # 时间只对命中的会话取，且要在 top 截断之前算——它是排序的第三优先级，
    # 也是 --days 的依据。
    undated = 0
    dated: list[tuple[_Candidate, float]] = []
    for candidate in ranked:
        moment = last_activity_of(candidate.primary)
        if since_ts is not None:
            if moment is None:
                undated += 1
                continue
            if moment < since_ts:
                continue
        dated.append((candidate, moment or 0.0))

    if undated:
        warnings.append(
            f"{undated} 场命中的会话文件里没有任何时间戳（多为只有元数据记录的空壳会话），"
            f"给了 --days 就无从判断，已排除"
        )

    dated.sort(key=lambda pair: (len(pair[0].matched_terms), pair[0].hit_lines, pair[1]), reverse=True)
    chosen = dated[:top]

    opencode_meta = _opencode_titles(
        [c.session_id for c, _ in chosen if c.core == "opencode"]
    )

    hits: list[SessionHit] = []
    degraded_count = 0
    for candidate, moment in chosen:
        primary = candidate.primary
        degraded = primary.name != RAW_FILENAME
        if degraded:
            degraded_count += 1

        title: str | None = None
        cwd: str | None = None
        if candidate.core == "opencode":
            title, cwd = opencode_meta.get(candidate.session_id, (None, None))
        elif not degraded:
            # 原文副本与 Claude 的转录逐字节相同，标题和工作目录就在记录里。
            data = _scan_file(primary) or {}
            title = data.get("custom_title") or data.get("ai_title") or data.get("slug")
            cwd = data.get("cwd")

        hits.append(
            SessionHit(
                source=candidate.core,
                session_id=candidate.session_id,
                title=title,
                cwd=cwd,
                last_activity=moment,
                matched_terms=candidate.matched_terms,
                hit_lines=candidate.hit_lines,
                location=str(primary),
                resume_command=_resume_command(candidate.core, candidate.session_id),
                capped=candidate.capped,
                degraded=degraded,
                snippets=_collect_snippets(primary, candidate.files[primary]),
            )
        )

    if degraded_count:
        warnings.append(
            f"{degraded_count} 场只剩早期的加工副本（原文已随 Claude 的滚动删除消失），"
            f"工具返回值等内容不在里面——在这几场里搜不到 NEVER 等于那件事没发生过"
        )

    return hits, scanned, warnings


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
    root: Path | None = None,
) -> SearchResult:
    """一句话 → 关键词 → 扫遍会话备份 → 排序。

    ``terms`` 显式给出时跳过模型扩展；``expand=False`` 则直接用原句切词。
    """
    started = time.time()
    corpus = root or backup_root()

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
            corpus_root=str(corpus),
            scanned_sessions=0,
            duration_ms=int((time.time() - started) * 1000),
            warnings=["没有可用的关键词——原句里全是过短或过于通用的词"],
        )

    since_ts = time.time() - days * 86400 if days else None
    hits, scanned, warnings = search_backup(plan.terms, since_ts=since_ts, top=top, root=corpus)

    return SearchResult(
        query=query,
        plan=plan,
        hits=hits,
        corpus_root=str(corpus),
        scanned_sessions=scanned,
        duration_ms=int((time.time() - started) * 1000),
        warnings=warnings,
    )
