"""``data:<关键词>`` —— 把 ``~/.frago/data`` 下的一个工作目录摊开成上下文。

``~/.frago/data/<语义目录>/`` 是产出物的落点：一次调研的 research 笔记、一份
spec、一个 notebook 账本、几份中间数据。目录名带日期前缀、带限定词，agent
下次回来只记得其中一小段。

这里做三件事：按关键词模糊定位目录、列出目录里有什么、把索引型小文件的全文
直接吐出来。为什么是"小文件全文 + 大文件只列路径"：一次调用要让 agent 建立
起上下文（不能只给路径，那还得再多轮 Read），又不能把 7 万字的 research
笔记灌进会话（那会把预算烧光）。所以按体积分流，并且在输出里显式写清楚哪些
被留在了外面——NEVER 让截断看起来像"全部内容就这些"。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from frago.context.errors import ContextError
from frago.context.matcher import Candidate, match_names

DATA_ROOT = Path.home() / ".frago" / "data"

# 单个文件超过这个体积就只列路径，不吐全文。16 KB 中文约合 5 千字，
# 足够装下一份 spec 或 notebook 的正文，又不至于一份就把预算吃掉。
INLINE_MAX_BYTES = 16 * 1024

# 一次调用最多吐出的全文总量。超出后剩下的文件降级为"只列路径"。
TOTAL_INLINE_BUDGET = 64 * 1024

# 文件清单最多列多少条。超出时显式报"还有 N 个未列出"。
MAX_LISTED_FILES = 300

# 探测是否二进制时读取的头部字节数。
_SNIFF_BYTES = 4096

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

# 有这些后缀才考虑吐全文。没有后缀的文件（LICENSE、Makefile）也放行，
# 真正的二进制由零字节探测挡下。
_TEXT_SUFFIXES = frozenset(
    {
        "",
        ".cfg",
        ".csv",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".jsonl",
        ".log",
        ".md",
        ".py",
        ".rst",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsv",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)

# 索引型文件：先于其它文件吐全文。它们是目录的"入口"，读完就知道其余文件是干什么的。
_INDEX_NAMES = (
    "notebook.md",
    "readme.md",
    "index.md",
    "spec.md",
    "plan.md",
    "summary.md",
    "conclusion.md",
    "report.md",
)


@dataclass
class FileEntry:
    """目录里的一个文件。"""

    rel: str
    """相对目录根的路径。"""

    size: int
    mtime: float

    text: str | None = None
    """吐出的全文；只列路径时为 None。"""

    skip_reason: str | None = None
    """没吐全文的原因（体积 / 二进制 / 预算用尽 / 读不出来）。"""


@dataclass
class ContextResult:
    """一次成功解析的结果。"""

    ref: str
    """原始引用，如 ``data:cxmt-ipo``。"""

    path: Path
    """命中的目录绝对路径。"""

    matched_by: str
    """命中理由（来自匹配器的分层标签）。"""

    entries: list[FileEntry] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0
    omitted_from_listing: int = 0
    also_matched: list[Candidate] = field(default_factory=list)
    """同时命中但没被展开的其它候选，只报名字，供 agent 判断是否找错了。"""

    @property
    def inlined(self) -> list[FileEntry]:
        return [e for e in self.entries if e.text is not None]

    @property
    def inlined_bytes(self) -> int:
        return sum(len(e.text.encode("utf-8")) for e in self.inlined if e.text)


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _is_text(path: Path) -> bool:
    """后缀在白名单内，且头部没有零字节。"""
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return False
    try:
        with open(path, "rb") as fh:
            return b"\0" not in fh.read(_SNIFF_BYTES)
    except OSError:
        return False


def _index_rank(rel: str) -> int:
    """索引型文件排前面；其余按 len(_INDEX_NAMES) 并列。"""
    base = Path(rel).name.lower()
    return _INDEX_NAMES.index(base) if base in _INDEX_NAMES else len(_INDEX_NAMES)


def _walk(root: Path) -> list[FileEntry]:
    """递归收集文件，跳过依赖/缓存目录与隐藏目录。按相对路径排序。"""
    found: list[FileEntry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        )
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            full = Path(dirpath) / fname
            try:
                stat = full.stat()
            except OSError:
                continue
            found.append(
                FileEntry(
                    rel=str(full.relative_to(root)),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )
    return found


def _fill_inline_text(entries: list[FileEntry], root: Path) -> None:
    """按优先级给够格的文件填全文，其余标上没填的原因。

    优先级 ``(索引名次, 目录深度, 体积)``：入口文件最先，同级里浅的先、小的先。
    预算用尽后剩下的一律标注，NEVER 静默略过。
    """
    order = sorted(
        entries,
        key=lambda e: (_index_rank(e.rel), e.rel.count(os.sep), e.size, e.rel),
    )
    budget = TOTAL_INLINE_BUDGET
    for entry in order:
        if entry.size > INLINE_MAX_BYTES:
            entry.skip_reason = f"大文件（{_human_size(entry.size)}），按需自行 Read"
            continue
        if not _is_text(root / entry.rel):
            entry.skip_reason = "非文本"
            continue
        if entry.size > budget:
            entry.skip_reason = "本次全文预算已用尽，按需自行 Read"
            continue
        try:
            entry.text = (root / entry.rel).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            entry.skip_reason = f"读不出来：{exc.strerror or exc}"
            continue
        budget -= entry.size


def _list_dirs(root: Path) -> list[str]:
    try:
        return sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError as exc:
        raise ContextError(
            f"读不了 {root}：{exc.strerror or exc}",
            f"ls -la {root}",
        ) from exc


def _no_match_error(keyword: str, root: Path, names: list[str]) -> ContextError:
    """没命中时，把最接近的几个名字摆出来，省掉 agent 再 ls 一轮。"""
    import difflib

    near = difflib.get_close_matches(keyword.lower(), [n.lower() for n in names], n=5, cutoff=0.3)
    lines = [f"{root} 下没有名字匹配 {keyword!r} 的目录（共 {len(names)} 个目录）"]
    if near:
        lines.append("最接近的几个：" + "、".join(near))
    return ContextError(
        "\n".join(lines),
        f"ls {root}",
        "frago context data:<换个词>",
    )


def resolve_data(keyword: str, *, root: Path | None = None) -> ContextResult:
    """把 ``data:<keyword>`` 解析成一个目录的上下文。

    多个目录都够分时不擅自选：抛 :class:`ContextError`，把候选连同命中理由列出来，
    让调用方带更精确的词再来一次。唯一的例外是完全同名——目录名唯一，完全同名
    就不存在"选错"，此时展开它并把其余候选的名字附在结果里。
    """
    base = root or DATA_ROOT
    if not base.exists():
        raise ContextError(
            f"{base} 不存在",
            f"mkdir -p {base}",
        )
    if not base.is_dir():
        raise ContextError(f"{base} 不是目录", f"ls -la {base}")

    names = _list_dirs(base)
    if not names:
        raise ContextError(f"{base} 下一个目录都没有", f"ls -la {base}")

    candidates = match_names(keyword, names)
    if not candidates:
        raise _no_match_error(keyword, base, names)

    exact = [c for c in candidates if c.is_exact]
    if exact:
        chosen, others = exact[0], [c for c in candidates if c is not exact[0]]
    elif len(candidates) == 1:
        chosen, others = candidates[0], []
    else:
        raise ContextError(
            f"{keyword!r} 命中 {len(candidates)} 个目录，没有完全同名的，不替你选：\n"
            + "\n".join(
                f"  {c.name}  （{c.reason}，score {c.score}）" for c in candidates
            ),
            *[f"frago context data:{c.name}" for c in candidates[:5]],
        )

    target = base / chosen.name
    entries = _walk(target)
    total_files = len(entries)
    total_bytes = sum(e.size for e in entries)
    omitted = max(0, total_files - MAX_LISTED_FILES)
    entries = entries[:MAX_LISTED_FILES]
    _fill_inline_text(entries, target)

    return ContextResult(
        ref=f"data:{keyword}",
        path=target,
        matched_by=f"{chosen.reason}（score {chosen.score}）",
        entries=entries,
        total_files=total_files,
        total_bytes=total_bytes,
        omitted_from_listing=omitted,
        also_matched=others,
    )


def render(result: ContextResult) -> str:
    """把结果渲染成给 agent 读的纯文本。"""
    lines = [
        result.ref,
        f"→ {result.path}",
        f"命中方式：{result.matched_by}",
    ]
    if result.also_matched:
        lines.append(
            "同时匹配（未展开）：" + "、".join(c.name for c in result.also_matched)
        )

    lines.append("")
    lines.append(f"FILES ({result.total_files}，共 {_human_size(result.total_bytes)})")
    if not result.entries:
        lines.append("  (空目录)")
    width = max((len(e.rel) for e in result.entries), default=0)
    for entry in result.entries:
        stamp = datetime.fromtimestamp(entry.mtime).strftime("%m-%d %H:%M")
        note = f"  [{entry.skip_reason}]" if entry.skip_reason else ""
        lines.append(
            f"  {entry.rel:<{width}}  {_human_size(entry.size):>9}  {stamp}{note}"
        )
    if result.omitted_from_listing:
        lines.append(
            f"  ... 另有 {result.omitted_from_listing} 个文件未列出"
            f"（清单上限 {MAX_LISTED_FILES}），完整清单：ls -R {result.path}"
        )

    inlined = result.inlined
    lines.append("")
    lines.append(
        f"全文吐出 {len(inlined)}/{result.total_files} 个文件"
        f"（{_human_size(result.inlined_bytes)} / 共 {_human_size(result.total_bytes)}）。"
        "其余见上方清单，按需自行 Read。"
    )

    for entry in inlined:
        lines.append("")
        lines.append(f"--- {entry.rel} ---")
        lines.append((entry.text or "").rstrip())

    return "\n".join(lines)
