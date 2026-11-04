"""frago employee — persistent store for `EmployeePostResource` (+R) and `DomainEmployeeRole` (~R) bindings.

One employee post = one JSON file under ``~/.frago/employees/<member_post_id>.json``
(``FRAGO_EMPLOYEES_DIR`` overrides for isolated tests).

Ontological separation in storage:
- **Rigid identity (`+R` `EmployeePostResource`)**: ``member_post_id``, ``title``,
  ``description``, ``knowledge_domains``, ``recipes``, ``data_slots``,
  ``allowed_commands``, ``created_at``. Replacing the underlying AI kernel
  NEVER alters ``post:<member_post_id>``.
- **Anti-rigid role binding (`~R` `DomainEmployeeRole`)**: ``agent_kernel``
  (the ``AgentKernel`` currently playing ``DomainEmployeeRole`` on this post),
  ``schedule_ids``, and ``active_session_ids``.

Layer: lower domain store — NEVER imports ``frago.server`` or ``frago.cli``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

VALID_AGENT_KERNELS: tuple[str, ...] = (
    "claude",
    "codex",
    "opencode",
    "gemini",
    "cursor",
    "agy",
    "coreagent",
)

_POST_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

EMPLOYEE_POST_SCHEMA: dict[str, Any] = {
    "filename": "<member_post_id>.json under ~/.frago/employees/ (FRAGO_EMPLOYEES_DIR overrides)",
    "ontological_classes": {
        "rigid_resource": "EmployeePostResource (+R, identity='post:<member_post_id>')",
        "anti_rigid_role": "DomainEmployeeRole (~R, bearer='AgentKernel', context='EmployeePostResource')",
    },
    "fields": [
        {
            "name": "member_post_id",
            "type": "string",
            "required": True,
            "rigidity": "+R",
            "description": "ASCII kebab/snake-case post identifier (e.g. 'jira-guardian').",
        },
        {
            "name": "title",
            "type": "string",
            "required": True,
            "rigidity": "+R",
            "description": "Human-readable post title (e.g. 'Jira 看板与排期专员').",
        },
        {
            "name": "agent_kernel",
            "type": "enum",
            "enum": list(VALID_AGENT_KERNELS),
            "default": "claude",
            "rigidity": "~R",
            "description": "AgentKernel currently playing DomainEmployeeRole on this post.",
        },
        {
            "name": "description",
            "type": "string",
            "default": "",
            "rigidity": "+R",
            "description": "Post charter, responsibilities, and operating boundaries.",
        },
        {
            "name": "work_scope",
            "type": "string",
            "default": "",
            "rigidity": "+R",
            "description": (
                "Generalized working scope and methodology: how this post handles both the "
                "enumerated tasks of its field and any new unenumerated task in the same field."
            ),
        },
        {
            "name": "cwd",
            "type": "string",
            "default": "",
            "rigidity": "+R",
            "description": "Default working directory when a new conversation is started for this post.",
        },
        {
            "name": "knowledge_domains",
            "type": "list[str]",
            "default": [],
            "rigidity": "+R",
            "description": "KnowledgeDomain names governed by this post (frago <domain> find/save).",
        },
        {
            "name": "recipes",
            "type": "list[str]",
            "default": [],
            "rigidity": "+R",
            "description": "RecipeModule names governed by this post.",
        },
        {
            "name": "data_slots",
            "type": "list[str]",
            "default": [],
            "rigidity": "+R",
            "description": "Canonical DataSlot paths governed by this post.",
        },
        {
            "name": "schedule_ids",
            "type": "list[str]",
            "default": [],
            "rigidity": "~R",
            "description": "ScheduleRuleSpec IDs governing this employee role.",
        },
        {
            "name": "active_session_ids",
            "type": "list[str]",
            "default": [],
            "rigidity": "~R",
            "description": "AgentSessionProcess IDs initiated by this employee role.",
        },
        {
            "name": "allowed_commands",
            "type": "list[str]",
            "default": [],
            "rigidity": "+R",
            "description": "CliCommandActionContract command_paths granted to this post.",
        },
        {
            "name": "skills",
            "type": "list[str]",
            "default": [],
            "rigidity": "+R",
            "description": "Default Skill names automatically embedded when starting a session for this post.",
        },
        {
            "name": "created_at",
            "type": "iso-datetime",
            "auto": True,
            "rigidity": "+R",
            "description": "UTC ISO timestamp when the post was established.",
        },
        {
            "name": "updated_at",
            "type": "iso-datetime",
            "auto": True,
            "rigidity": "~R",
            "description": "UTC ISO timestamp when the post or role binding was last updated.",
        },
    ],
}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def frago_home() -> Path:
    """Resolve the frago home directory.

    ``FRAGO_HOME`` 覆写是给测试沙箱用的：巡检要读 ``data/``、``recipes/``、``sessions/``、
    ``books/`` 四处，用例必须能把它们指到一个临时目录去，否则验证一次巡检就等于在真机上
    写一遍。与 :func:`~frago.server.services.data_repo_service.repo_path` 同一个变量名。
    """
    override = os.environ.get("FRAGO_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".frago"


def employees_dir(base_dir: Path | None = None) -> Path:
    """Resolve the employee post storage directory (honours ``FRAGO_EMPLOYEES_DIR``)."""
    if base_dir is not None:
        return base_dir
    env_override = os.environ.get("FRAGO_EMPLOYEES_DIR", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return frago_home() / "employees"


def validate_post_id(member_post_id: str) -> str:
    """Validate that `member_post_id` is a safe ASCII identifier."""
    cleaned = member_post_id.strip()
    if not _POST_ID_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid member_post_id '{member_post_id}': must match {_POST_ID_PATTERN.pattern} (ASCII lowercase letters, digits, '-' or '_')."
        )
    return cleaned


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        val = str(item).strip()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result


@dataclass
class EmployeePostRecord:
    """On-disk representation of an `EmployeePostResource` (+R) and its `DomainEmployeeRole` (~R) binding."""

    member_post_id: str
    title: str
    agent_kernel: str = "claude"
    description: str = ""
    work_scope: str = ""
    cwd: str = ""
    knowledge_domains: list[str] = field(default_factory=list)
    recipes: list[str] = field(default_factory=list)
    data_slots: list[str] = field(default_factory=list)
    schedule_ids: list[str] = field(default_factory=list)
    active_session_ids: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        self.member_post_id = validate_post_id(self.member_post_id)
        self.title = self.title.strip() or self.member_post_id
        self.agent_kernel = self.agent_kernel.strip()
        self.work_scope = self.work_scope.strip()
        self.cwd = self.cwd.strip()
        if self.agent_kernel not in VALID_AGENT_KERNELS:
            raise ValueError(
                f"Invalid agent_kernel '{self.agent_kernel}'; must be one of {VALID_AGENT_KERNELS}."
            )
        self.knowledge_domains = _dedup_preserve_order(self.knowledge_domains)
        self.recipes = _dedup_preserve_order(self.recipes)
        self.data_slots = _dedup_preserve_order(self.data_slots)
        self.schedule_ids = _dedup_preserve_order(self.schedule_ids)
        self.active_session_ids = _dedup_preserve_order(self.active_session_ids)
        self.allowed_commands = _dedup_preserve_order(self.allowed_commands)
        self.skills = _dedup_preserve_order(self.skills)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_projection_dict(self) -> dict[str, Any]:
        """Return the dictionary expected by `frago.ontology.projectors.project_employee_post_dict`."""
        return {
            "member_post_id": self.member_post_id,
            "agent_kernel": self.agent_kernel,
            "knowledge_domains": list(self.knowledge_domains),
            "recipes": list(self.recipes),
            "data_slots": list(self.data_slots),
            "schedule_ids": list(self.schedule_ids),
            "active_session_ids": list(self.active_session_ids),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EmployeePostRecord:
        return cls(
            member_post_id=str(raw.get("member_post_id", "")),
            title=str(raw.get("title", "") or raw.get("member_post_id", "")),
            agent_kernel=str(raw.get("agent_kernel", "claude")),
            description=str(raw.get("description", "")),
            work_scope=str(raw.get("work_scope", "")),
            cwd=str(raw.get("cwd", "")),
            knowledge_domains=list(raw.get("knowledge_domains", [])),
            recipes=list(raw.get("recipes", [])),
            data_slots=list(raw.get("data_slots", [])),
            schedule_ids=list(raw.get("schedule_ids", [])),
            active_session_ids=list(raw.get("active_session_ids", [])),
            allowed_commands=list(raw.get("allowed_commands", [])),
            skills=list(raw.get("skills", [])),
            created_at=str(raw.get("created_at", "") or _now_iso()),
            updated_at=str(raw.get("updated_at", "") or _now_iso()),
        )


def save_post(
    record: EmployeePostRecord,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Atomically persist `record` to `<employees_dir>/<member_post_id>.json`."""
    target_dir = employees_dir(base_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    record.updated_at = _now_iso()
    target_path = target_dir / f"{record.member_post_id}.json"

    fd, tmp_name = tempfile.mkstemp(
        dir=str(target_dir),
        prefix=f".{record.member_post_id}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, target_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return target_path


def get_post(
    member_post_id: str,
    *,
    base_dir: Path | None = None,
) -> EmployeePostRecord | None:
    """Load an `EmployeePostRecord` by `member_post_id`, or return `None` if absent."""
    post_id = validate_post_id(member_post_id)
    target_path = employees_dir(base_dir) / f"{post_id}.json"
    if not target_path.is_file():
        return None
    raw = json.loads(target_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Malformed employee post file: {target_path}")
    return EmployeePostRecord.from_dict(raw)


def list_posts(*, base_dir: Path | None = None) -> list[EmployeePostRecord]:
    """List all persisted `EmployeePostRecord`s sorted by `member_post_id`."""
    target_dir = employees_dir(base_dir)
    if not target_dir.is_dir():
        return []
    records: list[EmployeePostRecord] = []
    for path in sorted(target_dir.glob("*.json")):
        if path.name.startswith("."):
            continue
        # 账本落在同一个目录里、名字以 ``.ledger.yaml`` 结尾，``*.json`` 本来就够不着它。
        # 这一句是给将来留的：谁把账本改成别的后缀，岗位清单也不会被它撑破。
        if path.name.endswith(EMPLOYEE_LEDGER_SUFFIX):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            records.append(EmployeePostRecord.from_dict(raw))
    return records


def delete_post(
    member_post_id: str,
    *,
    base_dir: Path | None = None,
) -> bool:
    """Delete an employee post JSON file. Returns `True` if removed, `False` if not found."""
    post_id = validate_post_id(member_post_id)
    target_path = employees_dir(base_dir) / f"{post_id}.json"
    if not target_path.is_file():
        return False
    target_path.unlink()
    return True


# --- DataSlot territory: reading and archiving what an employee owns under ~/.frago/data ---

_SUMMARY_SOURCE_NAMES: tuple[str, ...] = ("notebook.md", "README.md", "readme.md")

# Enough to cover the front matter and first heading of a note; the whole file is NEVER
# pulled in. A slot may hold gigabytes of deliverables and the caller only needs one line.
_SUMMARY_READ_BYTES = 4096


def _first_heading_line(path: Path) -> str:
    """Return the first non-empty line of `path`, with any leading Markdown heading marks stripped.

    Reads at most ``_SUMMARY_READ_BYTES``: a slot entry's summary is one line, and slurping a
    whole deliverable to find it would make listing a slot cost as much as reading every file.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_SUMMARY_READ_BYTES)
    except OSError:
        return ""
    for line in head.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned
    return ""


def _entry_summary(directory: Path) -> str:
    """Pick the one-line summary of a slot entry: `notebook.md`, then `README.md`, then the first `.md`."""
    for name in _SUMMARY_SOURCE_NAMES:
        candidate = directory / name
        if candidate.is_file():
            summary = _first_heading_line(candidate)
            if summary:
                return summary
    try:
        markdown_files = sorted(
            p for p in directory.glob("*.md") if p.is_file() and not p.name.startswith(".")
        )
    except OSError:
        return ""
    for candidate in markdown_files:
        summary = _first_heading_line(candidate)
        if summary:
            return summary
    return ""


def scan_data_slot_entries(slot_path: str, *, limit: int = 15) -> dict[str, Any]:
    """List what a DataSlot holds, one level deep, newest-looking entry first.

    ``~/.frago/data/<主体>/`` is the shape being read: the slot is the subject container and
    every child is one dated piece of work. Only that one level is walked — nested trees are
    deliverables, not an index, and descending into them turns "what do I own" into a full
    filesystem crawl.

    Names are sorted descending because the transaction directories carry a ``YYYYMMDD-``
    prefix: descending by name IS newest-first. ``limit`` caps ``entries`` only;
    ``total_count`` still reports everything found, so a caller can say "14 in total, here
    are the 12 most recent" instead of silently pretending the rest do not exist.
    """
    requested = str(slot_path).strip()
    resolved = Path(requested).expanduser()
    if not resolved.is_dir():
        return {
            "slot_path": requested,
            "resolved_path": str(resolved),
            "exists": False,
            "total_count": 0,
            "entries": [],
        }

    try:
        children = [
            child
            for child in resolved.iterdir()
            if not child.name.startswith(".")
        ]
    except OSError:
        children = []
    children.sort(key=lambda p: p.name, reverse=True)

    entries: list[dict[str, Any]] = []
    for child in children[: max(limit, 0)]:
        if child.is_dir():
            try:
                file_count = sum(
                    1
                    for item in child.iterdir()
                    if item.is_file() and not item.name.startswith(".")
                )
            except OSError:
                file_count = 0
            summary = _entry_summary(child)
        else:
            file_count = 1
            summary = _first_heading_line(child) if child.suffix.lower() == ".md" else ""
        entries.append(
            {"name": child.name, "summary": summary, "file_count": file_count}
        )

    return {
        "slot_path": requested,
        "resolved_path": str(resolved),
        "exists": True,
        "total_count": len(children),
        "entries": entries,
    }


def create_data_slot_entry(
    slot_path: str,
    folder_name: str,
    *,
    summary: str = "",
) -> dict[str, Any]:
    """Create one archive folder inside a DataSlot and give it a `notebook.md`.

    ``folder_name`` MUST be a single path segment. The caller names the folder (the slot
    naming rule wants a ``YYYYMMDD-`` prefix on it); this function refuses to be talked into
    writing outside the slot, so a name carrying ``/`` or ``..`` is an error rather than a
    quiet escape from the employee's own territory.

    An existing `notebook.md` is kept as-is unless a non-empty ``summary`` is given, in which
    case the title line and summary line are rewritten and the rest of the note is preserved:
    the folder may already hold accumulated notes that this call knows nothing about.
    """
    clean_folder = str(folder_name).strip()
    if not clean_folder:
        raise ValueError("folder_name MUST not be empty.")
    if clean_folder in {".", ".."} or "/" in clean_folder or "\\" in clean_folder:
        raise ValueError(
            f"Invalid folder_name '{folder_name}': MUST be a single path segment without '/' or '..'."
        )

    resolved = Path(str(slot_path).strip()).expanduser()
    target_dir = resolved / clean_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    notebook_path = target_dir / "notebook.md"
    clean_summary = str(summary).strip()
    if not notebook_path.is_file():
        notebook_path.write_text(
            f"# {clean_folder}\n\n{clean_summary}\n" if clean_summary else f"# {clean_folder}\n",
            encoding="utf-8",
        )
    elif clean_summary:
        existing = notebook_path.read_text(encoding="utf-8")
        notebook_path.write_text(
            f"# {clean_folder}\n\n{clean_summary}\n\n{existing.lstrip()}"
            if existing.strip()
            else f"# {clean_folder}\n\n{clean_summary}\n",
            encoding="utf-8",
        )

    return {
        "slot_path": str(slot_path).strip(),
        "resolved_path": str(resolved),
        "folder_name": clean_folder,
        "entry_path": str(target_dir),
        "notebook_path": str(notebook_path),
        "summary": clean_summary,
    }


# --- Employee ledger: the post's own four-column book, kept next to its JSON ---
#
# 员工账本（``~/.frago/employees/<编号>.ledger.yaml``）是岗位资源自带的一个文件槽位，
# 不是一个新本体类：本体层（``frago.json``）里没有它，``EmployeePostResource`` 的字段也
# 没有它。这样做的理由是账本只在「这个员工巡检自己领地」和「这个员工起会话」两处出现，
# 不进图谱、不跨员工共享，为它加一个类只会把本体撑大而换不来任何查询能力。
#
# 账本落在 ``~/.frago/employees/`` 下而不是 ``~/.frago/data/`` 下，位置本身就是防自指：
# 巡检扫数据目录时天然扫不到自己，账本内容不会被自己再记一遍。

EMPLOYEE_LEDGER_SUFFIX = ".ledger.yaml"

#: 巡检自己产生的会话按标题前缀排除，避免「巡检这件事」被记进账本再触发下一轮巡检。
LEDGER_SYNC_SESSION_MARKERS: tuple[str, ...] = (
    "employee-ledger-sync",
    "员工账本巡检",
)

#: 可以被「排除名单」否决的三类资源，与 ``claimed_resources`` 的键一一对应。
#:
#: 会话与事务条目不在其中：那两类是**记录**，说的是「这台机器上发生过什么」，人否决它们
#: 等于要求账本假装某件事没发生过，而账本的价值恰恰在如实记录。能被否决的是**归属**——
#: 这块目录、这个知识域、这张配方算不算我这个岗位管的。会话按首句匹配，误伤面太大，
#: 一次误判就把一整场工作从岗位视野里抹掉，代价远高于它带来的干净。
EXCLUDABLE_RESOURCE_KINDS: tuple[str, ...] = (
    "data_slots",
    "recipes",
    "knowledge_domains",
)

#: 三类资源各自的主键字段，排除名单里存的就是这个字段的值。
RESOURCE_IDENTITY: dict[str, str] = {
    "data_slots": "path",
    "recipes": "name",
    "knowledge_domains": "name",
}


def apply_resource_exclusions(
    ledger: EmployeeLedger,
    *,
    data_slots: Sequence[str] = (),
    recipes: Sequence[str] = (),
    knowledge_domains: Sequence[str] = (),
) -> EmployeeLedger:
    """把人剔除掉的资源记进排除名单，并从账本当前的认领结果里拿掉。

    一次调用做两件事，缺一不可：

    - **记进名单**，否则下一轮巡检按职责词又会把它认领回来，人的这一次删除等于没做；
    - **当场从账本里拿掉**，否则页面保存完再一读，被删的那条还在，人以为自己没删掉。

    只处理被明确点名的条目，不碰其余——「保存」这个动作本身不代表要重扫一遍。
    """
    for kind, values in (
        ("data_slots", data_slots),
        ("recipes", recipes),
        ("knowledge_domains", knowledge_domains),
    ):
        if not values:
            continue
        identity = RESOURCE_IDENTITY[kind]
        excluded = ledger.excluded_resources.setdefault(kind, [])
        for value in values:
            cleaned = str(value).strip()
            if cleaned and cleaned not in excluded:
                excluded.append(cleaned)
        removed = {str(v).strip() for v in values if str(v).strip()}
        ledger.claimed_resources[kind] = [
            item
            for item in ledger.claimed_resources.get(kind, [])
            if str(item.get(identity, "") if isinstance(item, dict) else item).strip()
            not in removed
        ]
    return ledger


def is_resource_excluded(ledger: EmployeeLedger | None, kind: str, value: str) -> bool:
    """这条资源在不在排除名单上。巡检扫描时用它做最后一道筛。

    比对的是字符串本身，不做路径展开：名单里存的是人看到并删掉的那一行原文
    （``~/.frago/data/etf``），而巡检手上的是绝对路径。两种写法都要能对上，
    所以扫描侧传进来时把两种形式都试一遍，这里只管比。
    """
    if ledger is None:
        return False
    cleaned = str(value).strip()
    if not cleaned:
        return False
    return cleaned in (ledger.excluded_resources.get(kind) or [])


def _exclusion_forms(value: str) -> set[str]:
    """同一个资源可能以几种写法出现在名单里，把它们都算成同一个。

    槽位是最麻烦的一类：人从页面上删的时候存进去的是 ``~/.frago/data/etf``，
    而编制里可能写着绝对路径。只按字面比，人重新勾回来这一下就落不到名单上，
    下一次巡检又把它挡在外面——「撤销上次的剔除」成了空操作。
    """
    cleaned = str(value).strip()
    if not cleaned:
        return set()
    home = str(Path.home())
    forms = {cleaned}
    if cleaned.startswith(home):
        forms.add(f"~{cleaned[len(home):]}")
    elif cleaned.startswith("~"):
        forms.add(str(Path(cleaned).expanduser()))
    return forms


def lift_resource_exclusions(
    ledger: EmployeeLedger,
    *,
    data_slots: Sequence[str] = (),
    recipes: Sequence[str] = (),
    knowledge_domains: Sequence[str] = (),
) -> EmployeeLedger:
    """把人重新绑回来的资源从排除名单上撤掉。

    与 :func:`apply_resource_exclusions` 是同一件事的两个方向。少了这一半，人的调整就
    只能单向走：删掉的东西再也回不来——即使他随后在页面上重新勾选，巡检下一轮仍然按
    名单把它挡在外面，页面上刚勾上的那一项又消失了。

    只撤被明确点名的条目。撤了名单不等于当场重新认领：这一轮该资源是否真的归这个岗位，
    由下一次巡检按职责词重新判，这里只负责把「人否决过」这个记忆抹掉。
    """
    for kind, values in (
        ("data_slots", data_slots),
        ("recipes", recipes),
        ("knowledge_domains", knowledge_domains),
    ):
        if not values:
            continue
        wanted: set[str] = set()
        for value in values:
            wanted |= _exclusion_forms(value)
        if not wanted:
            continue
        ledger.excluded_resources[kind] = [
            kept
            for kept in ledger.excluded_resources.get(kind, [])
            if not (_exclusion_forms(kept) & wanted)
        ]
    return ledger


def employee_ledger_path(
    member_post_id: str,
    base_dir: Path | None = None,
) -> Path:
    """Resolve the ledger file of one post: ``<employees_dir>/<member_post_id>.ledger.yaml``."""
    post_id = validate_post_id(member_post_id)
    return employees_dir(base_dir) / f"{post_id}{EMPLOYEE_LEDGER_SUFFIX}"


def is_employee_ledger_path(path: Path | str) -> bool:
    """Whether `path` points at an employee ledger (or lives in the employees directory).

    巡检时的防自指判据之一：``~/.frago/employees/`` 下的任何文件都不是「被巡检的业务
    资源」，而是员工自己的编制与账本。
    """
    candidate = Path(path)
    if candidate.name.endswith(EMPLOYEE_LEDGER_SUFFIX):
        return True
    try:
        return candidate.resolve().parent == employees_dir().resolve()
    except OSError:
        return False


def digest_text(text: str) -> str:
    """Short stable fingerprint of a piece of text (16 hex chars of blake2b)."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def digest_path_entry(directory: Path) -> str:
    """Fingerprint one archive folder by its file names and sizes.

    取文件名与字节数而不是文件内容：事务目录里常放着几十兆的信号表，内容全读一遍会让
    每次巡检都变成一次全量 IO，而这里要回答的只是「自上次记账以来这个目录有没有变过」。
    文件名和体积的组合足以认出新增、改名、重写；真要精确到字节级，那种变化本来也会
    同时改到体积或名字。
    """
    try:
        parts = sorted(
            f"{item.name}:{item.stat().st_size}"
            for item in directory.iterdir()
            if not item.name.startswith(".")
        )
    except OSError:
        return ""
    return digest_text("\n".join(parts))


@dataclass
class LedgerCursor:
    """增量游标：上次记账走到哪，下次从哪继续。

    ``sessions_through`` 一律取会话 ``metadata.json`` 里的 ``started_at`` / ``last_activity``，
    NEVER 用目录 mtime——mtime 会被备份、同步、保活触碰改掉，按它判增量等于按文件的
    指纹判内容有没有变，两边根本不是一回事。
    """

    sessions_through: str = ""
    processed_session_ids: list[str] = field(default_factory=list)
    processed_data_entries: dict[str, str] = field(default_factory=dict)
    recipe_digests: dict[str, str] = field(default_factory=dict)
    domain_digests: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> LedgerCursor:
        data = raw if isinstance(raw, dict) else {}
        return cls(
            sessions_through=str(data.get("sessions_through", "") or ""),
            processed_session_ids=[
                str(x) for x in (data.get("processed_session_ids") or [])
            ],
            processed_data_entries={
                str(k): str(v)
                for k, v in (data.get("processed_data_entries") or {}).items()
            },
            recipe_digests={
                str(k): str(v) for k, v in (data.get("recipe_digests") or {}).items()
            },
            domain_digests={
                str(k): str(v) for k, v in (data.get("domain_digests") or {}).items()
            },
        )


@dataclass
class EmployeeLedger:
    """四栏账本：认领的资源、词汇与隐含语义、意图剧本、活跃事项。

    这四栏对着「新会话第一句话要秒懂什么」逐条排的：``claimed_resources`` 答「手上有
    什么」，``glossary`` 答「用户说的那个词指什么」，``intent_playbooks`` 答「这句话
    通常要我干什么」，``active_topics`` 答「上次停在哪」。

    ``excluded_resources`` 是人否决过的资源，答「巡检别再把这几样算进来」。它必须存在，
    因为巡检的判据是职责词，而职责词匹配天然会有误伤：岗位写着「股票与 ETF」，本机有个
    叫 ``etf-notes`` 的目录其实属于别的岗位，职责词解释不了这种例外，只有人能。人删掉
    一次，巡检下一轮又把它认领回来，这个「删」就等于没做——排除名单就是让人的判断
    压过词面匹配的那一处落点。
    """

    member_post_id: str
    work_scope_anchor: str = ""
    updated_at: str = field(default_factory=_now_iso)
    cursor: LedgerCursor = field(default_factory=LedgerCursor)
    claimed_resources: dict[str, Any] = field(
        default_factory=lambda: {
            "data_slots": [],
            "data_incremental_entries": [],
            "recipes": [],
            "knowledge_domains": [],
            "matched_sessions": [],
        }
    )
    excluded_resources: dict[str, list[str]] = field(default_factory=dict)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    intent_playbooks: list[dict[str, Any]] = field(default_factory=list)
    active_topics: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.member_post_id = validate_post_id(self.member_post_id)
        self.work_scope_anchor = str(self.work_scope_anchor or "").strip()
        if not isinstance(self.cursor, LedgerCursor):
            self.cursor = LedgerCursor.from_dict(self.cursor)
        merged = {
            "data_slots": [],
            "data_incremental_entries": [],
            "recipes": [],
            "knowledge_domains": [],
            "matched_sessions": [],
        }
        raw_resources = (
            self.claimed_resources if isinstance(self.claimed_resources, dict) else {}
        )
        for key, default in merged.items():
            value = raw_resources.get(key, default)
            merged[key] = value if isinstance(value, list) else default
        self.claimed_resources = merged

        raw_excluded = (
            self.excluded_resources if isinstance(self.excluded_resources, dict) else {}
        )
        self.excluded_resources = {
            key: [
                str(x).strip()
                for x in (raw_excluded.get(key) or [])
                if str(x).strip()
            ]
            for key in EXCLUDABLE_RESOURCE_KINDS
        }
        self.glossary = [x for x in self.glossary if isinstance(x, dict)]
        self.intent_playbooks = [
            x for x in self.intent_playbooks if isinstance(x, dict)
        ]
        self.active_topics = [x for x in self.active_topics if isinstance(x, dict)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_post_id": self.member_post_id,
            "work_scope_anchor": self.work_scope_anchor,
            "updated_at": self.updated_at,
            "cursor": asdict(self.cursor),
            "claimed_resources": self.claimed_resources,
            "excluded_resources": self.excluded_resources,
            "glossary": self.glossary,
            "intent_playbooks": self.intent_playbooks,
            "active_topics": self.active_topics,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EmployeeLedger:
        return cls(
            member_post_id=str(raw.get("member_post_id", "")),
            work_scope_anchor=str(raw.get("work_scope_anchor", "") or ""),
            updated_at=str(raw.get("updated_at", "") or _now_iso()),
            cursor=LedgerCursor.from_dict(raw.get("cursor")),
            claimed_resources=raw.get("claimed_resources") or {},
            excluded_resources=raw.get("excluded_resources") or {},
            glossary=list(raw.get("glossary") or []),
            intent_playbooks=list(raw.get("intent_playbooks") or []),
            active_topics=list(raw.get("active_topics") or []),
        )


def load_ledger(
    member_post_id: str,
    *,
    base_dir: Path | None = None,
) -> EmployeeLedger | None:
    """Load a post's ledger, or `None` when it has never been written."""
    path = employee_ledger_path(member_post_id, base_dir)
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    raw.setdefault("member_post_id", member_post_id)
    return EmployeeLedger.from_dict(raw)


def save_ledger(
    ledger: EmployeeLedger,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Atomically persist `ledger` to ``<employees_dir>/<member_post_id>.ledger.yaml``."""
    target_dir = employees_dir(base_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    ledger.updated_at = _now_iso()
    target_path = employee_ledger_path(ledger.member_post_id, base_dir)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(target_dir),
        prefix=f".{ledger.member_post_id}.",
        suffix=".ledger.tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                ledger.to_dict(),
                handle,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
        os.replace(tmp_name, target_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return target_path


def _merge_keyed_entries(
    old_entries: list[dict[str, Any]],
    new_entries: list[dict[str, Any]],
    *,
    key: str,
    merge_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], int, int]:
    """Merge two keyed entry lists, returning `(merged, added, updated)`.

    同名条目不是堆两行而是原地更新：旧账本留着一条「卡在 A 步」、新账本又添一条
    「A 步已完成」，员工起会话时两条都会读进去，得到的结论是自相矛盾的。按主键查重、
    新值覆盖旧值，账本里就永远只有这个条目当前的样子。
    """
    index: dict[str, int] = {}
    merged: list[dict[str, Any]] = []
    for entry in old_entries:
        clean = dict(entry)
        lookup = str(clean.get(key, "")).strip().casefold()
        if not lookup or lookup in index:
            continue
        index[lookup] = len(merged)
        merged.append(clean)

    added = 0
    updated = 0
    for entry in new_entries:
        clean = dict(entry)
        lookup = str(clean.get(key, "")).strip().casefold()
        if not lookup:
            continue
        if lookup not in index:
            index[lookup] = len(merged)
            merged.append(clean)
            added += 1
            continue
        position = index[lookup]
        previous = merged[position]
        if all(previous.get(f) == clean.get(f) for f in merge_fields):
            continue
        # 首次发现时间保留：它答的是「这个词/这件事什么时候进的账本」，与最后一次
        # 更新是两回事，被覆盖掉就再也查不回来了。
        if "first_seen_at" in previous and "first_seen_at" not in clean:
            clean["first_seen_at"] = previous["first_seen_at"]
        merged[position] = clean
        updated += 1
    return merged, added, updated


def _merge_resource_list(
    old_items: list[Any],
    new_items: list[Any],
    *,
    identity: str,
) -> list[Any]:
    """按唯一标识去重合并资源列表，旧值在前、新值覆盖同名项。"""
    merged: list[Any] = []
    index: dict[str, int] = {}
    for item in [*old_items, *new_items]:
        key = (
            str(item.get(identity, "")).strip()
            if isinstance(item, dict)
            else str(item).strip()
        )
        if not key:
            continue
        folded = key.casefold()
        if folded in index:
            merged[index[folded]] = item
            continue
        index[folded] = len(merged)
        merged.append(item)
    return merged


def _later_timestamp(current: str, candidate: str) -> str:
    """两个 ISO 时刻里取靠后的那个；解不动的那一方按「没有」处理。"""
    values = [v for v in (current, candidate) if str(v).strip()]
    if not values:
        return ""
    return max(values, key=lambda v: str(v))


def merge_ledger_entries(
    old_ledger: EmployeeLedger | None,
    delta: EmployeeLedger | dict[str, Any],
    *,
    member_post_id: str | None = None,
) -> tuple[EmployeeLedger, dict[str, int]]:
    """把新提炼出的一批账目合并进老账本，返回 `(合并后的账本, 本次增改计数)`。

    合并的判据是主键，不是「有没有见过」：``glossary`` 按 ``term``、``intent_playbooks``
    按 ``intent``、``active_topics`` 按 ``topic_key``、``claimed_resources`` 各栏按
    ``path`` / ``name`` / ``session_id``。同一主键的新条目原地更新，只有真新出现的才追加。

    游标一起推进：``processed_session_ids`` 取并集，``processed_data_entries`` /
    ``recipe_digests`` / ``domain_digests`` 按名字覆盖，``sessions_through`` 取更晚的那个
    时刻。游标推对了，下一轮巡检才不会把已经记过的资源再记一遍。
    """
    new_ledger = (
        delta
        if isinstance(delta, EmployeeLedger)
        else EmployeeLedger.from_dict(
            {"member_post_id": member_post_id or "", **(delta or {})}
        )
    )
    if old_ledger is None:
        base = EmployeeLedger(
            member_post_id=member_post_id or new_ledger.member_post_id,
        )
    else:
        base = old_ledger
    if member_post_id:
        base.member_post_id = validate_post_id(member_post_id)

    counts = {"glossary_added": 0, "glossary_updated": 0}

    base.glossary, added, updated = _merge_keyed_entries(
        base.glossary,
        new_ledger.glossary,
        key="term",
        merge_fields=("meaning", "mapped_targets"),
    )
    counts["glossary_added"] += added
    counts["glossary_updated"] += updated

    base.intent_playbooks, added, updated = _merge_keyed_entries(
        base.intent_playbooks,
        new_ledger.intent_playbooks,
        key="intent",
        merge_fields=("trigger_phrases", "default_action", "recipes_or_slots"),
    )
    counts["intent_added"] = added
    counts["intent_updated"] = updated

    base.active_topics, added, updated = _merge_keyed_entries(
        base.active_topics,
        new_ledger.active_topics,
        key="topic_key",
        merge_fields=("title", "status", "latest_conclusion", "artifacts"),
    )
    counts["topics_added"] = added
    counts["topics_updated"] = updated

    old_res = base.claimed_resources
    new_res = new_ledger.claimed_resources
    base.claimed_resources = {
        "data_slots": _merge_resource_list(
            old_res.get("data_slots", []),
            new_res.get("data_slots", []),
            identity="path",
        ),
        "data_incremental_entries": _merge_resource_list(
            old_res.get("data_incremental_entries", []),
            new_res.get("data_incremental_entries", []),
            identity="path",
        ),
        "recipes": _merge_resource_list(
            old_res.get("recipes", []),
            new_res.get("recipes", []),
            identity="name",
        ),
        "knowledge_domains": _merge_resource_list(
            old_res.get("knowledge_domains", []),
            new_res.get("knowledge_domains", []),
            identity="name",
        ),
        "matched_sessions": _merge_resource_list(
            old_res.get("matched_sessions", []),
            new_res.get("matched_sessions", []),
            identity="session_id",
        ),
    }

    counts["resources_claimed"] = (
        len(base.claimed_resources["data_incremental_entries"])
        + len(base.claimed_resources["recipes"])
        + len(base.claimed_resources["knowledge_domains"])
        + len(base.claimed_resources["matched_sessions"])
    )

    if new_ledger.work_scope_anchor:
        base.work_scope_anchor = new_ledger.work_scope_anchor

    # 排除名单只增不减：它是人的判断，巡检这一侧产不出「人改主意了」这个信号，
    # 新一轮合并时把新账本里那几栏并进去就够了，绝不覆盖。
    for kind in EXCLUDABLE_RESOURCE_KINDS:
        existing = base.excluded_resources.setdefault(kind, [])
        for value in new_ledger.excluded_resources.get(kind, []):
            if value not in existing:
                existing.append(value)

    cursor = base.cursor
    incoming = new_ledger.cursor
    cursor.sessions_through = _later_timestamp(
        cursor.sessions_through, incoming.sessions_through
    )
    cursor.processed_session_ids = [
        str(x)
        for x in dict.fromkeys(
            [*cursor.processed_session_ids, *incoming.processed_session_ids]
        )
    ]
    cursor.processed_data_entries = {
        **cursor.processed_data_entries,
        **incoming.processed_data_entries,
    }
    cursor.recipe_digests = {**cursor.recipe_digests, **incoming.recipe_digests}
    cursor.domain_digests = {**cursor.domain_digests, **incoming.domain_digests}
    base.updated_at = _now_iso()
    return base, counts


def ledger_summary(ledger: EmployeeLedger) -> dict[str, Any]:
    """账本的一页摘要：给接口和命令行用，不带全量条目正文。

    ``claimed_details`` 是给页面看的逐条明细：人要在详情弹窗里一眼看清「他到底认领到了
    什么、这些东西是干什么用的」，光有几个计数看不出该不该剔除。会话与词条各取前若干条，
    完整清单仍旧走 `frago employee ledger`——页面要的是「够判断」，不是「全量」。

    阈值取 10 / 20 是页面密度决定的：一屏能扫完的量。再多就得滚，滚起来反而没人看。
    """
    return {
        "member_post_id": ledger.member_post_id,
        "updated_at": ledger.updated_at,
        "last_synced_at": ledger.cursor.sessions_through,
        "cursor": {
            "sessions_through": ledger.cursor.sessions_through,
            "processed_session_count": len(ledger.cursor.processed_session_ids),
            "processed_data_entry_count": len(ledger.cursor.processed_data_entries),
            "recipe_digest_count": len(ledger.cursor.recipe_digests),
            "domain_digest_count": len(ledger.cursor.domain_digests),
        },
        "claimed_resources": {
            "data_slots": [
                str(s.get("path", "")) if isinstance(s, dict) else str(s)
                for s in ledger.claimed_resources.get("data_slots", [])
            ],
            "recipe_count": len(ledger.claimed_resources.get("recipes", [])),
            "knowledge_domain_count": len(
                ledger.claimed_resources.get("knowledge_domains", [])
            ),
            "matched_session_count": len(
                ledger.claimed_resources.get("matched_sessions", [])
            ),
        },
        "claimed_details": {
            "data_slots": list(ledger.claimed_resources.get("data_slots", [])),
            "recipes": list(ledger.claimed_resources.get("recipes", [])),
            "knowledge_domains": list(
                ledger.claimed_resources.get("knowledge_domains", [])
            ),
            "matched_sessions": list(
                ledger.claimed_resources.get("matched_sessions", [])
            )[:10],
            "glossary": list(ledger.glossary)[:20],
        },
        "excluded_resources": {
            kind: list(ledger.excluded_resources.get(kind, []))
            for kind in EXCLUDABLE_RESOURCE_KINDS
        },
        "glossary": list(ledger.glossary),
        "intent_playbooks": list(ledger.intent_playbooks),
        "active_topics": list(ledger.active_topics),
    }
