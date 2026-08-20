"""在会话内容里找一句话（左栏搜索框背后的那件事）。

## 解决什么问题

左栏的搜索框从前只认标题、目录和会话编号。可人记得住的往往不是这三样，而是**当时
说过的那句话**——"我让它把飞书 chat id 那个 bug 修一下的那场"。标题是模型起的，
未必提到飞书；目录一模一样的会话有上百场。于是搜索框在最该用上的时候用不上。

所以这个模块搜的是**会话里的话**：人打进去的提示词，与 agent 回复的正文。这两样
就是对话本身，其余（工具参数、工具输出、hook 注入、引擎记账）一律不算——它们体量
是对话的几十倍，掺进来的结果人一条都认不出是自己要的。

## 三步，一步都不能省

1. **ripgrep 先圈出可能命中的行。** 语料 3.2 GB、一千三百多个文件，逐行解析一遍是
   分钟量级，而 ripgrep 一趟两三秒就能给出"哪个文件的哪几行里有这个字面量"。
2. **只解析那几行。** 圈出来的行往往只占文件的万分之几。整场翻一遍最大的那个文件
   要 0.14 秒，只翻命中的十几行是毫秒量级。
3. **按判据表归类，再筛出对话那两类。** 顶着 ``user`` 标记的记录里 86% 不是人说的
   话，直接拿原始类型当发言人会把五万条工具结果全算成提示词。归类交给
   :mod:`~frago.session.adapters.claude_code_records` 的判据表，这里 NEVER 另写一套。

第 3 步同时也是**精确性**的来源：ripgrep 命中的是整行 JSON，工具输出里出现这个词
也会命中；翻成统一记录后只留 ``user.say`` 与 ``agent.say``，再确认那个词确实出现在
正文里，命中才作数。

## 没有 ripgrep 的时候

退回逐文件逐行扫，从最近动过的文件开始，扫到上限就停，并**在结果里明写这次只扫了
多少个文件**。NEVER 让"扫到这里就不扫了"看起来像"总共就这些"。

分层：核心数据层，NEVER import ``server/`` 或 ``cli/``。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from frago.session import codex_store, opencode_store
from frago.session.adapters.claude_code_records import translate_records
from frago.session.adapters.codex_records import (
    translate_session as codex_translate_session,
)
from frago.session.adapters.opencode_records import translate_session
from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.unified_record import RecordFamily, UnifiedRecord

__all__ = [
    "DIALOGUE_KINDS",
    "ContentHit",
    "SearchOutcome",
    "SessionMatch",
    "search_sessions",
]

logger = logging.getLogger(__name__)

DIALOGUE_KINDS = frozenset({"user.say", "agent.say"})
"""算作"对话"的两种形态：人打进去的提示词、agent 回复的正文。

工具调用、工具结果、hook 注入、引擎记账都不算。它们体量是对话的几十倍，掺进来的
结果人一条都认不出是自己要的。"""

# 一个文件里最多认多少个命中行。够排序也够出摘要，又不至于让一场巨型会话把整趟检索
# 拖住。触顶的会话在结果里标出来。
_MAX_LINES_PER_FILE = 200

# 没有 ripgrep 时最多亲手扫多少个文件。从最近动过的开始扫，扫到这里就停并报数。
_FALLBACK_MAX_FILES = 200

# 摘要在卡片上只占一两行：命中处前后各留这么多字。
_SNIPPET_PAD = 48

_MIN_QUERY_CHARS = 2


@dataclass(frozen=True)
class ContentHit:
    """一场会话里命中的一条对话记录。"""

    record_id: str
    kind: str
    """``user.say`` 或 ``agent.say``。"""

    ts: int
    """毫秒时间戳。"""

    snippet: str
    """命中处前后各留一小段的摘要，空白已压平。"""


@dataclass(frozen=True)
class SessionMatch:
    """一场会话的命中情况。"""

    session_id: str
    family: RecordFamily
    hit_count: int
    """命中了多少条对话记录（不是命中了多少次）。"""

    hits: list[ContentHit] = field(default_factory=list)
    """摘要，最多 ``per_session`` 条，按时刻从早到晚。"""

    capped: bool = False
    """这场会话的命中行数触了上限，报出来的不是全部。"""


@dataclass(frozen=True)
class SearchOutcome:
    """一趟检索的全部产出，含没做到的部分。"""

    query: str
    matches: list[SessionMatch] = field(default_factory=list)
    scanned_files: int = 0
    """真去解析过的文件数。"""

    warnings: list[str] = field(default_factory=list)
    """这趟没做全的地方。NEVER 空着——做不全却不说，等于谎报覆盖面。"""


# ── 词与摘要 ────────────────────────────────────────────────────────
def split_terms(query: str) -> list[str]:
    """一句话 → 一组字面量，按空白切开、去重、全部转小写。

    多个词是**并且**的关系，而且要落在**同一条**记录里：人打"飞书 chat id"，要找的
    是那句同时提到这三样的话，不是三个词各自出现在会话不同角落的一百场会话。
    """
    seen: list[str] = []
    for piece in query.lower().split():
        if piece and piece not in seen:
            seen.append(piece)
    return seen


def _snippet(text: str, terms: list[str]) -> str | None:
    """正文里命中处的前后一小段。**少一个词就返回 None。**

    ripgrep 命中的是整行 JSON，工具输出、hook 注入里出现这个词也会命中。这一步是把
    它们筛掉的地方——NEVER 因为"这一行里有"就断言"这句话里有"。
    """
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms]
    if any(at < 0 for at in positions):
        return None
    anchor = min(positions)
    width = len(terms[positions.index(anchor)])
    start = max(0, anchor - _SNIPPET_PAD)
    end = min(len(text), anchor + width + _SNIPPET_PAD)
    piece = " ".join(text[start:end].split())
    return ("…" if start else "") + piece + ("…" if end < len(text) else "")


def _distinct(hits: list[ContentHit], limit: int) -> list[ContentHit]:
    """摘要去重后取前几条。

    会话里有大量逐字重复的话——系统按来源投递的固定开场白、反复重发的模板消息，一场
    里能出现上百条一模一样的。照直取前两条，卡片上就是同一句话摆两遍，那一格等于白占。
    **条数不去重**：命中了多少条就是多少条，去重只发生在"摆出来给人看"这一步。
    """
    seen: set[str] = set()
    picked: list[ContentHit] = []
    for hit in hits:
        if hit.snippet in seen:
            continue
        seen.add(hit.snippet)
        picked.append(hit)
        if len(picked) >= limit:
            break
    return picked


def _hit_of(record: UnifiedRecord, terms: list[str]) -> ContentHit | None:
    """一条统一记录 → 一个命中。不是对话、或正文里缺词时返回 None。"""
    if record.kind not in DIALOGUE_KINDS:
        return None
    text = record.payload.get("text")
    if not isinstance(text, str) or not text:
        return None
    snippet = _snippet(text, terms)
    if snippet is None:
        return None
    return ContentHit(record_id=record.id, kind=record.kind, ts=record.ts, snippet=snippet)


# ── ripgrep ─────────────────────────────────────────────────────────
# 两趟，各解决一件事。
#
# **第一趟点名。** 每个词各扫一遍，只问"哪些文件里有、各有多少条命中行"（``-c``）。
# 输出一个文件一行，读回来是毫秒量级。它给出两样东西：同时含有全部词的文件（取交集），
# 以及哪个词最罕见。
#
# **第二趟定位。** 只拿最罕见的那个词、只在上一趟圈出的文件里，问"具体是哪几行"。
#
# 为什么不能一趟按词全要行号：``id`` 这种词在 3.2 GB 的 JSON 里命中 280 万处，ripgrep
# 吐得飞快（0.85 秒），可这边把 280 万行输出读进来要十几秒——瓶颈从来不在扫，在读回来。
# 分两趟之后，读回来的量由最罕见的那个词决定。
#
# 只用一个词定位不影响对不对：其余的词到记录正文里逐条核对（见 :func:`_snippet`），
# 选谁只影响多解析几个文件。
_RG_BASE = (
    "rg",
    "--null",  # 文件名后跟 NUL，路径里有冒号也不会切错
    "--fixed-strings",  # 搜的是字面量，里面的 . ( + 不当正则解释
    "--ignore-case",
    "--no-messages",
    "--no-config",
    "--no-ignore",
    "--glob",
    "*.jsonl",
)

# 第二趟最多把多少个文件路径直接摆到命令行上。超过就改成扫整棵树再按名单过滤——
# 命令行长度有上限，撑爆了 ripgrep 根本起不来。
_MAX_PATH_ARGS = 1000


def _run_rg(args: list[str]) -> str | None:
    """跑一趟 ripgrep，返回标准输出。跑不成返回 None，让调用方退回自己扫。"""
    if shutil.which("rg") is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - 参数全部由本模块构造
            [*_RG_BASE, *args], capture_output=True, text=True, errors="replace", check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("ripgrep invocation failed: %s", exc)
        return None
    # 0=有命中，1=无命中，都是正常结果；2 才是真出错。
    if proc.returncode not in (0, 1):
        logger.debug("ripgrep exited %s: %s", proc.returncode, proc.stderr[:400])
        return None
    return proc.stdout


def _rg_file_census(term: str, root: Path) -> dict[Path, int] | None:
    """第一趟：``{含有这个词的文件: 命中行数}``。"""
    out = _run_rg(["--count", "-e", term, str(root)])
    if out is None:
        return None
    census: dict[Path, int] = {}
    for raw in out.splitlines():
        path_text, sep, count_text = raw.partition("\0")
        if not sep or not count_text.isdigit():
            continue
        census[Path(path_text)] = int(count_text)
    return census


def _rg_line_numbers(term: str, targets: list[Path], root: Path) -> dict[Path, list[int]] | None:
    """第二趟：``{会话文件: 含有这个词的行号}``，只看 ``targets`` 这些文件。"""
    keep = set(targets)
    where = (
        [str(path) for path in targets] if len(targets) <= _MAX_PATH_ARGS else [str(root)]
    )
    out = _run_rg(
        [
            "--no-heading",
            "--with-filename",
            "--line-number",
            "--only-matching",  # 只吐命中的那一小段，NEVER 吐几万字符的整行
            "--max-count",
            str(_MAX_LINES_PER_FILE),
            "-e",
            term,
            *where,
        ]
    )
    if out is None:
        return None
    per_file: dict[Path, list[int]] = {}
    for raw in out.splitlines():
        path_text, sep, rest = raw.partition("\0")
        if not sep:
            continue
        lineno_text, sep2, _ = rest.partition(":")
        if not sep2 or not lineno_text.isdigit():
            continue
        path = Path(path_text)
        if path not in keep:
            continue
        lines = per_file.setdefault(path, [])
        lineno = int(lineno_text)
        if not lines or lines[-1] != lineno:
            lines.append(lineno)
    return per_file


def _rg_candidates(terms: list[str], root: Path) -> dict[Path, list[int]] | None:
    """两趟合起来：``{会话文件: 要解析的行号}``。ripgrep 用不了时返回 None。"""
    census: dict[str, dict[Path, int]] = {}
    for term in terms:
        counted = _rg_file_census(term, root)
        if counted is None:
            return None
        if not counted:
            return {}  # 有一个词一个文件都没命中，"并且"就不可能成立
        census[term] = counted

    common: set[Path] | None = None
    for counted in census.values():
        files = set(counted)
        common = files if common is None else (common & files)
    if not common:
        return {}

    # 在圈定的文件里命中行数最少的那个词，第二趟就用它。
    rarest = min(terms, key=lambda t: sum(census[t][path] for path in common))
    return _rg_line_numbers(rarest, sorted(common), root)


# ── Claude Code 那一侧 ──────────────────────────────────────────────
def _parse_lines(path: Path, wanted: list[int] | None) -> list[dict]:
    """把文件里指定行号的那几行解析出来。``wanted`` 为 None 时整个文件都读。

    行号是 ripgrep 给的，从 1 起。解不开的行直接跳过——这里不是翻译层，不需要为一行
    坏 JSON 留占位。
    """
    targets = set(wanted) if wanted is not None else None
    rows: list[dict] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for lineno, line in enumerate(handle, start=1):
                if targets is not None and lineno not in targets:
                    continue
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except (ValueError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
                if targets is not None and len(rows) >= len(targets):
                    break
    except OSError as exc:
        logger.debug("read failed for %s: %s", path, exc)
    return rows


def _match_of_file(
    path: Path, terms: list[str], wanted: list[int] | None, per_session: int
) -> SessionMatch | None:
    """一个会话文件 → 它的命中情况。一条对话都没命中时返回 None。

    命中的那几行各自单独翻。**这几种形态的归类只看这一行本身**（人说的话、agent 的
    回复正文、工具结果、伪消息、打断，判据全在行内），所以单行翻的结果与整场翻一遍
    一模一样，而代价小了三四个数量级。
    """
    rows = _parse_lines(path, wanted)
    if not rows:
        return None
    hits: list[ContentHit] = []
    for row in rows:
        for record in translate_records([row], path.stem):
            hit = _hit_of(record, terms)
            if hit is not None:
                hits.append(hit)
    if not hits:
        return None
    hits.sort(key=lambda hit: hit.ts)
    return SessionMatch(
        session_id=path.stem,
        family="claude-code",
        hit_count=len(hits),
        hits=_distinct(hits, per_session),
        capped=wanted is not None and len(wanted) >= _MAX_LINES_PER_FILE,
    )


def _claude_candidates(
    terms: list[str], root: Path
) -> tuple[list[tuple[Path, list[int] | None]], list[str]]:
    """要去解析的文件，以及各自要看哪几行。附一份"这趟哪里没做全"的说明。

    从最近动过的文件开始排——搜的人多半在找最近那场，而这个顺序决定了退回自己扫时
    先扫哪些。
    """
    warnings: list[str] = []
    by_line = _rg_candidates(terms, root)
    if by_line is not None:
        pairs = [(path, lines) for path, lines in by_line.items() if lines]
        pairs.sort(key=lambda item: _mtime(item[0]), reverse=True)
        return pairs, warnings

    warnings.append(
        f"ripgrep（rg）不在 PATH 上，这趟只亲手扫了最近动过的 {_FALLBACK_MAX_FILES} 个会话文件"
    )
    files = sorted(root.glob("*/*.jsonl"), key=_mtime, reverse=True)[:_FALLBACK_MAX_FILES]
    return [(path, None) for path in files], warnings


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ── opencode 那一侧 ─────────────────────────────────────────────────
def _opencode_matches(
    terms: list[str], per_session: int, limit: int
) -> tuple[list[SessionMatch], list[str]]:
    """opencode 那一家的命中。

    记录在 SQLite 里，没有"扫文件"这回事，粗筛交给库自己（``LIKE`` 一趟拿到可能命中
    的会话编号），命中的那几场才翻成统一记录。**不做粗筛就得整库全翻**——一场 6.6
    毫秒，几百场就是好几秒，每敲一个字都要等这么久。

    库读不出来时交白卷并报出来，NEVER 让整趟检索跟着失败，也 NEVER 静悄悄地当成"这
    一家没有命中"。
    """
    warnings: list[str] = []
    try:
        candidates = opencode_store.sessions_containing(terms)
    except Exception:  # noqa: BLE001 - 一家读不出不该拖垮另一家
        logger.debug("opencode store unavailable", exc_info=True)
        return [], ["opencode 会话库读不出来，这趟没搜它"]
    if candidates is None:
        return [], ["opencode 会话库读不出来，这趟没搜它"]

    matches: list[SessionMatch] = []
    for sid in sorted(candidates):
        if len(matches) >= limit:
            warnings.append(f"opencode 那侧命中超过 {limit} 场，只报了其中一部分")
            break
        try:
            records = translate_session(sid)
        except Exception:  # noqa: BLE001 - 逐场兜底
            logger.debug("opencode session %s unreadable", sid, exc_info=True)
            continue
        hits = [hit for hit in (_hit_of(r, terms) for r in records) if hit is not None]
        if not hits:
            continue
        hits.sort(key=lambda hit: hit.ts)
        matches.append(
            SessionMatch(
                session_id=sid,
                family="opencode",
                hit_count=len(hits),
                hits=_distinct(hits, per_session),
            )
        )
    return matches, warnings


# ── codex 那一侧 ────────────────────────────────────────────────────
def _codex_matches(
    terms: list[str], per_session: int, limit: int
) -> tuple[list[SessionMatch], list[str]]:
    """codex 那一家的命中。

    记录是 rollout JSONL，与 Claude Code 一样是文件，所以粗筛复用同一趟 ripgrep
    （``_rg_candidates``，它本来就只看 ``*.jsonl``）——只是圈出文件之后整场翻，不做
    Claude Code 那种"只翻命中的那几行"的优化：codex 的会话数量与体量都小得多，而
    整场翻能保住轮次分组，逐行翻会把它丢掉。

    没装 codex（``sessions/`` 不存在）时交白卷且**不报告警**——那不是"这趟没搜成"，
    是这台机器上根本没有这一家。ripgrep 不在时才报，因为那时确实漏搜了。
    """
    root = codex_store.sessions_root()
    if not root.is_dir():
        return [], []

    warnings: list[str] = []
    by_line = _rg_candidates(terms, root)
    if by_line is None:
        return [], ["ripgrep（rg）不在 PATH 上，这趟没搜 codex 的会话"]

    paths = sorted(
        (path for path, lines in by_line.items() if lines), key=_mtime, reverse=True
    )
    matches: list[SessionMatch] = []
    for path in paths:
        if len(matches) >= limit:
            warnings.append(f"codex 那侧命中超过 {limit} 场，只报了最近动过的这些")
            break
        meta = codex_store._read_meta(path)
        if meta is None:
            continue
        try:
            records = codex_translate_session(meta.session_id)
        except Exception:  # noqa: BLE001 - 逐场兜底，一场坏掉不拖垮整趟
            logger.debug("codex session %s unreadable", meta.session_id, exc_info=True)
            continue
        hits = [hit for hit in (_hit_of(r, terms) for r in records) if hit is not None]
        if not hits:
            continue
        hits.sort(key=lambda hit: hit.ts)
        matches.append(
            SessionMatch(
                session_id=meta.session_id,
                family="codex",
                hit_count=len(hits),
                hits=_distinct(hits, per_session),
            )
        )
    return matches, warnings


# ── 对外入口 ────────────────────────────────────────────────────────
def search_sessions(
    query: str,
    *,
    limit: int = 60,
    per_session: int = 2,
    projects_root: Path | None = None,
) -> SearchOutcome:
    """在三家的会话内容里找 ``query``，只认提示词与 agent 回复正文。

    ``limit`` 是**最多报几场**，按最近动过的顺序取，取满就停并在告警里说明。
    ``per_session`` 是每场最多附几条摘要。

    查询太短（少于两个字）时直接交白卷：一个字能命中几乎所有会话，报出来也没用。
    """
    terms = split_terms(query)
    if not terms or sum(len(term) for term in terms) < _MIN_QUERY_CHARS:
        return SearchOutcome(query=query, warnings=["搜的字太短了，至少要两个字"])

    root = projects_root or CLAUDE_PROJECTS_DIR
    matches: list[SessionMatch] = []
    warnings: list[str] = []
    scanned = 0

    if root.is_dir():
        candidates, warnings = _claude_candidates(terms, root)
        started = time.monotonic()
        for path, wanted in candidates:
            if len(matches) >= limit:
                warnings.append(f"命中的会话超过 {limit} 场，只报了最近动过的这些")
                break
            scanned += 1
            match = _match_of_file(path, terms, wanted, per_session)
            if match is not None:
                matches.append(match)
        logger.debug(
            "content search %r: %d files in %.2fs", query, scanned, time.monotonic() - started
        )

    opencode, opencode_warnings = _opencode_matches(terms, per_session, limit)
    matches.extend(opencode)
    warnings.extend(opencode_warnings)

    codex, codex_warnings = _codex_matches(terms, per_session, limit)
    matches.extend(codex)
    warnings.extend(codex_warnings)
    return SearchOutcome(
        query=query, matches=matches, scanned_files=scanned, warnings=warnings
    )
