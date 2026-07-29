"""按关键词把一个根目录翻一遍，报告命中落在哪儿——三类，各自成段。

## 为什么不再吐全文

这条命令最初会把命中目录里的小文件整篇贴出来，想的是省掉 agent 再多轮 Read。
实测第一次真用就翻车：``data:lenovo`` 吐了十个文件、六万多字符，约合两万 token，
终端回显都装不下。而其中真正被需要的往往只有一两篇——剩下的是替调用方做了它没
要求的决定，还把它的预算花光了。

所以改成只报"命中在哪儿"：

- **目录命中** —— 名字匹配的目录。这通常就是"那件事"本身。
- **文件名命中** —— 名字匹配的文件。
- **可读内容命中** —— 正文里含关键词的文档，按命中次数从多到少排。

看完自己决定 Read 哪个。清单里路径都是全的。

## 内容命中为什么只按次数排

排在最前的未必是最有价值的：一份 ffmpeg 的文件拼接清单可以因为路径里带着关键词
而拿到上百次命中，而真正有内容的那篇笔记只有十次。曾经试图用密度、用路径特征给
工序中间产物降权——那些都是拍脑袋的规则，会以没人预料的方式误伤。

按次数排是**可解释**的：调用方看得懂这个序是怎么来的。而每条命中都带一行摘要，
噪音在摘要里自己暴露（``ile '/Users/…/G001.mp4'`` 一眼就是机器清单）。规则透明加
证据在场，比一个猜出来的聪明排序可靠。

## 可读的边界

内容检索只走人写的文档格式（见 :data:`READABLE_SUFFIXES`）。JSON、JSONL、HTML
这些机器格式排除在外——它们命中的多半是路径和标识符，不是内容。被排除的那些命中
数量会一并报出来，NEVER 让"没找"看起来像"找了没有"。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from frago.context.errors import ContextError
from frago.context.matcher import Candidate, match_names

# 人写的文档格式。内容检索只走这些。
READABLE_SUFFIXES = ("md", "markdown", "txt", "rst", "org", "yaml", "yml", "csv", "tsv")

# 机器格式。只统计数量、不列清单——命中多半落在路径和标识符上。
MACHINE_SUFFIXES = ("json", "jsonl", "html", "htm", "xml", "log", "sql", "ndjson")

# 各段最多列多少条，超出报数量。全盘搜索动辄上百命中，全列出来等于把上下文冲掉。
MAX_DIR_HITS = 15
MAX_FILE_HITS = 15
MAX_CONTENT_HITS = 20

# 摘要一行最多多少字符。rg 侧同时用它挡住超长行（机器文件一行可以有几万字符）。
SNIPPET_WIDTH = 200

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "venv",
    }
)


@dataclass
class DirHit:
    rel: str
    path: Path
    file_count: int
    total_bytes: int
    mtime: float
    reason: str
    score: int


@dataclass
class FileHit:
    rel: str
    size: int
    mtime: float
    reason: str
    score: int


@dataclass
class ContentHit:
    rel: str
    count: int
    """命中次数（总匹配数，不是匹配行数）。"""
    snippet: str


@dataclass
class SearchReport:
    ref: str
    root: Path
    keyword: str
    duration_ms: int = 0
    scanned_dirs: int = 0
    skipped_dirs: int = 0

    dir_hits: list[DirHit] = field(default_factory=list)
    file_hits: list[FileHit] = field(default_factory=list)
    content_hits: list[ContentHit] = field(default_factory=list)

    dir_total: int = 0
    file_total: int = 0
    content_total: int = 0
    machine_total: int = 0
    """机器格式里命中的文件数，只报数量不列清单。"""

    notes: list[str] = field(default_factory=list)
    """本次检索有哪一半没做成（如 ripgrep 不在），如实报出。"""

    @property
    def empty(self) -> bool:
        return not (self.dir_hits or self.file_hits or self.content_hits)


# ── 名字扫描 ────────────────────────────────────────────────────────
def walk_names(root: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]], int, int]:
    """一次遍历同时收集目录名与文件名。

    返回 ``(目录名表, 文件名表, 扫过的目录数, 跳过的目录数)``。同名的东西在树里
    可以出现多次，所以每个名字挂一串路径，全部保留——调用方要看见它们分别在哪儿。

    构建产物目录整棵跳过：它们不可能是任何人的上下文，而且体量足以让这趟慢一个
    数量级。跳过的数量一并返回并显示，NEVER 让"没扫"看起来像"扫了没有"。
    """
    dirs: dict[str, list[Path]] = {}
    files: dict[str, list[Path]] = {}
    scanned = 0
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        skipped += sum(1 for d in dirnames if d in _SKIP_DIRS)
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        here = Path(dirpath)
        for name in dirnames:
            scanned += 1
            dirs.setdefault(name, []).append(here / name)
        for name in filenames:
            files.setdefault(name, []).append(here / name)
    return dirs, files, scanned, skipped


def _dir_size(path: Path) -> tuple[int, int]:
    """目录下的文件数与总字节。构建产物目录同样跳过，与扫描口径保持一致。"""
    count = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            count += 1
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return count, total


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _name_hits(
    keyword: str, table: dict[str, list[Path]], root: Path, limit: int
) -> tuple[list[tuple[str, Path, Candidate]], int]:
    """名字表里够分的条目，按分数排序。返回 ``(前 limit 条, 总数)``。"""
    candidates = match_names(keyword, list(table))
    flat: list[tuple[str, Path, Candidate]] = []
    for cand in candidates:
        for path in table[cand.name]:
            flat.append((str(path.relative_to(root)), path, cand))
    flat.sort(key=lambda item: (-item[2].score, item[0]))
    return flat[:limit], len(flat)


# ── 内容检索 ────────────────────────────────────────────────────────
def _globs(suffixes: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for suffix in suffixes:
        out += ["--glob", f"*.{suffix}"]
    return out


def _rg(args: list[str]) -> str | None:
    """跑一次 ripgrep，返回 stdout。跑不成返回 None（NEVER 抛给调用方）。"""
    try:
        proc = subprocess.run(  # noqa: S603 - 参数全部由本模块构造
            ["rg", *args], capture_output=True, text=True, errors="replace", check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # 0=有命中，1=无命中；2 才是真出错。
    return proc.stdout if proc.returncode in (0, 1) else None


_RG_BASE = [
    "--ignore-case",
    "--no-messages",
    "--no-config",
    "--no-ignore",
    "--hidden",
]

# Rust 正则的元字符。摘要那一趟要在关键词两侧各取一段上下文，就不能再用
# --fixed-strings，只能自己把关键词转义干净。NEVER 用 Python 的 re.escape——
# 它会把空格、``-``、``~`` 这类也加上反斜杠，而 Rust 正则不认那些转义。
_RUST_REGEX_META = set(r".^$*+?()[]{}|\/")


def _escape_regex(text: str) -> str:
    return "".join(f"\\{ch}" if ch in _RUST_REGEX_META else ch for ch in text)


def _parse_null_pairs(out: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in out.splitlines():
        path, sep, rest = raw.partition("\0")
        if sep:
            pairs.append((path, rest))
    return pairs


def search_content(
    keyword: str, root: Path
) -> tuple[list[ContentHit], int, int, list[str]]:
    """内容检索。返回 ``(可读命中, 可读命中总数, 机器格式命中数, 提示)``。

    两趟 ripgrep：一趟数每个文件的命中次数，一趟取每个文件第一处命中所在的行做
    摘要。分两趟是因为数数和取文本要的输出形态不同，而每趟都是全树一遍、零点几秒。
    """
    notes: list[str] = []
    if shutil.which("rg") is None:
        return [], 0, 0, ["ripgrep (rg) 不在 PATH 上，内容这一段没搜"]

    counts_out = _rg(
        [
            *_RG_BASE,
            "--null",  # 路径后跟 NUL，路径里有冒号也不会切错
            "--fixed-strings",  # 数数这趟关键词是字面量，里面的 . ( + 不当正则解释
            "--count-matches",
            *_globs(READABLE_SUFFIXES),
            "-e",
            keyword,
            str(root),
        ]
    )
    if counts_out is None:
        return [], 0, 0, ["ripgrep 执行失败，内容这一段没搜"]

    counts: dict[str, int] = {}
    for path, rest in _parse_null_pairs(counts_out):
        value = rest.strip()
        if value.isdigit():
            counts[path] = int(value)

    # 摘要这趟取关键词两侧各一段上下文。用 --only-matching 加窗口正则，而不是打印
    # 整行再截断——中文文档一段就是一行，--max-columns 遇到长行会整行换成
    # "[Omitted long matching line]"，而摘要恰恰是判断这条命中是不是噪音的唯一证据。
    half = SNIPPET_WIDTH // 2
    window = f".{{0,{half}}}{_escape_regex(keyword)}.{{0,{half}}}"
    snippets: dict[str, str] = {}
    snip_out = _rg(
        [
            *_RG_BASE,
            "--null",
            "--only-matching",
            "--max-count",
            "1",
            "--no-heading",
            "--with-filename",
            *_globs(READABLE_SUFFIXES),
            "-e",
            window,
            str(root),
        ]
    )
    if snip_out is not None:
        for path, rest in _parse_null_pairs(snip_out):
            snippets.setdefault(path, " ".join(rest.split())[:SNIPPET_WIDTH])

    # 这趟 NEVER 加 --null：``-l --null`` 的输出是 NUL 分隔、不带换行，按行数
    # 数出来永远是 1。改回换行分隔，路径里带换行的情况本就不存在。
    machine_out = _rg(
        [
            *_RG_BASE,
            "--fixed-strings",
            "--files-with-matches",
            *_globs(MACHINE_SUFFIXES),
            "-e",
            keyword,
            str(root),
        ]
    )
    machine_total = len(machine_out.splitlines()) if machine_out else 0

    hits = [
        ContentHit(
            rel=str(Path(path).relative_to(root)),
            count=count,
            snippet=snippets.get(path, ""),
        )
        for path, count in counts.items()
    ]
    # 次数从多到少；同次数按路径排，保证结果稳定可复现。
    hits.sort(key=lambda h: (-h.count, h.rel))
    return hits[:MAX_CONTENT_HITS], len(hits), machine_total, notes


# ── 编排 ────────────────────────────────────────────────────────────
def search(keyword: str, root: Path, *, ref: str) -> SearchReport:
    """在 ``root`` 下按关键词找目录、文件名、可读内容三类命中。"""
    if not root.exists():
        raise ContextError(f"{root} 不存在", f"mkdir -p {root}")
    if not root.is_dir():
        raise ContextError(f"{root} 不是目录", f"ls -la {root}")

    started = time.time()
    dirs, files, scanned, skipped = walk_names(root)

    dir_raw, dir_total = _name_hits(keyword, dirs, root, MAX_DIR_HITS)
    file_raw, file_total = _name_hits(keyword, files, root, MAX_FILE_HITS)
    content_hits, content_total, machine_total, notes = search_content(keyword, root)

    dir_hits = []
    for rel, path, cand in dir_raw:
        count, total = _dir_size(path)
        dir_hits.append(
            DirHit(
                rel=rel,
                path=path,
                file_count=count,
                total_bytes=total,
                mtime=_mtime(path),
                reason=cand.reason,
                score=cand.score,
            )
        )

    file_hits = [
        FileHit(
            rel=rel,
            size=path.stat().st_size if path.exists() else 0,
            mtime=_mtime(path),
            reason=cand.reason,
            score=cand.score,
        )
        for rel, path, cand in file_raw
    ]

    return SearchReport(
        ref=ref,
        root=root,
        keyword=keyword,
        duration_ms=int((time.time() - started) * 1000),
        scanned_dirs=scanned,
        skipped_dirs=skipped,
        dir_hits=dir_hits,
        file_hits=file_hits,
        content_hits=content_hits,
        dir_total=dir_total,
        file_total=file_total,
        content_total=content_total,
        machine_total=machine_total,
        notes=notes,
    )


# ── 渲染 ────────────────────────────────────────────────────────────
def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _stamp(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M") if mtime else "-"


def render(report: SearchReport) -> str:
    lines = [
        report.ref,
        f"搜索范围 {report.root}（{report.scanned_dirs} 个目录，"
        f"跳过 {report.skipped_dirs} 个构建产物目录）｜耗时 {report.duration_ms / 1000:.1f} 秒",
    ]
    for note in report.notes:
        lines.append(f"[!] {note}")

    lines.append("")
    lines.append(f"── 目录命中 {report.dir_total} ──")
    if not report.dir_hits:
        lines.append("  （没有目录名匹配）")
    else:
        width = max(len(h.rel) for h in report.dir_hits)
        for hit in report.dir_hits:
            lines.append(
                f"  {hit.rel:<{width}}  {hit.file_count:>5} 文件  "
                f"{human_size(hit.total_bytes):>9}  {_stamp(hit.mtime)}  {hit.reason}"
            )
        if report.dir_total > len(report.dir_hits):
            lines.append(f"  ... 另有 {report.dir_total - len(report.dir_hits)} 个未列出")

    lines.append("")
    lines.append(f"── 文件名命中 {report.file_total} ──")
    if not report.file_hits:
        lines.append("  （没有文件名匹配）")
    else:
        width = max(len(h.rel) for h in report.file_hits)
        for hit in report.file_hits:
            lines.append(
                f"  {hit.rel:<{width}}  {human_size(hit.size):>9}  "
                f"{_stamp(hit.mtime)}  {hit.reason}"
            )
        if report.file_total > len(report.file_hits):
            lines.append(f"  ... 另有 {report.file_total - len(report.file_hits)} 个未列出")

    lines.append("")
    header = f"── 可读内容命中 {report.content_total} 个文件（按命中次数排） ──"
    lines.append(header)
    if report.machine_total:
        lines.append(
            f"  另有 {report.machine_total} 个机器格式文件（json / jsonl / html 等）也命中，"
            "未列出——那类命中多半落在路径和标识符上"
        )
    if not report.content_hits:
        lines.append("  （没有可读文档含这个词）")
    else:
        width = max(len(h.rel) for h in report.content_hits)
        for hit in report.content_hits:
            lines.append(f"  {hit.rel:<{width}}  {hit.count:>4} 处")
            if hit.snippet:
                lines.append(f"      {hit.snippet}")
        if report.content_total > len(report.content_hits):
            lines.append(
                f"  ... 另有 {report.content_total - len(report.content_hits)} 个未列出"
                f"（上限 {MAX_CONTENT_HITS}）"
            )

    if report.empty:
        lines.append("")
        lines.append(f"{report.keyword!r} 在 {report.root} 下没有任何命中。")

    return "\n".join(lines)
