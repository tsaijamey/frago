"""frago todo — local todo store.

One todo = one JSON file under ``~/.frago/todo/`` named
``<YYYYMMDD>-<slug>.json``, following a fixed :data:`TODO_SCHEMA`.

This is the storage layer only — it owns filename generation, schema,
sorting, prefix-id resolution and file CRUD. The CLI in
``cli/todo_commands.py`` is a thin wrapper over these functions (mirrors how
``frago def`` splits ``def_/registry.py`` from ``cli/def_commands.py``).

The todo directory defaults to ``~/.frago/todo/`` but honours the
``FRAGO_TODO_DIR`` environment variable so tests and manual verification can
run fully isolated from the real directory.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path

from slugify import slugify

from frago.todo import categories

# ── Vocabularies ────────────────────────────────────────────────────────

STATUSES = ("todo", "doing", "done", "dropped")
PRIORITIES = ("low", "normal", "high")
_ACTIVE = ("todo", "doing")
# 普通编辑路径（add / edit / log / done）改得动的那几档。
#
# 「弃置」不在里面：它是「这件不做了」的终态，进去必须说清为什么，所以只留 `drop`
# 那一条路（见 :func:`drop`）。放在这里随手可设，理由那一栏就永远是空的——一条没有
# 理由的弃置记录，跟直接删掉它区别不大。
_SETTABLE_STATUSES = ("todo", "doing", "done")
DROPPED = "dropped"
# next/list sort priority by semantic order (NOT lexical — high>normal>low)
_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}

# Self-describing schema, surfaced by `frago todo schema` so an agent knows
# the structure without reading source.
TODO_SCHEMA = {
    "filename": "<YYYYMMDD>-<slug>.json under ~/.frago/todo/ (FRAGO_TODO_DIR overrides)",
    "sort": "category (position in the category list; uncategorized or unknown id last) "
            "then priority(high>normal>low) then created(asc); "
            "`next` picks first active (todo/doing)",
    "fields": [
        {"name": "id", "type": "string", "auto": True,
         "description": "filename without .json; reference handle (prefix-resolvable)"},
        {"name": "title", "type": "string", "required": True,
         "description": "one-line title; source of the slug"},
        {"name": "summary", "type": "string|null", "description": "shorter summary"},
        {"name": "status", "type": "enum", "enum": list(STATUSES), "default": "todo",
         "description": "add/edit/log/done only set todo|doing|done; `dropped` is reachable "
                        "only through `frago todo drop <ref> --reason ...` and moving back "
                        "out of it clears drop_reason/dropped_at"},
        {"name": "priority", "type": "enum", "enum": list(PRIORITIES), "default": "normal"},
        {"name": "tags", "type": "list[str]", "default": []},
        {"name": "category", "type": "string|null", "default": None,
         "description": "category id from `frago todo category list` (config.json -> "
                        "todo_categories; defaults family/work/hobby/other). null = "
                        "uncategorized; an id no longer in the list sorts as uncategorized "
                        "but is kept"},
        {"name": "created", "type": "date", "auto": True, "description": "ISO date, set on add"},
        {"name": "updated", "type": "date", "auto": True, "description": "ISO date, refreshed on edit"},
        {"name": "done_at", "type": "date|null", "auto": True, "description": "stamped when status->done"},
        {"name": "dropped_at", "type": "date|null", "auto": True,
         "description": "stamped by `todo drop`; cleared if the todo comes back out of dropped"},
        {"name": "drop_reason", "type": "string|null", "auto": True,
         "description": "why it was dropped — `todo drop` requires it, verbatim; cleared "
                        "if the todo comes back out of dropped"},
        {"name": "context", "type": "string|null", "description": "background / why"},
        {"name": "steps", "type": "list[str]", "default": [], "description": "implementation steps"},
        {"name": "done_when", "type": "list[str]", "default": [], "description": "completion conditions"},
        {"name": "links", "type": "list[str]", "default": [], "description": "related urls"},
        {"name": "sessions", "type": "list[str]", "default": [],
         "description": "session ids this todo was worked in, oldest first; `add` records the "
                        "current one, `log` appends the next — the trail back to the raw "
                        "conversations (see `frago todo --how-to`)"},
    ],
}


@dataclass
class Todo:
    """A single todo. Field order mirrors the on-disk JSON layout."""

    id: str
    title: str
    summary: str | None = None
    status: str = "todo"
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    # 分类 id。旧事务文件没有这个键，读出来就是 None（未分类）。
    category: str | None = None
    created: str = ""
    updated: str = ""
    done_at: str | None = None
    # 弃置那一刻记下的日期与理由。旧事务文件里没有这两个键，读出来就是 None。
    dropped_at: str | None = None
    drop_reason: str | None = None
    context: str | None = None
    steps: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)


# ── Paths & ids ─────────────────────────────────────────────────────────


def todo_dir() -> Path:
    """Return the todo directory (creating it if needed).

    Honours ``FRAGO_TODO_DIR`` so callers can isolate from ``~/.frago/todo``.
    """
    base = os.environ.get("FRAGO_TODO_DIR")
    d = Path(base) if base else Path.home() / ".frago" / "todo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today() -> str:
    return date.today().isoformat()


def _path_for(todo_id: str) -> Path:
    return todo_dir() / f"{todo_id}.json"


SLUG_MAX_LENGTH = 32


def _make_id(title: str) -> str:
    """Build a unique ``<YYYYMMDD>-<slug>`` id from the title.

    Slug generation is delegated to ``python-slugify`` (already a project
    dependency). We keep the default ASCII transliteration (unidecode) rather
    than ``allow_unicode``: this is an open-source, internationalized tool, and
    ASCII filenames are portable across every locale and filesystem (a Japanese
    or Arabic title would otherwise produce script-specific filenames with
    cross-platform / git / archive pitfalls). Transliteration of non-Latin
    scripts is inherently lossy and unlovely (CJK -> pinyin, etc.), so we keep
    it SHORT via ``max_length`` + ``word_boundary`` instead of trying to make it
    pretty. The filename is only a handle — the real title lives in the JSON and
    is shown by ``list`` / ``show``. Empty slug (un-transliterable input)
    degrades to the bare date; uniqueness is preserved by the ``-N`` suffix.
    """
    stem = date.today().strftime("%Y%m%d")
    slug = slugify(title, max_length=SLUG_MAX_LENGTH, word_boundary=True, save_order=True)
    if slug:
        stem = f"{stem}-{slug}"
    candidate = stem
    n = 2
    while _path_for(candidate).exists():
        candidate = f"{stem}-{n}"
        n += 1
    return candidate


def resolve_id(ref: str) -> str:
    """Resolve a full id or unique prefix to a concrete todo id.

    Raises ``KeyError`` when nothing matches and ``ValueError`` when the prefix
    is ambiguous (listing the candidates) — we never silently pick one.
    """
    if _path_for(ref).exists():
        return ref
    matches = sorted(p.stem for p in todo_dir().glob("*.json") if p.stem.startswith(ref))
    if not matches:
        raise KeyError(f"no todo matching {ref!r}; run `frago todo list`")
    if len(matches) > 1:
        raise ValueError(f"ambiguous ref {ref!r} matches: {', '.join(matches)}")
    return matches[0]


# ── Serialization ───────────────────────────────────────────────────────


def _write(todo: Todo) -> None:
    _path_for(todo.id).write_text(
        json.dumps(asdict(todo), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_file(path: Path) -> Todo:
    """Load one todo, tolerating missing/extra keys.

    ``id`` is always derived from the filename (the filesystem is the source of
    truth for it). Unknown keys are dropped; missing optional keys fall back to
    dataclass defaults.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("todo file is not a JSON object")
    known = {f.name for f in fields(Todo)}
    data = {k: v for k, v in raw.items() if k in known}
    data["id"] = path.stem
    data.setdefault("title", path.stem)
    return Todo(**data)


# ── CRUD ────────────────────────────────────────────────────────────────


def _require_settable_status(status: str) -> None:
    """普通编辑路径只收待办/在做/已完成；弃置从这里进不去。

    报错里直接给出该走的那条命令。拒绝一个动作却不说替代路径，调用方（尤其是 agent）
    下一步就是把 STATUSES 里的词挨个试一遍。
    """
    if status not in _SETTABLE_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; must be one of {_SETTABLE_STATUSES}. "
            f"To drop a todo say why: `frago todo drop <ref> --reason \"...\"`"
        )


def _apply_status(todo: Todo, status: str) -> None:
    """走普通路径改状态，顺带把跟着状态走的那几个戳记对齐。

    从弃置回到别的档时清掉理由与日期：那两项是「这件不做了，因为……」的记录，事情
    重新开工之后还挂在那里，读的人会以为它仍然是被搁下的。
    """
    _require_settable_status(status)
    todo.status = status
    if status == "done" and not todo.done_at:
        todo.done_at = _today()
    todo.dropped_at = None
    todo.drop_reason = None


def add(
    title: str,
    *,
    summary: str | None = None,
    priority: str = "normal",
    status: str = "todo",
    tags: list[str] | None = None,
    category: str | None = None,
    context: str | None = None,
    steps: list[str] | None = None,
    done_when: list[str] | None = None,
    links: list[str] | None = None,
    sessions: list[str] | None = None,
) -> Todo:
    """Create a new todo file and return the :class:`Todo`."""
    if not title or not title.strip():
        raise ValueError("title is required")
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority {priority!r}; must be one of {PRIORITIES}")
    _require_settable_status(status)
    if category is not None:
        categories.require(category)

    today = _today()
    todo = Todo(
        id=_make_id(title),
        title=title.strip(),
        summary=summary,
        status=status,
        priority=priority,
        tags=list(tags or []),
        category=category,
        created=today,
        updated=today,
        done_at=today if status == "done" else None,
        context=context,
        steps=list(steps or []),
        done_when=list(done_when or []),
        links=list(links or []),
        sessions=_dedupe(sessions),
    )
    _write(todo)
    return todo


def _dedupe(values: list[str] | None) -> list[str]:
    """去重但保序——会话 id 的先后就是这件事的时间线，排序会把它抹平。"""
    out: list[str] = []
    for v in values or []:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


def list_todos(
    *,
    status: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
    category: str | None = None,
) -> list[Todo]:
    """List todos, optionally filtered, sorted by (category, priority, created, id).

    ``category`` filters by id; ``"none"`` keeps the uncategorized ones — including
    todos whose id has since been removed from the list, since that is how they sort
    and show everywhere else.

    Only ``*.json`` files are considered — legacy ``.md`` todos are ignored.
    Malformed files are skipped with a stderr warning, never aborting the list.
    """
    todos: list[Todo] = []
    for p in sorted(todo_dir().glob("*.json")):
        try:
            todos.append(_load_file(p))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"warning: skipping malformed todo {p.name}: {e}", file=sys.stderr)

    if status:
        todos = [t for t in todos if t.status == status]
    if priority:
        todos = [t for t in todos if t.priority == priority]
    if tag:
        todos = [t for t in todos if tag in t.tags]

    rank = category_rank()
    if category == categories.UNCATEGORIZED:
        todos = [t for t in todos if t.category not in rank]
    elif category:
        todos = [t for t in todos if t.category == category]

    todos.sort(key=lambda t: sort_key(t, rank))
    return todos


def category_rank() -> dict[str, int]:
    """分类 id → 在清单里的位置（0 起）。"""
    return {c.id: i for i, c in enumerate(categories.list_categories())}


def sort_key(todo: Todo, rank: dict[str, int]) -> tuple:
    """清单顺序：分类位置 → 高中低 → 建得早的在前。

    未分类、以及引用了已不在清单里的分类的，统一排在所有分类之后——分类被删了不
    代表那件事不做了，但也没有理由让它继续占着一个已经不存在的名次。
    """
    return (
        rank.get(todo.category, len(rank)),
        _PRIORITY_ORDER.get(todo.priority, 1),
        todo.created,
        todo.id,
    )


def get(ref: str) -> Todo:
    """Load a single todo by id or unique prefix."""
    return _load_file(_path_for(resolve_id(ref)))


_EDITABLE = {
    "title", "summary", "status", "priority", "tags", "category",
    "context", "steps", "done_when", "links", "sessions",
}


def update(ref: str, **changes) -> Todo:
    """Apply field changes (None values are ignored), refresh ``updated``.

    Setting ``status`` to ``done`` stamps ``done_at`` if not already set.
    ``category=""`` clears the category (None already means "leave it alone").
    ``status="dropped"`` is refused here — see :func:`drop`.
    """
    todo = get(ref)
    for key, value in changes.items():
        if value is None:
            continue
        if key not in _EDITABLE:
            raise ValueError(f"field not editable: {key}")
        if key == "status":
            # 弃置要带着理由一起落，这里没有地方放它，所以整条路不通。
            _require_settable_status(value)
        if key == "priority" and value not in PRIORITIES:
            raise ValueError(f"invalid priority {value!r}; must be one of {PRIORITIES}")
        if key == "category":
            if value == "":
                value = None
            else:
                categories.require(value)
        setattr(todo, key, value)

    todo.updated = _today()
    if changes.get("status") is not None:
        _apply_status(todo, changes["status"])
    _write(todo)
    return todo


def log(
    ref: str,
    entry: str,
    *,
    session_id: str | None = None,
    status: str | None = None,
) -> Todo:
    """把这一场会话的进展追加到 ``context`` 末尾，并把会话 id 记进 ``sessions``。

    长周期的事情不是一场会话做得完的：这次推进一半，下次换个 agent 接着推。若每次
    接手都重写 ``context``，上一手的判断就被抹掉了，接手的人只看得到最后的结论，看
    不到为什么走到这一步——而「为什么」恰恰是代码和 git 历史里查不到的那部分。所以
    这里只追加，NEVER 覆盖。

    每段前面压一行日期与会话 id，日后顺着这个 id 就能回到当时的原始对话。
    """
    if not entry or not entry.strip():
        raise ValueError("log entry is required")

    todo = get(ref)
    stamp = f"--- {_today()}"
    if session_id:
        stamp += f" · session {session_id}"
    stamp += " ---"
    block = f"{stamp}\n{entry.strip()}"

    todo.context = f"{todo.context.rstrip()}\n\n{block}" if todo.context else block
    if session_id:
        todo.sessions = _dedupe([*todo.sessions, session_id])
    if status is not None:
        _apply_status(todo, status)
    todo.updated = _today()
    _write(todo)
    return todo


def mark_done(ref: str) -> Todo:
    """Mark a todo done (idempotent — keeps the original ``done_at``)."""
    todo = get(ref)
    if todo.status == "done":
        return todo
    _apply_status(todo, "done")
    todo.done_at = _today()
    todo.updated = _today()
    _write(todo)
    return todo


def drop(ref: str, reason: str) -> Todo:
    """把一件事务弃置：这件不做了，并且把为什么留在案卷里。

    弃置与完成是两个不同的结局。已完成说明事情办到了；弃置说明它被主动放下——半年后
    有人翻到这条，第一个问题一定是「当初为什么不做了」。清单本身答不出这个问题：标题
    和背景写的是要做什么，不是放弃的判断。所以理由在这里是必填的，没有默认值、没有
    「未填写」这种占位。

    只有这一个函数能把状态改成弃置。新建、编辑、记进展那几条路径都收窄到了待办/在做/
    已完成（见 :data:`_SETTABLE_STATUSES`）——留一条不用给理由的旁路，理由那一栏迟早
    大半是空的。

    已经弃置过的不许再弃置一次：那不是重复执行同一个动作，而是对同一件事的第二次判断，
    静悄悄覆盖掉第一次的理由，等于把当初的决定抹了。这里报错并把原有的日期与理由说出来，
    让人自己决定要不要先把它拿回在做的档位。
    """
    text = (reason or "").strip()
    if not text:
        raise ValueError("a reason is required: say why this is being dropped")

    todo = get(ref)
    if todo.status == DROPPED:
        had = todo.drop_reason or "(no reason recorded)"
        raise ValueError(
            f"{todo.id} was already dropped on {todo.dropped_at or 'an unknown date'}: {had}"
        )

    todo.status = DROPPED
    todo.dropped_at = _today()
    todo.drop_reason = text
    todo.updated = _today()
    _write(todo)
    return todo


def remove(ref: str) -> str:
    """Delete a todo file; return the resolved id."""
    todo_id = resolve_id(ref)
    _path_for(todo_id).unlink()
    return todo_id


def categorize(assignments: dict[str, str | None]) -> tuple[list[tuple[Todo, str | None]], int]:
    """一次给一批事务定分类：全部校验通过才写，任何一条不对就整批不写。

    给定时任务里的 agent 用——它读完清单、一口气分好，一条命令交上来。只写了一半
    的批次最难收拾：agent 看到报错重来一遍，前一半已经改了、后一半没改，它分不清
    哪些是自己这次的结果。所以先把每一条都核一遍，把问题攒齐一次报出来，再动文件。

    ``assignments`` 是「事务 id（或唯一前缀）→ 分类 id」；分类 id 为 None 或
    ``"none"`` 表示清空。返回 ``([(改动后的事务, 原分类), ...], 没变的件数)``；
    校验失败抛 :class:`BatchError`，里面带着每一条问题。
    """
    current = categories.list_categories()
    valid = {c.id for c in current}
    problems: list[str] = []
    resolved: dict[str, str | None] = {}
    origin: dict[str, str] = {}

    for ref, category_id in assignments.items():
        if category_id is not None and not isinstance(category_id, str):
            problems.append(f"{ref}: category must be a string id or null, got {category_id!r}")
            continue
        if category_id == categories.UNCATEGORIZED:
            category_id = None
        try:
            todo_id = resolve_id(ref)
        except (KeyError, ValueError) as e:
            problems.append(f"{ref}: {e.args[0]}")
            todo_id = None
        if category_id is not None and category_id not in valid:
            problems.append(f"{ref}: unknown category {category_id!r}")
        if todo_id is None or (category_id is not None and category_id not in valid):
            continue
        if todo_id in resolved and resolved[todo_id] != category_id:
            problems.append(
                f"{ref}: same todo as {origin[todo_id]!r} ({todo_id}) but a different category"
            )
            continue
        resolved[todo_id] = category_id
        origin.setdefault(todo_id, ref)

    if problems:
        raise BatchError(problems, current)

    changed: list[tuple[Todo, str | None]] = []
    unchanged = 0
    for todo_id, category_id in resolved.items():
        todo = get(todo_id)
        if todo.category == category_id:
            unchanged += 1
            continue
        before = todo.category
        todo.category = category_id
        todo.updated = _today()
        _write(todo)
        changed.append((todo, before))
    return changed, unchanged


class BatchError(ValueError):
    """批量分类整批被拒。``problems`` 一条一句，``categories`` 是当时的可选项。"""

    def __init__(self, problems: list[str], current: list[categories.Category]):
        self.problems = problems
        self.categories = current
        super().__init__(f"{len(problems)} problem(s): " + "; ".join(problems))


def category_usage() -> dict[str, int]:
    """每个分类 id 被几件事务引用（含已不在清单里的 id）。"""
    usage: dict[str, int] = {}
    for todo in list_todos():
        if todo.category:
            usage[todo.category] = usage.get(todo.category, 0) + 1
    return usage


def next_todo() -> Todo | None:
    """Return the most urgent active todo (first in list order), or None."""
    active = [t for t in list_todos() if t.status in _ACTIVE]
    return active[0] if active else None
