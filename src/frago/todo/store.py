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

# ── Vocabularies ────────────────────────────────────────────────────────

STATUSES = ("todo", "doing", "done", "dropped")
PRIORITIES = ("low", "normal", "high")
_ACTIVE = ("todo", "doing")
# next/list sort priority by semantic order (NOT lexical — high>normal>low)
_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}

# Self-describing schema, surfaced by `frago todo schema` so an agent knows
# the structure without reading source.
TODO_SCHEMA = {
    "filename": "<YYYYMMDD>-<slug>.json under ~/.frago/todo/ (FRAGO_TODO_DIR overrides)",
    "sort": "priority(high>normal>low) then created(asc); `next` picks first active (todo/doing)",
    "fields": [
        {"name": "id", "type": "string", "auto": True,
         "description": "filename without .json; reference handle (prefix-resolvable)"},
        {"name": "title", "type": "string", "required": True,
         "description": "one-line title; source of the slug"},
        {"name": "summary", "type": "string|null", "description": "shorter summary"},
        {"name": "status", "type": "enum", "enum": list(STATUSES), "default": "todo"},
        {"name": "priority", "type": "enum", "enum": list(PRIORITIES), "default": "normal"},
        {"name": "tags", "type": "list[str]", "default": []},
        {"name": "created", "type": "date", "auto": True, "description": "ISO date, set on add"},
        {"name": "updated", "type": "date", "auto": True, "description": "ISO date, refreshed on edit"},
        {"name": "done_at", "type": "date|null", "auto": True, "description": "stamped when status->done"},
        {"name": "context", "type": "string|null", "description": "background / why"},
        {"name": "steps", "type": "list[str]", "default": [], "description": "implementation steps"},
        {"name": "done_when", "type": "list[str]", "default": [], "description": "completion conditions"},
        {"name": "links", "type": "list[str]", "default": [], "description": "related urls"},
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
    created: str = ""
    updated: str = ""
    done_at: str | None = None
    context: str | None = None
    steps: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


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


def add(
    title: str,
    *,
    summary: str | None = None,
    priority: str = "normal",
    status: str = "todo",
    tags: list[str] | None = None,
    context: str | None = None,
    steps: list[str] | None = None,
    done_when: list[str] | None = None,
    links: list[str] | None = None,
) -> Todo:
    """Create a new todo file and return the :class:`Todo`."""
    if not title or not title.strip():
        raise ValueError("title is required")
    if priority not in PRIORITIES:
        raise ValueError(f"invalid priority {priority!r}; must be one of {PRIORITIES}")
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}; must be one of {STATUSES}")

    today = _today()
    todo = Todo(
        id=_make_id(title),
        title=title.strip(),
        summary=summary,
        status=status,
        priority=priority,
        tags=list(tags or []),
        created=today,
        updated=today,
        done_at=today if status == "done" else None,
        context=context,
        steps=list(steps or []),
        done_when=list(done_when or []),
        links=list(links or []),
    )
    _write(todo)
    return todo


def list_todos(
    *, status: str | None = None, priority: str | None = None, tag: str | None = None
) -> list[Todo]:
    """List todos, optionally filtered, sorted by (priority, created, id).

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

    todos.sort(key=lambda t: (_PRIORITY_ORDER.get(t.priority, 1), t.created, t.id))
    return todos


def get(ref: str) -> Todo:
    """Load a single todo by id or unique prefix."""
    return _load_file(_path_for(resolve_id(ref)))


_EDITABLE = {"title", "summary", "status", "priority", "tags", "context", "steps", "done_when", "links"}


def update(ref: str, **changes) -> Todo:
    """Apply field changes (None values are ignored), refresh ``updated``.

    Setting ``status`` to ``done`` stamps ``done_at`` if not already set.
    """
    todo = get(ref)
    for key, value in changes.items():
        if value is None:
            continue
        if key not in _EDITABLE:
            raise ValueError(f"field not editable: {key}")
        if key == "status" and value not in STATUSES:
            raise ValueError(f"invalid status {value!r}; must be one of {STATUSES}")
        if key == "priority" and value not in PRIORITIES:
            raise ValueError(f"invalid priority {value!r}; must be one of {PRIORITIES}")
        setattr(todo, key, value)

    todo.updated = _today()
    if changes.get("status") == "done" and not todo.done_at:
        todo.done_at = _today()
    _write(todo)
    return todo


def mark_done(ref: str) -> Todo:
    """Mark a todo done (idempotent — keeps the original ``done_at``)."""
    todo = get(ref)
    if todo.status == "done":
        return todo
    todo.status = "done"
    todo.done_at = _today()
    todo.updated = _today()
    _write(todo)
    return todo


def remove(ref: str) -> str:
    """Delete a todo file; return the resolved id."""
    todo_id = resolve_id(ref)
    _path_for(todo_id).unlink()
    return todo_id


def next_todo() -> Todo | None:
    """Return the most urgent active todo (highest priority, oldest), or None."""
    active = [t for t in list_todos() if t.status in _ACTIVE]
    return active[0] if active else None
